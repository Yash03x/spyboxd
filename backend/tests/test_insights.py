from __future__ import annotations

from datetime import date, datetime, timezone
import unittest
from unittest.mock import MagicMock

from sqlalchemy import create_engine, event as sqlalchemy_event, inspect as sqlalchemy_inspect
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
    ProfileFollowEdge as ServiceProfileFollowEdge,
    ProfileSync as ServiceProfileSync,
    SyncDataset as ServiceSyncDataset,
)
from backend.services.insights import (
    EventRow,
    FollowGraph,
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
    logged_date: date | None = None,
) -> EventRow:
    return EventRow(
        id=event_id,
        profile_id=profile_id,
        username=username,
        movie_id=movie.id,
        watched_date=watched_date,
        logged_date=logged_date,
        rating=rating,
        liked=liked,
        rewatch=rewatch,
        tags=[],
        source_kind="diary_csv",
        movie=movie,
    )


def follow_graph(
    profiles,
    *,
    following=(),
    followers=(),
    authoritative_following=(),
    authoritative_followers=(),
) -> FollowGraph:
    """Build a graph directly so annotation logic is testable without a session."""
    return FollowGraph(
        active_following=frozenset(following),
        active_followers=frozenset(followers),
        authoritative_following=frozenset(authoritative_following),
        authoritative_followers=frozenset(authoritative_followers),
        normalized_username_by_profile_id={
            profile.id: profile.username.casefold() for profile in profiles
        },
        username_by_profile_id={profile.id: profile.username for profile in profiles},
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
            letterboxd_url="https://letterboxd.com/film/test-film/",
        )

    def test_movie_summary_includes_canonical_letterboxd_identity(self) -> None:
        summary = self.service._movie_summary(self.movie)

        self.assertEqual(summary["letterboxd_slug"], "test-film")
        self.assertEqual(
            summary["letterboxd_url"],
            "https://letterboxd.com/film/test-film/",
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

    def test_rewatch_echoes_carry_the_follow_reading_and_its_coverage(self) -> None:
        profiles = [
            Profile(id=1, username="leader", is_active=True, scraping_status="completed"),
            Profile(id=2, username="follower", is_active=True, scraping_status="completed"),
        ]
        rows = [
            event(
                event_id=1,
                profile_id=1,
                username="leader",
                watched_date=date(2026, 7, 10),
                movie=self.movie,
                rewatch=True,
            ),
            event(
                event_id=2,
                profile_id=2,
                username="follower",
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
        self.service._follow_graph = lambda _profiles: follow_graph(
            profiles,
            following=[(2, "leader")],
            authoritative_following=[2],
        )

        payload = self.service.rewatch_echoes(
            [profile.username for profile in profiles],
            gap_days=1,
            limit=10,
        )

        echo = payload["echoes"][0]
        self.assertTrue(echo["follows_earlier_watcher"])
        self.assertTrue(echo["follow_relationship"]["b_follows_a"])
        self.assertEqual(echo["follow_relationship"]["earlier_watcher"], "leader")
        self.assertEqual(payload["follow_graph"]["follow_backed_gap_events"], 1)
        self.assertEqual(payload["follow_graph"]["coincidental_gap_events"], 0)
        self.assertEqual(payload["follow_graph"]["profiles_with_social_sync"], ["follower"])
        self.assertEqual(payload["follow_graph"]["social_sync_coverage_ratio"], 0.5)

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


class FollowAwareSignalTests(unittest.TestCase):
    """The social graph annotates co-watch events without asserting influence."""

    def setUp(self) -> None:
        self.service = InsightsService(db=None)
        self.movie = Movie(
            id=10,
            canonical_key="letterboxd:test-film",
            title="Test Film",
            normalized_title="test film",
            release_year=2026,
            letterboxd_slug="test-film",
        )
        self.profiles = [
            Profile(id=1, username="Leader", is_active=True, scraping_status="completed"),
            Profile(id=2, username="Follower", is_active=True, scraping_status="completed"),
        ]
        self.gap_rows = [
            event(
                event_id=1,
                profile_id=1,
                username="Leader",
                watched_date=date(2026, 7, 1),
                movie=self.movie,
            ),
            event(
                event_id=2,
                profile_id=2,
                username="Follower",
                watched_date=date(2026, 7, 2),
                movie=self.movie,
            ),
        ]

    def _gap_event(self, graph: FollowGraph) -> dict:
        matches = self.service._matched_events(
            self.gap_rows,
            gap_days=1,
            follow_graph=graph,
        )
        return next(match for match in matches if match["day_gap"] == 1)

    def test_events_without_a_graph_report_unknown_rather_than_no_follow(self) -> None:
        match = self._gap_event(follow_graph(self.profiles))

        relationship = match["follow_relationship"]
        self.assertFalse(relationship["known"])
        self.assertIsNone(relationship["a_follows_b"])
        self.assertIsNone(relationship["b_follows_a"])
        self.assertIsNone(relationship["mutual"])
        self.assertEqual(relationship["observed_by"], [])
        self.assertIsNone(match["follows_earlier_watcher"])
        self.assertIsNone(match["follow_backed"])

    def test_later_watcher_following_the_earlier_one_is_the_directional_read(self) -> None:
        match = self._gap_event(
            follow_graph(
                self.profiles,
                following=[(2, "leader")],
                authoritative_following=[2],
            )
        )

        relationship = match["follow_relationship"]
        self.assertEqual(relationship["earlier_watcher"], "Leader")
        self.assertEqual(relationship["later_watcher"], "Follower")
        self.assertTrue(relationship["b_follows_a"])
        self.assertFalse(relationship["a_follows_b"])
        self.assertFalse(relationship["mutual"])
        self.assertTrue(relationship["known"])
        self.assertTrue(match["follows_earlier_watcher"])
        self.assertTrue(match["follow_backed"])

    def test_follow_pointing_the_other_way_is_not_a_follow_backed_gap(self) -> None:
        match = self._gap_event(
            follow_graph(
                self.profiles,
                following=[(1, "follower")],
                authoritative_following=[1, 2],
            )
        )

        relationship = match["follow_relationship"]
        self.assertTrue(relationship["a_follows_b"])
        self.assertFalse(relationship["b_follows_a"])
        self.assertFalse(match["follows_earlier_watcher"])
        self.assertFalse(match["follow_backed"])

    def test_a_followers_page_corroborates_the_same_edge(self) -> None:
        # Only the earlier watcher was synced, and their followers page lists
        # the later watcher: the same edge, observed from the other side.
        match = self._gap_event(
            follow_graph(
                self.profiles,
                followers=[(1, "follower")],
                authoritative_followers=[1],
            )
        )

        self.assertTrue(match["follow_relationship"]["b_follows_a"])
        self.assertTrue(match["follows_earlier_watcher"])

    def test_authoritative_absence_reads_false_and_silence_reads_unknown(self) -> None:
        authoritative = self._gap_event(
            follow_graph(self.profiles, authoritative_following=[1, 2])
        )
        silent = self._gap_event(follow_graph(self.profiles))

        self.assertTrue(authoritative["follow_relationship"]["known"])
        self.assertFalse(authoritative["follow_relationship"]["b_follows_a"])
        self.assertFalse(authoritative["follow_backed"])
        self.assertFalse(silent["follow_relationship"]["known"])
        self.assertIsNone(silent["follow_backed"])

    def test_mutual_stays_unknown_until_both_directions_are_observable(self) -> None:
        match = self._gap_event(
            follow_graph(
                self.profiles,
                following=[(2, "leader")],
                authoritative_following=[2],
            )
        )
        # The earlier watcher has no social import, so "does Leader follow
        # Follower?" is unanswered; a one-way observation cannot settle mutual.
        self.assertIsNone(match["follow_relationship"]["a_follows_b"])
        self.assertIsNone(match["follow_relationship"]["mutual"])

    def test_same_day_events_carry_the_edge_but_no_directional_read(self) -> None:
        rows = [
            event(
                event_id=1,
                profile_id=1,
                username="Leader",
                watched_date=date(2026, 7, 1),
                movie=self.movie,
            ),
            event(
                event_id=2,
                profile_id=2,
                username="Follower",
                watched_date=date(2026, 7, 1),
                movie=self.movie,
            ),
        ]
        graph = follow_graph(
            self.profiles,
            following=[(2, "leader")],
            authoritative_following=[2],
        )

        match = self.service._matched_events(rows, gap_days=1, follow_graph=graph)[0]

        # Same-day pairs sort by username, so the later watcher is `a` here.
        relationship = match["follow_relationship"]
        self.assertEqual((relationship["a"], relationship["b"]), ("Follower", "Leader"))
        self.assertTrue(relationship["a_follows_b"])
        self.assertIsNone(match["follow_relationship"]["earlier_watcher"])
        self.assertIsNone(match["follows_earlier_watcher"])
        self.assertIsNone(match["follow_backed"])

    def test_group_events_keep_every_pair_instead_of_one_relationship(self) -> None:
        profiles = [
            *self.profiles,
            Profile(id=3, username="Third", is_active=True, scraping_status="completed"),
        ]
        rows = [
            *self.gap_rows,
            event(
                event_id=3,
                profile_id=3,
                username="Third",
                watched_date=date(2026, 7, 2),
                movie=self.movie,
            ),
        ]
        graph = follow_graph(
            profiles,
            following=[(2, "leader")],
            authoritative_following=[2],
        )

        match = next(
            item
            for item in self.service._matched_events(rows, gap_days=1, follow_graph=graph)
            if item["profile_count"] == 3
        )

        self.assertIsNone(match["follow_relationship"])
        self.assertIsNone(match["follows_earlier_watcher"])
        self.assertEqual(len(match["follow_relationships"]), 3)
        self.assertEqual(
            {
                (item["a"], item["b"], item["follows_earlier_watcher"])
                for item in match["follow_relationships"]
            },
            {
                ("Leader", "Follower", True),
                ("Leader", "Third", None),
                ("Follower", "Third", None),
            },
        )
        # One observed edge is enough to call the event follow-backed, but the
        # unresolved pairs are still reported rather than assumed absent.
        self.assertTrue(match["follow_backed"])

    def test_summary_splits_follow_backed_from_coincidental_and_undetermined(self) -> None:
        summary = self.service._follow_graph_summary(
            follow_graph(self.profiles, authoritative_following=[1]),
            self.profiles,
            [
                {"day_gap": 1, "follow_backed": True},
                {"day_gap": 2, "follow_backed": False},
                {"day_gap": 3, "follow_backed": None},
                {"day_gap": 0, "follow_backed": None},
            ],
        )

        self.assertEqual(summary["gap_events"], 3)
        self.assertEqual(summary["follow_backed_gap_events"], 1)
        self.assertEqual(summary["coincidental_gap_events"], 1)
        self.assertEqual(summary["undetermined_gap_events"], 1)
        self.assertEqual(summary["same_day_events"], 1)
        self.assertEqual(summary["social_sync_coverage_ratio"], 0.5)
        self.assertTrue(
            any("not evidence" in warning for warning in summary["warnings"])
        )
        self.assertTrue(
            any("undetermined" in warning for warning in summary["warnings"])
        )

    def test_pair_dossier_annotates_paths_and_keeps_existing_fields(self) -> None:
        self.service._resolve_profiles = lambda *_args, **_kwargs: self.profiles
        self.service._event_rows = lambda *_args, **_kwargs: self.gap_rows
        self.service._state_rows = lambda *_args, **_kwargs: []
        self.service._feature_coverage = lambda *_args, **_kwargs: {
            "status": "ready",
            "score": 100,
            "dated_watch_events": 2,
            "total_watch_events": 2,
            "blockers": [],
            "warnings": [],
            "last_updated": None,
        }
        self.service._follow_graph = lambda _profiles: follow_graph(
            self.profiles,
            following=[(2, "leader")],
            authoritative_following=[2],
        )
        self.service.db = MagicMock()
        self.service.db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        payload = self.service.pair_dossier(["Leader", "Follower"], gap_days=1)

        path = payload["influence_paths"][0]
        self.assertEqual(path["leader"], "Leader")
        self.assertEqual(path["follower"], "Follower")
        self.assertTrue(path["follows_earlier_watcher"])
        self.assertEqual(payload["follow_graph"]["follow_backed_gap_events"], 1)
        self.assertEqual(payload["follow_graph"]["coincidental_gap_events"], 0)
        self.assertTrue(payload["follow_graph"]["relationship"]["b_follows_a"])
        # The pair's own relationship is not tied to any single event.
        self.assertIsNone(payload["follow_graph"]["relationship"]["later_watcher"])
        self.assertEqual(payload["summary"]["directional_leader"], "Leader")

    def test_edges_and_authority_load_in_bounded_queries(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        ServiceBase.metadata.create_all(
            engine,
            tables=[
                ServiceProfile.__table__,
                ServiceProfileSync.__table__,
                ServiceSyncDataset.__table__,
                ServiceProfileFollowEdge.__table__,
            ],
        )
        db = sessionmaker(bind=engine)()
        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        try:
            leader = ServiceProfile(id=1, username="leader", scraping_status="completed")
            watcher = ServiceProfile(id=2, username="watcher", scraping_status="completed")
            bystander = ServiceProfile(id=3, username="bystander", scraping_status="completed")
            sync = ServiceProfileSync(
                id=10,
                profile_id=watcher.id,
                source_kind="uploaded_csv_bundle",
                source_fingerprint="bundle",
                importer_version="test",
                status="completed",
                completed_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
                manifest={},
                coverage={},
                stats={},
            )
            db.add_all(
                [
                    leader,
                    watcher,
                    bystander,
                    sync,
                    ServiceSyncDataset(
                        id=100,
                        profile_sync_id=sync.id,
                        dataset_name="following",
                        source_row_count=2,
                        imported_row_count=2,
                        is_authoritative=True,
                        metadata_payload={},
                    ),
                    ServiceProfileFollowEdge(
                        id=200,
                        profile_id=watcher.id,
                        direction="following",
                        counterpart_username="Leader",
                        counterpart_username_normalized="leader",
                    ),
                    ServiceProfileFollowEdge(
                        id=201,
                        profile_id=watcher.id,
                        direction="following",
                        counterpart_username="Unrelated",
                        counterpart_username_normalized="unrelated",
                    ),
                    ServiceProfileFollowEdge(
                        id=202,
                        profile_id=watcher.id,
                        direction="following",
                        counterpart_username="Bystander",
                        counterpart_username_normalized="bystander",
                        removed_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
                    ),
                ]
            )
            db.commit()

            profiles = db.query(ServiceProfile).order_by(ServiceProfile.id).all()
            sqlalchemy_event.listen(engine, "before_cursor_execute", record)
            graph = InsightsService(db)._follow_graph(profiles)
            sqlalchemy_event.remove(engine, "before_cursor_execute", record)

            edge_queries = [
                statement
                for statement in statements
                if "profile_follow_edges" in statement
            ]
            self.assertEqual(len(edge_queries), 1)
            # Edges, latest syncs, the legacy-sync fallback and datasets: four
            # bounded statements, and the count does not grow with the group.
            self.assertLessEqual(len(statements), 4)

            self.assertTrue(graph.follows(watcher.id, leader.id))
            # An unfollow is soft-removed, so it must not read as an edge, and
            # the watcher's authoritative following list makes that a real no.
            self.assertFalse(graph.follows(watcher.id, bystander.id))
            # Nobody imported the leader's or bystander's social surfaces.
            self.assertIsNone(graph.follows(leader.id, watcher.id))
            self.assertIsNone(graph.follows(bystander.id, leader.id))
            self.assertTrue(graph.has_authoritative_social_sync(watcher.id))
            self.assertFalse(graph.has_authoritative_social_sync(leader.id))
        finally:
            db.close()
            engine.dispose()

    def test_an_unavailable_social_surface_never_becomes_authoritative_absence(self) -> None:
        service = InsightsService(db=MagicMock())
        service.db.query.return_value.filter.return_value.all.return_value = []
        profiles = [
            Profile(id=1, username="left", is_active=True, scraping_status="completed"),
            Profile(id=2, username="right", is_active=True, scraping_status="completed"),
        ]
        sync = ProfileSync(id=10, profile_id=1, status="completed")
        blocked = SyncDataset(
            profile_sync_id=sync.id,
            dataset_name="following",
            source_row_count=0,
            imported_row_count=0,
            is_authoritative=True,
            metadata_payload={"unavailable_reason": "forbidden/private"},
        )
        service._latest_sync_context = lambda _profiles: {
            1: (sync, {"following": blocked}),
            2: (None, {}),
        }

        graph = service._follow_graph(profiles)

        self.assertFalse(graph.has_authoritative_social_sync(1))
        self.assertIsNone(graph.follows(1, 2))


if __name__ == "__main__":
    unittest.main()


class SemanticNeighborTests(unittest.TestCase):
    """Different films that are contextually the same thing.

    The panel promised "contextual matches, not exact-title co-watches" and the
    backend returned a hard-coded empty list from the first commit onward, so the
    section was always blank. These pin what it may and may not claim.
    """

    def setUp(self) -> None:
        self.service = InsightsService(db=None)
        self.profiles = [
            Profile(id=1, username="ana", is_active=True, scraping_status="completed"),
            Profile(id=2, username="ben", is_active=True, scraping_status="completed"),
        ]

    def _movie(self, movie_id: int, title: str) -> Movie:
        return Movie(
            id=movie_id,
            canonical_key=f"letterboxd:{movie_id}",
            title=title,
            normalized_title=title.casefold(),
            release_year=2024,
            letterboxd_slug=f"film-{movie_id}",
        )

    def _state(
        self,
        profile_index: int,
        movie_id: int,
        title: str,
        watched: date,
        *,
        director: str | None = None,
        keywords: tuple[str, ...] = (),
    ) -> StateRow:
        profile = self.profiles[profile_index]
        crew = [{"name": director, "job": "Director"}] if director else []
        return StateRow(
            profile_id=profile.id,
            username=profile.username,
            movie_id=movie_id,
            rating=None,
            liked=False,
            tags=[],
            first_watched_date=watched,
            latest_watched_date=watched,
            watch_count=1,
            rewatch_count=0,
            movie=self._movie(movie_id, title),
            enrichment=MovieEnrichment(
                movie_id=movie_id,
                genres=[],
                keywords=list(keywords),
                credits={"crew": crew, "cast": []},
                production_countries=[],
            ),
        )

    def _neighbors(self, states, *, limit: int = 8, profiles=None):
        return self.service._semantic_neighbors(
            profiles if profiles is not None else self.profiles, states, limit
        )

    def test_two_different_films_by_one_director_are_a_neighbour(self) -> None:
        result = self._neighbors([
            self._state(0, 10, "Oldboy", date(2026, 7, 1), director="Park Chan-wook"),
            self._state(1, 11, "Decision to Leave", date(2026, 7, 3), director="Park Chan-wook"),
        ])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["movie"]["title"], "Decision to Leave")
        self.assertEqual(result[0]["reason"], "Both watched a Park Chan-wook film")
        self.assertEqual(result[0]["day_gap"], 2)

    def test_the_same_film_is_a_co_watch_and_never_a_semantic_neighbour(self) -> None:
        """The panel's whole promise is that these are NOT exact-title co-watches."""
        result = self._neighbors([
            self._state(0, 10, "Oldboy", date(2026, 7, 1), director="Park Chan-wook"),
            self._state(1, 10, "Oldboy", date(2026, 7, 2), director="Park Chan-wook"),
        ])

        self.assertEqual(result, [])

    def test_one_person_watching_two_related_films_is_not_a_match_between_anyone(self) -> None:
        result = self._neighbors([
            self._state(0, 10, "Oldboy", date(2026, 7, 1), director="Park Chan-wook"),
            self._state(0, 11, "Thirst", date(2026, 7, 2), director="Park Chan-wook"),
        ])

        self.assertEqual(result, [])

    def test_a_single_profile_can_have_no_neighbours(self) -> None:
        result = self._neighbors(
            [self._state(0, 10, "Oldboy", date(2026, 7, 1), director="Park Chan-wook")],
            profiles=self.profiles[:1],
        )

        self.assertEqual(result, [])

    def test_films_watched_further_apart_than_the_window_are_not_related_in_time(self) -> None:
        result = self._neighbors([
            self._state(0, 10, "Oldboy", date(2026, 6, 1), director="Park Chan-wook"),
            self._state(1, 11, "Thirst", date(2026, 7, 15), director="Park Chan-wook"),
        ])

        self.assertEqual(result, [])

    def test_a_film_without_a_watch_date_cannot_claim_closeness_in_time(self) -> None:
        undated = self._state(1, 11, "Thirst", date(2026, 7, 2), director="Park Chan-wook")
        undated = StateRow(**{**undated.__dict__, "latest_watched_date": None})

        result = self._neighbors([
            self._state(0, 10, "Oldboy", date(2026, 7, 1), director="Park Chan-wook"),
            undated,
        ])

        self.assertEqual(result, [])

    def test_watched_by_names_the_earlier_watcher_first(self) -> None:
        result = self._neighbors([
            self._state(1, 11, "Thirst", date(2026, 7, 5), director="Park Chan-wook"),
            self._state(0, 10, "Oldboy", date(2026, 7, 1), director="Park Chan-wook"),
        ])

        self.assertEqual(result[0]["watched_by"], ["ana", "ben"])

    def test_production_trivia_is_not_a_shared_theme(self) -> None:
        """TMDB keywords mix themes with credits metadata.

        "Both explored duringcreditsstinger" reached the real UI before this.
        """
        result = self._neighbors([
            self._state(0, 10, "A", date(2026, 7, 1), keywords=("duringcreditsstinger", "woman director")),
            self._state(1, 11, "B", date(2026, 7, 2), keywords=("duringcreditsstinger", "woman director")),
        ])

        self.assertEqual(result, [])

    def test_one_card_per_film_even_when_several_pairs_point_at_it(self) -> None:
        """Two Park Chan-wook pairs both surfaced "Decision to Leave" as duplicates."""
        result = self._neighbors([
            self._state(0, 10, "Oldboy", date(2026, 7, 1), director="Park Chan-wook"),
            self._state(0, 12, "Thirst", date(2026, 7, 2), director="Park Chan-wook"),
            self._state(1, 11, "Decision to Leave", date(2026, 7, 3), director="Park Chan-wook"),
        ])

        titles = [entry["movie"]["title"] for entry in result]
        self.assertEqual(titles, sorted(set(titles)))
        self.assertEqual(titles.count("Decision to Leave"), 1)

    def test_a_director_match_outranks_a_shared_keyword(self) -> None:
        result = self._neighbors([
            self._state(0, 10, "A", date(2026, 7, 1), director="Agnes Varda", keywords=("grief",)),
            self._state(1, 11, "B", date(2026, 7, 2), director="Agnes Varda", keywords=("grief",)),
        ])

        self.assertEqual(len(result), 1)
        self.assertIn("Agnes Varda", result[0]["reason"])

    def test_a_vowel_initial_name_takes_the_right_article(self) -> None:
        result = self._neighbors([
            self._state(0, 10, "A", date(2026, 7, 1), director="Alex Garland"),
            self._state(1, 11, "B", date(2026, 7, 2), director="Alex Garland"),
        ])

        self.assertEqual(result[0]["reason"], "Both watched an Alex Garland film")

    def test_the_limit_trims_without_reordering(self) -> None:
        states = [
            self._state(0, 10, "A", date(2026, 7, 1), director="Wong Kar-Wai"),
            self._state(1, 11, "B", date(2026, 7, 2), director="Wong Kar-Wai"),
            self._state(0, 12, "C", date(2026, 7, 1), director="Michael Mann"),
            self._state(1, 13, "D", date(2026, 7, 8), director="Michael Mann"),
        ]

        full = self._neighbors(states, limit=8)
        trimmed = self._neighbors(states, limit=1)

        self.assertEqual(len(trimmed), 1)
        self.assertEqual(trimmed[0]["movie"]["title"], full[0]["movie"]["title"])
