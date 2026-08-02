"""How mainstream one profile's taste is, measured in audience size.

``movies.letterboxd_rating_count`` across this library runs from 205 to
6,110,855 -- a 30,000x spread. That range is what makes "how mainstream is this
person's taste" an answerable question rather than a vibe, and Letterboxd never
puts it on screen: it shows a film's rating count on the film's own page and
never aggregates those counts over a member's history.

Three deliberate choices hold this module up.

* **The headline is the median, never the mean.** Audience sizes are wildly
  right-skewed. One 6-million-rating blockbuster among five hundred
  two-hundred-rating obscurities drags a mean into six figures and reports a
  mainstream taste that nobody has; the median stays where the person actually
  lives. The mean is reported beside it precisely so the gap between the two is
  visible -- a mean far above the median *is* the blockbuster showing up.
* **A lean is only ever relative.** "Mainstream" is not a property of a number;
  200,000 ratings is obscure next to one crowd and enormous next to another.
  ``lean`` is therefore read off ``percentile_vs_group`` and is null exactly
  when that percentile is null, so the two can never contradict each other. A
  profile with no group to compare against gets a median and no lean, rather
  than a lean invented from a threshold nobody chose.
* **Nothing is extrapolated over missing data.** The crowd-rating backfill has
  not reached every film, and ``letterboxd_rating_distribution`` is unpopulated
  until that backfill re-runs. Films without a known audience size are dropped
  from the median rather than counted as zero, ``coverage`` reports exactly how
  many survived so the UI can qualify a partial figure, and ``crowd_position``
  is an empty list -- not null, not fabricated -- while distributions are
  missing, so the endpoint is useful before the re-backfill lands.

The universe throughout is the profile's *rated* films. A rating is the
evidence that the film was actually engaged with, and it is also the number
``crowd_position`` places against the crowd's curve, so keeping one universe
means the coverage funnel, the headline median and the three film lists all
describe the same set of films.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy.orm import Session, load_only

from database.models import Movie, MovieEnrichment, Profile, ProfileFilm
from services.insights import InsightsService, _round, _safe_float


DEFAULT_LIMIT = 10
MAX_LIMIT = 50

# How far from the middle of the group a profile must sit before its taste is
# named. Inside this band the profile is simply where most people are.
LEAN_PERCENTILE_MARGIN = 15.0

# Half-star ratings are exact multiples of 0.5, but they arrive as floats;
# compare with a tolerance so 3.5 is never excluded from its own bucket.
_RATING_EPSILON = 1e-9


@dataclass(frozen=True)
class _RatedFilm:
    """One film this profile rated, with whatever the crowd data can say."""

    movie_id: int
    title: str
    profile_rating: float
    rating_count: Optional[int]
    crowd_average: Optional[float]
    distribution: Optional[Mapping[str, Any]]

    @property
    def has_audience(self) -> bool:
        return self.rating_count is not None


def _clamp_limit(limit: Optional[int]) -> int:
    try:
        value = int(limit) if limit is not None else DEFAULT_LIMIT
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(value, MAX_LIMIT))


def _audience(value: Any) -> Optional[int]:
    """A film's rating count, where anything non-positive means "not synced".

    The backfill only ever writes a count alongside a published average, so a
    zero here is a placeholder rather than a film nobody rated. Treating it as
    an audience of zero would make every unsynced film the most obscure thing
    the profile has ever seen.
    """

    number = _safe_float(value)
    if number is None or number <= 0:
        return None
    return int(number)


def _crowd_average(value: Any) -> Optional[float]:
    average = _safe_float(value)
    return average if average is not None and average > 0 else None


def _whole(value: Optional[float]) -> Optional[int]:
    """Round an audience size to a whole person, half away from zero."""

    if value is None:
        return None
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def _rated_films(db: Session, profile_id: int) -> List[_RatedFilm]:
    """Bulk-load the profile's rated films and their crowd figures in one query.

    Only the six columns this module reads are selected, so a 1,600-film
    library never drags whole ``Movie`` rows across to reach a rating count.
    """

    rows = (
        db.query(
            ProfileFilm.movie_id,
            ProfileFilm.rating,
            Movie.title,
            Movie.letterboxd_rating_count,
            Movie.letterboxd_average_rating,
            Movie.letterboxd_rating_distribution,
        )
        .join(Movie, Movie.id == ProfileFilm.movie_id)
        .filter(
            ProfileFilm.profile_id == profile_id,
            ProfileFilm.removed_at.is_(None),
            ProfileFilm.rating.isnot(None),
        )
        .all()
    )
    films: List[_RatedFilm] = []
    for row in rows:
        rating = _safe_float(row.rating)
        if rating is None:
            continue
        films.append(
            _RatedFilm(
                movie_id=int(row.movie_id),
                title=row.title or "",
                profile_rating=rating,
                rating_count=_audience(row.letterboxd_rating_count),
                crowd_average=_crowd_average(row.letterboxd_average_rating),
                distribution=row.letterboxd_rating_distribution,
            )
        )
    return films


def _group_medians(db: Session, *, exclude_profile_id: int) -> List[float]:
    """Every *other* tracked profile's median audience size, in one query.

    One pass over every tracked profile's rated films, grouped in memory --
    seventeen profiles must never mean seventeen round trips. Only active,
    completed profiles count, matching the rule the rest of the app uses for a
    usable imported profile, and a profile with no film of known audience size
    contributes no median rather than a zero.
    """

    rows = (
        db.query(ProfileFilm.profile_id, Movie.letterboxd_rating_count)
        .join(Movie, Movie.id == ProfileFilm.movie_id)
        .join(Profile, Profile.id == ProfileFilm.profile_id)
        .filter(
            ProfileFilm.profile_id != exclude_profile_id,
            ProfileFilm.removed_at.is_(None),
            ProfileFilm.rating.isnot(None),
            Movie.letterboxd_rating_count.isnot(None),
            Profile.is_active.is_(True),
            Profile.scraping_status == "completed",
        )
        .all()
    )
    grouped: Dict[int, List[int]] = {}
    for profile_id, rating_count in rows:
        audience = _audience(rating_count)
        if audience is not None:
            grouped.setdefault(int(profile_id), []).append(audience)
    return [median(counts) for counts in grouped.values() if counts]


def _percentile_vs_group(
    subject_median: Optional[float],
    other_medians: Sequence[float],
) -> Optional[float]:
    """Where this profile sits among its peers, as an *obscurity* percentile.

    100 means every other tracked profile watches bigger films; 0 means every
    other one watches smaller. A profile tied with the rest of the group lands
    at 50 rather than 0 or 100, because ties are counted at their midpoint --
    being level with everybody is the middle of the pack, not either end of it.

    Null when there is nobody to compare against. A group of one has no
    percentile, and inventing 50 for it would claim a placement we never made.
    """

    if subject_median is None or not other_medians:
        return None
    greater = sum(1 for value in other_medians if value > subject_median)
    equal = sum(1 for value in other_medians if value == subject_median)
    return 100.0 * (greater + 0.5 * equal) / len(other_medians)


def _lean(percentile: Optional[float]) -> Optional[str]:
    """Name the taste from the reported percentile, so the two always agree."""

    if percentile is None:
        return None
    if percentile > 50.0 + LEAN_PERCENTILE_MARGIN:
        return "obscure"
    if percentile < 50.0 - LEAN_PERCENTILE_MARGIN:
        return "mainstream"
    return "balanced"


def _numeric_buckets(distribution: Any) -> Dict[float, int]:
    """Coerce a stored ``{"0.5": int}`` distribution into numeric buckets.

    Unreadable keys and values are dropped rather than guessed at; a bucket we
    cannot place on the star scale cannot be counted on either side of a
    rating.
    """

    if not isinstance(distribution, Mapping):
        return {}
    buckets: Dict[float, int] = {}
    for raw_key, raw_value in distribution.items():
        star = _safe_float(raw_key)
        size = _safe_float(raw_value)
        if star is None or size is None or size < 0:
            continue
        buckets[star] = buckets.get(star, 0) + int(size)
    return buckets


def _share_at_or_below(distribution: Any, rating: float) -> Optional[float]:
    """The fraction of the crowd that rated this film at or below ``rating``.

    The denominator is the bucket total, not ``letterboxd_rating_count``: this
    is a share *of the histogram*, and dividing one source by another would
    drift whenever the two were captured at different moments.
    """

    buckets = _numeric_buckets(distribution)
    total = sum(buckets.values())
    if total <= 0:
        return None
    at_or_below = sum(
        size for star, size in buckets.items() if star <= rating + _RATING_EPSILON
    )
    return at_or_below / total


def _film_identities(db: Session, movie_ids: Iterable[int]) -> Dict[int, Dict[str, Any]]:
    """Display fields for the handful of films that reached an output list.

    Poster hygiene (TMDB path, placeholder rejection, Letterboxd image
    endpoints) already lives in ``InsightsService._movie_summary``; this reuses
    it rather than growing a second copy of those rules.
    """

    wanted = {int(movie_id) for movie_id in movie_ids}
    if not wanted:
        return {}
    rows = (
        db.query(Movie, MovieEnrichment)
        .outerjoin(MovieEnrichment, MovieEnrichment.movie_id == Movie.id)
        .options(load_only(MovieEnrichment.movie_id, MovieEnrichment.poster_path))
        .filter(Movie.id.in_(wanted))
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


def _audience_entry(film: _RatedFilm, identity: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **identity,
        "rating_count": film.rating_count,
        "profile_rating": _round(film.profile_rating, 2),
    }


def _crowd_entry(
    film: _RatedFilm,
    share: float,
    identity: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        **identity,
        "profile_rating": _round(film.profile_rating, 2),
        "share_at_or_below": round(share, 4),
        "crowd_average": _round(film.crowd_average, 2),
    }


def build_obscurity_index(
    db: Session,
    profile: Profile,
    *,
    limit: int = DEFAULT_LIMIT,
) -> Dict[str, Any]:
    """Measure how mainstream one profile's rated films are.

    ``index.median_rating_count`` is the headline: the audience size of the
    typical film this person rated. ``percentile_vs_group`` places that median
    among every other tracked profile's median, and ``lean`` names it.

    ``most_obscure`` and ``most_mainstream`` are the two ends of the same
    ordering. ``crowd_position`` is a different question -- not how big the
    crowd was, but where inside it this rating fell -- and it stays empty until
    ``letterboxd_rating_distribution`` is populated.
    """

    limit = _clamp_limit(limit)
    films = _rated_films(db, profile.id)
    with_audience = [film for film in films if film.has_audience]

    audiences = [float(film.rating_count) for film in with_audience]
    subject_median = median(audiences) if audiences else None
    subject_mean = (sum(audiences) / len(audiences)) if audiences else None

    percentile = _percentile_vs_group(
        subject_median,
        _group_medians(db, exclude_profile_id=profile.id),
    )

    ordered_by_audience = sorted(
        with_audience,
        key=lambda film: (film.rating_count, film.title.casefold(), film.movie_id),
    )
    most_obscure = ordered_by_audience[:limit]
    # The mainstream end of the same ordering, reversed so the biggest crowd
    # leads. Slicing the tail first would silently return fewer than ``limit``
    # films whenever the library is smaller than twice the limit.
    most_mainstream = sorted(
        with_audience,
        key=lambda film: (-film.rating_count, film.title.casefold(), film.movie_id),
    )[:limit]

    positioned: List[Tuple[_RatedFilm, float]] = []
    for film in films:
        share = _share_at_or_below(film.distribution, film.profile_rating)
        if share is not None:
            positioned.append((film, share))
    # Most contrarian first: the smallest share is the film this profile rated
    # above almost the entire crowd. Ties break towards the larger crowd, where
    # standing apart took more disagreeing with.
    positioned.sort(
        key=lambda pair: (
            pair[1],
            -(pair[0].rating_count or 0),
            pair[0].title.casefold(),
            pair[0].movie_id,
        )
    )
    crowd_position = positioned[:limit]
    # The other end of the same ordering: films this profile rated below almost
    # everyone. Showing only the contrarian tail told half the story -- somebody
    # can be out on a limb in both directions at once.
    crowd_position_below = list(reversed(positioned))[:limit]

    # And the whole distribution behind those tails. The median share says where
    # this profile usually sits inside the crowds it joins: above 0.5 means it
    # typically rates a film higher than most of the people who rated it.
    all_shares = [share for _, share in positioned]
    typical_share = median(all_shares) if all_shares else None

    identities = _film_identities(
        db,
        [
            film.movie_id
            for film in (
                *most_obscure,
                *most_mainstream,
                *(pair[0] for pair in crowd_position),
            )
        ],
    )

    def identity(film: _RatedFilm) -> Dict[str, Any]:
        return identities.get(
            film.movie_id,
            {
                "title": film.title,
                "year": None,
                "poster_url": None,
                "letterboxd_url": None,
            },
        )

    return {
        "username": profile.username,
        "coverage": {
            "rated_films": len(films),
            "films_with_rating_count": len(with_audience),
        },
        "index": {
            "median_rating_count": _whole(subject_median),
            "mean_rating_count": _whole(subject_mean),
            "percentile_vs_group": _round(percentile, 1),
            "lean": _lean(percentile),
        },
        "most_obscure": [_audience_entry(film, identity(film)) for film in most_obscure],
        "most_mainstream": [
            _audience_entry(film, identity(film)) for film in most_mainstream
        ],
        "crowd_position": [
            _crowd_entry(film, share, identity(film)) for film, share in crowd_position
        ],
        "crowd_position_below": [
            _crowd_entry(film, share, identity(film))
            for film, share in crowd_position_below
        ],
        # Where this profile usually lands inside a crowd, across everything it
        # rated that carries a histogram. Null when no film does -- "we never
        # measured" rather than "exactly average".
        "crowd_percentile": {
            "measured_films": len(all_shares),
            "typical_share": _round(typical_share, 3) if typical_share is not None else None,
            "lean": (
                None
                if typical_share is None
                else "generous" if typical_share > 0.55
                else "harsh" if typical_share < 0.45
                else "typical"
            ),
        },
    }
