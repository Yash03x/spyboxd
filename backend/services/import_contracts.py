from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import urljoin, urlparse

import pandas as pd


IMPORTER_VERSION = "4"


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or value.strip().casefold() in {"nan", "none", "null"}
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    try:
        return bool(missing)
    except (TypeError, ValueError):
        return False


def clean_text(value: Any, *, max_length: Optional[int] = None) -> Optional[str]:
    if is_missing(value):
        return None
    text = str(value).strip()
    if max_length is not None:
        text = text[:max_length]
    return text or None


def parse_integer(value: Any, *, minimum: Optional[int] = None) -> Optional[int]:
    if is_missing(value):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or not numeric.is_integer():
        return None
    parsed = int(numeric)
    if minimum is not None and parsed < minimum:
        return None
    return parsed


def parse_boolean(value: Any, *, default: bool = False) -> bool:
    if is_missing(value):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().casefold()
    if normalized in {"yes", "true", "1", "y", "liked", "on"}:
        return True
    if normalized in {"no", "false", "0", "n", "off"}:
        return False
    return default


def parse_date(value: Any) -> Optional[date]:
    if is_missing(value):
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def parse_tags(value: Any) -> List[str]:
    if is_missing(value):
        return []
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        raw = str(value).strip()
        if raw.startswith("["):
            try:
                decoded = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                decoded = None
            if isinstance(decoded, list):
                raw_values = decoded
            else:
                raw_values = re.split(r"\s*[,;|]\s*", raw)
        else:
            raw_values = re.split(r"\s*[,;|]\s*", raw)

    tags: List[str] = []
    seen = set()
    for candidate in raw_values:
        tag = clean_text(candidate, max_length=100)
        if not tag:
            continue
        key = tag.casefold()
        if key not in seen:
            tags.append(tag)
            seen.add(key)
    return tags


def normalize_title(value: Any) -> str:
    text = clean_text(value) or ""
    return " ".join(text.casefold().split())


def first_value(row: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        if name in row and not is_missing(row.get(name)):
            return row.get(name)
    return None


def normalize_letterboxd_url(value: Any) -> Optional[str]:
    raw = clean_text(value, max_length=500)
    if not raw:
        return None
    if raw.startswith("/"):
        return urljoin("https://letterboxd.com/", raw)
    return raw


def slug_from_url(value: Any) -> Optional[str]:
    raw = clean_text(value)
    if not raw:
        return None
    parsed = urlparse(raw if "://" in raw else f"https://letterboxd.com{raw}")
    match = re.search(r"/(?:film|films)/([^/?#]+)/?", parsed.path)
    return clean_text(match.group(1), max_length=250) if match else None


@dataclass(frozen=True)
class MovieIdentity:
    title: str
    release_year: Optional[int]
    letterboxd_id: Optional[str] = None
    letterboxd_slug: Optional[str] = None
    letterboxd_url: Optional[str] = None
    poster_url: Optional[str] = None

    @property
    def normalized_title(self) -> str:
        return normalize_title(self.title)

    @property
    def canonical_key(self) -> str:
        if self.letterboxd_id:
            return f"letterboxd:{self.letterboxd_id}"
        if self.letterboxd_slug:
            return f"letterboxd-slug:{self.letterboxd_slug.casefold()}"
        return f"title:{self.normalized_title}|year:{self.release_year or 'na'}"


def movie_identity_from_row(row: Mapping[str, Any]) -> Optional[MovieIdentity]:
    title = clean_text(first_value(row, ("Name", "Title", "Film", "Movie")), max_length=300)
    if not title:
        return None

    url = normalize_letterboxd_url(first_value(row, ("Film_URL", "Film URL", "URL", "Letterboxd URI")))
    slug = clean_text(first_value(row, ("Slug", "Film_Slug", "Letterboxd Slug")), max_length=250)
    if not slug:
        slug = slug_from_url(url)

    # The current HTML scraper's Movie_ID is an alias of Letterboxd's data-film-id,
    # not a TMDB identifier. Keep it in the Letterboxd identity namespace.
    letterboxd_id = clean_text(
        first_value(row, ("Film_ID", "Letterboxd_ID", "Letterboxd ID", "Movie_ID")),
        max_length=100,
    )
    poster_url = normalize_letterboxd_url(first_value(row, ("Poster_URL", "Poster URL")))
    return MovieIdentity(
        title=title,
        release_year=parse_integer(first_value(row, ("Year", "Release Year")), minimum=1800),
        letterboxd_id=letterboxd_id,
        letterboxd_slug=slug,
        letterboxd_url=url,
        poster_url=poster_url,
    )


def source_entry_id_from_row(row: Mapping[str, Any]) -> Optional[str]:
    return clean_text(
        first_value(
            row,
            (
                "Diary_Entry_ID",
                "Diary Entry ID",
                "Entry_ID",
                "Entry ID",
                "Viewing_ID",
                "Viewing ID",
            ),
        ),
        max_length=200,
    )


def diary_event_key(
    *,
    username: str,
    identity: MovieIdentity,
    watched_date: date,
    occurrence: int,
    source_entry_id: Optional[str] = None,
) -> str:
    if occurrence < 1:
        raise ValueError("occurrence must be positive")
    if source_entry_id:
        stable = f"{username.casefold()}|entry:{source_entry_id}"
    else:
        stable = (
            f"{username.casefold()}|{identity.canonical_key}|"
            f"{watched_date.isoformat()}|{occurrence}"
        )
    digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()
    return f"diary:{digest}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bundle_fingerprint(username: str, files: Iterable[Mapping[str, Any]]) -> str:
    canonical_files = sorted(
        (
            clean_text(file_info.get("name")) or "",
            clean_text(file_info.get("sha256")) or "",
        )
        for file_info in files
    )
    payload = json.dumps(
        {"username": username.casefold(), "files": canonical_files},
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def frame_records(frame: pd.DataFrame) -> Iterable[Dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    return (row.to_dict() for _, row in frame.iterrows())
