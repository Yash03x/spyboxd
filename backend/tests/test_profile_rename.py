"""Rename semantics: profile identity, feed repointing, and app-user mirroring."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest import TestCase

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.auth import ClerkUser
from backend.database.models import (
    AppUser,
    Profile,
    ProfileAccessRequest,
    ProfileFeedState,
    UserTrackedProfile,
)
from backend.database.repository import ProfileRepository
from backend.services.profile_access import provision_app_user_identity


class ProfileRenameTests(TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        for table in (
            Profile.__table__,
            ProfileFeedState.__table__,
            AppUser.__table__,
            UserTrackedProfile.__table__,
            ProfileAccessRequest.__table__,
        ):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine)()

        self.profile = Profile(username="gowri_sriya", scraping_status="completed")
        self.db.add(self.profile)
        self.db.flush()
        self.db.add(
            ProfileFeedState(
                profile_id=self.profile.id,
                feed_url="https://letterboxd.com/gowri_sriya/rss/",
                activity_guids=[],
                consecutive_failures=7,
                last_error="HTTP 404",
                last_http_status=404,
            )
        )
        self.db.add(
            AppUser(
                clerk_user_id="user_1",
                letterboxd_username="gowri_sriya",
            )
        )
        self.db.add(
            AppUser(
                clerk_user_id="user_2",
                letterboxd_username="someone_else",
            )
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_rename_carries_profile_feed_and_app_user(self):
        repo = ProfileRepository(self.db)

        feed_repointed = repo.rename_profile(self.profile, "mnigsm")

        self.assertTrue(feed_repointed)
        self.assertEqual(self.profile.username, "mnigsm")

        feed = self.db.get(ProfileFeedState, self.profile.id)
        self.assertEqual(feed.feed_url, "https://letterboxd.com/mnigsm/rss/")
        self.assertEqual(feed.consecutive_failures, 0)
        self.assertIsNone(feed.last_error)
        self.assertIsNone(feed.last_http_status)
        self.assertIsNotNone(feed.next_poll_at)

        mirrored = (
            self.db.query(AppUser).filter(AppUser.clerk_user_id == "user_1").one()
        )
        untouched = (
            self.db.query(AppUser).filter(AppUser.clerk_user_id == "user_2").one()
        )
        self.assertEqual(mirrored.letterboxd_username, "mnigsm")
        self.assertEqual(untouched.letterboxd_username, "someone_else")

        # Old username no longer resolves; the new one does, case-insensitively.
        self.assertIsNone(repo.get_profile_by_username("gowri_sriya"))
        self.assertEqual(repo.get_profile_by_username("MNIGSM").id, self.profile.id)

    def test_rename_without_feed_state_reports_no_repoint(self):
        repo = ProfileRepository(self.db)
        bare = Profile(username="lonely", scraping_status="completed")
        self.db.add(bare)
        self.db.commit()

        self.assertFalse(repo.rename_profile(bare, "still_lonely"))
        self.assertEqual(bare.username, "still_lonely")

    def test_accepted_rename_keeps_the_mirrored_app_user_provisionable(self):
        repo = ProfileRepository(self.db)

        repo.rename_profile(self.profile, "filmfan_7")
        identity = provision_app_user_identity(
            self.db,
            ClerkUser(
                user_id="user_1",
                session_id="session_1",
                letterboxd_username="filmfan_7",
            ),
        )

        self.assertEqual(
            identity,
            {
                "letterboxd_username": "filmfan_7",
                "primary_profile_status": "tracked",
            },
        )

    def test_rename_rejects_a_username_that_auth_cannot_provision(self):
        repo = ProfileRepository(self.db)

        with self.assertRaisesRegex(ValueError, "2-15 characters"):
            repo.rename_profile(self.profile, "film-fan")

        self.assertEqual(self.profile.username, "gowri_sriya")
