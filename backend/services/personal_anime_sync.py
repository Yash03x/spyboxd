"""Opt-in public MAL reads saved only in the requesting owner's private workspace.

The official public-list API needs an app client ID, not a password or user token.
No deletion or partial fetch replaces the previous snapshot on provider failure.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from uuid import uuid4

from sqlalchemy import or_, update
from database.models import AppUser, PersonalAnimeSync
from services.anime_export import (AnimeImportError, STATUS_LABELS, _date_value,
                                   latest_snapshot, save_snapshot)
from services.anime_metadata import aware
from services.mal_client import MALClient, MALError, MALRequestError

INTERVAL = timedelta(hours=6)
COOLDOWN = timedelta(minutes=10)
LEASE = timedelta(minutes=15)


class SyncUnavailable(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def configured():
    return bool(os.getenv("MAL_CLIENT_ID", "").strip())


def sync_status(db, owner_id):
    state = db.get(PersonalAnimeSync, owner_id)
    now = datetime.now(timezone.utc)
    return {"configured": configured(), "enabled": bool(state and state.enabled),
            "interval_hours": 6,
            "last_attempt_at": state.last_attempt_at.isoformat() if state and state.last_attempt_at else None,
            "last_success_at": state.last_success_at.isoformat() if state and state.last_success_at else None,
            "next_sync_at": state.next_sync_at.isoformat() if state and state.next_sync_at and state.enabled else None,
            "running": bool(state and state.lease_expires_at and aware(state.lease_expires_at) > now),
            "last_error": state.last_error if state else None,
            "username": (snapshot.mal_username if (snapshot := latest_snapshot(db, owner_id)) else None)}


def set_enabled(db, owner, enabled):
    if enabled and not configured():
        raise SyncUnavailable("Add MAL_CLIENT_ID to the API environment before enabling automatic sync.", 503)
    if enabled and not latest_snapshot(db, owner.id):
        raise SyncUnavailable("Import your MAL export first to identify the account to sync.")
    db.query(AppUser).filter_by(id=owner.id).with_for_update().one()
    state = db.get(PersonalAnimeSync, owner.id)
    if state is None:
        state = PersonalAnimeSync(user_id=owner.id)
        db.add(state)
    state.enabled = enabled
    if enabled and not state.next_sync_at:
        state.next_sync_at = datetime.now(timezone.utc)
    if not enabled:
        # Also revoke an in-flight scheduled sync. Its result cannot publish.
        state.lease_token = state.lease_expires_at = None
    db.commit()
    return sync_status(db, owner.id)


def _number(value, label, *, minimum=0, maximum=1_000_000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise MALRequestError(f"MAL returned an invalid {label}; previous snapshot retained")
    return value


def normalize_entries(rows):
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("node"), dict) or not isinstance(row.get("list_status"), dict):
            raise MALRequestError("MAL returned an incomplete entry; previous snapshot retained")
        title, status = row["node"], row["list_status"]
        mal_id = _number(title.get("id"), "title ID", minimum=1, maximum=2_147_483_647)
        if mal_id in seen:
            raise MALRequestError("MAL returned duplicate title IDs; previous snapshot retained")
        seen.add(mal_id)
        name = title.get("title")
        if (not isinstance(name, str) or not name.strip() or len(name) > 500
                or not isinstance(status.get("status"), str) or status["status"] not in STATUS_LABELS):
            raise MALRequestError("MAL returned an invalid title or list status; previous snapshot retained")
        watched = _number(status.get("num_episodes_watched"), "episode progress")
        episodes = _number(title.get("num_episodes", 0), "episode count") or None
        score = _number(status.get("score"), "score", maximum=10) or None
        rewatching = status.get("is_rewatching", False)
        if type(rewatching) is not bool:
            raise MALRequestError("MAL returned an invalid rewatch flag")
        dates = [status.get(key) or "" for key in ("start_date", "finish_date")]
        if any(not isinstance(value, str) or len(value) > 20 for value in dates):
            raise MALRequestError("MAL returned an invalid list date")
        start, sp = _date_value(dates[0])
        finish, fp = _date_value(dates[1])
        issues = []
        if episodes and watched > episodes:
            issues.append("progress_exceeds_total")
        if start and finish and finish < start:
            issues.append("finish_before_start")
        for precision in ("partial", "invalid"):
            if precision in (sp, fp):
                issues.append(f"{precision}_date")
        if title.get("media_type") is not None and not isinstance(title["media_type"], str):
            raise MALRequestError("MAL returned an invalid title format")
        media = {"tv": "TV", "movie": "Movie", "ova": "OVA", "ona": "ONA", "special": "Special",
                 "tv_special": "TV Special", "cm": "CM", "pv": "PV", "music": "Music"}.get(title.get("media_type"), "Unknown")
        result.append({"mal_id": mal_id, "title": name.strip(), "status": status["status"],
                       "media_type": media, "score": score, "episodes": episodes,
                       "episodes_watched": watched, "is_rewatching": rewatching,
                       "started_date": start, "finished_date": finish,
                       "start_raw": dates[0], "finish_raw": dates[1], "start_precision": sp, "finish_precision": fp,
                       "priority": "UNKNOWN", "times_watched_raw": None, "issues": issues})
    return sorted(result, key=lambda row: row["mal_id"])


def sync_owner(db, owner_id, *, client=None, scheduled=False, now=None):
    now = now or datetime.now(timezone.utc)
    if client is None and not configured():
        raise SyncUnavailable("MAL_CLIENT_ID is not configured. Existing imports are unchanged.", 503)
    owner = db.query(AppUser).filter_by(id=owner_id, is_active=True).with_for_update().first()
    if not owner:
        raise SyncUnavailable("This account is unavailable.", 403)
    baseline = latest_snapshot(db, owner_id)
    if not baseline:
        raise SyncUnavailable("Import a MAL export before syncing.")
    baseline_id, username, mal_user_id = baseline.id, baseline.mal_username, baseline.mal_user_id
    state = db.get(PersonalAnimeSync, owner_id)
    if state is None:
        state = PersonalAnimeSync(user_id=owner_id, enabled=False)
        db.add(state)
        db.flush()
    if scheduled and (not state.enabled or (state.next_sync_at and aware(state.next_sync_at) > now)):
        db.rollback()
        return {"skipped": True}
    if ((state.lease_expires_at and aware(state.lease_expires_at) > now)
            or (state.last_attempt_at and aware(state.last_attempt_at) + COOLDOWN > now)):
        db.rollback()
        raise SyncUnavailable("A sync is running or was attempted recently. Please wait ten minutes before retrying.", 429)
    token = uuid4().hex
    state.lease_token, state.lease_expires_at = token, now + LEASE
    state.last_attempt_at, state.next_sync_at = now, now + LEASE
    db.commit()  # No database lock is held during provider requests.
    try:
        entries = normalize_entries((client or MALClient()).fetch_private_list(username))
        if not entries and baseline.payload["entries"]:
            raise MALRequestError("MAL returned an empty list. Import an empty XML export explicitly if you intend to clear it.")
        owner = db.query(AppUser).filter_by(id=owner_id, is_active=True).with_for_update().first()
        db.refresh(state)
        if not owner or state.lease_token != token or aware(state.lease_expires_at) <= datetime.now(timezone.utc):
            raise SyncUnavailable("The sync was cancelled or expired. Existing imports are unchanged.")
        latest = latest_snapshot(db, owner_id)
        if latest.id != baseline_id:
            raise SyncUnavailable("A newer import arrived during sync. It was preserved; retry later.")
        created = False
        if entries != sorted(latest.payload["entries"], key=lambda row: row["mal_id"]):
            canonical = json.dumps(entries, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            # Include the predecessor so a real later reversion can be saved,
            # while identical consecutive successful checks create no duplicates.
            digest = hashlib.sha256(f"MAL API:{baseline_id}:{canonical}".encode()).hexdigest()
            _, created = save_snapshot(db, owner, {"version": 1, "username": username, "mal_user_id": mal_user_id,
                "source": "MAL API", "fetched_at": datetime.now(timezone.utc).isoformat(),
                "entries": entries, "source_hash": digest}, "MAL API sync", commit=False)
        state.last_success_at = datetime.now(timezone.utc)
        state.next_sync_at = state.last_success_at + INTERVAL
        state.last_error = state.lease_token = state.lease_expires_at = None
        db.commit()
        return {"created": created, "message": "MAL list synced privately." if created else "MAL checked: your list is unchanged.", **sync_status(db, owner_id)}
    except (MALError, AnimeImportError, SyncUnavailable):
        db.rollback()
        db.execute(update(PersonalAnimeSync).where(PersonalAnimeSync.user_id == owner_id, PersonalAnimeSync.lease_token == token).values(
            lease_token=None, lease_expires_at=None, next_sync_at=datetime.now(timezone.utc) + timedelta(hours=1),
            last_error="Sync did not complete. Previous snapshots retained. Check MAL access and retry later."))
        db.commit()
        raise


def due_owners(db, *, now=None):
    instant = now or datetime.now(timezone.utc)
    return [row[0] for row in db.query(PersonalAnimeSync.user_id).join(AppUser, AppUser.id == PersonalAnimeSync.user_id).filter(
        AppUser.is_active.is_(True), PersonalAnimeSync.enabled.is_(True),
        or_(PersonalAnimeSync.next_sync_at.is_(None), PersonalAnimeSync.next_sync_at <= instant),
        or_(PersonalAnimeSync.lease_expires_at.is_(None), PersonalAnimeSync.lease_expires_at <= instant)
    ).order_by(PersonalAnimeSync.next_sync_at, PersonalAnimeSync.user_id).limit(20).all()]
