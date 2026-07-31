from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from sqlalchemy import false, func
from sqlalchemy.orm import Session, joinedload, selectinload

from database.models import (
    MovieList,
    MovieListItem,
    Profile,
    ProfileDataChange,
    ProfileFavoriteMovie,
    ProfileFilm,
    ProfileFollowEdge,
    ProfileSync,
    Review,
    WatchEvent,
    WatchlistItem,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _movie_payload(movie) -> Dict[str, Any]:
    return {
        "id": movie.id,
        "title": movie.title,
        "year": movie.release_year,
        "poster_url": movie.poster_url,
        "letterboxd_url": movie.letterboxd_url,
    }


def _list_key(movie_list: MovieList) -> str:
    return movie_list.source_list_key or f"list-id:{movie_list.id}"


def capture_profile_state(db: Session, profile_id: int) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Capture the semantic profile state used to compute one atomic sync delta.

    The snapshot only lives in memory. Review text, list descriptions, list tags,
    and list-item notes are intentionally excluded from persisted change payloads.
    Notes are reduced to a digest so a change can be detected without copying the
    private text into the audit feed.
    """

    films: Dict[str, Dict[str, Any]] = {}
    for item in (
        db.query(ProfileFilm)
        .options(joinedload(ProfileFilm.movie))
        .filter(ProfileFilm.profile_id == profile_id, ProfileFilm.removed_at.is_(None))
        .all()
    ):
        key = f"movie:{item.movie_id}"
        films[key] = {
            "movie_id": item.movie_id,
            "movie": _movie_payload(item.movie),
            "rating": item.rating,
            "is_liked": bool(item.is_liked),
        }

    watchlist: Dict[str, Dict[str, Any]] = {}
    for item in (
        db.query(WatchlistItem)
        .options(joinedload(WatchlistItem.movie))
        .filter(WatchlistItem.profile_id == profile_id, WatchlistItem.removed_at.is_(None))
        .all()
    ):
        key = f"movie:{item.movie_id}"
        watchlist[key] = {
            "movie_id": item.movie_id,
            "movie": _movie_payload(item.movie),
            "added_date": _iso(item.added_date),
            "added_date_source_kind": item.added_date_source_kind,
        }

    favorites: Dict[str, Dict[str, Any]] = {}
    for item in (
        db.query(ProfileFavoriteMovie)
        .options(joinedload(ProfileFavoriteMovie.movie))
        .filter(ProfileFavoriteMovie.profile_id == profile_id)
        .all()
    ):
        key = f"movie:{item.movie_id}"
        favorites[key] = {
            "movie_id": item.movie_id,
            "movie": _movie_payload(item.movie),
            "position": item.position,
        }

    diary: Dict[str, Dict[str, Any]] = {}
    for event in (
        db.query(WatchEvent)
        .options(joinedload(WatchEvent.movie))
        .filter(WatchEvent.profile_id == profile_id, WatchEvent.superseded_at.is_(None))
        .all()
    ):
        diary[event.event_key] = {
            "movie_id": event.movie_id,
            "movie": _movie_payload(event.movie),
            "watched_date": _iso(event.watched_date),
            "rating": event.rating,
            "is_rewatch": bool(event.is_rewatch),
            "is_liked": bool(event.is_liked),
        }

    reviews: Dict[str, Dict[str, Any]] = {}
    for review in (
        db.query(Review)
        .options(joinedload(Review.movie))
        .filter(Review.profile_id == profile_id, Review.removed_at.is_(None))
        .all()
    ):
        key = review.source_review_key or f"review-id:{review.id}"
        movie = review.movie
        text_digest = (
            hashlib.sha256(review.review_text.encode("utf-8")).hexdigest()
            if review.review_text
            else None
        )
        reviews[key] = {
            "movie_id": review.movie_id,
            "movie": _movie_payload(movie) if movie is not None else {
                "id": None,
                "title": review.movie_title,
                "year": review.movie_year,
                "poster_url": None,
                "letterboxd_url": review.source_url,
            },
            "published_date": _iso(review.published_date),
            "rating": review.rating,
            "likes_count": review.likes_count or 0,
            "comments_count": review.comments_count or 0,
            "contains_spoilers": bool(review.contains_spoilers),
            "text_digest": text_digest,
        }

    lists: Dict[str, Dict[str, Any]] = {}
    list_items: Dict[str, Dict[str, Any]] = {}
    public_lists = (
        db.query(MovieList)
        .options(
            selectinload(MovieList.items).joinedload(MovieListItem.movie),
        )
        .filter(
            MovieList.profile_id == profile_id,
            MovieList.removed_at.is_(None),
            MovieList.is_public.is_(True),
        )
        .all()
    )
    for movie_list in public_lists:
        key = _list_key(movie_list)
        lists[key] = {
            "movie_list_id": movie_list.id,
            "name": movie_list.name,
            "movie_count": movie_list.movie_count or 0,
            "is_ranked": bool(movie_list.is_ranked),
            "published_date": _iso(movie_list.published_date),
            "letterboxd_url": movie_list.letterboxd_url,
        }
        for item in movie_list.items:
            if item.removed_at is not None:
                continue
            entity_key = f"{key}|movie:{item.movie_id}"
            note_digest = (
                hashlib.sha256(item.notes.encode("utf-8")).hexdigest()
                if item.notes
                else None
            )
            list_items[entity_key] = {
                "movie_list_id": movie_list.id,
                "list_name": movie_list.name,
                "movie_id": item.movie_id,
                "movie": _movie_payload(item.movie),
                "position": item.position,
                "note_digest": note_digest,
            }

    following: Dict[str, Dict[str, Any]] = {}
    followers: Dict[str, Dict[str, Any]] = {}
    for edge in (
        db.query(ProfileFollowEdge)
        .filter(
            ProfileFollowEdge.profile_id == profile_id,
            ProfileFollowEdge.removed_at.is_(None),
        )
        .all()
    ):
        payload = {
            "username": edge.counterpart_username,
            "display_name": edge.counterpart_display_name,
            "profile_url": edge.counterpart_profile_url,
            "counterpart_profile_id": edge.counterpart_profile_id,
        }
        target = following if edge.direction == "following" else followers
        target[f"user:{edge.counterpart_username_normalized}"] = payload

    return {
        "films": films,
        "watchlist": watchlist,
        "favorites": favorites,
        "diary": diary,
        "reviews": reviews,
        "lists": lists,
        "list_items": list_items,
        "following": following,
        "followers": followers,
    }


def _safe_item_payload(item: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not item:
        return {}
    return {
        key: value
        for key, value in item.items()
        if key not in {"note_digest", "text_digest"}
    }


def _change_key(change_type: str, entity_key: str) -> str:
    raw = f"{change_type}|{entity_key}"
    if len(raw) <= 600:
        return raw
    return f"{change_type}|sha256:{hashlib.sha256(entity_key.encode('utf-8')).hexdigest()}"


def record_profile_changes(
    db: Session,
    *,
    profile_id: int,
    profile_sync: ProfileSync,
    before: Mapping[str, Mapping[str, Mapping[str, Any]]],
    after: Mapping[str, Mapping[str, Mapping[str, Any]]],
    authoritative: Mapping[str, bool],
    has_baseline: bool,
) -> int:
    """Persist semantic deltas inside the caller's ingestion transaction.

    A first import establishes a baseline and emits no feed entries. This keeps
    old history from appearing as newly observed activity. Replaying a sync is
    idempotent through ``unique_profile_sync_change_key``.
    """

    if not has_baseline:
        return 0

    existing_keys = {
        key
        for (key,) in (
            db.query(ProfileDataChange.change_key)
            .filter(ProfileDataChange.profile_sync_id == profile_sync.id)
            .all()
        )
    }
    queued = 0

    def add(
        change_type: str,
        entity_type: str,
        entity_key: str,
        *,
        source_dataset: str,
        old: Optional[Mapping[str, Any]] = None,
        new: Optional[Mapping[str, Any]] = None,
        before_payload: Optional[Mapping[str, Any]] = None,
        after_payload: Optional[Mapping[str, Any]] = None,
        source_date: Optional[str] = None,
    ) -> None:
        nonlocal queued
        key = _change_key(change_type, entity_key)
        if key in existing_keys:
            return
        reference = new or old or {}
        parsed_source_date = None
        if source_date:
            try:
                parsed_source_date = date.fromisoformat(source_date)
            except (TypeError, ValueError):
                parsed_source_date = None
        db.add(
            ProfileDataChange(
                profile_id=profile_id,
                profile_sync_id=profile_sync.id,
                change_key=key,
                change_type=change_type,
                entity_type=entity_type,
                entity_key=entity_key,
                source_kind=profile_sync.source_kind,
                source_dataset=source_dataset,
                movie_id=reference.get("movie_id"),
                movie_list_id=reference.get("movie_list_id"),
                before_payload=dict(before_payload) if before_payload is not None else _safe_item_payload(old),
                after_payload=dict(after_payload) if after_payload is not None else _safe_item_payload(new),
                source_date=parsed_source_date,
            )
        )
        existing_keys.add(key)
        queued += 1

    def membership_changes(
        surface: str,
        *,
        entity_type: str,
        dataset: str,
        added_type: str,
        removed_type: str,
        date_field: Optional[str] = None,
    ) -> None:
        old_items = before.get(surface, {})
        new_items = after.get(surface, {})
        for entity_key in sorted(set(new_items) - set(old_items)):
            item = new_items[entity_key]
            add(
                added_type,
                entity_type,
                entity_key,
                source_dataset=dataset,
                new=item,
                source_date=item.get(date_field) if date_field else None,
            )
        for entity_key in sorted(set(old_items) - set(new_items)):
            item = old_items[entity_key]
            add(removed_type, entity_type, entity_key, source_dataset=dataset, old=item)

    if authoritative.get("films"):
        membership_changes(
            "films",
            entity_type="film",
            dataset="films",
            added_type="film_added",
            removed_type="film_removed",
        )

    old_films = before.get("films", {})
    new_films = after.get("films", {})
    for entity_key in sorted(set(old_films) & set(new_films)):
        old_item = old_films[entity_key]
        new_item = new_films[entity_key]
        if (authoritative.get("films") or authoritative.get("ratings")) and old_item.get("rating") != new_item.get("rating"):
            add(
                "rating_changed",
                "film",
                entity_key,
                source_dataset="ratings" if authoritative.get("ratings") else "films",
                old=old_item,
                new=new_item,
                before_payload={"rating": old_item.get("rating")},
                after_payload={"rating": new_item.get("rating")},
            )
        if (authoritative.get("films") or authoritative.get("likes")) and bool(old_item.get("is_liked")) != bool(new_item.get("is_liked")):
            add(
                "like_changed",
                "film",
                entity_key,
                source_dataset="likes" if authoritative.get("likes") else "films",
                old=old_item,
                new=new_item,
                before_payload={"is_liked": bool(old_item.get("is_liked"))},
                after_payload={"is_liked": bool(new_item.get("is_liked"))},
            )

    if authoritative.get("watchlist"):
        membership_changes(
            "watchlist",
            entity_type="watchlist",
            dataset="watchlist",
            added_type="watchlist_added",
            removed_type="watchlist_removed",
            date_field="added_date",
        )

    if authoritative.get("following"):
        membership_changes(
            "following",
            entity_type="follow",
            dataset="following",
            added_type="follow_added",
            removed_type="follow_removed",
        )

    if authoritative.get("followers"):
        membership_changes(
            "followers",
            entity_type="follow",
            dataset="followers",
            added_type="follower_gained",
            removed_type="follower_lost",
        )

    if authoritative.get("favorites"):
        membership_changes(
            "favorites",
            entity_type="favorite",
            dataset="favorites",
            added_type="favorite_added",
            removed_type="favorite_removed",
        )
        old_items = before.get("favorites", {})
        new_items = after.get("favorites", {})
        for entity_key in sorted(set(old_items) & set(new_items)):
            old_position = old_items[entity_key].get("position")
            new_position = new_items[entity_key].get("position")
            if old_position != new_position:
                add(
                    "favorite_moved",
                    "favorite",
                    entity_key,
                    source_dataset="favorites",
                    old=old_items[entity_key],
                    new=new_items[entity_key],
                    before_payload={"position": old_position},
                    after_payload={"position": new_position},
                )

    if authoritative.get("diary"):
        membership_changes(
            "diary",
            entity_type="diary",
            dataset="diary",
            added_type="diary_added",
            removed_type="diary_removed",
            date_field="watched_date",
        )

    if authoritative.get("reviews"):
        membership_changes(
            "reviews",
            entity_type="review",
            dataset="reviews",
            added_type="review_added",
            removed_type="review_removed",
            date_field="published_date",
        )
        old_items = before.get("reviews", {})
        new_items = after.get("reviews", {})
        compared_fields = ("published_date", "rating", "likes_count", "comments_count", "contains_spoilers")
        for entity_key in sorted(set(old_items) & set(new_items)):
            text_changed = (
                old_items[entity_key].get("text_digest")
                != new_items[entity_key].get("text_digest")
            )
            changed_fields = [
                field
                for field in compared_fields
                if old_items[entity_key].get(field) != new_items[entity_key].get(field)
            ]
            if changed_fields or text_changed:
                before_payload = {
                    field: old_items[entity_key].get(field)
                    for field in changed_fields
                }
                after_payload = {
                    field: new_items[entity_key].get(field)
                    for field in changed_fields
                }
                if text_changed:
                    before_payload["text_changed"] = True
                    after_payload["text_changed"] = True
                add(
                    "review_updated",
                    "review",
                    entity_key,
                    source_dataset="reviews",
                    old=old_items[entity_key],
                    new=new_items[entity_key],
                    before_payload=before_payload,
                    after_payload=after_payload,
                    source_date=new_items[entity_key].get("published_date"),
                )

    if authoritative.get("lists"):
        membership_changes(
            "lists",
            entity_type="list",
            dataset="lists",
            added_type="list_added",
            removed_type="list_removed",
            date_field="published_date",
        )
        old_items = before.get("lists", {})
        new_items = after.get("lists", {})
        compared_fields = ("name", "movie_count", "is_ranked", "published_date", "letterboxd_url")
        for entity_key in sorted(set(old_items) & set(new_items)):
            changed_fields = [
                field
                for field in compared_fields
                if old_items[entity_key].get(field) != new_items[entity_key].get(field)
            ]
            if changed_fields:
                add(
                    "list_updated",
                    "list",
                    entity_key,
                    source_dataset="lists",
                    old=old_items[entity_key],
                    new=new_items[entity_key],
                    before_payload={field: old_items[entity_key].get(field) for field in changed_fields},
                    after_payload={field: new_items[entity_key].get(field) for field in changed_fields},
                )

    if authoritative.get("list_items"):
        membership_changes(
            "list_items",
            entity_type="list_item",
            dataset="list_items",
            added_type="list_item_added",
            removed_type="list_item_removed",
        )
        old_items = before.get("list_items", {})
        new_items = after.get("list_items", {})
        for entity_key in sorted(set(old_items) & set(new_items)):
            old_item = old_items[entity_key]
            new_item = new_items[entity_key]
            position_changed = old_item.get("position") != new_item.get("position")
            notes_changed = old_item.get("note_digest") != new_item.get("note_digest")
            if position_changed or notes_changed:
                add(
                    "list_item_updated",
                    "list_item",
                    entity_key,
                    source_dataset="list_items",
                    old=old_item,
                    new=new_item,
                    before_payload={
                        "position": old_item.get("position"),
                        "notes_present": bool(old_item.get("note_digest")),
                    },
                    after_payload={
                        "position": new_item.get("position"),
                        "notes_present": bool(new_item.get("note_digest")),
                    },
                )

    db.flush()
    return queued


def get_recent_profile_changes(
    db: Session,
    *,
    usernames: Optional[Sequence[str]] = None,
    profile_ids: Optional[Sequence[int]] = None,
    limit: int = 20,
    since: Optional[datetime] = None,
    latest_sync_only: bool = False,
) -> Dict[str, Any]:
    """Return a bounded, provenance-aware recent-change feed for API routes."""

    bounded_limit = min(max(int(limit), 1), 100)
    query = (
        db.query(ProfileDataChange, Profile, MovieList)
        .join(Profile, Profile.id == ProfileDataChange.profile_id)
        .outerjoin(MovieList, MovieList.id == ProfileDataChange.movie_list_id)
        .filter(Profile.is_active.is_(True))
    )
    normalized_usernames = sorted(
        {
            str(username).strip().casefold()
            for username in usernames or []
            if str(username).strip()
        }
    )
    if profile_ids is not None:
        selected_profile_ids = {int(profile_id) for profile_id in profile_ids}
        query = query.filter(
            Profile.id.in_(selected_profile_ids) if selected_profile_ids else false()
        )
    elif usernames is not None and not normalized_usernames:
        query = query.filter(false())
    elif normalized_usernames:
        query = query.filter(func.lower(Profile.username).in_(normalized_usernames))
    if since is not None:
        query = query.filter(ProfileDataChange.detected_at >= since)
    if latest_sync_only:
        query = query.filter(
            Profile.last_profile_sync_id.is_not(None),
            ProfileDataChange.profile_sync_id == Profile.last_profile_sync_id,
        )

    rows = (
        query.order_by(ProfileDataChange.detected_at.desc(), ProfileDataChange.id.desc())
        .limit(bounded_limit)
        .all()
    )
    changes = []
    for change, profile, movie_list in rows:
        movie = change.movie
        changes.append(
            {
                "id": change.id,
                "change_type": change.change_type,
                "entity_type": change.entity_type,
                "detected_at": change.detected_at.isoformat() if change.detected_at else None,
                "source_date": change.source_date.isoformat() if change.source_date else None,
                "source_kind": change.source_kind,
                "source_dataset": change.source_dataset,
                "username": profile.username,
                "movie": (
                    {
                        "id": movie.id,
                        "title": movie.title,
                        "year": movie.release_year,
                        "poster_url": movie.poster_url,
                    }
                    if movie is not None
                    else None
                ),
                "list": (
                    {"id": movie_list.id, "name": movie_list.name}
                    if movie_list is not None
                    else None
                ),
                "before": change.before_payload or {},
                "after": change.after_payload or {},
            }
        )
    return {
        "generated_at": _utcnow().isoformat(),
        "scope": "latest_sync" if latest_sync_only else "history",
        "changes": changes,
    }
