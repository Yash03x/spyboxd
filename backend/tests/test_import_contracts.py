from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import Mock, patch
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from bs4 import BeautifulSoup

from scraper_html import EnhancedLetterboxdScraper
from database.models import Movie
from services.import_contracts import (
    MovieIdentity,
    diary_event_key,
    movie_identity_from_row,
    parse_boolean,
)
from services.profile_loader import load_profile_data, validate_import_bundle
from services.movie_resolver import MovieResolver
from services.ingestion import _build_coverage, _build_legacy_movies
from scripts import import_local_archive


class _ExistingMovieQuery:
    def __init__(self, existing: Movie):
        self.existing = existing

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.existing


class _ExistingMovieSession:
    def __init__(self, existing: Movie):
        self.existing = existing
        self.added = []

    def query(self, *args, **kwargs):
        return _ExistingMovieQuery(self.existing)

    def add(self, value):
        self.added.append(value)

    def flush(self):
        return None


class MovieIdentityContractTests(unittest.TestCase):
    def test_stable_letterboxd_identity_wins_over_title(self) -> None:
        identity = movie_identity_from_row(
            {
                "Title": "The Movie",
                "Year": 2026,
                "Movie_ID": "1255394",
                "Film_URL": "/film/the-movie/",
                "Poster_URL": "/film/the-movie/image-150/",
            }
        )

        self.assertIsNotNone(identity)
        self.assertEqual(identity.letterboxd_id, "1255394")
        self.assertEqual(identity.canonical_key, "letterboxd:1255394")
        self.assertEqual(identity.letterboxd_slug, "the-movie")
        self.assertEqual(identity.poster_url, "https://letterboxd.com/film/the-movie/image-150/")

    def test_movie_id_is_not_mistaken_for_tmdb_id(self) -> None:
        identity = movie_identity_from_row({"Name": "Arrival", "Year": 2016, "Movie_ID": 123})

        self.assertEqual(identity.letterboxd_id, "123")
        self.assertFalse(hasattr(identity, "tmdb_id"))

    def test_boolean_false_strings_remain_false(self) -> None:
        for value in ("No", "false", "0", "off", ""):
            with self.subTest(value=value):
                self.assertFalse(parse_boolean(value))

    def test_fallback_diary_keys_are_occurrence_aware_and_repeatable(self) -> None:
        identity = MovieIdentity("Arrival", 2016, letterboxd_slug="arrival-2016")
        first = diary_event_key(
            username="viewer",
            identity=identity,
            watched_date=date(2026, 7, 28),
            occurrence=1,
        )
        second = diary_event_key(
            username="viewer",
            identity=identity,
            watched_date=date(2026, 7, 28),
            occurrence=2,
        )

        self.assertNotEqual(first, second)
        self.assertEqual(
            first,
            diary_event_key(
                username="VIEWER",
                identity=identity,
                watched_date=date(2026, 7, 28),
                occurrence=1,
            ),
        )

    def test_source_entry_id_is_stable_if_row_order_changes(self) -> None:
        identity = MovieIdentity("Arrival", 2016)
        kwargs = {
            "username": "viewer",
            "identity": identity,
            "watched_date": date(2026, 7, 28),
            "source_entry_id": "viewing-456",
        }

        self.assertEqual(
            diary_event_key(**kwargs, occurrence=1),
            diary_event_key(**kwargs, occurrence=9),
        )

    def test_resolver_reuses_backfilled_movie_with_same_numeric_letterboxd_id(self) -> None:
        existing = Movie(
            id=42,
            canonical_key="letterboxd:1255394",
            letterboxd_id="1255394",
            letterboxd_slug="the-odyssey-2026",
            title="The Odyssey",
            normalized_title="the odyssey",
            release_year=2026,
            poster_url="/film/the-odyssey-2026/image-150/",
        )
        session = _ExistingMovieSession(existing)
        resolver = MovieResolver(session, profile_sync_id=9)

        resolved = resolver.resolve(
            MovieIdentity(
                title="The Odyssey",
                release_year=2026,
                letterboxd_id="1255394",
                letterboxd_slug="the-odyssey-2026",
                poster_url="https://letterboxd.com/film/the-odyssey-2026/image-150/",
            )
        )

        self.assertIs(resolved, existing)
        self.assertEqual(session.added, [])
        self.assertEqual(resolved.last_seen_profile_sync_id, 9)
        self.assertTrue(resolved.poster_url.startswith("https://"))


class ProfileLoaderContractTests(unittest.TestCase):
    def _write_full_bundle(self, root: Path) -> None:
        pd.DataFrame(
            [{"Username": "viewer", "Display_Name": "Viewer", "Date Joined": "2020-01-02"}]
        ).to_csv(root / "profile.csv", index=False)
        pd.DataFrame(
            [
                {
                    "Title": "Arrival",
                    "Year": 2016,
                    "Rating": 4.5,
                    "Film_ID": "123",
                    "Slug": "arrival-2016",
                }
            ]
        ).to_csv(root / "films_comprehensive.csv", index=False)
        pd.DataFrame(
            [
                {
                    "Title": "Arrival",
                    "Year": 2016,
                    "Watched Date": "2026-07-28",
                    "Film_ID": "123",
                }
            ]
        ).to_csv(root / "diary.csv", index=False)
        pd.DataFrame(columns=["Name", "Year", "Is_Liked", "Film_ID"]).to_csv(
            root / "likes.csv", index=False
        )
        pd.DataFrame(columns=["Title", "Year", "Review"]).to_csv(root / "reviews.csv", index=False)
        pd.DataFrame(columns=["Title", "Year"]).to_csv(root / "watchlist.csv", index=False)
        pd.DataFrame(
            [{"List_Name": "Favorites", "List_URL": "/viewer/list/favorites/", "Film_Count": 1}]
        ).to_csv(root / "lists.csv", index=False)
        pd.DataFrame(
            [
                {
                    "List_Name": "Favorites",
                    "List_URL": "/viewer/list/favorites/",
                    "Position": 1,
                    "Title": "Arrival",
                    "Year": 2016,
                    "Film_ID": "123",
                }
            ]
        ).to_csv(root / "list_items.csv", index=False)
        pd.DataFrame(columns=["Position", "Title", "Year", "Film_ID"]).to_csv(
            root / "favorites.csv", index=False
        )
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "source_kind": "full_html_upload",
                    "username": "viewer",
                    "completed_datasets": [
                        "profile",
                        "favorites",
                        "films",
                        "diary",
                        "likes",
                        "reviews",
                        "watchlist",
                        "lists",
                        "list_items",
                    ],
                    "counts": {
                        "films": 1,
                        "diary": 1,
                        "likes": 0,
                        "reviews": 0,
                        "watchlist": 0,
                        "lists": 1,
                        "list_items": 1,
                        "favorites": 0,
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_complete_v2_bundle_and_join_date_alias_validate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_full_bundle(root)

            loaded = load_profile_data(str(root), "viewer")
            validate_import_bundle(loaded, require_full_manifest=True)

            self.assertEqual(loaded.join_date, date(2020, 1, 2))
            self.assertEqual(len(loaded.list_metadata), 1)
            self.assertEqual(sum(len(frame) for frame in loaded.lists), 1)
            self.assertEqual(loaded.lists[0].iloc[0]["list_name"], "/viewer/list/favorites/")

    def test_v2_bundle_fails_closed_on_missing_authoritative_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_full_bundle(root)
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["completed_datasets"].remove("favorites")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            loaded = load_profile_data(str(root), "viewer")
            with self.assertRaisesRegex(ValueError, "favorites"):
                validate_import_bundle(loaded, require_full_manifest=True)

    def test_v2_bundle_detects_manifest_count_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_full_bundle(root)
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["counts"]["diary"] = 99
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            loaded = load_profile_data(str(root), "viewer")
            with self.assertRaisesRegex(ValueError, "diary"):
                validate_import_bundle(loaded, require_full_manifest=True)

    def test_v2_bundle_preserves_and_rejects_mismatched_manifest_username(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_full_bundle(root)
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["username"] = "someone_else"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            loaded = load_profile_data(str(root), "viewer")

            self.assertEqual(loaded.manifest["username"], "someone_else")
            with self.assertRaisesRegex(ValueError, "does not match"):
                validate_import_bundle(loaded, require_full_manifest=True)

    def test_v2_bundle_requires_manifest_username(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_full_bundle(root)
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("username")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            loaded = load_profile_data(str(root), "viewer")

            self.assertNotIn("username", loaded.manifest)
            with self.assertRaisesRegex(ValueError, "manifest username is required"):
                validate_import_bundle(loaded, require_full_manifest=True)

    def test_v2_bundle_does_not_silently_replace_malformed_csv_with_empty_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_full_bundle(root)
            (root / "reviews.csv").write_text(
                'Name,Review\n"Arrival,unterminated\n', encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "reviews.csv"):
                load_profile_data(str(root), "viewer")

    def test_v2_bundle_cross_checks_likes_against_authoritative_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_full_bundle(root)
            films = pd.read_csv(root / "films_comprehensive.csv")
            films["Is_Liked"] = "Yes"
            films.to_csv(root / "films_comprehensive.csv", index=False)

            loaded = load_profile_data(str(root), "viewer")
            with self.assertRaisesRegex(ValueError, "Liked-film identity mismatch"):
                validate_import_bundle(loaded, require_full_manifest=True)

    def test_private_watchlist_is_accepted_only_when_explicitly_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_full_bundle(root)
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["completed_datasets"].remove("watchlist")
            manifest["unavailable_datasets"] = {"watchlist": "forbidden/private"}
            manifest["counts"].pop("watchlist")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "watchlist.csv").unlink()

            loaded = load_profile_data(str(root), "viewer")

            validate_import_bundle(loaded, require_full_manifest=True)
            self.assertNotIn("watchlist.csv", loaded.source_files)

    def test_missing_surface_without_completed_or_unavailable_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_full_bundle(root)
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["completed_datasets"].remove("watchlist")
            manifest["counts"].pop("watchlist")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "watchlist.csv").unlink()

            loaded = load_profile_data(str(root), "viewer")
            with self.assertRaisesRegex(ValueError, "unaccounted datasets: watchlist"):
                validate_import_bundle(loaded, require_full_manifest=True)

    def test_unavailable_list_items_reject_stale_legacy_list_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_full_bundle(root)
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["completed_datasets"].remove("lists")
            manifest["completed_datasets"].remove("list_items")
            manifest["unavailable_datasets"] = {
                "lists": "forbidden/private",
                "list_items": "forbidden/private",
            }
            manifest["counts"].pop("lists")
            manifest["counts"].pop("list_items")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "lists.csv").unlink()
            (root / "list_items.csv").unlink()
            legacy_dir = root / "lists"
            legacy_dir.mkdir()
            pd.DataFrame([{"Name": "Heat", "Year": 1995}]).to_csv(
                legacy_dir / "old-list.csv", index=False
            )

            loaded = load_profile_data(str(root), "viewer")

            with self.assertRaisesRegex(ValueError, "lists/old-list.csv"):
                validate_import_bundle(loaded, require_full_manifest=True)

    def test_legacy_list_directory_remains_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lists_dir = root / "lists"
            lists_dir.mkdir()
            pd.DataFrame([{"Name": "Heat", "Year": 1995}]).to_csv(
                lists_dir / "Crime.csv", index=False
            )

            loaded = load_profile_data(str(root), "viewer")

            self.assertEqual(len(loaded.lists), 1)
            self.assertEqual(loaded.lists[0].iloc[0]["list_name"], "Crime")


class CurrentLetterboxdMarkupTests(unittest.TestCase):
    @staticmethod
    def _profile_scraper_for_markup(markup: str) -> EnhancedLetterboxdScraper:
        scraper = EnhancedLetterboxdScraper.__new__(EnhancedLetterboxdScraper)
        scraper.username = "viewer"
        scraper.urls = {"profile": "https://letterboxd.com/viewer/"}
        scraper.profile_info = SimpleNamespace(
            display_name="",
            bio="",
            location="",
            website="",
            avatar_url="",
            total_films=0,
            following_count=0,
            followers_count=0,
            favorite_films=[],
        )
        scraper.completed_datasets = set()
        scraper.unavailable_datasets = {}
        response = SimpleNamespace(content=markup.encode("utf-8"))
        scraper.fetch_with_retry = Mock(return_value=response)
        return scraper

    def test_lazy_poster_extracts_numeric_uid_and_absolute_poster_url(self) -> None:
        soup = BeautifulSoup(
            """
            <div class="react-component" data-component-class="LazyPoster"
                 data-item-name="Challengers (2024)" data-item-slug="challengers"
                 data-item-link="/film/challengers/"
                 data-postered-identifier='{"lid":"zld0","uid":"film:842301"}'
                 data-poster-url="/film/challengers/image-150/">
              <img alt="Challengers" src="https://example.invalid/placeholder.png">
            </div>
            """,
            "html.parser",
        )

        identity = EnhancedLetterboxdScraper._poster_identity(soup.div)

        self.assertEqual(identity["film_id"], "842301")
        self.assertEqual(identity["year"], 2024)
        self.assertEqual(identity["poster_url"], "https://letterboxd.com/film/challengers/image-150/")

    def test_empty_state_whitespace_and_svg_rating_are_supported(self) -> None:
        empty = BeautifulSoup('<section class="empty-text">No  lists yet</section>', "html.parser")
        rating = BeautifulSoup('<svg class="glyph -rating" aria-label="★★★½"></svg>', "html.parser")
        scraper = EnhancedLetterboxdScraper.__new__(EnhancedLetterboxdScraper)

        self.assertTrue(scraper._declares_empty(empty, "lists"))
        self.assertEqual(scraper._extract_rating(rating), 3.5)

    def test_rewatch_status_is_read_from_the_table_cell_not_the_icon_span(self) -> None:
        markup = BeautifulSoup(
            """
            <table><tr>
              <td id="first" class="col-rewatch js-td-rewatch icon-status-off">
                <span class="has-icon icon-rewatch icon-16"></span>
              </td>
              <td id="second" class="col-rewatch js-td-rewatch">
                <span class="has-icon icon-rewatch icon-16"></span>
              </td>
            </tr></table>
            """,
            "html.parser",
        )

        self.assertFalse(EnhancedLetterboxdScraper._extract_rewatch(markup.select_one("#first")))
        self.assertTrue(EnhancedLetterboxdScraper._extract_rewatch(markup.select_one("#second")))

    def test_display_name_excludes_membership_badge(self) -> None:
        markup = BeautifulSoup(
            """
            <h1 class="person-display-name">
              <span class="displayname"><span class="label">Whiteknight03X</span></span>
              <span class="tail"><span class="badge">Patron</span></span>
            </h1>
            """,
            "html.parser",
        )

        self.assertEqual(
            EnhancedLetterboxdScraper._extract_display_name(markup),
            "Whiteknight03X",
        )

    def test_only_letterboxd_classified_403_is_treated_as_private(self) -> None:
        private = SimpleNamespace(
            status_code=403,
            text=(
                "<title>Letterboxd - Forbidden</title>"
                "The file you’re attempting to access is classified. "
                "Please contact us if you have the correct clearance."
            ),
        )
        generic = SimpleNamespace(status_code=403, text="Cloud protection challenge")

        self.assertTrue(EnhancedLetterboxdScraper._is_private_forbidden_response(private))
        self.assertFalse(EnhancedLetterboxdScraper._is_private_forbidden_response(generic))

    def test_favorites_are_authoritative_with_recognized_empty_container(self) -> None:
        scraper = self._profile_scraper_for_markup(
            '<main><h1>Viewer</h1><section id="favourites"></section></main>'
        )

        profile = scraper.scrape_profile_info()

        self.assertEqual(profile.favorite_films, [])
        self.assertIn("favorites", scraper.completed_datasets)

    def test_favorites_fail_closed_without_container_or_empty_evidence(self) -> None:
        scraper = self._profile_scraper_for_markup('<main><h1>Viewer</h1></main>')

        with self.assertRaisesRegex(
            RuntimeError,
            "no recognized favorites container or explicit empty state",
        ):
            scraper.scrape_profile_info()

        self.assertNotIn("favorites", scraper.completed_datasets)

    def test_explicit_favorites_empty_state_is_authoritative_without_container(self) -> None:
        scraper = self._profile_scraper_for_markup(
            "<main><h1>Viewer</h1><p>No favourite films</p></main>"
        )

        scraper.scrape_profile_info()

        self.assertIn("favorites", scraper.completed_datasets)

    def test_repeat_sync_removes_only_stale_unavailable_surface_csvs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            (output / "watchlist.csv").write_text("Title\\nArrival\\n", encoding="utf-8")
            (output / "lists.csv").write_text("Title\\nOld list\\n", encoding="utf-8")
            (output / "notes.txt").write_text("keep me", encoding="utf-8")
            (output / "favorites.csv").write_text("Name\\nHeat\\n", encoding="utf-8")
            legacy_lists = output / "lists"
            legacy_lists.mkdir()
            (legacy_lists / "old-list.csv").write_text("Name\\nHeat\\n", encoding="utf-8")
            (legacy_lists / "notes.txt").write_text("keep this too", encoding="utf-8")
            scraper = EnhancedLetterboxdScraper.__new__(EnhancedLetterboxdScraper)
            scraper.output_dir = str(output)
            scraper.unavailable_datasets = {
                "watchlist": "forbidden/private",
                "lists": "forbidden/private",
                "list_items": "forbidden/private",
            }

            scraper._remove_stale_unavailable_files()

            self.assertFalse((output / "watchlist.csv").exists())
            self.assertFalse((output / "lists.csv").exists())
            self.assertEqual((output / "notes.txt").read_text(encoding="utf-8"), "keep me")
            self.assertTrue((output / "favorites.csv").exists())
            self.assertFalse((legacy_lists / "old-list.csv").exists())
            self.assertEqual(
                (legacy_lists / "notes.txt").read_text(encoding="utf-8"),
                "keep this too",
            )


class LegacyLikeMappingTests(unittest.TestCase):
    @staticmethod
    def _profile(*, all_films: pd.DataFrame, likes: pd.DataFrame) -> SimpleNamespace:
        return SimpleNamespace(
            all_films=all_films,
            ratings=pd.DataFrame(),
            watched=pd.DataFrame(),
            diary=pd.DataFrame(),
            likes=likes,
        )

    def test_comprehensive_is_liked_column_maps_to_legacy_state(self) -> None:
        profile = self._profile(
            all_films=pd.DataFrame([{"Title": "Heat", "Year": 1995, "Is_Liked": "Yes"}]),
            likes=pd.DataFrame(),
        )

        movies = _build_legacy_movies(profile, 1, {})

        self.assertTrue(next(iter(movies.values()))["is_liked"])

    def test_presence_in_official_likes_csv_is_the_liked_signal(self) -> None:
        profile = self._profile(
            all_films=pd.DataFrame([{"Title": "Heat", "Year": 1995}]),
            likes=pd.DataFrame([{"Name": "Heat", "Year": 1995}]),
        )

        movies = _build_legacy_movies(profile, 1, {})

        self.assertTrue(next(iter(movies.values()))["is_liked"])


class LocalArchiveImportTests(unittest.TestCase):
    def test_direct_import_refreshes_dashboard_snapshot_with_http_upload_limits(self) -> None:
        session = Mock()
        with patch.object(import_local_archive, "AnalyticsRepository") as repository_class:
            repository_class.return_value.refresh_dashboard_analytics_snapshot.return_value = {
                "system_stats": {"total_profiles": 13}
            }

            snapshot = import_local_archive.refresh_dashboard_snapshot(session)

        repository_class.assert_called_once_with(session)
        repository_class.return_value.refresh_dashboard_analytics_snapshot.assert_called_once_with(
            group_limit=6,
            top_movies_limit=10,
        )
        self.assertEqual(snapshot["system_stats"]["total_profiles"], 13)


class CoverageUnavailableTests(unittest.TestCase):
    def test_private_watchlist_makes_coverage_partial_and_records_preservation(self) -> None:
        profile = SimpleNamespace(
            source_kind="full_html_upload",
            source_files={},
            manifest={"unavailable_datasets": {"watchlist": "forbidden/private"}},
        )
        authoritative = {
            "profile": True,
            "films": True,
            "diary": True,
            "reviews": True,
            "watchlist": False,
            "lists": True,
            "list_items": True,
        }

        coverage = _build_coverage(
            analyzer_profile=profile,
            imported_counts={},
            authoritative=authoritative,
            skipped_diary_rows=0,
            now=datetime.now(timezone.utc),
        )

        self.assertTrue(coverage["is_partial"])
        self.assertEqual(coverage["unavailable_datasets"]["watchlist"], "forbidden/private")
        self.assertTrue(any("prior imported state was preserved" in item for item in coverage["limitations"]))

if __name__ == "__main__":
    unittest.main()
