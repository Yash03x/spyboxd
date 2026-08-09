"""The library rather than the people who hold it.

Everything here reads ``movie_enrichments``, so everything here is capped by the
TMDB match rate. Each response carries that ceiling rather than presenting a
partial answer as a whole one — a country breakdown over 87% of a library is a
different claim from a country breakdown.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func, literal_column
from sqlalchemy.orm import Session

from database.models import (
    Movie,
    MovieEnrichment,
    Profile,
    ProfileFilm,
    WatchEvent,
    WatchlistItem,
)


# TMDB buries one or two directors in a crew list that routinely runs past two
# hundred people. Selecting the crew and filtering it in Python shipped all of
# them: /api/films/filmographies took twelve seconds on production against
# well under one for every other panel in the section. Extracting just the
# names by JSON path leaves the crew in the database.
#
# The constant is inlined rather than bound because PostgreSQL needs a
# `jsonpath`-typed argument and a bound parameter arrives as text. It is a
# literal in this file, never anything a caller supplies.
_DIRECTOR_NAMES_JSONPATH = """'$[*] ? (@.job == "Director").name'::jsonpath"""


def _library(db: Session, profile_ids: Sequence[int], *enrichment_columns):
    """Active film rows for the selection, joined to whatever enrichment exists.

    Only the columns a panel actually reads are selected. Loading whole
    ``MovieEnrichment`` entities pulled ``raw_payload`` — the entire TMDB
    response, watch providers included — for every film in the selection, and
    five Films panels ask at once on first paint. On a library this size that
    was enough to stop the API answering anything at all, so the fragments
    anybody needs out of a large JSON column are extracted by path in the
    database rather than shipped whole. ``profile_stats`` already did this; this
    module was written without it.
    """

    if not profile_ids:
        return []
    return (
        db.query(
            ProfileFilm.rating,
            ProfileFilm.is_liked,
            Movie.id.label("movie_id"),
            Movie.title,
            Movie.release_year,
            Movie.poster_url,
            Movie.tmdb_id,
            MovieEnrichment.movie_id.label("enrichment_movie_id"),
            *enrichment_columns,
        )
        .join(Movie, Movie.id == ProfileFilm.movie_id)
        .outerjoin(MovieEnrichment, MovieEnrichment.movie_id == Movie.id)
        .filter(ProfileFilm.profile_id.in_(profile_ids), ProfileFilm.removed_at.is_(None))
        .all()
    )


def _director_names_column(db: Session):
    """Director names per film, extracted in the database where it can be.

    PostgreSQL has `jsonb_path_query_array`, so production ships two strings
    per film instead of a two-hundred-entry crew list. SQLite has no jsonpath,
    so the tests fall back to the crew column and filter it here — the same
    answer either way, and a fixture library is small enough not to care.

    Returns the column and whether it is already reduced to names.
    """

    crew = MovieEnrichment.credits["crew"]
    if db.get_bind().dialect.name == "postgresql":
        return (
            func.jsonb_path_query_array(crew, literal_column(_DIRECTOR_NAMES_JSONPATH)),
            True,
        )
    return crew, False


def _films_held(db: Session, profile_ids: Sequence[int], *enrichment_columns):
    """One row per distinct film the selection holds, not one per holder.

    Two queries rather than a join, because the interesting columns are large
    JSON and a film held by six profiles was shipping its enrichment six times.
    The rating is the selection's mean for the film: panels that group films
    (by director, by collection) used to dedupe in Python and keep whichever
    holder's rating the database happened to return first, which made the
    average depend on row order.
    """

    if not profile_ids:
        return []

    holdings = (
        db.query(
            ProfileFilm.movie_id,
            func.avg(ProfileFilm.rating).label("rating"),
            func.count(ProfileFilm.movie_id).label("holders"),
        )
        .filter(ProfileFilm.profile_id.in_(profile_ids), ProfileFilm.removed_at.is_(None))
        .group_by(ProfileFilm.movie_id)
        .all()
    )
    if not holdings:
        return []

    by_movie = {row.movie_id: row for row in holdings}
    films = (
        db.query(
            Movie.id.label("movie_id"),
            Movie.title,
            Movie.release_year,
            Movie.poster_url,
            Movie.tmdb_id,
            MovieEnrichment.movie_id.label("enrichment_movie_id"),
            *enrichment_columns,
        )
        .outerjoin(MovieEnrichment, MovieEnrichment.movie_id == Movie.id)
        .filter(Movie.id.in_(list(by_movie)))
        .all()
    )

    held = []
    for film in films:
        holding = by_movie.get(film.movie_id)
        # An unrated film has no average, never an average of zero.
        rating = None if holding is None or holding.rating is None else float(holding.rating)
        held.append(_HeldFilm(film, rating, holding.holders if holding else 0))
    return held


class _HeldFilm:
    """A film plus what the selection did with it, addressed like a row."""

    __slots__ = ("_film", "rating", "holders")

    def __init__(self, film, rating: Optional[float], holders: int) -> None:
        self._film = film
        self.rating = rating
        self.holders = holders

    def __getattr__(self, name: str):
        return getattr(self._film, name)


def _director_names(value: Any, already_names: bool) -> List[str]:
    """Director names from either shape the column above can return."""

    if not isinstance(value, list):
        return []
    if already_names:
        return [name.strip() for name in value if isinstance(name, str) and name.strip()]
    names = []
    for member in value:
        if isinstance(member, Mapping) and member.get("job") == "Director":
            name = str(member.get("name") or "").strip()
            if name:
                names.append(name)
    return names


def _coverage(rows) -> Dict[str, Any]:
    distinct: Dict[int, bool] = {}
    for row in rows:
        enriched = row.enrichment_movie_id is not None
        distinct[row.movie_id] = distinct.get(row.movie_id, False) or enriched
    total = len(distinct)
    enriched = sum(1 for value in distinct.values() if value)
    return {
        "films": total,
        "enriched": enriched,
        "ratio": round(enriched / total, 4) if total else None,
    }


def _cap_sentence(coverage: Dict[str, Any]) -> str:
    if not coverage["films"]:
        return "Nothing imported for this selection yet."
    return (
        f"Read over the {coverage['enriched']:,} of {coverage['films']:,} distinct films that "
        f"carry TMDB metadata ({round((coverage['ratio'] or 0) * 100)}%). Unmatched films are "
        "excluded rather than counted as an empty value."
    )


def build_keywords(db: Session, profiles: Sequence[Profile], *, limit: int = 12) -> Dict[str, Any]:
    """Subjects the group returns to.

    Genre says drama. Keywords say grief, one location, unreliable narrator.
    """

    rows = _library(db, [profile.id for profile in profiles], MovieEnrichment.keywords)
    coverage = _coverage(rows)

    counts: Counter[str] = Counter()
    seen: set[int] = set()
    for row in rows:
        if row.enrichment_movie_id is None or row.movie_id in seen:
            continue
        seen.add(row.movie_id)
        for keyword in row.keywords or []:
            label = (keyword.get("name") if isinstance(keyword, dict) else str(keyword)) or ""
            label = label.strip().lower()
            if label:
                counts[label] += 1

    total = coverage["enriched"] or 1
    return {
        "keywords": [
            {"keyword": keyword, "films": films, "share": round(films / total, 4)}
            for keyword, films in counts.most_common(limit)
        ],
        "coverage": coverage,
        "caveat": (
            f"{_cap_sentence(coverage)} Share is against the enriched library, so anything above "
            "roughly 4% is a real preference rather than a long tail."
        ),
    }


RUNTIME_BANDS = [
    ("under 90", 0, 89),
    ("90–110", 90, 110),
    ("110–130", 111, 130),
    ("130–150", 131, 150),
    ("over 150", 151, None),
]


def build_runtime(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """What they add against what they finish.

    Intention and follow-through part company somewhere, and a single average
    runtime cannot say where.
    """

    profile_ids = [profile.id for profile in profiles]
    rows = _library(db, profile_ids, MovieEnrichment.runtime_minutes)
    coverage = _coverage(rows)

    watched: Counter[str] = Counter()
    seen: set[int] = set()
    for row in rows:
        # TMDB stores an unfilled runtime as 0, not as null, so `is None` alone
        # let every unmeasured film land in the shortest band -- the panel
        # reported a taste for films under 90 minutes that was really a gap in
        # enrichment. A runtime of zero is an absence.
        if (
            row.enrichment_movie_id is None
            or not row.runtime_minutes
            or row.movie_id in seen
        ):
            continue
        seen.add(row.movie_id)
        for label, low, high in RUNTIME_BANDS:
            if row.runtime_minutes >= low and (high is None or row.runtime_minutes <= high):
                watched[label] += 1
                break

    queued: Counter[str] = Counter()
    if profile_ids:
        # Distinct films, matching WATCHED. Counting watchlist rows meant a
        # film four people had queued arrived as four, so QUEUED and WATCHED
        # were different units printed as one ratio.
        queue_rows = (
            db.query(MovieEnrichment.movie_id, MovieEnrichment.runtime_minutes)
            .join(WatchlistItem, WatchlistItem.movie_id == MovieEnrichment.movie_id)
            .filter(WatchlistItem.profile_id.in_(profile_ids), WatchlistItem.removed_at.is_(None))
            .distinct()
            .all()
        )
        # Deduplicated here rather than with DISTINCT ON, which Postgres only
        # accepts alongside a matching ORDER BY and SQLite does not implement
        # at all -- the shape of bug this repository has shipped before.
        queued_seen: set[int] = set()
        for movie_id, runtime in queue_rows:
            if not runtime or movie_id in queued_seen:
                continue
            queued_seen.add(movie_id)
            for label, low, high in RUNTIME_BANDS:
                if runtime >= low and (high is None or runtime <= high):
                    queued[label] += 1
                    break

    bands = [
        {
            "label": label,
            "watched": watched.get(label, 0),
            "queued": queued.get(label, 0),
            # Null rather than infinity: a band nobody has queued has no ratio.
            "ratio": round(watched.get(label, 0) / queued[label], 2) if queued.get(label) else None,
        }
        for label, _low, _high in RUNTIME_BANDS
    ]

    over_150 = next((band for band in bands if band["label"] == "over 150"), None)
    return {
        "bands": bands,
        "coverage": coverage,
        "caveat": (
            f"{_cap_sentence(coverage)}"
            + (
                f" The longest band is the telling one: {over_150['queued']:,} queued against "
                f"{over_150['watched']:,} watched."
                if over_150 and over_150["queued"]
                else ""
            )
        ),
    }


def build_atlas(db: Session, profiles: Sequence[Profile], *, limit: int = 12) -> Dict[str, Any]:
    """Countries, and how much of the library needs reading."""

    rows = _library(
        db,
        [profile.id for profile in profiles],
        MovieEnrichment.production_countries,
        MovieEnrichment.original_language,
    )
    coverage = _coverage(rows)

    countries: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    seen: set[int] = set()
    for row in rows:
        if row.enrichment_movie_id is None or row.movie_id in seen:
            continue
        seen.add(row.movie_id)
        for country in row.production_countries or []:
            name = (country.get("name") if isinstance(country, dict) else str(country)) or ""
            if name.strip():
                countries[name.strip()] += 1
        if row.original_language:
            languages[row.original_language] += 1

    measured = sum(languages.values())
    non_english = measured - languages.get("en", 0)

    return {
        "countries": [
            {"country": country, "films": films} for country, films in countries.most_common(limit)
        ],
        "distinct_countries": len(countries),
        "subtitled_share": round(non_english / measured, 4) if measured else None,
        "coverage": coverage,
        "caveat": (
            f"{_cap_sentence(coverage)} Subtitled share is by original language, so an English-"
            "language film made abroad counts as a country here and as English there."
        ),
    }


def build_collections(db: Session, profiles: Sequence[Profile], *, limit: int = 12) -> Dict[str, Any]:
    """Series worked through, counted over films held.

    Never "8 of 8": TMDB's collection size is not in the film payload, so a
    denominator would be invented.
    """

    # TMDB nests this under `details`, which is where profile_stats has always
    # read it. Reading the top level found nothing, so the panel was empty for
    # every selection rather than wrong in a visible way.
    rows = _films_held(
        db,
        [profile.id for profile in profiles],
        MovieEnrichment.raw_payload["details"]["belongs_to_collection"].label(
            "belongs_to_collection"
        ),
    )
    coverage = _coverage(rows)

    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if row.enrichment_movie_id is None:
            continue
        collection = row.belongs_to_collection
        if not isinstance(collection, Mapping):
            continue
        name = str(collection.get("name") or "").strip()
        if not name:
            continue
        entry = grouped.setdefault(name, {"name": name, "films": 0, "ratings": []})
        entry["films"] += 1
        if row.rating is not None:
            entry["ratings"].append(row.rating)

    series = [
        {
            "name": entry["name"],
            "films": entry["films"],
            # An unrated series has no average, never an average of zero.
            "average_rating": (
                round(sum(entry["ratings"]) / len(entry["ratings"]), 2) if entry["ratings"] else None
            ),
        }
        for entry in grouped.values()
        # One film is not a franchise.
        if entry["films"] > 1
    ]
    # Name breaks the tie: without it the order among equal counts came from
    # row order, so the panel reshuffled between two identical refreshes.
    series.sort(key=lambda item: (-item["films"], item["name"].casefold()))

    return {
        "series": series[:limit],
        "count": len(series),
        "coverage": coverage,
        "caveat": (
            f"{_cap_sentence(coverage)} A count of films held, not a completion score: TMDB's "
            "collection size is not in the film payload. Singles are excluded."
        ),
    }


def build_filmographies(db: Session, profiles: Sequence[Profile], *, limit: int = 12) -> Dict[str, Any]:
    """How much of one director's work the group holds."""

    directors_column, already_names = _director_names_column(db)
    rows = _films_held(
        db, [profile.id for profile in profiles], directors_column.label("directors")
    )
    coverage = _coverage(rows)

    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if row.enrichment_movie_id is None:
            continue
        for name in _director_names(row.directors, already_names):
            entry = grouped.setdefault(name, {"director": name, "films": 0, "ratings": [], "titles": []})
            entry["films"] += 1
            entry["titles"].append(row.title)
            if row.rating is not None:
                entry["ratings"].append(row.rating)

    directors = [
        {
            "director": entry["director"],
            "films": entry["films"],
            "titles": sorted(entry["titles"])[:5],
            "average_rating": (
                round(sum(entry["ratings"]) / len(entry["ratings"]), 2) if entry["ratings"] else None
            ),
        }
        for entry in grouped.values()
        if entry["films"] > 1
    ]
    # Name breaks the tie, so two identical reads render in the same order.
    directors.sort(key=lambda item: (-item["films"], item["director"].casefold()))

    return {
        "directors": directors[:limit],
        "count": len(directors),
        "coverage": coverage,
        "caveat": (
            f"{_cap_sentence(coverage)} Films held, never a percentage of a filmography: TMDB does "
            "not give a director's total in the film payload, so a denominator would be a guess."
        ),
    }


def build_liked_vs_rated(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """A heart and a score are different instruments.

    The interesting corner is the third one: films given a high score with the
    heart withheld.
    """

    rows = _library(db, [profile.id for profile in profiles])

    high_and_liked = 0
    liked_only = 0
    high_only = 0
    neither = 0
    for row in rows:
        liked = bool(row.is_liked)
        high = row.rating is not None and row.rating >= 4.0
        if liked and high:
            high_and_liked += 1
        elif liked:
            liked_only += 1
        elif high:
            high_only += 1
        else:
            neither += 1

    total = high_and_liked + liked_only + high_only + neither or 1
    return {
        "quadrants": [
            {"tag": "HEART + HIGH SCORE", "films": high_and_liked, "share": round(high_and_liked / total, 4),
             "note": "Agreement between the two instruments. The unremarkable corner."},
            {"tag": "HEART, NO HIGH SCORE", "films": liked_only, "share": round(liked_only / total, 4),
             "note": "Loved it, would not rank it. Comfort watches and childhood films."},
            {"tag": "HIGH SCORE, NO HEART", "films": high_only, "share": round(high_only / total, 4),
             "note": "Admired, not loved. The most revealing corner in the panel."},
            {"tag": "NEITHER", "films": neither, "share": round(neither / total, 4),
             "note": "Watched and moved on."},
        ],
        "total": total,
        "caveat": (
            "A high score is four stars or more. An unrated film has no score, so it lands in "
            "\"neither\" alongside films that were actually rated low — the two are not the same, "
            "and People › Watched but never rated separates them. These are logs rather than "
            "distinct films: a film six of the selection watched is counted six times, once per "
            "opinion, which is the unit the question needs — the same film can be a heart for "
            "one person and nothing for another."
        ),
    }


def build_decade_divergence(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """Divergence from the crowd, split by the film's decade.

    A single contrarian number hides this: somebody can be conventional about
    new releases and heretical about the seventies.
    """

    profile_ids = [profile.id for profile in profiles]
    if not profile_ids:
        return {"decades": [], "caveat": "No profiles selected."}

    rows = (
        db.query(ProfileFilm.rating, Movie.release_year, Movie.letterboxd_average_rating)
        .join(Movie, Movie.id == ProfileFilm.movie_id)
        .filter(
            ProfileFilm.profile_id.in_(profile_ids),
            ProfileFilm.removed_at.is_(None),
            ProfileFilm.rating.isnot(None),
            Movie.release_year.isnot(None),
            Movie.letterboxd_average_rating.isnot(None),
        )
        .all()
    )

    by_decade: Dict[int, List[float]] = defaultdict(list)
    for rating, year, crowd in rows:
        by_decade[(year // 10) * 10].append(rating - crowd)

    decades = [
        {
            "decade": f"{decade}s",
            "delta": round(sum(deltas) / len(deltas), 3),
            "films": len(deltas),
        }
        for decade, deltas in sorted(by_decade.items())
        # Below a handful there is no lean, only a couple of opinions.
        if len(deltas) >= 5
    ]

    return {
        "decades": decades,
        "measured": sum(entry["films"] for entry in decades),
        "caveat": (
            # Rating rows, not distinct films: a film three people rated counts three
            # times, because each contributes its own delta to the lean.
            f"Measured over {len(rows):,} rating{'' if len(rows) == 1 else 's'} across the selection on films that "
            "carry Letterboxd's own crowd average. "
            "Decades with fewer than five such films are dropped rather than shown as a lean built "
            "from two opinions."
        ),
    }


def build_queue_age(db: Session, profiles: Sequence[Profile], *, limit: int = 12) -> Dict[str, Any]:
    """Queue entries that have survived every refresh since they were added.

    The added date comes from an official export only, so this is blank for
    scraped-only profiles and says so.
    """

    profile_ids = [profile.id for profile in profiles]
    if not profile_ids:
        return {
            "films": [],
            "dated": 0,
            "total": 0,
            "distinct_queued": 0,
            "rated_by_selection": 0,
            "caveat": "No profiles selected.",
        }

    rows = (
        db.query(WatchlistItem, Movie, Profile.username)
        .join(Movie, Movie.id == WatchlistItem.movie_id)
        .join(Profile, Profile.id == WatchlistItem.profile_id)
        .filter(WatchlistItem.profile_id.in_(profile_ids), WatchlistItem.removed_at.is_(None))
        .all()
    )

    # Selection-wide conversion figures. The Taste map panel used to take these
    # from the FIRST selected profile's watchlist insights and present them as
    # the group's — every sibling panel on that tab computes over the whole
    # selection.
    distinct_queued_ids = {item.movie_id for item, _movie, _username in rows}
    rated_by_selection = (
        db.query(func.count(func.distinct(ProfileFilm.movie_id)))
        .filter(
            ProfileFilm.movie_id.in_(distinct_queued_ids),
            ProfileFilm.profile_id.in_(profile_ids),
            ProfileFilm.rating.isnot(None),
            ProfileFilm.removed_at.is_(None),
        )
        .scalar()
        or 0
    ) if distinct_queued_ids else 0

    dated = [(item, movie, username) for item, movie, username in rows if item.added_date]
    dated.sort(key=lambda entry: entry[0].added_date)

    films = [
        {
            "title": movie.title,
            "year": movie.release_year,
            "poster_url": movie.poster_url,
            "username": username,
            "added_date": item.added_date.isoformat(),
        }
        for item, movie, username in dated[:limit]
    ]

    with_dates = sorted({username for item, _movie, username in rows if item.added_date})

    return {
        "films": films,
        "dated": len(dated),
        "total": len(rows),
        "distinct_queued": len(distinct_queued_ids),
        "rated_by_selection": rated_by_selection,
        "profiles_with_added_dates": with_dates,
        "caveat": (
            f"{len(with_dates)} of {len(profiles)} selected profiles carry an added date, so "
            f"{len(dated):,} of {len(rows):,} queued entries can be aged at all. The rest are "
            "excluded rather than guessed at."
        ),
    }


def build_language_ladder(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """Non-English share, year over year.

    Somebody widening their range looks nothing like somebody who always
    watched this way, and a current ratio cannot tell them apart.
    """

    profile_ids = [profile.id for profile in profiles]
    if not profile_ids:
        return {"years": [], "caveat": "No profiles selected."}

    rows = (
        db.query(WatchEvent.watched_date, MovieEnrichment.original_language)
        .join(MovieEnrichment, MovieEnrichment.movie_id == WatchEvent.movie_id)
        .filter(
            WatchEvent.profile_id.in_(profile_ids),
            WatchEvent.superseded_at.is_(None),
            WatchEvent.watched_date.isnot(None),
            MovieEnrichment.original_language.isnot(None),
        )
        .all()
    )

    by_year: Dict[int, List[str]] = defaultdict(list)
    for watched_date, language in rows:
        by_year[watched_date.year].append(language)

    years = [
        {
            "year": year,
            "watches": len(languages),
            "non_english": sum(1 for language in languages if language != "en"),
            "share": round(sum(1 for language in languages if language != "en") / len(languages), 4),
        }
        for year, languages in sorted(by_year.items())
        if len(languages) >= 10
    ]

    return {
        "years": years,
        "caveat": (
            f"Measured over {len(rows):,} dated watches whose film carries an original language. "
            "Years with fewer than ten such watches are dropped rather than shown as a share built "
            "from a handful."
        ),
    }


def build_metadata_gaps(db: Session, profiles: Sequence[Profile], *, limit: int = 12) -> Dict[str, Any]:
    """Unenriched films, ranked by how often they actually appear on screen.

    Fixing the top row removes more blank posters than fixing the bottom forty.
    """

    profile_ids = [profile.id for profile in profiles]
    rows = _library(db, profile_ids)

    exposure: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        if row.enrichment_movie_id is not None:
            continue
        entry = exposure.setdefault(
            row.movie_id,
            {
                "title": row.title,
                "year": row.release_year,
                "poster_url": row.poster_url,
                "profiles": 0,
                "missing": [],
            },
        )
        entry["profiles"] += 1
        if not row.poster_url and "poster" not in entry["missing"]:
            entry["missing"].append("poster")

    films = sorted(exposure.values(), key=lambda item: -item["profiles"])
    for film in films:
        if not film["missing"]:
            film["missing"] = ["runtime", "genres", "credits"]

    coverage = _coverage(rows)
    return {
        "films": films[:limit],
        "count": len(films),
        "coverage": coverage,
        "caveat": (
            f"{len(films):,} distinct film{'s carry' if len(films) != 1 else ' carries'} no enrichment at all. Ordered by how many "
            "profiles hold each one rather than alphabetically, because that is what decides how "
            "often a blank appears on screen."
        ),
    }


def build_match_rate(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """The ceiling on every metadata panel in the product."""

    rows = _library(db, [profile.id for profile in profiles])
    coverage = _coverage(rows)

    distinct: Dict[int, Optional[int]] = {}
    for row in rows:
        distinct[row.movie_id] = row.tmdb_id

    with_id = sum(1 for value in distinct.values() if value)

    return {
        "films": coverage["films"],
        "enriched": coverage["enriched"],
        "with_tmdb_id": with_id,
        "ratio": coverage["ratio"],
        "reasons": [
            {"reason": "Matched to a TMDB id and enriched", "films": coverage["enriched"]},
            {
                "reason": "Matched to a TMDB id, enrichment not fetched yet",
                "films": max(with_id - coverage["enriched"], 0),
            },
            {
                "reason": "No confident title and year match",
                "films": max(coverage["films"] - with_id, 0),
            },
        ],
        "caveat": (
            "Taste breakdown, runtime appetite, countries, keywords and availability all read the "
            "enrichment cache. Whatever this number is, it is their maximum — and every one of "
            "those panels states it rather than presenting a partial answer as a whole one."
        ),
    }
