"""Opt-in backfill of Letterboxd's own crowd rating for each canonical film.

Never imported by the profile ingestion path. This mirrors the shape of
``services.tmdb_enrichment``: bounded candidate selection with an expiry window,
network work performed outside the read transaction, per-movie savepoints and
batched commits, so a two-hour run can be interrupted and resumed.

The source is Letterboxd's rating-histogram CSI include
(``/csi/film/<slug>/rating-histogram/``), roughly 6KB against the ~300KB film
page. Its ``averagerating`` anchor carries the authoritative phrase::

    Weighted average of 4.50 based on 4,609,944 ratings

The average and the total are read from that phrase alone, and never by summing
the ten half-star buckets in the same document.

Those ten buckets are read too, and stored as the film's rating distribution.
Each bucket row carries its size twice::

    <a class="barcolumn tooltip" title="2,230,960 ★★★★★ ratings (48%)">
      <span class="_sr-only">2.2M (48%)</span>

The exact figure in the ``title`` attribute is preferred; the visible label is
abbreviated and lossy ("2.2M" is 30,960 ratings short of the truth, and the ten
labels together miss that film's real total by 80,202) so it is only expanded
as a fallback if that attribute ever goes away. Either way the bucket sum stays
a *shape*, not a total: ``letterboxd_rating_count`` always comes from the
weighted-average phrase.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import html as html_module
import logging
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from sqlalchemy.orm import Session

from database.models import Movie

try:
    from curl_cffi import requests as curl_requests
except ImportError:  # Kept for a clear local error before dependencies are installed.
    curl_requests = None

try:
    import cloudscraper
except ImportError:  # pragma: no cover - optional fallback only
    cloudscraper = None


logger = logging.getLogger(__name__)


DEFAULT_MAX_AGE_DAYS = 30
DEFAULT_DELAY_SECONDS = 1.5
DEFAULT_MAX_RETRIES = 4
DEFAULT_BACKOFF_SECONDS = 2.0
DEFAULT_BATCH_SIZE = 10
DEFAULT_TIMEOUT_SECONDS = 30
RATING_HISTOGRAM_URL_TEMPLATE = "https://letterboxd.com/csi/film/{slug}/rating-histogram/"

# Letterboxd renders the weighted average only once a film has enough ratings.
_WEIGHTED_AVERAGE_RE = re.compile(
    r"Weighted\s+average\s+of\s+(\d+(?:\.\d+)?)\s+based\s+on\s+([\d,]+)\s+ratings?",
    re.IGNORECASE,
)
_FILM_SLUG_RE = re.compile(r"/film/([^/?#]+)")

# One ``<tr class="column">`` per half-star bucket. The ``<thead>`` row carries
# no such class, so the header never enters the distribution.
_BUCKET_ROW_RE = re.compile(
    r"<tr\b[^>]*\bclass=\"[^\"]*\bcolumn\b[^\"]*\"[^>]*>(.*?)</tr>",
    re.IGNORECASE | re.DOTALL,
)
_BAR_ANCHOR_RE = re.compile(r"<a\b[^>]*\bbarcolumn\b[^>]*>", re.IGNORECASE)
_TITLE_ATTR_RE = re.compile(r"\btitle=\"([^\"]*)\"", re.IGNORECASE)
_ROW_HEADER_RE = re.compile(r"<th\b[^>]*>(.*?)</th>", re.IGNORECASE | re.DOTALL)
_SR_ONLY_RE = re.compile(
    r"<span\b[^>]*\b_sr-only\b[^>]*>(.*?)</span>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]*>")
# "2,230,960 ★★★★★ ratings (48%)" -> the exact size and the star label.
_BUCKET_TITLE_RE = re.compile(
    r"^\s*([\d,]+(?:\.\d+)?\s*[KMB]?)\s+(.+?)\s+ratings?\b",
    re.IGNORECASE,
)
# "2.2M (48%)" / "2,789 (0%)" -> the leading size, abbreviated or not.
_LEADING_COUNT_RE = re.compile(r"^\s*([\d,]+(?:\.\d+)?\s*[KMB]?)\b", re.IGNORECASE)
_ABBREVIATED_COUNT_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([KMB]?)$", re.IGNORECASE)
_COUNT_MULTIPLIERS = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}

# The ten half-star keys, in the order Letterboxd renders them.
BUCKET_KEYS: tuple[str, ...] = tuple(f"{index / 2:.1f}" for index in range(1, 11))

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class LetterboxdRatingError(RuntimeError):
    """A film's rating histogram could not be retrieved."""


class LetterboxdRatingParseError(RuntimeError):
    """The histogram was retrieved but its weighted average was not usable."""


@dataclass(frozen=True)
class RatingCandidate:
    movie_id: int
    title: str
    slug: str


@dataclass(frozen=True)
class ParsedRating:
    """A film's crowd rating, where ``None`` means "Letterboxd did not say".

    ``distribution`` is the ten half-star buckets keyed ``"0.5"``..``"5.0"``, or
    ``None`` when the document carried no buckets at all. It is never an empty
    dict: "no histogram" and "a histogram of zeros" are different claims, and
    only the second one would be a number.
    """

    average: Optional[float]
    count: Optional[int]
    distribution: Optional[Dict[str, int]] = None

    @property
    def is_known(self) -> bool:
        return self.average is not None


@dataclass
class RatingSyncStats:
    selected: int = 0
    skipped_no_slug: int = 0
    fetched: int = 0
    updated: int = 0
    unavailable: int = 0
    failed: int = 0
    dry_run: bool = False
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _aware_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def resolve_slug(letterboxd_slug: Optional[str], letterboxd_url: Optional[str]) -> Optional[str]:
    """Resolve a film's Letterboxd slug, falling back to its stored URL."""
    candidate = (letterboxd_slug or "").strip().strip("/")
    if candidate and "/" not in candidate and "?" not in candidate:
        return candidate
    for source in (candidate, (letterboxd_url or "").strip()):
        if not source:
            continue
        match = _FILM_SLUG_RE.search(source)
        if match:
            resolved = match.group(1).strip("/")
            if resolved:
                return resolved
    return None


def _expand_count_label(raw: str) -> Optional[int]:
    """Turn one bar label into an integer, expanding Letterboxd's abbreviations.

    ``"2,230,960"`` is exact and survives untouched; ``"2.2M"`` expands to
    2,200,000, which is the best the abbreviated form can say. That loss is why
    the exact ``title`` attribute is always preferred over the visible label,
    and why no caller may add these buckets up to obtain a rating count.
    """

    text = (raw or "").strip().replace(",", "").replace(" ", "")
    match = _ABBREVIATED_COUNT_RE.match(text)
    if match is None:
        return None
    multiplier = _COUNT_MULTIPLIERS[match.group(2).upper()]
    return int(round(float(match.group(1)) * multiplier))


def _bucket_key(label: str) -> Optional[str]:
    """Map a star label ("★★½", "half-★") to its ``"0.5"``..``"5.0"`` key."""

    text = _TAG_RE.sub("", label or "").strip()
    if not text:
        return None
    if text.casefold().startswith("half"):
        value = 0.5
    else:
        stars = text.count("★")
        if stars == 0:
            return None
        value = stars + (0.5 if "½" in text else 0.0)
    key = f"{value:.1f}"
    return key if key in BUCKET_KEYS else None


def _parse_buckets(unescaped: str) -> Optional[Dict[str, int]]:
    """Read the half-star buckets out of an already-unescaped include.

    Returns ``None`` when the document has no bucket rows -- an empty include,
    or a film Letterboxd has no histogram for. A row that *is* a bucket but
    whose label or size cannot be read raises, because a partially readable
    histogram is markup drift, and half a distribution stored as if it were
    whole would silently misplace every rating measured against it.
    """

    buckets: Dict[str, int] = {}
    for row in _BUCKET_ROW_RE.findall(unescaped):
        anchor = _BAR_ANCHOR_RE.search(row)
        if anchor is None:
            continue

        title_match = _TITLE_ATTR_RE.search(anchor.group(0))
        title = title_match.group(1) if title_match else ""
        titled = _BUCKET_TITLE_RE.match(title)

        # The star label is written twice -- as the row header and inside the
        # tooltip -- so either one alone is enough to place the bucket.
        header = _ROW_HEADER_RE.search(row)
        labels: List[str] = []
        if header is not None:
            labels.append(header.group(1))
        if titled is not None:
            labels.append(titled.group(2))
        key = next(
            (candidate for candidate in map(_bucket_key, labels) if candidate),
            None,
        )
        if key is None:
            raise LetterboxdRatingParseError(
                "Unreadable rating-histogram bucket label "
                f"{(labels[0].strip() if labels else '')!r}"
            )

        # The title carries the exact figure; the visible label is abbreviated
        # and is only read when that attribute is missing.
        count = _expand_count_label(titled.group(1)) if titled else None
        if count is None:
            visible = _SR_ONLY_RE.findall(row)
            for candidate in visible:
                leading = _LEADING_COUNT_RE.match(_TAG_RE.sub("", candidate).strip())
                if leading is not None:
                    count = _expand_count_label(leading.group(1))
                    if count is not None:
                        break
        if count is None:
            raise LetterboxdRatingParseError(
                f"Unreadable rating-histogram bucket size for {key} stars"
            )
        if key in buckets:
            raise LetterboxdRatingParseError(
                f"Rating histogram repeated the {key}-star bucket"
            )
        buckets[key] = count

    if not buckets:
        return None
    return {key: buckets[key] for key in BUCKET_KEYS if key in buckets}


def parse_rating_buckets(document: Optional[str]) -> Optional[Dict[str, int]]:
    """Public entry point for the half-star buckets of a raw CSI include."""

    if not document:
        return None
    return _parse_buckets(html_module.unescape(document))


def parse_rating_histogram(document: Optional[str]) -> ParsedRating:
    """Parse Letterboxd's weighted-average phrase and buckets out of the include.

    Returns a null average and count when the film has too few ratings for
    Letterboxd to publish an average (the include is then empty, or renders the
    histogram without an ``averagerating`` anchor). That is "unknown", not zero.
    The buckets are read independently: a document can show the shape of its
    ratings without Letterboxd publishing a headline average for them.

    Raises ``LetterboxdRatingParseError`` when the phrase is present but carries
    a value outside Letterboxd's 0-5 scale, which would mean the markup drifted.
    """
    if not document:
        return ParsedRating(average=None, count=None, distribution=None)

    unescaped = html_module.unescape(document)
    distribution = _parse_buckets(unescaped)

    match = _WEIGHTED_AVERAGE_RE.search(unescaped)
    if match is None:
        return ParsedRating(average=None, count=None, distribution=distribution)

    raw_average, raw_count = match.group(1), match.group(2)
    try:
        average = float(raw_average)
        count = int(raw_count.replace(",", ""))
    except ValueError as exc:  # pragma: no cover - regex already constrains this
        raise LetterboxdRatingParseError(f"Unreadable weighted average {raw_average!r}") from exc

    if not 0.0 <= average <= 5.0:
        raise LetterboxdRatingParseError(
            f"Weighted average {average} is outside Letterboxd's 0-5 scale"
        )
    if count < 0:  # pragma: no cover - regex already constrains this
        raise LetterboxdRatingParseError(f"Negative rating count {count}")
    return ParsedRating(average=average, count=count, distribution=distribution)


def _build_session():
    """Mirror the scraper's browser impersonation; Letterboxd challenges plain requests."""
    if curl_requests is not None:
        session = curl_requests.Session(impersonate="chrome")
        impersonates = True
    elif cloudscraper is not None:
        session = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "darwin", "mobile": False}
        )
        impersonates = False
    else:  # pragma: no cover - dependency error surfaced at call time
        raise LetterboxdRatingError(
            "curl_cffi (or cloudscraper) is required to fetch Letterboxd rating histograms"
        )
    session.headers.update(
        {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
            "Referer": "https://letterboxd.com/",
        }
    )
    return session, impersonates


class LetterboxdRatingFetcher:
    """Fetches one film's rating-histogram include, with retry and backoff."""

    def __init__(
        self,
        *,
        session: Any = None,
        impersonates: Optional[bool] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_retries <= 0:
            raise ValueError("max_retries must be positive")
        if session is None:
            session, built_impersonates = _build_session()
            impersonates = built_impersonates if impersonates is None else impersonates
        self._session = session
        self._impersonates = bool(impersonates)
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._timeout_seconds = timeout_seconds
        self._sleep = sleeper

    def fetch(self, slug: str) -> Optional[str]:
        """Return the include's HTML, or ``None`` when Letterboxd has no such film.

        Raises ``LetterboxdRatingError`` once retries are exhausted; the caller
        treats that as a failure and leaves the stored values untouched.
        """
        url = RATING_HISTOGRAM_URL_TEMPLATE.format(slug=slug)
        last_error = "unknown error"
        for attempt in range(self._max_retries):
            try:
                request_kwargs: Dict[str, Any] = {"timeout": self._timeout_seconds}
                if self._impersonates:
                    request_kwargs["impersonate"] = "chrome"
                response = self._session.get(url, **request_kwargs)
                status = int(getattr(response, "status_code", 0))
                if status in (404, 410):
                    # A retired or renamed film page: terminal, never retried.
                    return None
                if status == 429 or status >= 500:
                    last_error = f"HTTP {status}"
                elif status >= 400:
                    raise LetterboxdRatingError(f"HTTP {status} for {url}")
                else:
                    return response.text
            except LetterboxdRatingError:
                raise
            except Exception as exc:  # noqa: BLE001 - any transport error is retryable
                last_error = f"{type(exc).__name__}: {exc}"

            if attempt < self._max_retries - 1:
                wait_seconds = self._backoff_seconds * (2**attempt)
                logger.warning(
                    "Letterboxd rating histogram attempt %s/%s failed for %s (%s); retrying in %ss",
                    attempt + 1,
                    self._max_retries,
                    slug,
                    last_error,
                    wait_seconds,
                )
                self._sleep(wait_seconds)
        raise LetterboxdRatingError(
            f"Failed to fetch {url} after {self._max_retries} attempts ({last_error})"
        )


def _select_candidates(
    db: Session,
    *,
    now: datetime,
    max_age_days: int,
    refresh: bool,
    limit: Optional[int],
    movie_ids: Optional[Sequence[int]],
) -> tuple[List[RatingCandidate], int]:
    cutoff = now - timedelta(days=max_age_days)
    query = db.query(
        Movie.id,
        Movie.title,
        Movie.letterboxd_slug,
        Movie.letterboxd_url,
        Movie.letterboxd_rating_synced_at,
    ).order_by(Movie.id)
    if movie_ids:
        query = query.filter(
            Movie.id.in_(list(dict.fromkeys(int(value) for value in movie_ids)))
        )

    skipped_no_slug = 0
    ranked: List[tuple[tuple[int, datetime, int], RatingCandidate]] = []
    for movie_id, title, slug, url, synced_at in query.all():
        synced = _aware_utc(synced_at)
        if not refresh and synced is not None and synced > cutoff:
            continue
        resolved = resolve_slug(slug, url)
        if not resolved:
            skipped_no_slug += 1
            continue
        # A bounded run should spend its budget on films that were never synced
        # before it revisits the oldest expired ones.
        ranked.append(
            (
                (0 if synced is None else 1, synced or _EPOCH, int(movie_id)),
                RatingCandidate(movie_id=int(movie_id), title=str(title), slug=resolved),
            )
        )
    ranked.sort(key=lambda item: item[0])
    candidates = [candidate for _, candidate in ranked]
    if limit is not None:
        candidates = candidates[:limit]
    return candidates, skipped_no_slug


def _chunks(values: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _persist_rating(
    db: Session,
    candidate: RatingCandidate,
    parsed: ParsedRating,
    *,
    synced_at: datetime,
) -> None:
    """Stamp the attempt, and write values only when Letterboxd published them.

    An "unknown" result never overwrites a previously fetched value: the absent
    phrase means Letterboxd declined to publish one, not that the film's rating
    became zero. The distribution follows the same rule but on its own -- a
    document can carry buckets without a headline average, and a film that has
    an average already keeps it while ``--refresh`` fills in the buckets behind
    it.
    """
    movie = db.get(Movie, candidate.movie_id)
    if movie is None:
        raise ValueError(f"Movie {candidate.movie_id} disappeared during rating sync")
    if parsed.is_known:
        movie.letterboxd_average_rating = parsed.average
        movie.letterboxd_rating_count = parsed.count
    if parsed.distribution is not None:
        movie.letterboxd_rating_distribution = parsed.distribution
    movie.letterboxd_rating_synced_at = synced_at
    db.flush()


def sync_letterboxd_ratings(
    db: Session,
    fetcher: Optional[LetterboxdRatingFetcher] = None,
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: Optional[int] = None,
    movie_ids: Optional[Sequence[int]] = None,
    refresh: bool = False,
    dry_run: bool = False,
    progress: Optional[Callable[[int, int, RatingCandidate], None]] = None,
    sleeper: Callable[[float], None] = time.sleep,
    now: Optional[datetime] = None,
) -> RatingSyncStats:
    """Backfill ``movies.letterboxd_*`` from Letterboxd's rating histograms.

    Resuming is driven entirely by ``movies.letterboxd_rating_synced_at``: a
    film whose stamp is newer than ``max_age_days`` is skipped, and every
    attempt that reached a definite answer (an average, or a confirmed absence)
    is stamped, so an interrupted run picks up where it left off and dead films
    are not retried on every pass. One film never fails the run.
    """
    if max_age_days <= 0:
        raise ValueError("max_age_days must be positive")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if delay_seconds < 0:
        raise ValueError("delay_seconds must not be negative")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive when provided")

    current_time = _aware_utc(now) or datetime.now(timezone.utc)
    candidates, skipped_no_slug = _select_candidates(
        db,
        now=current_time,
        max_age_days=max_age_days,
        refresh=refresh,
        limit=limit,
        movie_ids=movie_ids,
    )
    # End the read transaction before the (slow, deliberately paced) fetches.
    db.rollback()

    stats = RatingSyncStats(
        selected=len(candidates),
        skipped_no_slug=skipped_no_slug,
        dry_run=dry_run,
    )
    if dry_run or not candidates:
        return stats
    if fetcher is None:
        raise ValueError("fetcher is required unless dry_run is enabled")

    completed = 0
    requests_made = 0
    for candidate_batch in _chunks(candidates, batch_size):
        resolved_batch: List[tuple[RatingCandidate, ParsedRating]] = []
        for candidate in candidate_batch:
            if progress:
                progress(completed + 1, len(candidates), candidate)
            completed += 1
            if requests_made and delay_seconds:
                sleeper(delay_seconds)
            try:
                document = fetcher.fetch(candidate.slug)
                requests_made += 1
                stats.fetched += 1
                parsed = parse_rating_histogram(document)
            except Exception as exc:  # noqa: BLE001 - one film never fails the run
                requests_made += 1
                stats.failed += 1
                message = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Letterboxd rating sync failed for %s (%s): %s",
                    candidate.slug,
                    candidate.movie_id,
                    message,
                )
                stats.errors.append(
                    {
                        "movie_id": candidate.movie_id,
                        "title": candidate.title,
                        "slug": candidate.slug,
                        "error": message,
                    }
                )
                continue
            resolved_batch.append((candidate, parsed))

        written_updates = 0
        written_unavailable = 0
        for candidate, parsed in resolved_batch:
            try:
                with db.begin_nested():
                    _persist_rating(
                        db,
                        candidate,
                        parsed,
                        synced_at=datetime.now(timezone.utc),
                    )
                if parsed.is_known:
                    written_updates += 1
                else:
                    written_unavailable += 1
            except Exception as exc:  # noqa: BLE001 - one film never fails the run
                stats.failed += 1
                message = f"Database write failed: {exc}"
                logger.warning(
                    "Letterboxd rating write failed for %s (%s): %s",
                    candidate.slug,
                    candidate.movie_id,
                    exc,
                )
                stats.errors.append(
                    {
                        "movie_id": candidate.movie_id,
                        "title": candidate.title,
                        "slug": candidate.slug,
                        "error": message,
                    }
                )

        try:
            db.commit()
            stats.updated += written_updates
            stats.unavailable += written_unavailable
        except Exception as exc:  # noqa: BLE001 - a lost batch must not stop the run
            db.rollback()
            stats.failed += written_updates + written_unavailable
            stats.errors.append(
                {
                    "movie_id": None,
                    "title": None,
                    "slug": None,
                    "error": f"Batch commit failed: {exc}",
                }
            )

    return stats
