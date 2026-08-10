"""Opt-in TMDB enrichment service; never imported by the profile ingestion path."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from sqlalchemy.orm import Session

from database.models import Movie, MovieEnrichment, MovieWatchProvider
from services.import_contracts import normalize_title
from services.tmdb_client import TMDBClient, TMDBError


DEFAULT_CACHE_DAYS = 30
DEFAULT_REGION = "DE"
DEFAULT_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
DEFAULT_PROVIDER_LOGO_BASE_URL = "https://image.tmdb.org/t/p/original"
PROVIDER_TYPES = ("flatrate", "rent", "buy", "free", "ads")
TMDB_LOOKUP_MATCHER_VERSION = 1


@dataclass(frozen=True)
class EnrichmentCandidate:
    movie_id: int
    title: str
    release_year: Optional[int]
    tmdb_id: Optional[int]
    needs_details: bool
    needs_providers: bool


@dataclass(frozen=True)
class PreparedEnrichment:
    candidate: EnrichmentCandidate
    tmdb_id: int
    details: Optional[Dict[str, Any]]
    providers: Optional[Dict[str, Any]]


@dataclass
class EnrichmentStats:
    selected: int = 0
    searched: int = 0
    details_fetched: int = 0
    provider_fetches: int = 0
    enriched: int = 0
    not_found: int = 0
    not_found_cached: int = 0
    identity_conflicts: int = 0
    identity_conflicts_cached: int = 0
    failed: int = 0
    provider_rows: int = 0
    dry_run: bool = False
    identity_conflict_details: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _aware_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return _aware_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def _parse_iso_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _positive_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _provider_region_expiry(raw_payload: Any, region: str) -> Optional[datetime]:
    metadata = _as_dict(_as_dict(raw_payload).get("_spyboxd"))
    expiries = _as_dict(metadata.get("provider_region_expires_at"))
    return _parse_iso_datetime(expiries.get(region.upper()))


def _tmdb_lookup_key(
    title: str,
    release_year: Optional[int],
    language: str,
) -> str:
    """Fingerprint every input that can change a cached identity-search result."""
    payload = {
        "language": language.strip().casefold(),
        "matcher_version": TMDB_LOOKUP_MATCHER_VERSION,
        "normalized_title": normalize_title(title),
        "release_year": release_year,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _certification_for_region(details: Mapping[str, Any], region: str) -> Optional[str]:
    releases = _as_dict(details.get("release_dates"))
    country_groups = _as_list(releases.get("results"))
    matching_groups = [
        group
        for group in country_groups
        if isinstance(group, Mapping) and str(group.get("iso_3166_1") or "").upper() == region.upper()
    ]
    for group in matching_groups:
        release_rows = sorted(
            (row for row in _as_list(group.get("release_dates")) if isinstance(row, Mapping)),
            key=lambda row: (
                0 if row.get("type") in {3, 4} else 1,
                str(row.get("release_date") or ""),
            ),
        )
        for row in release_rows:
            certification = str(row.get("certification") or "").strip()
            if certification:
                return certification
    return None


# Cast kept in the summary, by billing order. The panels read the top five and
# insights reads the top eight; eight is the larger, so eight is what is kept.
SUMMARY_CAST_LIMIT = 8


def summarize_credits(credits: Any) -> Dict[str, Any]:
    """The three facts the panels read out of a TMDB credits document.

    A full credits payload averages 22KB — a hundred-plus crew entries and
    forty cast, each carrying `profile_path`, `credit_id`, `popularity` and
    `known_for_department`. Every panel that touches it reads names, job
    titles, and the gender of directors. Loading one profile's library shipped
    36MB of JSON to use about a sixth of it, which is what made the stats panel
    take seven seconds in production.

    Crew is kept whole rather than filtered to the job titles used today: a
    whitelist would silently return nothing the first time a panel asked for a
    job nobody had listed, and the fields are what cost, not the rows.
    """

    payload = _as_dict(credits)
    crew = [
        {"name": member.get("name"), "job": member.get("job"), "gender": member.get("gender")}
        for member in _as_list(payload.get("crew"))
        if isinstance(member, Mapping) and member.get("name")
    ]
    # `order` is carried, not dropped. TMDB's order values skip -- a film can
    # bill 0,1,2,3,5 -- so "the first five entries" and "order below five" are
    # different sets, and a reader that had to fall back on position would
    # quietly bill a sixth actor. Keeping the number lets every caller apply
    # the same rule it applied to the full document.
    cast = [
        {"name": member.get("name"), "order": order}
        for index, member in enumerate(_as_list(payload.get("cast")))
        if isinstance(member, Mapping)
        and member.get("name")
        and (order := member.get("order") if isinstance(member.get("order"), int) else index)
        < SUMMARY_CAST_LIMIT
    ]
    return {"crew": crew, "cast": cast}


def collection_name(payload: Any) -> Optional[str]:
    """The franchise TMDB places a film in, if any.

    Most films belong to none, which is why this is nullable rather than a
    bucket: a standalone film is not a one-film franchise.
    """

    if not isinstance(payload, Mapping):
        return None
    return str(payload.get("name") or "").strip() or None


def build_enrichment_values(details: Mapping[str, Any]) -> Dict[str, Any]:
    """Map a TMDB detail response to typed MovieEnrichment fields."""
    keywords_payload = _as_dict(details.get("keywords"))
    keywords = _as_list(keywords_payload.get("keywords") or keywords_payload.get("results"))
    credits_payload = _as_dict(details.get("credits"))
    credits = {
        "cast": _as_list(credits_payload.get("cast"))[:40],
        "crew": _as_list(credits_payload.get("crew"))[:120],
    }
    return {
        "original_title": str(details.get("original_title") or "").strip() or None,
        "overview": str(details.get("overview") or "").strip() or None,
        # TMDB writes 0 for a runtime nobody has filled in, and `_positive_int`
        # keeps zero because other callers (display_priority) legitimately use
        # it. A film of zero minutes does not exist, so store the absence: 55
        # rows arrived as 0 before this and had to be defended against on every
        # read, once landing 27 films in a "Under 90 min" taste bucket.
        "runtime_minutes": _positive_int(details.get("runtime")) or None,
        "original_language": str(details.get("original_language") or "").strip() or None,
        "release_date": _parse_iso_date(details.get("release_date")),
        "genres": _as_list(details.get("genres")),
        "keywords": keywords,
        "credits": credits,
        # Written alongside the full document, not instead of it: the whole
        # payload stays the record of what TMDB said, and this is the part the
        # panels read without paying for the rest.
        "credits_summary": summarize_credits(credits),
        "production_countries": _as_list(details.get("production_countries")),
        # Promoted out of raw_payload. Reading them back by JSON path made
        # Postgres detoast the whole payload, which was 65% of the film query.
        "production_companies": _as_list(details.get("production_companies")),
        "spoken_languages": _as_list(details.get("spoken_languages")),
        "collection_name": collection_name(details.get("belongs_to_collection")),
        "poster_path": str(details.get("poster_path") or "").strip() or None,
        "backdrop_path": str(details.get("backdrop_path") or "").strip() or None,
    }


def provider_rows_for_region(
    payload: Mapping[str, Any],
    *,
    region: str,
    logo_base_url: str = DEFAULT_PROVIDER_LOGO_BASE_URL,
) -> List[Dict[str, Any]]:
    """Flatten TMDB's per-country watch-provider payload for one region."""
    normalized_region = region.upper()
    country_payload = _as_dict(_as_dict(payload.get("results")).get(normalized_region))
    link = str(country_payload.get("link") or "").strip() or None
    records: List[Dict[str, Any]] = []
    seen = set()
    for provider_type in PROVIDER_TYPES:
        for provider in _as_list(country_payload.get(provider_type)):
            if not isinstance(provider, Mapping):
                continue
            provider_id = _positive_int(provider.get("provider_id"))
            provider_name = str(provider.get("provider_name") or "").strip()
            if provider_id is None or not provider_name:
                continue
            identity = (provider_id, provider_type)
            if identity in seen:
                continue
            seen.add(identity)
            raw_logo = str(provider.get("logo_path") or "").strip()
            logo_path = (
                f"{logo_base_url.rstrip('/')}/{raw_logo.lstrip('/')}"
                if raw_logo
                else None
            )
            records.append(
                {
                    "region": normalized_region,
                    "provider_id": provider_id,
                    "provider_name": provider_name,
                    "provider_type": provider_type,
                    "logo_path": logo_path,
                    "display_priority": _positive_int(provider.get("display_priority")),
                    "link": link,
                }
            )
    return records


def _select_candidates(
    db: Session,
    *,
    region: str,
    now: datetime,
    refresh: bool,
    limit: Optional[int],
    movie_ids: Optional[Sequence[int]],
    language: str,
) -> List[EnrichmentCandidate]:
    query = (
        db.query(
            Movie.id,
            Movie.title,
            Movie.release_year,
            Movie.tmdb_id,
            MovieEnrichment.movie_id,
            MovieEnrichment.expires_at,
            MovieEnrichment.raw_payload,
            Movie.tmdb_lookup_attempted_at,
            Movie.tmdb_lookup_expires_at,
            Movie.tmdb_lookup_key,
        )
        .outerjoin(MovieEnrichment, MovieEnrichment.movie_id == Movie.id)
        .order_by(Movie.id)
    )
    if movie_ids:
        query = query.filter(Movie.id.in_(list(dict.fromkeys(int(value) for value in movie_ids))))

    existing_provider_movie_ids = {
        movie_id
        for (movie_id,) in (
            db.query(MovieWatchProvider.movie_id)
            .filter(MovieWatchProvider.region == region)
            .distinct()
            .all()
        )
    }

    ranked_candidates: List[tuple[tuple[int, int, int, int], EnrichmentCandidate]] = []
    for (
        movie_id,
        title,
        release_year,
        tmdb_id,
        enrichment_movie_id,
        expires_at,
        raw_payload,
        tmdb_lookup_attempted_at,
        tmdb_lookup_expires_at,
        tmdb_lookup_key,
    ) in query.all():
        lookup_attempted_at = _aware_utc(tmdb_lookup_attempted_at)
        lookup_expiry = _aware_utc(tmdb_lookup_expires_at)
        current_lookup_key = _tmdb_lookup_key(title, release_year, language)
        lookup_inputs_match = tmdb_lookup_key == current_lookup_key
        if (
            tmdb_id is None
            and not refresh
            and lookup_expiry is not None
            and lookup_expiry > now
            and lookup_inputs_match
        ):
            continue
        details_expiry = _aware_utc(expires_at)
        details_are_stale = details_expiry is None or details_expiry <= now
        provider_expiry = _provider_region_expiry(raw_payload, region)
        providers_are_stale = provider_expiry is None or provider_expiry <= now
        if provider_expiry is None and movie_id in existing_provider_movie_ids and not details_are_stale:
            providers_are_stale = False

        needs_details = refresh or tmdb_id is None or details_are_stale
        needs_providers = refresh or needs_details or providers_are_stale
        if not needs_details and not needs_providers:
            continue
        candidate = EnrichmentCandidate(
            movie_id=int(movie_id),
            title=title,
            release_year=release_year,
            tmdb_id=int(tmdb_id) if tmdb_id is not None else None,
            needs_details=needs_details,
            needs_providers=needs_providers,
        )
        # A bounded timer must not let newly imported movies wait behind a
        # large synchronized cache-expiry backlog or expired negative lookups.
        # Manual/unbounded runs still receive every eligible candidate; this
        # changes only processing order.
        ranked_candidates.append(
            (
                (
                    0 if enrichment_movie_id is None else 1,
                    0 if lookup_attempted_at is None or not lookup_inputs_match else 1,
                    0 if tmdb_id is None else 1,
                    int(movie_id),
                ),
                candidate,
            )
        )
    ranked_candidates.sort(key=lambda item: item[0])
    candidates = [candidate for _, candidate in ranked_candidates]
    return candidates[:limit] if limit is not None else candidates


def _chunks(values: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _existing_tmdb_owners(
    db: Session,
    tmdb_ids: Iterable[int],
) -> Dict[int, tuple[int, str]]:
    unique_ids = list(dict.fromkeys(int(tmdb_id) for tmdb_id in tmdb_ids))
    if not unique_ids:
        return {}
    return {
        int(tmdb_id): (int(movie_id), str(title or ""))
        for tmdb_id, movie_id, title in (
            db.query(Movie.tmdb_id, Movie.id, Movie.title)
            .filter(Movie.tmdb_id.in_(unique_ids))
            .all()
        )
        if tmdb_id is not None
    }


def _prepare_candidate(
    client: TMDBClient,
    candidate: EnrichmentCandidate,
    *,
    language: str,
) -> Optional[PreparedEnrichment]:
    tmdb_id = candidate.tmdb_id
    if tmdb_id is None:
        matched = client.find_movie(
            candidate.title,
            release_year=candidate.release_year,
            language=language,
        )
        if not matched:
            return None
        tmdb_id = _positive_int(matched.get("id"))
        if tmdb_id is None or tmdb_id == 0:
            return None

    details = (
        client.get_movie_details(tmdb_id, language=language)
        if candidate.needs_details
        else None
    )
    providers = (
        client.get_movie_watch_providers(tmdb_id)
        if candidate.needs_providers
        else None
    )
    return PreparedEnrichment(
        candidate=candidate,
        tmdb_id=tmdb_id,
        details=details,
        providers=providers,
    )


def _persist_prepared(
    db: Session,
    prepared: PreparedEnrichment,
    *,
    region: str,
    fetched_at: datetime,
    expires_at: datetime,
) -> int:
    movie = db.get(Movie, prepared.candidate.movie_id)
    if movie is None:
        raise ValueError(f"Movie {prepared.candidate.movie_id} disappeared during enrichment")
    movie.tmdb_id = prepared.tmdb_id
    movie.tmdb_lookup_attempted_at = None
    movie.tmdb_lookup_expires_at = None
    movie.tmdb_lookup_key = None

    enrichment = db.get(MovieEnrichment, movie.id)
    if enrichment is None:
        enrichment = MovieEnrichment(movie_id=movie.id)
        db.add(enrichment)

    raw_payload = dict(enrichment.raw_payload or {})
    if prepared.details is not None:
        details = prepared.details
        values = build_enrichment_values(details)
        for key, value in values.items():
            setattr(enrichment, key, value)
        external_ids = _as_dict(details.get("external_ids"))
        imdb_id = str(external_ids.get("imdb_id") or details.get("imdb_id") or "").strip()
        if imdb_id:
            movie.imdb_id = imdb_id
        # Letterboxd resolves posters client-side, so a scraped poster may be
        # their static empty-poster placeholder. Treat that as absent, or the
        # placeholder permanently blocks the real artwork.
        poster_is_placeholder = bool(movie.poster_url) and "empty-poster" in movie.poster_url
        if (not movie.poster_url or poster_is_placeholder) and values.get("poster_path"):
            image_base_url = os.getenv("TMDB_IMAGE_BASE_URL", DEFAULT_IMAGE_BASE_URL)
            movie.poster_url = f"{image_base_url.rstrip('/')}/{str(values['poster_path']).lstrip('/')}"
        raw_payload["details"] = details
        raw_payload["certification"] = _certification_for_region(details, region)
        enrichment.fetched_at = fetched_at
        enrichment.expires_at = expires_at

    inserted_provider_rows = 0
    if prepared.providers is not None:
        provider_rows = provider_rows_for_region(
            prepared.providers,
            region=region,
            logo_base_url=os.getenv(
                "TMDB_PROVIDER_LOGO_BASE_URL",
                DEFAULT_PROVIDER_LOGO_BASE_URL,
            ),
        )
        (
            db.query(MovieWatchProvider)
            .filter(
                MovieWatchProvider.movie_id == movie.id,
                MovieWatchProvider.region == region,
            )
            .delete(synchronize_session=False)
        )
        for provider_row in provider_rows:
            db.add(
                MovieWatchProvider(
                    movie_id=movie.id,
                    fetched_at=fetched_at,
                    **provider_row,
                )
            )
        inserted_provider_rows = len(provider_rows)
        raw_payload["watch_providers"] = prepared.providers
        metadata = dict(_as_dict(raw_payload.get("_spyboxd")))
        region_expiries = dict(_as_dict(metadata.get("provider_region_expires_at")))
        region_expiries[region] = expires_at.isoformat()
        metadata["provider_region_expires_at"] = region_expiries
        metadata["last_provider_region"] = region
        raw_payload["_spyboxd"] = metadata

    enrichment.raw_payload = raw_payload
    db.flush()
    return inserted_provider_rows


def _persist_lookup_deferral(
    db: Session,
    candidate: EnrichmentCandidate,
    *,
    attempted_at: datetime,
    expires_at: datetime,
    lookup_key: str,
) -> bool:
    movie = db.get(Movie, candidate.movie_id)
    if movie is None:
        raise ValueError(f"Movie {candidate.movie_id} disappeared during enrichment")
    # RSS or another trusted ingestion path may have supplied the identity
    # while the network search was running. Never overwrite that newer fact
    # with a stale negative lookup.
    if movie.tmdb_id is not None:
        return False
    movie.tmdb_lookup_attempted_at = attempted_at
    movie.tmdb_lookup_expires_at = expires_at
    movie.tmdb_lookup_key = lookup_key
    db.flush()
    return True


def enrich_movies(
    db: Session,
    client: Optional[TMDBClient],
    *,
    region: str = DEFAULT_REGION,
    language: str = "en-US",
    cache_days: int = DEFAULT_CACHE_DAYS,
    batch_size: int = 25,
    limit: Optional[int] = None,
    movie_ids: Optional[Sequence[int]] = None,
    refresh: bool = False,
    dry_run: bool = False,
    progress: Optional[Callable[[int, int, EnrichmentCandidate], None]] = None,
) -> EnrichmentStats:
    """Enrich selected canonical movies using a dedicated, caller-owned session.

    The function controls transactions on ``db``. It selects candidates first,
    closes that read transaction, performs HTTP requests without holding database
    locks, and persists each prepared batch atomically with per-movie savepoints.
    """
    normalized_region = region.strip().upper()
    if len(normalized_region) != 2 or not normalized_region.isalpha():
        raise ValueError("region must be a two-letter country code")
    if cache_days <= 0:
        raise ValueError("cache_days must be positive")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive when provided")

    now = datetime.now(timezone.utc)
    candidates = _select_candidates(
        db,
        region=normalized_region,
        now=now,
        refresh=refresh,
        limit=limit,
        movie_ids=movie_ids,
        language=language,
    )
    # End the read transaction before any potentially slow network request.
    db.rollback()

    stats = EnrichmentStats(selected=len(candidates), dry_run=dry_run)
    if dry_run or not candidates:
        return stats
    if client is None:
        raise ValueError("client is required unless dry_run is enabled")

    completed = 0
    for candidate_batch in _chunks(candidates, batch_size):
        prepared_batch: List[PreparedEnrichment] = []
        missed_batch: List[EnrichmentCandidate] = []
        for candidate in candidate_batch:
            if progress:
                progress(completed + 1, len(candidates), candidate)
            try:
                if candidate.tmdb_id is None:
                    stats.searched += 1
                prepared = _prepare_candidate(client, candidate, language=language)
                if prepared is None:
                    stats.not_found += 1
                    missed_batch.append(candidate)
                    completed += 1
                    continue
                if candidate.needs_details:
                    stats.details_fetched += 1
                if candidate.needs_providers:
                    stats.provider_fetches += 1
                prepared_batch.append(prepared)
            except TMDBError as exc:
                stats.failed += 1
                stats.errors.append(
                    {"movie_id": candidate.movie_id, "title": candidate.title, "error": str(exc)}
                )
            completed += 1

        successful_writes = 0
        successful_provider_rows = 0
        successful_miss_writes = 0
        successful_conflict_writes = 0
        tmdb_owners = _existing_tmdb_owners(
            db,
            (prepared.tmdb_id for prepared in prepared_batch),
        )
        writable_batch: List[PreparedEnrichment] = []
        conflicted_batch: List[EnrichmentCandidate] = []
        for prepared in prepared_batch:
            candidate = prepared.candidate
            owner = tmdb_owners.get(prepared.tmdb_id)
            if owner is not None and owner[0] != candidate.movie_id:
                stats.identity_conflicts += 1
                stats.identity_conflict_details.append(
                    {
                        "movie_id": candidate.movie_id,
                        "title": candidate.title,
                        "tmdb_id": prepared.tmdb_id,
                        "owner_movie_id": owner[0],
                        "owner_title": owner[1],
                        "reason": "tmdb_id_already_owned",
                    }
                )
                conflicted_batch.append(candidate)
                continue
            # Reserve this identity within the prepared batch as well as
            # respecting mappings already persisted in the database.
            tmdb_owners[prepared.tmdb_id] = (candidate.movie_id, candidate.title)
            writable_batch.append(prepared)

        for candidate in missed_batch:
            try:
                with db.begin_nested():
                    attempted_at = datetime.now(timezone.utc)
                    if _persist_lookup_deferral(
                        db,
                        candidate,
                        attempted_at=attempted_at,
                        expires_at=attempted_at + timedelta(days=cache_days),
                        lookup_key=_tmdb_lookup_key(
                            candidate.title,
                            candidate.release_year,
                            language,
                        ),
                    ):
                        successful_miss_writes += 1
            except Exception as exc:
                stats.failed += 1
                stats.errors.append(
                    {
                        "movie_id": candidate.movie_id,
                        "title": candidate.title,
                        "error": f"Search-miss cache write failed: {exc}",
                    }
                )

        for candidate in conflicted_batch:
            try:
                with db.begin_nested():
                    attempted_at = datetime.now(timezone.utc)
                    if _persist_lookup_deferral(
                        db,
                        candidate,
                        attempted_at=attempted_at,
                        expires_at=attempted_at + timedelta(days=cache_days),
                        lookup_key=_tmdb_lookup_key(
                            candidate.title,
                            candidate.release_year,
                            language,
                        ),
                    ):
                        successful_conflict_writes += 1
            except Exception as exc:
                stats.failed += 1
                stats.errors.append(
                    {
                        "movie_id": candidate.movie_id,
                        "title": candidate.title,
                        "error": f"Identity-conflict cache write failed: {exc}",
                    }
                )

        for prepared in writable_batch:
            try:
                with db.begin_nested():
                    fetched_at = datetime.now(timezone.utc)
                    expires_at = fetched_at + timedelta(days=cache_days)
                    provider_count = _persist_prepared(
                        db,
                        prepared,
                        region=normalized_region,
                        fetched_at=fetched_at,
                        expires_at=expires_at,
                    )
                successful_writes += 1
                successful_provider_rows += provider_count
            except Exception as exc:
                stats.failed += 1
                stats.errors.append(
                    {
                        "movie_id": prepared.candidate.movie_id,
                        "title": prepared.candidate.title,
                        "error": f"Database write failed: {exc}",
                    }
                )
        try:
            db.commit()
            stats.enriched += successful_writes
            stats.not_found_cached += successful_miss_writes
            stats.identity_conflicts_cached += successful_conflict_writes
            stats.provider_rows += successful_provider_rows
        except Exception as exc:
            db.rollback()
            stats.failed += (
                successful_writes
                + successful_miss_writes
                + successful_conflict_writes
            )
            stats.errors.append({"movie_id": None, "title": None, "error": f"Batch commit failed: {exc}"})

    return stats
