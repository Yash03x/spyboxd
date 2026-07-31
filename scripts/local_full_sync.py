#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import requests
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"


def load_local_environment(env_file: Path = REPO_ROOT / ".env") -> None:
    """Load ignored local credentials without overriding the caller's shell."""
    load_dotenv(env_file, override=False)


load_local_environment()

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scraper_html import EnhancedLetterboxdScraper, validate_username  # noqa: E402


def zip_directory(source_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in source_dir.rglob("*"):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(source_dir))


def upload_archive(
    *,
    api_base_url: str,
    zip_path: Path,
    upload_token: str | None,
    bearer_token: str | None,
    timeout_seconds: int,
) -> dict:
    headers = {}
    if upload_token:
        headers["X-Upload-Token"] = upload_token
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    with zip_path.open("rb") as handle:
        response = requests.post(
            f"{api_base_url.rstrip('/')}/upload/",
            files={"files": (zip_path.name, handle, "application/zip")},
            data={"require_full_sync": "true"},
            headers=headers,
            timeout=timeout_seconds,
        )

    try:
        payload = response.json()
    except ValueError:
        payload = {"raw_response": response.text}

    if not response.ok:
        raise RuntimeError(f"Upload failed ({response.status_code}): {payload}")

    return payload


def sync_profile(
    *,
    username: str,
    api_base_url: str,
    upload_token: str | None,
    bearer_token: str | None,
    output_dir: str | None = None,
    keep_zip: bool = False,
    timeout_seconds: int = 180,
) -> dict:
    if not validate_username(username):
        raise ValueError("Invalid username. Use only letters, numbers, underscores, and hyphens.")

    if not upload_token and not bearer_token:
        raise ValueError("Provide either an upload token or a bearer token.")

    if output_dir:
        resolved_output_dir = Path(output_dir).resolve()
        resolved_output_dir.mkdir(parents=True, exist_ok=True)
        temp_context = None
        working_dir = resolved_output_dir
    else:
        temp_context = tempfile.TemporaryDirectory(prefix="spyboxd-local-sync-")
        working_dir = Path(temp_context.name)

    try:
        scrape_dir = working_dir / f"{username}_data"
        zip_path = working_dir / f"{username}.zip"

        print(f"[1/3] Scraping full Letterboxd HTML locally for @{username}...")
        scraper = EnhancedLetterboxdScraper(username, str(scrape_dir), debug=False)
        scraper.scrape_all()

        print(f"[2/3] Packaging {scrape_dir}...")
        zip_directory(scrape_dir, zip_path)

        print(f"[3/3] Uploading {zip_path.name} to {api_base_url.rstrip('/')}...")
        payload = upload_archive(
            api_base_url=api_base_url,
            zip_path=zip_path,
            upload_token=upload_token,
            bearer_token=bearer_token,
            timeout_seconds=timeout_seconds,
        )

        if not keep_zip and zip_path.exists():
            zip_path.unlink()

        return payload
    finally:
        if temp_context is not None:
            temp_context.cleanup()


def main() -> int:
    default_api_base_url = os.environ.get("SPYBOXD_API_BASE_URL")
    default_upload_token = os.environ.get("INGESTION_API_TOKEN")
    default_bearer_token = os.environ.get("SPYBOXD_BEARER_TOKEN")

    parser = argparse.ArgumentParser(
        description=(
            "Run the full HTML scraper on a residential machine, then upload the result "
            "to the Spyboxd API."
        ),
    )
    parser.add_argument("username", help='Letterboxd username, e.g. "gnanendar"')
    parser.add_argument(
        "--api-base-url",
        default=default_api_base_url,
        help="Spyboxd API base URL, e.g. https://api.spyboxd.com",
    )
    parser.add_argument(
        "--upload-token",
        default=default_upload_token,
        help="Value for X-Upload-Token. Recommended for trusted local syncs.",
    )
    parser.add_argument(
        "--bearer-token",
        default=default_bearer_token,
        help="Clerk bearer token. Use this instead of --upload-token if preferred.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional directory to keep the scraped CSV output locally.",
    )
    parser.add_argument(
        "--keep-zip",
        action="store_true",
        help="Keep the generated ZIP archive on disk after upload.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=180,
        help="HTTP timeout for the upload request.",
    )

    args = parser.parse_args()

    if not args.api_base_url:
        print("Provide --api-base-url or set SPYBOXD_API_BASE_URL.", file=sys.stderr)
        return 1

    try:
        payload = sync_profile(
            username=args.username,
            api_base_url=args.api_base_url,
            upload_token=args.upload_token,
            bearer_token=args.bearer_token,
            output_dir=args.output_dir,
            keep_zip=args.keep_zip,
            timeout_seconds=args.timeout_seconds,
        )

        print("Upload completed successfully.")
        print(payload)

        return 0
    except Exception as exc:
        print(f"Sync failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
