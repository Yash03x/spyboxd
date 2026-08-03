"""Group-level rhythm read from ``watch_events``.

Every function here answers a question about *when* the tracked group watches
rather than *what*. All of it reads dated, non-superseded events only: an
undated entry is excluded rather than assumed, which is why each response
carries the coverage it was computed from.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from database.models import Movie, MovieEnrichment, Profile, ProfileFilm, WatchEvent
from services.profile_stats import (
    MARATHON_MAX_FILMS_WITHOUT_RUNTIME,
    MARATHON_MAX_HOURS,
    MARATHON_MIN_FILMS,
)


def _dated_events(
    db: Session, profile_ids: Sequence[int]
) -> List[Tuple[int, date, str, Optional[int]]]:
    """(profile_id, watched_date, title, runtime) for active, dated events."""

    if not profile_ids:
        return []

    rows = (
        db.query(
            WatchEvent.profile_id,
            WatchEvent.watched_date,
            Movie.title,
            MovieEnrichment.runtime_minutes,
        )
        .join(Movie, Movie.id == WatchEvent.movie_id)
        .outerjoin(MovieEnrichment, MovieEnrichment.movie_id == Movie.id)
        .filter(
            WatchEvent.profile_id.in_(profile_ids),
            WatchEvent.superseded_at.is_(None),
            WatchEvent.watched_date.isnot(None),
        )
        .all()
    )
    return [(row[0], row[1], row[2] or "", row[3] or None) for row in rows]


def _undated_count(db: Session, profile_ids: Sequence[int]) -> int:
    """Films we hold for these profiles that carry no date at all.

    ``watch_events.watched_date`` is NOT NULL, so an undated *event* cannot
    exist — counting those would always return zero and quietly claim full
    coverage. An undated film is a ``profile_films`` row with no first-watch
    date, which is what a ratings snapshot without a diary produces.
    """

    if not profile_ids:
        return 0
    return (
        db.query(ProfileFilm)
        .filter(
            ProfileFilm.profile_id.in_(profile_ids),
            ProfileFilm.removed_at.is_(None),
            ProfileFilm.first_watched_date.is_(None),
        )
        .count()
    )


def build_marathons(
    db: Session, profiles: Sequence[Profile], *, limit: int = 12
) -> Dict[str, Any]:
    """Days one person logged several films, across the whole selection.

    The same guardrail the per-profile panel uses applies here: a day whose
    films could not physically fit inside it is an import artifact, not a
    sitting, and is counted separately rather than presented as somebody's
    biggest day.
    """

    names = {profile.id: profile.username for profile in profiles}
    events = _dated_events(db, list(names))

    by_person_day: Dict[Tuple[int, date], List[Tuple[str, Optional[int]]]] = defaultdict(list)
    for profile_id, watched_date, title, runtime in events:
        by_person_day[(profile_id, watched_date)].append((title, runtime))

    marathons: List[Dict[str, Any]] = []
    discarded = 0
    for (profile_id, day), films in by_person_day.items():
        if len(films) < MARATHON_MIN_FILMS:
            continue
        known = [runtime for _, runtime in films if runtime]
        total_minutes = sum(known)
        if known and total_minutes > MARATHON_MAX_HOURS * 60:
            discarded += 1
            continue
        if not known and len(films) > MARATHON_MAX_FILMS_WITHOUT_RUNTIME:
            discarded += 1
            continue
        marathons.append(
            {
                "date": day.isoformat(),
                "username": names[profile_id],
                "films": len(films),
                "runtime_minutes": total_minutes or None,
                "titles": [title for title, _ in films if title][:6],
            }
        )

    marathons.sort(key=lambda item: (item["date"], -item["films"]), reverse=True)

    return {
        "marathons": marathons[:limit],
        "count": len(marathons),
        "import_artifact_days": discarded,
        "caveat": _marathon_caveat(len(marathons), discarded),
    }


def _marathon_caveat(count: int, discarded: int) -> str:
    # A day that was set aside is not a day that never existed. Saying "no day
    # qualifies" when several were discarded would be the one wrong sentence
    # this panel can produce, so the discard is reported either way.
    artifacts = (
        f" {discarded} day{'s' if discarded != 1 else ''} held more film than a day holds and "
        f"{'were' if discarded != 1 else 'was'} set aside as an import artifact rather than counted."
        if discarded
        else ""
    )

    if count == 0:
        return (
            f"No day in the selection has {MARATHON_MIN_FILMS} or more dated films logged by one "
            "person that could physically fit inside one. Undated films cannot be grouped into a "
            "day at all and are excluded rather than guessed at." + artifacts
        )

    return (
        f"{count} day{'s' if count != 1 else ''} across the selection with {MARATHON_MIN_FILMS} or "
        "more films logged by one person." + artifacts
    )


# Monday-first, matching how the calendar heat grid is drawn.
WEEKDAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTH_LABELS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def build_weekday_rhythm(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """Watches by day of week. Diary entries carry a date but no clock, so this
    is as fine-grained as time gets — there is no late-night pattern to find."""

    profile_ids = [profile.id for profile in profiles]
    events = _dated_events(db, profile_ids)

    counts = [0] * 7
    for _, watched_date, _, _ in events:
        counts[watched_date.weekday()] += 1

    total = sum(counts)
    undated = _undated_count(db, profile_ids)

    return {
        "days": [
            {
                "label": WEEKDAY_LABELS[index],
                "watches": value,
                "share": round(value / total, 4) if total else None,
            }
            for index, value in enumerate(counts)
        ],
        "total": total,
        "undated": undated,
        "caveat": (
            "Diary entries carry a date but no clock, so weekday is as fine-grained as time gets."
            + (
                f" {undated:,} films carry no date at all and are excluded rather than placed on a guessed day."
                if undated
                else ""
            )
        ),
    }


def build_season_shape(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """Month of year across every year at once.

    A single year's activity chart cannot separate a seasonal habit from a busy
    month; folding every year onto twelve buckets can.
    """

    profile_ids = [profile.id for profile in profiles]
    events = _dated_events(db, profile_ids)

    counts = [0] * 12
    years: set[int] = set()
    for _, watched_date, _, _ in events:
        counts[watched_date.month - 1] += 1
        years.add(watched_date.year)

    total = sum(counts)
    ordered = sorted(range(12), key=lambda index: counts[index])
    quietest = ordered[0] if total else None
    busiest = ordered[-1] if total else None

    return {
        "months": [
            {
                "label": MONTH_LABELS[index],
                "name": MONTH_NAMES[index],
                "watches": value,
                "share": round(value / total, 4) if total else None,
            }
            for index, value in enumerate(counts)
        ],
        "total": total,
        "years_covered": len(years),
        "busiest": MONTH_NAMES[busiest] if busiest is not None else None,
        "quietest": MONTH_NAMES[quietest] if quietest is not None else None,
        "caveat": (
            f"Folded from {len(years)} year{'s' if len(years) != 1 else ''} of dated watches. "
            "A month that looks quiet here is a habit, not a bad month — the years are stacked."
            if total
            else "No dated watches in the selection, so there is no seasonal shape to fold."
        ),
    }


# Anything past this is a backfill rather than a late log, and saying so is
# more useful than letting one imported diary dominate the long tail.
LAG_BUCKETS: List[Tuple[str, int, Optional[int]]] = [
    ("Same day", 0, 0),
    ("Next day", 1, 1),
    ("2–7 days", 2, 7),
    ("1–4 weeks", 8, 28),
    ("Over a month", 29, None),
]


def build_logging_lag(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """When they watched it against when they told Letterboxd.

    ``logged_date`` only exists on official exports; public HTML never carries
    it. The response says how much of the selection could be measured at all.
    """

    profile_ids = [profile.id for profile in profiles]
    if not profile_ids:
        return {"buckets": [], "measured": 0, "total": 0, "caveat": "No profiles selected."}

    rows = (
        db.query(WatchEvent.watched_date, WatchEvent.logged_date)
        .filter(
            WatchEvent.profile_id.in_(profile_ids),
            WatchEvent.superseded_at.is_(None),
            WatchEvent.watched_date.isnot(None),
        )
        .all()
    )

    counts = {label: 0 for label, _, _ in LAG_BUCKETS}
    measured = 0
    for watched_date, logged_date in rows:
        if logged_date is None:
            continue
        delta = (logged_date - watched_date).days
        if delta < 0:
            # A log dated before the watch is a data error, not a negative lag.
            continue
        measured += 1
        for label, low, high in LAG_BUCKETS:
            if delta >= low and (high is None or delta <= high):
                counts[label] += 1
                break

    return {
        "buckets": [
            {
                "label": label,
                "events": counts[label],
                "share": round(counts[label] / measured, 4) if measured else None,
            }
            for label, _, _ in LAG_BUCKETS
        ],
        "measured": measured,
        "total": len(rows),
        "caveat": (
            f"{measured:,} of {len(rows):,} dated watches carry a log date. Log dates come from the "
            "official export only — public pages never publish one, so scraped-only profiles cannot "
            "appear here at all."
        ),
    }
