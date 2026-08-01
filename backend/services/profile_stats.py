"""Per-profile viewing statistics computed from rows we already own.

Letterboxd publishes its own ``/<user>/stats/`` page, but only to Patrons, so
scraping it covers a handful of profiles at best. TMDB enrichment already
carries runtime, language, release date, genres, credits, production countries
and the raw payload's production companies for every film we have matched, so
the same figures can be recomputed for *every* profile from local data.

Nothing here extrapolates. Runtime is summed only over the films whose runtime
we actually hold, and ``runtime_coverage`` reports what fraction of the library
that was, so a client can qualify the number instead of presenting a partial
sum as a total. Where enrichment supplies no evidence at all, the payload says
``null`` rather than ``0`` -- an unenriched profile has an unknown director
count, not zero directors.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence

from sqlalchemy.orm import Session

from database.models import Movie, MovieEnrichment, Profile, ProfileFilm, WatchEvent
from services.insights import _as_string_list, _average, _round, _safe_float


# Every list surface is a "top" list, not an export: a stats page that renders
# 800 directors is a database dump, not a summary.
MAX_LIST_ENTRIES = 10

# A single five-star film is not a favourite genre. "Highest rated" needs
# enough rated films behind the average for the number to mean anything.
MIN_FAVOURITE_SAMPLE = 3

# TMDB orders `cast` by billing. Counting all of it would let a 40-name
# ensemble outweigh a two-hander, so only the top-billed roles count.
TOP_BILLED_CAST_ORDER = 5


class _Value(NamedTuple):
    """One bucket membership for a film: merge key, display label, optional code."""

    key: str
    label: str
    code: Optional[str] = None


@dataclass(frozen=True)
class _FilmRow:
    """One active profile_films row, joined to whatever enrichment exists."""

    rating: Optional[float]
    rewatch_count: int
    release_year: Optional[int]
    enriched: bool
    runtime_minutes: Optional[int]
    genres: List[_Value]
    countries: List[_Value]
    languages: List[_Value]
    directors: List[_Value]
    actors: List[_Value]
    studios: List[_Value]

    @property
    def decades(self) -> List[_Value]:
        if not self.release_year:
            return []
        label = f"{(int(self.release_year) // 10) * 10}s"
        return [_Value(label, label)]


def _plain_values(labels: Iterable[str]) -> List[_Value]:
    return [_Value(label.casefold(), label) for label in labels]


def _country_values(payload: Any) -> List[_Value]:
    """TMDB production countries carry both a name and an ISO 3166-1 code."""

    values: List[_Value] = []
    seen: set[str] = set()
    for item in payload if isinstance(payload, list) else []:
        if isinstance(item, Mapping):
            label = str(item.get("name") or "").strip()
            code = str(item.get("iso_3166_1") or "").strip().upper() or None
        else:
            label = str(item or "").strip()
            code = None
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            values.append(_Value(key, label, code))
    return values


def _language_values(original_language: Any, spoken_languages: Any) -> List[_Value]:
    """Name the original language from the payload rather than a hardcoded map.

    ``original_language`` is a bare ISO 639-1 code. The same TMDB response
    lists every spoken language with its English name, so the readable label
    comes from the data itself and falls back to the uppercased code when the
    payload never names it.
    """

    code = str(original_language or "").strip()
    if not code:
        return []
    label = None
    for item in spoken_languages if isinstance(spoken_languages, list) else []:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("iso_639_1") or "").strip().casefold() == code.casefold():
            label = str(item.get("english_name") or item.get("name") or "").strip() or None
            break
    return [_Value(code.casefold(), label or code.upper(), code.casefold())]


def _director_values(credits: Any) -> List[_Value]:
    """Only crew credited with the Director job; a film may have several."""

    crew = credits.get("crew") if isinstance(credits, Mapping) else None
    if not isinstance(crew, list):
        return []
    return _plain_values(
        _as_string_list(
            [
                member
                for member in crew
                if isinstance(member, Mapping) and member.get("job") == "Director"
            ]
        )
    )


def _actor_values(credits: Any) -> List[_Value]:
    cast = credits.get("cast") if isinstance(credits, Mapping) else None
    if not isinstance(cast, list):
        return []
    billed: List[Any] = []
    for index, member in enumerate(cast):
        if not isinstance(member, Mapping):
            continue
        order = _safe_float(member.get("order"))
        position = int(order) if order is not None else index
        if position < TOP_BILLED_CAST_ORDER:
            billed.append(member)
    return _plain_values(_as_string_list(billed))


def _film_rows(db: Session, profile_id: int) -> List[_FilmRow]:
    """Bulk-load one profile's library in a single query.

    Only the columns the statistics need are selected. ``raw_payload`` holds
    the entire TMDB response including watch providers -- tens of megabytes
    across a large library -- so the two fragments needed from it are extracted
    by JSON path in the database instead of shipping the whole document.
    """

    production_companies = MovieEnrichment.raw_payload["details"]["production_companies"]
    spoken_languages = MovieEnrichment.raw_payload["details"]["spoken_languages"]
    rows = (
        db.query(
            ProfileFilm.rating,
            ProfileFilm.rewatch_count,
            Movie.release_year,
            MovieEnrichment.movie_id,
            MovieEnrichment.runtime_minutes,
            MovieEnrichment.original_language,
            MovieEnrichment.release_date,
            MovieEnrichment.genres,
            MovieEnrichment.credits,
            MovieEnrichment.production_countries,
            production_companies.label("production_companies"),
            spoken_languages.label("spoken_languages"),
        )
        .join(Movie, Movie.id == ProfileFilm.movie_id)
        .outerjoin(MovieEnrichment, MovieEnrichment.movie_id == Movie.id)
        .filter(
            ProfileFilm.profile_id == profile_id,
            ProfileFilm.removed_at.is_(None),
        )
        .all()
    )

    films: List[_FilmRow] = []
    for row in rows:
        enriched = row.movie_id is not None
        release_year = row.release_year
        if not release_year and row.release_date is not None:
            release_year = row.release_date.year
        credits = row.credits if isinstance(row.credits, Mapping) else {}
        films.append(
            _FilmRow(
                rating=_safe_float(row.rating),
                rewatch_count=int(row.rewatch_count or 0),
                release_year=int(release_year) if release_year else None,
                enriched=enriched,
                runtime_minutes=(
                    int(row.runtime_minutes)
                    if row.runtime_minutes is not None and int(row.runtime_minutes) > 0
                    else None
                ),
                genres=_plain_values(_as_string_list(row.genres)),
                countries=_country_values(row.production_countries),
                languages=_language_values(row.original_language, row.spoken_languages),
                directors=_director_values(credits),
                actors=_actor_values(credits),
                studios=_plain_values(_as_string_list(row.production_companies)),
            )
        )
    return films


def _dated_watch_dates(db: Session, profile_id: int) -> List[date]:
    """Every active watch event's date, one small column, one query."""

    return [
        watched_date
        for (watched_date,) in db.query(WatchEvent.watched_date)
        .filter(
            WatchEvent.profile_id == profile_id,
            WatchEvent.superseded_at.is_(None),
            WatchEvent.watched_date.isnot(None),
        )
        .all()
        if watched_date is not None
    ]


def longest_streak_weeks(dates: Sequence[date]) -> Optional[int]:
    """Longest run of consecutive ISO weeks that each contain a watch.

    Each date collapses to the Monday that starts its ISO week, so two watches
    in one week count once and consecutive weeks are exactly seven days apart
    -- true across year boundaries, where ISO week numbers restart.
    """

    if not dates:
        return None
    week_starts = sorted({value - timedelta(days=value.weekday()) for value in dates})
    longest = 1
    current = 1
    for previous, following in zip(week_starts, week_starts[1:]):
        current = current + 1 if (following - previous).days == 7 else 1
        longest = max(longest, current)
    return longest


def multi_film_days(dates: Sequence[date]) -> Optional[int]:
    """Distinct days carrying two or more watch events."""

    if not dates:
        return None
    return sum(1 for count in Counter(dates).values() if count >= 2)


def _collect(
    films: Sequence[_FilmRow],
    values_for: Callable[[_FilmRow], Sequence[_Value]],
) -> Dict[str, Dict[str, Any]]:
    """Tally one dimension across the library, keeping each bucket's ratings."""

    buckets: Dict[str, Dict[str, Any]] = {}
    for film in films:
        for value in values_for(film):
            bucket = buckets.get(value.key)
            if bucket is None:
                bucket = {
                    "label": value.label,
                    "code": value.code,
                    "count": 0,
                    "ratings": [],
                }
                buckets[value.key] = bucket
            elif bucket["code"] is None and value.code is not None:
                bucket["code"] = value.code
            bucket["count"] += 1
            if film.rating is not None:
                bucket["ratings"].append(film.rating)
    return buckets


def _entry(
    bucket: Mapping[str, Any],
    *,
    label_key: str = "label",
    include_code: bool = False,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {label_key: bucket["label"]}
    if include_code:
        entry["code"] = bucket["code"]
    entry["count"] = bucket["count"]
    entry["average_rating"] = _round(_average(bucket["ratings"]), 2)
    return entry


def _by_count(bucket: Mapping[str, Any]):
    return (-bucket["count"], bucket["label"].casefold(), bucket["label"])


def _ranked(
    buckets: Mapping[str, Dict[str, Any]],
    *,
    label_key: str = "label",
    include_code: bool = False,
) -> List[Dict[str, Any]]:
    ordered = sorted(buckets.values(), key=_by_count)[:MAX_LIST_ENTRIES]
    return [
        _entry(bucket, label_key=label_key, include_code=include_code)
        for bucket in ordered
    ]


def _ranked_decades(buckets: Mapping[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The busiest decades, replayed in chronological order for charting."""

    ordered = sorted(buckets.values(), key=_by_count)[:MAX_LIST_ENTRIES]
    ordered.sort(key=lambda bucket: int(bucket["label"][:-1]))
    return [_entry(bucket) for bucket in ordered]


def _highest_rated(
    buckets: Mapping[str, Dict[str, Any]],
    *,
    label_key: str = "label",
) -> Optional[Dict[str, Any]]:
    """The best-rated bucket that clears the credible-sample floor."""

    eligible = [
        bucket
        for bucket in buckets.values()
        if len(bucket["ratings"]) >= MIN_FAVOURITE_SAMPLE
    ]
    if not eligible:
        return None
    best = min(
        eligible,
        key=lambda bucket: (
            -(_average(bucket["ratings"]) or 0.0),
            -bucket["count"],
            bucket["label"].casefold(),
        ),
    )
    return _entry(best, label_key=label_key)


def _distinct(buckets: Mapping[str, Dict[str, Any]]) -> Optional[int]:
    """A dimension nothing in the library described is unknown, not zero."""

    return len(buckets) or None


def build_profile_stats(db: Session, profile: Profile) -> Dict[str, Any]:
    """Recompute the Letterboxd stats page for one profile from local rows.

    ``letterboxd_reported`` carries the scraped Patron figures verbatim where
    they exist so a client can show ours against theirs. It is a cross-check,
    never the source: the two will differ because Letterboxd counts its own
    runtime data over a member's whole library while we count TMDB runtimes
    over the films we managed to match.
    """

    films = _film_rows(db, profile.id)
    watch_dates = _dated_watch_dates(db, profile.id)

    films_total = len(films)
    films_enriched = sum(1 for film in films if film.enriched)
    ratings = [film.rating for film in films if film.rating is not None]
    runtimes = [
        film.runtime_minutes for film in films if film.runtime_minutes is not None
    ]

    genres = _collect(films, lambda film: film.genres)
    countries = _collect(films, lambda film: film.countries)
    languages = _collect(films, lambda film: film.languages)
    decades = _collect(films, lambda film: film.decades)
    directors = _collect(films, lambda film: film.directors)
    actors = _collect(films, lambda film: film.actors)
    studios = _collect(films, lambda film: film.studios)

    return {
        "username": profile.username,
        "coverage": {
            "films_total": films_total,
            "films_enriched": films_enriched,
            "enrichment_ratio": _round(films_enriched / films_total, 4) if films_total else 0.0,
            "dated_events": len(watch_dates),
            "rated_films": len(ratings),
        },
        "totals": {
            "films": films_total,
            "hours_watched": _round(sum(runtimes) / 60, 1) if runtimes else None,
            "runtime_coverage": _round(len(runtimes) / films_total, 4) if films_total else 0.0,
            "distinct_directors": _distinct(directors),
            "distinct_actors": _distinct(actors),
            "distinct_countries": _distinct(countries),
            "distinct_languages": _distinct(languages),
            "distinct_studios": _distinct(studios),
            "longest_streak_weeks": longest_streak_weeks(watch_dates),
            "multi_film_days": multi_film_days(watch_dates),
            "rewatches": sum(film.rewatch_count for film in films),
            "average_rating": _round(_average(ratings), 2),
        },
        "top_directors": _ranked(directors, label_key="name"),
        "top_actors": _ranked(actors, label_key="name"),
        "top_studios": _ranked(studios, label_key="name"),
        "genres": _ranked(genres),
        "countries": _ranked(countries, include_code=True),
        "languages": _ranked(languages),
        "decades": _ranked_decades(decades),
        "highest_rated": {
            "genre": _highest_rated(genres),
            "decade": _highest_rated(decades),
            "director": _highest_rated(directors, label_key="name"),
        },
        "letterboxd_reported": profile.stats_snapshot,
    }
