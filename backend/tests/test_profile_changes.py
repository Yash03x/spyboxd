from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import (
    Base,
    Movie,
    MovieList,
    Profile,
    ProfileDataChange,
    ProfileSourceActivity,
    ProfileFilm,
    ProfileSync,
    WatchEvent,
)
from backend.services.ingestion import (
    _build_legacy_movies,
    _get_or_create_sync,
    _upsert_source_activities,
    unified_data_loader,
)
from backend.services.profile_changes import get_recent_profile_changes, record_profile_changes
from backend.services.profile_loader import load_profile_data


class _StaticResolver:
    def __init__(self, movie: Movie):
        self.movie = movie

    def resolve(self, _identity):
        return self.movie


class OfficialExportContractTests(TestCase):
    def test_activity_dates_do_not_become_legacy_watch_dates(self):
        export = SimpleNamespace(
            all_films=pd.DataFrame(),
            ratings=pd.DataFrame([{"Name": "Heat", "Year": 1995, "Date": "2026-07-01", "Rating": 4.5}]),
            watched=pd.DataFrame([{"Name": "Heat", "Year": 1995, "Date": "2026-06-01"}]),
            diary=pd.DataFrame(),
            likes=pd.DataFrame([{"Name": "Heat", "Year": 1995, "Date": "2026-07-02"}]),
        )

        movies = _build_legacy_movies(export, 1, {})

        self.assertIsNone(next(iter(movies.values()))["watched_date"])

    def test_only_diary_date_becomes_legacy_watch_date(self):
        export = SimpleNamespace(
            all_films=pd.DataFrame(),
            ratings=pd.DataFrame([{"Name": "Heat", "Year": 1995, "Date": "2026-07-01", "Rating": 4.5}]),
            watched=pd.DataFrame([{"Name": "Heat", "Year": 1995, "Date": "2026-06-01"}]),
            diary=pd.DataFrame([{"Name": "Heat", "Year": 1995, "Watched Date": "2020-03-04"}]),
            likes=pd.DataFrame(),
        )

        movies = _build_legacy_movies(export, 1, {})

        self.assertEqual(next(iter(movies.values()))["watched_date"], date(2020, 3, 4))

    def test_profile_csv_identity_and_nested_film_likes_are_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "likes").mkdir()
            pd.DataFrame([{"Username": "actual_user", "Date Joined": "2020-01-01"}]).to_csv(
                root / "profile.csv", index=False
            )
            pd.DataFrame([{"Date": "2026-07-01", "Name": "Heat", "Year": 1995}]).to_csv(
                root / "watched.csv", index=False
            )
            pd.DataFrame([{"Date": "2026-07-02", "Name": "Heat", "Year": 1995}]).to_csv(
                root / "likes" / "films.csv", index=False
            )

            loaded = load_profile_data(str(root), "zip_filename")

        self.assertEqual(loaded.username, "actual_user")
        self.assertEqual(loaded.source_kind, "letterboxd_export")
        self.assertEqual(len(loaded.likes), 1)
        self.assertIn("likes/films.csv", loaded.source_files)


class ProfileChangePersistenceTests(TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        for table in (
            Profile.__table__,
            ProfileSync.__table__,
            Movie.__table__,
            MovieList.__table__,
            ProfileFilm.__table__,
            WatchEvent.__table__,
            ProfileDataChange.__table__,
            ProfileSourceActivity.__table__,
        ):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine)()
        self.profile = Profile(id=1, username="viewer", is_active=True, scraping_status="completed")
        self.movie = Movie(
            id=10,
            canonical_key="title:heat|year:1995",
            title="Heat",
            normalized_title="heat",
            release_year=1995,
        )
        self.sync = ProfileSync(
            id=20,
            profile_id=1,
            source_kind="letterboxd_export",
            source_fingerprint="sync-20",
            importer_version="3",
            status="running",
        )
        self.db.add_all([self.profile, self.movie, self.sync])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_official_export_activity_is_explicitly_non_watch(self):
        analyzer = SimpleNamespace(
            username="viewer",
            watched=pd.DataFrame([{"Name": "Heat", "Year": 1995, "Date": "2026-01-01"}]),
            ratings=pd.DataFrame([{"Name": "Heat", "Year": 1995, "Date": "2026-01-02"}]),
            likes=pd.DataFrame([{"Name": "Heat", "Year": 1995, "Date": "2026-01-03"}]),
            watchlist=pd.DataFrame([{"Name": "Heat", "Year": 1995, "Date": "2026-01-04"}]),
        )

        count = _upsert_source_activities(
            analyzer_profile=analyzer,
            profile_id=1,
            sync=self.sync,
            resolver=_StaticResolver(self.movie),
            identity_lookup={},
            db=self.db,
        )
        self.db.commit()

        self.assertEqual(count, 4)
        self.assertEqual(self.db.query(WatchEvent).count(), 0)
        activities = self.db.query(ProfileSourceActivity).all()
        self.assertEqual(
            {activity.activity_type for activity in activities},
            {"watched_marked", "rating_recorded", "like_recorded", "watchlist_added"},
        )
        self.assertEqual(
            {activity.date_semantics for activity in activities},
            {"account_activity", "watchlist_added"},
        )
        self.assertTrue(all(activity.source_kind == "letterboxd_export" for activity in activities))

    def test_completed_source_fingerprint_replay_is_an_immutable_no_op(self):
        self.sync.status = "completed"
        self.sync.stats = {"films": 17, "changes": 2}
        self.db.commit()
        completed_at = self.sync.completed_at

        replay = SimpleNamespace(
            source_kind="letterboxd_export",
            source_fingerprint="sync-20",
            manifest={"different": "replay metadata"},
        )
        returned, was_completed = _get_or_create_sync(replay, self.profile.id, self.db)

        self.assertTrue(was_completed)
        self.assertEqual(returned.id, self.sync.id)
        self.assertEqual(returned.status, "completed")
        self.assertEqual(returned.stats, {"films": 17, "changes": 2})
        self.assertEqual(returned.manifest, {})
        self.assertEqual(returned.completed_at, completed_at)

    def test_completed_bundle_replay_does_not_mutate_profile_snapshot(self):
        self.profile.avg_rating = 4.0
        self.profile.scraping_status = "completed"
        self.sync.status = "completed"
        self.sync.stats = {"films": 17}
        self.db.commit()

        replay = SimpleNamespace(
            username="viewer",
            source_kind="letterboxd_export",
            source_fingerprint="sync-20",
            manifest={},
            avg_rating=1.0,
        )
        imported = unified_data_loader(replay, self.profile.id, self.db)
        self.db.refresh(self.profile)

        self.assertEqual(imported, 17)
        self.assertEqual(self.profile.avg_rating, 4.0)
        self.assertEqual(self.profile.scraping_status, "completed")

    def test_first_sync_is_baseline_and_emits_no_changes(self):
        count = record_profile_changes(
            self.db,
            profile_id=1,
            profile_sync=self.sync,
            before={"films": {}},
            after={"films": {"movie:10": {"movie_id": 10, "movie": {"title": "Heat"}}}},
            authoritative={"films": True},
            has_baseline=False,
        )
        self.db.commit()

        self.assertEqual(count, 0)
        self.assertEqual(self.db.query(ProfileDataChange).count(), 0)

    def test_review_text_edit_is_detected_without_persisting_review_prose_or_digest(self):
        count = record_profile_changes(
            self.db,
            profile_id=self.profile.id,
            profile_sync=self.sync,
            before={
                "reviews": {
                    "review:10": {
                        "movie_id": self.movie.id,
                        "movie": {"id": self.movie.id, "title": "Heat", "year": 1995},
                        "text_digest": "private-old-review-digest",
                    }
                }
            },
            after={
                "reviews": {
                    "review:10": {
                        "movie_id": self.movie.id,
                        "movie": {"id": self.movie.id, "title": "Heat", "year": 1995},
                        "text_digest": "private-new-review-digest",
                    }
                }
            },
            authoritative={"reviews": True},
            has_baseline=True,
        )
        self.db.commit()

        self.assertEqual(count, 1)
        change = self.db.query(ProfileDataChange).one()
        self.assertEqual(change.change_type, "review_updated")
        self.assertEqual(change.before_payload, {"text_changed": True})
        self.assertEqual(change.after_payload, {"text_changed": True})
        serialized = str(change.before_payload) + str(change.after_payload)
        self.assertNotIn("private-old-review-digest", serialized)
        self.assertNotIn("private-new-review-digest", serialized)

    def test_latest_sync_feed_does_not_resurface_older_changes(self):
        current_sync = ProfileSync(
            id=21,
            profile_id=self.profile.id,
            source_kind="letterboxd_export",
            source_fingerprint="sync-21",
            importer_version="3",
            status="completed",
        )
        self.db.add(current_sync)
        self.db.add_all(
            [
                ProfileDataChange(
                    profile_id=self.profile.id,
                    profile_sync_id=self.sync.id,
                    change_key="old-film",
                    change_type="film_added",
                    entity_type="film",
                    entity_key="movie:10",
                    source_kind="letterboxd_export",
                ),
                ProfileDataChange(
                    profile_id=self.profile.id,
                    profile_sync_id=current_sync.id,
                    change_key="current-rating",
                    change_type="rating_changed",
                    entity_type="film",
                    entity_key="movie:10",
                    source_kind="letterboxd_export",
                ),
            ]
        )
        self.profile.last_profile_sync_id = current_sync.id
        self.db.commit()

        latest = get_recent_profile_changes(
            self.db,
            usernames=["viewer"],
            limit=10,
            latest_sync_only=True,
        )
        history = get_recent_profile_changes(
            self.db,
            usernames=["viewer"],
            limit=10,
        )

        self.assertEqual(latest["scope"], "latest_sync")
        self.assertEqual([item["change_type"] for item in latest["changes"]], ["rating_changed"])
        self.assertEqual(history["scope"], "history")
        self.assertEqual(len(history["changes"]), 2)

    def test_subsequent_sync_records_safe_semantic_deltas_and_query_contract(self):
        before = {
            "films": {
                "movie:10": {
                    "movie_id": 10,
                    "movie": {"id": 10, "title": "Heat", "year": 1995},
                    "rating": 3.0,
                    "is_liked": False,
                }
            },
            "watchlist": {},
            "list_items": {
                "list:key|movie:10": {
                    "movie_list_id": None,
                    "movie_id": 10,
                    "movie": {"id": 10, "title": "Heat", "year": 1995},
                    "position": 1,
                    "note_digest": "private-old-digest",
                }
            },
        }
        after = {
            "films": {
                "movie:10": {
                    "movie_id": 10,
                    "movie": {"id": 10, "title": "Heat", "year": 1995},
                    "rating": 4.5,
                    "is_liked": True,
                }
            },
            "watchlist": {
                "movie:10": {
                    "movie_id": 10,
                    "movie": {"id": 10, "title": "Heat", "year": 1995},
                    "added_date": "2026-07-29",
                    "added_date_source_kind": "letterboxd_export:watchlist",
                }
            },
            "list_items": {
                "list:key|movie:10": {
                    "movie_list_id": None,
                    "movie_id": 10,
                    "movie": {"id": 10, "title": "Heat", "year": 1995},
                    "position": 2,
                    "note_digest": "private-new-digest",
                }
            },
        }

        count = record_profile_changes(
            self.db,
            profile_id=1,
            profile_sync=self.sync,
            before=before,
            after=after,
            authoritative={"films": True, "ratings": True, "likes": True, "watchlist": True, "list_items": True},
            has_baseline=True,
        )
        self.sync.status = "completed"
        self.db.commit()

        self.assertEqual(count, 4)
        self.assertEqual(
            {change.change_type for change in self.db.query(ProfileDataChange).all()},
            {"rating_changed", "like_changed", "watchlist_added", "list_item_updated"},
        )
        serialized = " ".join(
            str(change.before_payload) + str(change.after_payload)
            for change in self.db.query(ProfileDataChange).all()
        )
        self.assertNotIn("private-old-digest", serialized)
        self.assertNotIn("private-new-digest", serialized)

        response = get_recent_profile_changes(self.db, usernames=["VIEWER"], limit=10)
        self.assertEqual(len(response["changes"]), 4)
        self.assertTrue(all(item["username"] == "viewer" for item in response["changes"]))
        self.assertTrue(all(item["source_kind"] == "letterboxd_export" for item in response["changes"]))


if __name__ == "__main__":
    import unittest

    unittest.main()
