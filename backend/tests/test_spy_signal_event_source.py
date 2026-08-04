from __future__ import annotations

from copy import deepcopy
from datetime import date
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import (
    Movie,
    Profile,
    ProfileFilm,
    ProfileSync,
    Rating,
    SyncDataset,
    WatchEvent,
)
from backend.database.repository import (
    AnalyticsRepository,
    _calculate_event_source_timing,
    _merge_event_source_timing,
)


def timing_entry(
    *,
    profile_id: int,
    username: str,
    watched_date: date,
    movie_id: int = 100,
    title: str = "Test Film",
    year: int = 2026,
    rewatch: bool = False,
):
    return {
        "profile_id": profile_id,
        "movie_id": movie_id,
        "username": username,
        "movie_title": title,
        "movie_year": year,
        "film_slug": "test-film",
        "letterboxd_id": None,
        "rating": 4.0,
        "watched_date": watched_date,
        "is_rewatch": rewatch,
        "is_liked": False,
    }


class EventSourceTimingTests(unittest.TestCase):
    def calculate(self, entries, gap_days=1):
        return _calculate_event_source_timing(entries, gap_days=gap_days)

    def test_one_profile_rewatches_do_not_create_a_group_signal(self):
        entries = [
            timing_entry(
                profile_id=1,
                username="solo",
                watched_date=date(2026, 7, 1),
            ),
            timing_entry(
                profile_id=1,
                username="solo",
                watched_date=date(2026, 7, 2),
                rewatch=True,
            ),
        ]

        timing = self.calculate(entries)

        self.assertEqual(timing["same_day_events"], [])
        self.assertEqual(timing["one_day_gap_events"], [])
        self.assertEqual(dict(timing["pair_metrics"]), {})
        self.assertEqual(dict(timing["follow_paths"]), {})

    def test_duplicate_same_day_events_do_not_inflate_participants_or_pairs(self):
        entries = [
            timing_entry(
                profile_id=1,
                username="left",
                watched_date=date(2026, 7, 1),
            ),
            timing_entry(
                profile_id=1,
                username="left",
                watched_date=date(2026, 7, 1),
                rewatch=True,
            ),
            timing_entry(
                profile_id=2,
                username="right",
                watched_date=date(2026, 7, 1),
            ),
        ]

        timing = self.calculate(entries)
        event = timing["same_day_events"][0]

        self.assertEqual(event["profile_count"], 2)
        self.assertEqual(event["pair_count"], 1)
        self.assertEqual(event["profiles"], ["left", "right"])
        self.assertEqual(len(event["participants"]), 2)
        self.assertEqual(event["rewatch_count"], 1)
        self.assertEqual(timing["pair_metrics"][("left", "right")]["same_day_count"], 1)

    def test_duplicate_event_does_not_change_three_profile_pair_count(self):
        entries = [
            timing_entry(
                profile_id=1,
                username="a",
                watched_date=date(2026, 7, 1),
            ),
            timing_entry(
                profile_id=1,
                username="a",
                watched_date=date(2026, 7, 1),
                rewatch=True,
            ),
            timing_entry(
                profile_id=2,
                username="b",
                watched_date=date(2026, 7, 1),
            ),
            timing_entry(
                profile_id=3,
                username="c",
                watched_date=date(2026, 7, 1),
            ),
        ]

        event = self.calculate(entries)["same_day_events"][0]

        self.assertEqual(event["profile_count"], 3)
        self.assertEqual(event["pair_count"], 3)

    def test_cross_date_pair_count_excludes_self_pairs_and_duplicates(self):
        entries = [
            timing_entry(
                profile_id=1,
                username="a",
                watched_date=date(2026, 7, 1),
            ),
            timing_entry(
                profile_id=2,
                username="b",
                watched_date=date(2026, 7, 1),
            ),
            timing_entry(
                profile_id=1,
                username="a",
                watched_date=date(2026, 7, 2),
                rewatch=True,
            ),
            timing_entry(
                profile_id=3,
                username="c",
                watched_date=date(2026, 7, 2),
            ),
        ]

        event = self.calculate(entries)["one_day_gap_events"][0]

        self.assertEqual(event["profile_count"], 3)
        self.assertEqual(event["pair_count"], 3)
        self.assertEqual(len(event["participants"]), 3)

    def test_pair_alignment_uses_minimum_gap_once_per_movie(self):
        entries = [
            timing_entry(
                profile_id=1,
                username="a",
                watched_date=date(2026, 7, 1),
            ),
            timing_entry(
                profile_id=1,
                username="a",
                watched_date=date(2026, 7, 3),
                rewatch=True,
            ),
            timing_entry(
                profile_id=2,
                username="b",
                watched_date=date(2026, 7, 1),
            ),
            timing_entry(
                profile_id=2,
                username="b",
                watched_date=date(2026, 7, 2),
                rewatch=True,
            ),
        ]

        timing = self.calculate(entries)
        metrics = timing["pair_metrics"][("a", "b")]

        self.assertEqual(len(timing["same_day_events"]), 1)
        self.assertGreaterEqual(len(timing["one_day_gap_events"]), 1)
        self.assertEqual(metrics["same_day_count"], 1)
        self.assertEqual(metrics["one_day_gap_count"], 0)
        self.assertEqual(metrics["tight_window_count"], 1)
        self.assertEqual(metrics["within_gap_count"], 1)
        self.assertEqual(len(metrics["movie_keys"]), 1)
        self.assertEqual(dict(timing["follow_paths"]), {})

    def test_opposite_direction_minimum_gap_tie_has_no_follow_path(self):
        entries = [
            timing_entry(
                profile_id=1,
                username="a",
                watched_date=date(2026, 7, 1),
            ),
            timing_entry(
                profile_id=1,
                username="a",
                watched_date=date(2026, 7, 3),
                rewatch=True,
            ),
            timing_entry(
                profile_id=2,
                username="b",
                watched_date=date(2026, 7, 2),
            ),
        ]

        timing = self.calculate(entries)

        self.assertEqual(timing["pair_metrics"][("a", "b")]["one_day_gap_count"], 1)
        self.assertEqual(dict(timing["follow_paths"]), {})

    def test_unambiguous_next_day_watch_creates_one_follow_path(self):
        entries = [
            timing_entry(
                profile_id=1,
                username="leader",
                watched_date=date(2026, 7, 1),
            ),
            timing_entry(
                profile_id=2,
                username="follower",
                watched_date=date(2026, 7, 2),
            ),
        ]

        timing = self.calculate(entries)

        self.assertEqual(
            timing["follow_paths"][("leader", "follower")]["count"],
            1,
        )

    def test_normalized_movie_id_matches_variants_without_merging_same_title(self):
        entries = [
            timing_entry(
                profile_id=1,
                username="a",
                watched_date=date(2026, 7, 1),
                movie_id=10,
                title="The Film",
            ),
            timing_entry(
                profile_id=2,
                username="b",
                watched_date=date(2026, 7, 1),
                movie_id=10,
                title="The Film: Alternate Title",
            ),
            timing_entry(
                profile_id=3,
                username="c",
                watched_date=date(2026, 7, 1),
                movie_id=11,
                title="The Film",
            ),
        ]

        timing = self.calculate(entries)

        self.assertEqual(len(timing["same_day_events"]), 1)
        self.assertEqual(timing["same_day_events"][0]["profiles"], ["a", "b"])
        self.assertEqual(set(timing["pair_metrics"]), {("a", "b")})


class EventSourceMergeTests(unittest.TestCase):
    def test_merge_changes_only_timing_surfaces_and_keeps_response_shape(self):
        baseline = {
            "summary": {
                "profiles_analyzed": 2,
                "profiles_with_diary_dates": 2,
                "shared_titles": 4,
                "same_day_events": 0,
                "one_day_gap_events": 0,
                "same_day_pair_hits": 0,
                "one_day_gap_pair_hits": 0,
                "strongest_alignment_pair": None,
            },
            "same_day_events": [],
            "one_day_gap_events": [],
            "most_shared_titles": [{"title": "State result"}],
            "consensus_hits": [{"title": "Consensus result"}],
            "divisive_titles": [{"title": "Divisive result"}],
            "aligned_pairs": [
                {
                    "profiles": ["a", "b"],
                    "shared_titles": 4,
                    "rating_overlap_count": 3,
                    "rating_correlation": 0.8,
                    "average_rating_gap": 0.5,
                    "same_day_count": 0,
                    "one_day_gap_count": 0,
                    "tight_window_count": 0,
                    "alignment_score": 70.0,
                    "sample_titles": [{"title": "State result", "year": 2026}],
                }
            ],
            "follow_paths": [],
        }
        original_keys = set(baseline)
        original_state_surfaces = {
            key: deepcopy(baseline[key])
            for key in ("most_shared_titles", "consensus_hits", "divisive_titles")
        }
        timing = _calculate_event_source_timing(
            [
                timing_entry(
                    profile_id=1,
                    username="a",
                    watched_date=date(2026, 7, 1),
                ),
                timing_entry(
                    profile_id=2,
                    username="b",
                    watched_date=date(2026, 7, 1),
                ),
            ],
            gap_days=None,
        )

        result = _merge_event_source_timing(
            baseline,
            timing,
            limit=10,
            gap_days=None,
        )

        self.assertEqual(set(result), original_keys)
        for key, expected in original_state_surfaces.items():
            self.assertEqual(result[key], expected)
        aligned_pair = result["aligned_pairs"][0]
        self.assertEqual(aligned_pair["shared_titles"], 4)
        self.assertEqual(aligned_pair["rating_overlap_count"], 3)
        self.assertEqual(aligned_pair["rating_correlation"], 0.8)
        self.assertEqual(aligned_pair["average_rating_gap"], 0.5)
        self.assertEqual(aligned_pair["same_day_count"], 1)
        self.assertNotIn("event_source", result)

    def test_every_pair_survives_the_leaderboard_limit(self):
        """`limit` is for top-N lists; `aligned_pairs` feeds a matrix.

        The Overview co-watch grid draws one cell per pair in the selection.
        When aligned_pairs was cut to the leaderboard's six, the other 184
        cells of a twenty-profile grid rendered the dash that means "no shared
        film" — for pairs sharing hundreds. Pair leaderboard and matrix then
        contradicted each other about the same pair.
        """

        def pair(left: str, right: str, shared: int) -> dict:
            return {
                "profiles": [left, right],
                "shared_titles": shared,
                "rating_overlap_count": 2,
                "rating_correlation": 0.5,
                "average_rating_gap": 0.5,
                "same_day_count": 0,
                "one_day_gap_count": 0,
                "tight_window_count": 0,
                "alignment_score": 50.0,
                "sample_titles": [],
            }

        baseline = {
            "summary": {
                "profiles_analyzed": 3,
                "profiles_with_diary_dates": 3,
                "shared_titles": 0,
                "same_day_events": 0,
                "one_day_gap_events": 0,
                "same_day_pair_hits": 0,
                "one_day_gap_pair_hits": 0,
                "strongest_alignment_pair": None,
            },
            "same_day_events": [],
            "one_day_gap_events": [],
            "most_shared_titles": [{"title": f"t{i}"} for i in range(5)],
            "consensus_hits": [],
            "divisive_titles": [],
            "aligned_pairs": [pair("a", "b", 400), pair("a", "c", 300), pair("b", "c", 200)],
            "follow_paths": [],
        }
        timing = _calculate_event_source_timing([], gap_days=None)

        result = _merge_event_source_timing(baseline, timing, limit=1, gap_days=None)

        # The leaderboard lists honour the limit; the pair list does not.
        self.assertEqual(len(result["most_shared_titles"]), 1)
        self.assertEqual(
            sorted(tuple(entry["profiles"]) for entry in result["aligned_pairs"]),
            [("a", "b"), ("a", "c"), ("b", "c")],
        )

        capped = _merge_event_source_timing(
            deepcopy(baseline), timing, limit=1, gap_days=None, pair_limit=2
        )
        self.assertEqual(len(capped["aligned_pairs"]), 2)

    def test_repository_rejects_unknown_event_source_before_querying(self):
        repository = AnalyticsRepository(db=None)

        with self.assertRaisesRegex(ValueError, "event_source"):
            repository.get_group_correlation_metrics(event_source="unknown")


class EventSourceSelectionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        for table in (
            Profile.__table__,
            ProfileSync.__table__,
            SyncDataset.__table__,
            Movie.__table__,
            Rating.__table__,
            ProfileFilm.__table__,
            WatchEvent.__table__,
        ):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_authority_is_profile_scoped_and_excludes_superseded_events(self):
        profiles = [
            Profile(id=1, username="authoritative", is_active=True, scraping_status="completed"),
            Profile(id=2, username="fallback", is_active=True, scraping_status="completed"),
            Profile(id=3, username="authoritative_empty", is_active=True, scraping_status="completed"),
            Profile(id=4, username="failed_authority", is_active=True, scraping_status="completed"),
        ]
        movie = Movie(
            id=100,
            canonical_key="letterboxd:test-film",
            title="Test Film",
            normalized_title="test film",
            release_year=2026,
            letterboxd_slug="test-film",
        )
        syncs = [
            ProfileSync(
                id=1,
                profile_id=1,
                source_kind="letterboxd_export",
                source_fingerprint="authoritative",
                importer_version="test",
                status="completed",
            ),
            ProfileSync(
                id=2,
                profile_id=2,
                source_kind="legacy_backfill",
                source_fingerprint="fallback",
                importer_version="test",
                status="completed",
            ),
            ProfileSync(
                id=3,
                profile_id=3,
                source_kind="letterboxd_export",
                source_fingerprint="authoritative-empty",
                importer_version="test",
                status="completed",
            ),
            ProfileSync(
                id=4,
                profile_id=4,
                source_kind="letterboxd_export",
                source_fingerprint="failed-authority",
                importer_version="test",
                status="failed",
            ),
        ]
        datasets = [
            SyncDataset(
                id=1,
                profile_sync_id=1,
                dataset_name="diary",
                source_row_count=2,
                imported_row_count=2,
                is_authoritative=True,
            ),
            SyncDataset(
                id=2,
                profile_sync_id=2,
                dataset_name="watch_events",
                source_row_count=1,
                imported_row_count=1,
                is_authoritative=False,
            ),
            SyncDataset(
                id=3,
                profile_sync_id=3,
                dataset_name="diary",
                source_row_count=0,
                imported_row_count=0,
                is_authoritative=True,
            ),
            SyncDataset(
                id=4,
                profile_sync_id=4,
                dataset_name="diary",
                source_row_count=1,
                imported_row_count=1,
                is_authoritative=True,
            ),
        ]
        ratings = [
            Rating(
                id=profile.id,
                profile_id=profile.id,
                movie_id=movie.id,
                movie_title=movie.title,
                movie_year=movie.release_year,
                watched_date=date(2026, 7, profile.id + 10),
            )
            for profile in profiles
        ]
        watch_events = [
            WatchEvent(
                id=1,
                profile_id=1,
                movie_id=movie.id,
                event_key="authoritative-active",
                watched_date=date(2026, 7, 1),
                source_kind="diary_csv",
            ),
            WatchEvent(
                id=2,
                profile_id=1,
                movie_id=movie.id,
                event_key="authoritative-superseded",
                watched_date=date(2026, 7, 2),
                source_kind="diary_csv",
                superseded_at=date(2026, 7, 3),
            ),
            WatchEvent(
                id=3,
                profile_id=2,
                movie_id=movie.id,
                event_key="non-authoritative-copy",
                watched_date=date(2026, 7, 2),
                source_kind="legacy_rating_snapshot",
            ),
        ]
        self.db.add_all([*profiles, movie, *syncs, *datasets, *ratings, *watch_events])
        self.db.commit()

        entries = AnalyticsRepository(self.db)._get_event_source_timing_entries(
            [profile.username for profile in profiles]
        )
        entries_by_profile = {}
        for entry in entries:
            entries_by_profile.setdefault(entry["username"], []).append(entry)

        self.assertEqual(
            [entry["watched_date"] for entry in entries_by_profile["authoritative"]],
            [date(2026, 7, 1)],
        )
        self.assertEqual(
            [entry["watched_date"] for entry in entries_by_profile["fallback"]],
            [date(2026, 7, 12)],
        )
        self.assertNotIn("authoritative_empty", entries_by_profile)
        self.assertEqual(
            [entry["watched_date"] for entry in entries_by_profile["failed_authority"]],
            [date(2026, 7, 14)],
        )


if __name__ == "__main__":
    unittest.main()


class SignalFeedOrderingTests(unittest.TestCase):
    """The Signal Feed is presented newest first and truncated to a limit.

    Whichever key leads the sort decides which events survive that truncation.
    Leading with crowd size kept the biggest gatherings and dropped the latest
    ones, so a three-day scan showed nothing from the most recent week while the
    header still said "most recent first".
    """

    def _timing(self, entries, gap_days=3):
        return _calculate_event_source_timing(entries, gap_days=gap_days)

    def test_the_newest_match_leads_even_against_a_bigger_crowd(self) -> None:
        entries = []
        # An old film three people watched together.
        for index, name in enumerate(("ana", "ben", "cal"), start=1):
            entries.append(
                timing_entry(
                    profile_id=index,
                    username=name,
                    watched_date=date(2026, 1, 10),
                    movie_id=1,
                    title="Old Crowd",
                )
            )
        # A recent film only two of them watched.
        for index, name in enumerate(("ana", "ben"), start=1):
            entries.append(
                timing_entry(
                    profile_id=index,
                    username=name,
                    watched_date=date(2026, 7, 30),
                    movie_id=2,
                    title="Recent Pair",
                )
            )

        events = self._timing(entries)["gap_events"]

        self.assertEqual(events[0]["title"], "Recent Pair")

    def test_a_bigger_crowd_still_wins_within_the_same_day(self) -> None:
        """Recency leads, but crowd size remains the tiebreaker."""
        entries = []
        for index, name in enumerate(("ana", "ben", "cal"), start=1):
            entries.append(
                timing_entry(
                    profile_id=index,
                    username=name,
                    watched_date=date(2026, 7, 30),
                    movie_id=1,
                    title="Same Day Crowd",
                )
            )
        for index, name in enumerate(("ana", "ben"), start=1):
            entries.append(
                timing_entry(
                    profile_id=index,
                    username=name,
                    watched_date=date(2026, 7, 30),
                    movie_id=2,
                    title="Same Day Pair",
                )
            )

        events = self._timing(entries)["gap_events"]
        titles = [event["title"] for event in events]

        self.assertLess(titles.index("Same Day Crowd"), titles.index("Same Day Pair"))


class AlignmentEvidenceTests(unittest.TestCase):
    """A rating correlation is only worth what its sample is worth.

    Any two points lie on a line, so a pair who had rated two films in common
    and agreed scored a perfect correlation and a zero rating gap -- the full
    55% those two components carry. That put them level with a pair sharing 95
    films and 48 ratings, and the card said "Strongest Pair" above it.
    """

    def _score(self, *, shared_titles, overlap, correlation, gap):
        """Run one pair through the merge path's scoring."""
        baseline = {
            "summary": {},
            "aligned_pairs": [
                {
                    "profiles": ["ana", "ben"],
                    "shared_titles": shared_titles,
                    "rating_overlap_count": overlap,
                    "rating_correlation": correlation,
                    "average_rating_gap": gap,
                    # Deliberately stale: the merge only recomputes the score
                    # when the timing it holds differs from the event-derived
                    # timing below, so these must not already agree.
                    "same_day_count": 0,
                    "one_day_gap_count": 0,
                    "tight_window_count": 0,
                    "alignment_score": 0.0,
                }
            ]
        }
        timing = {
            "profiles_with_dates": ["ana", "ben"],
            "same_day_events": [],
            "one_day_gap_events": [],
            "gap_events": [],
            "follow_paths": {},
            "pair_metrics": {
                ("ana", "ben"): {
                    "same_day_count": 0,
                    "one_day_gap_count": 0,
                    "tight_window_count": 1,
                    "within_gap_count": 0,
                }
            },
        }
        merged = _merge_event_source_timing(baseline, timing, limit=8, gap_days=0)
        return merged["aligned_pairs"][0]["alignment_score"]

    def test_a_thin_perfect_agreement_scores_below_a_broad_real_one(self) -> None:
        thin = self._score(shared_titles=88, overlap=2, correlation=1.0, gap=0.0)
        broad = self._score(shared_titles=95, overlap=48, correlation=0.56, gap=0.48)

        self.assertLess(thin, broad)

    def test_two_shared_ratings_do_not_earn_the_full_correlation_weight(self) -> None:
        thin = self._score(shared_titles=88, overlap=2, correlation=1.0, gap=0.0)

        # Unshrunk, a perfect correlation and a zero gap take all 55% those two
        # components carry, which with a full shared-titles score reaches 80.
        self.assertLess(thin, 65)
