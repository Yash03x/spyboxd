"""Bounded MAL XML import and descriptive insights, without network enrichment.

Grain is one list entry per MAL title, not an episode event or a franchise.
Zero scores and absent/partial dates never become measured values. Original
date strings survive for inspection; comments and other private notes do not.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import gzip
import hashlib
import io
import re
from statistics import mean, median
import xml.etree.ElementTree as ET
import zlib

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import AppUser, PersonalAnimeImport

MAX_UPLOAD_BYTES = 4 * 1024 * 1024
MAX_XML_BYTES = 12 * 1024 * 1024
MAX_ENTRIES = 20000
STATUS_LABELS = {
    "watching": "Watching", "completed": "Completed", "on_hold": "On hold",
    "dropped": "Dropped", "plan_to_watch": "Plan to watch",
}
XML_STATUSES = {
    "Watching": "watching", "Completed": "completed", "On-Hold": "on_hold",
    "Dropped": "dropped", "Plan to Watch": "plan_to_watch",
}
HEADER_COUNTS = {
    "user_total_watching": "watching", "user_total_completed": "completed",
    "user_total_onhold": "on_hold", "user_total_dropped": "dropped",
    "user_total_plantowatch": "plan_to_watch",
}


class AnimeImportError(ValueError):
    pass


class _SafeTreeBuilder(ET.TreeBuilder):
    def doctype(self, *_):
        # Parser-level rejection also covers UTF-16 and obfuscated byte encodings.
        raise AnimeImportError("XML document types and entities are not allowed.")


def _integer(value: str, field: str, *, maximum=1_000_000, minimum=0) -> int:
    if not re.fullmatch(r"[0-9]{1,12}", value):
        raise AnimeImportError(f"Invalid {field}: expected a non-negative integer.")
    number = int(value)
    if not minimum <= number <= maximum:
        raise AnimeImportError(f"Invalid {field}: value is out of range.")
    return number


def _date_value(raw: str) -> tuple[str | None, str]:
    if not raw or raw == "0000-00-00":
        return None, "missing"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            return date.fromisoformat(raw).isoformat(), "full"
        except ValueError:
            pass
    # Validate genuine partial dates, keeping their precision rather than guessing.
    match = re.fullmatch(r"([1-9]\d{3})(?:-(\d{2})(?:-(\d{2}))?)?", raw)
    if match:
        month, day = match.group(2), match.group(3)
        if month is None or (month == "00" and day in (None, "00")):
            return None, "partial"
        if 1 <= int(month) <= 12 and day in (None, "00"):
            return None, "partial"
    return None, "invalid"


def parse_export(content: bytes) -> dict:
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise AnimeImportError("Choose a non-empty MAL .xml or .xml.gz export up to 4 MiB.")
    if content.startswith(b"\x1f\x8b"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(content)) as stream:
                raw = stream.read(MAX_XML_BYTES + 1)
        except (OSError, EOFError, zlib.error) as exc:
            raise AnimeImportError("The gzip export is damaged or incomplete.") from exc
    else:
        raw = content
    if len(raw) > MAX_XML_BYTES:
        raise AnimeImportError("The decompressed export exceeds 12 MiB.")
    try:
        root = ET.fromstring(raw, parser=ET.XMLParser(target=_SafeTreeBuilder()))
    except ET.ParseError as exc:
        raise AnimeImportError("The file is not a complete, valid MAL XML export.") from exc
    if root.tag != "myanimelist" or len(root.findall("myinfo")) != 1:
        raise AnimeImportError("Expected a MAL anime export with one myinfo header.")
    info = root.find("myinfo")
    assert info is not None
    if len([child.tag for child in info]) != len({child.tag for child in info}):
        raise AnimeImportError("The export header contains repeated fields.")
    if info.findtext("user_export_type", "").strip() != "1" or root.findall("manga"):
        raise AnimeImportError("This section accepts anime exports, not manga exports.")
    username = info.findtext("user_name", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", username):
        raise AnimeImportError("The export is missing a valid MAL username.")
    user_id = _integer(info.findtext("user_id", "").strip(), "MAL user ID", minimum=1, maximum=9_999_999_999)
    nodes = root.findall("anime")
    if len(nodes) > MAX_ENTRIES:
        raise AnimeImportError("This export exceeds the 20,000-title limit.")
    entries, seen = [], set()
    for node in nodes:
        keys = [child.tag for child in node]
        if len(keys) != len(set(keys)):
            raise AnimeImportError("An anime entry contains repeated fields.")
        def field(key):
            return node.findtext(key, "").strip()
        mal_id = _integer(field("series_animedb_id"), "anime ID", minimum=1, maximum=2_147_483_647)
        if mal_id in seen:
            raise AnimeImportError(f"Duplicate MAL title ID {mal_id}; nothing was imported.")
        seen.add(mal_id)
        title = field("series_title")
        if not title or len(title) > 500:
            raise AnimeImportError("Every anime needs a title of at most 500 characters.")
        status = XML_STATUSES.get(field("my_status"))
        if status is None:
            raise AnimeImportError(f"Unsupported list status for MAL title {mal_id}.")
        media_type = field("series_type") or "Unknown"
        if len(media_type) > 32:
            raise AnimeImportError("The anime format name is too long.")
        score = _integer(field("my_score"), "score", maximum=10) or None
        total = _integer(field("series_episodes"), "total episodes") or None
        watched = _integer(field("my_watched_episodes"), "watched episodes")
        start_raw, finish_raw = field("my_start_date"), field("my_finish_date")
        if len(start_raw) > 20 or len(finish_raw) > 20:
            raise AnimeImportError("An anime date is too long.")
        started, start_precision = _date_value(start_raw)
        finished, finish_precision = _date_value(finish_raw)
        issues = []
        if total is not None and watched > total:
            issues.append("progress_exceeds_total")
        if started and finished and finished < started:
            issues.append("finish_before_start")
        if "invalid" in (start_precision, finish_precision):
            issues.append("invalid_date")
        if "partial" in (start_precision, finish_precision):
            issues.append("partial_date")
        priority = field("my_priority") or "LOW"
        if priority not in {"LOW", "MEDIUM", "HIGH"}:
            priority = "UNKNOWN"
        entries.append({
            "mal_id": mal_id, "title": title, "media_type": media_type, "status": status,
            "score": score, "episodes": total, "episodes_watched": watched,
            "started_date": started, "finished_date": finished,
            "start_raw": start_raw, "finish_raw": finish_raw,
            "start_precision": start_precision, "finish_precision": finish_precision,
            "priority": priority,
            "times_watched_raw": _integer(field("my_times_watched") or "0", "times watched"),
            "is_rewatching": _integer(field("my_rewatching") or "0", "rewatching flag", maximum=1) == 1,
            "issues": issues,
        })
    expected = _integer(info.findtext("user_total_anime", "").strip(), "header total", maximum=MAX_ENTRIES)
    if expected != len(entries):
        raise AnimeImportError("Header title count does not match the export; nothing was imported.")
    counts = Counter(row["status"] for row in entries)
    for key, status in HEADER_COUNTS.items():
        value = info.findtext(key)
        if value is not None and _integer(value.strip(), key, maximum=MAX_ENTRIES) != counts[status]:
            raise AnimeImportError("Header status counts do not match the entries; nothing was imported.")
    return {"version": 1, "username": username, "mal_user_id": user_id,
            "entries": entries, "source_hash": hashlib.sha256(raw).hexdigest()}


def import_snapshot(db: Session, owner: AppUser, content: bytes, filename: str) -> tuple[PersonalAnimeImport, bool]:
    parsed = parse_export(content)  # Validate the entire export before any write.
    # Serialize imports for one account. Concurrent duplicates cannot race a
    # different account into the same private workspace.
    db.query(AppUser).filter(AppUser.id == owner.id).with_for_update().one()
    latest = latest_snapshot(db, owner.id)
    if latest and latest.mal_user_id != parsed["mal_user_id"]:
        raise AnimeImportError("This workspace already belongs to another MAL account. Use the same account's export.")
    existing = db.query(PersonalAnimeImport).filter_by(user_id=owner.id, source_hash=parsed["source_hash"]).first()
    if existing:
        db.rollback()
        return existing, False
    snapshot = PersonalAnimeImport(
        user_id=owner.id, source_hash=parsed.pop("source_hash"),
        filename=re.split(r"[/\\]", filename)[-1][:255] or "animelist.xml",
        mal_username=parsed["username"], mal_user_id=parsed["mal_user_id"], payload=parsed,
    )
    db.add(snapshot)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AnimeImportError("An import conflicted with another request. Refresh and try again.") from None
    db.refresh(snapshot)
    return snapshot, True


def latest_snapshot(db: Session, owner_id: int):
    return db.query(PersonalAnimeImport).filter_by(user_id=owner_id).order_by(PersonalAnimeImport.id.desc()).first()


def summarize(entries: list[dict], *, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    cutoff = today.isoformat()
    scores = [row["score"] for row in entries if row["score"] is not None]
    completed = [row for row in entries if row["status"] == "completed"]
    dated = [row for row in completed if row["finished_date"] and row["finished_date"] <= cutoff]
    dated_starts = [row for row in entries if row["started_date"] and row["started_date"] <= cutoff]
    durations = [(date.fromisoformat(row["finished_date"]) - date.fromisoformat(row["started_date"])).days
                 for row in dated if row["started_date"] and row["started_date"] <= row["finished_date"]]
    by_status = Counter(row["status"] for row in entries)
    by_score = Counter(scores)
    formats = defaultdict(list)
    years, months = defaultdict(lambda: {"started": 0, "completed": 0}), defaultdict(lambda: {"started": 0, "completed": 0})
    for row in entries:
        formats[row["media_type"]].append(row)
    for field, rows, metric in (("started_date", dated_starts, "started"), ("finished_date", dated, "completed")):
        for row in rows:
            years[row[field][:4]][metric] += 1
            months[row[field][:7]][metric] += 1
    issues = Counter(issue for row in entries for issue in row["issues"])
    issues["future_date"] = sum(any(row[key] and row[key] > cutoff for key in ("started_date", "finished_date")) for row in entries)
    queues = [row for row in entries if row["status"] in {"watching", "on_hold"}]
    known_queue = [row for row in queues if row["episodes"] is not None and row["episodes_watched"] <= row["episodes"]]
    return {
        "total": len(entries), "completed": len(completed), "rated": len(scores),
        "unrated": len(entries) - len(scores), "mean_score": round(mean(scores), 2) if scores else None,
        "median_score": median(scores) if scores else None,
        "episodes_watched": sum(row["episodes_watched"] for row in entries),
        "completion_percent": round(len(completed) * 100 / len(entries), 1) if entries else None,
        "high_scores": sum(score >= 8 for score in scores),
        "statuses": [{"key": key, "label": label, "count": by_status[key]} for key, label in STATUS_LABELS.items()],
        "scores": [{"score": score, "count": by_score[score]} for score in range(1, 11)],
        "formats": [{"label": name, "count": len(rows),
                     "completed": sum(row["status"] == "completed" for row in rows),
                     "rated": sum(row["score"] is not None for row in rows),
                     "mean_score": round(mean([row["score"] for row in rows if row["score"] is not None]), 2)
                     if any(row["score"] is not None for row in rows) else None}
                    for name, rows in sorted(formats.items(), key=lambda pair: (-len(pair[1]), pair[0]))],
        "years": [{"period": key, **value} for key, value in sorted(years.items())],
        "months": [{"period": key, **value} for key, value in sorted(months.items())],
        "dated_completions": len(dated), "undated_completions": sum(not row["finished_date"] for row in completed),
        "dated_starts": len(dated_starts), "duration_sample": len(durations),
        "median_elapsed_days": median(durations) if durations else None,
        "same_day_completions": sum(days == 0 for days in durations),
        "known_queue_remaining": sum(row["episodes"] - row["episodes_watched"] for row in known_queue),
        "queue_unknown_length": sum(row["episodes"] is None for row in queues),
        "issues": dict(issues), "as_of": cutoff,
    }


def snapshot_response(db: Session, owner_id: int, *, snapshot_id: int | None = None, today: date | None = None):
    # There is deliberately no admin override: owner exports remain private.
    query = db.query(PersonalAnimeImport).filter_by(user_id=owner_id)
    snapshot = query.filter_by(id=snapshot_id).first() if snapshot_id else latest_snapshot(db, owner_id)
    if snapshot is None:
        return {"snapshot": None}
    history = query.order_by(PersonalAnimeImport.id.desc()).limit(20).all()
    entries = snapshot.payload["entries"]
    return {
        "snapshot": {"id": snapshot.id, "username": snapshot.mal_username, "filename": snapshot.filename,
                     "imported_at": snapshot.imported_at.isoformat(), "sha256": snapshot.source_hash,
                     "exported_at": None, "private": True},
        "entries": entries, "summary": summarize(entries, today=today),
        "history": [{"id": row.id, "imported_at": row.imported_at.isoformat(),
                     "titles": len(row.payload["entries"])} for row in history],
        "limitations": [
            "This is an uploaded snapshot, not a live MAL connection. Its generation time is not recorded in the XML; import time is not source freshness.",
            "One row is one MAL title, including separate seasons and specials, not a unique franchise or an episode-watch event.",
            "Scores use MAL's 1–10 scale. Zero means unscored and is excluded from rating averages.",
            "Only complete, non-future start and finish dates enter the timeline. Completed titles without finish dates still count in totals.",
            "Episodes are summed as exported, without adding assumed rewatches. No runtime, episode diary, genre, studio or community-score data is present.",
            "Elapsed days span the recorded start and finish, including breaks; they are not watch time, binge speed or a viewing streak.",
            "Comments, tags and other private notes are not imported. This dataset is not shared with monitored-profile or group statistics.",
        ],
    }
