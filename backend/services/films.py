"""The library rather than the people who hold it.

Everything here reads ``movie_enrichments``, so everything here is capped by the
TMDB match rate. Each response carries that ceiling rather than presenting a
partial answer as a whole one — a country breakdown over 87% of a library is a
different claim from a country breakdown.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import (
    Movie,
    MovieEnrichment,
    Profile,
    ProfileFilm,
    WatchEvent,
    WatchlistItem,
)


def _library(db: Session, profile_ids: Sequence[int]):
    """Active film rows for the selection, joined to whatever enrichment exists."""

    if not profile_ids:
        return []
    return (
        db.query(ProfileFilm, Movie, MovieEnrichment)
        .join(Movie, Movie.id == ProfileFilm.movie_id)
        .outerjoin(MovieEnrichment, MovieEnrichment.movie_id == Movie.id)
        .filter(ProfileFilm.profile_id.in_(profile_ids), ProfileFilm.removed_at.is_(None))
        .all()
    )


def _coverage(rows) -> Dict[str, Any]:
    distinct: Dict[int, bool] = {}
    for _film, movie, enrichment in rows:
        distinct[movie.id] = distinct.get(movie.id, False) or enrichment is not None
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

    rows = _library(db, [profile.id for profile in profiles])
    coverage = _coverage(rows)

    counts: Counter[str] = Counter()
    seen: set[int] = set()
    for _film, movie, enrichment in rows:
        if enrichment is None or movie.id in seen:
            continue
        seen.add(movie.id)
        for keyword in enrichment.keywords or []:
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
    rows = _library(db, profile_ids)
    coverage = _coverage(rows)

    watched: Counter[str] = Counter()
    seen: set[int] = set()
    for _film, movie, enrichment in rows:
        if enrichment is None or enrichment.runtime_minutes is None or movie.id in seen:
            continue
        seen.add(movie.id)
        for label, low, high in RUNTIME_BANDS:
            if enrichment.runtime_minutes >= low and (high is None or enrichment.runtime_minutes <= high):
                watched[label] += 1
                break

    queued: Counter[str] = Counter()
    if profile_ids:
        queue_rows = (
            db.query(MovieEnrichment.runtime_minutes)
            .join(WatchlistItem, WatchlistItem.movie_id == MovieEnrichment.movie_id)
            .filter(WatchlistItem.profile_id.in_(profile_ids), WatchlistItem.removed_at.is_(None))
            .all()
        )
        for (runtime,) in queue_rows:
            if runtime is None:
                continue
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

    rows = _library(db, [profile.id for profile in profiles])
    coverage = _coverage(rows)

    countries: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    seen: set[int] = set()
    for _film, movie, enrichment in rows:
        if enrichment is None or movie.id in seen:
            continue
        seen.add(movie.id)
        for country in enrichment.production_countries or []:
            name = (country.get("name") if isinstance(country, dict) else str(country)) or ""
            if name.strip():
                countries[name.strip()] += 1
        if enrichment.original_language:
            languages[enrichment.original_language] += 1

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

    rows = _library(db, [profile.id for profile in profiles])
    coverage = _coverage(rows)

    grouped: Dict[str, Dict[str, Any]] = {}
    seen: set[int] = set()
    for film, movie, enrichment in rows:
        if enrichment is None or movie.id in seen:
            continue
        seen.add(movie.id)
        collection = (enrichment.raw_payload or {}).get("belongs_to_collection")
        if not isinstance(collection, dict):
            continue
        name = (collection.get("name") or "").strip()
        if not name:
            continue
        entry = grouped.setdefault(name, {"name": name, "films": 0, "ratings": []})
        entry["films"] += 1
        if film.rating is not None:
            entry["ratings"].append(film.rating)

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
    series.sort(key=lambda item: -item["films"])

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

    rows = _library(db, [profile.id for profile in profiles])
    coverage = _coverage(rows)

    grouped: Dict[str, Dict[str, Any]] = {}
    seen: set[int] = set()
    for film, movie, enrichment in rows:
        if enrichment is None or movie.id in seen:
            continue
        seen.add(movie.id)
        crew = (enrichment.credits or {}).get("crew") or []
        for member in crew:
            if not isinstance(member, dict) or member.get("job") != "Director":
                continue
            name = (member.get("name") or "").strip()
            if not name:
                continue
            entry = grouped.setdefault(name, {"director": name, "films": 0, "ratings": [], "titles": []})
            entry["films"] += 1
            entry["titles"].append(movie.title)
            if film.rating is not None:
                entry["ratings"].append(film.rating)

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
    directors.sort(key=lambda item: -item["films"])

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
    for film, _movie, _enrichment in rows:
        liked = bool(film.is_liked)
        high = film.rating is not None and film.rating >= 4.0
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
            "and People › Watched but never rated separates them."
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
            f"Measured over {len(rows):,} rated films that carry Letterboxd's own crowd average. "
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
        return {"films": [], "dated": 0, "total": 0, "caveat": "No profiles selected."}

    rows = (
        db.query(WatchlistItem, Movie, Profile.username)
        .join(Movie, Movie.id == WatchlistItem.movie_id)
        .join(Profile, Profile.id == WatchlistItem.profile_id)
        .filter(WatchlistItem.profile_id.in_(profile_ids), WatchlistItem.removed_at.is_(None))
        .all()
    )

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
    for _film, movie, enrichment in rows:
        if enrichment is not None:
            continue
        entry = exposure.setdefault(
            movie.id,
            {
                "title": movie.title,
                "year": movie.release_year,
                "poster_url": movie.poster_url,
                "profiles": 0,
                "missing": [],
            },
        )
        entry["profiles"] += 1
        if not movie.poster_url and "poster" not in entry["missing"]:
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
            f"{len(films):,} distinct films carry no enrichment at all. Ordered by how many "
            "profiles hold each one rather than alphabetically, because that is what decides how "
            "often a blank appears on screen."
        ),
    }


def build_match_rate(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """The ceiling on every metadata panel in the product."""

    rows = _library(db, [profile.id for profile in profiles])
    coverage = _coverage(rows)

    distinct: Dict[int, Optional[int]] = {}
    for _film, movie, _enrichment in rows:
        distinct[movie.id] = movie.tmdb_id

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
