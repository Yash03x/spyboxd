from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPOSITORY_ROOT / "frontend" / "scripts" / "start-production.sh"
RUNTIME_PROOF = REPOSITORY_ROOT / "frontend" / "scripts" / "runtime-proof.cjs"


class ProductionLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        (self.root / "scripts").mkdir()
        (self.root / "node_modules" / "next" / "dist" / "bin").mkdir(
            parents=True
        )
        shutil.copy2(LAUNCHER, self.root / "scripts" / LAUNCHER.name)
        shutil.copy2(RUNTIME_PROOF, self.root / "scripts" / RUNTIME_PROOF.name)
        (self.root / "node_modules" / "next" / "dist" / "bin" / "next").touch()
        self.capture_path = self.root / "arguments.txt"

    def _fake_node(self, path: Path, *, accept_version_probe: bool = True) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        probe_exit = 0 if accept_version_probe else 1
        path.write_text(
            "#!/bin/sh\n"
            f"if [ \"${{1:-}}\" = -e ]; then exit {probe_exit}; fi\n"
            'printf "%s\\n" "$@" >"${SPYBOXD_TEST_CAPTURE}"\n',
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _run(self, *, path: str = "/usr/bin:/bin") -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "NODE_ENV": "production",
                "PATH": path,
                "SPYBOXD_TEST_CAPTURE": str(self.capture_path),
            }
        )
        return subprocess.run(
            [
                "/bin/sh",
                "scripts/start-production.sh",
                "--hostname",
                "127.0.0.1",
                "--port",
                "3100",
            ],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def _assert_production_arguments(self) -> None:
        self.assertEqual(
            self.capture_path.read_text(encoding="utf-8").splitlines(),
            [
                "--require",
                "./scripts/runtime-proof.cjs",
                "./node_modules/next/dist/bin/next",
                "start",
                "--hostname",
                "127.0.0.1",
                "--port",
                "3100",
            ],
        )

    def test_bundled_runtime_always_invokes_next_start(self) -> None:
        self._fake_node(self.root / ".runtime" / "node")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self._assert_production_arguments()

    def test_node_24_fallback_always_invokes_next_start(self) -> None:
        bin_dir = self.root / "bin"
        self._fake_node(bin_dir / "node")
        result = self._run(path=f"{bin_dir}:/usr/bin:/bin")
        self.assertEqual(result.returncode, 0, result.stderr)
        self._assert_production_arguments()

    def test_production_fails_closed_without_a_trusted_runtime(self) -> None:
        bin_dir = self.root / "bin"
        self._fake_node(bin_dir / "node", accept_version_probe=False)
        result = self._run(path=f"{bin_dir}:/usr/bin:/bin")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("trusted Node.js 24", result.stderr)
        self.assertFalse(self.capture_path.exists())


if __name__ == "__main__":
    unittest.main()
