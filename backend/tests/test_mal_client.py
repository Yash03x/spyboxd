"""What the MyAnimeList client is allowed to claim.

Anime arrives from a service whose conventions differ from Letterboxd's in
three ways that have each already caused a bug on the film side: a zero that
means "absent", a date that is not a whole date, and a paginated feed whose
cursor is handed back rather than constructed. Each is pinned here.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from services.mal_client import (
    MALClient,
    MALConfigurationError,
    MALNotFoundError,
    MALRequestError,
    normalise_list_entry,
    normalise_score,
    parse_mal_date,
    parse_mal_timestamp,
)


class FakeResponse:
    def __init__(self, payload, status_code: int = 200, *, invalid_json: bool = False):
        self._payload = payload
        self.status_code = status_code
        self._invalid_json = invalid_json

    def json(self):
        if self._invalid_json:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Records what was asked for, so the request itself can be asserted."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        if not self._responses:
            raise AssertionError("the client made more requests than the test provided")
        return self._responses.pop(0)


def _entry(**overrides):
    node = {
        "node": {
            "id": 5114,
            "title": "Fullmetal Alchemist: Brotherhood",
            "alternative_titles": {"en": "Fullmetal Alchemist: Brotherhood", "ja": "鋼の錬金術師"},
            "media_type": "tv",
            "num_episodes": 64,
            "status": "finished_airing",
            "start_date": "2009-04-05",
            "end_date": "2010-07-04",
            "mean": 9.1,
            "main_picture": {"medium": "https://cdn.myanimelist.net/s.jpg", "large": "https://cdn.myanimelist.net/l.jpg"},
            "genres": [{"id": 1, "name": "Action"}, {"id": 2, "name": "Adventure"}],
            "studios": [{"id": 4, "name": "Bones"}],
        },
        "list_status": {
            "status": "completed",
            "score": 10,
            "num_episodes_watched": 64,
            "is_rewatching": False,
            "num_times_rewatched": 1,
            "start_date": "2024-01-02",
            "finish_date": "2024-02-11",
            "updated_at": "2024-02-11T18:04:00+00:00",
        },
    }
    node["node"].update(overrides.pop("node", {}))
    node["list_status"].update(overrides.pop("list_status", {}))
    return node


def test_an_unscored_entry_is_absent_rather_than_a_score_of_zero() -> None:
    """MAL writes 0 for unscored. Stored as 0 it would drag every average
    down and read as the worst possible opinion."""

    assert normalise_score(0) is None
    assert normalise_score(None) is None
    assert normalise_score(True) is None
    assert normalise_score(8) == 8
    # Out of MAL's own range, so not a score it could have meant.
    assert normalise_score(11) is None


def test_a_partial_date_is_not_widened_into_a_day() -> None:
    """MAL genuinely stores `2019` and `2019-04`. Overlap timing is computed
    from these dates, so inventing a first-of-the-month would manufacture a
    coincidence."""

    assert parse_mal_date("2019-04-05") == date(2019, 4, 5)
    assert parse_mal_date("2019-04") is None
    assert parse_mal_date("2019") is None
    assert parse_mal_date("") is None
    assert parse_mal_date(None) is None


def test_a_naive_timestamp_is_read_as_utc() -> None:
    assert parse_mal_timestamp("2024-02-11T18:04:00Z") == datetime(
        2024, 2, 11, 18, 4, tzinfo=timezone.utc
    )
    assert parse_mal_timestamp("2024-02-11T18:04:00") == datetime(
        2024, 2, 11, 18, 4, tzinfo=timezone.utc
    )
    assert parse_mal_timestamp("nonsense") is None


def test_a_row_without_an_id_or_a_status_is_dropped_rather_than_defaulted() -> None:
    assert normalise_list_entry({"node": {"id": 1}}) is None
    assert normalise_list_entry(_entry(node={"id": None})) is None
    assert normalise_list_entry(_entry(list_status={"status": ""})) is None
    assert normalise_list_entry("not a dict") is None


def test_a_normalised_entry_keeps_mal_s_own_vocabulary() -> None:
    entry = normalise_list_entry(_entry())

    assert entry["mal_id"] == 5114
    # Not translated into the film side's vocabulary, which has no "on hold".
    assert entry["status"] == "completed"
    assert entry["score"] == 10
    assert entry["finished_date"] == date(2024, 2, 11)
    assert entry["genres"] == ["Action", "Adventure"]
    assert entry["studios"] == ["Bones"]
    # The large image: the medium one is a hundred pixels wide and reads as a
    # broken asset beside the film posters.
    assert entry["poster_url"].endswith("l.jpg")


def test_the_client_id_travels_in_a_header_not_a_query_string() -> None:
    session = FakeSession([FakeResponse({"data": [_entry()], "paging": {}})])
    client = MALClient(client_id="abc123", session=session, min_interval_seconds=0)

    list(client.iter_anime_list("whiteknight03X"))

    call = session.calls[0]
    assert call["headers"]["X-MAL-CLIENT-ID"] == "abc123"
    # A credential in a query string ends up in proxy logs and referrers.
    assert "abc123" not in call["url"]
    assert "abc123" not in str(call["params"])


def test_pagination_follows_mal_s_cursor_without_re_sending_our_own_query() -> None:
    """The cursor already encodes the offset; sending `limit` again with it
    would restart the page it points at."""

    session = FakeSession(
        [
            FakeResponse(
                {
                    "data": [_entry()],
                    "paging": {
                        "next": "https://api.myanimelist.net/v2/users/x/animelist?offset=500"
                    },
                }
            ),
            FakeResponse({"data": [_entry(node={"id": 1})], "paging": {}}),
        ]
    )
    client = MALClient(client_id="abc123", session=session, min_interval_seconds=0)

    entries = list(client.iter_anime_list("x"))

    assert [entry["mal_id"] for entry in entries] == [5114, 1]
    assert session.calls[1]["params"] is None


def test_a_cursor_pointing_off_mal_is_refused() -> None:
    """A pagination URL is a URL the API chose. It is still checked."""

    session = FakeSession(
        [
            FakeResponse(
                {"data": [], "paging": {"next": "https://evil.example/v2/users/x/animelist"}}
            )
        ]
    )
    client = MALClient(client_id="abc123", session=session, min_interval_seconds=0)

    with pytest.raises(MALRequestError, match="outside the MyAnimeList API"):
        list(client.iter_anime_list("x"))


def test_a_private_or_missing_list_is_one_honest_error() -> None:
    """MAL answers 404 for both, and drawing a distinction it does not make
    would be a guess presented as a fact."""

    session = FakeSession([FakeResponse({}, status_code=404)])
    client = MALClient(client_id="abc123", session=session, min_interval_seconds=0)

    with pytest.raises(MALNotFoundError):
        list(client.iter_anime_list("nobody"))


def test_a_runaway_cursor_stops_instead_of_paging_forever() -> None:
    looping = FakeResponse(
        {
            "data": [_entry()],
            "paging": {"next": "https://api.myanimelist.net/v2/users/x/animelist?offset=0"},
        }
    )
    session = FakeSession([looping] * 12)
    client = MALClient(client_id="abc123", session=session, min_interval_seconds=0)

    with pytest.raises(MALRequestError, match="did not terminate"):
        list(client.iter_anime_list("x", max_pages=10))


def test_a_missing_credential_says_what_to_do_about_it(monkeypatch) -> None:
    monkeypatch.delenv("MAL_CLIENT_ID", raising=False)

    with pytest.raises(MALConfigurationError, match="developer console"):
        MALClient()
