from __future__ import annotations

import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARDEN_RUNNER = (
    "step-security/harden-runner@"
    "bf7454d06d71f1098171f2acdf0cd4708d7b5920"
)


def read_repo_file(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def workflow_concurrency_group(relative_path: str) -> str:
    contents = read_repo_file(relative_path)
    match = re.search(r"(?m)^concurrency:\n(?:^[ ]{2}.*\n)*?^[ ]{2}group: ([^\n]+)$", contents)
    if match is None:
        raise AssertionError(f"No top-level concurrency group in {relative_path}")
    return match.group(1).strip()


def dependabot_block(ecosystem: str, directory: str) -> str:
    contents = read_repo_file(".github/dependabot.yml")
    blocks = re.split(r"(?m)^  - package-ecosystem: ", contents)[1:]
    for block in blocks:
        lines = block.splitlines()
        if lines[0].strip() != ecosystem:
            continue
        if f"    directory: {directory}" in block:
            return block
    raise AssertionError(f"Missing Dependabot block for {ecosystem} {directory}")


class WorkflowControlsTests(unittest.TestCase):
    def test_compose_smoke_is_bounded_disposable_and_semantic(self) -> None:
        ci = read_repo_file(".github/workflows/ci.yml")
        smoke = read_repo_file("deploy/run-compose-smoke.sh")
        override = read_repo_file("deploy/docker-compose.ci.yml")
        dockerignore = read_repo_file(".dockerignore")

        self.assertIn("timeout-minutes: 30", ci)
        self.assertIn("needs: frontend", ci)
        self.assertIn("Download the already-built frontend artifact", ci)
        self.assertIn("path: frontend/.next", ci)
        self.assertIn("bash deploy/run-compose-smoke.sh", ci)
        self.assertIn("deploy/docker-compose.ci.yml", ci)
        self.assertIn(
            '"${runtime_dir}/node" --test '
            "frontend/scripts/run-production-auth-canary.test.mjs",
            ci,
        )
        self.assertIn("--project-name", smoke)
        self.assertIn("build --pull api frontend", smoke)
        self.assertIn("docker build --check -f frontend/Dockerfile .", smoke)
        self.assertIn(
            "up --detach --wait --wait-timeout 180 postgres api frontend",
            smoke,
        )
        self.assertIn("down --volumes --remove-orphans", smoke)
        self.assertIn('report["status"] == "ready"', smoke)
        self.assertIn('"schema": "current"', smoke)
        self.assertIn("SELECT version_num FROM alembic_version", smoke)
        self.assertIn("to_regclass('public.profiles')", smoke)
        self.assertIn("container_frontend_build_id", smoke)
        self.assertIn("unexpectedly started rss-poller", smoke)
        self.assertGreaterEqual(smoke.count("timeout --signal=TERM"), 8)
        self.assertEqual(override.count("container_name: !reset null"), 4)
        self.assertEqual(override.count("ports: !reset []"), 3)
        self.assertIn("dockerfile: Dockerfile.prebuilt", override)
        self.assertIn("**/.env", dockerignore)
        self.assertIn("**/.env.*", dockerignore)

    def test_rollback_does_not_queue_behind_tmdb_enrichment(self) -> None:
        tmdb_group = workflow_concurrency_group(".github/workflows/tmdb-enrichment.yml")
        rollback_group = workflow_concurrency_group(".github/workflows/rollback.yml")
        deploy_group = workflow_concurrency_group(".github/workflows/deploy.yml")
        self.assertEqual(rollback_group, deploy_group)
        self.assertNotEqual(tmdb_group, rollback_group)

        workflow = read_repo_file(".github/workflows/tmdb-enrichment.yml")
        self.assertIn('active_release="$(readlink -f -- "${current_link}")"', workflow)
        self.assertIn(
            'runner_path="${active_release}/deploy/run-tmdb-enrichment.sh"',
            workflow,
        )
        self.assertIn(
            '[ "${active_release}" = "/opt/spyboxd/releases/${active_revision}" ]',
            workflow,
        )
        self.assertIn('environment["SPYBOXD_CURRENT_LINK"] = str(active_release)', workflow)
        self.assertIn('environment["TMDB_ENRICHMENT_LIMIT"] = "50"', workflow)
        self.assertIn('environment["TMDB_ENRICHMENT_BATCH_SIZE"] = "10"', workflow)
        self.assertIn("--kill-after=15s 8m", workflow)

    def test_privileged_jobs_start_with_pinned_harden_runner(self) -> None:
        ci = read_repo_file(".github/workflows/ci.yml")
        release_bundle = ci.split("\n  release_bundle:\n", maxsplit=1)[1]
        dependency_review = read_repo_file(".github/workflows/dependency-review.yml")

        for workflow_job in (release_bundle, dependency_review):
            self.assertIn(HARDEN_RUNNER, workflow_job)
            self.assertIn("egress-policy: audit", workflow_job)
            self.assertLess(
                workflow_job.index(HARDEN_RUNNER),
                workflow_job.index("actions/checkout@"),
            )
        self.assertNotIn("pull-requests: write", dependency_review)
        self.assertNotIn("comment-summary-in-pr", dependency_review)

    def test_deployment_is_an_exact_main_ci_handoff_without_pr_workflow_runs(self) -> None:
        ci = read_repo_file(".github/workflows/ci.yml")
        deployment = read_repo_file(".github/workflows/deploy.yml")

        self.assertIn(
            "cancel-in-progress: ${{ github.event_name == 'pull_request' }}",
            ci,
        )
        self.assertIn("deploy_production:", ci)
        self.assertIn("needs: release_bundle", ci)
        self.assertIn("uses: ./.github/workflows/deploy.yml", ci)
        self.assertIn("release_sha: ${{ github.sha }}", ci)
        self.assertIn("ci_run_id: ${{ github.run_id }}", ci)
        self.assertNotIn("secrets: inherit", ci)
        self.assertIn("workflow_call:", deployment)
        self.assertNotIn("workflow_run:", deployment)
        self.assertIn("environment:\n      name: production", deployment)
        for secret_name in ("VPS_HOST", "VPS_HOST_FINGERPRINT", "VPS_SSH_KEY"):
            self.assertRegex(
                deployment,
                rf"(?m)^      {secret_name}:\n        required: false$",
            )
        self.assertIn('[[ "${CI_RUN_ID}" == "${GITHUB_RUN_ID}" ]]', deployment)
        self.assertIn('[[ "${RELEASE_SHA}" == "${GITHUB_SHA}" ]]', deployment)
        self.assertIn("ref: ${{ inputs.release_sha }}", deployment)
        self.assertIn("run-id: ${{ inputs.ci_run_id }}", deployment)

    def test_dependabot_groups_nonmajor_updates_for_every_runtime_source(self) -> None:
        cases = (
            ("npm", "/frontend", "npm-minor-and-patch"),
            ("pip", "/", "python-minor-and-patch"),
            ("docker-compose", "/", "compose-images-minor-and-patch"),
            ("docker", "/backend", "backend-base-images-minor-and-patch"),
            ("docker", "/frontend", "frontend-base-images-minor-and-patch"),
        )
        for ecosystem, directory, group_name in cases:
            with self.subTest(ecosystem=ecosystem, directory=directory):
                block = dependabot_block(ecosystem, directory)
                self.assertIn(f"      {group_name}:", block)
                self.assertIn('update-types: ["minor", "patch"]', block)
                self.assertNotIn('dependency-name: "*"', block)
                self.assertNotIn('version-update:semver-major', block)


if __name__ == "__main__":
    unittest.main()
