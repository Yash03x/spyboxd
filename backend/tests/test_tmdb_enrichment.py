from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.tmdb_client import (
    DETAIL_APPEND_ENDPOINTS,
    TMDBClient,
    TMDBConfigurationError,
    select_best_movie_match,
)
from services.tmdb_enrichment import (
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
        return self.responses.pop(0)


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

    def query(self, *entities):
        self.query_count += 1
        return self.movie_query if self.query_count == 1 else self.provider_query

    def rollback(self):
        self.rolled_back = True


class FakeIdentityConflictSession:
    def __init__(self, movie_rows, owner_rows):
        self.query_results = [movie_rows, [], owner_rows]
        self.query_count = 0
        self.rolled_back = False
        self.commits = 0
        self.write_attempts = 0

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
        raise AssertionError("identity conflicts must be skipped before writes")


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
            [(1, "Arrival", 2016, None, stale, {})],
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
                    fresh,
                    {
                        "_spyboxd": {
                            "provider_region_expires_at": {"DE": fresh.isoformat()}
                        }
                    },
                )
            ],
        )

        stats = enrich_movies(session, None, region="DE", dry_run=True)

        self.assertEqual(stats.selected, 0)
        self.assertTrue(session.rolled_back)

    def test_identity_conflict_is_reported_and_skipped_before_any_write(self):
        session = FakeIdentityConflictSession(
            [
                (8713, "The Girlfriend", 2025, None, None, {}),
                (9000, "Definitely Missing", 2025, None, None, {}),
            ],
            [(1196348, 147, "The Girlfriend")],
        )
        client = FakeMatchingClient({"The Girlfriend": 1196348})

        with patch("services.tmdb_enrichment._persist_prepared") as persist:
            stats = enrich_movies(session, client, region="DE", batch_size=25)

        self.assertEqual(stats.selected, 2)
        self.assertEqual(stats.identity_conflicts, 1)
        self.assertEqual(stats.not_found, 1)
        self.assertEqual(stats.failed, 0)
        self.assertEqual(stats.enriched, 0)
        self.assertEqual(session.write_attempts, 0)
        persist.assert_not_called()
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


if __name__ == "__main__":
    unittest.main()
