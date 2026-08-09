"""Small, synchronous MyAnimeList API v2 client.

Reads public anime lists for the profiles this instance tracks. Only the
public surface is used: `GET /users/{name}/animelist` with a client id, which
needs no per-user OAuth and so needs nothing from the people being tracked.

The credential is a client id registered once against the MAL developer
console and supplied as MAL_CLIENT_ID. It is sent as `X-MAL-CLIENT-ID`, never
in a query string, so it cannot end up in a proxy log or a redirect.

Design notes worth keeping:

- MAL paginates with an opaque `paging.next` URL rather than page numbers. The
  cursor is followed rather than reconstructed, and it is checked to be on
  MAL's own host before being fetched, so a compromised or surprising response
  cannot walk this client onto another origin.
- A score of 0 on MAL means "unscored", not "the worst". It is returned as
  None, because a zero standing in for an absence is the mistake this product
  keeps finding in its own panels.
- Dates arrive as `YYYY-MM-DD`, `YYYY-MM` or `YYYY` — MAL genuinely stores
  partial dates. Anything short of a full date is None rather than a guessed
  first-of-the-month, since these dates are what an overlap is computed from.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import os
import time
from typing import Any, Dict, Iterator, List, Mapping, Optional
from urllib.parse import urlsplit

import requests


DEFAULT_API_BASE_URL = "https://api.myanimelist.net/v2"
API_HOST = "api.myanimelist.net"
# MAL's documented ceiling for this endpoint. Asking for more is rejected
# rather than truncated, so it is pinned here instead of being a caller's
# problem.
MAX_PAGE_LIMIT = 1000
# Everything the list endpoint will give about an entry, plus the fields of
# the title itself that the catalogue stores.
LIST_FIELDS = (
    "list_status{status,score,num_episodes_watched,is_rewatching,"
    "num_times_rewatched,start_date,finish_date,updated_at},"
    "id,title,alternative_titles,media_type,num_episodes,status,"
    "start_date,end_date,mean,main_picture,synopsis,genres,studios"
)
REQUEST_TIMEOUT_SECONDS = 20
# MAL is not explicit about its rate limit; this is deliberately gentle. A
# full list is a handful of requests, and being slow costs nothing here.
MIN_SECONDS_BETWEEN_REQUESTS = 0.7


class MALError(RuntimeError):
    """Base error for a MyAnimeList operation."""


class MALConfigurationError(MALError):
    """Raised when no MAL client id is configured."""


class MALNotFoundError(MALError):
    """Raised when MAL has no such user, or their list is private.

    The two are deliberately one error: MAL answers 404 for both, and
    inventing a distinction the API does not draw would be a guess.
    """


class MALRequestError(MALError):
    """Raised after an HTTP or response-decoding failure."""

    def __init__(self, message: str, *, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def resolve_client_id(explicit: Optional[str] = None) -> str:
    client_id = (explicit or os.getenv("MAL_CLIENT_ID") or "").strip()
    if not client_id:
        raise MALConfigurationError(
            "MAL_CLIENT_ID is not set; register a client id in the MyAnimeList "
            "developer console and add it to the API environment"
        )
    return client_id


def parse_mal_date(value: Any) -> Optional[date]:
    """MAL stores partial dates. A partial date is not a date.

    `2019` and `2019-04` are both real MAL values. Widening either into a
    concrete day would invent a fact that overlap timing is computed from, so
    only a full date is accepted.
    """

    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_mal_timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def normalise_score(value: Any) -> Optional[int]:
    """0 on MAL means unscored, and must not become a rating of zero."""

    if not isinstance(value, int) or isinstance(value, bool):
        return None
    if value <= 0 or value > 10:
        return None
    return value


class MALClient:
    def __init__(
        self,
        *,
        client_id: Optional[str] = None,
        base_url: str = DEFAULT_API_BASE_URL,
        session: Optional[requests.Session] = None,
        min_interval_seconds: float = MIN_SECONDS_BETWEEN_REQUESTS,
    ) -> None:
        self._client_id = resolve_client_id(client_id)
        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._min_interval = max(0.0, min_interval_seconds)
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if self._last_request_at and elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_at = time.monotonic()

    def _get(self, url: str, params: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        # Every URL this client fetches -- including a pagination cursor the
        # API handed back -- must be MAL's own host over HTTPS.
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != API_HOST:
            raise MALRequestError("refusing to follow a URL outside the MyAnimeList API")

        self._throttle()
        try:
            response = self._session.get(
                url,
                params=params,
                headers={
                    "X-MAL-CLIENT-ID": self._client_id,
                    "Accept": "application/json",
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise MALRequestError("the MyAnimeList API could not be reached") from exc

        if response.status_code == 404:
            raise MALNotFoundError(
                "MyAnimeList has no such user, or their list is not public"
            )
        if response.status_code >= 400:
            raise MALRequestError(
                f"the MyAnimeList API answered HTTP {response.status_code}",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MALRequestError("the MyAnimeList API returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise MALRequestError("the MyAnimeList API returned an unexpected shape")
        return payload

    def iter_anime_list(
        self, username: str, *, limit: int = 500, max_pages: int = 40
    ) -> Iterator[Dict[str, Any]]:
        """Yield one normalised entry per title on a member's public list.

        `max_pages` is a runaway guard, not a policy: at 500 per page it
        covers 20,000 titles, well past any real list. Hitting it means the
        cursor is looping, which is worth stopping for rather than paging
        forever.
        """

        name = (username or "").strip()
        if not name:
            raise MALRequestError("a MyAnimeList username is required")

        url = f"{self._base_url}/users/{requests.utils.quote(name, safe='')}/animelist"
        params: Optional[Dict[str, Any]] = {
            "fields": LIST_FIELDS,
            "limit": min(max(int(limit), 1), MAX_PAGE_LIMIT),
            "nsfw": "true",
        }

        for _ in range(max_pages):
            payload = self._get(url, params)
            for node in payload.get("data") or []:
                entry = normalise_list_entry(node)
                if entry is not None:
                    yield entry
            following = (payload.get("paging") or {}).get("next")
            if not isinstance(following, str) or not following:
                return
            # The cursor already carries its query; sending ours again would
            # override the offset it encodes.
            url, params = following, None
        raise MALRequestError("the MyAnimeList list cursor did not terminate")


def normalise_list_entry(node: Any) -> Optional[Dict[str, Any]]:
    """One MAL list row into the shape the importer stores.

    Returns None for a row without an id or a status: those are the two facts
    an entry cannot mean anything without, and a partial row is dropped rather
    than written with invented defaults.
    """

    if not isinstance(node, dict):
        return None
    anime = node.get("node")
    status_block = node.get("list_status")
    if not isinstance(anime, dict) or not isinstance(status_block, dict):
        return None

    mal_id = anime.get("id")
    if not isinstance(mal_id, int) or isinstance(mal_id, bool) or mal_id <= 0:
        return None
    status = status_block.get("status")
    if not isinstance(status, str) or not status.strip():
        return None

    alternative = anime.get("alternative_titles")
    alternative = alternative if isinstance(alternative, dict) else {}
    picture = anime.get("main_picture")
    picture = picture if isinstance(picture, dict) else {}

    return {
        "mal_id": mal_id,
        "title": str(anime.get("title") or "").strip() or f"MAL #{mal_id}",
        "title_english": (alternative.get("en") or "").strip() or None,
        "title_japanese": (alternative.get("ja") or "").strip() or None,
        "media_type": anime.get("media_type") or None,
        "episodes": anime.get("num_episodes")
        if isinstance(anime.get("num_episodes"), int)
        else None,
        "airing_status": anime.get("status") or None,
        "start_date": parse_mal_date(anime.get("start_date")),
        "end_date": parse_mal_date(anime.get("end_date")),
        "mean_score": anime.get("mean") if isinstance(anime.get("mean"), (int, float)) else None,
        # Preferring the large image: the small one is 100px wide and looks
        # like a broken asset beside the film posters.
        "poster_url": picture.get("large") or picture.get("medium") or None,
        "synopsis": (anime.get("synopsis") or "").strip() or None,
        "genres": [
            genre["name"]
            for genre in (anime.get("genres") or [])
            if isinstance(genre, dict) and isinstance(genre.get("name"), str)
        ],
        "studios": [
            studio["name"]
            for studio in (anime.get("studios") or [])
            if isinstance(studio, dict) and isinstance(studio.get("name"), str)
        ],
        "status": status.strip(),
        "score": normalise_score(status_block.get("score")),
        "episodes_watched": status_block.get("num_episodes_watched")
        if isinstance(status_block.get("num_episodes_watched"), int)
        else None,
        "is_rewatching": bool(status_block.get("is_rewatching")),
        "times_rewatched": status_block.get("num_times_rewatched")
        if isinstance(status_block.get("num_times_rewatched"), int)
        else None,
        "started_date": parse_mal_date(status_block.get("start_date")),
        "finished_date": parse_mal_date(status_block.get("finish_date")),
        "updated_at_source": parse_mal_timestamp(status_block.get("updated_at")),
    }


def fetch_anime_list(username: str, *, client_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Convenience wrapper: the whole list, normalised."""

    return list(MALClient(client_id=client_id).iter_anime_list(username))
