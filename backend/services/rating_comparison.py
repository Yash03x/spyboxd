"""How one profile rates against the circle it actually shares films with.

Letterboxd shows a member their own rating beside its site-wide average and
nothing else. We hold every tracked profile's rating for the same films, so a
film can also carry a *local* average -- what this member's own circle thought
of it -- and that is the comparison Letterboxd structurally cannot make. The
same film therefore gets two reference points: the group, and Letterboxd's own
crowd.

Two rules keep the local comparison honest.

* **The group average for a film always excludes the profile being measured.**
  Leaving a member inside the crowd they are measured against drags that crowd
  toward them, shrinks every delta, and correlates a profile with itself: a
  member who rated everything five stars while everyone else rated three would
  still look partly agreeable purely because their own fives sit in the
  average. Every ``group_average`` in this payload is the mean over *other*
  profiles only.
* **A film needs at least two other raters before it is compared at all.** One
  other person is an opinion, not a group, and half the difference between two
  people is not a lean.

``most_divisive`` answers a different question and so uses a different rule:
its spread is measured across *every* profile who rated the film, this one
included, because a film everyone scores 4.5 except one holdout is not the same
object as a film split down the middle. That needs three raters to mean
anything, so the floor there is three in total rather than two others.

The Letterboxd average is the only external reference here, and it is never
required. ``movies.letterboxd_average_rating`` is backfilled separately and is
null for any film that backfill has not reached, so the ``letterboxd_*`` fields
simply report null for it and the rest of the payload is unaffected. It is
already on Letterboxd's own five-point scale -- the same scale as every rating
in this module -- so nothing is converted between the two numbers being
subtracted.

Nothing here extrapolates: a profile that shares no film with anybody returns a
complete payload of nulls and empty lists rather than zeros.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased, load_only

from database.models import Movie, MovieEnrichment, Profile, ProfileFilm
from services.insights import InsightsService, _average, _pearson, _round, _safe_float


# One other person is an opinion, not a group.
MIN_OTHER_RATERS = 2

# A spread needs a crowd: two raters describe a gap, three describe a split.
MIN_SPREAD_RATERS = 3

# Two paired points always correlate perfectly; a correlation needs three.
MIN_CORRELATION_FILMS = 3

# Below this the mean delta is rating noise (a single half-star on a handful of
# films), not a temperament.
LEAN_THRESHOLD = 0.15

DEFAULT_LIMIT = 10
MAX_LIMIT = 50


@dataclass(frozen=True)
class _FilmRow:
    """One film in the profile's library with every rating we can compare it to."""

    movie_id: int
    title: str
    profile_rating: Optional[float]
    letterboxd_average: Optional[float]
    # How settled the wider crowd is about this film, from its ten-bucket
    # histogram: the share sitting in the single most popular bucket. A high
    # value means Letterboxd has largely made up its mind.
    crowd_consensus: Optional[float]
    other_ratings: Tuple[float, ...]

    @property
    def group_average(self) -> Optional[float]:
        """The mean over other profiles only -- never including this one."""

        return _average(self.other_ratings)

    @property
    def is_compared(self) -> bool:
        return (
            self.profile_rating is not None
            and len(self.other_ratings) >= MIN_OTHER_RATERS
        )

    @property
    def delta(self) -> Optional[float]:
        group_average = self.group_average
        if not self.is_compared or group_average is None:
            return None
        return self.profile_rating - group_average

    @property
    def all_ratings(self) -> Tuple[float, ...]:
        """Every rating on the film, this profile's included."""

        if self.profile_rating is None:
            return self.other_ratings
        return (*self.other_ratings, self.profile_rating)


def _clamp_limit(limit: Optional[int]) -> int:
    try:
        value = int(limit) if limit is not None else DEFAULT_LIMIT
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(value, MAX_LIMIT))


def _crowd_consensus(distribution: Any) -> Optional[float]:
    """Share of the crowd in the film's most popular half-star bucket.

    A film everyone scores 4 sits near 1.0; one the world argues about spreads
    across the buckets and sits low. Null when no histogram has been imported,
    which is not the same as no consensus.
    """

    if not isinstance(distribution, dict) or not distribution:
        return None
    counts = []
    for value in distribution.values():
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count >= 0:
            counts.append(count)
    total = sum(counts)
    if total <= 0:
        return None
    return round(max(counts) / total, 4)


def _letterboxd_average(value: Any) -> Optional[float]:
    """The Letterboxd crowd average, or null while the backfill is pending."""

    average = _safe_float(value)
    return average if average is not None and average > 0 else None


def _other_ratings_by_movie(db: Session, profile_id: int) -> Dict[int, List[float]]:
    """Every *other* tracked profile's rating for the films in this library.

    Restricted to the films this profile actually holds by subquery, so a large
    shared movie table never leaves the database. Only active, completed
    profiles count towards the group, matching the rule the rest of the app
    uses for a usable imported profile.
    """

    library = aliased(ProfileFilm)
    library_movie_ids = select(library.movie_id).where(
        library.profile_id == profile_id,
        library.removed_at.is_(None),
    )
    rows = (
        db.query(ProfileFilm.movie_id, ProfileFilm.rating)
        .join(Profile, Profile.id == ProfileFilm.profile_id)
        .filter(
            ProfileFilm.profile_id != profile_id,
            ProfileFilm.removed_at.is_(None),
            ProfileFilm.rating.isnot(None),
            Profile.is_active.is_(True),
            Profile.scraping_status == "completed",
            ProfileFilm.movie_id.in_(library_movie_ids),
        )
        .all()
    )
    grouped: Dict[int, List[float]] = {}
    for movie_id, rating in rows:
        value = _safe_float(rating)
        if value is not None:
            grouped.setdefault(int(movie_id), []).append(value)
    return grouped


def _library_rows(db: Session, profile_id: int) -> List[_FilmRow]:
    """Bulk-load the profile's library, its own ratings, and the site average.

    Only the columns this comparison reads are selected, so a large library
    never drags whole ``Movie`` rows into memory to reach four numbers.
    """

    rows = (
        db.query(
            ProfileFilm.movie_id,
            ProfileFilm.rating,
            Movie.title,
            Movie.letterboxd_average_rating,
            Movie.letterboxd_rating_distribution,
        )
        .join(Movie, Movie.id == ProfileFilm.movie_id)
        .filter(
            ProfileFilm.profile_id == profile_id,
            ProfileFilm.removed_at.is_(None),
        )
        .all()
    )
    others = _other_ratings_by_movie(db, profile_id)
    return [
        _FilmRow(
            movie_id=int(row.movie_id),
            title=row.title or "",
            profile_rating=_safe_float(row.rating),
            letterboxd_average=_letterboxd_average(row.letterboxd_average_rating),
            crowd_consensus=_crowd_consensus(row.letterboxd_rating_distribution),
            other_ratings=tuple(others.get(int(row.movie_id), ())),
        )
        for row in rows
    ]


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


def _lean(group_delta: Optional[float]) -> Optional[str]:
    """Name the temperament from the reported delta, so the two always agree."""

    if group_delta is None:
        return None
    if group_delta > LEAN_THRESHOLD:
        return "generous"
    if group_delta < -LEAN_THRESHOLD:
        return "harsh"
    return "aligned"


def _agreement(compared: Sequence[_FilmRow]) -> Optional[float]:
    """Pearson correlation of this profile's ratings against the group's.

    Both sequences are paired per film, and the group side excludes this
    profile, so a member cannot correlate with themselves. Two points always
    correlate perfectly, so three paired films is the floor; a group that rated
    every shared film identically has no variance to correlate against and
    returns null rather than a fabricated 1.0.
    """

    if len(compared) < MIN_CORRELATION_FILMS:
        return None
    profile_ratings = [row.profile_rating for row in compared]
    group_averages = [row.group_average for row in compared]
    return _pearson(profile_ratings, group_averages)


def _film_delta(row: _FilmRow, identity: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **identity,
        "profile_rating": _round(row.profile_rating, 2),
        "group_average": _round(row.group_average, 2),
        "delta": _round(row.delta, 2),
        # The size of the group behind ``group_average``: other raters only,
        # which is the number ``coverage.min_raters`` is a floor on.
        "rater_count": len(row.other_ratings),
        "letterboxd_average": _round(row.letterboxd_average, 2),
    }


def _divisive_entry(row: _FilmRow, identity: Dict[str, Any]) -> Dict[str, Any]:
    ratings = row.all_ratings
    return {
        **identity,
        "rating_spread": _round(max(ratings) - min(ratings), 2),
        # The spread is measured across everyone who rated the film, the group
        # average deliberately excludes the profile being viewed. Reporting one
        # count for both presented a four-person average as a five-person one,
        # so each figure now carries its own denominator.
        "rater_count": len(ratings),
        "group_rater_count": len(row.other_ratings),
        # The point of the pairing: a film this circle splits over that the
        # wider crowd has already settled is an argument that belongs to this
        # group rather than to the film.
        "crowd_consensus": row.crowd_consensus,
        "group_average": _round(row.group_average, 2),
        "profile_rating": _round(row.profile_rating, 2),
    }


def _ordered(rows: Iterable[_FilmRow], *, key) -> List[_FilmRow]:
    return sorted(rows, key=key)


def build_rating_comparison(
    db: Session,
    profile: Profile,
    *,
    limit: int = DEFAULT_LIMIT,
) -> Dict[str, Any]:
    """Compare one profile's ratings with its circle and with Letterboxd.

    ``summary.group_delta`` is the mean of ``profile rating - group average``
    over every compared film, where each group average is taken over the other
    profiles who rated that film and never over this one. ``lean`` reads that
    delta against a half-star-noise threshold, and ``agreement`` correlates the
    two rating sequences over the same films.

    ``most_generous`` and ``most_harsh`` only ever contain films whose delta
    actually points that way: a uniformly harsh profile has no generous films,
    and returning its least-harsh ones under that heading would be a lie.
    """

    limit = _clamp_limit(limit)
    rows = _library_rows(db, profile.id)

    rated = [row for row in rows if row.profile_rating is not None]
    compared = [row for row in rows if row.is_compared]

    group_delta = _average([row.delta for row in compared])
    letterboxd_pairs = [
        row.profile_rating - row.letterboxd_average
        for row in rated
        if row.letterboxd_average is not None
    ]

    generous = _ordered(
        (row for row in compared if row.delta > 0),
        key=lambda row: (-row.delta, -len(row.other_ratings), row.title.casefold(), row.movie_id),
    )[:limit]
    harsh = _ordered(
        (row for row in compared if row.delta < 0),
        key=lambda row: (row.delta, -len(row.other_ratings), row.title.casefold(), row.movie_id),
    )[:limit]
    divisive = _ordered(
        (row for row in rows if len(row.all_ratings) >= MIN_SPREAD_RATERS),
        key=lambda row: (
            -(max(row.all_ratings) - min(row.all_ratings)),
            -len(row.all_ratings),
            row.title.casefold(),
            row.movie_id,
        ),
    )[:limit]

    identities = _film_identities(
        db,
        [row.movie_id for row in (*generous, *harsh, *divisive)],
    )

    def identity(row: _FilmRow) -> Dict[str, Any]:
        return identities.get(
            row.movie_id,
            {
                "title": row.title,
                "year": None,
                "poster_url": None,
                "letterboxd_url": None,
            },
        )

    rounded_group_delta = _round(group_delta, 2)
    return {
        "username": profile.username,
        "coverage": {
            "rated_films": len(rated),
            "compared_films": len(compared),
            "min_raters": MIN_OTHER_RATERS,
            "letterboxd_average_films": len(letterboxd_pairs),
        },
        "summary": {
            "group_delta": rounded_group_delta,
            "letterboxd_delta": _round(_average(letterboxd_pairs), 2),
            "lean": _lean(rounded_group_delta),
            "agreement": _round(_agreement(compared), 2),
        },
        "most_generous": [_film_delta(row, identity(row)) for row in generous],
        "most_harsh": [_film_delta(row, identity(row)) for row in harsh],
        "most_divisive": [_divisive_entry(row, identity(row)) for row in divisive],
    }
