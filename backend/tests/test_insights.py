from __future__ import annotations

from datetime import date, datetime, timezone
import unittest
from unittest.mock import MagicMock

from sqlalchemy import create_engine, inspect as sqlalchemy_inspect
from sqlalchemy.orm import sessionmaker

from backend.database.models import (
    Movie,
    MovieEnrichment,
    MovieWatchProvider,
    Profile,
    ProfileSync,
    Review,
    SyncDataset,
)
from database.models import (
    Base as ServiceBase,
    Movie as ServiceMovie,
    MovieEnrichment as ServiceMovieEnrichment,
    Profile as ServiceProfile,
    ProfileFilm as ServiceProfileFilm,
    ProfileSync as ServiceProfileSync,
    SyncDataset as ServiceSyncDataset,
)
from backend.services.insights import (
    EventRow,
    InsightsService,
    ProviderAvailability,
    StateRow,
    _as_string_list,
    _cached_provider_region_codes,
    _merge_provider_availability,
    _normalize_availability_filter,
    _pearson,
    _provider_availability_reason,
    _provider_for_availability_reason,
    _provider_matches_availability,
    _providers_from_cached_tmdb,
)


def event(
    *,
    event_id: int,
    profile_id: int,
    username: str,
    watched_date: date,
    movie: Movie,
    rewatch: bool = False,
    rating: float | None = 4.0,
    liked: bool = False,
) -> EventRow:
    return EventRow(
        id=event_id,
        profile_id=profile_id,
        username=username,
        movie_id=movie.id,
        watched_date=watched_date,
        rating=rating,
        liked=liked,
        rewatch=rewatch,
        tags=[],
        source_kind="diary_csv",
        movie=movie,
    )


class InsightCalculationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = InsightsService(db=None)  # Pure calculation helpers do not touch the DB.
        self.movie = Movie(
            id=10,
            canonical_key="letterboxd:test-film",
            title="Test Film",
            normalized_title="test film",
            release_year=2026,
            letterboxd_slug="test-film",
        )

    def test_same_profile_rewatches_do_not_create_a_group_signal(self) -> None:
        rows = [
            event(
                event_id=1,
                profile_id=1,
                username="left",
                watched_date=date(2026, 7, 1),
                movie=self.movie,
            ),
            event(
                event_id=2,
                profile_id=1,
                username="left",
                watched_date=date(2026, 7, 1),
                movie=self.movie,
                rewatch=True,
            ),
        ]

        self.assertEqual(self.service._matched_events(rows, gap_days=1), [])

    def test_duplicate_events_preserve_rewatch_evidence_without_inflating_pairs(self) -> None:
        rows = [
            event(
                event_id=1,
                profile_id=1,
                username="left",
                watched_date=date(2026, 7, 1),
                movie=self.movie,
            ),
            event(
                event_id=2,
                profile_id=1,
                username="left",
                watched_date=date(2026, 7, 1),
                movie=self.movie,
                rewatch=True,
            ),
            event(
                event_id=3,
                profile_id=2,
                username="right",
                watched_date=date(2026, 7, 1),
                movie=self.movie,
            ),
        ]

        matches = self.service._matched_events(rows, gap_days=0)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["pair_count"], 1)
        self.assertEqual(matches[0]["profile_count"], 2)
        self.assertEqual(matches[0]["rewatch_count"], 1)

    def test_one_day_direction_is_retained_as_a_gap_event(self) -> None:
        rows = [
            event(
                event_id=1,
                profile_id=1,
                username="leader",
                watched_date=date(2026, 7, 1),
                movie=self.movie,
            ),
            event(
                event_id=2,
                profile_id=2,
                username="follower",
                watched_date=date(2026, 7, 2),
                movie=self.movie,
            ),
        ]

        matches = self.service._matched_events(rows, gap_days=1)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["day_gap"], 1)
        self.assertEqual(matches[0]["profiles"], ["follower", "leader"])

    def test_cross_date_pair_count_uses_unique_profile_pairs(self) -> None:
        rows = [
            event(
                event_id=1,
                profile_id=1,
                username="left",
                watched_date=date(2026, 7, 1),
                movie=self.movie,
            ),
            event(
                event_id=2,
                profile_id=2,
                username="right",
                watched_date=date(2026, 7, 1),
                movie=self.movie,
            ),
            event(
                event_id=3,
                profile_id=1,
                username="left",
                watched_date=date(2026, 7, 2),
                movie=self.movie,
                rewatch=True,
            ),
            event(
                event_id=4,
                profile_id=2,
                username="right",
                watched_date=date(2026, 7, 2),
                movie=self.movie,
                rewatch=True,
            ),
        ]

        matches = self.service._matched_events(rows, gap_days=1)
        cross_date = next(match for match in matches if match["day_gap"] == 1)

        self.assertEqual(cross_date["pair_count"], 1)
        self.assertEqual(cross_date["profile_count"], 2)

    def test_rewatch_echoes_classifies_first_known_without_claiming_first_ever(self) -> None:
        profiles = [
            Profile(id=1, username="leader", is_active=True, scraping_status="completed"),
            Profile(id=2, username="follower", is_active=True, scraping_status="completed"),
            Profile(id=3, username="also-new", is_active=True, scraping_status="completed"),
        ]
        rows = [
            event(
                event_id=1,
                profile_id=1,
                username="leader",
                watched_date=date(2026, 7, 1),
                movie=self.movie,
            ),
            event(
                event_id=2,
                profile_id=1,
                username="leader",
                watched_date=date(2026, 7, 10),
                movie=self.movie,
                rewatch=True,
            ),
            event(
                event_id=3,
                profile_id=2,
                username="follower",
                watched_date=date(2026, 7, 11),
                movie=self.movie,
            ),
            event(
                event_id=4,
                profile_id=3,
                username="also-new",
                watched_date=date(2026, 7, 11),
                movie=self.movie,
            ),
        ]
        self.service._resolve_profiles = lambda *_args, **_kwargs: profiles
        self.service._event_rows = lambda *_args, **_kwargs: rows
        self.service._state_rows = lambda *_args, **_kwargs: []
        self.service._feature_coverage = lambda *_args, **_kwargs: {
            "status": "ready",
            "score": 100,
            "dated_watch_events": len(rows),
            "total_watch_events": len(rows),
            "blockers": [],
            "warnings": [],
            "last_updated": None,
        }

        payload = self.service.rewatch_echoes(
            [profile.username for profile in profiles],
            gap_days=1,
            limit=10,
        )

        self.assertEqual(payload["summary"]["echoes"], 2)
        self.assertTrue(
            all(item["pattern"] == "first_known_plus_rewatch" for item in payload["echoes"])
        )
        self.assertEqual(
            [item["echo_id"] for item in payload["echoes"]],
            ["a08cdc0947e45d34", "d4ae0efd02a76ec9"],
        )
        self.assertTrue(
            all(len(item["echo_id"]) == 16 for item in payload["echoes"])
        )
        for echo in payload["echoes"]:
            by_kind = {participant["watch_kind"]: participant for participant in echo["participants"]}
            self.assertEqual(
                by_kind["rewatch"]["classification_basis"],
                "letterboxd_rewatch_flag",
            )
            self.assertEqual(
                by_kind["first_known_watch"]["classification_basis"],
                "earliest_observed_unmarked_event",
            )

    def test_taste_timeline_groups_december_into_following_winter(self) -> None:
        profiles = [
            Profile(id=1, username="left", is_active=True, scraping_status="completed"),
            Profile(id=2, username="right", is_active=True, scraping_status="completed"),
        ]
        second_movie = Movie(
            id=11,
            canonical_key="letterboxd:second-film",
            title="Second Film",
            normalized_title="second film",
            release_year=2020,
            letterboxd_slug="second-film",
        )
        enrichments = {
            self.movie.id: MovieEnrichment(movie_id=self.movie.id, genres=[{"name": "Drama"}]),
            second_movie.id: MovieEnrichment(movie_id=second_movie.id, genres=[{"name": "Comedy"}]),
        }
        states = [
            StateRow(
                profile_id=profile.id,
                username=profile.username,
                movie_id=movie.id,
                rating=rating,
                liked=False,
                tags=[],
                first_watched_date=None,
                latest_watched_date=None,
                watch_count=2,
                rewatch_count=0,
                movie=movie,
                enrichment=enrichments[movie.id],
            )
            for profile, movie, rating in [
                (profiles[0], self.movie, 4.0),
                (profiles[1], second_movie, 2.0),
            ]
        ]
        rows = [
            event(
                event_id=1,
                profile_id=1,
                username="left",
                watched_date=date(2025, 12, 31),
                movie=self.movie,
                rating=4.0,
            ),
            event(
                event_id=2,
                profile_id=2,
                username="right",
                watched_date=date(2026, 1, 1),
                movie=second_movie,
                rating=2.0,
            ),
        ]
        self.service._resolve_profiles = lambda *_args, **_kwargs: profiles
        self.service._state_rows = lambda *_args, **_kwargs: states
        self.service._event_rows = lambda *_args, **_kwargs: rows
        self.service._feature_coverage = lambda *_args, **_kwargs: {
            "status": "partial",
            "score": 75,
            "dated_watch_events": len(rows),
            "total_watch_events": 4,
            "blockers": [],
            "warnings": [],
            "last_updated": None,
        }

        payload = self.service.taste_timeline(
            ["left", "right"],
            dimensions=["genre", "decade"],
            from_year=None,
            to_year=None,
            trait_limit=5,
            year_limit=10,
        )

        self.assertEqual([period["year"] for period in payload["yearly"]], [2025, 2026])
        self.assertEqual(len(payload["seasonal"]), 1)
        self.assertEqual(payload["seasonal"][0]["key"], "2026-winter")
        self.assertEqual(payload["seasonal"][0]["watch_events"], 2)
        self.assertEqual(payload["summary"]["date_coverage_ratio"], 0.5)
        self.assertEqual(payload["summary"]["undated_known_watches"], 2)

    def test_list_mission_without_list_id_returns_discovery_payload(self) -> None:
        profiles = [
            Profile(id=1, username="left", is_active=True, scraping_status="completed"),
            Profile(id=2, username="right", is_active=True, scraping_status="completed"),
        ]
        available = [
            {"id": 7, "owner": "left", "name": "Mission", "movie_count": 10, "is_ranked": True}
        ]
        self.service._resolve_profiles = lambda *_args, **_kwargs: profiles
        self.service._available_public_lists = lambda *_args, **_kwargs: available

        with self.assertRaisesRegex(ValueError, "list_id is required") as raised:
            self.service.watch_together(
                ["left", "right"],
                mode="list_mission",
                list_id=None,
                region="ALL",
                max_runtime=None,
                genre=None,
                availability=None,
                limit=10,
            )

        self.assertEqual(raised.exception.detail["available_lists"], available)

    def test_public_list_summary_has_stable_frontend_shape(self) -> None:
        payload = self.service._public_list_summary(
            list_id=7,
            owner="left",
            name="Mission",
            movie_count=10,
            is_ranked=True,
        )

        self.assertEqual(
            payload,
            {"id": 7, "owner": "left", "name": "Mission", "movie_count": 10, "is_ranked": True},
        )

    def test_comparison_with_undated_profiles_does_not_crash(self) -> None:
        states = [
            StateRow(
                profile_id=profile_id,
                username=username,
                movie_id=self.movie.id,
                rating=rating,
                liked=False,
                tags=[],
                first_watched_date=None,
                latest_watched_date=None,
                watch_count=1,
                rewatch_count=0,
                movie=self.movie,
                enrichment=None,
            )
            for profile_id, username, rating in [
                (1, "left", 4.0),
                (2, "right", 3.5),
            ]
        ]

        comparison = self.service._comparison(self.movie, states, [], {})

        self.assertIsNone(comparison["minimum_watch_gap_days"])
        self.assertEqual(
            [observation["watched_dates"] for observation in comparison["observations"]],
            [[], []],
        )

    def test_comparison_exposes_authoritative_review_spoiler_metadata(self) -> None:
        states = [
            StateRow(
                profile_id=profile_id,
                username=username,
                movie_id=self.movie.id,
                rating=rating,
                liked=False,
                tags=[],
                first_watched_date=None,
                latest_watched_date=None,
                watch_count=1,
                rewatch_count=0,
                movie=self.movie,
                enrichment=None,
            )
            for profile_id, username, rating in [
                (1, "reviewer", 4.5),
                (2, "viewer", 4.0),
            ]
        ]
        review = Review(
            profile_id=1,
            movie_id=self.movie.id,
            movie_title=self.movie.title,
            movie_year=self.movie.release_year,
            review_text="The actual spoiler review.",
            contains_spoilers=True,
            tags=[],
        )

        comparison = self.service._comparison(
            self.movie,
            states,
            [],
            {(1, self.movie.id): review},
        )

        observations = {
            observation["username"]: observation
            for observation in comparison["observations"]
        }
        self.assertTrue(observations["reviewer"]["contains_spoilers"])
        self.assertEqual(
            observations["reviewer"]["review_text"],
            "The actual spoiler review.",
        )
        self.assertFalse(observations["viewer"]["contains_spoilers"])

    def test_calendar_intensity_uses_frontend_levels_zero_through_four(self) -> None:
        profiles = [
            type("ProfileRef", (), {"id": value, "username": username})()
            for value, username in [(1, "one"), (2, "two"), (3, "three")]
        ]
        rows = [
            event(
                event_id=index,
                profile_id=profile.id,
                username=profile.username,
                watched_date=date(2026, 7, 1),
                movie=self.movie,
            )
            for index, profile in enumerate(profiles, start=1)
        ] + [
            event(
                event_id=4,
                profile_id=1,
                username="one",
                watched_date=date(2026, 7, 3),
                movie=self.movie,
            ),
            event(
                event_id=5,
                profile_id=2,
                username="two",
                watched_date=date(2026, 7, 3),
                movie=self.movie,
            ),
        ]
        self.service._resolve_profiles = lambda *_args, **_kwargs: profiles
        self.service._event_rows = lambda *_args, **_kwargs: rows
        self.service._feature_coverage = lambda *_args, **_kwargs: {
            "status": "ready",
            "score": 100,
            "dated_watch_events": len(rows),
            "total_watch_events": len(rows),
            "blockers": [],
            "warnings": [],
            "last_updated": None,
        }

        payload = self.service.signal_calendar(
            ["one", "two", "three"],
            gap_days=0,
            from_date=date(2026, 7, 1),
            to_date=date(2026, 7, 3),
        )

        self.assertEqual(
            {bucket["date"]: bucket["intensity"] for bucket in payload["buckets"]},
            {"2026-07-01": 4, "2026-07-03": 2},
        )

    def test_signal_calendar_uses_stable_sha256_ui_event_ids(self) -> None:
        profiles = [
            type("ProfileRef", (), {"id": value, "username": username})()
            for value, username in [(1, "one"), (2, "two")]
        ]
        rows = [
            event(
                event_id=index,
                profile_id=profile.id,
                username=profile.username,
                watched_date=date(2026, 7, 1),
                movie=self.movie,
            )
            for index, profile in enumerate(profiles, start=1)
        ]
        self.service._resolve_profiles = lambda *_args, **_kwargs: profiles
        self.service._event_rows = lambda *_args, **_kwargs: rows
        self.service._feature_coverage = lambda *_args, **_kwargs: {
            "status": "ready",
            "score": 100,
            "dated_watch_events": len(rows),
            "total_watch_events": len(rows),
            "blockers": [],
            "warnings": [],
            "last_updated": None,
        }

        first = self.service.signal_calendar(
            ["one", "two"],
            gap_days=0,
            from_date=date(2026, 7, 1),
            to_date=date(2026, 7, 1),
        )
        second = self.service.signal_calendar(
            ["one", "two"],
            gap_days=0,
            from_date=date(2026, 7, 1),
            to_date=date(2026, 7, 1),
        )

        event_id = first["events"][0]["event_id"]
        self.assertEqual(event_id, "b59e064945895370")
        self.assertEqual(second["events"][0]["event_id"], event_id)
        self.assertRegex(event_id, r"^[0-9a-f]{16}$")

    def test_streaming_availability_maps_to_tmdb_flatrate(self) -> None:
        provider = MovieWatchProvider(
            provider_id=8,
            provider_name="Netflix",
            provider_type="flatrate",
            region="DE",
        )

        self.assertTrue(_provider_matches_availability(provider, "streaming"))
        self.assertTrue(_provider_matches_availability(provider, "netflix"))
        self.assertFalse(_provider_matches_availability(provider, "rent"))

    def test_movie_summary_prefers_tmdb_poster_over_letterboxd_placeholder(self) -> None:
        self.movie.poster_url = "https://s.ltrbxd.com/static/img/empty-poster-70.png"
        enrichment = MovieEnrichment(movie_id=self.movie.id, poster_path="/poster.jpg")

        summary = self.service._movie_summary(self.movie, enrichment)

        self.assertEqual(
            summary["poster_url"],
            "https://image.tmdb.org/t/p/w500/poster.jpg",
        )

    def test_movie_summary_suppresses_unusable_letterboxd_poster_urls(self) -> None:
        unusable_urls = [
            "https://s.ltrbxd.com/static/img/empty-poster-70.png",
            "https://letterboxd.com/film/test-film/image-150/",
            "/film/test-film/image-150/",
        ]

        for poster_url in unusable_urls:
            with self.subTest(poster_url=poster_url):
                self.movie.poster_url = poster_url
                self.assertIsNone(self.service._movie_summary(self.movie)["poster_url"])

    def test_movie_summary_preserves_usable_imported_poster(self) -> None:
        self.movie.poster_url = "https://a.ltrbxd.com/resized/film-poster/123/poster.jpg"

        summary = self.service._movie_summary(self.movie)

        self.assertEqual(summary["poster_url"], self.movie.poster_url)

    def test_comparison_movie_summary_uses_tmdb_poster_enrichment(self) -> None:
        enrichment = MovieEnrichment(movie_id=self.movie.id, poster_path="/tmdb-poster.jpg")
        row = StateRow(
            profile_id=1,
            username="viewer",
            movie_id=self.movie.id,
            rating=4.0,
            liked=True,
            tags=[],
            first_watched_date=None,
            latest_watched_date=None,
            watch_count=1,
            rewatch_count=0,
            movie=self.movie,
            enrichment=enrichment,
        )

        comparison = self.service._comparison(self.movie, [row], [], {})

        self.assertTrue(comparison["movie"]["poster_url"].endswith("/tmdb-poster.jpg"))

    def test_availability_reason_uses_provider_matching_requested_type(self) -> None:
        providers = [
            MovieWatchProvider(
                provider_id=2,
                provider_name="Apple TV Store",
                provider_type="rent",
                region="DE",
            ),
            MovieWatchProvider(
                provider_id=3,
                provider_name="Amazon Video",
                provider_type="buy",
                region="DE",
            ),
            MovieWatchProvider(
                provider_id=8,
                provider_name="Netflix",
                provider_type="flatrate",
                region="DE",
            ),
        ]

        expected_names = {
            "streaming": "Netflix",
            "rent": "Apple TV Store",
            "buy": "Amazon Video",
        }
        for availability, expected_name in expected_names.items():
            with self.subTest(availability=availability):
                provider = _provider_for_availability_reason(providers, availability)
                self.assertIsNotNone(provider)
                self.assertEqual(provider.provider_name, expected_name)

        self.assertEqual(
            _provider_for_availability_reason(providers, None).provider_name,
            "Apple TV Store",
        )
        self.assertEqual(len(providers), 3)

    def test_any_availability_does_not_filter_unknown_provider_data(self) -> None:
        for value in (None, "", "all", "ALL", "any", " Any "):
            with self.subTest(value=value):
                self.assertIsNone(_normalize_availability_filter(value))

        self.assertEqual(_normalize_availability_filter("streaming"), "streaming")

    def test_cached_provider_payload_supports_country_and_worldwide_scopes(self) -> None:
        raw_payload = {
            "watch_providers": {
                "results": {
                    "DE": {
                        "flatrate": [
                            {
                                "provider_id": 8,
                                "provider_name": "Netflix",
                                "logo_path": "/netflix.jpg",
                                "display_priority": 2,
                            }
                        ]
                    },
                    "US": {
                        "flatrate": [
                            {
                                "provider_id": 8,
                                "provider_name": "Netflix",
                                "logo_path": "/netflix.jpg",
                                "display_priority": 1,
                            }
                        ],
                        "rent": [
                            {
                                "provider_id": 2,
                                "provider_name": "Apple TV Store",
                                "logo_path": "/apple.jpg",
                                "display_priority": 3,
                            }
                        ],
                        "free": [
                            {
                                "provider_id": 99,
                                "provider_name": "Unsupported Free Provider",
                            }
                        ],
                    },
                }
            }
        }

        germany = _providers_from_cached_tmdb(10, raw_payload, region="DE")
        united_states = _providers_from_cached_tmdb(10, raw_payload, region="US")
        worldwide = _providers_from_cached_tmdb(10, raw_payload, region="ALL")

        self.assertEqual([(row.provider_name, row.regions) for row in germany], [
            ("Netflix", ("DE",)),
        ])
        self.assertEqual(
            {(row.provider_name, row.provider_type, row.regions) for row in united_states},
            {
                ("Netflix", "flatrate", ("US",)),
                ("Apple TV Store", "rent", ("US",)),
            },
        )
        self.assertEqual(len(worldwide), 3)
        self.assertEqual(_cached_provider_region_codes(raw_payload), ["DE", "US"])
        self.assertTrue(germany[0].logo_path.endswith("/netflix.jpg"))

    def test_worldwide_provider_merge_deduplicates_names_and_retains_countries(self) -> None:
        cached = [
            ProviderAvailability(
                movie_id=10,
                provider_id=8,
                provider_name="Netflix",
                provider_type="flatrate",
                logo_path="https://image.tmdb.org/t/p/original/netflix.jpg",
                display_priority=2,
                regions=("DE",),
            ),
            ProviderAvailability(
                movie_id=10,
                provider_id=8,
                provider_name="Netflix",
                provider_type="flatrate",
                logo_path="https://image.tmdb.org/t/p/original/netflix.jpg",
                display_priority=1,
                regions=("US",),
            ),
        ]
        stored = [
            MovieWatchProvider(
                movie_id=10,
                provider_id=8,
                provider_name="Netflix",
                provider_type="flatrate",
                logo_path="https://image.tmdb.org/t/p/original/netflix.jpg",
                display_priority=3,
                region="GB",
            )
        ]

        merged = _merge_provider_availability(10, stored, cached)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].regions, ("DE", "GB", "US"))
        self.assertEqual(merged[0].display_priority, 1)
        self.assertEqual(
            _provider_availability_reason(merged[0], "ALL"),
            "Available from Netflix in 3 countries",
        )
        self.assertEqual(
            _provider_availability_reason(merged[0], "DE"),
            "Available from Netflix in DE",
        )

    def test_partial_surface_score_never_claims_full_coverage(self) -> None:
        score = self.service._surface_score({"status": "partial", "ratio": 1.0})

        self.assertLess(score, 1.0)

    def test_zero_expected_rows_has_no_capture_ratio(self) -> None:
        surface = self.service._surface(
            "watchlist",
            captured=0,
            expected=0,
            last_updated=None,
            authoritative=True,
        )

        self.assertEqual(surface["status"], "complete")
        self.assertIsNone(surface["ratio"])
        self.assertEqual(surface["availability_status"], "available")
        self.assertIsNone(surface["unavailable_reason"])

    def test_private_surface_exposes_unavailability_without_perfect_ratio(self) -> None:
        surface = self.service._surface(
            "watchlist",
            captured=0,
            expected=0,
            last_updated=None,
            authoritative=False,
            unavailable_reason="forbidden/private",
        )

        self.assertEqual(surface["status"], "missing")
        self.assertIsNone(surface["ratio"])
        self.assertEqual(surface["availability_status"], "unavailable")
        self.assertEqual(surface["unavailable_reason"], "forbidden/private")
        self.assertIn(
            "Watchlist source unavailable (forbidden/private).",
            surface["warnings"],
        )

    def test_coverage_payload_carries_private_watchlist_reason_from_latest_sync(self) -> None:
        db = MagicMock()
        query = db.query.return_value
        query.filter.return_value = query
        query.group_by.return_value = query
        query.all.return_value = []
        service = InsightsService(db)
        profile = Profile(id=1, username="private-profile")
        sync = ProfileSync(
            id=1,
            profile_id=1,
            source_kind="letterboxd_html",
            source_fingerprint="test",
            importer_version="test",
            status="completed",
            coverage={"unavailable_datasets": {"watchlist": "forbidden/private"}},
        )
        watchlist_dataset = SyncDataset(
            profile_sync_id=1,
            dataset_name="watchlist",
            source_row_count=0,
            imported_row_count=0,
            is_authoritative=False,
            metadata_payload={
                "source_present": False,
                "unavailable_reason": "forbidden/private",
            },
        )
        service._latest_sync_context = lambda _profiles: {
            profile.id: (sync, {"watchlist": watchlist_dataset})
        }
        service._state_rows = lambda _profiles, **_kwargs: []

        payload = service._coverage_payload([profile], events=[])
        watchlist = next(
            surface
            for surface in payload["profiles"][0]["surfaces"]
            if surface["surface"] == "watchlist"
        )

        self.assertEqual(watchlist["availability_status"], "unavailable")
        self.assertEqual(watchlist["unavailable_reason"], "forbidden/private")
        self.assertIsNone(watchlist["ratio"])

    def test_incremental_rss_sync_does_not_replace_authoritative_coverage_context(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        ServiceBase.metadata.create_all(
            engine,
            tables=[
                ServiceProfileSync.__table__,
                ServiceProfile.__table__,
                ServiceSyncDataset.__table__,
            ],
        )
        db = sessionmaker(bind=engine)()
        try:
            profile = ServiceProfile(id=1, username="viewer", scraping_status="completed")
            baseline = ServiceProfileSync(
                id=10,
                profile_id=profile.id,
                source_kind="full_html_upload",
                source_fingerprint="baseline",
                importer_version="test",
                status="completed",
                completed_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
                manifest={},
                coverage={},
                stats={},
            )
            incremental = ServiceProfileSync(
                id=11,
                profile_id=profile.id,
                source_kind="rss_incremental",
                source_fingerprint="rss:changed",
                importer_version="test",
                status="completed",
                completed_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
                manifest={},
                coverage={},
                stats={},
            )
            db.add_all(
                [
                    profile,
                    baseline,
                    incremental,
                    ServiceSyncDataset(
                        id=100,
                        profile_sync_id=baseline.id,
                        dataset_name="films",
                        source_row_count=100,
                        imported_row_count=100,
                        is_authoritative=True,
                        metadata_payload={},
                    ),
                    ServiceSyncDataset(
                        id=101,
                        profile_sync_id=incremental.id,
                        dataset_name="diary",
                        source_row_count=1,
                        imported_row_count=1,
                        is_authoritative=False,
                        metadata_payload={"source": "rss"},
                    ),
                ]
            )
            db.commit()

            sync, datasets = InsightsService(db)._latest_sync_context([profile])[profile.id]

            self.assertEqual(sync.id, baseline.id)
            self.assertEqual(set(datasets), {"films"})
            self.assertTrue(datasets["films"].is_authoritative)
        finally:
            db.close()
            engine.dispose()

    def test_lightweight_state_rows_defer_large_enrichment_payloads(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        ServiceBase.metadata.create_all(
            engine,
            tables=[
                ServiceProfile.__table__,
                ServiceProfileSync.__table__,
                ServiceMovie.__table__,
                ServiceProfileFilm.__table__,
                ServiceMovieEnrichment.__table__,
            ],
        )
        db = sessionmaker(bind=engine)()
        try:
            profile = ServiceProfile(id=1, username="viewer")
            movie = ServiceMovie(
                id=10,
                canonical_key="letterboxd:test-film",
                title="Test Film",
                normalized_title="test film",
            )
            profile_film = ServiceProfileFilm(
                id=20,
                profile_id=profile.id,
                movie_id=movie.id,
                rating=4.0,
                is_liked=False,
                tags=[],
                watch_count=1,
                rewatch_count=0,
            )
            enrichment = ServiceMovieEnrichment(
                movie_id=movie.id,
                poster_path="/poster.jpg",
                genres=["Drama"],
                raw_payload={"large": "payload" * 1_000},
            )
            db.add_all([profile, movie, profile_film, enrichment])
            db.commit()
            db.expunge_all()

            stored_profile = db.query(ServiceProfile).filter_by(id=1).one()
            row = InsightsService(db)._state_rows(
                [stored_profile],
                lightweight_enrichment=True,
            )[0]

            self.assertEqual(row.enrichment.poster_path, "/poster.jpg")
            self.assertIn("raw_payload", sqlalchemy_inspect(row.enrichment).unloaded)
            self.assertIn("credits", sqlalchemy_inspect(row.enrichment).unloaded)

            db.expunge_all()
            stored_profile = db.query(ServiceProfile).filter_by(id=1).one()
            analytical_row = InsightsService(db)._state_rows(
                [stored_profile],
                analytical_enrichment=True,
            )[0]

            self.assertEqual(analytical_row.enrichment.genres, ["Drama"])
            self.assertNotIn("credits", sqlalchemy_inspect(analytical_row.enrichment).unloaded)
            self.assertIn("raw_payload", sqlalchemy_inspect(analytical_row.enrichment).unloaded)
            self.assertIn("overview", sqlalchemy_inspect(analytical_row.enrichment).unloaded)
        finally:
            db.close()
            engine.dispose()

    def test_metadata_helpers_accept_tmdb_dict_arrays(self) -> None:
        self.assertEqual(
            _as_string_list([{"id": 18, "name": "Drama"}, {"name": "Drama"}, "Comedy"]),
            ["Drama", "Comedy"],
        )
        self.assertAlmostEqual(_pearson([1, 2, 3], [2, 4, 6]), 1.0)
        self.assertIsNone(_pearson([1], [1]))


if __name__ == "__main__":
    unittest.main()
