"""A watchlist ranked by the verdict of the circle that already saw the films.

A Letterboxd watchlist is a bag: it remembers what a member meant to watch and
nothing about whether it was worth watching. Letterboxd can only ever answer
that with its own site-wide average, which says what several hundred thousand
strangers thought. We already hold every tracked profile's rating, so a film
sitting unwatched on one watchlist can carry the far more useful number -- what
*this member's own people* scored it -- and that is the ranking built here.

Three rules keep the ranking honest.

* **Only unwatched films are recommended.** A watchlist row for a film that
  already has a ``profile_films`` row for this profile is stale bookkeeping,
  not a suggestion, so it is dropped from every list and from ``coverage``.
  Any such row counts, removed ones included: a film that later left the
  library was still watched.
* **The group average for a film always excludes the profile being served.**
  This falls out of the rule above for recommendations, and is enforced in the
  query regardless so no surface can ever recommend a film to someone on the
  strength of their own rating.
* **A recommendation needs at least one other rater.** With no rating behind
  it there is no verdict to rank on, so the film stays a candidate -- counted
  in ``coverage.watchlist_films``, eligible for ``longest_waiting`` and
  ``genre_skew`` -- but never appears in ``recommendations``.

Nothing here extrapolates. ``coverage`` reports how much of the watchlist each
figure was computed over so a client can qualify a partial answer, and every
unknown is null rather than zero: a film with no ``added_date`` has an unknown
wait, not a zero-day one, and is left out of the wait statistics entirely
instead of being counted as freshly added.

The Letterboxd crowd average is the only external reference and is never
required. ``movies.letterboxd_average_rating`` is backfilled separately, so
``letterboxd_average`` is simply null for a film that backfill has not reached
and the rest of the payload is unaffected.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased, load_only

from database.models import (
    Movie,
    MovieEnrichment,
    Profile,
    ProfileFilm,
    WatchlistItem,
)
from services.insights import InsightsService, _as_string_list, _average, _round, _safe_float


# One other rater is enough to rank on -- it is a verdict, thin but real --
# and below it there is nothing to rank at all.
MIN_GROUP_RATERS = 1

# The ranked queue a client actually renders. Its cap is the request's
# ``limit``; the supporting lists are summaries and keep a fixed ceiling.
DEFAULT_LIMIT = 20
MAX_LIMIT = 50

# Enough names to show who liked it without turning a card into a roster.
SHRINKAGE_PRIOR_RATERS = 2

MAX_RATERS_LISTED = 6

# ``longest_waiting`` and ``genre_skew`` are summaries, not exports.
MAX_SECONDARY_ENTRIES = 10


class _Rater(NamedTuple):
    """One other member's rating for a film on this profile's watchlist."""

    username: str
    rating: float


@dataclass(frozen=True)
class _Opinions:
    """What the rest of the circle did with one film."""

    raters: Tuple[_Rater, ...] = ()
    liked_by: int = 0

    @property
    def group_average(self) -> Optional[float]:
        return _average([rater.rating for rater in self.raters])

    @property
    def is_recommendable(self) -> bool:
        return len(self.raters) >= MIN_GROUP_RATERS


@dataclass(frozen=True)
class _Candidate:
    """One active watchlist row for a film this profile has not watched."""

    movie_id: int
    title: str
    added_date: Optional[date]
    letterboxd_average: Optional[float]
    # What the crowd's ten buckets say beyond their mean. Two films can share an
    # average of 3.5 while one splits the room and the other bores it equally,
    # and the mean cannot tell them apart.
    crowd_ceiling: Optional[float]
    crowd_floor: Optional[float]
    genres: Tuple[str, ...]
    opinions: _Opinions

    def days_waiting(self, today: date) -> Optional[int]:
        """Days since it was added, or null when the import carried no date.

        Letterboxd only publishes an added date on some watchlist surfaces, so
        a null here is a genuine unknown. A row dated in the future is clamped
        to zero rather than reported as a negative wait.
        """

        if self.added_date is None:
            return None
        return max(0, (today - self.added_date).days)


# Half-star buckets counted as "this film can be a favourite" and "this film
# can be a write-off". Deliberately not the extremes alone: a 4.5 is already an
# enthusiastic verdict, and a 2.0 already a dismissal.
CEILING_FROM = 4.5
FLOOR_TO = 2.0


def _crowd_shape(distribution: Any) -> Tuple[Optional[float], Optional[float]]:
    """Share of the crowd at 4.5+ and at 2.0-, from the stored histogram.

    Returns nulls when no histogram has been imported for the film, which is a
    real state rather than a zero: "nobody rated it highly" and "we have not
    looked" are different answers.
    """

    if not isinstance(distribution, dict) or not distribution:
        return None, None
    total = 0
    ceiling = 0
    floor = 0
    for key, value in distribution.items():
        try:
            stars = float(key)
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count < 0:
            continue
        total += count
        if stars >= CEILING_FROM:
            ceiling += count
        if stars <= FLOOR_TO:
            floor += count
    if total <= 0:
        return None, None
    return round(ceiling / total, 4), round(floor / total, 4)


def _letterboxd_average(value: Any) -> Optional[float]:
    """The Letterboxd crowd average, or null while the backfill is pending."""

    average = _safe_float(value)
    return average if average is not None and average > 0 else None


def _watchlist_movie_ids(profile_id: int):
    """Subquery: the movies on this profile's active watchlist."""

    watchlist = aliased(WatchlistItem)
    return select(watchlist.movie_id).where(
        watchlist.profile_id == profile_id,
        watchlist.removed_at.is_(None),
    )



def _group_baseline_rating(db: Session, profile_id: int) -> float:
    """What a film typically scores from this circle, across everything rated.

    The prior has to come from general behaviour, not from the watchlist
    candidates: those are films people chose to queue, so their mean runs high
    and shrinking toward it barely moves a lone five-star rating. Averaging the
    circle's whole rated history gives the honest "expected" score to pull
    thin verdicts back toward.
    """

    baseline = (
        db.query(func.avg(ProfileFilm.rating))
        .join(Profile, Profile.id == ProfileFilm.profile_id)
        .filter(
            ProfileFilm.profile_id != profile_id,
            ProfileFilm.rating.isnot(None),
            ProfileFilm.removed_at.is_(None),
            Profile.is_active.is_(True),
            Profile.scraping_status == "completed",
        )
        .scalar()
    )
    return float(baseline) if baseline is not None else 0.0


def _group_opinions(db: Session, profile_id: int) -> Dict[int, _Opinions]:
    """Every *other* tracked profile's rating and like for the watchlist films.

    Restricted to the watchlist by subquery, so a shared movie table spanning
    thousands of films never leaves the database, and gathered in one query
    rather than one per film. Only active, completed profiles count towards the
    group, matching the rule the rest of the app uses for a usable profile.
    """

    rows = (
        db.query(
            ProfileFilm.movie_id,
            ProfileFilm.rating,
            ProfileFilm.is_liked,
            Profile.username,
        )
        .join(Profile, Profile.id == ProfileFilm.profile_id)
        .filter(
            ProfileFilm.profile_id != profile_id,
            ProfileFilm.removed_at.is_(None),
            Profile.is_active.is_(True),
            Profile.scraping_status == "completed",
            ProfileFilm.movie_id.in_(_watchlist_movie_ids(profile_id)),
        )
        .all()
    )

    raters: Dict[int, List[_Rater]] = {}
    likes: Counter[int] = Counter()
    for movie_id, rating, is_liked, username in rows:
        key = int(movie_id)
        value = _safe_float(rating)
        if value is not None:
            raters.setdefault(key, []).append(_Rater(username or "", value))
        if is_liked:
            likes[key] += 1

    return {
        movie_id: _Opinions(
            raters=tuple(
                sorted(
                    raters.get(movie_id, ()),
                    key=lambda rater: (-rater.rating, rater.username.casefold()),
                )
            ),
            liked_by=likes.get(movie_id, 0),
        )
        for movie_id in set(raters) | set(likes)
    }


def _candidates(db: Session, profile_id: int) -> List[_Candidate]:
    """Bulk-load the unwatched watchlist in one query, opinions in a second.

    Films the profile already has a ``profile_films`` row for are excluded in
    SQL by subquery, so a large library is never shipped to Python to be
    filtered. Only the columns this module reads are selected -- in particular
    never ``MovieEnrichment.raw_payload``, which holds the whole TMDB response.
    """

    watched = select(ProfileFilm.movie_id).where(ProfileFilm.profile_id == profile_id)
    rows = (
        db.query(
            WatchlistItem.movie_id,
            WatchlistItem.added_date,
            Movie.title,
            Movie.letterboxd_average_rating,
            Movie.letterboxd_rating_distribution,
            MovieEnrichment.genres,
        )
        .join(Movie, Movie.id == WatchlistItem.movie_id)
        .outerjoin(MovieEnrichment, MovieEnrichment.movie_id == Movie.id)
        .filter(
            WatchlistItem.profile_id == profile_id,
            WatchlistItem.removed_at.is_(None),
            WatchlistItem.movie_id.notin_(watched),
        )
        .all()
    )
    opinions = _group_opinions(db, profile_id)
    candidates = []
    for row in rows:
        ceiling, floor = _crowd_shape(row.letterboxd_rating_distribution)
        candidates.append(
            _Candidate(
                movie_id=int(row.movie_id),
                title=row.title or "",
                added_date=row.added_date,
                letterboxd_average=_letterboxd_average(row.letterboxd_average_rating),
                crowd_ceiling=ceiling,
                crowd_floor=floor,
                genres=tuple(_as_string_list(row.genres)),
                opinions=opinions.get(int(row.movie_id), _Opinions()),
            )
        )
    return candidates


def _film_identities(db: Session, movie_ids: Sequence[int]) -> Dict[int, Dict[str, Any]]:
    """Display fields for the handful of films that reached an output list.

    Poster hygiene (TMDB path, placeholder rejection, Letterboxd image
    endpoints) already lives in ``InsightsService._movie_summary``; this reuses
    it rather than growing a second copy of those rules.
    """

    if not movie_ids:
        return {}
    rows = (
        db.query(Movie, MovieEnrichment)
        .outerjoin(MovieEnrichment, MovieEnrichment.movie_id == Movie.id)
        .options(load_only(MovieEnrichment.movie_id, MovieEnrichment.poster_path))
        .filter(Movie.id.in_(set(movie_ids)))
        .all()
    )
    identities: Dict[int, Dict[str, Any]] = {}
    for movie, enrichment in rows:
        summary = InsightsService._movie_summary(movie, enrichment)
        identities[movie.id] = {
            "title": summary["title"],
            "year": summary["year"],
            "poster_url": summary["poster_url"],
            "letterboxd_url": summary["letterboxd_url"],
        }
    return identities


def _whole_days(value: Optional[float]) -> Optional[int]:
    """Round a day count half-up, so a 30.5-day median never reads as 30."""

    if value is None:
        return None
    return int(math.floor(value + 0.5))


def median_days_waiting(waits: Sequence[int]) -> Optional[int]:
    """The middle wait, over dated rows only -- unknown when none are dated.

    Undated rows are absent from ``waits`` rather than folded in as zero, which
    would drag the median toward "just added" for a watchlist whose dates the
    import never captured.
    """

    if not waits:
        return None
    return _whole_days(median(waits))


def _genre_skew(candidates: Sequence[_Candidate]) -> List[Dict[str, Any]]:
    """The genres piling up unwatched, over every candidate that is enriched.

    Counted across the whole unwatched watchlist rather than the recommended
    slice, because the question is what the member keeps postponing, not what
    the group happens to have rated.
    """

    counts: Counter[str] = Counter()
    labels: Dict[str, str] = {}
    for candidate in candidates:
        for genre in candidate.genres:
            key = genre.casefold()
            labels.setdefault(key, genre)
            counts[key] += 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], labels[item[0]].casefold()))
    return [
        {"label": labels[key], "count": count}
        for key, count in ordered[:MAX_SECONDARY_ENTRIES]
    ]


def _recommendation(
    candidate: _Candidate,
    identity: Dict[str, Any],
    today: date,
) -> Dict[str, Any]:
    opinions = candidate.opinions
    return {
        **identity,
        "group_average": _round(opinions.group_average, 2),
        "group_raters": len(opinions.raters),
        "liked_by": opinions.liked_by,
        "letterboxd_average": _round(candidate.letterboxd_average, 2),
        # The shape behind that average: what share of the crowd called it a
        # favourite, and what share wrote it off.
        "crowd_ceiling": candidate.crowd_ceiling,
        "crowd_floor": candidate.crowd_floor,
        "added_date": candidate.added_date.isoformat() if candidate.added_date else None,
        "days_waiting": candidate.days_waiting(today),
        "raters": [
            {"username": rater.username, "rating": _round(rater.rating, 2)}
            for rater in opinions.raters[:MAX_RATERS_LISTED]
        ],
    }


def _waiting_entry(
    candidate: _Candidate,
    identity: Dict[str, Any],
    today: date,
) -> Dict[str, Any]:
    return {
        **identity,
        "added_date": candidate.added_date.isoformat() if candidate.added_date else None,
        "days_waiting": candidate.days_waiting(today),
    }


def _clamp_limit(limit: Optional[int]) -> int:
    try:
        value = int(limit) if limit is not None else DEFAULT_LIMIT
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(value, MAX_LIMIT))


def build_watchlist_insights(
    db: Session,
    profile: Profile,
    *,
    limit: int = DEFAULT_LIMIT,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Rank one profile's unwatched watchlist by what its circle scored.

    ``recommendations`` is ordered by ``group_average`` and then by how many
    other members are behind that average, so a 4.5 from four people outranks a
    4.5 from one. Every film in it has at least one other rater and no
    ``profile_films`` row for this profile; ``group_average``, ``group_raters``
    and ``liked_by`` are computed over *other* profiles only.

    ``coverage`` qualifies all of it. ``watchlist_films`` is the size of the
    unwatched candidate pool -- the denominator for everything else here, and
    smaller than the raw watchlist wherever a film was watched after being
    added. ``rated_by_group`` is how many of those the circle can speak to at
    all, and ``with_letterboxd_average`` how many carry the external crowd
    number. A client showing a partial queue can say so from these three.

    ``longest_waiting`` and the wait totals read only rows carrying an
    ``added_date``; an undated row has an unknown wait and is omitted rather
    than counted as new.
    """

    limit = _clamp_limit(limit)
    today = today or date.today()
    candidates = _candidates(db, profile.id)

    recommendable = [
        candidate for candidate in candidates if candidate.opinions.is_recommendable
    ]
    # Rank on a confidence-weighted score, not the raw average. A single 5.0
    # is weaker evidence than five people at 4.6, and sorting on the mean puts
    # the lone opinion on top: across the tracked set, most of what surfaced
    # that way rested on one rater. Shrinking each film's average toward the
    # pool mean in proportion to how few people rated it keeps the ordering
    # honest without discarding thinly-rated films entirely. group_average and
    # group_raters are still reported verbatim, so the panel can show the real
    # figures and badge a thin verdict.
    prior = _group_baseline_rating(db, profile.id)

    def confidence_weighted(candidate) -> float:
        average = candidate.opinions.group_average
        if average is None:
            return 0.0
        raters = len(candidate.opinions.raters)
        # k is the number of notional prior raters; at k=2 a single rating is
        # pulled a third of the way back toward the pool, five barely move.
        weight = raters / (raters + SHRINKAGE_PRIOR_RATERS)
        return weight * average + (1 - weight) * prior

    ranked = sorted(
        recommendable,
        key=lambda candidate: (
            -confidence_weighted(candidate),
            -len(candidate.opinions.raters),
            candidate.title.casefold(),
            candidate.movie_id,
        ),
    )[:limit]

    dated = [
        (candidate, candidate.days_waiting(today))
        for candidate in candidates
        if candidate.added_date is not None
    ]
    longest = sorted(
        dated,
        key=lambda pair: (-pair[1], pair[0].title.casefold(), pair[0].movie_id),
    )[:MAX_SECONDARY_ENTRIES]
    waits = [days for _, days in dated]

    identities = _film_identities(
        db,
        [candidate.movie_id for candidate in (*ranked, *(pair[0] for pair in longest))],
    )

    def identity(candidate: _Candidate) -> Dict[str, Any]:
        return identities.get(
            candidate.movie_id,
            {
                "title": candidate.title,
                "year": None,
                "poster_url": None,
                "letterboxd_url": None,
            },
        )

    return {
        "username": profile.username,
        "coverage": {
            "watchlist_films": len(candidates),
            "rated_by_group": len(recommendable),
            "with_letterboxd_average": sum(
                1 for candidate in candidates if candidate.letterboxd_average is not None
            ),
        },
        "recommendations": [
            _recommendation(candidate, identity(candidate), today) for candidate in ranked
        ],
        "longest_waiting": [
            _waiting_entry(candidate, identity(candidate), today)
            for candidate, _ in longest
        ],
        "genre_skew": _genre_skew(candidates),
        "totals": {
            "median_days_waiting": median_days_waiting(waits),
            "oldest_days_waiting": max(waits) if waits else None,
        },
    }
