"""What to actually watch, and where a film can be watched right now.

The one section with a deadline in it. Two things it refuses to do: invent an
expiry date the provider feed never publishes, and rank a list by progress it
cannot see because the list is not public.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from database.models import (
    Movie,
    MovieList,
    MovieListItem,
    MovieWatchProvider,
    Profile,
    ProfileFilm,
    WatchlistItem,
)


# A five-star rating from one person that nobody else has logged is the
# strongest recommendation the data holds.
BLIND_SPOT_RATING = 4.5


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    """Treat a naive timestamp as UTC.

    Postgres hands these back with a timezone; SQLite does not, and a driver
    that returns naive datetimes would otherwise raise on the first subtraction
    and take the whole panel down rather than showing a slightly wrong age.
    """

    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def build_blind_spot_favourites(
    db: Session, profiles: Sequence[Profile], *, limit: int = 12
) -> Dict[str, Any]:
    """Top-rated by one person, unlogged by everybody else in the room."""

    profile_ids = [profile.id for profile in profiles]
    if len(profile_ids) < 2:
        return {
            "films": [],
            "count": 0,
            "caveat": "Needs at least two profiles: a blind spot is somebody else not having seen it.",
        }

    rows = (
        db.query(ProfileFilm, Movie, Profile.username)
        .join(Movie, Movie.id == ProfileFilm.movie_id)
        .join(Profile, Profile.id == ProfileFilm.profile_id)
        .filter(ProfileFilm.profile_id.in_(profile_ids), ProfileFilm.removed_at.is_(None))
        .all()
    )

    holders: Dict[int, List[Any]] = defaultdict(list)
    for film, movie, username in rows:
        holders[movie.id].append((film, movie, username))

    films = []
    for entries in holders.values():
        if len(entries) != 1:
            continue
        film, movie, username = entries[0]
        if film.rating is None or film.rating < BLIND_SPOT_RATING:
            continue
        films.append(
            {
                "title": movie.title,
                "year": movie.release_year,
                "poster_url": movie.poster_url,
                "letterboxd_url": movie.letterboxd_url,
                "username": username,
                "rating": film.rating,
                "unseen_by": len(profile_ids) - 1,
            }
        )

    films.sort(key=lambda item: (-item["rating"], item["title"]))

    return {
        "films": films[:limit],
        "count": len(films),
        "caveat": (
            f"{len(films)} films rated {BLIND_SPOT_RATING} or higher by exactly one of the "
            f"{len(profile_ids)} selected profiles and logged by none of the others. An unrated "
            "film cannot qualify, however much somebody liked it."
        ),
    }


def build_list_progress(
    db: Session, profiles: Sequence[Profile], *, limit: int = 12
) -> Dict[str, Any]:
    """How far the group has got through each list it can see.

    Any watch by any selected profile counts. The interesting number is not the
    percentage but how many people it took to get there.
    """

    profile_ids = [profile.id for profile in profiles]
    if not profile_ids:
        return {"lists": [], "caveat": "No profiles selected."}

    watched_by: Dict[int, set] = defaultdict(set)
    for movie_id, profile_id in (
        db.query(ProfileFilm.movie_id, ProfileFilm.profile_id)
        .filter(ProfileFilm.profile_id.in_(profile_ids), ProfileFilm.removed_at.is_(None))
        .all()
    ):
        watched_by[movie_id].add(profile_id)

    # Scoped to the selection's own public lists, the same set "Work through a
    # list" shows. Unscoped, this counted every list in the store -- including
    # other people's, and including the private ones an account export brings
    # in -- while its own caption claimed the lists were "readable for this
    # selection". Three panels on this tab then reported three different
    # totals for the same word.
    rows = (
        db.query(MovieList, MovieListItem.movie_id)
        .join(MovieListItem, MovieListItem.movie_list_id == MovieList.id)
        .filter(
            MovieList.profile_id.in_(profile_ids),
            MovieList.is_public.is_(True),
            MovieList.removed_at.is_(None),
            MovieListItem.removed_at.is_(None),
        )
        .all()
    )

    grouped: Dict[int, Dict[str, Any]] = {}
    for movie_list, movie_id in rows:
        entry = grouped.setdefault(
            movie_list.id,
            {
                "name": movie_list.name,
                "owner_profile_id": movie_list.profile_id,
                "total": 0,
                "seen": 0,
                "contributors": set(),
            },
        )
        entry["total"] += 1
        holders = watched_by.get(movie_id)
        if holders:
            entry["seen"] += 1
            entry["contributors"].update(holders)

    lists = [
        {
            "name": entry["name"],
            "total": entry["total"],
            "seen": entry["seen"],
            "share": round(entry["seen"] / entry["total"], 4) if entry["total"] else None,
            "contributors": len(entry["contributors"]),
        }
        for entry in grouped.values()
        if entry["total"] > 0
    ]
    lists.sort(key=lambda item: (-(item["share"] or 0), -item["total"]))

    return {
        "lists": lists[:limit],
        "count": len(lists),
        "caveat": (
            f"{len(lists)} public {'list belongs' if len(lists) == 1 else 'lists belong'} to this "
            "selection. A private list is not counted at all — including one an account export "
            "brought in — so an absent list is not a list nobody has started."
        ),
    }


def build_list_only_films(
    db: Session, profiles: Sequence[Profile], *, limit: int = 12, min_lists: int = 2
) -> Dict[str, Any]:
    """Films on several lists the group follows that nobody has watched.

    Canonical blind spots rather than obscure ones.
    """

    profile_ids = [profile.id for profile in profiles]
    if not profile_ids:
        return {"films": [], "count": 0, "caveat": "No profiles selected."}

    watched = {
        movie_id
        for (movie_id,) in db.query(ProfileFilm.movie_id)
        .filter(ProfileFilm.profile_id.in_(profile_ids), ProfileFilm.removed_at.is_(None))
        .all()
    }
    queued = {
        movie_id
        for (movie_id,) in db.query(WatchlistItem.movie_id)
        .filter(WatchlistItem.profile_id.in_(profile_ids), WatchlistItem.removed_at.is_(None))
        .all()
    }

    rows = (
        db.query(MovieListItem.movie_id, Movie, func.count(MovieListItem.id))
        .join(Movie, Movie.id == MovieListItem.movie_id)
        .join(MovieList, MovieList.id == MovieListItem.movie_list_id)
        .filter(
            # Same scope as the panels above it: the selection's own public
            # lists. A blind spot drawn from a stranger's list is not one.
            MovieList.profile_id.in_(profile_ids),
            MovieList.is_public.is_(True),
            MovieListItem.removed_at.is_(None),
            MovieList.removed_at.is_(None),
        )
        .group_by(MovieListItem.movie_id, Movie.id)
        .all()
    )

    films = [
        {
            "title": movie.title,
            "year": movie.release_year,
            "poster_url": movie.poster_url,
            "letterboxd_url": movie.letterboxd_url,
            "lists": lists,
            "queued": movie_id in queued,
        }
        for movie_id, movie, lists in rows
        if lists >= min_lists and movie_id not in watched
    ]
    films.sort(key=lambda item: -item["lists"])

    return {
        "films": films[:limit],
        "count": len(films),
        "caveat": (
            f"On {min_lists} or more of the selection's own public lists and logged by nobody in "
            "it. A film on one list is not yet a canonical blind spot, so it is left out."
        ),
    }


def build_list_cadence(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """Who keeps their lists alive.

    A list last touched years ago is a document; one edited last week is a
    plan, and only the second is worth ranking against.
    """

    profile_ids = [profile.id for profile in profiles]
    names = {profile.id: profile.username for profile in profiles}
    if not profile_ids:
        return {"profiles": [], "caveat": "No profiles selected."}

    # Split by visibility rather than counted flat. Curating is curating
    # whether or not the list is published, so a private list still belongs in
    # this panel -- but every other list panel on the tab can only see the
    # public ones, and a bare total here read as a contradiction of them.
    rows = (
        db.query(
            MovieList.profile_id,
            func.count(MovieList.id),
            func.sum(case((MovieList.is_public.is_(True), 1), else_=0)),
            func.max(MovieList.updated_at),
        )
        .filter(MovieList.profile_id.in_(profile_ids), MovieList.removed_at.is_(None))
        .group_by(MovieList.profile_id)
        .all()
    )

    now = datetime.now(timezone.utc)
    by_profile = {
        profile_id: (count, int(public or 0), _aware(last))
        for profile_id, count, public, last in rows
    }

    entries = []
    private_total = 0
    for profile in profiles:
        count, public, last = by_profile.get(profile.id, (0, 0, None))
        private_total += count - public
        days = (now - last).days if last else None
        if count == 0:
            read = "Never made one"
        elif days is None:
            read = "No edit date recorded"
        elif days <= 30:
            read = "Actively curating"
        elif days <= 180:
            read = "Occasionally tended"
        else:
            read = "Collector, not curator"
        entries.append(
            {
                "username": names.get(profile.id, profile.username),
                "lists": count,
                "public_lists": public,
                "last_edit_days": days,
                "read": read,
            }
        )

    entries.sort(key=lambda item: (item["last_edit_days"] is None, item["last_edit_days"] or 0))

    return {
        "profiles": entries,
        "private_lists": private_total,
        "caveat": (
            "Edit dates come from the list surface, which is read on its own schedule. A list we "
            "have never re-read looks stale here even if it changed yesterday."
            + (
                f" {private_total} of these are private and appear in no other panel on this tab: "
                "an account export carries them, a public page never would."
                if private_total
                else ""
            )
        ),
    }


def build_availability(db: Session, profiles: Sequence[Profile], *, region: str = "IN") -> Dict[str, Any]:
    """Where a queued film can be streamed, and how fresh that reading is.

    Deliberately not a countdown. The provider feed publishes which services
    carry a film today and nothing about when that stops being true, so a
    "days left" figure would be a guess wearing a number's clothes.
    """

    profile_ids = [profile.id for profile in profiles]
    if not profile_ids:
        return {"films": [], "regions": [], "caveat": "No profiles selected."}

    queued = (
        db.query(WatchlistItem.movie_id, Movie, Profile.username)
        .join(Movie, Movie.id == WatchlistItem.movie_id)
        .join(Profile, Profile.id == WatchlistItem.profile_id)
        .filter(WatchlistItem.profile_id.in_(profile_ids), WatchlistItem.removed_at.is_(None))
        .all()
    )

    wanted_by: Dict[int, Dict[str, Any]] = {}
    for movie_id, movie, username in queued:
        entry = wanted_by.setdefault(movie_id, {"movie": movie, "usernames": []})
        entry["usernames"].append(username)

    providers = (
        db.query(MovieWatchProvider)
        .filter(
            MovieWatchProvider.movie_id.in_(list(wanted_by)),
            MovieWatchProvider.region == region,
            MovieWatchProvider.provider_type == "flatrate",
        )
        .all()
        if wanted_by
        else []
    )

    by_movie: Dict[int, List[MovieWatchProvider]] = defaultdict(list)
    for provider in providers:
        by_movie[provider.movie_id].append(provider)

    films = []
    for movie_id, entry in wanted_by.items():
        carriers = by_movie.get(movie_id, [])
        if not carriers:
            continue
        checked = max(_aware(provider.fetched_at) for provider in carriers)
        films.append(
            {
                "title": entry["movie"].title,
                "year": entry["movie"].release_year,
                "poster_url": entry["movie"].poster_url,
                "letterboxd_url": entry["movie"].letterboxd_url,
                "usernames": sorted(set(entry["usernames"])),
                "wanted_by": len(set(entry["usernames"])),
                "providers": sorted({provider.provider_name for provider in carriers}),
                "checked_at": checked.isoformat() if checked else None,
            }
        )

    films.sort(key=lambda item: (-item["wanted_by"], item["title"]))

    region_rows = (
        db.query(
            MovieWatchProvider.region,
            func.count(func.distinct(MovieWatchProvider.movie_id)),
            func.max(MovieWatchProvider.fetched_at),
        )
        .group_by(MovieWatchProvider.region)
        .all()
    )
    now = datetime.now(timezone.utc)
    regions = []
    for code, films_count, raw_checked in region_rows:
        checked = _aware(raw_checked)
        regions.append(
            {
                "region": code,
                "films": films_count,
                "checked_at": checked.isoformat() if checked else None,
                "days_ago": (now - checked).days if checked else None,
                # Availability is the fastest-rotting data in the product.
                "stale": bool(checked and (now - checked).days > 14),
            }
        )
    regions.sort(key=lambda item: (item["days_ago"] is None, item["days_ago"] or 0))

    # A region nobody has ever fetched holds no rows, which is not the same
    # fact as a region that was read and carries none of the queue. Reporting
    # the first as the second is the one thing this section is not allowed to
    # do, and the freshness panel beside it already says so in words.
    region_read = any(entry["region"] == region for entry in regions)
    if region_read:
        scope = (
            f"{len(films)} queued films are carried by a subscription service in {region} as of "
            "the last reading."
        )
    else:
        others = ", ".join(entry["region"] for entry in regions[:5])
        scope = (
            f"{region} has never been read, so this is empty for want of a fetch rather than for "
            "want of availability."
            + (f" The regions we do hold are {others}." if others else "")
        )

    return {
        "films": films,
        "region": region,
        "region_read": region_read,
        "regions": regions,
        "caveat": (
            f"{scope} There is no countdown here on purpose: the provider feed publishes what "
            "carries a film today and nothing about when that stops, so a \"days left\" figure "
            "would be invented rather than read."
        ),
    }
