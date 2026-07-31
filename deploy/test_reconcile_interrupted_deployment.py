from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RECONCILE_SCRIPT = REPOSITORY_ROOT / "deploy/reconcile-interrupted-deployment.sh"
HEALTH_VALIDATOR = REPOSITORY_ROOT / "deploy/check-runtime-health.py"
DEPLOY_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/deploy.yml"


class InterruptedDeploymentReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="spyboxd-reconcile-test-")
        self.root = Path(self.temporary.name).resolve()
        self.app_root = self.root / "app"
        self.releases = self.app_root / "releases"
        self.shared = self.app_root / "shared"
        self.state = self.shared / "release-state"
        self.repository = self.app_root / "repository"
        self.bin_dir = self.root / "bin"
        for directory in (self.releases, self.state, self.bin_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.state.chmod(0o750)

        self.source_repository = self.root / "source"
        subprocess.run(
            ["git", "init", "--quiet", "--initial-branch=main", self.source_repository],
            check=True,
        )
        subprocess.run(
            ["git", "-C", self.source_repository, "config", "user.name", "Spyboxd CI"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                self.source_repository,
                "config",
                "user.email",
                "ci@spyboxd.invalid",
            ],
            check=True,
        )
        marker = self.source_repository / "marker"
        marker.write_text("previous\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", self.source_repository, "add", "marker"], check=True
        )
        subprocess.run(
            ["git", "-C", self.source_repository, "commit", "--quiet", "-m", "previous"],
            check=True,
        )
        self.previous_revision = self._git(self.source_repository, "rev-parse", "HEAD")
        marker.write_text("attempted\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", self.source_repository, "commit", "--quiet", "-am", "attempted"],
            check=True,
        )
        self.attempted_revision = self._git(self.source_repository, "rev-parse", "HEAD")
        subprocess.run(
            ["git", "clone", "--quiet", "--bare", self.source_repository, self.repository],
            check=True,
        )

        self.previous_release = self._release(self.previous_revision)
        self.attempted_release = self._release(self.attempted_revision)
        self.current_link = self.app_root / "current"
        self.current_link.symlink_to(self.attempted_release)
        self._write_state(self.previous_revision, self.previous_revision)

        self.curl_trace = self.root / "curl-trace.log"
        self.service_trace = self.root / "service-trace.log"
        self.curl_trace.touch()
        self.service_trace.touch()
        self._install_command_fakes()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _git(repository: Path, *arguments: str) -> str:
        return subprocess.check_output(
            ["git", "-C", repository, *arguments], text=True
        ).strip()

    def _release(self, revision: str) -> Path:
        release = self.releases / revision
        (release / ".venv/bin").mkdir(parents=True)
        (release / "frontend/.next").mkdir(parents=True)
        (release / "frontend/node_modules/next/dist/bin").mkdir(parents=True)
        (release / "frontend/.runtime").mkdir(parents=True)
        (release / "deploy").mkdir(parents=True)
        (release / "REVISION").write_text(f"{revision}\n", encoding="utf-8")
        (release / ".revision-health-v1").touch()
        (release / "frontend/.next/BUILD_ID").write_text("test\n", encoding="utf-8")
        (release / "frontend/node_modules/next/dist/bin/next").touch()
        (release / "frontend/.runtime/LICENSE.nodejs").write_text(
            "test license\n", encoding="utf-8"
        )
        for executable in (
            release / ".venv/bin/uvicorn",
            release / "frontend/.runtime/node",
        ):
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        shutil.copyfile(
            HEALTH_VALIDATOR, release / "deploy/check-runtime-health.py"
        )
        return release

    def _write_state(self, active: str, previous: str | None) -> None:
        for name, value in (("active", active), ("previous", previous)):
            marker = self.state / name
            if value is None:
                marker.unlink(missing_ok=True)
                continue
            marker.write_text(f"{value}\n", encoding="utf-8")
            marker.chmod(0o640)

    def _executable(self, name: str, contents: str) -> None:
        path = self.bin_dir / name
        path.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _install_command_fakes(self) -> None:
        self._executable(
            "flock",
            """
            #!/usr/bin/env bash
            if [[ "${SPYBOXD_TEST_FAIL_LOCK:-0}" == 1 && "${1:-}" == -w ]]; then
              exit 1
            fi
            exit 0
            """,
        )
        self._executable(
            "timeout",
            """
            #!/usr/bin/env bash
            set -Eeuo pipefail
            while [[ "${1:-}" == --* ]]; do shift; done
            shift
            exec "$@"
            """,
        )
        self._executable(
            "sudo",
            """
            #!/usr/bin/env bash
            set -Eeuo pipefail
            printf '%s\n' "$*" >>"${SPYBOXD_TEST_SERVICE_TRACE}"
            if [[ " $* " == *" stop "* && "${SPYBOXD_TEST_FAIL_STOP:-0}" == 1 ]]; then
              exit 1
            fi
            if [[ " $* " == *" restart "* && "${SPYBOXD_TEST_FAIL_RESTART:-0}" == 1 ]]; then
              exit 1
            fi
            exit 0
            """,
        )
        self._executable(
            "sleep",
            """
            #!/usr/bin/env bash
            exit 0
            """,
        )
        self._executable(
            "readlink",
            """
            #!/usr/bin/env bash
            set -Eeuo pipefail
            if [[ "${1:-}" == -f ]]; then
              python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$2"
            else
              /usr/bin/readlink "$@"
            fi
            """,
        )
        self._executable(
            "stat",
            """
            #!/usr/bin/env bash
            set -Eeuo pipefail
            [[ "$1" == -c ]]
            case "$2" in
              %u) python3 -c 'import os,sys; print(os.stat(sys.argv[1], follow_symlinks=False).st_uid)' "$3" ;;
              %a) python3 -c 'import os,stat,sys; print(oct(stat.S_IMODE(os.stat(sys.argv[1], follow_symlinks=False).st_mode))[2:])' "$3" ;;
              *) exit 64 ;;
            esac
            """,
        )
        self._executable(
            "mv",
            """
            #!/usr/bin/env bash
            set -Eeuo pipefail
            if [[ "${1:-}" == -Tf ]]; then
              shift
              [[ "${1:-}" == -- ]] && shift
              [[ "$#" == 2 ]]
              source_path="$1"
              destination_path="$2"
              /bin/rm -f -- "${destination_path}"
              exec /bin/mv -f -- "${source_path}" "${destination_path}"
            fi
            exec /bin/mv "$@"
            """,
        )
        self._executable(
            "curl",
            """
            #!/usr/bin/env bash
            set -Eeuo pipefail
            url="${!#}"
            printf '%s\n' "${url}" >>"${SPYBOXD_TEST_CURL_TRACE}"
            current_release="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${SPYBOXD_CURRENT_LINK}")"
            revision="$(basename "${current_release}")"
            case "${url}" in
              */ready)
                database=ok
                schema=current
                if [[ "${revision}" == "${SPYBOXD_TEST_PREVIOUS_REVISION}" ]]; then
                  schema=pending
                fi
                printf '{"status":"ready","revision":"%s","checks":{"database":"%s","schema":"%s"}}\n' \
                  "${revision}" "${database}" "${schema}"
                ;;
              */health)
                printf '{"status":"ok","revision":"%s"}\n' "${revision}"
                ;;
              */api/public/dashboard)
                if [[ "${revision}" == "${SPYBOXD_TEST_PREVIOUS_REVISION}" \
                    && "${SPYBOXD_TEST_FAIL_PREVIOUS_DASHBOARD:-0}" == 1 ]]; then
                  printf '%s\n' '{"activity_data":"invalid"}'
                else
                  printf '%s\n' '{"activity_data":[],"data_health":{"active_profiles":2,"completed_profiles":2,"last_synced_at":"2026-07-31T00:00:00Z"},"rating_distribution":{},"signal_counts":{"one_day_gap_events":0,"one_day_gap_pair_hits":0,"profiles_analyzed":2,"profiles_with_diary_dates":2,"same_day_events":0,"same_day_pair_hits":0,"shared_titles":1},"system_stats":{"global_avg_rating":3.5,"total_movies_tracked":2,"total_profiles":2,"total_reviews":1},"timestamp":"2026-07-31T00:00:00Z"}'
                fi
                ;;
              *) printf '%s\n' ok ;;
            esac
            """,
        )

    def _run(
        self,
        previous_target: str | None = None,
        *,
        fail_lock: bool = False,
        fail_stop: bool = False,
        fail_restart: bool = False,
        fail_previous_dashboard: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.bin_dir}:{environment['PATH']}",
                "SPYBOXD_APP_ROOT": str(self.app_root),
                "SPYBOXD_REPOSITORY_DIR": str(self.repository),
                "SPYBOXD_RELEASES_DIR": str(self.releases),
                "SPYBOXD_SHARED_DIR": str(self.shared),
                "SPYBOXD_RELEASE_STATE_DIR": str(self.state),
                "SPYBOXD_CURRENT_LINK": str(self.current_link),
                "SPYBOXD_TEST_CURL_TRACE": str(self.curl_trace),
                "SPYBOXD_TEST_SERVICE_TRACE": str(self.service_trace),
                "SPYBOXD_TEST_PREVIOUS_REVISION": self.previous_revision,
                "SPYBOXD_TEST_FAIL_LOCK": "1" if fail_lock else "0",
                "SPYBOXD_TEST_FAIL_STOP": "1" if fail_stop else "0",
                "SPYBOXD_TEST_FAIL_RESTART": "1" if fail_restart else "0",
                "SPYBOXD_TEST_FAIL_PREVIOUS_DASHBOARD": "1"
                if fail_previous_dashboard
                else "0",
            }
        )
        return subprocess.run(
            [
                "bash",
                RECONCILE_SCRIPT,
                self.attempted_revision,
                previous_target or self.previous_revision,
                "false",
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )

    def test_interrupted_healthy_candidate_is_conservatively_rolled_back(self) -> None:
        self._write_state(self.attempted_revision, self.previous_revision)
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.current_link.resolve(), self.previous_release)
        self.assertEqual(
            (self.state / "active").read_text().strip(), self.previous_revision
        )
        self.assertEqual(
            (self.state / "previous").read_text().strip(), self.attempted_revision
        )
        requested = self.curl_trace.read_text(encoding="utf-8").splitlines()
        self.assertTrue(any(url.endswith("/health") for url in requested))
        self.assertTrue(
            any(url.endswith("/api/public/dashboard") for url in requested)
        )
        self.assertFalse(any(url.endswith("/ready") for url in requested))

    def test_failed_candidate_restores_prior_release(self) -> None:
        self._write_state(self.previous_revision, self.previous_revision)
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.current_link.resolve(), self.previous_release)
        self.assertEqual(
            (self.state / "active").read_text().strip(), self.previous_revision
        )
        self.assertFalse((self.state / "previous").exists())

    def test_first_activation_stops_services_and_clears_current_state(self) -> None:
        self._write_state(self.attempted_revision, None)
        result = self._run("none")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.current_link.exists())
        self.assertFalse(self.current_link.is_symlink())
        self.assertFalse((self.state / "active").exists())
        self.assertFalse((self.state / "previous").exists())
        self.assertIn(" systemctl stop ", f" {self.service_trace.read_text()} ")

    def test_first_activation_stop_failure_preserves_current_and_state(self) -> None:
        self._write_state(self.attempted_revision, None)
        result = self._run("none", fail_stop=True)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("failed to stop services", result.stdout)
        self.assertEqual(self.current_link.resolve(), self.attempted_release)
        self.assertEqual(
            (self.state / "active").read_text().strip(), self.attempted_revision
        )

    def test_busy_lock_and_corrupt_state_fail_without_switching_release(self) -> None:
        result = self._run(fail_lock=True)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("did not relinquish", result.stdout)
        self.assertEqual(self.current_link.resolve(), self.attempted_release)

        self.state.chmod(0o700)
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("unsafe ownership or permissions", result.stdout)
        self.assertEqual(self.current_link.resolve(), self.attempted_release)

        self.state.chmod(0o750)
        (self.state / "previous").write_text("corrupt\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("previous release-state marker is invalid", result.stdout)
        self.assertEqual(self.current_link.resolve(), self.attempted_release)

        self._write_state(self.attempted_revision, None)
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("no trustworthy previous marker", result.stdout)
        self.assertEqual(self.current_link.resolve(), self.attempted_release)

    def test_service_restart_failure_restores_attempted_link_and_fails(self) -> None:
        self._write_state(self.attempted_revision, self.previous_revision)
        result = self._run(fail_restart=True)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("directly restored previous release", result.stdout)
        self.assertEqual(self.current_link.resolve(), self.attempted_release)
        service_calls = self.service_trace.read_text(encoding="utf-8")
        self.assertGreaterEqual(service_calls.count("systemctl restart"), 2)

    def test_database_incompatible_previous_restores_healthy_attempted_release(self) -> None:
        self._write_state(self.attempted_revision, self.previous_revision)
        result = self._run(fail_previous_dashboard=True)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("restored the healthy attempted release", result.stdout)
        self.assertEqual(self.current_link.resolve(), self.attempted_release)

    def test_workflow_invokes_the_exact_repository_native_helper(self) -> None:
        workflow = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            '"${release_sha}:deploy/reconcile-interrupted-deployment.sh"', workflow
        )
        self.assertIn(
            '"${release_sha}" "${previous_target}" "${clerk_bridge_mode}"', workflow
        )


if __name__ == "__main__":
    unittest.main()
