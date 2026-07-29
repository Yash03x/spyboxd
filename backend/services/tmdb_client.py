"""Small, synchronous TMDB API client used only by the opt-in enrichment job."""

from __future__ import annotations

from difflib import SequenceMatcher
import math
import os
import re
import time
import unicodedata
from typing import Any, Callable, Dict, List, Mapping, Optional

import requests


DEFAULT_API_BASE_URL = "https://api.themoviedb.org/3"
DEFAULT_LANGUAGE = "en-US"
DETAIL_APPEND_ENDPOINTS = "credits,keywords,external_ids,release_dates"


class TMDBError(RuntimeError):
    """Base error for an opt-in TMDB enrichment operation."""


class TMDBConfigurationError(TMDBError):
    """Raised when no supported TMDB credential is configured."""


class TMDBNotFoundError(TMDBError):
    """Raised when TMDB returns a 404 for a requested resource."""


class TMDBRequestError(TMDBError):
    """Raised after an HTTP or response-decoding failure."""

    def __init__(self, message: str, *, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _normalized_title(value: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    without_marks = "".join(character for character in decomposed if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^\w]+", " ", without_marks.casefold()).split())


def _release_year(value: Any) -> Optional[int]:
    match = re.match(r"^(\d{4})", str(value or ""))
    return int(match.group(1)) if match else None


def _numbered_title_markers(value: Any) -> tuple[int, ...]:
    """Return standalone Arabic and Roman numerals that distinguish title entries.

    A lone ``I`` is deliberately excluded because it is commonly the English
    pronoun (for example, ``Here I Come``). Other Roman numerals retain their
    original uppercase requirement so ordinary words are not interpreted as
    sequel numbers.
    """
    text = unicodedata.normalize("NFKC", str(value or ""))
    markers: List[int] = []
    for match in re.finditer(r"(?<!\w)(\d+|[IVXLCDM]+)(?!\w)", text):
        token = match.group(1)
        if token.isdigit():
            markers.append(int(token))
            continue
        if token == "I" or token != token.upper():
            continue

        total = 0
        previous = 0
        for character in reversed(token):
            value = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}[character]
            if value < previous:
                total -= value
            else:
                total += value
                previous = value
        markers.append(total)
    return tuple(markers)


def select_best_movie_match(
    results: List[Mapping[str, Any]],
    *,
    title: str,
    release_year: Optional[int],
) -> Optional[Dict[str, Any]]:
    """Choose a conservative title/year match from TMDB search results."""
    wanted_title = _normalized_title(title)
    if not wanted_title:
        return None
    wanted_markers = _numbered_title_markers(title)

    ranked: List[tuple[float, float, Dict[str, Any]]] = []
    for raw_result in results:
        result = dict(raw_result)
        try:
            tmdb_id = int(result.get("id"))
        except (TypeError, ValueError):
            continue
        if tmdb_id <= 0:
            continue

        candidate_titles = {
            normalized
            for normalized in (
                _normalized_title(result.get("title")),
                _normalized_title(result.get("original_title")),
            )
            if normalized
        }
        if not candidate_titles:
            continue

        # Numbered installments are especially prone to false-positive fuzzy
        # matches (``II`` and ``III`` differ by one character). If both titles
        # explicitly identify an installment, those markers must agree. A
        # marker may still be absent from one title because TMDB sometimes
        # publishes a subtitle-only variant (for example, ``Ready or Not 2:
        # Here I Come`` versus ``Ready or Not: Here I Come``).
        candidate_marker_variants = {
            markers
            for markers in (
                _numbered_title_markers(result.get("title")),
                _numbered_title_markers(result.get("original_title")),
            )
            if markers
        }
        if (
            wanted_markers
            and candidate_marker_variants
            and wanted_markers not in candidate_marker_variants
        ):
            continue

        exact_title = wanted_title in candidate_titles
        title_similarity = max(
            SequenceMatcher(None, wanted_title, candidate_title).ratio()
            for candidate_title in candidate_titles
        )
        candidate_year = _release_year(result.get("release_date"))
        exact_year = release_year is not None and candidate_year == release_year
        near_year = (
            release_year is not None
            and candidate_year is not None
            and abs(candidate_year - release_year) <= 1
        )

        # Reject plausible-looking but wrong remakes. A fuzzy title is accepted
        # only with an exact year; an exact title tolerates a one-year festival /
        # territory release discrepancy.
        if release_year is not None and candidate_year is not None:
            if exact_title and not near_year:
                continue
            if not exact_title and not (exact_year and title_similarity >= 0.92):
                continue
        elif not exact_title and title_similarity < 0.96:
            continue

        try:
            popularity = max(float(result.get("popularity") or 0.0), 0.0)
        except (TypeError, ValueError):
            popularity = 0.0

        score = (100.0 if exact_title else title_similarity * 60.0)
        if exact_year:
            score += 30.0
        elif near_year:
            score += 12.0
        elif release_year is None or candidate_year is None:
            score += 2.0
        score += min(math.log1p(popularity), 8.0)
        ranked.append((score, popularity, result))

    if not ranked:
        return None
    ranked.sort(key=lambda pair: (pair[0], pair[1]), reverse=True)
    return ranked[0][2]


class TMDBClient:
    """Authenticated TMDB v3 client with bounded retries for 429/5xx failures."""

    def __init__(
        self,
        *,
        bearer_token: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_API_BASE_URL,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
        session: Optional[requests.Session] = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.bearer_token = (bearer_token or "").strip() or None
        self.api_key = (api_key or "").strip() or None
        if not self.bearer_token and not self.api_key:
            raise TMDBConfigurationError(
                "TMDB credentials are missing. Set TMDB_API_TOKEN (or TMDB_BEARER_TOKEN) "
                "for a read-access bearer token, or set TMDB_API_KEY for a v3 API key."
            )
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")

        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.sleeper = sleeper
        self.session.headers.setdefault("Accept", "application/json")
        self.session.headers.setdefault("User-Agent", "Spyboxd-TMDB-Enrichment/1.0")
        if self.bearer_token:
            self.session.headers["Authorization"] = f"Bearer {self.bearer_token}"

    @classmethod
    def from_env(cls, **kwargs: Any) -> "TMDBClient":
        bearer_token = (
            os.getenv("TMDB_BEARER_TOKEN")
            or os.getenv("TMDB_API_TOKEN")
            or os.getenv("TMDB_READ_ACCESS_TOKEN")
        )
        return cls(
            bearer_token=bearer_token,
            api_key=os.getenv("TMDB_API_KEY"),
            base_url=os.getenv("TMDB_API_BASE_URL", DEFAULT_API_BASE_URL),
            **kwargs,
        )

    def search_movies(
        self,
        title: str,
        *,
        release_year: Optional[int] = None,
        language: str = DEFAULT_LANGUAGE,
    ) -> List[Dict[str, Any]]:
        payload = self._get(
            "/search/movie",
            params={
                "query": title,
                "primary_release_year": release_year,
                "include_adult": "false",
                "language": language,
                "page": 1,
            },
        )
        results = payload.get("results")
        if not isinstance(results, list):
            return []
        return [dict(result) for result in results if isinstance(result, Mapping)]

    def find_movie(
        self,
        title: str,
        *,
        release_year: Optional[int] = None,
        language: str = DEFAULT_LANGUAGE,
    ) -> Optional[Dict[str, Any]]:
        return select_best_movie_match(
            self.search_movies(title, release_year=release_year, language=language),
            title=title,
            release_year=release_year,
        )

    def get_movie_details(
        self,
        tmdb_id: int,
        *,
        language: str = DEFAULT_LANGUAGE,
    ) -> Dict[str, Any]:
        return self._get(
            f"/movie/{int(tmdb_id)}",
            params={
                "append_to_response": DETAIL_APPEND_ENDPOINTS,
                "language": language,
            },
        )

    def get_movie_watch_providers(self, tmdb_id: int) -> Dict[str, Any]:
        return self._get(f"/movie/{int(tmdb_id)}/watch/providers")

    def _get(self, path: str, *, params: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        request_params = {
            key: value
            for key, value in dict(params or {}).items()
            if value is not None
        }
        if not self.bearer_token and self.api_key:
            request_params["api_key"] = self.api_key

        url = f"{self.base_url}/{path.lstrip('/')}"
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=request_params,
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                if attempt < self.max_retries:
                    self.sleeper(min(2**attempt, 8))
                    continue
                raise TMDBRequestError(f"TMDB request failed: {exc}") from exc

            if response.status_code == 404:
                raise TMDBNotFoundError(f"TMDB resource was not found: {path}")
            if response.status_code in {401, 403}:
                raise TMDBRequestError(
                    "TMDB rejected the configured credential. Check the bearer token or API key.",
                    status_code=response.status_code,
                )
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self.max_retries:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = float(retry_after) if retry_after is not None else float(2**attempt)
                    except (TypeError, ValueError):
                        delay = float(2**attempt)
                    self.sleeper(max(0.0, min(delay, 30.0)))
                    continue
            if not response.ok:
                raise TMDBRequestError(
                    f"TMDB returned HTTP {response.status_code} for {path}",
                    status_code=response.status_code,
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise TMDBRequestError(f"TMDB returned invalid JSON for {path}") from exc
            if not isinstance(payload, dict):
                raise TMDBRequestError(f"TMDB returned an unexpected payload for {path}")
            return payload

        raise TMDBRequestError(f"TMDB request failed after retries: {path}")
