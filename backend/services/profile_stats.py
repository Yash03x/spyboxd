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

The ``rewatches`` and ``reviews`` blocks read rows nothing else analysed:
``profile_films.rewatch_count`` and the ``reviews`` table. Both offer a pair
of averages -- rewatched against watched-once, reviewed against unreviewed --
and both pairs are averages over two disjoint, self-selected sets of one
profile's films. Neither is a paired test, and neither says that rewatching or
reviewing changes a rating.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from database.models import Movie, MovieEnrichment, Profile, ProfileFilm, Review, WatchEvent
from services.insights import _as_string_list, _average, _round, _safe_float


# Every list surface is a "top" list, not an export: a stats page that renders
# 800 directors is a database dump, not a summary.
MAX_LIST_ENTRIES = 10

# The most-liked reviews are a shortlist next to the counts, not a leaderboard.
MAX_LIKED_REVIEWS = 5

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

    movie_id: int
    title: str
    poster_url: Optional[str]
    letterboxd_url: Optional[str]
    rating: Optional[float]
    watch_count: int
    rewatch_count: int
    release_year: Optional[int]
    enriched: bool
    runtime_minutes: Optional[int]
    genres: List[_Value]
    countries: List[_Value]
    languages: List[_Value]
    directors: List[_Value]
    director_genders: List[int]
    composers: List[_Value]
    cinematographers: List[_Value]
    editors: List[_Value]
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


# Crew whose work shapes a film as much as the director's, and whose credits
# TMDB stores on ~4,000 of the enriched films while nothing reads them.
BELOW_THE_LINE_JOBS = {
    "composer": "Original Music Composer",
    "cinematographer": "Director of Photography",
    "editor": "Editor",
}


def _crew_values(credits: Any, job: str) -> List[_Value]:
    """Names credited with one specific crew job."""

    crew = credits.get("crew") if isinstance(credits, Mapping) else None
    if not isinstance(crew, list):
        return []
    return _plain_values(
        _as_string_list(
            [
                member
                for member in crew
                if isinstance(member, Mapping) and member.get("job") == job
            ]
        )
    )


def _director_genders(credits: Any) -> List[int]:
    """TMDB gender codes for this film's directors.

    1 is female and 2 is male; 0 and null mean TMDB has not recorded one, and
    those are dropped rather than counted as a third category. Coverage is 93%
    of director credits across the enriched library.
    """

    crew = credits.get("crew") if isinstance(credits, Mapping) else None
    if not isinstance(crew, list):
        return []
    genders = []
    for member in crew:
        if not isinstance(member, Mapping) or member.get("job") != "Director":
            continue
        try:
            code = int(member.get("gender") or 0)
        except (TypeError, ValueError):
            continue
        if code in (1, 2):
            genders.append(code)
    return genders


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
            ProfileFilm.watch_count,
            ProfileFilm.rewatch_count,
            Movie.id.label("movie_id"),
            Movie.title,
            Movie.poster_url,
            Movie.letterboxd_url,
            Movie.release_year,
            MovieEnrichment.movie_id.label("enrichment_movie_id"),
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
        enriched = row.enrichment_movie_id is not None
        release_year = row.release_year
        if not release_year and row.release_date is not None:
            release_year = row.release_date.year
        credits = row.credits if isinstance(row.credits, Mapping) else {}
        films.append(
            _FilmRow(
                movie_id=int(row.movie_id),
                title=row.title,
                poster_url=row.poster_url,
                letterboxd_url=row.letterboxd_url,
                rating=_safe_float(row.rating),
                watch_count=int(row.watch_count or 0),
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
                director_genders=_director_genders(credits),
                composers=_crew_values(credits, BELOW_THE_LINE_JOBS["composer"]),
                cinematographers=_crew_values(
                    credits, BELOW_THE_LINE_JOBS["cinematographer"]
                ),
                editors=_crew_values(credits, BELOW_THE_LINE_JOBS["editor"]),
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
    # `count` is every film in the bucket; the average is over the rated ones
    # only. Presenting them together read as "4.6 average across 12 films" when
    # the average came from three, so the rated count travels with it.
    entry["rated_count"] = len(bucket["ratings"])
    entry["average_rating"] = _round(_average(bucket["ratings"]), 2)
    return entry


def _by_count(bucket: Mapping[str, Any]):
    return (-bucket["count"], bucket["label"].casefold(), bucket["label"])


def _director_gender_split(films: Sequence[_FilmRow]) -> Dict[str, Any]:
    """Share of watched films directed by women, men, and by both.

    Counted per film rather than per credit, so a two-director film is one
    film. TMDB records no gender for 7% of director credits; a film whose
    directors are all unrecorded is left out of the shares entirely rather than
    being assigned to either side, and the count that was measured is reported
    so the reader can weigh it.
    """

    women = 0
    men = 0
    mixed = 0
    measured = 0
    for film in films:
        genders = set(film.director_genders)
        if not genders:
            continue
        measured += 1
        if genders == {1}:
            women += 1
        elif genders == {2}:
            men += 1
        else:
            mixed += 1
    if measured == 0:
        return {"measured_films": 0, "women": 0, "men": 0, "mixed": 0, "women_share": None}
    return {
        "measured_films": measured,
        "women": women,
        "men": men,
        "mixed": mixed,
        "women_share": _round((women + mixed) / measured, 3),
    }


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


# --- rewatches --------------------------------------------------------------


def _median(values: Sequence[int]) -> Optional[int]:
    """Middle value, so one very old revisit cannot drag the typical one."""

    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return int(round((ordered[middle - 1] + ordered[middle]) / 2))


def build_return_journeys(
    events: Sequence[Tuple[int, date, Optional[float]]]
) -> Dict[str, Any]:
    """How long before somebody goes back to a film, and whether the score moves.

    ``events`` is (movie_id, watched_date, rating). Unlike the two averages
    below this IS a paired measurement: the same person rating the same film on
    two separate viewings, so the difference is the effect of the revisit rather
    than a difference between two sets of films.

    Only films whose viewings fall on different dates count. A rewatch logged on
    the same day as the first viewing carries no interval and says nothing about
    returning to something later.
    """

    by_movie: Dict[int, List[Tuple[date, Optional[float]]]] = defaultdict(list)
    for movie_id, watched, rating in events:
        if watched is not None:
            by_movie[movie_id].append((watched, rating))

    gaps: List[int] = []
    rose = 0
    fell = 0
    held = 0
    deltas: List[float] = []
    for viewings in by_movie.values():
        if len(viewings) < 2:
            continue
        viewings.sort(key=lambda item: item[0])
        first_date, _ = viewings[0]
        last_date, _ = viewings[-1]
        if last_date <= first_date:
            continue
        gaps.append((last_date - first_date).days)

        rated = [(day, rating) for day, rating in viewings if rating is not None]
        if len(rated) < 2:
            continue
        first_rating = rated[0][1]
        last_rating = rated[-1][1]
        delta = round(last_rating - first_rating, 2)
        deltas.append(delta)
        if delta > 0:
            rose += 1
        elif delta < 0:
            fell += 1
        else:
            held += 1

    return {
        "revisited_films": len(gaps),
        "median_days_to_return": _median(gaps) if gaps else None,
        # The paired half: only films this profile rated on two separate
        # viewings, which is a far smaller set than the one above.
        "rated_twice": len(deltas),
        "rating_rose": rose,
        "rating_fell": fell,
        "rating_held": held,
        "average_change": _round(_average(deltas), 2) if deltas else None,
    }


def _return_events(db: Session, profile_id: int) -> List[Tuple[int, date, Optional[float]]]:
    """(movie_id, watched_date, rating) for every active dated watch event."""

    return [
        (int(movie_id), watched, float(rating) if rating is not None else None)
        for movie_id, watched, rating in db.query(
            WatchEvent.movie_id, WatchEvent.watched_date, WatchEvent.rating
        )
        .filter(
            WatchEvent.profile_id == profile_id,
            WatchEvent.superseded_at.is_(None),
            WatchEvent.watched_date.isnot(None),
        )
        .all()
    ]


def _rewatch_block(films: Sequence[_FilmRow]) -> Dict[str, Any]:
    """What a profile returns to, and how it rates the films it returns to.

    ``average_rating_rewatched`` and ``average_rating_once`` are two ordinary
    averages over two disjoint halves of the same profile's library -- the
    films carrying at least one rewatch, and the films seen exactly once. They
    are not a paired measurement: they compare two self-selected sets of films
    and each side ignores the films that profile never rated, so a gap between
    them describes which films get revisited, not what revisiting does to a
    rating. ``return_journeys`` answers that question properly, from the
    per-viewing ratings on watch events -- the same person, the same film,
    twice.

    ``most_rewatched`` ranks by ``watch_count`` because that is the figure it
    reports, and lists only films with a rewatch -- a film seen once is not a
    quiet entry at the bottom of a rewatch list. Deeper rewatches break ties,
    because equal watch counts do not mean equal returning.

    A ``watch_count`` of 1 next to a rewatch is real: Letterboxd lets a diary
    entry be flagged as a rewatch when the original viewing was never logged,
    and 166 rows in the current database look exactly like that. The count
    stays as the column holds it rather than being nudged up to two, which
    would be inventing a viewing nobody recorded.
    """

    rewatched = [film for film in films if film.rewatch_count > 0]
    watched_once = [film for film in films if film.rewatch_count == 0]
    ranked = sorted(
        rewatched,
        key=lambda film: (
            -film.watch_count,
            -film.rewatch_count,
            film.title.casefold(),
            film.title,
        ),
    )[:MAX_LIST_ENTRIES]

    return {
        "total_rewatches": sum(film.rewatch_count for film in films),
        "films_rewatched": len(rewatched),
        # An empty library has no rewatch rate; it does not have a rate of zero.
        "rewatch_rate": _round(len(rewatched) / len(films), 4) if films else None,
        "most_rewatched": [
            {
                "title": film.title,
                "year": film.release_year,
                "poster_url": film.poster_url,
                "letterboxd_url": film.letterboxd_url,
                "watch_count": film.watch_count,
                "rating": _round(film.rating, 2),
            }
            for film in ranked
        ],
        "average_rating_rewatched": _round(
            _average([film.rating for film in rewatched]), 2
        ),
        "average_rating_once": _round(
            _average([film.rating for film in watched_once]), 2
        ),
    }


# --- reviews ----------------------------------------------------------------


@dataclass(frozen=True)
class _ReviewRow:
    """One active review, resolved to a display title where a film matched."""

    movie_id: Optional[int]
    title: str
    year: Optional[int]
    length_chars: Optional[int]
    contains_spoilers: bool
    likes_count: int
    published_date: Optional[date]


def _review_rows(db: Session, profile_id: int) -> List[_ReviewRow]:
    """Bulk-load one profile's active reviews in a single query.

    A review row carries its own ``movie_title``/``movie_year`` because a
    review can exist without ever resolving to a film in ``movies``, so the
    canonical row wins where the match exists and the review's own copy is the
    fallback. Review text is short enough to read in full -- unlike the TMDB
    payloads above -- so lengths are measured in Python, where stripping
    trailing whitespace means the same thing it does everywhere else.
    """

    rows = (
        db.query(
            Review.movie_id,
            Review.movie_title,
            Review.movie_year,
            Review.review_text,
            Review.contains_spoilers,
            Review.likes_count,
            Review.published_date,
            Movie.title.label("canonical_title"),
            Movie.release_year.label("canonical_year"),
        )
        .outerjoin(Movie, Movie.id == Review.movie_id)
        .filter(
            Review.profile_id == profile_id,
            Review.removed_at.is_(None),
        )
        .all()
    )

    reviews: List[_ReviewRow] = []
    for row in rows:
        text = (row.review_text or "").strip()
        year = row.canonical_year if row.canonical_year is not None else row.movie_year
        reviews.append(
            _ReviewRow(
                movie_id=int(row.movie_id) if row.movie_id is not None else None,
                title=(row.canonical_title or row.movie_title or "").strip(),
                year=int(year) if year else None,
                # A rating logged without prose has no length, not a length of 0.
                length_chars=len(text) if text else None,
                contains_spoilers=bool(row.contains_spoilers),
                likes_count=int(row.likes_count or 0),
                published_date=row.published_date,
            )
        )
    return reviews


def median_length_chars(lengths: Sequence[int]) -> Optional[int]:
    """The middle review length, in whole characters.

    An even-sized sample has no single middle review, so the two middle
    lengths are averaged and floored: the answer is a character count, and a
    half-character would be a fiction of the arithmetic.
    """

    if not lengths:
        return None
    ordered = sorted(lengths)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


def _review_block(
    reviews: Sequence[_ReviewRow],
    films: Sequence[_FilmRow],
) -> Dict[str, Any]:
    """Writing habits, and how a profile rates the films it writes about.

    ``average_rating_reviewed`` and ``average_rating_unreviewed`` both read
    ``profile_films.rating`` -- the profile's own rating of the film, not the
    rating attached to the review -- so the two sides are the same scale over
    the same library, split by whether a review resolved to that film. Reviews
    that never matched a film cannot place one on either side and are counted
    only in the totals. As with rewatches, these are two averages over two
    self-selected sets, not a before-and-after.

    ``reviews_by_year`` counts only reviews carrying a publication date; a
    review with no date belongs to no year and is left out of the series
    rather than being assigned to one.
    """

    written = [review for review in reviews if review.length_chars is not None]
    longest = min(
        written,
        key=lambda review: (-(review.length_chars or 0), review.title.casefold()),
        default=None,
    )
    # A review nobody liked is not one of the most-liked reviews.
    ranked = sorted(
        (review for review in reviews if review.likes_count > 0),
        key=lambda review: (
            -review.likes_count,
            -(review.published_date.toordinal() if review.published_date else 0),
            review.title.casefold(),
        ),
    )[:MAX_LIKED_REVIEWS]
    per_year = Counter(
        review.published_date.year
        for review in reviews
        if review.published_date is not None
    )

    reviewed_movie_ids = {
        review.movie_id for review in reviews if review.movie_id is not None
    }
    reviewed = [film.rating for film in films if film.movie_id in reviewed_movie_ids]
    unreviewed = [
        film.rating for film in films if film.movie_id not in reviewed_movie_ids
    ]

    return {
        "total_reviews": len(reviews),
        "with_text": len(written),
        "spoiler_reviews": sum(1 for review in reviews if review.contains_spoilers),
        "median_length_chars": median_length_chars(
            [review.length_chars for review in written if review.length_chars is not None]
        ),
        "longest": (
            {
                "title": longest.title,
                "year": longest.year,
                "length_chars": longest.length_chars,
            }
            if longest is not None
            else None
        ),
        "most_liked": [
            {
                "title": review.title,
                "year": review.year,
                "likes_count": review.likes_count,
                "published_date": (
                    review.published_date.isoformat()
                    if review.published_date is not None
                    else None
                ),
            }
            for review in ranked
        ],
        "reviews_by_year": [
            {"year": year, "count": per_year[year]} for year in sorted(per_year)
        ],
        "average_rating_reviewed": _round(_average(reviewed), 2),
        "average_rating_unreviewed": _round(_average(unreviewed), 2),
    }


def build_profile_stats(db: Session, profile: Profile) -> Dict[str, Any]:
    """Recompute the Letterboxd stats page for one profile from local rows.

    ``letterboxd_reported`` carries the scraped Patron figures verbatim where
    they exist so a client can show ours against theirs. It is a cross-check,
    never the source: the two will differ because Letterboxd counts its own
    runtime data over a member's whole library while we count TMDB runtimes
    over the films we managed to match.

    ``rewatches`` and ``reviews`` are always present, even for a profile that
    has neither: their counts fall to zero and every average, median and
    headline film falls to null, so a client renders "none yet" rather than
    guessing whether the block failed to compute.
    """

    films = _film_rows(db, profile.id)
    watch_dates = _dated_watch_dates(db, profile.id)
    reviews = _review_rows(db, profile.id)

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
    composers = _collect(films, lambda film: film.composers)
    cinematographers = _collect(films, lambda film: film.cinematographers)
    editors = _collect(films, lambda film: film.editors)
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
            # How many reviews could be placed against a film in the library at
            # all: the ratings comparison in ``reviews`` is blind to the rest.
            "reviews_total": len(reviews),
            "reviews_matched_to_films": sum(
                1 for review in reviews if review.movie_id is not None
            ),
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
        # The people whose work shapes a film without their name being the one
        # anybody counts. Their credits were already stored and never read.
        "top_composers": _ranked(composers, label_key="name"),
        "top_cinematographers": _ranked(cinematographers, label_key="name"),
        "top_editors": _ranked(editors, label_key="name"),
        "director_gender": _director_gender_split(films),
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
        "rewatches": _rewatch_block(films),
        # A genuine paired measurement, unlike the two averages inside
        # ``rewatches``: the same person, the same film, two viewings.
        "return_journeys": build_return_journeys(_return_events(db, profile.id)),
        "reviews": _review_block(reviews, films),
        "letterboxd_reported": profile.stats_snapshot,
    }
