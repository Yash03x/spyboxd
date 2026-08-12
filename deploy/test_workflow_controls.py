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

    def test_database_backed_health_routes_keep_the_api_rate_limit(self) -> None:
        nginx = read_repo_file("deploy/nginx/spyboxd.conf")

        for route in ("/ready", "/health/rss"):
            with self.subTest(route=route):
                location = re.search(
                    rf"(?ms)^    location = {re.escape(route)} \{{\n(.*?)^    \}}",
                    nginx,
                )
                self.assertIsNotNone(location, f"missing exact Nginx location for {route}")
                self.assertIn(
                    "limit_req zone=spyboxd_api_per_ip burst=60 nodelay;",
                    location.group(1),
                )

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


class AuthCanaryDiagnosticsTests(unittest.TestCase):
    """The guardian's reason has to reach the log, or the job is undiagnosable.

    For a fortnight the job reported "The VPS guardian did not publish a canary
    plan" while the guardian had in fact run, failed its preflight, and written
    the reason to its status file. The workflow read that status, took the
    branch for a timeout, and threw the diagnosis away.
    """

    def test_the_guardian_records_why_it_failed(self) -> None:
        guardian = read_repo_file("deploy/run-production-auth-canary.py")

        self.assertIn('status_payload["reason"]', guardian)
        self.assertIn("def lease_failure_reason(", guardian)
        self.assertIn('commands.add_parser("reason")', guardian)
        # Only a message this file wrote: anything else contributes its type,
        # because a traceback can carry DATABASE_URL.
        self.assertIn("if isinstance(reported, AuthCanaryError)", guardian)
        self.assertIn("type(reported).__name__", guardian)

    def test_the_workflow_reports_a_failure_as_a_failure_not_as_a_timeout(self) -> None:
        workflow = read_repo_file(".github/workflows/production-canary.yml")

        self.assertIn("The VPS guardian failed before publishing a plan", workflow)
        self.assertIn("did not publish a canary plan before its deadline", workflow)
        self.assertIn('"${REMOTE_CANARY_PATH}" reason --lease-id', workflow)
        # `set -u` is on and the loop may break on its first iteration.
        self.assertLess(
            workflow.index("guardian_status=running\n          for _ in $(seq 1 60)"),
            workflow.index('"${REMOTE_CANARY_PATH}" reason --lease-id'),
        )

    def test_the_guardian_stderr_stays_closed(self) -> None:
        """The reason travels through the status file, never through a traceback."""

        workflow = read_repo_file(".github/workflows/production-canary.yml")

        self.assertIn("2>/dev/null", workflow)

    def test_the_remote_guardian_heredoc_is_posix_sh(self) -> None:
        """The VPS runs these blocks under /bin/sh, where [[ is not found.

        The fast-death diagnostic used [[ ]] and crashed with exit 127 before
        reporting the guardian's status — replacing the diagnosis at exactly
        the moment one was needed.
        """

        import re

        workflow = read_repo_file(".github/workflows/production-canary.yml")
        blocks = re.findall(r"sh -s --.*?<<'REMOTE'(.*?)\n\s*REMOTE", workflow, re.S)
        self.assertTrue(blocks, "no remote sh heredoc found")
        for block in blocks:
            for line in block.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                self.assertNotIn("[[", stripped, f"bashism in sh heredoc: {stripped}")
        self.assertIn("guardian exited within its startup window", workflow)

    def test_the_canary_reset_is_dispatch_only_dry_run_first_and_posix(self) -> None:
        """A production-row delete must be asked for twice: dispatch, then execute."""

        import re

        workflow = read_repo_file(".github/workflows/canary-reset.yml")
        script = read_repo_file("deploy/run-canary-reset.py")

        self.assertIn("workflow_dispatch", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertIn("default: false", workflow)
        # Same queued concurrency group as the auth canary, so a reset can
        # neither race a live guardian nor be replaced while waiting behind it.
        reset_concurrency = workflow.split("\n    concurrency:\n", maxsplit=1)[1].split(
            "\n    environment:", maxsplit=1
        )[0]
        self.assertIn("group: spyboxd-production-auth-canary", reset_concurrency)
        self.assertIn("queue: max", reset_concurrency)
        self.assertIn("cancel-in-progress: false", reset_concurrency)
        for block in re.findall(r"sh -s --.*?<<'REMOTE'(.*?)\n\s*REMOTE", workflow, re.S):
            for line in block.splitlines():
                if not line.strip().startswith("#"):
                    self.assertNotIn("[[", line, f"bashism in sh heredoc: {line.strip()}")

        # The script's own guarantees: dry run default, admin refusal, and the
        # dry-run transaction is rolled back rather than committed.
        self.assertIn('"--execute", action="store_true"', script)
        self.assertIn("belongs to an administrator; refusing", script)
        self.assertIn("transaction.rollback()", script)
        self.assertIn("DELETE FROM app_users", script)
        self.assertNotIn("DELETE FROM profiles", script)
        self.assertNotIn("DELETE FROM watch_events", script)


class FailureAlertTests(unittest.TestCase):
    """A production failure has to reach somebody.

    The authenticated canary was broken for three days before anyone noticed,
    and a deploy blocked by a fresh npm advisory failed silently on a merge
    whose own PR checks were green. Both landed only in the Actions tab.
    """

    ALERT = ".github/workflows/failure-alert.yml"

    GUARDED = (
        ".github/workflows/ci.yml",
        ".github/workflows/production-canary.yml",
        ".github/workflows/tmdb-enrichment.yml",
        ".github/workflows/postgres-restore-drill.yml",
        ".github/workflows/canary-reset.yml",
        ".github/workflows/panel-sweep.yml",
        ".github/workflows/credits-summary-backfill.yml",
    )

    # Touches production but deliberately does not file an issue, with the
    # reason. An unlisted production workflow fails the enumeration test below,
    # so this stays a decision rather than an omission.
    UNGUARDED = {
        ".github/workflows/rollback.yml": (
            "manual dispatch only; a rollback has a person watching it, and an "
            "issue filed behind their back would arrive after they already knew"
        ),
    }

    def test_no_production_workflow_escapes_this_list(self) -> None:
        """The list above used to be hand-maintained, which is how a new
        production workflow gets written with no alerting and nothing says so.

        Every workflow that claims the production environment must be either
        guarded or explicitly excused.
        """

        production = {
            f".github/workflows/{path.name}"
            for path in sorted(ROOT.glob(".github/workflows/*.yml"))
            if "name: production" in path.read_text(encoding="utf-8")
        }
        classified = set(self.GUARDED) | set(self.UNGUARDED)
        self.assertEqual(
            production - classified,
            set(),
            "these reach production and are neither guarded nor excused",
        )
        self.assertEqual(
            classified - production,
            set(),
            "these are classified but no longer reach production",
        )

    def test_every_workflow_that_guards_production_reports_its_own_failure(self) -> None:
        for relative_path in self.GUARDED:
            contents = read_repo_file(relative_path)
            self.assertIn(
                "uses: ./.github/workflows/failure-alert.yml",
                contents,
                f"{relative_path} never reports a failure to anybody",
            )
            # The name it reports itself under must be its own `name:`, or the
            # issue title splits and a still-broken workflow files a second
            # issue instead of updating the open one.
            declared = contents.splitlines()[0]
            self.assertTrue(declared.startswith("name: "))
            name = declared.removeprefix("name: ").strip()
            self.assertIn(f"workflow: {name}", contents)

    def test_every_alert_covers_all_of_its_workflow_s_jobs(self) -> None:
        for relative_path in self.GUARDED:
            contents = read_repo_file(relative_path)
            jobs = set(re.findall(r"(?m)^  ([A-Za-z0-9_-]+):$", contents.split("\njobs:", 1)[1]))
            jobs.discard("alert_on_failure")
            # Scoped to the alert job: several of these workflows have their
            # own `needs:` earlier in the file, and reading the first one
            # tested a different job's dependencies.
            alert_block = contents.split("\n  alert_on_failure:", 1)
            self.assertEqual(len(alert_block), 2, relative_path)
            needs = re.search(r"(?m)^    needs: \[([^\]]*)\]", alert_block[1])
            self.assertIsNotNone(needs, relative_path)
            watched = {entry.strip() for entry in needs.group(1).split(",") if entry.strip()}
            # A job left out of `needs` is a job whose failure is silent.
            self.assertEqual(
                jobs,
                watched,
                f"{relative_path} does not alert on every one of its jobs",
            )

    def test_only_a_real_failure_raises_an_alert(self) -> None:
        for relative_path in self.GUARDED:
            contents = read_repo_file(relative_path)
            condition = contents.split("\n  alert_on_failure:", 1)[1].split("uses:", 1)[0]
            # A cancelled run is somebody pressing the button and a skipped one
            # is a guard working; alerting on either trains people to ignore
            # these. And a fork's failing pull request must not file issues.
            #
            # Asserted as three properties rather than one literal string: the
            # conditions have earned exceptions -- a deploy that declined a
            # superseded artifact is not a failure -- and pinning the exact
            # text made adding one look like removing the guard.
            for required in (
                "always()",
                "contains(needs.*.result, 'failure')",
                "github.ref == 'refs/heads/main'",
            ):
                self.assertIn(required, condition, f"{relative_path}: {required}")

    def test_a_superseded_deploy_does_not_alert_while_a_broken_one_still_does(self) -> None:
        """Merging several changes quickly makes earlier artifacts stale.

        The deploy job refuses to ship one, which is the guard working, and it
        used to file an issue for it. The exemption is narrow on purpose: it
        applies only when every other job passed, so a deploy that was both
        superseded and broken still alerts.
        """

        contents = read_repo_file(".github/workflows/ci.yml")
        condition = contents.split("\n  alert_on_failure:", 1)[1].split("uses:", 1)[0]

        self.assertIn("needs.deploy_production.outputs.superseded == 'true'", condition)
        self.assertIn("printf 'superseded=true\\n' >>\"${GITHUB_OUTPUT}\"", contents)
        # Every other job must be required green for the exemption to apply.
        for job in ("backend", "frontend", "e2e", "compose", "release_gate", "release_bundle"):
            self.assertIn(f"needs.{job}.result == 'success'", condition, job)

    def test_the_alert_is_called_rather_than_triggered_by_workflow_run(self) -> None:
        """`workflow_run` runs in the base repository's context and is the
        standard shape of a pwn-request; the security audit rejects it."""

        contents = read_repo_file(self.ALERT)
        triggers = re.search(r"(?ms)^on:\n((?:^[ ]{2}.*\n|^\n)*)", contents)
        self.assertIsNotNone(triggers)
        self.assertIn("workflow_call:", triggers.group(1))
        self.assertNotIn("workflow_run", triggers.group(1))

    def test_a_repeat_failure_updates_one_issue_rather_than_filing_another(self) -> None:
        contents = read_repo_file(self.ALERT)
        self.assertIn("issues.createComment", contents)
        self.assertIn("issue.title === title", contents)

    def test_the_alert_can_write_issues_and_nothing_else(self) -> None:
        contents = read_repo_file(self.ALERT)
        job_permissions = re.search(
            r"(?ms)^    permissions:\n((?:^      .*\n)+)", contents
        )
        self.assertIsNotNone(job_permissions)
        granted = dict(
            line.strip().split(": ", 1)
            for line in job_permissions.group(1).splitlines()
            if ": " in line
        )
        self.assertEqual(granted.get("issues"), "write")
        self.assertEqual(granted.get("contents"), "read")
        self.assertNotIn("actions", granted)
        self.assertNotIn("packages", granted)

    def test_the_alert_runs_the_same_hardened_runner_as_everything_else(self) -> None:
        self.assertIn(HARDEN_RUNNER, read_repo_file(self.ALERT))


class RestoreDrillProvisioningTests(unittest.TestCase):
    """The drill has never once run: it needs a credential file the deploy
    account's sudo cannot write, so it failed on the first check every night
    and the schedule skipped without telling anybody."""

    SCRIPT = "deploy/provision-restore-drill.sh"

    def test_the_drill_names_the_script_that_unblocks_it(self) -> None:
        drill = read_repo_file("deploy/postgres_restore_drill.py")
        self.assertIn("deploy/provision-restore-drill.sh", drill)

    def test_the_restore_role_can_create_a_database_but_is_not_a_superuser(self) -> None:
        contents = read_repo_file(self.SCRIPT)
        # The drill refuses a superuser outright, and the application role must
        # stay NOCREATEDB — which is the whole reason for a separate role.
        self.assertIn("CREATEDB NOSUPERUSER", contents)
        self.assertNotIn("SUPERUSER;", contents)

    def test_the_credential_never_reaches_argv(self) -> None:
        contents = read_repo_file(self.SCRIPT)
        # `ps` is world readable; the password goes in on stdin.
        self.assertNotIn("-v password=", contents)
        self.assertIn("\\set password", contents)

    def test_the_file_is_written_with_the_ownership_the_drill_demands(self) -> None:
        contents = read_repo_file(self.SCRIPT)
        self.assertIn("install -o root -g \"${deploy_group}\" -m 0640", contents)
        drill = read_repo_file("deploy/postgres_restore_drill.py")
        self.assertIn("0o640", drill)

    def test_it_refuses_to_run_as_anybody_but_root(self) -> None:
        self.assertIn('[ "$(id -u)" -eq 0 ]', read_repo_file(self.SCRIPT))


class CanaryReleaseGraceTests(unittest.TestCase):
    """A deploy in flight must not page anybody.

    The alignment guard already recognised "production is mid-deploy" as
    benign and set exact_release=false for it. The authenticated phase then
    treated that same benign state as a hard failure, so every fast merge
    filed a "Production Canary is failing" issue that resolved itself minutes
    later. An alert that fires on a self-healing condition is how people learn
    to ignore alerts.
    """

    WORKFLOW = ".github/workflows/production-canary.yml"

    def test_a_deploy_in_flight_is_reported_separately_from_misalignment(self) -> None:
        contents = read_repo_file(self.WORKFLOW)

        # The grace path marks itself, rather than being indistinguishable
        # from every other reason alignment can fail.
        self.assertIn("printf 'release_pending=true\\n' >>\"${GITHUB_OUTPUT}\"", contents)

    def test_the_hard_failure_excludes_the_deploy_in_flight_case(self) -> None:
        contents = read_repo_file(self.WORKFLOW)
        block = contents.split("- name: Require exact release alignment", 1)
        self.assertEqual(len(block), 2, "the fail-closed step is gone")
        condition = block[1].split("run:", 1)[0]

        self.assertIn("exact_release != 'true'", condition)
        self.assertIn("release_pending != 'true'", condition)

    def test_the_authenticated_phase_still_refuses_to_run_mid_deploy(self) -> None:
        """Deferring is not the same as blessing: isolation must never be
        proved against a release nobody asked about."""

        contents = read_repo_file(self.WORKFLOW)
        gate = contents.split("\n  authenticated_canary:", 1)[1].split("runs-on", 1)[0]

        self.assertIn("outputs.exact_release == 'true'", gate)
