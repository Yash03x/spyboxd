#!/usr/bin/env python3
"""Install and inspect user-level macOS services for localhost Spyboxd.

No root privileges, public listeners, credentials in plists, or shell terminals
are required. PostgreSQL remains managed independently by Homebrew.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("api", "web", "rss")
PREFIX = "com.spyboxd.local"


def service_definitions(root: Path, node: Path, logs: Path) -> dict[str, dict]:
    python = root / ".venv/bin/python"
    commands = {
        "api": [str(python), "-m", "uvicorn", "main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", "8000"],
        "web": [str(node), "--require", "./scripts/runtime-proof.cjs", "./node_modules/next/dist/bin/next", "start", "--hostname", "localhost", "--port", "3000"],
        "rss": [str(python), "-m", "rss_worker"],
    }
    return {
        name: {
            "Label": f"{PREFIX}.{name}",
            "ProgramArguments": command,
            "WorkingDirectory": str(root / "frontend" if name == "web" else root),
            "EnvironmentVariables": {
                "PATH": f"{node.parent}:/opt/homebrew/bin:/usr/bin:/bin",
                "PYTHONPATH": str(root / "backend"),
                "PYTHONUNBUFFERED": "1",
                "NODE_ENV": "production",
                "NEXT_TELEMETRY_DISABLED": "1",
            },
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": 15,
            "ExitTimeOut": 30,
            "Umask": 0o077,
            "StandardOutPath": str(logs / f"{name}.log"),
            "StandardErrorPath": str(logs / f"{name}.error.log"),
        }
        for name, command in commands.items()
    }


def validate_node(node: Path) -> None:
    result = subprocess.run([str(node), "-p", "process.versions.node.split('.')[0]"], capture_output=True, text=True, check=True)
    if result.stdout.strip() != "24":
        raise ValueError("Spyboxd requires a Node.js 24 executable.")


def validate_existing(path: Path, expected: dict) -> None:
    if path.is_symlink():
        raise ValueError(f"Refusing symlinked service definition: {path}")
    if path.exists():
        old = plistlib.loads(path.read_bytes())
        if old.get("Label") != expected["Label"] or old.get("WorkingDirectory") != expected["WorkingDirectory"]:
            raise ValueError(f"A different installation owns {path}; leave it unchanged.")


def launchctl(*args: str, check: bool = True):
    return subprocess.run(["/bin/launchctl", *args], capture_output=True, text=True, check=check)


def bootstrap(domain: str, path: Path):
    # bootout may return before launchd has finished tearing the old job down.
    # A bounded retry handles that race without a terminal-dependent fallback.
    for attempt in range(5):
        result = launchctl("bootstrap", domain, str(path), check=False)
        if result.returncode == 0:
            return
        if attempt < 4:
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"launchd could not load {path.name} (exit {result.returncode}).")


def service_status(name: str, domain: str) -> dict:
    result = launchctl("print", f"{domain}/{PREFIX}.{name}", check=False)
    details = {"loaded": result.returncode == 0}
    # Never dump launchctl's environment (which could contain credentials).
    for line in result.stdout.splitlines():
        key, sep, value = line.strip().partition(" = ")
        if sep and key in {"state", "pid", "last exit code"} and key not in details:
            details[key] = value
    return details


def probe(url: str) -> dict:
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    try:
        with build_opener(NoRedirect()).open(url, timeout=5) as response:
            return {"reachable": True, "http_status": response.status}
    except HTTPError as exc:
        return {"reachable": 200 <= exc.code < 400, "http_status": exc.code}
    except (URLError, TimeoutError, OSError) as exc:
        return {"reachable": False, "error": type(exc).__name__}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "restart", "stop", "uninstall"))
    parser.add_argument("--node", type=Path, help="Node 24 binary to copy into a stable, private runtime directory.")
    parser.add_argument("--only", choices=SERVICES, help="Operate on one service (default: all).")
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        parser.error("This local launcher is macOS-only; use deploy/systemd on Linux.")
    user_home = Path.home()
    agents = user_home / "Library/LaunchAgents"
    logs = user_home / "Library/Logs/Spyboxd"
    runtime = user_home / "Library/Application Support/Spyboxd/runtime/node"
    domain = f"gui/{os.getuid()}"
    names = (args.only,) if args.only else SERVICES
    definitions = service_definitions(ROOT, runtime, logs)
    paths = {name: agents / f"{PREFIX}.{name}.plist" for name in names}

    if args.action == "status":
        states = {name: service_status(name, domain) for name in names}
        web, api = probe("http://localhost:3000/"), probe("http://127.0.0.1:8000/ready")
        print(json.dumps({"services": states, "web": web, "api": api}, indent=2))
        return 0 if all(s.get("state") == "running" for s in states.values()) and web['reachable'] and api['reachable'] else 1

    for name, path in paths.items():
        validate_existing(path, definitions[name])
    if args.action == "install":
        if not (ROOT / ".venv/bin/python").is_file() or not (ROOT / "frontend/.next/BUILD_ID").is_file():
            parser.error("Install the backend environment and build the production frontend first.")
        source_node = args.node.expanduser().resolve() if args.node else runtime
        validate_node(source_node)
        runtime.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if source_node != runtime:
            staged = runtime.with_suffix(".new")
            shutil.copy2(source_node, staged)
            staged.chmod(0o700)
            staged.replace(runtime)
        agents.mkdir(parents=True, exist_ok=True)
        logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        for name, path in paths.items():
            if path.exists():
                shutil.copy2(path, path.with_suffix(f".plist.{stamp}.bak"))
            staged = path.with_suffix(".plist.new")
            staged.write_bytes(plistlib.dumps(definitions[name]))
            staged.chmod(0o600)
            staged.replace(path)
            launchctl("bootout", f"{domain}/{PREFIX}.{name}", check=False)
            launchctl("enable", f"{domain}/{PREFIX}.{name}")
            bootstrap(domain, path)
    elif args.action == "restart":
        for name, path in paths.items():
            if not path.exists():
                parser.error(f"Install {name} first.")
            if not service_status(name, domain)["loaded"]:
                bootstrap(domain, path)
            launchctl("kickstart", "-k", f"{domain}/{PREFIX}.{name}")
    else:
        for name, path in paths.items():
            launchctl("bootout", f"{domain}/{PREFIX}.{name}", check=False)
            if args.action == "uninstall" and path.exists():
                # Recoverable uninstall: keep the exact plist beside its old path.
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                path.rename(path.with_suffix(f".plist.{stamp}.disabled"))
    print(f"{args.action}: {', '.join(names)}. Logs: {logs}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        # Avoid command environments and arbitrary subprocess output in errors.
        print(f"Local service operation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
