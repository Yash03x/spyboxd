from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import (
    MovieList,
    MovieListItem,
    Profile,
    ProfileFeedState,
    ProfileFavoriteMovie,
    ProfileFilm,
    ProfileSourceActivity,
    ProfileSync,
    Rating,
    Review,
    SyncDataset,
    WatchEvent,
    WatchlistItem,
)
from services.import_contracts import (
    IMPORTER_VERSION,
    MovieIdentity,
    clean_text,
    diary_event_key,
    first_value,
    frame_records,
    movie_identity_from_row,
    normalize_letterboxd_url,
    normalize_title,
    parse_boolean,
    parse_date,
    parse_integer,
    parse_tags,
    source_entry_id_from_row,
)
from services.movie_resolver import MovieResolver
from services.profile_changes import (
    capture_profile_state,
    record_profile_changes,
)
from services.profile_loader import validate_import_bundle
from services.profile_ingestion_lock import lock_profile_ingestion


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_date_for_db(date_value):
    """Backward-compatible public helper used by older import callers."""
    return parse_date(date_value)


def parse_rating_value(value):
    """Parse rating values safely, returning None for NaN/Inf/invalid."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        numeric = pd.to_numeric(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(numeric):
        return None
    parsed = float(numeric)
    return parsed if math.isfinite(parsed) else None


def _bounded_rating(value: Any) -> Optional[float]:
    rating = parse_rating_value(value)
    if rating is None or not 0.5 <= rating <= 5.0:
        return None
    return rating


def parse_rewatch_status(rewatch_value):
    """Backward-compatible boolean parser for Letterboxd's rewatch flag."""
    return parse_boolean(rewatch_value)


def _row_year(row: Mapping[str, Any]) -> Optional[int]:
    return parse_integer(first_value(row, ("Year", "Release Year")), minimum=1800)


def _legacy_key(identity: MovieIdentity) -> Tuple[str, Optional[int]]:
    return identity.title, identity.release_year


def _identity_lookup(all_films: pd.DataFrame) -> Dict[Tuple[str, Optional[int]], MovieIdentity]:
    lookup: Dict[Tuple[str, Optional[int]], MovieIdentity] = {}
    for row in frame_records(all_films):
        identity = movie_identity_from_row(row)
        if identity is not None:
            lookup[(identity.normalized_title, identity.release_year)] = identity
    return lookup


def _enrich_identity(
    identity: MovieIdentity,
    lookup: Mapping[Tuple[str, Optional[int]], MovieIdentity],
) -> MovieIdentity:
    fallback = lookup.get((identity.normalized_title, identity.release_year))
    if fallback is None:
        return identity
    return MovieIdentity(
        title=identity.title or fallback.title,
        release_year=identity.release_year if identity.release_year is not None else fallback.release_year,
        letterboxd_id=identity.letterboxd_id or fallback.letterboxd_id,
        letterboxd_slug=identity.letterboxd_slug or fallback.letterboxd_slug,
        letterboxd_url=identity.letterboxd_url or fallback.letterboxd_url,
        poster_url=identity.poster_url or fallback.poster_url,
    )


def _new_legacy_payload(
    profile_id: int,
    identity: MovieIdentity,
    row: Mapping[str, Any],
    *,
    allow_watched_date: bool,
) -> Dict[str, Any]:
    return {
        "profile_id": profile_id,
        "identity": identity,
        "movie_title": identity.title,
        "movie_year": identity.release_year,
        "letterboxd_id": identity.letterboxd_id,
        "rating": parse_rating_value(first_value(row, ("Rating", "Stars"))),
        # Letterboxd export `Date` values are account-activity timestamps. They
        # are not watch dates unless the row came from diary.csv.
        "watched_date": (
            parse_date(first_value(row, ("Watched Date", "Date")))
            if allow_watched_date
            else None
        ),
        "is_rewatch": parse_boolean(first_value(row, ("Rewatch", "Is_Rewatch", "Is Rewatch"))),
        "is_liked": parse_boolean(first_value(row, ("Liked", "Is_Liked", "Is Liked"))),
        "tags": parse_tags(first_value(row, ("Tags", "Tag"))),
        "film_slug": identity.letterboxd_slug,
        "poster_url": identity.poster_url,
        "has_review": parse_boolean(first_value(row, ("Has_Review", "Has Review"))),
    }


def _merge_legacy_payload(
    target: Dict[str, Any],
    row: Mapping[str, Any],
    identity: MovieIdentity,
    *,
    allow_watched_date: bool,
) -> None:
    if not target.get("letterboxd_id") and identity.letterboxd_id:
        target["letterboxd_id"] = identity.letterboxd_id
    if not target.get("film_slug") and identity.letterboxd_slug:
        target["film_slug"] = identity.letterboxd_slug
    if not target.get("poster_url") and identity.poster_url:
        target["poster_url"] = identity.poster_url
    if target.get("rating") is None:
        target["rating"] = parse_rating_value(first_value(row, ("Rating", "Stars")))
    if allow_watched_date and target.get("watched_date") is None:
        target["watched_date"] = parse_date(first_value(row, ("Watched Date", "Date")))
    target["is_rewatch"] = bool(target.get("is_rewatch")) or parse_boolean(
        first_value(row, ("Rewatch", "Is_Rewatch", "Is Rewatch"))
    )
    target["is_liked"] = bool(target.get("is_liked")) or parse_boolean(
        first_value(row, ("Liked", "Is_Liked", "Is Liked"))
    )
    target["has_review"] = bool(target.get("has_review")) or parse_boolean(
        first_value(row, ("Has_Review", "Has Review"))
    )
    existing_tags = list(target.get("tags") or [])
    seen_tags = {tag.casefold() for tag in existing_tags}
    for tag in parse_tags(first_value(row, ("Tags", "Tag"))):
        if tag.casefold() not in seen_tags:
            existing_tags.append(tag)
            seen_tags.add(tag.casefold())
    target["tags"] = existing_tags
    target["identity"] = _enrich_identity(identity, {
        (target["identity"].normalized_title, target["identity"].release_year): target["identity"]
    })


def _build_legacy_movies(
    analyzer_profile,
    profile_id: int,
    identity_lookup: Mapping[Tuple[str, Optional[int]], MovieIdentity],
) -> Dict[Tuple[str, Optional[int]], Dict[str, Any]]:
    movies: Dict[Tuple[str, Optional[int]], Dict[str, Any]] = {}

    def ingest_frame(
        frame: pd.DataFrame,
        *,
        force_liked: bool = False,
        allow_watched_date: bool = False,
    ) -> None:
        for row in frame_records(frame):
            if force_liked:
                row = {**row, "Is_Liked": "Yes"}
            identity = movie_identity_from_row(row)
            if identity is None:
                continue
            identity = _enrich_identity(identity, identity_lookup)
            key = _legacy_key(identity)
            if key not in movies:
                movies[key] = _new_legacy_payload(
                    profile_id,
                    identity,
                    row,
                    allow_watched_date=allow_watched_date,
                )
            else:
                _merge_legacy_payload(
                    movies[key],
                    row,
                    identity,
                    allow_watched_date=allow_watched_date,
                )

    ingest_frame(getattr(analyzer_profile, "all_films", pd.DataFrame()))
    ingest_frame(getattr(analyzer_profile, "ratings", pd.DataFrame()))
    ingest_frame(getattr(analyzer_profile, "watched", pd.DataFrame()))
    ingest_frame(
        getattr(analyzer_profile, "diary", pd.DataFrame()),
        allow_watched_date=True,
    )
    # A row's presence in Letterboxd's likes.csv is itself the liked signal;
    # official exports do not include a redundant boolean column.
    ingest_frame(getattr(analyzer_profile, "likes", pd.DataFrame()), force_liked=True)
    return movies


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def _stable_digest(prefix: str, parts: Sequence[Any]) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts)
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _get_or_create_sync(analyzer_profile, profile_id: int, db: Session) -> Tuple[ProfileSync, bool]:
    source_kind = clean_text(getattr(analyzer_profile, "source_kind", None), max_length=50) or "uploaded_csv_bundle"
    source_fingerprint = clean_text(getattr(analyzer_profile, "source_fingerprint", None), max_length=200)
    if not source_fingerprint:
        source_fingerprint = _stable_digest("bundle", (profile_id, source_kind))

    sync = (
        db.query(ProfileSync)
        .filter(
            ProfileSync.profile_id == profile_id,
            ProfileSync.source_fingerprint == source_fingerprint,
            ProfileSync.importer_version == IMPORTER_VERSION,
        )
        .first()
    )
    was_completed = bool(sync and sync.status == "completed")
    if sync is None:
        sync = ProfileSync(
            profile_id=profile_id,
            source_kind=source_kind,
            source_fingerprint=source_fingerprint,
            importer_version=IMPORTER_VERSION,
            status="running",
            manifest=getattr(analyzer_profile, "manifest", {}) or {},
            coverage={},
            stats={},
        )
        db.add(sync)
    elif was_completed:
        # A source fingerprint is immutable ingestion history. Replaying an
        # already-completed bundle must be a no-op; reopening it after a newer
        # sync could silently restore stale state and corrupt change-feed
        # chronology/deduplication.
        return sync, True
    else:
        sync.status = "running"
        sync.started_at = _utcnow()
        sync.completed_at = None
        sync.error_message = None
        sync.manifest = getattr(analyzer_profile, "manifest", {}) or {}
    db.flush()
    return sync, was_completed


def _reconcile_legacy_rows(
    *,
    analyzer_profile,
    profile_id: int,
    sync: ProfileSync,
    resolver: MovieResolver,
    legacy_movies: Mapping[Tuple[str, Optional[int]], Dict[str, Any]],
    identity_lookup: Mapping[Tuple[str, Optional[int]], MovieIdentity],
    films_authoritative: bool,
    reviews_authoritative: bool,
    rating_authoritative: bool,
    diary_authoritative: bool,
    likes_authoritative: bool,
    tags_authoritative: bool,
    db: Session,
) -> Tuple[Dict[int, Rating], int]:
    existing_ratings = db.query(Rating).filter(Rating.profile_id == profile_id).all()
    ratings_by_movie = {
        rating.movie_id: rating
        for rating in existing_ratings
        if rating.movie_id is not None
    }
    all_ratings_by_legacy_key = {
        (normalize_title(rating.movie_title), rating.movie_year): rating
        for rating in existing_ratings
    }
    ratings_by_legacy_key = {
        (normalize_title(rating.movie_title), rating.movie_year): rating
        for rating in existing_ratings
        if rating.movie_id is None
    }
    seen_rating_ids = set()
    ratings_by_movie_id: Dict[int, Rating] = {}
    for payload in legacy_movies.values():
        identity = payload["identity"]
        movie = resolver.resolve(identity)
        legacy_key = (normalize_title(payload["movie_title"]), payload["movie_year"])
        rating = ratings_by_movie.get(movie.id) or ratings_by_legacy_key.get(legacy_key)
        conflicting_rating = all_ratings_by_legacy_key.get(legacy_key)
        if (
            rating is None
            and conflicting_rating is not None
            and conflicting_rating.movie_id != movie.id
        ):
            # The legacy table cannot represent two canonical movies sharing a
            # title/year because of its compatibility uniqueness constraint.
            # Never steal the existing row from another ProfileFilm; the
            # normalized ProfileFilm below remains the source of truth.
            continue
        created_rating = rating is None
        if created_rating:
            rating = Rating(
                profile_id=profile_id,
                movie_id=movie.id,
                first_seen_profile_sync_id=sync.id,
            )
            db.add(rating)
        rating.movie_id = movie.id
        rating.last_seen_profile_sync_id = sync.id
        rating.removed_at = None
        rating.movie_title = payload["movie_title"]
        rating.movie_year = payload["movie_year"]
        rating.letterboxd_id = payload["letterboxd_id"] or rating.letterboxd_id
        if created_rating or rating_authoritative:
            rating.rating = payload["rating"]
        if created_rating or diary_authoritative:
            rating.watched_date = payload["watched_date"]
            rating.is_rewatch = payload["is_rewatch"]
        if created_rating or likes_authoritative:
            rating.is_liked = payload["is_liked"]
        if created_rating or tags_authoritative:
            rating.tags = payload["tags"]
        rating.film_slug = payload["film_slug"] or rating.film_slug
        rating.poster_url = payload["poster_url"] or rating.poster_url
        db.flush()
        seen_rating_ids.add(rating.id)
        ratings_by_movie_id[movie.id] = rating

    if films_authoritative:
        stale_rating_ids = [
            rating.id for rating in existing_ratings if rating.id not in seen_rating_ids
        ]
        if stale_rating_ids:
            db.query(ProfileFilm).filter(
                ProfileFilm.legacy_rating_id.in_(stale_rating_ids)
            ).update(
                {ProfileFilm.legacy_rating_id: None},
                synchronize_session=False,
            )
            db.query(Rating).filter(Rating.id.in_(stale_rating_ids)).delete(
                synchronize_session=False
            )
    db.flush()

    existing_reviews = db.query(Review).filter(Review.profile_id == profile_id).all()
    reviews_by_key = {
        review.source_review_key: review
        for review in existing_reviews
        if review.source_review_key
    }
    reviews_by_movie_date: Dict[Tuple[int, Optional[date]], List[Review]] = defaultdict(list)
    for review in existing_reviews:
        if review.movie_id is not None:
            reviews_by_movie_date[(review.movie_id, review.published_date)].append(review)
    claimed_review_ids = set()
    review_occurrences: Dict[Tuple[int, Optional[str]], int] = defaultdict(int)
    review_count = 0
    for row_number, row in enumerate(frame_records(getattr(analyzer_profile, "reviews", pd.DataFrame())), start=1):
        identity = movie_identity_from_row(row)
        if identity is None:
            continue
        identity = _enrich_identity(identity, identity_lookup)
        movie = resolver.resolve(identity)
        published_raw = first_value(row, ("Review_Date", "Review Date", "Date"))
        published_date = parse_date(published_raw)
        occurrence_key = (movie.id, published_date.isoformat() if published_date else None)
        review_occurrences[occurrence_key] += 1
        source_review_key = _stable_digest(
            "review",
            (
                profile_id,
                movie.canonical_key,
                occurrence_key[1],
                review_occurrences[occurrence_key],
            ),
        )
        review = reviews_by_key.get(source_review_key)
        if review is None:
            candidates = [
                candidate
                for candidate in reviews_by_movie_date.get((movie.id, published_date), [])
                if candidate.id not in claimed_review_ids
            ]
            if len(candidates) == 1:
                review = candidates[0]
        if review is None:
            review = Review(
                profile_id=profile_id,
                movie_id=movie.id,
                source_review_key=source_review_key,
                first_seen_profile_sync_id=sync.id,
                tags=[],
                likes_count=0,
                comments_count=0,
            )
            db.add(review)
        review.movie_id = movie.id
        review.last_seen_profile_sync_id = sync.id
        review.source_review_key = source_review_key
        review.source_url = review.source_url or identity.letterboxd_url
        parsed_published_at = _parse_timestamp(published_raw)
        if review.published_at is None:
            review.published_at = parsed_published_at
        review.removed_at = None
        review.movie_title = identity.title
        review.movie_year = identity.release_year
        review.letterboxd_id = identity.letterboxd_id or review.letterboxd_id
        review.review_text = clean_text(first_value(row, ("Review", "Review Text"))) or ""
        review.rating = parse_rating_value(first_value(row, ("Rating", "Stars")))
        review.published_date = published_date
        review.likes_count = parse_integer(
            first_value(row, ("Review_Likes", "Review Likes", "Likes_Count", "Likes Count")),
            minimum=0,
        ) or 0
        comments_value = first_value(
            row,
            ("Review_Comments", "Review Comments", "Comments_Count", "Comments Count"),
        )
        if comments_value is not None:
            review.comments_count = parse_integer(comments_value, minimum=0) or 0
        spoilers_value = first_value(
            row,
            ("Contains Spoilers", "Contains_Spoilers", "Spoiler", "Is Spoiler"),
        )
        if spoilers_value is not None:
            review.contains_spoilers = parse_boolean(spoilers_value)
        tags_value = first_value(row, ("Tags", "Tag"))
        if tags_value is not None:
            review.tags = parse_tags(tags_value)
        db.flush()
        claimed_review_ids.add(review.id)
        review_count += 1

    if reviews_authoritative:
        stale_review_ids = [
            review.id for review in existing_reviews if review.id not in claimed_review_ids
        ]
        if stale_review_ids:
            db.query(Review).filter(Review.id.in_(stale_review_ids)).delete(
                synchronize_session=False
            )
    db.flush()
    return ratings_by_movie_id, review_count


def _prepare_diary_events(
    *,
    analyzer_profile,
    resolver: MovieResolver,
    identity_lookup: Mapping[Tuple[str, Optional[int]], MovieIdentity],
) -> Tuple[List[Dict[str, Any]], int]:
    prepared: List[Dict[str, Any]] = []
    skipped = 0
    occurrences: Dict[Tuple[int, str], int] = defaultdict(int)
    username = analyzer_profile.username

    for row_number, row in enumerate(frame_records(getattr(analyzer_profile, "diary", pd.DataFrame())), start=1):
        identity = movie_identity_from_row(row)
        watched_date = parse_date(first_value(row, ("Watched Date", "Date")))
        if identity is None or watched_date is None:
            skipped += 1
            continue
        identity = _enrich_identity(identity, identity_lookup)
        movie = resolver.resolve(identity)
        occurrence_key = (movie.id, watched_date.isoformat())
        occurrences[occurrence_key] += 1
        source_entry_id = source_entry_id_from_row(row)
        event_key = diary_event_key(
            username=username,
            identity=MovieIdentity(
                title=movie.title,
                release_year=movie.release_year,
                letterboxd_id=movie.letterboxd_id,
                letterboxd_slug=movie.letterboxd_slug,
                letterboxd_url=movie.letterboxd_url,
                poster_url=movie.poster_url,
            ),
            watched_date=watched_date,
            occurrence=occurrences[occurrence_key],
            source_entry_id=source_entry_id,
        )
        prepared.append(
            {
                "movie": movie,
                "event_key": event_key,
                "watched_date": watched_date,
                "rating": _bounded_rating(first_value(row, ("Rating", "Stars"))),
                "is_rewatch": parse_boolean(first_value(row, ("Rewatch", "Is_Rewatch", "Is Rewatch"))),
                "is_liked": parse_boolean(first_value(row, ("Liked", "Is_Liked", "Is Liked"))),
                "has_review": parse_boolean(first_value(row, ("Has_Review", "Has Review"))),
                "tags": parse_tags(first_value(row, ("Tags", "Tag"))),
                "source_entry_id": source_entry_id,
                "source_url": identity.letterboxd_url,
                "source_row_number": row_number,
            }
        )
    return prepared, skipped


def _upsert_profile_films(
    *,
    profile_id: int,
    sync: ProfileSync,
    legacy_movies: Mapping[Tuple[str, Optional[int]], Dict[str, Any]],
    ratings_by_movie_id: Mapping[int, Rating],
    prepared_events: Sequence[Dict[str, Any]],
    resolver: MovieResolver,
    all_films_authoritative: bool,
    diary_authoritative: bool,
    rating_authoritative: bool,
    likes_authoritative: bool,
    review_state_authoritative: bool,
    tags_authoritative: bool,
    db: Session,
) -> Tuple[Dict[int, ProfileFilm], int]:
    aggregate: Dict[int, Dict[str, Any]] = defaultdict(
        lambda: {
            "dates": [],
            "watch_count": 0,
            "rewatch_count": 0,
            "is_liked": False,
            "has_review": False,
            "tags": [],
        }
    )
    for event in prepared_events:
        movie_id = event["movie"].id
        values = aggregate[movie_id]
        values["dates"].append(event["watched_date"])
        values["watch_count"] += 1
        values["rewatch_count"] += int(event["is_rewatch"])
        values["is_liked"] = values["is_liked"] or event["is_liked"]
        values["has_review"] = values["has_review"] or event["has_review"]
        values["tags"] = list(dict.fromkeys([*values["tags"], *event["tags"]]))

    states: Dict[int, Dict[str, Any]] = {}
    for payload in legacy_movies.values():
        movie = resolver.resolve(payload["identity"])
        values = aggregate.get(movie.id, {})
        states[movie.id] = {
            "rating": _bounded_rating(payload["rating"]),
            "is_liked": bool(payload["is_liked"]) or bool(values.get("is_liked")),
            "has_review": bool(payload["has_review"]) or bool(values.get("has_review")),
            "tags": list(dict.fromkeys([*(payload.get("tags") or []), *(values.get("tags") or [])])),
            "dates": values.get("dates", []),
            "watch_count": values.get("watch_count", 0),
            "rewatch_count": values.get("rewatch_count", 0),
        }
    for movie_id, values in aggregate.items():
        states.setdefault(
            movie_id,
            {
                "rating": next(
                    (event["rating"] for event in reversed(prepared_events) if event["movie"].id == movie_id and event["rating"] is not None),
                    None,
                ),
                "is_liked": values["is_liked"],
                "has_review": values["has_review"],
                "tags": values["tags"],
                "dates": values["dates"],
                "watch_count": values["watch_count"],
                "rewatch_count": values["rewatch_count"],
            },
        )

    existing = {
        item.movie_id: item
        for item in db.query(ProfileFilm).filter(ProfileFilm.profile_id == profile_id).all()
    }
    now = _utcnow()
    result: Dict[int, ProfileFilm] = {}
    for movie_id, state in states.items():
        item = existing.get(movie_id)
        created_item = item is None
        if created_item:
            item = ProfileFilm(
                profile_id=profile_id,
                movie_id=movie_id,
                first_seen_profile_sync_id=sync.id,
            )
            db.add(item)
        dates = state["dates"]
        item.legacy_rating = ratings_by_movie_id.get(movie_id)
        if created_item or rating_authoritative:
            item.rating = state["rating"]
        if created_item or likes_authoritative:
            item.is_liked = state["is_liked"]
        if created_item or review_state_authoritative:
            item.has_review = state["has_review"]
        if created_item or tags_authoritative:
            item.tags = state["tags"]
        if diary_authoritative:
            item.first_watched_date = min(dates) if dates else None
            item.latest_watched_date = max(dates) if dates else None
            item.watch_count = state["watch_count"]
            item.rewatch_count = state["rewatch_count"]
        elif item.watch_count == 0:
            legacy_date = ratings_by_movie_id.get(movie_id).watched_date if ratings_by_movie_id.get(movie_id) else None
            item.first_watched_date = legacy_date
            item.latest_watched_date = legacy_date
        item.last_seen_profile_sync_id = sync.id
        item.removed_at = None
        result[movie_id] = item

    if all_films_authoritative:
        for movie_id, item in existing.items():
            if movie_id not in states and item.removed_at is None:
                item.removed_at = now
    db.flush()
    return result, len(states)


def _upsert_watch_events(
    *,
    profile_id: int,
    sync: ProfileSync,
    source_kind: str,
    prepared_events: Sequence[Dict[str, Any]],
    profile_films: Mapping[int, ProfileFilm],
    diary_authoritative: bool,
    rating_authoritative: bool,
    rewatch_authoritative: bool,
    likes_authoritative: bool,
    review_state_authoritative: bool,
    tags_authoritative: bool,
    db: Session,
) -> int:
    existing = {
        event.event_key: event
        for event in db.query(WatchEvent).filter(WatchEvent.profile_id == profile_id).all()
    }
    seen_keys = set()
    for payload in prepared_events:
        event_key = payload["event_key"]
        seen_keys.add(event_key)
        event = existing.get(event_key)
        created_event = event is None
        if created_event:
            event = WatchEvent(
                profile_id=profile_id,
                movie_id=payload["movie"].id,
                event_key=event_key,
                first_seen_profile_sync_id=sync.id,
            )
            db.add(event)
        event.movie_id = payload["movie"].id
        event.profile_film = profile_films.get(payload["movie"].id)
        event.watched_date = payload["watched_date"]
        if created_event or rating_authoritative:
            event.rating = payload["rating"]
        if created_event or rewatch_authoritative:
            event.is_rewatch = payload["is_rewatch"]
        if created_event or likes_authoritative:
            event.is_liked = payload["is_liked"]
        if created_event or review_state_authoritative:
            event.has_review = payload["has_review"]
        if created_event or tags_authoritative:
            event.tags = payload["tags"]
        event.source_kind = source_kind
        event.source_entry_id = payload["source_entry_id"] or event.source_entry_id
        event.source_url = payload["source_url"] or event.source_url
        event.source_row_number = payload["source_row_number"]
        event.last_seen_profile_sync_id = sync.id
        event.superseded_at = None
        event.superseded_by_profile_sync_id = None

    if diary_authoritative:
        now = _utcnow()
        for event_key, event in existing.items():
            if event_key not in seen_keys and event.superseded_at is None:
                event.superseded_at = now
                event.superseded_by_profile_sync_id = sync.id
    db.flush()
    return len(prepared_events)


def _upsert_watchlist(
    *,
    analyzer_profile,
    profile_id: int,
    sync: ProfileSync,
    resolver: MovieResolver,
    identity_lookup: Mapping[Tuple[str, Optional[int]], MovieIdentity],
    authoritative: bool,
    db: Session,
) -> int:
    existing = {
        item.movie_id: item
        for item in db.query(WatchlistItem).filter(WatchlistItem.profile_id == profile_id).all()
    }
    seen_movie_ids = set()
    for source_position, row in enumerate(frame_records(getattr(analyzer_profile, "watchlist", pd.DataFrame())), start=1):
        identity = movie_identity_from_row(row)
        if identity is None:
            continue
        identity = _enrich_identity(identity, identity_lookup)
        movie = resolver.resolve(identity)
        if movie.id in seen_movie_ids:
            continue
        seen_movie_ids.add(movie.id)
        item = existing.get(movie.id)
        if item is None:
            item = WatchlistItem(
                profile_id=profile_id,
                movie_id=movie.id,
                first_seen_profile_sync_id=sync.id,
            )
            db.add(item)
        added_date = parse_date(first_value(row, ("Date", "Added Date", "Added_Date")))
        # Public HTML exposes current watchlist membership but not the original
        # add date. Keep a more precise date learned from an account export (or
        # another dated source) instead of erasing it with an undated snapshot.
        if added_date is not None:
            item.added_date = added_date
            item.added_date_source_kind = f"{sync.source_kind}:watchlist"
        item.position = parse_integer(first_value(row, ("Position", "Rank")), minimum=1) or source_position
        item.last_seen_profile_sync_id = sync.id
        item.removed_at = None

    if authoritative:
        now = _utcnow()
        for movie_id, item in existing.items():
            if movie_id not in seen_movie_ids and item.removed_at is None:
                item.removed_at = now
    db.flush()
    return len(seen_movie_ids)


def _upsert_source_activities(
    *,
    analyzer_profile,
    profile_id: int,
    sync: ProfileSync,
    resolver: MovieResolver,
    identity_lookup: Mapping[Tuple[str, Optional[int]], MovieIdentity],
    db: Session,
) -> int:
    """Store official-export dates without upgrading them into watch events."""

    if sync.source_kind != "letterboxd_export":
        return 0

    datasets = (
        ("watched", "watched_marked", "account_activity"),
        ("ratings", "rating_recorded", "account_activity"),
        ("likes", "like_recorded", "account_activity"),
        ("watchlist", "watchlist_added", "watchlist_added"),
    )
    existing = {
        item.activity_key: item
        for item in (
            db.query(ProfileSourceActivity)
            .filter(ProfileSourceActivity.profile_id == profile_id)
            .all()
        )
    }
    seen_keys = set()
    occurrences: Dict[Tuple[str, int, str], int] = defaultdict(int)
    for dataset_name, activity_type, date_semantics in datasets:
        frame = getattr(analyzer_profile, dataset_name, pd.DataFrame())
        for row_number, row in enumerate(frame_records(frame), start=1):
            activity_date = parse_date(first_value(row, ("Date", "Added Date", "Added_Date")))
            identity = movie_identity_from_row(row)
            if identity is None or activity_date is None:
                continue
            identity = _enrich_identity(identity, identity_lookup)
            movie = resolver.resolve(identity)
            occurrence_key = (dataset_name, movie.id, activity_date.isoformat())
            occurrences[occurrence_key] += 1
            activity_key = _stable_digest(
                "source-activity",
                (
                    analyzer_profile.username.casefold(),
                    dataset_name,
                    movie.canonical_key,
                    activity_date.isoformat(),
                    occurrences[occurrence_key],
                ),
            )
            if activity_key in seen_keys:
                continue
            seen_keys.add(activity_key)
            activity = existing.get(activity_key)
            if activity is None:
                activity = ProfileSourceActivity(
                    profile_id=profile_id,
                    movie_id=movie.id,
                    activity_key=activity_key,
                    first_seen_profile_sync_id=sync.id,
                )
                db.add(activity)
            activity.movie_id = movie.id
            activity.activity_type = activity_type
            activity.activity_date = activity_date
            activity.date_semantics = date_semantics
            activity.source_kind = sync.source_kind
            activity.source_dataset = f"{dataset_name}.csv"
            activity.source_row_number = row_number
            activity.last_seen_profile_sync_id = sync.id
    db.flush()
    return len(seen_keys)


def _list_source_key(name: str, url: Optional[str]) -> str:
    normalized_url = normalize_letterboxd_url(url)
    if normalized_url:
        return f"url:{normalized_url.casefold()}"
    return f"name:{normalize_title(name)}"


def _upsert_lists(
    *,
    analyzer_profile,
    profile_id: int,
    sync: ProfileSync,
    resolver: MovieResolver,
    identity_lookup: Mapping[Tuple[str, Optional[int]], MovieIdentity],
    metadata_authoritative: bool,
    db: Session,
) -> Tuple[int, int]:
    existing_lists = db.query(MovieList).filter(MovieList.profile_id == profile_id).all()
    by_key = {item.source_list_key: item for item in existing_lists if item.source_list_key}
    by_name = {normalize_title(item.name): item for item in existing_lists}
    seen_list_ids = set()

    def get_list(name: str, url: Optional[str], row: Optional[Mapping[str, Any]] = None) -> MovieList:
        source_key = _list_source_key(name, url)
        movie_list = by_key.get(source_key) or by_name.get(normalize_title(name))
        if movie_list is None:
            movie_list = MovieList(
                profile_id=profile_id,
                name=name[:200],
                source_list_key=source_key,
                first_seen_profile_sync_id=sync.id,
            )
            db.add(movie_list)
            db.flush()
            by_key[source_key] = movie_list
            by_name[normalize_title(name)] = movie_list
        elif not movie_list.source_list_key:
            movie_list.source_list_key = source_key
        movie_list.name = name[:200]
        movie_list.letterboxd_url = normalize_letterboxd_url(url)
        movie_list.last_seen_profile_sync_id = sync.id
        movie_list.removed_at = None
        if row is not None:
            movie_list.description = clean_text(first_value(row, ("Description", "Notes")))
            movie_list.movie_count = parse_integer(first_value(row, ("Film_Count", "Film Count", "Count")), minimum=0) or 0
            # Ranked/published/tags mirror the is_public presence guard below:
            # a metadata row from a source that does not carry these columns
            # (pre-upgrade scraper bundles, official exports) must preserve
            # previously imported values instead of resetting to defaults.
            ranked_value = first_value(row, ("Ranked", "Is_Ranked", "Is Ranked"))
            if ranked_value is not None:
                movie_list.is_ranked = parse_boolean(ranked_value)
            if first_value(row, ("Private", "Is_Private")) is not None:
                movie_list.is_public = not parse_boolean(first_value(row, ("Private", "Is_Private")))
            elif first_value(row, ("Public", "Is_Public")) is not None:
                movie_list.is_public = parse_boolean(first_value(row, ("Public", "Is_Public")), default=True)
            published_value = first_value(row, ("Published Date", "Published_Date", "Date"))
            if published_value is not None:
                movie_list.published_date = parse_date(published_value)
            tags_value = first_value(row, ("Tags", "List_Tags", "List Tags"))
            if tags_value is not None:
                movie_list.tags = parse_tags(tags_value)
        seen_list_ids.add(movie_list.id)
        return movie_list

    for row in frame_records(getattr(analyzer_profile, "list_metadata", pd.DataFrame())):
        name = clean_text(first_value(row, ("Title", "Name", "List_Name", "List Name")), max_length=200)
        if not name:
            continue
        get_list(name, clean_text(first_value(row, ("URL", "List_URL", "List URL"))), row)

    item_count = 0
    for list_frame in getattr(analyzer_profile, "lists", []) or []:
        if list_frame is None:
            continue
        frame_rows = list(frame_records(list_frame))
        fallback_name = clean_text(list_frame.attrs.get("list_name"), max_length=200)
        if fallback_name is None and not list_frame.empty:
            fallback_name = clean_text(list_frame.iloc[0].get("list_name"), max_length=200)
        first_row = frame_rows[0] if frame_rows else {}
        name = clean_text(first_value(first_row, ("List_Name", "List Name", "list_name")), max_length=200) or fallback_name
        if not name:
            continue
        list_url = clean_text(first_value(first_row, ("List_URL", "List URL")))
        movie_list = get_list(name, list_url)
        # Official list member CSVs may repeat explicit list metadata. Only
        # consume unambiguous list-prefixed fields here: a generic Description
        # belongs to the individual list item, not to the list itself.
        ranked_value = first_value(first_row, ("List_Ranked", "List Ranked"))
        if ranked_value is not None:
            movie_list.is_ranked = parse_boolean(ranked_value)
        private_value = first_value(first_row, ("List_Private", "List Private"))
        public_value = first_value(first_row, ("List_Public", "List Public"))
        if private_value is not None:
            movie_list.is_public = not parse_boolean(private_value)
        elif public_value is not None:
            movie_list.is_public = parse_boolean(public_value, default=True)
        elif sync.source_kind == "letterboxd_export":
            # Account exports can include private lists, but their member CSVs
            # do not consistently expose visibility. Keep them out of public
            # product surfaces until visibility is explicit.
            movie_list.is_public = False
        published_value = first_value(first_row, ("List_Published_Date", "List Published Date"))
        if published_value is not None:
            movie_list.published_date = parse_date(published_value)
        list_tags_value = first_value(first_row, ("List_Tags", "List Tags"))
        if list_tags_value is not None:
            movie_list.tags = parse_tags(list_tags_value)

        # A member CSV is an authoritative snapshot for that list. Temporarily
        # deactivate existing positions before reordering to satisfy the active-position index.
        current_items = {
            item.movie_id: item
            for item in db.query(MovieListItem).filter(MovieListItem.movie_list_id == movie_list.id).all()
        }
        now = _utcnow()
        for item in current_items.values():
            item.removed_at = now
        db.flush()

        seen_movies = set()
        used_positions = set()
        for source_position, row in enumerate(frame_rows, start=1):
            identity = movie_identity_from_row(row)
            if identity is None:
                continue
            identity = _enrich_identity(identity, identity_lookup)
            movie = resolver.resolve(identity)
            if movie.id in seen_movies:
                continue
            seen_movies.add(movie.id)
            position = parse_integer(first_value(row, ("Position", "Rank")), minimum=1) or source_position
            while position in used_positions:
                position += 1
            used_positions.add(position)
            item = current_items.get(movie.id)
            if item is None:
                item = MovieListItem(
                    movie_list_id=movie_list.id,
                    movie_id=movie.id,
                    position=position,
                    first_seen_profile_sync_id=sync.id,
                )
                db.add(item)
            item.position = position
            item.notes = clean_text(first_value(row, ("Notes", "Description")))
            item.last_seen_profile_sync_id = sync.id
            item.removed_at = None
            item_count += 1
        movie_list.movie_count = len(seen_movies)

    if metadata_authoritative:
        now = _utcnow()
        for movie_list in existing_lists:
            if movie_list.id not in seen_list_ids and movie_list.removed_at is None:
                movie_list.removed_at = now
    db.flush()
    return len(seen_list_ids), item_count


def _reconcile_favorites(
    *,
    analyzer_profile,
    profile_id: int,
    sync: ProfileSync,
    resolver: MovieResolver,
    identity_lookup: Mapping[Tuple[str, Optional[int]], MovieIdentity],
    authoritative: bool,
    db: Session,
) -> int:
    if not authoritative:
        return 0

    desired: List[Tuple[int, int]] = []
    seen_movies = set()
    for source_position, row in enumerate(frame_records(getattr(analyzer_profile, "favorites", pd.DataFrame())), start=1):
        if source_position > 4:
            break
        identity = movie_identity_from_row(row)
        if identity is None:
            continue
        identity = _enrich_identity(identity, identity_lookup)
        movie = resolver.resolve(identity)
        if movie.id in seen_movies:
            continue
        seen_movies.add(movie.id)
        desired.append((movie.id, len(desired) + 1))

    existing = db.query(ProfileFavoriteMovie).filter(
        ProfileFavoriteMovie.profile_id == profile_id
    ).all()
    existing_by_movie = {item.movie_id: item for item in existing}
    desired_by_movie = dict(desired)

    # Position uniqueness makes in-place swaps unsafe with immediate database
    # constraints. Preserve stable rows directly; for moved favorites, replace
    # only the constrained membership while retaining its identifier and
    # first-seen lineage. Removed favorites are the only rows not reinserted.
    stable_movie_ids = {
        movie_id
        for movie_id, position in desired
        if (item := existing_by_movie.get(movie_id)) is not None
        and item.position == position
    }
    changed_existing = [item for item in existing if item.movie_id not in stable_movie_ids]
    changed_existing_ids = [item.id for item in changed_existing]
    moved_rows = [
        {
            "id": item.id,
            "profile_id": item.profile_id,
            "movie_id": item.movie_id,
            "position": desired_by_movie[item.movie_id],
            "first_seen_profile_sync_id": item.first_seen_profile_sync_id,
            "last_seen_profile_sync_id": sync.id,
            "created_at": item.created_at,
        }
        for item in changed_existing
        if item.movie_id in desired_by_movie
    ]
    if changed_existing_ids:
        for item in changed_existing:
            db.expunge(item)
        db.execute(
            ProfileFavoriteMovie.__table__.delete().where(
                ProfileFavoriteMovie.id.in_(changed_existing_ids)
            )
        )
        db.flush()

    for values in moved_rows:
        db.execute(ProfileFavoriteMovie.__table__.insert().values(**values))
    if moved_rows:
        db.flush()

    for movie_id, position in desired:
        if movie_id in stable_movie_ids:
            existing_by_movie[movie_id].last_seen_profile_sync_id = sync.id
            continue
        if movie_id in existing_by_movie:
            continue
        db.add(
            ProfileFavoriteMovie(
                profile_id=profile_id,
                movie_id=movie_id,
                position=position,
                first_seen_profile_sync_id=sync.id,
                last_seen_profile_sync_id=sync.id,
            )
        )
    db.flush()
    return len(desired_by_movie)


def _source_present(analyzer_profile, *names: str) -> bool:
    source_files = getattr(analyzer_profile, "source_files", {}) or {}
    return any(name in source_files for name in names)


def _frame_has_any_column(frame: pd.DataFrame, names: Sequence[str]) -> bool:
    return frame is not None and any(name in frame.columns for name in names)


def _update_profile_metadata(profile: Profile, analyzer_profile, sync: ProfileSync, now: datetime) -> None:
    if not _source_present(analyzer_profile, "profile.csv"):
        return
    info = getattr(analyzer_profile, "profile_info", {}) or {}
    profile.display_name = clean_text(
        first_value(info, ("Display_Name", "Display Name")), max_length=200
    )
    profile.bio = clean_text(first_value(info, ("Bio",)))
    profile.location = clean_text(first_value(info, ("Location",)), max_length=100)
    profile.website = clean_text(first_value(info, ("Website",)), max_length=200)
    profile.profile_image_url = clean_text(
        first_value(info, ("Avatar_URL", "Avatar URL")), max_length=500
    )
    # The public HTML scraper currently cannot observe join date. An omitted
    # value therefore means "unknown in this source", not "clear known data".
    if analyzer_profile.join_date is not None:
        profile.join_date = analyzer_profile.join_date

    integer_fields = {
        "following_count": parse_integer(first_value(info, ("Following_Count", "Following Count")), minimum=0),
        "followers_count": parse_integer(first_value(info, ("Followers_Count", "Followers Count")), minimum=0),
        "reported_total_films": parse_integer(first_value(info, ("Total_Films", "Total Films")), minimum=0),
        "reported_total_reviews": parse_integer(first_value(info, ("Total_Reviews", "Total Reviews")), minimum=0),
        "reported_total_lists": parse_integer(first_value(info, ("Total_Lists", "Total Lists")), minimum=0),
    }
    for attribute, value in integer_fields.items():
        if value is not None:
            setattr(profile, attribute, value)
    profile.metadata_synced_at = now


def _dataset_file_names(analyzer_profile, dataset_name: str) -> List[str]:
    source_files = getattr(analyzer_profile, "source_files", {}) or {}
    mapping = {
        "profile": ["profile.csv"],
        "films": ["films.csv", "all_films.csv", "films_comprehensive.csv"],
        "ratings": ["ratings.csv"],
        "watched": ["watched.csv"],
        "diary": ["diary.csv"],
        "reviews": ["reviews.csv"],
        "likes": ["likes.csv", "likes/films.csv"],
        "watchlist": ["watchlist.csv"],
        "comments": ["comments.csv"],
        "lists": ["lists.csv"],
        "favorites": ["favorites.csv"],
    }
    if dataset_name == "list_items":
        return sorted(
            name for name in source_files if name == "list_items.csv" or name.startswith("lists/")
        )
    if dataset_name == "lists" and getattr(analyzer_profile, "source_kind", None) == "letterboxd_export":
        direct = [name for name in mapping["lists"] if name in source_files]
        if direct:
            return direct
        return sorted(name for name in source_files if name.startswith("lists/"))
    return [name for name in mapping.get(dataset_name, []) if name in source_files]


def _upsert_sync_datasets(
    *,
    analyzer_profile,
    sync: ProfileSync,
    imported_counts: Mapping[str, int],
    authoritative: Mapping[str, bool],
    db: Session,
) -> None:
    source_files = getattr(analyzer_profile, "source_files", {}) or {}
    manifest = getattr(analyzer_profile, "manifest", {}) or {}
    unavailable = manifest.get("unavailable_datasets", {}) if isinstance(manifest, dict) else {}
    unavailable = unavailable if isinstance(unavailable, dict) else {}
    existing = {
        dataset.dataset_name: dataset
        for dataset in db.query(SyncDataset).filter(SyncDataset.profile_sync_id == sync.id).all()
    }
    for dataset_name in (
        "profile",
        "films",
        "ratings",
        "watched",
        "diary",
        "reviews",
        "likes",
        "watchlist",
        "comments",
        "lists",
        "list_items",
        "favorites",
    ):
        filenames = _dataset_file_names(analyzer_profile, dataset_name)
        infos = [source_files[name] for name in filenames]
        combined_hash = None
        if infos:
            combined_hash = hashlib.sha256(
                "|".join(str(info.get("sha256") or "") for info in infos).encode("utf-8")
            ).hexdigest()
        dataset = existing.get(dataset_name)
        if dataset is None:
            dataset = SyncDataset(profile_sync_id=sync.id, dataset_name=dataset_name)
            db.add(dataset)
        dataset.source_filename = filenames[0] if len(filenames) == 1 else (f"{len(filenames)} files" if filenames else None)
        dataset.source_sha256 = combined_hash
        dataset.source_row_count = sum(int(info.get("row_count") or 0) for info in infos)
        dataset.imported_row_count = max(int(imported_counts.get(dataset_name, 0)), 0)
        dataset.is_authoritative = bool(authoritative.get(dataset_name, False))
        dataset.metadata_payload = {
            "source_present": bool(filenames),
            "source_files": filenames,
            "unavailable_reason": unavailable.get(dataset_name),
        }
    db.flush()


def _build_coverage(
    *,
    analyzer_profile,
    imported_counts: Mapping[str, int],
    authoritative: Mapping[str, bool],
    skipped_diary_rows: int,
    now: datetime,
) -> Dict[str, Any]:
    source_files = getattr(analyzer_profile, "source_files", {}) or {}
    manifest = getattr(analyzer_profile, "manifest", {}) or {}
    unavailable = manifest.get("unavailable_datasets", {}) if isinstance(manifest, dict) else {}
    unavailable = unavailable if isinstance(unavailable, dict) else {}
    datasets: Dict[str, Any] = {}
    for dataset_name in authoritative:
        filenames = _dataset_file_names(analyzer_profile, dataset_name)
        datasets[dataset_name] = {
            "source_present": bool(filenames),
            "source_rows": sum(int(source_files[name].get("row_count") or 0) for name in filenames),
            "imported_rows": max(int(imported_counts.get(dataset_name, 0)), 0),
            "is_authoritative": bool(authoritative.get(dataset_name, False)),
            "unavailable_reason": unavailable.get(dataset_name),
        }

    limitations: List[str] = []
    if not authoritative.get("diary"):
        limitations.append("Diary history was not included, so timing and rewatch signals may be incomplete.")
    if skipped_diary_rows:
        limitations.append(f"{skipped_diary_rows} diary row(s) lacked a usable movie or watch date.")
    if unavailable.get("watchlist"):
        limitations.append(
            f"Watchlist unavailable ({unavailable['watchlist']}); prior imported state was preserved."
        )
    elif not authoritative.get("watchlist"):
        limitations.append("Watchlist data was not included in this sync.")
    if unavailable.get("lists") or unavailable.get("list_items"):
        reasons = sorted(
            {
                str(unavailable[name])
                for name in ("lists", "list_items")
                if unavailable.get(name)
            }
        )
        limitations.append(
            "Custom lists unavailable ("
            + "; ".join(reasons)
            + "); prior imported state was preserved where applicable."
        )
    elif not authoritative.get("lists") and not authoritative.get("list_items"):
        limitations.append("Custom list data was not included in this sync.")
    elif authoritative.get("lists") and not authoritative.get("list_items"):
        limitations.append("Custom list metadata was imported, but list memberships were not included.")
    if not authoritative.get("profile"):
        limitations.append("Profile metadata was not included in this sync.")

    history_available = bool(
        authoritative.get("films") or authoritative.get("ratings") or authoritative.get("watched")
    )
    complete_surfaces = bool(
        history_available
        and authoritative.get("diary")
        and authoritative.get("watchlist")
        and authoritative.get("lists")
        and authoritative.get("list_items")
    )
    return {
        "mode": getattr(analyzer_profile, "source_kind", "uploaded_csv_bundle"),
        "source": getattr(analyzer_profile, "source_kind", "uploaded_csv_bundle"),
        "is_partial": not complete_surfaces,
        "summary": "Imported Letterboxd datasets with per-surface coverage tracking.",
        "limitations": limitations,
        "unavailable_datasets": unavailable,
        "stats_label": "synced",
        "refreshed_at": now.isoformat(),
        "profile_metadata_available": authoritative.get("profile", False),
        "watchlist_available": authoritative.get("watchlist", False),
        "lists_available": authoritative.get("lists", False) or authoritative.get("list_items", False),
        "list_memberships_available": authoritative.get("list_items", False),
        "diary_available": authoritative.get("diary", False),
        "captured_unique_films": imported_counts.get("profile_films", 0),
        "captured_diary_entries": datasets.get("diary", {}).get("source_rows", 0),
        "imported_watch_events": imported_counts.get("diary", 0),
        "captured_reviews": imported_counts.get("reviews", 0),
        "datasets": datasets,
    }


def _record_failed_sync(analyzer_profile, profile_id: int, error: Exception, db: Session) -> None:
    try:
        source_kind = clean_text(getattr(analyzer_profile, "source_kind", None), max_length=50) or "uploaded_csv_bundle"
        source_fingerprint = clean_text(getattr(analyzer_profile, "source_fingerprint", None), max_length=200) or _stable_digest(
            "bundle", (profile_id, source_kind)
        )
        sync = (
            db.query(ProfileSync)
            .filter(
                ProfileSync.profile_id == profile_id,
                ProfileSync.source_fingerprint == source_fingerprint,
                ProfileSync.importer_version == IMPORTER_VERSION,
            )
            .first()
        )
        if sync is not None and sync.status == "completed":
            db.rollback()
            return
        if sync is None:
            sync = ProfileSync(
                profile_id=profile_id,
                source_kind=source_kind,
                source_fingerprint=source_fingerprint,
                importer_version=IMPORTER_VERSION,
                manifest=getattr(analyzer_profile, "manifest", {}) or {},
                coverage={},
                stats={},
            )
            db.add(sync)
        sync.status = "failed"
        sync.completed_at = _utcnow()
        sync.error_message = str(error)[:4000]
        db.commit()
    except Exception:
        db.rollback()


def unified_data_loader(analyzer_profile, profile_id: int, db: Session):
    """
    Atomically reconcile one authoritative profile snapshot into stored data.

    Existing rows are updated in place where identity is stable, new rows are added,
    source-confirmed removals are reconciled, and normalized watch events retain
    supersession history. Replaying the same source bundle is idempotent.
    """
    try:
        validate_import_bundle(analyzer_profile)
        lock_profile_ingestion(db, profile_id)
        profile = db.query(Profile).filter(Profile.id == profile_id).one()
        sync, was_completed = _get_or_create_sync(analyzer_profile, profile_id, db)
        if was_completed:
            stats = sync.stats if isinstance(sync.stats, dict) else {}
            return int(stats.get("films") or stats.get("profile_films") or 0)

        has_change_baseline = profile.last_profile_sync_id is not None
        before_state = capture_profile_state(db, profile_id)
        resolver = MovieResolver(db, sync.id)
        now = _utcnow()

        all_films = getattr(analyzer_profile, "all_films", pd.DataFrame())
        identity_lookup = _identity_lookup(all_films)
        legacy_movies = _build_legacy_movies(analyzer_profile, profile_id, identity_lookup)

        diary_authoritative = _source_present(analyzer_profile, "diary.csv")
        films_authoritative = _source_present(
            analyzer_profile,
            "films.csv",
            "all_films.csv",
            "films_comprehensive.csv",
        )
        reviews_authoritative = _source_present(analyzer_profile, "reviews.csv")
        ratings_frame = getattr(analyzer_profile, "ratings", pd.DataFrame())
        diary_frame = getattr(analyzer_profile, "diary", pd.DataFrame())
        likes_frame = getattr(analyzer_profile, "likes", pd.DataFrame())
        watched_frame = getattr(analyzer_profile, "watched", pd.DataFrame())
        rating_authoritative = bool(
            _source_present(analyzer_profile, "ratings.csv")
            or _frame_has_any_column(all_films, ("Rating", "Stars"))
        )
        likes_authoritative = bool(
            _source_present(analyzer_profile, "likes.csv", "likes/films.csv")
            or _frame_has_any_column(
                all_films,
                ("Liked", "Is_Liked", "Is Liked"),
            )
            or _frame_has_any_column(
                diary_frame,
                ("Liked", "Is_Liked", "Is Liked"),
            )
        )
        review_state_authoritative = bool(
            reviews_authoritative
            or _frame_has_any_column(
                all_films,
                ("Has_Review", "Has Review"),
            )
            or _frame_has_any_column(
                diary_frame,
                ("Has_Review", "Has Review"),
            )
        )
        tags_authoritative = any(
            _frame_has_any_column(frame, ("Tags", "Tag"))
            for frame in (all_films, ratings_frame, watched_frame, diary_frame, likes_frame)
        )
        diary_rating_authoritative = _frame_has_any_column(
            diary_frame, ("Rating", "Stars")
        )
        diary_rewatch_authoritative = _frame_has_any_column(
            diary_frame, ("Rewatch", "Is_Rewatch", "Is Rewatch")
        )
        diary_likes_authoritative = _frame_has_any_column(
            diary_frame, ("Liked", "Is_Liked", "Is Liked")
        )
        diary_review_state_authoritative = _frame_has_any_column(
            diary_frame, ("Has_Review", "Has Review")
        )
        diary_tags_authoritative = _frame_has_any_column(
            diary_frame, ("Tags", "Tag")
        )

        ratings_by_movie_id, review_count = _reconcile_legacy_rows(
            analyzer_profile=analyzer_profile,
            profile_id=profile_id,
            sync=sync,
            resolver=resolver,
            legacy_movies=legacy_movies,
            identity_lookup=identity_lookup,
            films_authoritative=films_authoritative,
            reviews_authoritative=reviews_authoritative,
            rating_authoritative=rating_authoritative,
            diary_authoritative=diary_authoritative,
            likes_authoritative=likes_authoritative,
            tags_authoritative=tags_authoritative,
            db=db,
        )

        prepared_events, skipped_diary_rows = _prepare_diary_events(
            analyzer_profile=analyzer_profile,
            resolver=resolver,
            identity_lookup=identity_lookup,
        )
        profile_films, profile_film_count = _upsert_profile_films(
            profile_id=profile_id,
            sync=sync,
            legacy_movies=legacy_movies,
            ratings_by_movie_id=ratings_by_movie_id,
            prepared_events=prepared_events,
            resolver=resolver,
            all_films_authoritative=films_authoritative,
            diary_authoritative=diary_authoritative,
            rating_authoritative=rating_authoritative,
            likes_authoritative=likes_authoritative,
            review_state_authoritative=review_state_authoritative,
            tags_authoritative=tags_authoritative,
            db=db,
        )
        event_count = _upsert_watch_events(
            profile_id=profile_id,
            sync=sync,
            source_kind=sync.source_kind,
            prepared_events=prepared_events,
            profile_films=profile_films,
            diary_authoritative=diary_authoritative,
            rating_authoritative=diary_rating_authoritative,
            rewatch_authoritative=diary_rewatch_authoritative,
            likes_authoritative=diary_likes_authoritative,
            review_state_authoritative=diary_review_state_authoritative,
            tags_authoritative=diary_tags_authoritative,
            db=db,
        )

        watchlist_authoritative = _source_present(analyzer_profile, "watchlist.csv")
        watchlist_count = _upsert_watchlist(
            analyzer_profile=analyzer_profile,
            profile_id=profile_id,
            sync=sync,
            resolver=resolver,
            identity_lookup=identity_lookup,
            authoritative=watchlist_authoritative,
            db=db,
        )
        source_activity_count = _upsert_source_activities(
            analyzer_profile=analyzer_profile,
            profile_id=profile_id,
            sync=sync,
            resolver=resolver,
            identity_lookup=identity_lookup,
            db=db,
        )

        list_metadata_authoritative = bool(_dataset_file_names(analyzer_profile, "lists"))
        list_items_authoritative = bool(_dataset_file_names(analyzer_profile, "list_items"))
        list_count, list_item_count = _upsert_lists(
            analyzer_profile=analyzer_profile,
            profile_id=profile_id,
            sync=sync,
            resolver=resolver,
            identity_lookup=identity_lookup,
            metadata_authoritative=list_metadata_authoritative,
            db=db,
        )

        favorites_authoritative = _source_present(analyzer_profile, "favorites.csv")
        favorite_count = _reconcile_favorites(
            analyzer_profile=analyzer_profile,
            profile_id=profile_id,
            sync=sync,
            resolver=resolver,
            identity_lookup=identity_lookup,
            authoritative=favorites_authoritative,
            db=db,
        )

        authoritative = {
            "profile": _source_present(analyzer_profile, "profile.csv"),
            "films": films_authoritative,
            "ratings": _source_present(analyzer_profile, "ratings.csv"),
            "watched": _source_present(analyzer_profile, "watched.csv"),
            "diary": diary_authoritative,
            "reviews": _source_present(analyzer_profile, "reviews.csv"),
            "likes": _source_present(analyzer_profile, "likes.csv", "likes/films.csv"),
            "watchlist": watchlist_authoritative,
            "comments": _source_present(analyzer_profile, "comments.csv"),
            "lists": list_metadata_authoritative,
            "list_items": list_items_authoritative,
            "favorites": favorites_authoritative,
        }
        imported_counts = {
            "profile": int(authoritative["profile"]),
            "films": len(legacy_movies),
            "ratings": sum(1 for rating in ratings_by_movie_id.values() if rating.rating is not None),
            "watched": len(getattr(analyzer_profile, "watched", pd.DataFrame())),
            "diary": event_count,
            "reviews": review_count,
            "likes": len(getattr(analyzer_profile, "likes", pd.DataFrame())),
            "watchlist": watchlist_count,
            "comments": 0,
            "lists": list_count,
            "list_items": list_item_count,
            "favorites": favorite_count,
            "profile_films": profile_film_count,
            "source_activities": source_activity_count,
        }
        coverage = _build_coverage(
            analyzer_profile=analyzer_profile,
            imported_counts=imported_counts,
            authoritative=authoritative,
            skipped_diary_rows=skipped_diary_rows,
            now=now,
        )
        _upsert_sync_datasets(
            analyzer_profile=analyzer_profile,
            sync=sync,
            imported_counts=imported_counts,
            authoritative=authoritative,
            db=db,
        )
        _update_profile_metadata(profile, analyzer_profile, sync, now)

        after_state = capture_profile_state(db, profile_id)
        change_count = record_profile_changes(
            db,
            profile_id=profile_id,
            profile_sync=sync,
            before=before_state,
            after=after_state,
            authoritative=authoritative,
            has_baseline=has_change_baseline,
        )
        imported_counts["changes"] = change_count

        existing_metrics = profile.enhanced_metrics if isinstance(profile.enhanced_metrics, dict) else {}
        profile.enhanced_metrics = {**existing_metrics, "data_coverage": coverage}
        profile.last_profile_sync_id = sync.id
        if films_authoritative or rating_authoritative:
            average_rating = (
                db.query(func.avg(ProfileFilm.rating))
                .filter(
                    ProfileFilm.profile_id == profile_id,
                    ProfileFilm.removed_at.is_(None),
                    ProfileFilm.rating >= 0.5,
                    ProfileFilm.rating <= 5.0,
                )
                .scalar()
            )
            profile.avg_rating = float(average_rating) if average_rating is not None else 0.0
        if reviews_authoritative:
            profile.total_reviews = review_count
        profile.last_scraped_at = now
        profile.scraping_status = "completed"

        # A successful authoritative snapshot resolves any RSS rolling-window
        # gap and establishes a fresh reconciliation boundary.  The next feed
        # poll may safely seed its current GUID window without inferring that
        # older, rolled-off items were deleted.
        feed_state = db.get(ProfileFeedState, profile_id)
        if feed_state is not None and films_authoritative and diary_authoritative:
            feed_state.content_sha256 = None
            feed_state.activity_guids = []
            feed_state.latest_item_guid = None
            feed_state.latest_item_published_at = None
            feed_state.etag = None
            feed_state.last_modified = None
            feed_state.requires_full_sync = False
            feed_state.reconciliation_reason = None
            feed_state.next_poll_at = now

        sync.coverage = coverage
        sync.stats = imported_counts
        sync.status = "completed"
        sync.completed_at = now
        sync.error_message = None
        db.commit()

        print(
            f"Imported {len(legacy_movies)} legacy films, {event_count} diary events, "
            f"{watchlist_count} watchlist items, and {list_item_count} list items for "
            f"{analyzer_profile.username}"
        )
        return len(legacy_movies)
    except Exception as exc:
        db.rollback()
        _record_failed_sync(analyzer_profile, profile_id, exc, db)
        raise
