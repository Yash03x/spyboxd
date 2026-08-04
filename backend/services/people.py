"""What one person is like, read from rows nothing else looks at.

Each function here answers a question the per-profile stats endpoint does not:
the holes in somebody's evidence (watched but never rated), the top of their
scale where they said nothing, the rewatch that changed their mind, and the
silence that is long enough to mean something against their own rhythm.

Two rules run through all of it. Change needs two authoritative reads, so
anything derived from ``profile_data_changes`` is empty on a first import by
design and says so. And absence is never deletion: a soft-removed row is
history, not a current fact, and is filtered out rather than counted.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from statistics import median
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import (
    Movie,
    Profile,
    ProfileDataChange,
    ProfileFavoriteMovie,
    ProfileFilm,
    Review,
    WatchEvent,
)


def _movie_payload(movie: Movie) -> Dict[str, Any]:
    return {
        "title": movie.title,
        "year": movie.release_year,
        "poster_url": movie.poster_url,
        "letterboxd_url": movie.letterboxd_url,
    }


def build_unrated(db: Session, profile: Profile, *, limit: int = 12) -> Dict[str, Any]:
    """Films they logged and never rated.

    A hole in the evidence rather than an opinion. Every comparison in People
    and Overlaps skips these silently, so the size of the hole is worth stating
    beside them.
    """

    rows = (
        db.query(ProfileFilm, Movie)
        .join(Movie, Movie.id == ProfileFilm.movie_id)
        .filter(
            ProfileFilm.profile_id == profile.id,
            ProfileFilm.removed_at.is_(None),
            ProfileFilm.rating.is_(None),
        )
        .order_by(ProfileFilm.latest_watched_date.desc().nullslast(), Movie.title)
        .all()
    )

    library = (
        db.query(ProfileFilm)
        .filter(ProfileFilm.profile_id == profile.id, ProfileFilm.removed_at.is_(None))
        .count()
    )

    films = [
        {
            **_movie_payload(movie),
            "watch_count": film.watch_count,
            "first_watched_date": film.first_watched_date.isoformat()
            if film.first_watched_date
            else None,
            "latest_watched_date": film.latest_watched_date.isoformat()
            if film.latest_watched_date
            else None,
            "has_review": bool(film.has_review),
        }
        for film, movie in rows[:limit]
    ]

    return {
        "username": profile.username,
        "unrated": len(rows),
        "library": library,
        "share": round(len(rows) / library, 4) if library else None,
        "films": films,
        "caveat": (
            f"{len(rows):,} of {library:,} films in their library carry no rating. "
            "Every star comparison in the product skips these rather than treating an "
            "absent rating as a low one."
            if library
            else "Nothing imported for this profile yet."
        ),
    }


# Below this there is no "top of the scale" to be silent about.
SILENT_FIVE_THRESHOLD = 5.0


def build_silent_fives(db: Session, profile: Profile, *, limit: int = 12) -> Dict[str, Any]:
    """Top-of-scale ratings with no review text.

    The films that meant enough not to write about. Invisible to every panel
    that reads review bodies, which is most of them.
    """

    rows = (
        db.query(ProfileFilm, Movie)
        .join(Movie, Movie.id == ProfileFilm.movie_id)
        .filter(
            ProfileFilm.profile_id == profile.id,
            ProfileFilm.removed_at.is_(None),
            ProfileFilm.rating >= SILENT_FIVE_THRESHOLD,
            ProfileFilm.has_review.is_(False),
        )
        .order_by(ProfileFilm.watch_count.desc(), Movie.title)
        .all()
    )

    top_rated = (
        db.query(ProfileFilm)
        .filter(
            ProfileFilm.profile_id == profile.id,
            ProfileFilm.removed_at.is_(None),
            ProfileFilm.rating >= SILENT_FIVE_THRESHOLD,
        )
        .count()
    )

    reviews_total = (
        db.query(Review)
        .filter(Review.profile_id == profile.id, Review.removed_at.is_(None))
        .count()
    )
    library = (
        db.query(ProfileFilm)
        .filter(ProfileFilm.profile_id == profile.id, ProfileFilm.removed_at.is_(None))
        .count()
    )
    review_rate = reviews_total / library if library else None

    return {
        "username": profile.username,
        "silent": len(rows),
        "top_rated": top_rated,
        "films": [
            {**_movie_payload(movie), "rating": film.rating, "watch_count": film.watch_count}
            for film, movie in rows[:limit]
        ],
        "caveat": (
            f"{len(rows):,} of their {top_rated:,} five-star rating{'s carry' if top_rated != 1 else ' carries'} no review."
            + (
                f" Against a {round(review_rate * 100)}% review rate overall, silence at the top of "
                "the scale is the pattern rather than the exception."
                if review_rate is not None and top_rated
                else ""
            )
            if top_rated
            else "No five-star ratings imported for this profile yet."
        ),
    }


def build_rewatch_shifts(db: Session, profile: Profile, *, limit: int = 12) -> Dict[str, Any]:
    """Films whose rating moved between two authoritative reads.

    Needs two reads of the same profile: a first import is a baseline and
    records no change at all, which is why this stays empty by design rather
    than by accident.
    """

    rows = (
        db.query(ProfileDataChange, Movie)
        .outerjoin(Movie, Movie.id == ProfileDataChange.movie_id)
        .filter(
            ProfileDataChange.profile_id == profile.id,
            ProfileDataChange.change_type == "rating_changed",
        )
        .order_by(ProfileDataChange.detected_at.desc())
        .all()
    )

    shifts: List[Dict[str, Any]] = []
    for change, movie in rows:
        before = (change.before_payload or {}).get("rating")
        after = (change.after_payload or {}).get("rating")
        if before is None or after is None:
            continue
        try:
            before_value = float(before)
            after_value = float(after)
        except (TypeError, ValueError):
            continue
        if before_value == after_value:
            continue
        shifts.append(
            {
                "title": movie.title if movie else change.entity_key,
                "year": movie.release_year if movie else None,
                "poster_url": movie.poster_url if movie else None,
                "before": before_value,
                "after": after_value,
                "shift": round(after_value - before_value, 2),
                "detected_at": change.detected_at.isoformat() if change.detected_at else None,
            }
        )

    rose = sum(1 for shift in shifts if shift["shift"] > 0)
    fell = sum(1 for shift in shifts if shift["shift"] < 0)

    return {
        "username": profile.username,
        "shifts": shifts[:limit],
        "count": len(shifts),
        "rose": rose,
        "fell": fell,
        "caveat": (
            f"{len(shifts):,} rating{'s' if len(shifts) != 1 else ''} changed between reads — "
            f"{rose} up, {fell} down."
            if shifts
            else "Nothing here yet. A rating change is only detectable between two authoritative "
            "reads of the same profile; a first import establishes the baseline and emits nothing."
        ),
    }


def build_favourites(db: Session, profile: Profile) -> Dict[str, Any]:
    """The four slots, and every swap we have observed.

    Letterboxd stores no history for this: a swap is only visible as the
    difference between two reads, so the changes come from
    ``profile_data_changes`` rather than from a removal timestamp the table
    does not carry.
    """

    current = (
        db.query(ProfileFavoriteMovie, Movie)
        .join(Movie, Movie.id == ProfileFavoriteMovie.movie_id)
        .filter(ProfileFavoriteMovie.profile_id == profile.id)
        .order_by(ProfileFavoriteMovie.position)
        .all()
    )

    ratings = {
        film.movie_id: film.rating
        for film in db.query(ProfileFilm)
        .filter(ProfileFilm.profile_id == profile.id, ProfileFilm.removed_at.is_(None))
        .all()
    }

    changes = (
        db.query(ProfileDataChange, Movie)
        .outerjoin(Movie, Movie.id == ProfileDataChange.movie_id)
        .filter(
            ProfileDataChange.profile_id == profile.id,
            ProfileDataChange.entity_type == "favorite",
        )
        .order_by(ProfileDataChange.detected_at.desc())
        .limit(12)
        .all()
    )

    return {
        "username": profile.username,
        "favourites": [
            {
                **_movie_payload(movie),
                "position": favourite.position,
                "rating": ratings.get(favourite.movie_id),
                "first_seen": favourite.created_at.isoformat() if favourite.created_at else None,
            }
            for favourite, movie in current
        ],
        "changes": [
            {
                "change_type": change.change_type,
                "title": movie.title if movie else change.entity_key,
                "year": movie.release_year if movie else None,
                "detected_at": change.detected_at.isoformat() if change.detected_at else None,
                "before": change.before_payload or {},
                "after": change.after_payload or {},
            }
            for change, movie in changes
        ],
        "caveat": (
            "Four slots, chosen deliberately and changed rarely. A swap is only visible as the "
            "difference between two authoritative reads — Letterboxd publishes no history for it — "
            "so the list of changes starts empty and fills from the second refresh onward."
        ),
    }


# A profile's own rhythm is the only fair yardstick: somebody who logs weekly
# going dark for a month means more than a monthly logger doing the same.
QUIET_MULTIPLE = 2.0
MIN_GAPS_FOR_RHYTHM = 5


def build_quiet(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """How long each profile has been silent, against its own usual gap."""

    today = datetime.now(timezone.utc).date()
    entries: List[Dict[str, Any]] = []

    for profile in profiles:
        dates = [
            row[0]
            for row in db.query(WatchEvent.watched_date)
            .filter(
                WatchEvent.profile_id == profile.id,
                WatchEvent.superseded_at.is_(None),
                WatchEvent.watched_date.isnot(None),
            )
            .distinct()
            .order_by(WatchEvent.watched_date)
            .all()
        ]
        if not dates:
            entries.append(
                {
                    "username": profile.username,
                    "silent_days": None,
                    "usual_gap_days": None,
                    "multiple": None,
                    "read": "No dated watches, so there is no rhythm to measure silence against.",
                }
            )
            continue

        gaps = [(later - earlier).days for earlier, later in zip(dates, dates[1:])]
        usual = median(gaps) if len(gaps) >= MIN_GAPS_FOR_RHYTHM else None
        silent = (today - dates[-1]).days
        multiple = round(silent / usual, 2) if usual else None

        if usual is None:
            read = "Too few dated entries to know their normal gap yet."
        elif multiple is not None and multiple >= 9:
            read = f"{round(multiple)} times their normal gap"
        elif multiple is not None and multiple >= QUIET_MULTIPLE:
            read = f"Nearly {round(multiple)} times their normal gap — watch this one"
        elif multiple is not None and multiple >= 1:
            read = "Within their normal range"
        else:
            read = "Normal"

        entries.append(
            {
                "username": profile.username,
                "silent_days": silent,
                "usual_gap_days": usual,
                "multiple": multiple,
                "read": read,
            }
        )

    entries.sort(key=lambda item: (item["multiple"] is None, -(item["multiple"] or 0)))

    return {
        "profiles": entries,
        "caveat": (
            "Silence is measured against each profile's own median gap, not a global threshold, "
            f"and only once at least {MIN_GAPS_FOR_RHYTHM} gaps exist. A profile whose feed is "
            "failing looks identical here to one that stopped watching — the refresh ledger in "
            "Data tells those two apart."
        ),
    }


def build_reviews_per_watch(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """How often watching turns into writing, per profile.

    Separates the diarist from the critic without reading a word of anybody's
    prose.
    """

    entries: List[Dict[str, Any]] = []
    for profile in profiles:
        films = (
            db.query(func.count(ProfileFilm.id))
            .filter(ProfileFilm.profile_id == profile.id, ProfileFilm.removed_at.is_(None))
            .scalar()
            or 0
        )
        reviews = (
            db.query(func.count(Review.id))
            .filter(Review.profile_id == profile.id, Review.removed_at.is_(None))
            .scalar()
            or 0
        )
        entries.append(
            {
                "username": profile.username,
                "reviews": reviews,
                "films": films,
                "ratio": round(reviews / films, 4) if films else None,
            }
        )

    entries.sort(key=lambda item: (item["ratio"] is None, -(item["ratio"] or 0)))

    return {
        "profiles": entries,
        "caveat": (
            "Reviews divided by films held. A review that never resolved to a film in the library "
            "still counts in the numerator, so a profile whose reviews outrun its diary can exceed "
            "one — that is a coverage gap, not a reading habit."
        ),
    }


def build_tag_overlap(db: Session, profiles: Sequence[Profile], *, limit: int = 12) -> Dict[str, Any]:
    """Tags more than one selected profile uses.

    Private vocabulary, independently invented. Tags come from the diary
    surface only, so a profile read by an older importer has none at all
    rather than none used.
    """

    usage: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    carriers: List[str] = []

    for profile in profiles:
        rows = (
            db.query(ProfileFilm.tags)
            .filter(ProfileFilm.profile_id == profile.id, ProfileFilm.removed_at.is_(None))
            .all()
        )
        has_any = False
        for (tags,) in rows:
            for tag in tags or []:
                label = str(tag).strip().casefold()
                if not label:
                    continue
                usage[label][profile.username] += 1
                has_any = True
        if has_any:
            carriers.append(profile.username)

    shared = [
        {
            "tag": tag,
            "profiles": sorted(by_profile),
            "counts": dict(sorted(by_profile.items())),
            "total": sum(by_profile.values()),
        }
        for tag, by_profile in usage.items()
        if len(by_profile) > 1
    ]
    shared.sort(key=lambda item: (-len(item["profiles"]), -item["total"], item["tag"]))

    return {
        "tags": shared[:limit],
        "count": len(shared),
        "profiles_with_tags": carriers,
        "profiles_selected": len(profiles),
        "caveat": (
            f"{len(carriers)} of {len(profiles)} selected profiles carry any tags at all. Tags are "
            "read from the diary surface, so a profile last read by an older importer shows none — "
            "which is not the same as using none."
        ),
    }


def build_decade_drift(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """Average release year of what each profile watched, per year of watching.

    Somebody walking backwards through film history looks nothing like somebody
    who always watched old films, and a single current average cannot tell them
    apart.
    """

    series: Dict[str, List[Dict[str, Any]]] = {}
    for profile in profiles:
        rows = (
            db.query(WatchEvent.watched_date, Movie.release_year)
            .join(Movie, Movie.id == WatchEvent.movie_id)
            .filter(
                WatchEvent.profile_id == profile.id,
                WatchEvent.superseded_at.is_(None),
                WatchEvent.watched_date.isnot(None),
                Movie.release_year.isnot(None),
            )
            .all()
        )
        by_year: Dict[int, List[int]] = defaultdict(list)
        for watched_date, release_year in rows:
            by_year[watched_date.year].append(release_year)

        series[profile.username] = [
            {
                "year": year,
                "average_release_year": round(sum(values) / len(values), 1),
                "films": len(values),
            }
            for year, values in sorted(by_year.items())
        ]

    measured = sum(len(points) for points in series.values())

    return {
        "profiles": series,
        "caveat": (
            "Average release year of what was watched, by year of watching. Films with no release "
            "year are excluded rather than dated to the present, so a year with few enriched films "
            "carries a thin average."
            if measured
            else "No dated watches with a known release year, so there is no drift to plot."
        ),
    }


def build_pair_blind_spots(
    db: Session,
    pair: Sequence[Profile],
    circle: Sequence[Profile],
    *,
    limit: int = 12,
    min_raters: int = 2,
    min_average: float = 4.0,
) -> Dict[str, Any]:
    """Films the rest of the circle rates highly that neither of the pair has logged.

    A pair-level blind spot, which is a better shortlist than either watchlist:
    it is built from what people they actually follow already liked.
    """

    pair_ids = [profile.id for profile in pair]
    others = [profile for profile in circle if profile.id not in set(pair_ids)]
    if len(pair) < 2 or not others:
        return {
            "films": [],
            "count": 0,
            "caveat": "Needs two people and at least one other tracked profile to compare against.",
        }

    seen_movie_ids = {
        row[0]
        for row in db.query(ProfileFilm.movie_id)
        .filter(ProfileFilm.profile_id.in_(pair_ids), ProfileFilm.removed_at.is_(None))
        .all()
    }

    rows = (
        db.query(ProfileFilm, Movie, Profile.username)
        .join(Movie, Movie.id == ProfileFilm.movie_id)
        .join(Profile, Profile.id == ProfileFilm.profile_id)
        .filter(
            ProfileFilm.profile_id.in_([profile.id for profile in others]),
            ProfileFilm.removed_at.is_(None),
            ProfileFilm.rating.isnot(None),
        )
        .all()
    )

    by_movie: Dict[int, Dict[str, Any]] = {}
    for film, movie, username in rows:
        if movie.id in seen_movie_ids:
            continue
        entry = by_movie.setdefault(
            movie.id, {"movie": movie, "ratings": [], "raters": []}
        )
        entry["ratings"].append(film.rating)
        entry["raters"].append(username)

    candidates = []
    for entry in by_movie.values():
        if len(entry["ratings"]) < min_raters:
            continue
        average = sum(entry["ratings"]) / len(entry["ratings"])
        if average < min_average:
            continue
        candidates.append(
            {
                **_movie_payload(entry["movie"]),
                "raters": sorted(entry["raters"]),
                "rater_count": len(entry["ratings"]),
                "average_rating": round(average, 2),
            }
        )

    candidates.sort(key=lambda item: (-item["average_rating"], -item["rater_count"]))

    return {
        "films": candidates[:limit],
        "count": len(candidates),
        "caveat": (
            f"Rated at least {min_average:.1f} by {min_raters} or more of the other tracked "
            f"profiles, and logged by neither of the pair. {len(candidates)} qualify."
        ),
    }


def build_rename_resilience(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """Which profiles could survive a rename, and what a rename costs us.

    Letterboxd's member id is stable across a username change, and the importer
    uses it to rename a profile in place rather than create a second one. It
    does not keep the old username: the row is updated, not versioned. So this
    reports what a rename would and would not cost rather than listing renames
    that were never recorded — an empty history table would read as "nobody has
    ever renamed", which is a different and unearned claim.
    """

    resilient = [profile for profile in profiles if profile.letterboxd_person_id is not None]
    fragile = [profile for profile in profiles if profile.letterboxd_person_id is None]

    return {
        "profiles": [
            {
                "username": profile.username,
                "member_id": profile.letterboxd_person_id,
                "survives_rename": profile.letterboxd_person_id is not None,
            }
            for profile in profiles
        ],
        "resilient": [profile.username for profile in resilient],
        "fragile": [profile.username for profile in fragile],
        "caveat": (
            f"{len(resilient)} of {len(profiles)} selected profiles carry the member id a rename "
            "survives — those get renamed in place on the next read instead of duplicated as a new "
            "account. The previous username is not retained: the row is updated, not versioned, so "
            "this panel reports what a rename would cost rather than listing renames nobody recorded."
        ),
    }


def build_member_card(db: Session, profile: Profile) -> Dict[str, Any]:
    """Badge, pronouns, location, bio.

    Pronouns come from the official export only. Where a profile has not
    supplied one, the field is absent rather than guessed at.
    """

    # Letterboxd publishes no join date on a public page, so the earliest diary
    # entry is the honest answer to "how far back can we see this person".
    first_logged: Optional[date] = (
        db.query(func.min(WatchEvent.watched_date))
        .filter(
            WatchEvent.profile_id == profile.id,
            WatchEvent.superseded_at.is_(None),
            WatchEvent.watched_date.isnot(None),
        )
        .scalar()
    )
    return {
        "username": profile.username,
        "display_name": profile.display_name,
        "badge": profile.member_badge,
        "pronoun": profile.pronoun,
        "location": profile.location,
        "bio": profile.bio,
        "join_date": profile.join_date.isoformat() if profile.join_date else None,
        "first_logged_date": first_logged.isoformat() if first_logged else None,
        "external_links": profile.external_links or [],
        "followers_count": profile.followers_count,
        "following_count": profile.following_count,
        "caveat": (
            "Pronouns and location come from an official export only. Where a profile has not "
            "supplied one, the row is absent rather than filled with a guess — and Letterboxd "
            "publishes no join date on a public page at all."
        ),
    }


def build_reach(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """Audience against attention: followers beside following.

    Both figures are Letterboxd's own, read off the profile header — they count
    the whole site rather than the monitored set, which is what makes them
    different from the mutual counts in The circle. A profile whose header was
    never read has null on both, which is not the same as zero.
    """

    entries = [
        {
            "username": profile.username,
            "followers": profile.followers_count,
            "following": profile.following_count,
            "ratio": (
                round(profile.followers_count / profile.following_count, 3)
                if profile.followers_count is not None and profile.following_count
                else None
            ),
        }
        for profile in profiles
    ]
    entries.sort(key=lambda item: (item["followers"] is None, -(item["followers"] or 0)))

    measured = [entry for entry in entries if entry["followers"] is not None]

    return {
        "profiles": entries,
        "caveat": (
            f"{len(measured)} of {len(entries)} selected profiles have had their header read. "
            "Both counts are Letterboxd's own and cover the whole site, not the monitored set — "
            "a profile with no reading has null on both, which is not the same as zero."
        ),
    }
