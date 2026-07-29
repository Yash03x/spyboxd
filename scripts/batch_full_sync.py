#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from local_full_sync import sync_profile


def load_config(config_path: Path) -> Dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_usernames(raw_usernames: List[Any]) -> List[str]:
    usernames: List[str] = []
    seen = set()
    for value in raw_usernames:
        username = str(value).strip()
        if not username or username in seen:
            continue
        usernames.append(username)
        seen.add(username)
    return usernames


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the residential full-sync workflow for every username in a manifest.",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("SPYBOXD_SYNC_CONFIG", "sync-profiles.json"),
        help="Path to the sync config JSON file.",
    )
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="Optional subset of usernames to sync from the config.",
    )

    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        return 1

    try:
        config = load_config(config_path)
    except Exception as exc:
        print(f"Failed to read config: {exc}", file=sys.stderr)
        return 1

    api_base_url = str(config.get("api_base_url") or os.environ.get("SPYBOXD_API_BASE_URL", "")).strip()
    upload_token = os.environ.get("INGESTION_API_TOKEN", "").strip() or None
    bearer_token = os.environ.get("SPYBOXD_BEARER_TOKEN", "").strip() or None
    output_root_raw = str(config.get("output_root", "")).strip()
    pause_seconds = float(config.get("pause_seconds", 2))
    continue_on_error = bool(config.get("continue_on_error", True))
    timeout_seconds = int(config.get("timeout_seconds", 180))

    if not api_base_url:
        print("Set api_base_url in the config or SPYBOXD_API_BASE_URL in the environment.", file=sys.stderr)
        return 1

    if not upload_token and not bearer_token:
        print("Set INGESTION_API_TOKEN or SPYBOXD_BEARER_TOKEN in the environment.", file=sys.stderr)
        return 1

    usernames = normalize_usernames(config.get("usernames", []))
    if args.only:
        requested = {username.strip() for username in args.only if username.strip()}
        usernames = [username for username in usernames if username in requested]

    if not usernames:
        print("No usernames to sync.", file=sys.stderr)
        return 1

    output_root = (config_path.parent / output_root_raw).resolve() if output_root_raw else None
    if output_root is not None:
        output_root.mkdir(parents=True, exist_ok=True)

    failures: List[str] = []

    for index, username in enumerate(usernames, start=1):
        print(f"\n=== [{index}/{len(usernames)}] Syncing @{username} ===")
        try:
            payload = sync_profile(
                username=username,
                api_base_url=api_base_url,
                upload_token=upload_token,
                bearer_token=bearer_token,
                output_dir=str(output_root / username) if output_root is not None else None,
                keep_zip=False,
                timeout_seconds=timeout_seconds,
            )
            print(f"Completed @{username}: {payload}")
        except Exception as exc:
            print(f"Failed @{username}: {exc}", file=sys.stderr)
            failures.append(username)
            if not continue_on_error:
                break

        if index < len(usernames) and pause_seconds > 0:
            time.sleep(pause_seconds)

    if failures:
        print(f"\nFinished with failures: {', '.join(failures)}", file=sys.stderr)
        return 1

    print(f"\nFinished successfully for {len(usernames)} profile(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
