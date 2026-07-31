#!/usr/bin/env python3
"""Validate that the healthy frontend process uses the release-bundled Node."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from typing import Any


EXPECTED_KEYS = {
    "format_version",
    "revision",
    "runtime_path",
    "node_sha256",
    "node_version",
    "pid",
    "start_ticks",
    "boot_id",
    "next_entrypoint",
}
MAX_PROOF_BYTES = 8192


class RuntimeProofError(RuntimeError):
    """Raised when the frontend runtime proof cannot be trusted."""


def _read_regular_file(path: Path, *, uid: int, gid: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise RuntimeProofError("runtime proof is unavailable or unsafe") from error

    try:
        identity = os.fstat(descriptor)
        if not stat.S_ISREG(identity.st_mode):
            raise RuntimeProofError("runtime proof must be a regular file")
        if identity.st_uid != uid or identity.st_gid != gid:
            raise RuntimeProofError("runtime proof has an unexpected owner")
        if stat.S_IMODE(identity.st_mode) != 0o640:
            raise RuntimeProofError("runtime proof must use mode 0640")
        chunks: list[bytes] = []
        remaining = MAX_PROOF_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
    finally:
        os.close(descriptor)

    if len(content) > MAX_PROOF_BYTES:
        raise RuntimeProofError("runtime proof is unexpectedly large")
    return content


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _process_start_ticks(stat_text: str) -> str:
    command_end = stat_text.rfind(")")
    if command_end < 0:
        raise RuntimeProofError("frontend process metadata is malformed")
    fields = stat_text[command_end + 2 :].split()
    if len(fields) < 20 or not fields[19].isdigit():
        raise RuntimeProofError("frontend process start time is unavailable")
    return fields[19]


def _load_payload(content: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeProofError("runtime proof is not valid JSON") from error
    if not isinstance(payload, dict) or set(payload) != EXPECTED_KEYS:
        raise RuntimeProofError("runtime proof has an invalid schema")
    return payload


def validate_runtime_proof(
    *,
    proof_path: Path,
    expected_revision: str,
    expected_node_path: Path,
    expected_next_entrypoint: Path,
    runtime_uid: int,
    runtime_gid: int,
    control_group: str,
    proc_root: Path = Path("/proc"),
    cgroup_root: Path = Path("/sys/fs/cgroup"),
    boot_id_path: Path = Path("/proc/sys/kernel/random/boot_id"),
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", expected_revision):
        raise RuntimeProofError("expected release revision is invalid")

    node_path = expected_node_path.resolve(strict=True)
    next_entrypoint = expected_next_entrypoint.resolve(strict=True)
    payload = _load_payload(
        _read_regular_file(proof_path, uid=runtime_uid, gid=runtime_gid)
    )

    if payload["format_version"] != 1:
        raise RuntimeProofError("runtime proof format is unsupported")
    if payload["revision"] != expected_revision:
        raise RuntimeProofError("runtime proof belongs to another release")
    if payload["runtime_path"] != str(node_path):
        raise RuntimeProofError("frontend did not launch through the bundled Node path")
    if payload["next_entrypoint"] != str(next_entrypoint):
        raise RuntimeProofError("frontend launched an unexpected entrypoint")
    if payload["node_sha256"] != _sha256(node_path):
        raise RuntimeProofError("running Node proof does not match the bundled binary")

    version_result = subprocess.run(
        [node_path, "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if payload["node_version"] != version_result.stdout.strip():
        raise RuntimeProofError("running Node version does not match the bundle")

    pid = payload["pid"]
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
        raise RuntimeProofError("runtime proof contains an invalid process ID")
    process_directory = proc_root / str(pid)
    try:
        process_identity = process_directory.stat()
        stat_text = (process_directory / "stat").read_text(encoding="utf-8")
    except OSError as error:
        raise RuntimeProofError("proved frontend process is no longer running") from error
    if process_identity.st_uid != runtime_uid:
        raise RuntimeProofError("proved frontend process has an unexpected owner")
    if payload["start_ticks"] != _process_start_ticks(stat_text):
        raise RuntimeProofError("runtime proof is stale after process ID reuse")

    try:
        current_boot_id = boot_id_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeProofError("system boot identity is unavailable") from error
    if payload["boot_id"] != current_boot_id:
        raise RuntimeProofError("runtime proof is stale after a host reboot")

    group_path = PurePosixPath(control_group)
    if (
        not group_path.is_absolute()
        or ".." in group_path.parts
        or not re.fullmatch(r"/[A-Za-z0-9_.@:/\\-]+", control_group)
    ):
        raise RuntimeProofError("frontend systemd control group is invalid")
    resolved_cgroup_root = cgroup_root.resolve(strict=True)
    try:
        service_cgroup = (
            resolved_cgroup_root / control_group.removeprefix("/")
        ).resolve(strict=True)
    except OSError as error:
        raise RuntimeProofError("frontend systemd control group is unavailable") from error
    if not service_cgroup.is_relative_to(resolved_cgroup_root):
        raise RuntimeProofError("frontend systemd control group escaped its root")
    try:
        process_groups = (process_directory / "cgroup").read_text(
            encoding="utf-8"
        )
    except OSError as error:
        raise RuntimeProofError("frontend process cgroup identity is unavailable") from error
    expected_process_group = f"0::{control_group}"
    if expected_process_group not in process_groups.splitlines():
        raise RuntimeProofError("frontend process reports an unexpected control group")
    try:
        service_pids = {
            int(value)
            for value in (service_cgroup / "cgroup.procs")
            .read_text(encoding="utf-8")
            .splitlines()
            if value.isdigit()
        }
    except OSError as error:
        raise RuntimeProofError("frontend systemd process list is unavailable") from error
    if pid not in service_pids:
        raise RuntimeProofError("proved process does not belong to the frontend service")

    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--node", required=True, type=Path)
    parser.add_argument("--next-entrypoint", required=True, type=Path)
    parser.add_argument("--runtime-uid", required=True, type=int)
    parser.add_argument("--runtime-gid", required=True, type=int)
    parser.add_argument("--control-group", required=True)
    args = parser.parse_args()

    try:
        payload = validate_runtime_proof(
            proof_path=args.proof,
            expected_revision=args.revision,
            expected_node_path=args.node,
            expected_next_entrypoint=args.next_entrypoint,
            runtime_uid=args.runtime_uid,
            runtime_gid=args.runtime_gid,
            control_group=args.control_group,
        )
    except (OSError, subprocess.SubprocessError, RuntimeProofError) as error:
        print(f"frontend runtime proof failed: {error}", file=sys.stderr)
        return 1

    print(
        "frontend runtime proof passed: "
        f"revision={payload['revision']} node={payload['node_version']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
