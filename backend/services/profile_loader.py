from __future__ import annotations

import math
import json
from pathlib import Path
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

import pandas as pd

from services.import_contracts import (
    bundle_fingerprint,
    clean_text,
    file_sha256,
    first_value,
    frame_records,
    movie_identity_from_row,
    parse_boolean,
)


FULL_SCRAPE_REQUIRED_DATASETS = {
    "profile",
    "films",
    "diary",
    "likes",
    "reviews",
    "watchlist",
    "lists",
    "list_items",
    "favorites",
}

# Schema v3 adds the social surfaces. Gating them on the manifest version keeps
# every existing v2 bundle valid while new bundles must account for them.
V3_SCRAPE_REQUIRED_DATASETS = FULL_SCRAPE_REQUIRED_DATASETS | {"following", "followers"}


@dataclass
class LoadedProfileData:
    username: str
    profile_info: Dict
    ratings: pd.DataFrame
    reviews: pd.DataFrame
    watched: pd.DataFrame
    diary: pd.DataFrame
    watchlist: pd.DataFrame
    comments: pd.DataFrame
    lists: List[pd.DataFrame]
    list_metadata: pd.DataFrame
    favorites: pd.DataFrame
    likes: pd.DataFrame
    all_films: pd.DataFrame
    following: pd.DataFrame
    followers: pd.DataFrame
    avg_rating: float
    total_reviews: int
    join_date: Optional[date]
    source_kind: str
    source_fingerprint: str
    source_files: Dict[str, Dict[str, Any]]
    manifest: Dict[str, Any]


def _safe_read_csv(path: str, label: str, *, strict: bool = False) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path)
        print(f"Loaded {label}: {len(frame)} entries")
        return frame
    except Exception as exc:
        if strict:
            raise ValueError(f"Failed to read required {label}: {exc}") from exc
        print(f"Failed to load {label}: {exc}")
        return pd.DataFrame()


def _parse_join_date(profile_info: Dict) -> Optional[date]:
    raw_join_date = profile_info.get("Join_Date") or profile_info.get("Date Joined")
    if not raw_join_date:
        return None

    parsed = pd.to_datetime(raw_join_date, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _file_info(path: Path, row_count: int) -> Dict[str, Any]:
    return {
        "name": path.name,
        "relative_path": path.name,
        "sha256": file_sha256(path),
        "row_count": max(int(row_count), 0),
    }


def _detect_source_kind(source_files: Dict[str, Dict[str, Any]]) -> str:
    if "films_comprehensive.csv" in source_files:
        return "full_html_upload"
    if "watched.csv" in source_files or "ratings.csv" in source_files:
        return "letterboxd_export"
    return "uploaded_csv_bundle"


def load_profile_data(profile_path: str, username: str) -> LoadedProfileData:
    """
    Lightweight profile loader used by uploads and local sync ingestion.
    Keeps the runtime path focused on CSV ingestion only.
    """
    resolved_profile_path = Path(profile_path).resolve()
    source_files: Dict[str, Dict[str, Any]] = {}
    scrape_manifest: Dict[str, Any] = {}
    strict_sources = False

    def read_source(path: Path, label: str, *, source_name: Optional[str] = None) -> pd.DataFrame:
        frame = _safe_read_csv(str(path), label, strict=strict_sources)
        relative_name = source_name or str(path.relative_to(resolved_profile_path))
        info = _file_info(path, len(frame))
        info["name"] = relative_name
        info["relative_path"] = relative_name
        source_files[relative_name] = info
        return frame

    manifest_schema_version: Optional[int] = None
    manifest_path = resolved_profile_path / "manifest.json"
    if manifest_path.exists():
        try:
            with manifest_path.open("r", encoding="utf-8") as handle:
                decoded_manifest = json.load(handle)
            if isinstance(decoded_manifest, dict):
                scrape_manifest = decoded_manifest
                manifest_schema_version = parse_manifest_integer(scrape_manifest.get("schema_version"))
                strict_sources = manifest_schema_version is not None and manifest_schema_version >= 2
            source_files["manifest.json"] = _file_info(manifest_path, 0)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid scrape manifest: {exc}") from exc

    profile_csv = resolved_profile_path / "profile.csv"
    if profile_csv.exists():
        profile_df = read_source(profile_csv, "profile.csv")
        profile_info = profile_df.iloc[0].to_dict() if not profile_df.empty else {}
    else:
        profile_info = {}

    files_to_load = [
        "ratings", "reviews", "watched", "diary", "watchlist", "comments", "likes",
        "following", "followers",
    ]
    # Social CSVs are part of the contract from schema v3. A v2 bundle that
    # happens to contain one (stray or corrupt) is read the way the deployed
    # v2 loader behaved: not at all. Manifest-less bundles (official exports
    # ship top-level following.csv/followers.csv) load leniently like every
    # other surface in that mode.
    skip_social = manifest_schema_version is not None and manifest_schema_version < 3
    loaded: Dict[str, pd.DataFrame] = {}
    for name in files_to_load:
        if name in ("following", "followers") and skip_social:
            loaded[name] = pd.DataFrame()
            continue
        file_path = resolved_profile_path / f"{name}.csv"
        loaded[name] = read_source(file_path, f"{name}.csv") if file_path.exists() else pd.DataFrame()

    # Official account exports store liked films at likes/films.csv. The
    # public HTML scraper intentionally emits the top-level likes.csv contract,
    # so the nested path is a compatibility fallback rather than a second
    # competing source.
    official_likes_path = resolved_profile_path / "likes" / "films.csv"
    if "likes.csv" not in source_files and official_likes_path.exists():
        loaded["likes"] = read_source(
            official_likes_path,
            "likes/films.csv",
            source_name="likes/films.csv",
        )

    all_films = pd.DataFrame()
    for candidate in ["films.csv", "all_films.csv", "films_comprehensive.csv"]:
        candidate_path = resolved_profile_path / candidate
        if not candidate_path.exists():
            continue
        all_films = read_source(candidate_path, candidate)
        if not all_films.empty:
            break

    list_metadata_path = resolved_profile_path / "lists.csv"
    list_metadata = (
        read_source(list_metadata_path, "lists.csv")
        if list_metadata_path.exists()
        else pd.DataFrame()
    )

    lists: List[pd.DataFrame] = []
    lists_dir = resolved_profile_path / "lists"
    if lists_dir.is_dir():
        for entry_path in sorted(lists_dir.iterdir()):
            if not entry_path.is_file() or entry_path.suffix.casefold() != ".csv":
                continue
            relative_name = f"lists/{entry_path.name}"
            list_df = read_source(entry_path, relative_name, source_name=relative_name)
            list_df["list_name"] = entry_path.stem
            list_df["source_filename"] = relative_name
            list_df.attrs["list_name"] = entry_path.stem
            list_df.attrs["source_filename"] = relative_name
            lists.append(list_df)

    flat_list_items_path = resolved_profile_path / "list_items.csv"
    if flat_list_items_path.exists():
        flat_items = read_source(flat_list_items_path, "list_items.csv")
        group_column = next(
            (
                column
                for column in ("List_URL", "List URL", "List_Name", "List Name", "list_name")
                if column in flat_items.columns
            ),
            None,
        )
        if group_column:
            for group_name, group in flat_items.groupby(group_column, dropna=False, sort=False):
                grouped = group.copy()
                grouped["list_name"] = str(group_name)
                grouped["source_filename"] = "list_items.csv"
                grouped.attrs["list_name"] = str(group_name)
                grouped.attrs["source_filename"] = "list_items.csv"
                lists.append(grouped)

    favorites_path = resolved_profile_path / "favorites.csv"
    favorites = (
        read_source(favorites_path, "favorites.csv")
        if favorites_path.exists()
        else pd.DataFrame()
    )

    ratings = loaded.get("ratings", pd.DataFrame())
    reviews = loaded.get("reviews", pd.DataFrame())

    avg_rating = 0.0
    if not ratings.empty and "Rating" in ratings.columns:
        numeric_ratings = pd.to_numeric(ratings["Rating"], errors="coerce").dropna()
        if not numeric_ratings.empty:
            candidate_avg = float(numeric_ratings.mean())
            if math.isfinite(candidate_avg):
                avg_rating = candidate_avg

    effective_username = username
    if not strict_sources:
        profile_username = clean_text(
            first_value(profile_info, ("Username", "User Name", "Handle")),
            max_length=50,
        )
        if profile_username:
            effective_username = profile_username

    source_kind = str(scrape_manifest.get("source_kind") or _detect_source_kind(source_files))
    source_fingerprint = bundle_fingerprint(effective_username, source_files.values())
    manifest = {
        **scrape_manifest,
        "source_kind": source_kind,
        "files": sorted(source_files.values(), key=lambda item: item["name"]),
    }
    # A schema-v2 manifest is an integrity boundary. Preserve its claimed
    # username so validation can compare it with the requested import target;
    # replacing it here would make every mismatched bundle appear valid.
    if not strict_sources:
        manifest.setdefault("username", effective_username)

    return LoadedProfileData(
        username=effective_username,
        profile_info=profile_info,
        ratings=ratings,
        reviews=reviews,
        watched=loaded.get("watched", pd.DataFrame()),
        diary=loaded.get("diary", pd.DataFrame()),
        watchlist=loaded.get("watchlist", pd.DataFrame()),
        comments=loaded.get("comments", pd.DataFrame()),
        lists=lists,
        list_metadata=list_metadata,
        favorites=favorites,
        likes=loaded.get("likes", pd.DataFrame()),
        all_films=all_films,
        following=loaded.get("following", pd.DataFrame()),
        followers=loaded.get("followers", pd.DataFrame()),
        avg_rating=avg_rating,
        total_reviews=len(reviews),
        join_date=_parse_join_date(profile_info),
        source_kind=source_kind,
        source_fingerprint=source_fingerprint,
        source_files=source_files,
        manifest=manifest,
    )


def validate_import_bundle(
    loaded: LoadedProfileData,
    *,
    require_full_manifest: bool = False,
) -> None:
    """Fail closed for v2 full scrapes while retaining old upload compatibility."""
    schema_version = parse_manifest_integer(loaded.manifest.get("schema_version"))
    has_v2_manifest = schema_version is not None and schema_version >= 2
    if require_full_manifest and not has_v2_manifest:
        raise ValueError("A successful schema-v2 scraper manifest is required for local import")
    if not has_v2_manifest:
        return

    # v3 bundles must also account for the social surfaces; v2 bundles from
    # pre-upgrade scrapers remain valid without them.
    required_datasets = (
        V3_SCRAPE_REQUIRED_DATASETS
        if schema_version is not None and schema_version >= 3
        else FULL_SCRAPE_REQUIRED_DATASETS
    )

    manifest_username = str(loaded.manifest.get("username") or "").strip()
    if not manifest_username:
        raise ValueError("Schema-v2 manifest username is required")
    if manifest_username.casefold() != loaded.username.casefold():
        raise ValueError(
            f"Manifest username {manifest_username!r} does not match {loaded.username!r}"
        )

    completed = {
        str(value)
        for value in loaded.manifest.get("completed_datasets", [])
        if str(value).strip()
    }
    raw_unavailable = loaded.manifest.get("unavailable_datasets", {}) or {}
    if not isinstance(raw_unavailable, dict):
        raise ValueError("Manifest unavailable_datasets must be an object of dataset reasons")
    unavailable = {
        str(dataset): str(reason).strip()
        for dataset, reason in raw_unavailable.items()
        if str(dataset).strip()
    }
    empty_reasons = sorted(dataset for dataset, reason in unavailable.items() if not reason)
    if empty_reasons:
        raise ValueError(
            "Unavailable datasets require a reason: " + ", ".join(empty_reasons)
        )
    overlap = completed & set(unavailable)
    if overlap:
        raise ValueError(
            "Datasets cannot be both completed and unavailable: "
            + ", ".join(sorted(overlap))
        )

    requested_values = loaded.manifest.get("requested_datasets")
    requested = (
        {str(value) for value in requested_values if str(value).strip()}
        if isinstance(requested_values, list)
        else set(required_datasets)
    )
    missing_requests = required_datasets - requested
    if missing_requests:
        raise ValueError(
            "Full scrape manifest did not request datasets: "
            + ", ".join(sorted(missing_requests))
        )

    missing = required_datasets - completed - set(unavailable)
    if missing:
        raise ValueError(
            "Full scrape manifest has unaccounted datasets: "
            + ", ".join(sorted(missing))
        )

    mandatory = {"profile", "films", "diary", "reviews", "likes"}
    unavailable_mandatory = mandatory & set(unavailable)
    if unavailable_mandatory:
        raise ValueError(
            "Core datasets cannot be marked unavailable: "
            + ", ".join(sorted(unavailable_mandatory))
        )

    dataset_files = {
        "profile": "profile.csv",
        "films": "films_comprehensive.csv",
        "diary": "diary.csv",
        "likes": "likes.csv",
        "reviews": "reviews.csv",
        "watchlist": "watchlist.csv",
        "lists": "lists.csv",
        "list_items": "list_items.csv",
        "favorites": "favorites.csv",
        "following": "following.csv",
        "followers": "followers.csv",
    }
    required_files = {dataset_files[name] for name in completed if name in dataset_files}
    missing_files = required_files - set(loaded.source_files)
    if missing_files:
        raise ValueError(
            f"Full scrape artifact is missing files: {', '.join(sorted(missing_files))}"
        )
    contradictory_files = {
        dataset_files[name]
        for name in unavailable
        if name in dataset_files and dataset_files[name] in loaded.source_files
    }
    if "list_items" in unavailable:
        contradictory_files.update(
            source_name
            for source_name in loaded.source_files
            if source_name.startswith("lists/") and source_name.casefold().endswith(".csv")
        )
    if contradictory_files:
        raise ValueError(
            "Unavailable datasets must omit their data files: "
            + ", ".join(sorted(contradictory_files))
        )

    counts = loaded.manifest.get("counts") if isinstance(loaded.manifest.get("counts"), dict) else {}
    observed_counts = {
        "films": len(loaded.all_films),
        "diary": len(loaded.diary),
        "likes": len(loaded.likes),
        "reviews": len(loaded.reviews),
        "watchlist": len(loaded.watchlist),
        "lists": len(loaded.list_metadata),
        "list_items": sum(len(frame) for frame in loaded.lists),
        "favorites": len(loaded.favorites),
        "following": len(loaded.following),
        "followers": len(loaded.followers),
    }
    mismatches = []
    for dataset_name, observed in observed_counts.items():
        if dataset_name not in completed:
            continue
        expected = parse_manifest_integer(counts.get(dataset_name))
        if expected is None:
            mismatches.append(f"{dataset_name}: manifest count missing, observed={observed}")
        elif expected != observed:
            mismatches.append(f"{dataset_name}: manifest={expected}, observed={observed}")
    if mismatches:
        raise ValueError("Scrape artifact count mismatch: " + "; ".join(mismatches))

    def identity_keys(frame: pd.DataFrame, *, liked_only: bool = False) -> List[str]:
        keys: List[str] = []
        for row in frame_records(frame):
            if liked_only and not parse_boolean(row.get("Is_Liked")):
                continue
            identity = movie_identity_from_row(row)
            if identity is None:
                raise ValueError("Liked-film dataset contains a row without usable movie identity")
            keys.append(identity.canonical_key)
        return keys

    actual_like_keys = identity_keys(loaded.likes)
    if len(actual_like_keys) != len(set(actual_like_keys)):
        raise ValueError("likes.csv contains duplicate movie identities")
    expected_like_keys = set(identity_keys(loaded.all_films, liked_only=True))
    expected_like_keys.update(identity_keys(loaded.diary, liked_only=True))
    if set(actual_like_keys) != expected_like_keys:
        raise ValueError(
            "Liked-film identity mismatch: "
            f"likes.csv={len(set(actual_like_keys))}, authoritative surfaces={len(expected_like_keys)}"
        )


def parse_manifest_integer(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
