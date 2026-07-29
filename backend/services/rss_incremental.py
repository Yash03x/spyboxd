from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import (
    Movie,
    Profile,
    ProfileFeedState,
    ProfileFilm,
    ProfileSync,
    Rating,
    Review,
    SyncDataset,
    WatchEvent,
)
from services.import_contracts import (
    MovieIdentity,
    clean_text,
    diary_event_key,
    parse_boolean,
    parse_integer,
    slug_from_url,
)
from services.movie_resolver import MovieResolver
from services.profile_changes import capture_profile_state, record_profile_changes


MAX_RSS_BYTES = 2 * 1024 * 1024
RSS_IMPORTER_VERSION = "1"
DEFAULT_INTERVAL_SECONDS = 10 * 60
DEFAULT_MAX_BACKOFF_SECONDS = 24 * 60 * 60
DEFAULT_LEASE_SECONDS = 5 * 60
_HTTP_TIMEOUT = (5, 20)
_USER_AGENT = "Spyboxd-RSS/1.0 (+https://spyboxd.com)"


class RSSFeedError(ValueError):
    """Raised when a feed cannot be accepted without risking bad data."""


class RSSFeedTooLarge(RSSFeedError):
    """Raised before parsing when a response exceeds the bounded RSS size."""


@dataclass(frozen=True)
class RSSFeedItem:
    guid: str
    content_sha256: str
    title: str
    release_year: Optional[int]
    watched_date: date
    published_at: Optional[datetime]
    published_date: Optional[date]
    rating: Optional[float]
    is_rewatch: bool
    is_liked: bool
    has_review: bool
    review_text: str
    contains_spoilers: bool
    source_url: str
    letterboxd_slug: str
    movie_url: str
    poster_url: Optional[str]
    tmdb_id: Optional[int]
    position: int


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: Optional[datetime]) -> datetime:
    if value is None:
        return _utcnow()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _comparable_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return _aware_utc(value)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _child_text(element: ET.Element, name: str) -> Optional[str]:
    for child in element:
        if _local_name(child.tag) == name:
            return clean_text(child.text)
    return None


def _bounded_rating(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if 0.5 <= parsed <= 5.0 else None


def _parse_pub_date(value: Optional[str]) -> tuple[Optional[datetime], Optional[date]]:
    if not value:
        return None, None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None, None
    published_date = parsed.date()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc), published_date


def _parse_retry_after(value: Optional[str], now: datetime) -> Optional[datetime]:
    if not value:
        return None
    stripped = value.strip()
    if stripped.isdigit():
        return now + timedelta(seconds=int(stripped))
    try:
        parsed = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, OverflowError):
        return None
    return _aware_utc(parsed)


def _safe_letterboxd_link(value: Optional[str]) -> tuple[str, str, str]:
    link = clean_text(value, max_length=500)
    if not link:
        raise RSSFeedError("RSS watch item is missing its Letterboxd link")
    parsed = urlparse(link)
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() != "letterboxd.com":
        raise RSSFeedError("RSS watch item contains a non-Letterboxd link")
    slug = slug_from_url(link)
    if not slug:
        raise RSSFeedError("RSS watch item link has no film slug")
    return link, slug, f"https://letterboxd.com/film/{quote(slug, safe='-')}/"


def _description_fields(raw_description: Optional[str]) -> tuple[Optional[str], str, bool]:
    """Return a safe poster URL and plain review text; raw HTML never escapes."""

    if not raw_description:
        return None, "", False
    soup = BeautifulSoup(raw_description, "html.parser")
    poster_url = None
    image = soup.find("img")
    if image is not None:
        candidate = clean_text(image.get("src"), max_length=500)
        if candidate:
            parsed = urlparse(candidate)
            hostname = (parsed.hostname or "").casefold()
            if parsed.scheme == "https" and (
                hostname == "ltrbxd.com" or hostname.endswith(".ltrbxd.com")
            ):
                poster_url = candidate
    for unsafe in soup.find_all(["script", "style", "template", "iframe", "object"]):
        unsafe.decompose()
    for image_element in soup.find_all("img"):
        image_element.decompose()
    plain_text = soup.get_text("\n", strip=True)
    plain_text = re.sub(r"\n{3,}", "\n\n", plain_text).strip()[:20000]
    spoiler = bool(re.search(r"\b(?:contains?|may contain) spoilers?\b", plain_text, re.I))
    return poster_url, plain_text, spoiler


def _item_digest(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def parse_letterboxd_rss(payload: bytes, *, max_bytes: int = MAX_RSS_BYTES) -> List[RSSFeedItem]:
    """Parse the bounded public RSS format into typed, sanitized watch items.

    ``letterboxd:watchedDate`` is the only accepted watch date. ``pubDate`` is
    retained solely as publication/review provenance and is never substituted
    for a missing watch date.
    """

    effective_max_bytes = min(max(int(max_bytes), 1), MAX_RSS_BYTES)
    if len(payload) > effective_max_bytes:
        raise RSSFeedTooLarge(f"RSS response exceeds {effective_max_bytes} bytes")
    lowered_payload = payload.lower()
    if b"<!doctype" in lowered_payload or b"<!entity" in lowered_payload:
        raise RSSFeedError("RSS document type declarations are not accepted")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise RSSFeedError("RSS response is not valid XML") from exc
    if _local_name(root.tag).casefold() != "rss":
        raise RSSFeedError("response is not an RSS document")

    parsed_items: List[RSSFeedItem] = []
    seen_guids: Dict[str, str] = {}
    for position, element in enumerate(
        (node for node in root.iter() if _local_name(node.tag) == "item"),
        start=1,
    ):
        watched_raw = _child_text(element, "watchedDate")
        if not watched_raw:
            # Letterboxd includes custom-list entries in the same RSS channel.
            # They are not diary evidence and must not become watch events.
            continue
        try:
            watched_date = date.fromisoformat(watched_raw)
        except ValueError as exc:
            raise RSSFeedError("RSS watch item has an invalid watchedDate") from exc

        title = clean_text(_child_text(element, "filmTitle"), max_length=300)
        if not title:
            raise RSSFeedError("RSS watch item is missing filmTitle")
        source_url, slug, movie_url = _safe_letterboxd_link(_child_text(element, "link"))
        raw_guid = clean_text(_child_text(element, "guid"), max_length=200)
        description = _child_text(element, "description")
        poster_url, plain_text, contains_spoilers = _description_fields(description)
        published_at, published_date = _parse_pub_date(_child_text(element, "pubDate"))
        release_year = parse_integer(_child_text(element, "filmYear"), minimum=1800)
        rating = _bounded_rating(_child_text(element, "memberRating"))
        is_rewatch = parse_boolean(_child_text(element, "rewatch"))
        is_liked = parse_boolean(_child_text(element, "memberLike"))
        tmdb_id = parse_integer(_child_text(element, "movieId"), minimum=1)
        has_review = bool(raw_guid and raw_guid.casefold().startswith("letterboxd-review-"))

        semantic_payload = {
            "guid": raw_guid,
            "title": title,
            "year": release_year,
            "watched_date": watched_date.isoformat(),
            "published_at": published_at.isoformat() if published_at else None,
            "rating": rating,
            "rewatch": is_rewatch,
            "liked": is_liked,
            "review": plain_text if has_review else "",
            "source_url": source_url,
            "slug": slug,
            "poster_url": poster_url,
            "tmdb_id": tmdb_id,
        }
        content_sha256 = _item_digest(semantic_payload)
        guid = raw_guid or f"letterboxd-content-{content_sha256}"
        prior_digest = seen_guids.get(guid)
        if prior_digest is not None:
            if prior_digest != content_sha256:
                raise RSSFeedError("RSS contains conflicting entries for one GUID")
            continue
        seen_guids[guid] = content_sha256
        parsed_items.append(
            RSSFeedItem(
                guid=guid,
                content_sha256=content_sha256,
                title=title,
                release_year=release_year,
                watched_date=watched_date,
                published_at=published_at,
                published_date=published_date,
                rating=rating,
                is_rewatch=is_rewatch,
                is_liked=is_liked,
                has_review=has_review,
                review_text=plain_text if has_review else "",
                contains_spoilers=contains_spoilers if has_review else False,
                source_url=source_url,
                letterboxd_slug=slug,
                movie_url=movie_url,
                poster_url=poster_url,
                tmdb_id=tmdb_id,
                position=position,
            )
        )
    return parsed_items


def _default_feed_url(username: str) -> str:
    return f"https://letterboxd.com/{quote(username.strip(), safe='-_')}/rss/"


def _validate_feed_url(url: str, username: str) -> None:
    parsed = urlparse(url)
    expected_path = f"/{quote(username.strip(), safe='-_')}/rss/".casefold()
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").casefold() != "letterboxd.com"
        or parsed.path.casefold() != expected_path
        or parsed.query
        or parsed.fragment
    ):
        raise RSSFeedError("profile feed URL is not the expected Letterboxd RSS endpoint")


def _ensure_feed_state(db: Session, profile: Profile) -> ProfileFeedState:
    state = db.query(ProfileFeedState).filter(ProfileFeedState.profile_id == profile.id).first()
    if state is None:
        state = ProfileFeedState(
            profile_id=profile.id,
            feed_url=_default_feed_url(profile.username),
            activity_guids=[],
            consecutive_failures=0,
            requires_full_sync=False,
        )
        db.add(state)
        db.flush()
    return state


def _authoritative_baseline(db: Session, profile_id: int) -> Optional[ProfileSync]:
    return (
        db.query(ProfileSync)
        .filter(
            ProfileSync.profile_id == profile_id,
            ProfileSync.status == "completed",
            ProfileSync.source_kind != "rss_incremental",
            ProfileSync.datasets.any(
                and_(
                    SyncDataset.dataset_name == "films",
                    SyncDataset.is_authoritative.is_(True),
                )
            ),
            ProfileSync.datasets.any(
                and_(
                    SyncDataset.dataset_name == "diary",
                    SyncDataset.is_authoritative.is_(True),
                )
            ),
        )
        .order_by(ProfileSync.completed_at.desc().nullslast(), ProfileSync.id.desc())
        .first()
    )


def due_profiles(db: Session, *, now: Optional[datetime] = None, limit: int = 50) -> List[Profile]:
    """Return active profiles that are due and are not held by a live lease."""

    instant = _aware_utc(now)
    bounded_limit = min(max(int(limit), 1), 500)
    return (
        db.query(Profile)
        .outerjoin(ProfileFeedState, ProfileFeedState.profile_id == Profile.id)
        .filter(
            Profile.is_active.is_(True),
            or_(
                ProfileFeedState.profile_id.is_(None),
                and_(
                    or_(
                        ProfileFeedState.next_poll_at.is_(None),
                        ProfileFeedState.next_poll_at <= instant,
                    ),
                    or_(
                        ProfileFeedState.lease_until.is_(None),
                        ProfileFeedState.lease_until <= instant,
                    ),
                ),
            ),
        )
        .order_by(ProfileFeedState.next_poll_at.asc().nullsfirst(), Profile.id.asc())
        .limit(bounded_limit)
        .all()
    )


def acquire_profile_feed_lease(
    db: Session,
    profile_id: int,
    *,
    now: Optional[datetime] = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> bool:
    """Acquire and commit a short per-profile lease for a poller process."""

    instant = _aware_utc(now)
    profile = db.query(Profile).filter(Profile.id == profile_id, Profile.is_active.is_(True)).first()
    if profile is None:
        return False
    try:
        _ensure_feed_state(db, profile)
        db.commit()
    except IntegrityError:
        # Another worker may have inserted the one-to-one state after our
        # initial due-profile query. Roll back and compete only on the atomic
        # lease UPDATE below.
        db.rollback()
    # Persist initial state before the conditional update. The UPDATE predicate
    # itself is the compare-and-set, so concurrent workers cannot both acquire
    # an expired lease on PostgreSQL.
    acquired = (
        db.query(ProfileFeedState)
        .filter(
            ProfileFeedState.profile_id == profile_id,
            or_(
                ProfileFeedState.lease_until.is_(None),
                ProfileFeedState.lease_until <= instant,
            ),
        )
        .update(
            {
                ProfileFeedState.lease_until: instant
                + timedelta(seconds=max(int(lease_seconds), 30))
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return bool(acquired)


def _response_header(response: Any, name: str, max_length: int) -> Optional[str]:
    headers = getattr(response, "headers", {}) or {}
    return clean_text(headers.get(name), max_length=max_length)


def _read_limited_content(response: Any, max_bytes: int) -> bytes:
    content_length = _response_header(response, "Content-Length", 50)
    if content_length:
        try:
            parsed_length = int(content_length)
        except ValueError:
            parsed_length = None
        if parsed_length is not None and parsed_length > max_bytes:
            raise RSSFeedTooLarge(f"RSS response exceeds {max_bytes} bytes")

    chunks: List[bytes] = []
    total = 0
    iterator = getattr(response, "iter_content", None)
    if callable(iterator):
        source = iterator(chunk_size=64 * 1024)
    else:
        source = (getattr(response, "content", b""),)
    for chunk in source:
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise RSSFeedTooLarge(f"RSS response exceeds {max_bytes} bytes")
        chunks.append(bytes(chunk))
    return b"".join(chunks)


def _entry_tokens(guid: str) -> set[str]:
    tokens = {guid}
    match = re.search(r"(\d+)$", guid)
    if match:
        tokens.add(match.group(1))
    return tokens


def _event_entry_key(guid: str) -> str:
    match = re.search(r"(\d+)$", guid)
    return match.group(1) if match else guid


def _has_feed_overlap(db: Session, profile_id: int, items: Sequence[RSSFeedItem]) -> bool:
    tokens = sorted({token for item in items for token in _entry_tokens(item.guid)})
    if not tokens:
        return False
    return (
        db.query(WatchEvent.id)
        .filter(
            WatchEvent.profile_id == profile_id,
            WatchEvent.source_entry_id.in_(tokens),
        )
        .first()
        is not None
    )


def _find_event(
    db: Session,
    *,
    profile_id: int,
    movie_id: int,
    item: RSSFeedItem,
    event_key: str,
    claimed_event_ids: set[int],
) -> Optional[WatchEvent]:
    event = (
        db.query(WatchEvent)
        .filter(WatchEvent.profile_id == profile_id, WatchEvent.event_key == event_key)
        .first()
    )
    if event is not None:
        return event

    tokens = _entry_tokens(item.guid)
    event = (
        db.query(WatchEvent)
        .filter(
            WatchEvent.profile_id == profile_id,
            WatchEvent.source_entry_id.in_(tokens),
        )
        .first()
    )
    if event is not None:
        return event

    # Owner exports do not expose viewing IDs. Reuse a unique baseline event
    # for the same film/date instead of manufacturing a duplicate.
    candidates = (
        db.query(WatchEvent)
        .filter(
            WatchEvent.profile_id == profile_id,
            WatchEvent.movie_id == movie_id,
            WatchEvent.watched_date == item.watched_date,
            WatchEvent.superseded_at.is_(None),
        )
        .order_by(WatchEvent.id.asc())
        .all()
    )
    candidates = [candidate for candidate in candidates if candidate.id not in claimed_event_ids]
    if len(candidates) == 1:
        return candidates[0]
    exact = [
        candidate
        for candidate in candidates
        if bool(candidate.is_rewatch) == item.is_rewatch and candidate.rating == item.rating
    ]
    return exact[0] if len(exact) == 1 else None


def _find_or_create_profile_film(
    db: Session,
    *,
    profile_id: int,
    movie: Movie,
    sync: ProfileSync,
) -> tuple[ProfileFilm, bool]:
    profile_film = (
        db.query(ProfileFilm)
        .filter(ProfileFilm.profile_id == profile_id, ProfileFilm.movie_id == movie.id)
        .first()
    )
    created = profile_film is None
    if profile_film is None:
        profile_film = ProfileFilm(
            profile_id=profile_id,
            movie_id=movie.id,
            first_seen_profile_sync_id=sync.id,
            tags=[],
            watch_count=0,
            rewatch_count=0,
            is_liked=False,
            has_review=False,
        )
        db.add(profile_film)
        db.flush()
    profile_film.last_seen_profile_sync_id = sync.id
    profile_film.removed_at = None
    return profile_film, created


def _find_rating(db: Session, profile_id: int, movie: Movie) -> Optional[Rating]:
    rating = (
        db.query(Rating)
        .filter(Rating.profile_id == profile_id, Rating.movie_id == movie.id)
        .first()
    )
    if rating is not None:
        return rating
    year_clause = Rating.movie_year.is_(None) if movie.release_year is None else Rating.movie_year == movie.release_year
    return (
        db.query(Rating)
        .filter(
            Rating.profile_id == profile_id,
            Rating.movie_title == movie.title,
            year_clause,
        )
        .first()
    )


def _review_source_key(
    profile_id: int,
    movie: Movie,
    published_date: Optional[date],
    occurrence: int,
) -> str:
    # This is deliberately byte-for-byte compatible with ingestion._stable_digest
    # and its review key inputs. A later authoritative refresh therefore reuses
    # the RSS-created review instead of reporting a false remove/add pair.
    parts = (
        profile_id,
        movie.canonical_key,
        published_date.isoformat() if published_date else None,
        occurrence,
    )
    raw = "|".join("" if part is None else str(part) for part in parts)
    return f"review:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _find_review(
    db: Session,
    *,
    profile_id: int,
    movie_id: int,
    item: RSSFeedItem,
) -> Optional[Review]:
    review = (
        db.query(Review)
        .filter(
            Review.profile_id == profile_id,
            Review.source_url == item.source_url,
            Review.removed_at.is_(None),
        )
        .first()
    )
    if review is not None:
        return review
    candidates = db.query(Review).filter(
        Review.profile_id == profile_id,
        Review.movie_id == movie_id,
        Review.removed_at.is_(None),
    )
    candidates = candidates.filter(Review.published_date == item.watched_date)
    rows = candidates.limit(2).all()
    return rows[0] if len(rows) == 1 else None


def _next_review_occurrence(
    db: Session,
    *,
    profile_id: int,
    movie_id: int,
    review_date: date,
) -> int:
    query = db.query(func.count(Review.id)).filter(
        Review.profile_id == profile_id,
        Review.movie_id == movie_id,
    )
    query = query.filter(Review.published_date == review_date)
    return int(query.scalar() or 0) + 1


def _set_movie_tmdb_id(db: Session, movie: Movie, tmdb_id: Optional[int]) -> None:
    if not tmdb_id or movie.tmdb_id:
        return
    conflict = db.query(Movie.id).filter(Movie.tmdb_id == tmdb_id, Movie.id != movie.id).first()
    if conflict is None:
        movie.tmdb_id = tmdb_id


def _upsert_rss_items(
    db: Session,
    *,
    profile: Profile,
    sync: ProfileSync,
    items: Sequence[RSSFeedItem],
    initial_seed: bool = False,
) -> Dict[str, int]:
    resolver = MovieResolver(db, sync.id)
    claimed_event_ids: set[int] = set()
    impacted_movies: Dict[int, tuple[Movie, ProfileFilm]] = {}
    created_events = 0
    created_films = 0
    created_ratings = 0
    created_reviews = 0

    # Apply old-to-new so the most recent item supplies the film-level rating.
    ordered = sorted(
        items,
        key=lambda item: (
            item.watched_date,
            item.published_at or datetime.min.replace(tzinfo=timezone.utc),
            item.position,
        ),
    )
    for item in ordered:
        identity = MovieIdentity(
            title=item.title,
            release_year=item.release_year,
            letterboxd_slug=item.letterboxd_slug,
            letterboxd_url=item.movie_url,
            poster_url=item.poster_url,
        )
        movie = resolver.resolve(identity)
        _set_movie_tmdb_id(db, movie, item.tmdb_id)
        profile_film, profile_film_created = _find_or_create_profile_film(
            db,
            profile_id=profile.id,
            movie=movie,
            sync=sync,
        )
        created_films += int(profile_film_created)
        impacted_movies[movie.id] = (movie, profile_film)

        event_key = diary_event_key(
            username=profile.username,
            identity=MovieIdentity(
                title=movie.title,
                release_year=movie.release_year,
                letterboxd_id=movie.letterboxd_id,
                letterboxd_slug=movie.letterboxd_slug,
                letterboxd_url=movie.letterboxd_url,
                poster_url=movie.poster_url,
            ),
            watched_date=item.watched_date,
            occurrence=1,
            source_entry_id=_event_entry_key(item.guid),
        )
        event = _find_event(
            db,
            profile_id=profile.id,
            movie_id=movie.id,
            item=item,
            event_key=event_key,
            claimed_event_ids=claimed_event_ids,
        )
        event_created = event is None
        if event_created:
            event = WatchEvent(
                profile_id=profile.id,
                movie_id=movie.id,
                event_key=event_key,
                source_kind="rss_incremental",
                first_seen_profile_sync_id=sync.id,
                tags=[],
            )
            db.add(event)
            created_events += 1
        event.movie_id = movie.id
        event.profile_film = profile_film
        # The first successful fetch establishes the rolling RSS cursor. Keep
        # the authoritative snapshot's values for entries it already knew,
        # while still importing genuinely new entries that appeared after it.
        # Later RSS revisions to a known GUID are applied normally.
        if event_created or not initial_seed:
            event.watched_date = item.watched_date
            # An omitted RSS rating is not proof that a previously known film
            # rating was removed. Only an authoritative full sync may clear it.
            if item.rating is not None or event_created:
                event.rating = item.rating
            event.is_rewatch = item.is_rewatch
            event.is_liked = item.is_liked
        event.has_review = bool(event.has_review or item.has_review)
        event.source_entry_id = event.source_entry_id or item.guid
        event.source_url = event.source_url or item.source_url
        event.source_row_number = event.source_row_number or item.position
        event.last_seen_profile_sync_id = sync.id
        event.superseded_at = None
        event.superseded_by_profile_sync_id = None
        db.flush()
        claimed_event_ids.add(event.id)

        rating = _find_rating(db, profile.id, movie)
        if rating is None:
            rating = Rating(
                profile_id=profile.id,
                movie_id=movie.id,
                movie_title=movie.title,
                movie_year=movie.release_year,
                letterboxd_id=movie.letterboxd_id,
                film_slug=movie.letterboxd_slug,
                poster_url=movie.poster_url,
                first_seen_profile_sync_id=sync.id,
                tags=[],
            )
            db.add(rating)
            db.flush()
            created_ratings += 1
        rating.movie_id = movie.id
        rating.movie_title = movie.title
        rating.movie_year = movie.release_year
        rating.letterboxd_id = rating.letterboxd_id or movie.letterboxd_id
        rating.film_slug = rating.film_slug or movie.letterboxd_slug
        rating.poster_url = rating.poster_url or movie.poster_url
        rating.last_seen_profile_sync_id = sync.id
        rating.removed_at = None
        profile_film.legacy_rating = rating

        if item.has_review:
            review = _find_review(
                db,
                profile_id=profile.id,
                movie_id=movie.id,
                item=item,
            )
            review_created = review is None
            if review_created:
                occurrence = _next_review_occurrence(
                    db,
                    profile_id=profile.id,
                    movie_id=movie.id,
                    review_date=item.watched_date,
                )
                review = Review(
                    profile_id=profile.id,
                    movie_id=movie.id,
                    source_review_key=_review_source_key(
                        profile.id,
                        movie,
                        item.watched_date,
                        occurrence,
                    ),
                    movie_title=movie.title,
                    movie_year=movie.release_year,
                    letterboxd_id=movie.letterboxd_id,
                    first_seen_profile_sync_id=sync.id,
                    tags=[],
                    likes_count=0,
                    comments_count=0,
                )
                db.add(review)
                created_reviews += 1
            review.movie_id = movie.id
            review.movie_title = movie.title
            review.movie_year = movie.release_year
            review.letterboxd_id = review.letterboxd_id or movie.letterboxd_id
            review.source_url = review.source_url or item.source_url
            # RSS pubDate is useful publication provenance and is independent
            # from the authoritative watch date. It can safely enrich an
            # existing review during the initial cursor seed without changing
            # the review's semantic activity date.
            if item.published_at is not None:
                review.published_at = item.published_at
            if review_created or not initial_seed:
                # The full-loader's Review_Date is the diary/watch date. Keep
                # that compatibility key here; the actual RSS publication
                # timestamp is preserved separately in published_at.
                review.published_date = item.watched_date
                if item.review_text or review_created:
                    review.review_text = item.review_text
                if item.rating is not None or review_created:
                    review.rating = item.rating
            # RSS exposes review prose but no authoritative spoiler flag. Do
            # not infer one from words such as "spoiler" inside the text.
            if review_created:
                review.contains_spoilers = False
            review.last_seen_profile_sync_id = sync.id
            review.removed_at = None

    db.flush()
    for movie_id, (movie, profile_film) in impacted_movies.items():
        events = (
            db.query(WatchEvent)
            .filter(
                WatchEvent.profile_id == profile.id,
                WatchEvent.movie_id == movie_id,
                WatchEvent.superseded_at.is_(None),
            )
            .order_by(WatchEvent.watched_date.asc(), WatchEvent.id.asc())
            .all()
        )
        if not events:
            continue
        latest = events[-1]
        latest_rated = next(
            (event for event in reversed(events) if event.rating is not None),
            None,
        )
        profile_film.first_watched_date = min(event.watched_date for event in events)
        profile_film.latest_watched_date = max(event.watched_date for event in events)
        profile_film.watch_count = len(events)
        profile_film.rewatch_count = sum(bool(event.is_rewatch) for event in events)
        if latest_rated is not None:
            profile_film.rating = latest_rated.rating
        profile_film.is_liked = latest.is_liked
        profile_film.has_review = bool(
            any(event.has_review for event in events)
            or db.query(Review.id)
            .filter(
                Review.profile_id == profile.id,
                Review.movie_id == movie_id,
                Review.removed_at.is_(None),
            )
            .first()
        )
        rating = _find_rating(db, profile.id, movie)
        if rating is not None:
            if latest_rated is not None:
                rating.rating = latest_rated.rating
            rating.watched_date = latest.watched_date
            rating.is_rewatch = latest.is_rewatch
            rating.is_liked = latest.is_liked
            rating.last_seen_profile_sync_id = sync.id
            rating.removed_at = None

    profile.total_reviews = (
        db.query(func.count(Review.id))
        .filter(Review.profile_id == profile.id, Review.removed_at.is_(None))
        .scalar()
        or 0
    )
    average = (
        db.query(func.avg(ProfileFilm.rating))
        .filter(ProfileFilm.profile_id == profile.id, ProfileFilm.removed_at.is_(None))
        .scalar()
    )
    profile.avg_rating = float(average) if average is not None else 0.0
    db.flush()
    return {
        "items": len(items),
        "movies_touched": len(impacted_movies),
        "profile_films_created": created_films,
        "watch_events_created": created_events,
        "ratings_created": created_ratings,
        "reviews_created": created_reviews,
    }


def _add_sync_datasets(
    db: Session,
    *,
    sync: ProfileSync,
    feed_sha256: str,
    items: Sequence[RSSFeedItem],
    stats: Dict[str, int],
) -> None:
    counts = {
        "films": len({(item.letterboxd_slug, item.release_year) for item in items}),
        "ratings": sum(item.rating is not None for item in items),
        "diary": len(items),
        "reviews": sum(item.has_review for item in items),
        "likes": sum(item.is_liked for item in items),
    }
    imported = {
        "films": stats["movies_touched"],
        "ratings": counts["ratings"],
        "diary": len(items),
        "reviews": counts["reviews"],
        "likes": counts["likes"],
    }
    for name in ("films", "ratings", "diary", "reviews", "likes"):
        db.add(
            SyncDataset(
                profile_sync_id=sync.id,
                dataset_name=name,
                source_filename=None,
                source_sha256=feed_sha256,
                source_row_count=counts[name],
                imported_row_count=imported[name],
                is_authoritative=False,
                metadata_payload={
                    "source_present": True,
                    "incremental": True,
                    "absence_is_not_a_deletion": True,
                },
            )
        )


def _next_after_failure(
    now: datetime,
    failures: int,
    interval_seconds: int,
    max_backoff_seconds: int,
) -> datetime:
    exponent = min(max(failures - 1, 0), 10)
    delay = min(max(int(interval_seconds), 60) * (2**exponent), max(int(max_backoff_seconds), 60))
    return now + timedelta(seconds=delay)


def _record_poll_failure(
    db: Session,
    *,
    profile_id: int,
    now: datetime,
    message: str,
    http_status: Optional[int],
    interval_seconds: int,
    max_backoff_seconds: int,
    requires_full_sync: bool = False,
    reconciliation_reason: Optional[str] = None,
    retry_after_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    db.rollback()
    profile = db.query(Profile).filter(Profile.id == profile_id).one()
    state = _ensure_feed_state(db, profile)
    failures = int(state.consecutive_failures or 0) + 1
    state.last_polled_at = now
    state.consecutive_failures = failures
    state.last_http_status = http_status
    state.last_error = clean_text(message, max_length=4000) or "RSS poll failed"
    if requires_full_sync:
        state.requires_full_sync = True
        state.reconciliation_reason = clean_text(reconciliation_reason, max_length=4000)
    state.next_poll_at = _next_after_failure(
        now,
        failures,
        interval_seconds,
        max_backoff_seconds,
    )
    if retry_after_at is not None and retry_after_at > _aware_utc(state.next_poll_at):
        state.next_poll_at = retry_after_at
    state.lease_until = None
    db.commit()
    return {
        "status": "failed",
        "profile_id": profile_id,
        "username": profile.username,
        "http_status": http_status,
        "error": state.last_error,
        "consecutive_failures": failures,
        "next_poll_at": state.next_poll_at.isoformat(),
    }


def _mark_success(
    state: ProfileFeedState,
    *,
    now: datetime,
    interval_seconds: int,
    http_status: int,
    etag: Optional[str] = None,
    last_modified: Optional[str] = None,
) -> None:
    state.last_polled_at = now
    state.last_success_at = now
    state.next_poll_at = now + timedelta(seconds=max(int(interval_seconds), 60))
    state.lease_until = None
    state.consecutive_failures = 0
    state.last_http_status = http_status
    state.last_error = None
    state.requires_full_sync = False
    state.reconciliation_reason = None
    if etag:
        state.etag = etag
    if last_modified:
        state.last_modified = last_modified


def poll_profile_feed(
    db: Session,
    profile: Profile,
    *,
    session: Optional[requests.Session] = None,
    now: Optional[datetime] = None,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    max_backoff_seconds: int = DEFAULT_MAX_BACKOFF_SECONDS,
    max_bytes: int = MAX_RSS_BYTES,
) -> Dict[str, Any]:
    """Conditionally poll and atomically apply one profile's recent RSS window.

    The operation is intentionally additive. A completed authoritative films +
    diary baseline is mandatory, and missing RSS entries never remove or
    supersede rows. If the finite feed no longer overlaps known GUIDs, the
    function reports ``overflow`` and requires another full load.
    """

    instant = _aware_utc(now)
    effective_max_bytes = min(max(int(max_bytes), 1), MAX_RSS_BYTES)
    profile_id = profile.id
    state = _ensure_feed_state(db, profile)
    baseline = _authoritative_baseline(db, profile_id)
    if baseline is None:
        state.last_error = "authoritative films and diary baseline required before RSS polling"
        state.requires_full_sync = True
        state.reconciliation_reason = "authoritative_baseline_required"
        state.next_poll_at = instant + timedelta(seconds=max(int(interval_seconds), 60))
        state.lease_until = None
        db.commit()
        return {
            "status": "baseline_required",
            "profile_id": profile_id,
            "username": profile.username,
            "error": state.last_error,
        }

    if state.requires_full_sync:
        baseline_completed_at = _comparable_utc(baseline.completed_at)
        reconciliation_detected_at = _comparable_utc(state.last_polled_at)
        if (
            state.reconciliation_reason == "rss_window_no_overlap"
            and reconciliation_detected_at is not None
            and (baseline_completed_at is None or baseline_completed_at <= reconciliation_detected_at)
        ):
            state.next_poll_at = instant + timedelta(seconds=max(int(interval_seconds), 60))
            state.lease_until = None
            db.commit()
            return {
                "status": "full_sync_required",
                "profile_id": profile_id,
                "username": profile.username,
                "requires_full_sync": True,
                "error": state.last_error,
            }
        # A newer authoritative snapshot reconciles the finite-window gap. The
        # next request must be unconditional and seeds a fresh GUID window.
        state.requires_full_sync = False
        state.reconciliation_reason = None
        state.last_error = None
        state.activity_guids = []
        state.latest_item_guid = None
        state.latest_item_published_at = None
        state.content_sha256 = None
        state.etag = None
        state.last_modified = None

    initial_seed = bool(
        not state.content_sha256
        and not (state.activity_guids or [])
        and not state.latest_item_guid
    )

    http_status: Optional[int] = None
    retry_after_at: Optional[datetime] = None
    response = None
    client = session or requests.Session()
    owns_session = session is None
    try:
        _validate_feed_url(state.feed_url, profile.username)
        session_headers = getattr(client, "headers", {}) or {}
        configured_user_agent = clean_text(
            session_headers.get("User-Agent"),
            max_length=500,
        ) or _USER_AGENT
        headers = {
            "Accept": "application/rss+xml, application/xml;q=0.9",
            "User-Agent": configured_user_agent,
        }
        if state.etag:
            headers["If-None-Match"] = state.etag
        if state.last_modified:
            headers["If-Modified-Since"] = state.last_modified
        response = client.get(
            state.feed_url,
            headers=headers,
            timeout=_HTTP_TIMEOUT,
            stream=True,
            allow_redirects=False,
        )
        http_status = int(response.status_code)
        etag = _response_header(response, "ETag", 500)
        last_modified = _response_header(response, "Last-Modified", 200)
        if http_status == 304:
            _mark_success(
                state,
                now=instant,
                interval_seconds=interval_seconds,
                http_status=http_status,
                etag=etag,
                last_modified=last_modified,
            )
            db.commit()
            return {
                "status": "not_modified",
                "profile_id": profile_id,
                "username": profile.username,
                "items": 0,
            }
        if http_status != 200:
            if http_status in {429, 503}:
                retry_after_at = _parse_retry_after(
                    _response_header(response, "Retry-After", 200),
                    instant,
                )
            raise RSSFeedError(f"Letterboxd RSS returned HTTP {http_status}")

        body = _read_limited_content(response, effective_max_bytes)
        body_sha256 = hashlib.sha256(body).hexdigest()
        items = parse_letterboxd_rss(body, max_bytes=effective_max_bytes)
        newest = items[0] if items else None

        current_guids = [item.guid for item in items]
        previous_guids = {
            str(guid)
            for guid in (state.activity_guids or [])
            if clean_text(guid, max_length=200)
        }
        no_window_overlap = bool(previous_guids and previous_guids.isdisjoint(current_guids))
        legacy_no_overlap = bool(
            not previous_guids
            and state.latest_item_guid
            and state.latest_item_guid not in set(current_guids)
            and not _has_feed_overlap(db, profile_id, items)
        )
        if no_window_overlap or legacy_no_overlap:
            result = _record_poll_failure(
                db,
                profile_id=profile_id,
                now=instant,
                message="RSS recent window has no overlap with stored GUIDs; full sync required",
                http_status=http_status,
                interval_seconds=interval_seconds,
                max_backoff_seconds=max_backoff_seconds,
                requires_full_sync=True,
                reconciliation_reason="rss_window_no_overlap",
            )
            result["status"] = "overflow"
            result["requires_full_sync"] = True
            return result

        if state.content_sha256 == body_sha256 and (
            newest is None or state.latest_item_guid == newest.guid
        ):
            _mark_success(
                state,
                now=instant,
                interval_seconds=interval_seconds,
                http_status=http_status,
                etag=etag,
                last_modified=last_modified,
            )
            db.commit()
            return {
                "status": "unchanged",
                "profile_id": profile_id,
                "username": profile.username,
                "items": len(items),
            }

        activity_sha256 = hashlib.sha256(
            "\n".join(
                sorted(f"{item.guid}:{item.content_sha256}" for item in items)
            ).encode("utf-8")
        ).hexdigest()
        fingerprint = f"rss:{activity_sha256}"
        existing_sync = (
            db.query(ProfileSync)
            .filter(
                ProfileSync.profile_id == profile_id,
                ProfileSync.source_fingerprint == fingerprint,
                ProfileSync.importer_version == RSS_IMPORTER_VERSION,
                ProfileSync.status.in_(("completed", "skipped")),
            )
            .first()
        )
        if existing_sync is not None:
            _mark_success(
                state,
                now=instant,
                interval_seconds=interval_seconds,
                http_status=http_status,
                etag=etag,
                last_modified=last_modified,
            )
            state.content_sha256 = body_sha256
            state.activity_guids = current_guids[:250]
            if newest is not None:
                state.latest_item_guid = newest.guid
                state.latest_item_published_at = newest.published_at
            db.commit()
            return {
                "status": "unchanged",
                "profile_id": profile_id,
                "username": profile.username,
                "items": len(items),
                "profile_sync_id": existing_sync.id,
            }

        if not items:
            _mark_success(
                state,
                now=instant,
                interval_seconds=interval_seconds,
                http_status=http_status,
                etag=etag,
                last_modified=last_modified,
            )
            state.content_sha256 = body_sha256
            state.activity_guids = []
            db.commit()
            return {
                "status": "unchanged",
                "profile_id": profile_id,
                "username": profile.username,
                "items": 0,
            }

        before_state = capture_profile_state(db, profile_id)
        guid_digest = hashlib.sha256(
            "\n".join(item.guid for item in items).encode("utf-8")
        ).hexdigest()
        sync = ProfileSync(
            profile_id=profile_id,
            source_kind="rss_incremental",
            source_fingerprint=fingerprint,
            importer_version=RSS_IMPORTER_VERSION,
            status="running",
            started_at=instant,
            manifest={
                "schema_version": 1,
                "source": "letterboxd_rss",
                "feed_url": state.feed_url,
                "feed_sha256": body_sha256,
                "activity_sha256": activity_sha256,
                "item_guids_sha256": guid_digest,
                "item_count": len(items),
                "baseline_profile_sync_id": baseline.id,
                "absence_is_not_a_deletion": True,
            },
            coverage={
                "mode": "rss_incremental",
                "source": "letterboxd_rss",
                "is_partial": True,
                "baseline_profile_sync_id": baseline.id,
                "summary": "Recent RSS activity layered onto an authoritative full snapshot.",
            },
            stats={},
        )
        db.add(sync)
        db.flush()
        stats = _upsert_rss_items(
            db,
            profile=profile,
            sync=sync,
            items=items,
            initial_seed=initial_seed,
        )
        after_state = capture_profile_state(db, profile_id)
        change_count = record_profile_changes(
            db,
            profile_id=profile_id,
            profile_sync=sync,
            before=before_state,
            after=after_state,
            authoritative={
                "films": True,
                "ratings": True,
                "likes": True,
                "diary": True,
                "reviews": True,
            },
            has_baseline=True,
        )
        stats["initial_seed"] = initial_seed
        stats["changes"] = change_count
        _add_sync_datasets(
            db,
            sync=sync,
            feed_sha256=activity_sha256,
            items=items,
            stats=stats,
        )
        sync.stats = stats
        sync.status = "completed" if change_count else "skipped"
        sync.completed_at = instant
        sync.error_message = None
        if change_count:
            profile.last_profile_sync_id = sync.id

        _mark_success(
            state,
            now=instant,
            interval_seconds=interval_seconds,
            http_status=http_status,
            etag=etag,
            last_modified=last_modified,
        )
        state.content_sha256 = body_sha256
        state.activity_guids = current_guids[:250]
        state.latest_item_guid = newest.guid
        state.latest_item_published_at = newest.published_at
        if change_count:
            state.last_changed_at = instant
        db.commit()
        return {
            "status": "updated" if change_count else "unchanged",
            "profile_id": profile_id,
            "username": profile.username,
            "profile_sync_id": sync.id,
            **stats,
        }
    except Exception as exc:
        return _record_poll_failure(
            db,
            profile_id=profile_id,
            now=instant,
            message=str(exc) or exc.__class__.__name__,
            http_status=http_status,
            interval_seconds=interval_seconds,
            max_backoff_seconds=max_backoff_seconds,
            retry_after_at=retry_after_at,
        )
    finally:
        if response is not None:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        if owns_session:
            client.close()
