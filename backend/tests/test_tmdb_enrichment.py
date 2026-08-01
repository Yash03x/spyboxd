from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import traceback
import unittest
from unittest.mock import Mock, patch

import requests


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database.models import Movie
from services.tmdb_client import (
    DETAIL_APPEND_ENDPOINTS,
    TMDBClient,
    TMDBConfigurationError,
    TMDBRequestError,
    select_best_movie_match,
)
from services.tmdb_enrichment import (
    EnrichmentCandidate,
    _persist_lookup_deferral,
    _select_candidates,
    _tmdb_lookup_key,
    build_enrichment_values,
    enrich_movies,
    provider_rows_for_region,
)


class FakeResponse:
    def __init__(self, status_code, payload, *, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


class FakeHTTPSession:
    def __init__(self, responses):
        self.headers = {}
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, params, timeout):
        self.calls.append({"url": url, "params": dict(params), "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def outerjoin(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def distinct(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.rows)


class FakeSelectionSession:
    def __init__(self, movie_rows, provider_rows=()):
        self.movie_query = FakeQuery(movie_rows)
        self.provider_query = FakeQuery(provider_rows)
        self.query_count = 0
        self.rolled_back = False
        self.commits = 0

    def query(self, *entities):
        self.query_count += 1
        return self.movie_query if self.query_count == 1 else self.provider_query

    def rollback(self):
        self.rolled_back = True

    def commit(self):
        self.commits += 1


class FakeIdentityConflictSession:
    def __init__(self, movie_rows, owner_rows):
        self.query_results = [movie_rows, [], owner_rows]
        self.query_count = 0
        self.rolled_back = False
        self.commits = 0
        self.write_attempts = 0
        self.movies = {
            int(row[0]): Movie(
                id=int(row[0]),
                canonical_key=f"test:{row[0]}",
                title=str(row[1]),
                normalized_title=str(row[1]).casefold(),
                release_year=row[2],
                tmdb_id=row[3],
            )
            for row in movie_rows
        }

    def query(self, *entities):
        result = self.query_results[self.query_count]
        self.query_count += 1
        return FakeQuery(result)

    def rollback(self):
        self.rolled_back = True

    def commit(self):
        self.commits += 1

    def begin_nested(self):
        self.write_attempts += 1
        return nullcontext()

    def get(self, model, movie_id):
        if model is Movie:
            return self.movies.get(int(movie_id))
        raise AssertionError(f"Unexpected model lookup: {model}")

    def flush(self):
        return None


class FakeMatchingClient:
    def __init__(self, matches):
        self.matches = matches

    def find_movie(self, title, *, release_year, language):
        tmdb_id = self.matches.get(title)
        return {"id": tmdb_id} if tmdb_id is not None else None

    def get_movie_details(self, tmdb_id, *, language):
        return {"id": tmdb_id}

    def get_movie_watch_providers(self, tmdb_id):
        return {"results": {}}


class TMDBClientTests(unittest.TestCase):
    def test_missing_credentials_fail_clearly(self):
        with self.assertRaisesRegex(TMDBConfigurationError, "TMDB credentials are missing"):
            TMDBClient()

    def test_bearer_auth_and_appended_detail_request(self):
        session = FakeHTTPSession([FakeResponse(200, {"id": 11})])
        client = TMDBClient(bearer_token="read-token", session=session)

        payload = client.get_movie_details(11)

        self.assertEqual(payload["id"], 11)
        self.assertEqual(session.headers["Authorization"], "Bearer read-token")
        self.assertEqual(session.calls[0]["params"]["append_to_response"], DETAIL_APPEND_ENDPOINTS)
        self.assertNotIn("api_key", session.calls[0]["params"])

    def test_v3_key_is_sent_as_query_parameter(self):
        session = FakeHTTPSession([FakeResponse(200, {"results": []})])
        client = TMDBClient(api_key="v3-key", session=session)

        client.search_movies("Arrival", release_year=2016)

        self.assertEqual(session.calls[0]["params"]["api_key"], "v3-key")
        self.assertEqual(session.calls[0]["params"]["primary_release_year"], 2016)
        self.assertNotIn("Authorization", session.headers)

    def test_429_respects_retry_after(self):
        sleeps = []
        session = FakeHTTPSession(
            [
                FakeResponse(429, {}, headers={"Retry-After": "0.25"}),
                FakeResponse(200, {"results": []}),
            ]
        )
        client = TMDBClient(
            bearer_token="read-token",
            session=session,
            sleeper=sleeps.append,
            max_retries=1,
        )

        client.search_movies("Arrival")

        self.assertEqual(sleeps, [0.25])
        self.assertEqual(len(session.calls), 2)

    def test_environment_can_add_conservative_request_pacing(self):
        sleeps = []
        session = FakeHTTPSession([FakeResponse(200, {"results": []})])
        with patch.dict(
            "os.environ",
            {
                "TMDB_API_TOKEN": "read-token",
                "TMDB_REQUEST_PAUSE_SECONDS": "0.2",
            },
            clear=True,
        ):
            client = TMDBClient.from_env(session=session, sleeper=sleeps.append)

        client.search_movies("Arrival")

        self.assertEqual(sleeps, [0.2])
        self.assertEqual(len(session.calls), 1)

    def test_find_movie_retries_without_year_filter_for_near_year_release(self):
        session = FakeHTTPSession(
            [
                FakeResponse(200, {"results": []}),
                FakeResponse(
                    200,
                    {
                        "results": [
                            {
                                "id": 55347,
                                "title": "Beginners",
                                "release_date": "2011-06-03",
                                "popularity": 12,
                            }
                        ]
                    },
                ),
            ]
        )
        client = TMDBClient(bearer_token="read-token", session=session)

        match = client.find_movie("Beginners", release_year=2010)

        self.assertIsNotNone(match)
        self.assertEqual(match["id"], 55347)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[0]["params"]["primary_release_year"], 2010)
        self.assertNotIn("primary_release_year", session.calls[1]["params"])

    def test_find_movie_does_not_fallback_after_narrow_match(self):
        session = FakeHTTPSession(
            [
                FakeResponse(
                    200,
                    {
                        "results": [
                            {
                                "id": 329865,
                                "title": "Arrival",
                                "release_date": "2016-11-10",
                                "popularity": 20,
                            }
                        ]
                    },
                )
            ]
        )
        client = TMDBClient(bearer_token="read-token", session=session)

        match = client.find_movie("Arrival", release_year=2016)

        self.assertIsNotNone(match)
        self.assertEqual(match["id"], 329865)
        self.assertEqual(len(session.calls), 1)

    def test_find_movie_without_year_uses_one_unfiltered_search(self):
        session = FakeHTTPSession([FakeResponse(200, {"results": []})])
        client = TMDBClient(bearer_token="read-token", session=session)

        self.assertIsNone(client.find_movie("Unknown Film"))

        self.assertEqual(len(session.calls), 1)
        self.assertNotIn("primary_release_year", session.calls[0]["params"])

    def test_request_exception_does_not_expose_credentials_in_error_or_traceback(self):
        api_key = "super-secret-v3-key"
        bearer_token = "super-secret-bearer-token"
        request_error = requests.RequestException(
            "connection failed for "
            f"https://api.themoviedb.org/3/search/movie?api_key={api_key} "
            f"with Authorization: Bearer {bearer_token}"
        )
        session = FakeHTTPSession([request_error])
        client = TMDBClient(api_key=api_key, session=session, max_retries=0)

        try:
            client.search_movies("Arrival")
        except TMDBRequestError as exc:
            raised_error = exc
            serialized_error = str(exc)
            formatted_traceback = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
        else:
            self.fail("TMDBRequestError was not raised")

        self.assertEqual(
            serialized_error,
            "TMDB request failed while contacting the upstream service.",
        )
        self.assertIsNone(raised_error.__context__)
        for secret in (api_key, bearer_token):
            self.assertNotIn(secret, serialized_error)
            self.assertNotIn(secret, formatted_traceback)

    def test_matcher_rejects_a_wrong_year_remake(self):
        results = [
            {"id": 1, "title": "Suspiria", "release_date": "2018-10-26", "popularity": 20},
            {"id": 2, "title": "Suspiria", "release_date": "1977-02-01", "popularity": 5},
        ]

        match = select_best_movie_match(results, title="Suspiria", release_year=1977)

        self.assertIsNotNone(match)
        self.assertEqual(match["id"], 2)

    def test_matcher_rejects_conflicting_sequel_numbers(self):
        results = [
            {
                "id": 1,
                "title": "Drunken Master III",
                "release_date": "1994-02-03",
                "popularity": 50,
            }
        ]

        match = select_best_movie_match(
            results,
            title="Drunken Master II",
            release_year=1994,
        )

        self.assertIsNone(match)

    def test_matcher_accepts_subtitle_variant_that_omits_sequel_number(self):
        results = [
            {
                "id": 1,
                "title": "Ready or Not: Here I Come",
                "release_date": "2026-04-10",
                "popularity": 10,
            }
        ]

        match = select_best_movie_match(
            results,
            title="Ready or Not 2: Here I Come",
            release_year=2026,
        )

        self.assertIsNotNone(match)
        self.assertEqual(match["id"], 1)

class TMDBEnrichmentMappingTests(unittest.TestCase):
    def test_maps_details_into_taste_dna_shape(self):
        values = build_enrichment_values(
            {
                "original_title": "기생충",
                "overview": "A family story.",
                "runtime": 132,
                "original_language": "ko",
                "release_date": "2019-05-30",
                "genres": [{"id": 18, "name": "Drama"}],
                "keywords": {"keywords": [{"id": 1, "name": "class"}]},
                "credits": {
                    "cast": [{"id": 10, "name": "Actor"}],
                    "crew": [{"id": 20, "name": "Director", "job": "Director"}],
                },
                "production_countries": [{"iso_3166_1": "KR", "name": "South Korea"}],
                "poster_path": "/poster.jpg",
            }
        )

        self.assertEqual(values["runtime_minutes"], 132)
        self.assertEqual(values["release_date"].isoformat(), "2019-05-30")
        self.assertEqual(values["genres"][0]["name"], "Drama")
        self.assertEqual(values["keywords"][0]["name"], "class")
        self.assertEqual(values["credits"]["crew"][0]["job"], "Director")

    def test_flattens_only_requested_provider_region(self):
        rows = provider_rows_for_region(
            {
                "results": {
                    "DE": {
                        "link": "https://www.themoviedb.org/movie/1/watch?locale=DE",
                        "flatrate": [
                            {
                                "provider_id": 8,
                                "provider_name": "Netflix",
                                "logo_path": "/netflix.jpg",
                                "display_priority": 1,
                            }
                        ],
                    },
                    "US": {"flatrate": [{"provider_id": 9, "provider_name": "Other"}]},
                }
            },
            region="de",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["region"], "DE")
        self.assertEqual(rows[0]["provider_type"], "flatrate")
        self.assertTrue(rows[0]["logo_path"].endswith("/netflix.jpg"))

    def test_dry_run_selects_stale_movies_without_client_or_writes(self):
        stale = datetime.now(timezone.utc) - timedelta(days=1)
        session = FakeSelectionSession(
            [(1, "Arrival", 2016, None, None, stale, {}, None, None, None)],
        )

        stats = enrich_movies(session, None, region="DE", limit=1, dry_run=True)

        self.assertEqual(stats.selected, 1)
        self.assertTrue(stats.dry_run)
        self.assertTrue(session.rolled_back)

    def test_fresh_details_and_region_cache_are_skipped(self):
        fresh = datetime.now(timezone.utc) + timedelta(days=7)
        session = FakeSelectionSession(
            [
                (
                    1,
                    "Arrival",
                    2016,
                    329865,
                    1,
                    fresh,
                    {
                        "_spyboxd": {
                            "provider_region_expires_at": {"DE": fresh.isoformat()}
                        }
                    },
                    None,
                    None,
                    None,
                )
            ],
        )

        stats = enrich_movies(session, None, region="DE", dry_run=True)

        self.assertEqual(stats.selected, 0)
        self.assertTrue(session.rolled_back)

    def test_fresh_negative_lookup_is_skipped_until_expiry(self):
        now = datetime.now(timezone.utc)
        lookup_key = _tmdb_lookup_key("Unmatched Film", 2024, "en-US")
        session = FakeSelectionSession(
            [
                (
                    1,
                    "Unmatched Film",
                    2024,
                    None,
                    None,
                    None,
                    {},
                    now,
                    now + timedelta(days=30),
                    lookup_key,
                )
            ],
        )

        stats = enrich_movies(session, None, region="DE", dry_run=True)

        self.assertEqual(stats.selected, 0)
        self.assertTrue(session.rolled_back)

    def test_never_attempted_identity_precedes_expired_negative_lookup(self):
        now = datetime.now(timezone.utc)
        expired = now - timedelta(days=1)
        expired_lookup_key = _tmdb_lookup_key("Expired miss", 2023, "en-US")
        session = FakeSelectionSession(
            [
                (
                    1,
                    "Expired miss",
                    2023,
                    None,
                    None,
                    None,
                    {},
                    expired,
                    expired,
                    expired_lookup_key,
                ),
                (2, "Never attempted", 2024, None, None, None, {}, None, None, None),
            ],
        )

        candidates = _select_candidates(
            session,
            region="DE",
            now=now,
            refresh=False,
            limit=1,
            movie_ids=None,
            language="en-US",
        )

        self.assertEqual([candidate.movie_id for candidate in candidates], [2])

    def test_bounded_selection_prioritizes_missing_enrichment_and_tmdb_identity(self):
        stale = datetime.now(timezone.utc) - timedelta(days=1)
        session = FakeSelectionSession(
            [
                (1, "Stale cached", 2001, 101, 1, stale, {}, None, None, None),
                (2, "New import", 2002, 202, None, None, {}, None, None, None),
                (3, "Missing identity", 2003, None, 3, stale, {}, None, None, None),
            ],
        )

        candidates = _select_candidates(
            session,
            region="DE",
            now=datetime.now(timezone.utc),
            refresh=False,
            limit=2,
            movie_ids=None,
            language="en-US",
        )

        self.assertEqual([candidate.movie_id for candidate in candidates], [2, 3])

    def test_identity_conflict_is_reported_and_deferred_separately(self):
        session = FakeIdentityConflictSession(
            [
                (8713, "The Girlfriend", 2025, None, None, None, {}, None, None, None),
                (9000, "Definitely Missing", 2025, None, None, None, {}, None, None, None),
            ],
            [(1196348, 147, "The Girlfriend")],
        )
        client = FakeMatchingClient({"The Girlfriend": 1196348})

        with patch("services.tmdb_enrichment._persist_prepared") as persist:
            stats = enrich_movies(session, client, region="DE", batch_size=25)

        self.assertEqual(stats.selected, 2)
        self.assertEqual(stats.identity_conflicts, 1)
        self.assertEqual(stats.not_found, 1)
        self.assertEqual(stats.not_found_cached, 1)
        self.assertEqual(stats.identity_conflicts_cached, 1)
        self.assertEqual(stats.failed, 0)
        self.assertEqual(stats.enriched, 0)
        self.assertEqual(session.write_attempts, 2)
        persist.assert_not_called()
        self.assertIsNotNone(session.movies[8713].tmdb_lookup_expires_at)
        self.assertIsNotNone(session.movies[8713].tmdb_lookup_key)
        self.assertEqual(
            stats.identity_conflict_details,
            [
                {
                    "movie_id": 8713,
                    "title": "The Girlfriend",
                    "tmdb_id": 1196348,
                    "owner_movie_id": 147,
                    "owner_title": "The Girlfriend",
                    "reason": "tmdb_id_already_owned",
                }
            ],
        )
        self.assertEqual(stats.errors, [])

    def test_cached_identity_conflict_does_not_starve_later_candidate(self):
        rows = [
            (1, "Duplicate", 2025, None, None, None, {}, None, None, None),
            (2, "Later Film", 2024, None, None, None, {}, None, None, None),
        ]
        first_session = FakeIdentityConflictSession(
            rows,
            [(1196348, 147, "Existing Owner")],
        )
        client = FakeMatchingClient({"Duplicate": 1196348})

        first_stats = enrich_movies(
            first_session,
            client,
            region="DE",
            language="en-US",
            limit=1,
        )

        self.assertEqual(first_stats.identity_conflicts_cached, 1)
        deferred = first_session.movies[1]
        second_session = FakeSelectionSession(
            [
                (
                    1,
                    "Duplicate",
                    2025,
                    None,
                    None,
                    None,
                    {},
                    deferred.tmdb_lookup_attempted_at,
                    deferred.tmdb_lookup_expires_at,
                    deferred.tmdb_lookup_key,
                ),
                rows[1],
            ]
        )

        second_candidates = _select_candidates(
            second_session,
            region="DE",
            now=datetime.now(timezone.utc),
            refresh=False,
            limit=1,
            movie_ids=None,
            language="en-US",
        )

        self.assertEqual([candidate.movie_id for candidate in second_candidates], [2])

    def test_changed_year_or_language_bypasses_fresh_negative_cache(self):
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(days=30)
        stored_key = _tmdb_lookup_key("Unmatched Film", 2023, "en-US")
        cases = (
            ("corrected year", 2024, "en-US"),
            ("changed language", 2023, "fr-FR"),
        )

        for case, current_year, language in cases:
            with self.subTest(case=case):
                session = FakeSelectionSession(
                    [
                        (
                            1,
                            "Unmatched Film",
                            current_year,
                            None,
                            None,
                            None,
                            {},
                            now,
                            expiry,
                            stored_key,
                        )
                    ]
                )
                candidates = _select_candidates(
                    session,
                    region="DE",
                    now=now,
                    refresh=False,
                    limit=1,
                    movie_ids=None,
                    language=language,
                )
                self.assertEqual([candidate.movie_id for candidate in candidates], [1])

    def test_search_miss_cache_does_not_overwrite_concurrent_tmdb_identity(self):
        attempted_at = datetime.now(timezone.utc)
        movie = Movie(
            id=1,
            canonical_key="arrival-2016",
            title="Arrival",
            normalized_title="arrival",
            release_year=2016,
            tmdb_id=329865,
        )
        db = Mock()
        db.get.return_value = movie
        candidate = EnrichmentCandidate(
            movie_id=1,
            title="Arrival",
            release_year=2016,
            tmdb_id=None,
            needs_details=True,
            needs_providers=True,
        )

        persisted = _persist_lookup_deferral(
            db,
            candidate,
            attempted_at=attempted_at,
            expires_at=attempted_at + timedelta(days=30),
            lookup_key=_tmdb_lookup_key("Arrival", 2016, "en-US"),
        )

        self.assertFalse(persisted)
        self.assertIsNone(movie.tmdb_lookup_attempted_at)
        self.assertIsNone(movie.tmdb_lookup_expires_at)
        self.assertIsNone(movie.tmdb_lookup_key)
        db.flush.assert_not_called()

    def test_search_miss_cache_records_bounded_retry_window(self):
        attempted_at = datetime.now(timezone.utc)
        expires_at = attempted_at + timedelta(days=30)
        movie = Movie(
            id=2,
            canonical_key="unmatched-film-2024",
            title="Unmatched Film",
            normalized_title="unmatched film",
            release_year=2024,
        )
        db = Mock()
        db.get.return_value = movie
        candidate = EnrichmentCandidate(
            movie_id=2,
            title="Unmatched Film",
            release_year=2024,
            tmdb_id=None,
            needs_details=True,
            needs_providers=True,
        )

        lookup_key = _tmdb_lookup_key("Unmatched Film", 2024, "en-US")
        persisted = _persist_lookup_deferral(
            db,
            candidate,
            attempted_at=attempted_at,
            expires_at=expires_at,
            lookup_key=lookup_key,
        )

        self.assertTrue(persisted)
        self.assertEqual(movie.tmdb_lookup_attempted_at, attempted_at)
        self.assertEqual(movie.tmdb_lookup_expires_at, expires_at)
        self.assertEqual(movie.tmdb_lookup_key, lookup_key)
        db.flush.assert_called_once_with()

    def test_request_credentials_do_not_reach_enrichment_error_json(self):
        api_key = "persisted-secret-v3-key"
        bearer_token = "logged-secret-bearer-token"
        request_error = requests.RequestException(
            "timeout at "
            f"https://api.themoviedb.org/3/search/movie?api_key={api_key} "
            f"Authorization=Bearer%20{bearer_token}"
        )
        http_session = FakeHTTPSession([request_error])
        client = TMDBClient(api_key=api_key, session=http_session, max_retries=0)
        db = FakeSelectionSession(
            [(1, "Arrival", 2016, None, None, None, {}, None, None, None)],
        )

        stats = enrich_movies(db, client, region="DE", batch_size=1)
        cli_json = json.dumps(stats.to_dict())

        self.assertEqual(stats.failed, 1)
        self.assertEqual(db.commits, 1)
        self.assertIn("upstream service", cli_json)
        for secret in (api_key, bearer_token):
            self.assertNotIn(secret, cli_json)


if __name__ == "__main__":
    unittest.main()


class RuntimeAbsenceTests(unittest.TestCase):
    """TMDB writes 0 for a runtime nobody has filled in.

    Stored as 0 it reads as a known length everywhere downstream: 55 rows
    arrived that way and once put 27 films in an "Under 90 min" taste bucket on
    the strength of runtimes nobody had recorded.
    """

    def _runtime(self, value):
        return build_enrichment_values({"runtime": value})["runtime_minutes"]

    def test_a_zero_runtime_is_stored_as_unknown(self):
        self.assertIsNone(self._runtime(0))

    def test_a_missing_runtime_is_unknown(self):
        self.assertIsNone(self._runtime(None))

    def test_a_negative_runtime_is_unknown(self):
        self.assertIsNone(self._runtime(-5))

    def test_a_real_runtime_survives(self):
        self.assertEqual(self._runtime(132), 132)
