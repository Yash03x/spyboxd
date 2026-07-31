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
        self.assertEqual(ci.count("name: frontend-next-${{ github.sha }}"), 3)
        self.assertNotIn(
            "frontend-next-${{ github.sha }}-${{ github.run_attempt }}",
            ci,
        )
        self.assertIn("overwrite: true", ci)
        self.assertIn("bash deploy/run-compose-smoke.sh", ci)
        self.assertIn("deploy/docker-compose.ci.yml", ci)
        install_index = ci.index("npm ci --no-audit --no-fund")
        canary_test_index = ci.index(
            "node --test scripts/run-production-auth-canary.test.mjs"
        )
        self.assertLess(install_index, canary_test_index)
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
        ci = read_repo_file(".github/workflows/ci.yml")
        deployment = ci.split("\n  deploy_production:\n", maxsplit=1)[1]
        self.assertIn(f"      group: {rollback_group}", deployment)
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
        deployment = ci.split("\n  deploy_production:\n", maxsplit=1)[1]
        dependency_review = read_repo_file(".github/workflows/dependency-review.yml")

        for workflow_job in (release_bundle, deployment, dependency_review):
            self.assertIn(HARDEN_RUNNER, workflow_job)
            self.assertIn("egress-policy: audit", workflow_job)
            self.assertLess(
                workflow_job.index(HARDEN_RUNNER),
                workflow_job.index("actions/checkout@"),
            )
        self.assertNotIn("pull-requests: write", dependency_review)
        self.assertNotIn("comment-summary-in-pr", dependency_review)

    def test_deployment_is_an_exact_main_ci_job_without_extra_workflow_runs(self) -> None:
        ci = read_repo_file(".github/workflows/ci.yml")
        deployment = ci.split("\n  deploy_production:\n", maxsplit=1)[1]

        self.assertIn(
            "cancel-in-progress: ${{ github.event_name == 'pull_request' }}",
            ci,
        )
        self.assertIn("deploy_production:", ci)
        self.assertFalse((ROOT / ".github/workflows/deploy.yml").exists())
        self.assertIn("needs: release_bundle", ci)
        self.assertNotIn("uses: ./.github/workflows/deploy.yml", ci)
        self.assertIn("runs-on: ubuntu-24.04", deployment)
        self.assertNotIn("secrets: inherit", ci)
        self.assertIn("environment:\n      name: production", deployment)
        self.assertIn("SSH_HOST: ${{ secrets.VPS_HOST }}", deployment)
        self.assertIn("SSH_FINGERPRINT: ${{ secrets.VPS_HOST_FINGERPRINT }}", deployment)
        self.assertIn("SSH_PRIVATE_KEY: ${{ secrets.VPS_SSH_KEY }}", deployment)
        self.assertIn('[[ "${CI_RUN_ID}" == "${GITHUB_RUN_ID}" ]]', deployment)
        self.assertIn('[[ "${RELEASE_SHA}" == "${GITHUB_SHA}" ]]', deployment)
        self.assertIn("ref: ${{ github.sha }}", deployment)
        self.assertIn("run-id: ${{ github.run_id }}", deployment)

    def test_authenticated_canary_separates_session_handoff_from_private_access(self) -> None:
        workflow = read_repo_file(".github/workflows/production-canary.yml")
        guardian = read_repo_file("deploy/run-production-auth-canary.py")
        browser = read_repo_file("frontend/scripts/run-production-auth-canary.mjs")

        self.assertIn('"https://api.clerk.com/v1/sign_in_tokens"', guardian)
        self.assertIn(
            '"expires_in_seconds": SIGN_IN_TOKEN_DURATION_SECONDS', guardian
        )
        self.assertIn('"https://api.clerk.com/v1/testing_tokens"', guardian)
        self.assertIn('"testing_token": testing_token', guardian)
        self.assertIn("return \"cleanup_failed\"", guardian)
        self.assertIn("setupClerkTestingToken", browser)
        self.assertIn("installClerkTestingToken", browser)
        self.assertIn("::add-mask::${secret}", browser)
        self.assertIn("clerk.client.signIn.create", browser)
        self.assertIn("strategy: 'ticket'", browser)
        self.assertIn("await clerk.setActive", browser)
        self.assertLess(
            browser.index("openClerkCapabilityScope(testingToken, signInTokens)"),
            browser.index("await installClerkTestingToken("),
        )
        self.assertLess(
            browser.index("await consumeSignInTicket("),
            browser.index("await Promise.all(runtimes.map"),
        )
        self.assertLess(
            browser.index("add(testingToken);"),
            browser.index("process.env.CLERK_TESTING_TOKEN = testingToken;"),
        )
        self.assertNotIn("__clerk_testing_token", browser)
        self.assertNotIn("task_url", browser)
        self.assertIn("clerk.session.getToken()", browser)
        self.assertIn("`${taskContract.appOrigin}/profiles`", browser)
        self.assertNotIn("CLERK_SECRET_KEY: ${{", workflow)
        self.assertIn('chmod 0600 "${plan_file}"', workflow)
        self.assertIn('shred --force --iterations=1 --zero --remove -- "${path}"', workflow)
        self.assertIn("timeout --signal=TERM --kill-after=15s 12m", workflow)
        self.assertIn("--plan \"${plan_file}\"", workflow)
        self.assertIn("if (( browser_status == 0 ));", workflow)
        self.assertIn("signal_guardian passed", workflow)
        self.assertIn("--browser-passed", workflow)
        self.assertIn("signal_guardian failed", workflow)
        self.assertIn('>/dev/null 2>&1 || true', workflow)
        self.assertEqual(workflow.count('--expected-revision "${EXPECTED_REVISION}"'), 2)
        self.assertEqual(workflow.count('[[ "${EXPECTED_REVISION}" == "${GITHUB_SHA}" ]]'), 2)
        self.assertIn('"${guardian_status}" == cleanup_failed', workflow)
        self.assertLess(
            workflow.index('"${guardian_status}" == cleanup_failed'),
            workflow.index("if (( browser_status != 0 ));"),
        )

    def test_superseded_release_yields_instead_of_failing(self) -> None:
        ci = read_repo_file(".github/workflows/ci.yml")
        release = read_repo_file("deploy/release.sh")
        reconcile = read_repo_file("deploy/reconcile-interrupted-deployment.sh")

        # A release overtaken on main mid-flight stands down with exit 75; the
        # deploy job records a clean skip instead of a failed activation, and
        # the public verification never probes for a release that yielded.
        self.assertIn("yielding superseded release", release)
        self.assertIn('if [ "${activation_status}" -eq 75 ]; then', ci)
        self.assertIn('echo "superseded=true" >>"${GITHUB_OUTPUT}"', ci)
        self.assertEqual(
            ci.count("if: steps.activate.outputs.superseded != 'true'"), 2
        )
        self.assertIn("Retaining the historical previous-release marker", reconcile)

        # The exit-code mapping must live inside the activation step itself:
        # the workflow has several identical heredoc terminators, and a
        # mapping stranded in a later step leaves the activation step
        # swallowing every failure while the superseded output never gets
        # written, so spurious external-smoke rollbacks fire instead.
        activate_step = ci[
            ci.index("name: Release validated commit to Hetzner")
            : ci.index("name: Reconcile an interrupted or failed activation")
        ]
        reconcile_step = ci[
            ci.index("name: Reconcile an interrupted or failed activation")
            : ci.index("name: Verify public release from GitHub runner")
        ]
        self.assertIn('|| activation_status=$?', activate_step)
        self.assertIn('if [ "${activation_status}" -eq 75 ]; then', activate_step)
        self.assertIn('exit "${activation_status}"', activate_step)
        self.assertNotIn("activation_status", reconcile_step)

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
