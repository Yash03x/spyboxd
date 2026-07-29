#!/usr/bin/env python3
"""Import a completed local Letterboxd scrape directly into the configured database."""

from __future__ import annotations

import argparse
import json
import shutil
import stat
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import AnalyticsRepository, Profile, SessionLocal  # noqa: E402
from scraper_html import validate_username  # noqa: E402
from services.ingestion import unified_data_loader  # noqa: E402
from services.profile_loader import load_profile_data, validate_import_bundle  # noqa: E402
from sqlalchemy import func  # noqa: E402


MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_MEMBER_BYTES = 100 * 1024 * 1024
MAX_MEMBERS = 1_000
ALLOWED_SUFFIXES = {".csv", ".json"}


def _is_zip_symlink(member: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(member.external_attr >> 16)


def _safe_archive_members(archive: zipfile.ZipFile, destination: Path) -> Iterator[tuple[zipfile.ZipInfo, Path]]:
    members = archive.infolist()
    if len(members) > MAX_MEMBERS:
        raise ValueError(f"Archive contains more than {MAX_MEMBERS} entries")

    expanded_size = 0
    destination = destination.resolve()
    for member in members:
        expanded_size += max(int(member.file_size), 0)
        if expanded_size > MAX_EXPANDED_BYTES:
            raise ValueError("Archive expands beyond the 512 MiB safety limit")
        if member.file_size > MAX_MEMBER_BYTES:
            raise ValueError(f"Archive member is too large: {member.filename}")
        if _is_zip_symlink(member):
            raise ValueError(f"Archive contains a symbolic link: {member.filename}")

        member_path = Path(member.filename)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise ValueError(f"Archive contains an unsafe path: {member.filename}")

        target = (destination / member_path).resolve()
        if not target.is_relative_to(destination):
            raise ValueError(f"Archive member escapes extraction directory: {member.filename}")
        if not member.is_dir() and target.suffix.casefold() not in ALLOWED_SUFFIXES:
            raise ValueError(f"Archive contains an unsupported file: {member.filename}")
        yield member, target


def extract_archive(archive_path: Path, destination: Path) -> None:
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Archive exceeds the 100 MiB compressed-size safety limit")

    with zipfile.ZipFile(archive_path) as archive:
        for member, target in _safe_archive_members(archive, destination):
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)


def locate_bundle_root(root: Path) -> Path:
    root = root.resolve()
    direct_manifest = root / "manifest.json"
    if direct_manifest.is_file():
        return root

    candidates = sorted(path.parent for path in root.rglob("manifest.json") if path.is_file())
    if not candidates:
        raise ValueError("No schema-v2 manifest.json was found in the archive")
    if len(candidates) > 1:
        rendered = ", ".join(str(path.relative_to(root)) for path in candidates)
        raise ValueError(f"Archive contains multiple scrape bundles: {rendered}")
    return candidates[0]


def refresh_dashboard_snapshot(db) -> dict:
    """Use the same analytics cache rebuild performed by the HTTP upload path."""
    return AnalyticsRepository(db).refresh_dashboard_analytics_snapshot(
        group_limit=6,
        top_movies_limit=10,
    )


def import_bundle(username: str, bundle_path: Path) -> dict:
    loaded = load_profile_data(str(bundle_path), username)
    validate_import_bundle(loaded, require_full_manifest=True)

    db = SessionLocal()
    try:
        profile = (
            db.query(Profile)
            .filter(func.lower(Profile.username) == username.casefold())
            .one_or_none()
        )
        created = profile is None
        if profile is None:
            profile = Profile(username=username, scraping_status="processing")
            db.add(profile)
            db.flush()
        imported_films = unified_data_loader(loaded, profile.id, db)
        db.refresh(profile)
        coverage = (profile.enhanced_metrics or {}).get("data_coverage", {})
        refresh_dashboard_snapshot(db)
        return {
            "username": profile.username,
            "profile_id": profile.id,
            "created_profile": created,
            "profile_sync_id": profile.last_profile_sync_id,
            "imported_films": imported_films,
            "imported_watch_events": coverage.get("imported_watch_events", 0),
            "is_partial": bool(coverage.get("is_partial", True)),
            "dashboard_snapshot_refreshed": True,
            "source_fingerprint": loaded.source_fingerprint,
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Import a completed schema-v2 scrape directory or ZIP directly into the "
            "PostgreSQL database configured by DATABASE_URL."
        )
    )
    parser.add_argument("username", help="Letterboxd username represented by the scrape")
    parser.add_argument("archive", help="Path to the completed scrape directory or ZIP archive")
    args = parser.parse_args()

    username = args.username.strip()
    if not validate_username(username):
        print("Invalid Letterboxd username.", file=sys.stderr)
        return 2

    source = Path(args.archive).expanduser().resolve()
    if not source.exists():
        print(f"Archive not found: {source}", file=sys.stderr)
        return 2

    try:
        if source.is_dir():
            result = import_bundle(username, locate_bundle_root(source))
        elif source.is_file() and zipfile.is_zipfile(source):
            with tempfile.TemporaryDirectory(prefix="spyboxd-local-import-") as temp_dir:
                extraction_root = Path(temp_dir)
                extract_archive(source, extraction_root)
                result = import_bundle(username, locate_bundle_root(extraction_root))
        else:
            raise ValueError("Archive must be a directory or ZIP file")
    except Exception as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
