from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ROLLBACK_SCRIPT = REPOSITORY_ROOT / "deploy" / "rollback.sh"
HEALTH_VALIDATOR = REPOSITORY_ROOT / "deploy" / "check-runtime-health.py"


@unittest.skipUnless(
    sys.platform.startswith("linux"), "deployment scripts target Linux"
)
class RollbackStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="spyboxd-rollback-test-")
        self.root = Path(self.temporary.name)
        self.app_root = self.root / "app"
        self.releases = self.app_root / "releases"
        self.state = self.app_root / "shared" / "release-state"
        self.repository = self.app_root / "repository"
        self.bin_dir = self.root / "bin"
        self.env_dir = self.root / "env"
        for directory in (self.releases, self.state, self.bin_dir, self.env_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.state.chmod(0o750)

        source_repository = self.root / "source"
        subprocess.run(["git", "init", "--quiet", source_repository], check=True)
        subprocess.run(
            ["git", "-C", source_repository, "config", "user.name", "Spyboxd CI"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                source_repository,
                "config",
                "user.email",
                "ci@spyboxd.invalid",
            ],
            check=True,
        )
        marker = source_repository / "marker"
        marker.write_text("previous\n", encoding="utf-8")
        subprocess.run(["git", "-C", source_repository, "add", "marker"], check=True)
        subprocess.run(
            ["git", "-C", source_repository, "commit", "--quiet", "-m", "previous"],
            check=True,
        )
        self.previous_revision = self._git(source_repository, "rev-parse", "HEAD")
        marker.write_text("current\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", source_repository, "commit", "--quiet", "-am", "current"],
            check=True,
        )
        self.current_revision = self._git(source_repository, "rev-parse", "HEAD")
        subprocess.run(
            ["git", "clone", "--quiet", "--bare", source_repository, self.repository],
            check=True,
        )
        subprocess.run(
            [
                "git",
                f"--git-dir={self.repository}",
                "update-ref",
                "refs/remotes/origin/main",
                self.current_revision,
            ],
            check=True,
        )

        self.current_release = self._release(self.current_revision)
        self.previous_release = self._release(self.previous_revision)
        (self.app_root / "current").symlink_to(self.current_release)
        (self.state / "active").write_text(
            f"{self.current_revision}\n", encoding="utf-8"
        )
        (self.state / "previous").write_text(
            f"{self.previous_revision}\n", encoding="utf-8"
        )
        (self.state / "active").chmod(0o640)
        (self.state / "previous").chmod(0o640)

        self.api_env = self.env_dir / "api.env"
        self.frontend_env = self.env_dir / "frontend.env"
        self.api_env.write_text("TEST_ONLY=1\n", encoding="utf-8")
        self.frontend_env.write_text("TEST_ONLY=1\n", encoding="utf-8")
        self.clerk_validator = self.root / "validate-clerk.py"
        self.clerk_validator.write_text("raise SystemExit(0)\n", encoding="utf-8")
        self.clerk_validator.chmod(0o600)
        self.curl_trace = self.root / "curl-trace.log"
        self.curl_trace.touch()

        self._executable(
            "sudo",
            """
            #!/usr/bin/env bash
            set -Eeuo pipefail
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
            "curl",
            """
            #!/usr/bin/env bash
            set -Eeuo pipefail
            url="${!#}"
            current_release="$(readlink -f "${SPYBOXD_APP_ROOT}/current")"
            revision="$(basename "${current_release}")"
            printf '%s\n' "${url}" >>"${SPYBOXD_TEST_CURL_TRACE}"
            case "${url}" in
              */ready)
                printf '{"status":"not_ready","revision":"%s","checks":{"database":"ok","schema":"pending"}}\n' \
                  "${revision}"
                exit 22
                ;;
              */api/public/dashboard)
                if [[ "${SPYBOXD_TEST_FAIL_TARGET_DASHBOARD:-0}" == 1 \
                    && "${revision}" == "${SPYBOXD_TEST_TARGET_REVISION}" ]]; then
                  printf '%s\n' '{"activity_data": "not-an-array"}'
                else
                  printf '%s\n' '{"activity_data":[],"data_health":{"active_profiles":2,"completed_profiles":2,"last_synced_at":"2026-07-31T00:00:00Z"},"rating_distribution":{},"signal_counts":{"one_day_gap_events":0,"one_day_gap_pair_hits":0,"profiles_analyzed":2,"profiles_with_diary_dates":2,"same_day_events":0,"same_day_pair_hits":0,"shared_titles":1},"system_stats":{"global_avg_rating":3.5,"total_movies_tracked":2,"total_profiles":2,"total_reviews":1},"timestamp":"2026-07-31T00:00:00Z"}'
                fi
                ;;
              */health)
                response_revision="${revision}"
                if [[ "${revision}" == "${SPYBOXD_TEST_TARGET_REVISION}" \
                    && "${SPYBOXD_TEST_FAIL_TARGET_HEALTH:-0}" == 1 ]]; then
                  response_revision="${SPYBOXD_TEST_CURRENT_REVISION}"
                fi
                printf '{"status":"ok","revision":"%s"}\n' "${response_revision}"
                ;;
              *)
                printf '%s\n' 'ok'
                ;;
            esac
            """,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _git(repository: Path, *arguments: str) -> str:
        return subprocess.check_output(
            ["git", "-C", repository, *arguments],
            text=True,
        ).strip()

    def _release(self, revision: str) -> Path:
        release = self.releases / revision
        (release / ".venv" / "bin").mkdir(parents=True)
        (release / "frontend" / ".next").mkdir(parents=True)
        (release / "frontend" / "node_modules" / "next" / "dist" / "bin").mkdir(
            parents=True
        )
        (release / "REVISION").write_text(f"{revision}\n", encoding="utf-8")
        (release / ".revision-health-v1").touch()
        (release / ".spyboxd-release-manifest.json").write_text(
            f'{{"format_version":1,"revision":"{revision}"}}\n',
            encoding="utf-8",
        )
        uvicorn = release / ".venv" / "bin" / "uvicorn"
        uvicorn.touch()
        uvicorn.chmod(0o700)
        (release / "frontend" / ".next" / "BUILD_ID").write_text(
            "test\n", encoding="utf-8"
        )
        (
            release / "frontend" / "node_modules" / "next" / "dist" / "bin" / "next"
        ).touch()
        return release

    def _executable(self, name: str, contents: str) -> None:
        path = self.bin_dir / name
        path.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _run(
        self,
        *,
        fail_target_dashboard: bool = False,
        fail_target_health: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.bin_dir}:{environment['PATH']}",
                "SPYBOXD_APP_ROOT": str(self.app_root),
                "SPYBOXD_REPOSITORY_DIR": str(self.repository),
                "SPYBOXD_RELEASES_DIR": str(self.releases),
                "SPYBOXD_SHARED_DIR": str(self.app_root / "shared"),
                "SPYBOXD_RELEASE_STATE_DIR": str(self.state),
                "SPYBOXD_CURRENT_LINK": str(self.app_root / "current"),
                "SPYBOXD_API_ENV_FILE": str(self.api_env),
                "SPYBOXD_FRONTEND_ENV_FILE": str(self.frontend_env),
                "SPYBOXD_CLERK_VALIDATOR": str(self.clerk_validator),
                "SPYBOXD_HEALTH_VALIDATOR": str(HEALTH_VALIDATOR),
                "SPYBOXD_TEST_TARGET_REVISION": self.previous_revision,
                "SPYBOXD_TEST_CURRENT_REVISION": self.current_revision,
                "SPYBOXD_TEST_CURL_TRACE": str(self.curl_trace),
                "SPYBOXD_TEST_FAIL_TARGET_DASHBOARD": "1"
                if fail_target_dashboard
                else "0",
                "SPYBOXD_TEST_FAIL_TARGET_HEALTH": "1"
                if fail_target_health
                else "0",
            }
        )
        return subprocess.run(
            ["bash", ROLLBACK_SCRIPT, self.previous_revision],
            cwd=REPOSITORY_ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )

    def test_healthy_target_is_activated_and_release_state_is_swapped(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.app_root / "current").resolve(), self.previous_release)
        self.assertEqual(
            (self.state / "active").read_text().strip(), self.previous_revision
        )
        self.assertEqual(
            (self.state / "previous").read_text().strip(), self.current_revision
        )
        requested_urls = self.curl_trace.read_text(encoding="utf-8").splitlines()
        self.assertTrue(any(url.endswith("/health") for url in requested_urls))
        self.assertTrue(
            any(url.endswith("/api/public/dashboard") for url in requested_urls)
        )
        self.assertFalse(any(url.endswith("/ready") for url in requested_urls))

    def test_database_contract_failure_restores_original_release(self) -> None:
        result = self._run(fail_target_dashboard=True)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Rollback health verification failed", result.stdout)
        self.assertIn("Original release", result.stdout)
        self.assertEqual((self.app_root / "current").resolve(), self.current_release)
        self.assertEqual(
            (self.state / "active").read_text().strip(), self.current_revision
        )
        self.assertEqual(
            (self.state / "previous").read_text().strip(), self.previous_revision
        )

    def test_health_revision_failure_restores_original_release(self) -> None:
        result = self._run(fail_target_health=True)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Rollback health verification failed", result.stdout)
        self.assertIn("Original release", result.stdout)
        self.assertEqual((self.app_root / "current").resolve(), self.current_release)
        self.assertEqual(
            (self.state / "active").read_text().strip(), self.current_revision
        )
        requested_urls = self.curl_trace.read_text(encoding="utf-8").splitlines()
        self.assertTrue(any(url.endswith("/health") for url in requested_urls))
        self.assertFalse(any(url.endswith("/ready") for url in requested_urls))

    def test_runtime_aware_target_without_bundled_node_is_rejected(self) -> None:
        (self.previous_release / ".spyboxd-release-manifest.json").write_text(
            f'{{"format_version":2,"revision":"{self.previous_revision}"}}\n',
            encoding="utf-8",
        )
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("missing its self-contained Node.js runtime", result.stdout)
        self.assertEqual((self.app_root / "current").resolve(), self.current_release)


if __name__ == "__main__":
    unittest.main()
