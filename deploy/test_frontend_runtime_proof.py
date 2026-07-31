from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name("check-frontend-runtime.py")
SPEC = importlib.util.spec_from_file_location("check_frontend_runtime", MODULE_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class FrontendRuntimeProofTests(unittest.TestCase):
    revision = "a" * 40
    pid = 4242
    start_ticks = "123456"
    boot_id = "11111111-2222-3333-4444-555555555555"
    control_group = "/system.slice/spyboxd-frontend.service"

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.runtime_uid = os.getuid()
        self.runtime_gid = os.getgid()

        self.release = self.root / "release"
        self.node = self.release / "frontend" / ".runtime" / "node"
        self.next_entrypoint = (
            self.release
            / "frontend"
            / "node_modules"
            / "next"
            / "dist"
            / "bin"
            / "next"
        )
        self.node.parent.mkdir(parents=True)
        self.next_entrypoint.parent.mkdir(parents=True)
        self.node.write_text("#!/bin/sh\nprintf 'v24.18.1\\n'\n", encoding="utf-8")
        self.node.chmod(self.node.stat().st_mode | stat.S_IXUSR)
        self.next_entrypoint.write_text("// test entrypoint\n", encoding="utf-8")

        self.proc_root = self.root / "proc"
        process_directory = self.proc_root / str(self.pid)
        process_directory.mkdir(parents=True)
        fields = ["S", *("0" for _ in range(18)), self.start_ticks]
        (process_directory / "stat").write_text(
            f"{self.pid} (next-server (v16.2.12)) {' '.join(fields)}\n",
            encoding="utf-8",
        )
        (process_directory / "cgroup").write_text(
            f"0::{self.control_group}\n", encoding="utf-8"
        )
        self.boot_id_path = self.proc_root / "sys" / "kernel" / "random" / "boot_id"
        self.boot_id_path.parent.mkdir(parents=True)
        self.boot_id_path.write_text(f"{self.boot_id}\n", encoding="utf-8")

        self.cgroup_root = self.root / "cgroup"
        service_group = self.cgroup_root / self.control_group.removeprefix("/")
        service_group.mkdir(parents=True)
        (service_group / "cgroup.procs").write_text(
            f"100\n{self.pid}\n", encoding="utf-8"
        )

        self.proof = self.root / "runtime-proof.json"
        self.payload = {
            "format_version": 1,
            "revision": self.revision,
            "runtime_path": str(self.node.resolve()),
            "node_sha256": hashlib.sha256(self.node.read_bytes()).hexdigest(),
            "node_version": "v24.18.1",
            "pid": self.pid,
            "start_ticks": self.start_ticks,
            "boot_id": self.boot_id,
            "next_entrypoint": str(self.next_entrypoint.resolve()),
        }
        self._write_proof()

    def _write_proof(self) -> None:
        self.proof.write_text(json.dumps(self.payload), encoding="utf-8")
        self.proof.chmod(0o640)

    def _validate(self) -> dict[str, object]:
        return VALIDATOR.validate_runtime_proof(
            proof_path=self.proof,
            expected_revision=self.revision,
            expected_node_path=self.node,
            expected_next_entrypoint=self.next_entrypoint,
            runtime_uid=self.runtime_uid,
            runtime_gid=self.runtime_gid,
            control_group=self.control_group,
            proc_root=self.proc_root,
            cgroup_root=self.cgroup_root,
            boot_id_path=self.boot_id_path,
        )

    def test_accepts_exact_live_process_in_frontend_cgroup(self) -> None:
        self.assertEqual(self._validate()["revision"], self.revision)

    def test_rejects_runtime_binary_mismatch(self) -> None:
        self.payload["node_sha256"] = "0" * 64
        self._write_proof()
        with self.assertRaisesRegex(
            VALIDATOR.RuntimeProofError, "does not match the bundled binary"
        ):
            self._validate()

    def test_rejects_stale_process_start_time(self) -> None:
        self.payload["start_ticks"] = "999"
        self._write_proof()
        with self.assertRaisesRegex(VALIDATOR.RuntimeProofError, "process ID reuse"):
            self._validate()

    def test_rejects_proof_from_another_release(self) -> None:
        self.payload["revision"] = "b" * 40
        self._write_proof()
        with self.assertRaisesRegex(VALIDATOR.RuntimeProofError, "another release"):
            self._validate()

    def test_rejects_proof_from_another_boot(self) -> None:
        self.payload["boot_id"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        self._write_proof()
        with self.assertRaisesRegex(VALIDATOR.RuntimeProofError, "host reboot"):
            self._validate()

    def test_rejects_process_reported_cgroup_mismatch(self) -> None:
        process_directory = self.proc_root / str(self.pid)
        (process_directory / "cgroup").write_text(
            "0::/system.slice/unrelated.service\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(
            VALIDATOR.RuntimeProofError, "reports an unexpected control group"
        ):
            self._validate()

    def test_rejects_process_outside_frontend_cgroup(self) -> None:
        service_group = self.cgroup_root / self.control_group.removeprefix("/")
        (service_group / "cgroup.procs").write_text("100\n", encoding="utf-8")
        with self.assertRaisesRegex(
            VALIDATOR.RuntimeProofError, "does not belong to the frontend service"
        ):
            self._validate()

    def test_rejects_group_traversal(self) -> None:
        with self.assertRaisesRegex(
            VALIDATOR.RuntimeProofError, "control group is invalid"
        ):
            VALIDATOR.validate_runtime_proof(
                proof_path=self.proof,
                expected_revision=self.revision,
                expected_node_path=self.node,
                expected_next_entrypoint=self.next_entrypoint,
                runtime_uid=self.runtime_uid,
                runtime_gid=self.runtime_gid,
                control_group="/system.slice/../escape",
                proc_root=self.proc_root,
                cgroup_root=self.cgroup_root,
                boot_id_path=self.boot_id_path,
            )

    def test_rejects_permissive_proof_mode(self) -> None:
        self.proof.chmod(0o644)
        with self.assertRaisesRegex(VALIDATOR.RuntimeProofError, "mode 0640"):
            self._validate()


if __name__ == "__main__":
    unittest.main()
