"""Who got there first, read from ``profile_films.first_watched_date``.

Both answers here depend on a first-watch date existing on *both* sides of a
comparison. A profile imported from a ratings snapshot carries one date per
film at best and often none, so every response states how much of the selection
could be measured rather than quietly comparing the subset that could.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from itertools import combinations
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from database.models import Movie, Profile, ProfileFilm


def _first_watch_rows(
    db: Session, profile_ids: Sequence[int]
) -> List[Tuple[int, int, Optional[date], str, Optional[int], Optional[str]]]:
    """(profile_id, movie_id, first_watched_date, title, year, poster_url)."""

    if not profile_ids:
        return []

    rows = (
        db.query(
            ProfileFilm.profile_id,
            ProfileFilm.movie_id,
            ProfileFilm.first_watched_date,
            Movie.title,
            Movie.release_year,
            Movie.poster_url,
        )
        .join(Movie, Movie.id == ProfileFilm.movie_id)
        .filter(
            ProfileFilm.profile_id.in_(profile_ids),
            # A soft-removed row is history, not a current watch.
            ProfileFilm.removed_at.is_(None),
        )
        .all()
    )
    return [tuple(row) for row in rows]  # type: ignore[misc]


def build_first_watch_order(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """Share of shared films where this person was the earlier watch.

    High is not better: it means the rest of the group tends to arrive after
    them. Films where either side has no first-watch date are excluded rather
    than assumed late, which is why the shares do not sum to anything.
    """

    names = {profile.id: profile.username for profile in profiles}
    rows = _first_watch_rows(db, list(names))

    by_movie: Dict[int, List[Tuple[int, Optional[date]]]] = defaultdict(list)
    for profile_id, movie_id, first_watched, _title, _year, _poster in rows:
        by_movie[movie_id].append((profile_id, first_watched))

    first_counts: Dict[int, int] = defaultdict(int)
    comparable: Dict[int, int] = defaultdict(int)
    undated_pairs = 0

    for holders in by_movie.values():
        if len(holders) < 2:
            continue
        for (left_id, left_date), (right_id, right_date) in combinations(holders, 2):
            if left_date is None or right_date is None:
                undated_pairs += 1
                continue
            comparable[left_id] += 1
            comparable[right_id] += 1
            if left_date < right_date:
                first_counts[left_id] += 1
            elif right_date < left_date:
                first_counts[right_id] += 1
            else:
                # A tie is genuinely simultaneous. Crediting both would inflate
                # every share above 100%; crediting neither is the honest read.
                pass

    entries = []
    for profile_id, username in names.items():
        total = comparable.get(profile_id, 0)
        firsts = first_counts.get(profile_id, 0)
        entries.append(
            {
                "username": username,
                "firsts": firsts,
                "comparable": total,
                "share": round(firsts / total, 4) if total else None,
            }
        )
    entries.sort(key=lambda item: (item["share"] is None, -(item["share"] or 0)))

    return {
        "profiles": entries,
        "undated_pairs": undated_pairs,
        "caveat": (
            f"{undated_pairs:,} shared-film pairings have no first-watch date on one or both sides "
            "and are excluded rather than assumed late. That is why the shares below do not sum to "
            "anything meaningful."
            if undated_pairs
            else "Every shared film in the selection carries a first-watch date on both sides."
        ),
    }


def build_shared_firsts(
    db: Session, profiles: Sequence[Profile], *, limit: int = 12
) -> Dict[str, Any]:
    """Same film, same day, and it was the first ever watch for both of them.

    Stronger than any repeat co-watch: nobody was catching up with anybody, so
    the coincidence is the whole of the evidence rather than one person
    revisiting something the other had recommended.
    """

    names = {profile.id: profile.username for profile in profiles}
    rows = _first_watch_rows(db, list(names))

    by_movie: Dict[int, Dict[str, Any]] = {}
    for profile_id, movie_id, first_watched, title, year, poster_url in rows:
        entry = by_movie.setdefault(
            movie_id,
            {"title": title, "year": year, "poster_url": poster_url, "holders": []},
        )
        entry["holders"].append((profile_id, first_watched))

    results: List[Dict[str, Any]] = []
    eligible_profiles: set[int] = set()

    for entry in by_movie.values():
        dated = [(pid, day) for pid, day in entry["holders"] if day is not None]
        if len(dated) < 2:
            continue
        by_day: Dict[date, List[int]] = defaultdict(list)
        for profile_id, day in dated:
            by_day[day].append(profile_id)
        for day, holders in by_day.items():
            if len(holders) < 2:
                continue
            eligible_profiles.update(holders)
            results.append(
                {
                    "title": entry["title"],
                    "year": entry["year"],
                    "poster_url": entry["poster_url"],
                    "date": day.isoformat(),
                    "usernames": sorted(names[pid] for pid in holders),
                }
            )

    results.sort(key=lambda item: item["date"], reverse=True)

    dated_profiles = sorted(
        {
            names[profile_id]
            for profile_id, _movie, first_watched, *_rest in rows
            if first_watched is not None
        }
    )

    return {
        "shared_firsts": results[:limit],
        "count": len(results),
        "profiles_with_first_watch_dates": dated_profiles,
        "profiles_selected": len(names),
        "caveat": (
            f"Needs a first-watch date on both sides, so this only fires for the "
            f"{len(dated_profiles)} of {len(names)} selected profiles that have one. "
            f"{len(results)} qualifying film{'s' if len(results) != 1 else ''} in total."
        ),
    }
