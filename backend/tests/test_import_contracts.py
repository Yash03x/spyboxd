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

from scraper_html import EnhancedLetterboxdScraper, ScrapeValidationError
from database.models import Movie
from services.import_contracts import (
    MovieIdentity,
    diary_event_key,
    movie_identity_from_row,
    parse_boolean,
    parse_tags,
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

    def _upgrade_bundle_to_v3(self, root: Path, *, account_social: bool = True) -> None:
        """Rewrite the v2 bundle's manifest as v3, optionally with social surfaces."""
        manifest = json.loads((root / "manifest.json").read_text())
        manifest["schema_version"] = 3
        if account_social:
            manifest["completed_datasets"] = manifest["completed_datasets"] + [
                "following",
                "followers",
            ]
            manifest["counts"]["following"] = 1
            manifest["counts"]["followers"] = 0
            pd.DataFrame(
                [{
                    "Position": 1,
                    "Username": "vaultedapathy",
                    "Display_Name": "🫀",
                    "Avatar_URL": "https://a.ltrbxd.com/x.jpg",
                    "Profile_URL": "https://letterboxd.com/vaultedapathy/",
                }]
            ).to_csv(root / "following.csv", index=False)
            pd.DataFrame(
                columns=["Position", "Username", "Display_Name", "Avatar_URL", "Profile_URL"]
            ).to_csv(root / "followers.csv", index=False)
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_v3_bundle_requires_social_surfaces_accounted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_full_bundle(root)
            self._upgrade_bundle_to_v3(root, account_social=False)

            loaded = load_profile_data(str(root), "viewer")
            with self.assertRaisesRegex(ValueError, "followers, following"):
                validate_import_bundle(loaded, require_full_manifest=True)

    def test_v3_bundle_with_social_surfaces_validates_and_loads_frames(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_full_bundle(root)
            self._upgrade_bundle_to_v3(root)

            loaded = load_profile_data(str(root), "viewer")
            validate_import_bundle(loaded, require_full_manifest=True)

            self.assertEqual(len(loaded.following), 1)
            self.assertEqual(loaded.following.iloc[0]["Username"], "vaultedapathy")
            self.assertEqual(len(loaded.followers), 0)
            self.assertIn("following.csv", loaded.source_files)

    def test_v3_bundle_count_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_full_bundle(root)
            self._upgrade_bundle_to_v3(root)
            manifest = json.loads((root / "manifest.json").read_text())
            manifest["counts"]["following"] = 5
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            loaded = load_profile_data(str(root), "viewer")
            with self.assertRaisesRegex(ValueError, "following: manifest=5, observed=1"):
                validate_import_bundle(loaded, require_full_manifest=True)

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

    def test_spoiler_review_uses_hidden_body_and_persists_spoiler_flag(self) -> None:
        scraper = EnhancedLetterboxdScraper.__new__(EnhancedLetterboxdScraper)
        scraper.username = "viewer"
        scraper.urls = {"reviews": "https://letterboxd.com/viewer/reviews/"}
        scraper.completed_datasets = set()
        scraper.unavailable_datasets = {}
        response = SimpleNamespace(
            content="""
                <main>
                  <article class="production-viewing">
                    <div class="react-component"
                         data-component-class="LazyPoster"
                         data-item-name="Predestination (2014)"
                         data-item-slug="predestination"
                         data-item-link="/film/predestination/"
                         data-postered-identifier='{"uid":"film:147509"}'>
                    </div>
                    <svg class="glyph -rating" aria-label="★★★★★"></svg>
                    <time class="timestamp" datetime="2023-06-19"></time>
                    <div class="js-review">
                      <p class="body-text -prose js-spoiler-container">
                        <em>This review may contain spoilers.
                          <a data-js-trigger="spoiler.reveal"
                             data-js-hide-on-trigger="spoiler.reveal">I can handle the truth.</a>
                        </em>
                      </p>
                      <div class="body-text -prose -reset js-review-body js-collapsible-text"
                           data-js-reveal-on-trigger="spoiler.reveal"
                           data-full-text-url="/s/full-text/viewing:403034793/"
                           hidden>
                        <p>Sarah Snook, a star is born. This is the DARK equivalent for movies.</p>
                      </div>
                      <p class="like-link-target" data-count="1"></p>
                    </div>
                  </article>
                </main>
            """.encode("utf-8")
        )
        scraper.fetch_with_retry = Mock(return_value=response)

        reviews = scraper.scrape_reviews()

        self.assertEqual(len(reviews), 1)
        self.assertEqual(
            reviews[0]["review_text"],
            "Sarah Snook, a star is born. This is the DARK equivalent for movies.",
        )
        self.assertNotIn("I can handle the truth", reviews[0]["review_text"])
        self.assertTrue(reviews[0]["contains_spoilers"])
        self.assertEqual(reviews[0]["rating"], 5.0)

        with tempfile.TemporaryDirectory() as temp_dir:
            scraper.output_dir = temp_dir
            scraper._save_reviews()
            persisted = pd.read_csv(Path(temp_dir) / "reviews.csv", keep_default_na=False)

        self.assertEqual(persisted.loc[0, "Review"], reviews[0]["review_text"])
        self.assertEqual(persisted.loc[0, "Contains_Spoilers"], "Yes")

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
            (output / "following.csv").write_text("Username\\nsomeone\\n", encoding="utf-8")
            (output / "followers.csv").write_text("Username\\nsomeone\\n", encoding="utf-8")
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
                "following": "crawl exceeded configured cap 5000",
                "followers": "forbidden/private",
            }

            scraper._remove_stale_unavailable_files()

            self.assertFalse((output / "watchlist.csv").exists())
            self.assertFalse((output / "lists.csv").exists())
            self.assertFalse((output / "following.csv").exists())
            self.assertFalse((output / "followers.csv").exists())
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


class SocialSurfaceScrapingTests(unittest.TestCase):
    """Following/followers capture: markup, pagination, caps, empty states."""

    PERSON_PAGE = """
        <main><table class="member-table"><tbody>
          <tr><td class="col-member table-person"><div class="person-summary">
            <a class="avatar -a40" href="/vaultedapathy/">
              <img alt="🫀" src="https://a.ltrbxd.com/resized/avatar/x.jpg" width="40"/></a>
            <h3 class="title-3"><a class="name" href="/vaultedapathy/"> 🫀 </a></h3>
            <small class="metadata"><a class="_nobr" href="/vaultedapathy/followers/">71 followers</a>,
              <a class="_nobr" href="/vaultedapathy/following/">following 65</a></small>
          </div></td></tr>
          <tr><td class="col-member table-person"><div class="person-summary">
            <a class="avatar -a40" href="/adireviews11/"><img alt="a" src="https://a.ltrbxd.com/a.jpg"/></a>
            <h3 class="title-3"><a class="name" href="/adireviews11/">adireviews11</a></h3>
          </div></td></tr>
        </tbody></table>
        {pagination}
        </main>
    """
    NEXT_LINK = '<div class="pagination"><div class="paginate-nextprev"><a class="next" href="{href}">Next</a></div></div>'

    @staticmethod
    def _people_scraper(following_count=None, followers_count=None) -> EnhancedLetterboxdScraper:
        scraper = EnhancedLetterboxdScraper.__new__(EnhancedLetterboxdScraper)
        scraper.username = "viewer"
        scraper.urls = {
            "following": "https://letterboxd.com/viewer/following/",
            "followers": "https://letterboxd.com/viewer/followers/",
        }
        scraper.profile_info = SimpleNamespace(
            following_count=following_count, followers_count=followers_count
        )
        scraper.social_data = {"following": [], "followers": [], "activity": []}
        scraper.completed_datasets = set()
        scraper.unavailable_datasets = {}
        return scraper

    def test_person_rows_extract_username_display_name_and_avatar(self) -> None:
        soup = BeautifulSoup(self.PERSON_PAGE.format(pagination=""), "html.parser")

        rows = EnhancedLetterboxdScraper._extract_person_rows(soup)

        self.assertEqual(
            rows[0],
            {
                "username": "vaultedapathy",
                "display_name": "🫀",
                "avatar_url": "https://a.ltrbxd.com/resized/avatar/x.jpg",
                "profile_url": "https://letterboxd.com/vaultedapathy/",
            },
        )
        self.assertEqual(rows[1]["username"], "adireviews11")

    def test_scrape_people_paginates_dedupes_and_saves_csv(self) -> None:
        scraper = self._people_scraper(following_count=3)
        page_1 = self.PERSON_PAGE.format(
            pagination=self.NEXT_LINK.format(href="/viewer/following/page/2/")
        )
        # Page 2 repeats one member (drift) and adds one more.
        page_2 = """
            <main><table><tbody>
              <tr><td class="table-person"><div class="person-summary">
                <a class="avatar" href="/adireviews11/"><img src="https://a.ltrbxd.com/a.jpg"/></a>
                <h3><a class="name" href="/adireviews11/">adireviews11</a></h3>
              </div></td></tr>
              <tr><td class="table-person"><div class="person-summary">
                <a class="avatar" href="/Maaxmc/"><img src="https://a.ltrbxd.com/m.jpg"/></a>
                <h3><a class="name" href="/Maaxmc/">Maaxmc</a></h3>
              </div></td></tr>
            </tbody></table></main>
        """
        pages = {
            "https://letterboxd.com/viewer/following/": page_1,
            "https://letterboxd.com/viewer/following/page/2/": page_2,
        }
        scraper.fetch_with_retry = Mock(
            side_effect=lambda url, **kwargs: SimpleNamespace(content=pages[url].encode("utf-8"))
        )

        with patch("scraper_html.time.sleep"):
            people = scraper.scrape_following()

        self.assertEqual(
            [person["username"] for person in people],
            ["vaultedapathy", "adireviews11", "Maaxmc"],
        )
        self.assertEqual([person["position"] for person in people], [1, 2, 3])
        self.assertIn("following", scraper.completed_datasets)

        with tempfile.TemporaryDirectory() as temp_dir:
            scraper.output_dir = temp_dir
            scraper._save_people("following")
            persisted = pd.read_csv(Path(temp_dir) / "following.csv", keep_default_na=False)
        self.assertEqual(list(persisted["Username"]), ["vaultedapathy", "adireviews11", "Maaxmc"])
        self.assertEqual(
            persisted.loc[0, "Profile_URL"], "https://letterboxd.com/vaultedapathy/"
        )

    def test_empty_surfaces_require_declared_empty_state(self) -> None:
        scraper = self._people_scraper()
        empty_following = "<main><p>viewer is not following anyone.</p></main>"
        empty_followers = "<main><p>viewer has no followers.</p></main>"
        pages = {
            "https://letterboxd.com/viewer/following/": empty_following,
            "https://letterboxd.com/viewer/followers/": empty_followers,
        }
        scraper.fetch_with_retry = Mock(
            side_effect=lambda url, **kwargs: SimpleNamespace(content=pages[url].encode("utf-8"))
        )

        self.assertEqual(scraper.scrape_following(), [])
        self.assertEqual(scraper.scrape_followers(), [])
        self.assertEqual(scraper.completed_datasets, {"following", "followers"})

        unrecognized = self._people_scraper()
        unrecognized.fetch_with_retry = Mock(
            return_value=SimpleNamespace(content=b"<main><p>something else</p></main>")
        )
        with self.assertRaisesRegex(ScrapeValidationError, "no recognized person rows"):
            unrecognized.scrape_following()

    def test_private_surface_is_preserved_not_failed(self) -> None:
        scraper = self._people_scraper()
        forbidden = SimpleNamespace(
            status_code=403,
            text="Letterboxd - Forbidden: the page you are attempting to access is classified. "
                 "You do not have the correct clearance.",
        )
        scraper.fetch_with_retry = Mock(return_value=forbidden)

        self.assertEqual(scraper.scrape_followers(), [])
        self.assertEqual(scraper.unavailable_datasets["followers"], "forbidden/private")

    def test_header_cap_marks_surface_unavailable(self) -> None:
        scraper = self._people_scraper(followers_count=9000)
        scraper.fetch_with_retry = Mock(side_effect=AssertionError("must not fetch"))

        self.assertEqual(scraper.scrape_followers(), [])
        self.assertIn("exceeds configured cap", scraper.unavailable_datasets["followers"])

    def test_count_drift_beyond_tolerance_fails_closed(self) -> None:
        scraper = self._people_scraper(following_count=25)
        scraper.fetch_with_retry = Mock(
            return_value=SimpleNamespace(
                content=self.PERSON_PAGE.format(pagination="").encode("utf-8")
            )
        )

        with self.assertRaisesRegex(ScrapeValidationError, "header reported 25"):
            scraper.scrape_following()

    def test_unparsed_header_count_skips_cross_check_but_keeps_data(self) -> None:
        # A header parse miss must not abort the scrape on a guessed zero, and
        # the live last-page pagination shape (disabled next span) must
        # terminate the crawl.
        scraper = self._people_scraper(following_count=None)
        last_page = self.PERSON_PAGE.format(
            pagination='<div class="pagination"><div class="paginate-nextprev paginate-disabled">'
                       '<span class="next">Next</span></div></div>'
        )
        scraper.fetch_with_retry = Mock(
            return_value=SimpleNamespace(content=last_page.encode("utf-8"))
        )

        people = scraper.scrape_following()

        self.assertEqual(len(people), 2)
        self.assertIn("following", scraper.completed_datasets)

    def test_in_loop_cap_stops_runaway_crawl_without_header_count(self) -> None:
        scraper = self._people_scraper(followers_count=None)
        page = self.PERSON_PAGE.format(
            pagination=self.NEXT_LINK.format(href="/viewer/followers/")  # endless loop page
        )
        scraper.fetch_with_retry = Mock(
            return_value=SimpleNamespace(content=page.encode("utf-8"))
        )

        with patch("scraper_html.time.sleep"), patch.dict(
            "scraper_html.os.environ", {"SPYBOXD_MAX_FOLLOW_EDGES_PER_SURFACE": "1"}
        ):
            result = scraper.scrape_followers()

        self.assertEqual(result, [])
        self.assertIn("exceeded configured cap", scraper.unavailable_datasets["followers"])

    def test_social_cap_env_parse_is_guarded(self) -> None:
        with patch.dict("scraper_html.os.environ", {"SPYBOXD_MAX_FOLLOW_EDGES_PER_SURFACE": "banana"}):
            self.assertEqual(EnhancedLetterboxdScraper._configured_social_cap(), 5000)
        with patch.dict("scraper_html.os.environ", {"SPYBOXD_MAX_FOLLOW_EDGES_PER_SURFACE": "-3"}):
            self.assertEqual(EnhancedLetterboxdScraper._configured_social_cap(), 5000)
        with patch.dict("scraper_html.os.environ", {"SPYBOXD_MAX_FOLLOW_EDGES_PER_SURFACE": "250"}):
            self.assertEqual(EnhancedLetterboxdScraper._configured_social_cap(), 250)

    def test_scraper_output_round_trips_through_loader_and_validation(self) -> None:
        # Producer-to-consumer: save_all_data's real CSVs + v3 manifest must
        # load and validate under the strict full-manifest contract.
        scraper = EnhancedLetterboxdScraper.__new__(EnhancedLetterboxdScraper)
        scraper.username = "viewer"
        scraper.profile_info = SimpleNamespace(
            username="viewer", display_name="Viewer", bio="", location="", website="",
            join_date=None, avatar_url="", total_films=1, total_reviews=0,
            total_lists=0, following_count=1, followers_count=None, favorite_films=[],
        )
        scraper.films_data = [{
            "title": "Challengers", "year": 2024, "rating": 4.0, "film_id": "842301",
            "slug": "challengers", "poster_url": "", "film_url": "https://letterboxd.com/film/challengers/",
            "has_review": False, "is_liked": False, "movie_id": "842301", "tags": [],
        }]
        scraper.diary_entries = []
        scraper.reviews_data = []
        scraper.watchlist_data = []
        scraper.lists_data = []
        scraper.list_items_data = []
        scraper.social_data = {
            "following": [{
                "position": 1, "username": "vaultedapathy", "display_name": "🫀",
                "avatar_url": "https://a.ltrbxd.com/x.jpg",
                "profile_url": "https://letterboxd.com/vaultedapathy/",
            }],
            "followers": [],
            "activity": [],
        }
        scraper.requested_datasets = {
            "profile", "favorites", "films", "diary", "likes", "reviews",
            "watchlist", "lists", "list_items", "following", "followers",
        }
        scraper.completed_datasets = set(scraper.requested_datasets) - {"followers"}
        scraper.unavailable_datasets = {"followers": "forbidden/private"}

        with tempfile.TemporaryDirectory() as temp_dir:
            scraper.output_dir = temp_dir
            scraper.save_all_data()

            loaded = load_profile_data(temp_dir, "viewer")
            validate_import_bundle(loaded, require_full_manifest=True)

            self.assertEqual(loaded.manifest["schema_version"], 3)
            self.assertEqual(len(loaded.following), 1)
            self.assertEqual(loaded.following.iloc[0]["Username"], "vaultedapathy")
            # Unavailable surface: no CSV, no counts entry, empty frame.
            self.assertEqual(len(loaded.followers), 0)
            self.assertNotIn("followers.csv", loaded.source_files)
            self.assertNotIn("followers", loaded.manifest["counts"])

    def test_v2_bundle_with_corrupt_social_csv_still_loads(self) -> None:
        # Deployed-parity: schema-v2 bundles predate the social contract, so a
        # stray unreadable following.csv must not fail the strict load.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ProfileLoaderContractTests._write_full_bundle(
                ProfileLoaderContractTests(), root
            )
            (root / "following.csv").write_bytes(b'"unterminated,quote\nrow')

            loaded = load_profile_data(str(root), "viewer")
            validate_import_bundle(loaded, require_full_manifest=True)

            self.assertEqual(len(loaded.following), 0)
            self.assertNotIn("following.csv", loaded.source_files)


class TagScrapingTests(unittest.TestCase):
    """Public tags-surface crawl: index parsing, per-tag matching, CSV contract."""

    TAG_INDEX_MARKUP = """
        <main>
          <ul class="js-tags-section tags tags-columns" data-check-action="/ajax/tag/check/films/">
            <li class="hoverable">
              <a href="/viewer/tag/mood-eerie/films/" title="mood, eerie">mood, eerie</a>
              <span class="detail -has-count"> 2 </span>
            </li>
            <li class="hoverable">
              <a href="/viewer/tag/profile/films/" title="profile">profile</a>
              <span class="detail -has-no-count"> </span>
            </li>
            <li class="hoverable">
              <a href="/viewer/tag/marathon/films/" title="marathon">marathon</a>
              <span class="detail -has-count"> 2.1K </span>
            </li>
            <li style="visibility:hidden"></li>
          </ul>
        </main>
    """

    @staticmethod
    def _tags_scraper() -> EnhancedLetterboxdScraper:
        scraper = EnhancedLetterboxdScraper.__new__(EnhancedLetterboxdScraper)
        scraper.username = "viewer"
        scraper.urls = {"tags": "https://letterboxd.com/viewer/tags/"}
        scraper.completed_datasets = set()
        scraper.unavailable_datasets = {}
        scraper.films_data = []
        scraper.diary_entries = []
        scraper.reviews_data = []
        scraper.lists_data = []
        return scraper

    def test_tag_index_parses_counts_including_singletons_and_abbreviations(self) -> None:
        soup = BeautifulSoup(self.TAG_INDEX_MARKUP, "html.parser")

        entries = EnhancedLetterboxdScraper._extract_tag_entries(soup)

        self.assertEqual(
            entries,
            [
                {"name": "mood, eerie", "slug": "mood-eerie", "count": 2},
                {"name": "profile", "slug": "profile", "count": 1},
                {"name": "marathon", "slug": "marathon", "count": None},
            ],
        )

    def test_tagless_kind_declares_empty_without_tags_section(self) -> None:
        soup = BeautifulSoup(
            "<main><section><p>No film tags yet</p></section></main>", "html.parser"
        )
        scraper = self._tags_scraper()

        self.assertEqual(EnhancedLetterboxdScraper._extract_tag_entries(soup), [])
        self.assertTrue(scraper._declares_empty(soup, "tags_films"))
        self.assertFalse(scraper._declares_empty(soup, "tags_diary"))

    def test_scrape_tags_attaches_across_surfaces_and_survives_csv_round_trip(self) -> None:
        scraper = self._tags_scraper()
        scraper.films_data = [
            {"title": "Challengers", "year": 2024, "film_id": "842301", "slug": "challengers"},
            {"title": "Heat", "year": 1995, "film_id": "51818", "slug": "heat-1995"},
        ]
        scraper.diary_entries = [
            {"title": "Challengers", "source_entry_id": "459597569", "is_rewatch": False,
             "is_liked": False, "has_review": True, "watch_date": "2026-07-01",
             "rating": 4.0, "year": 2024, "film_id": "842301", "slug": "challengers",
             "film_url": "/film/challengers/"},
        ]
        scraper.reviews_data = [
            {"title": "Challengers", "viewing_id": "459597569", "year": 2024,
             "rating": 4.0, "review_text": "x", "review_date": "2026-07-01",
             "review_likes": 0, "contains_spoilers": False, "is_rewatch": True,
             "film_id": "842301", "slug": "challengers", "film_url": "/film/challengers/"},
        ]
        scraper.lists_data = [
            {"title": "Best", "description": "", "film_count": 1, "url": "/viewer/list/best/"},
        ]

        index_films = """
            <main><ul class="js-tags-section">
              <li class="hoverable"><a href="/viewer/tag/mood-eerie/films/" title="mood, eerie">mood, eerie</a>
                <span class="detail -has-no-count"></span></li>
            </ul></main>
        """
        empty_diary = "<main><p>No diary tags yet</p></main>"
        index_reviews = """
            <main><ul class="js-tags-section">
              <li class="hoverable"><a href="/viewer/tag/mood-eerie/reviews/" title="mood, eerie">mood, eerie</a>
                <span class="detail -has-no-count"></span></li>
            </ul></main>
        """
        index_lists = """
            <main><ul class="js-tags-section">
              <li class="hoverable"><a href="/viewer/tag/favorites/lists/" title="favorites">favorites</a>
                <span class="detail -has-no-count"></span></li>
            </ul></main>
        """
        tag_films_page = """
            <main><ul class="poster-list">
              <li><div class="react-component" data-component-class="LazyPoster"
                   data-item-name="Challengers (2024)" data-item-slug="challengers"
                   data-item-link="/film/challengers/"
                   data-postered-identifier='{"uid":"film:842301"}'></div></li>
            </ul></main>
        """
        tag_reviews_page = """
            <main>
              <article class="production-viewing" data-object-id="viewing:459597569"
                       data-object-name="review"></article>
            </main>
        """
        tag_lists_page = """
            <main>
              <article class="list-summary js-list-summary">
                <h2 class="name prettify"><a href="/viewer/list/best/">Best</a></h2>
              </article>
            </main>
        """
        pages = {
            "https://letterboxd.com/viewer/tags/films/": index_films,
            "https://letterboxd.com/viewer/tags/diary/": empty_diary,
            "https://letterboxd.com/viewer/tags/reviews/": index_reviews,
            "https://letterboxd.com/viewer/tags/lists/": index_lists,
            "https://letterboxd.com/viewer/tag/mood-eerie/films/": tag_films_page,
            "https://letterboxd.com/viewer/tag/mood-eerie/reviews/": tag_reviews_page,
            "https://letterboxd.com/viewer/tag/favorites/lists/": tag_lists_page,
        }
        scraper.fetch_with_retry = Mock(
            side_effect=lambda url, **kwargs: SimpleNamespace(content=pages[url].encode("utf-8"))
        )

        with patch("scraper_html.time.sleep"):
            scraper.scrape_tags()

        self.assertEqual(scraper.films_data[0]["tags"], ["mood, eerie"])
        self.assertNotIn("tags", scraper.films_data[1])
        self.assertNotIn("tags", scraper.diary_entries[0])
        self.assertEqual(scraper.reviews_data[0]["tags"], ["mood, eerie"])
        self.assertEqual(scraper.lists_data[0]["tags"], ["favorites"])

        with tempfile.TemporaryDirectory() as temp_dir:
            scraper.output_dir = temp_dir
            scraper.completed_datasets = {"films", "reviews", "lists"}
            scraper._save_comprehensive_films()
            scraper._save_reviews()
            scraper._save_custom_lists()
            films_csv = pd.read_csv(Path(temp_dir) / "films_comprehensive.csv", keep_default_na=False)
            reviews_csv = pd.read_csv(Path(temp_dir) / "reviews.csv", keep_default_na=False)
            lists_csv = pd.read_csv(Path(temp_dir) / "lists.csv", keep_default_na=False)

        # A tag containing a comma must survive the CSV round trip through the
        # same parser ingestion uses; delimiter-splitting would corrupt it.
        self.assertEqual(parse_tags(films_csv.loc[0, "Tags"]), ["mood, eerie"])
        self.assertEqual(parse_tags(films_csv.loc[1, "Tags"]), [])
        self.assertEqual(parse_tags(reviews_csv.loc[0, "Tags"]), ["mood, eerie"])
        self.assertEqual(reviews_csv.loc[0, "Rewatch"], "Yes")
        self.assertEqual(parse_tags(lists_csv.loc[0, "Tags"]), ["favorites"])

    def test_tags_index_pagination_collects_all_pages(self) -> None:
        # Live tag indexes paginate at 120 tags per page; tags on page 2+ must
        # not be silently dropped (they would authoritatively erase DB tags).
        scraper = self._tags_scraper()
        scraper.films_data = [
            {"title": "Alpha", "year": 2020, "film_id": "1", "slug": "alpha"},
            {"title": "Beta", "year": 2021, "film_id": "2", "slug": "beta"},
        ]
        index_page_1 = """
            <main><ul class="js-tags-section">
              <li class="hoverable"><a href="/viewer/tag/one/films/" title="one">one</a>
                <span class="detail -has-no-count"></span></li>
            </ul>
            <div class="pagination"><a class="next" href="/viewer/tags/films/page/2/">Next</a></div>
            </main>
        """
        index_page_2 = """
            <main><ul class="js-tags-section">
              <li class="hoverable"><a href="/viewer/tag/two/films/" title="two">two</a>
                <span class="detail -has-no-count"></span></li>
            </ul></main>
        """
        def film_page(film_id, slug, name):
            return f"""
                <main><ul class="poster-list">
                  <li><div class="react-component" data-component-class="LazyPoster"
                       data-item-name="{name}" data-item-slug="{slug}"
                       data-item-link="/film/{slug}/"
                       data-postered-identifier='{{"uid":"film:{film_id}"}}'></div></li>
                </ul></main>
            """
        pages = {
            "https://letterboxd.com/viewer/tags/films/": index_page_1,
            "https://letterboxd.com/viewer/tags/films/page/2/": index_page_2,
            "https://letterboxd.com/viewer/tags/diary/": "<main><p>No diary tags yet</p></main>",
            "https://letterboxd.com/viewer/tags/reviews/": "<main><p>No review tags yet</p></main>",
            "https://letterboxd.com/viewer/tags/lists/": "<main><p>No list tags yet</p></main>",
            "https://letterboxd.com/viewer/tag/one/films/": film_page("1", "alpha", "Alpha (2020)"),
            "https://letterboxd.com/viewer/tag/two/films/": film_page("2", "beta", "Beta (2021)"),
        }
        scraper.fetch_with_retry = Mock(
            side_effect=lambda url, **kwargs: SimpleNamespace(content=pages[url].encode("utf-8"))
        )

        with patch("scraper_html.time.sleep"):
            scraper.scrape_tags()

        self.assertEqual(scraper.films_data[0]["tags"], ["one"])
        self.assertEqual(scraper.films_data[1]["tags"], ["two"])

    def test_per_tag_pagination_and_slug_fallback_matching(self) -> None:
        scraper = self._tags_scraper()
        scraper.films_data = [
            {"title": "Alpha", "year": 2020, "film_id": "1", "slug": "alpha"},
            {"title": "Beta", "year": 2021, "film_id": "2", "slug": "beta"},
        ]
        index_films = """
            <main><ul class="js-tags-section">
              <li class="hoverable"><a href="/viewer/tag/marathon/films/" title="marathon">marathon</a>
                <span class="detail -has-count">2</span></li>
            </ul></main>
        """
        tag_page_1 = """
            <main><ul class="poster-list">
              <li><div class="react-component" data-component-class="LazyPoster"
                   data-item-name="Alpha (2020)" data-item-slug="alpha"
                   data-item-link="/film/alpha/"
                   data-postered-identifier='{"uid":"film:1"}'></div></li>
            </ul>
            <div class="pagination"><a class="next" href="/viewer/tag/marathon/films/page/2/">Next</a></div>
            </main>
        """
        # Page 2's poster carries no numeric id anywhere: slug matching must apply.
        tag_page_2 = """
            <main><ul class="poster-list">
              <li><div class="react-component" data-component-class="LazyPoster"
                   data-item-name="Beta (2021)" data-item-slug="beta"
                   data-item-link="/film/beta/"></div></li>
            </ul></main>
        """
        pages = {
            "https://letterboxd.com/viewer/tags/films/": index_films,
            "https://letterboxd.com/viewer/tags/diary/": "<main><p>No diary tags yet</p></main>",
            "https://letterboxd.com/viewer/tags/reviews/": "<main><p>No review tags yet</p></main>",
            "https://letterboxd.com/viewer/tags/lists/": "<main><p>No list tags yet</p></main>",
            "https://letterboxd.com/viewer/tag/marathon/films/": tag_page_1,
            "https://letterboxd.com/viewer/tag/marathon/films/page/2/": tag_page_2,
        }
        scraper.fetch_with_retry = Mock(
            side_effect=lambda url, **kwargs: SimpleNamespace(content=pages[url].encode("utf-8"))
        )

        with patch("scraper_html.time.sleep"):
            scraper.scrape_tags()

        self.assertEqual(scraper.films_data[0]["tags"], ["marathon"])
        self.assertEqual(scraper.films_data[1]["tags"], ["marathon"])

    def test_per_tag_diary_pages_attach_by_viewing_id(self) -> None:
        scraper = self._tags_scraper()
        scraper.diary_entries = [
            {"title": "Alpha", "source_entry_id": "77"},
            {"title": "Beta", "source_entry_id": "88"},
        ]
        index_diary = """
            <main><ul class="js-tags-section">
              <li class="hoverable"><a href="/viewer/tag/cinema/diary/" title="cinema">cinema</a>
                <span class="detail -has-count">2</span></li>
            </ul></main>
        """
        tag_diary_page = """
            <main><table class="diary-table"><tbody>
              <tr class="diary-entry-row" data-viewing-id="77"></tr>
              <tr class="diary-entry-row" data-viewing-id="88"></tr>
            </tbody></table></main>
        """
        pages = {
            "https://letterboxd.com/viewer/tags/films/": "<main><p>No film tags yet</p></main>",
            "https://letterboxd.com/viewer/tags/diary/": index_diary,
            "https://letterboxd.com/viewer/tags/reviews/": "<main><p>No review tags yet</p></main>",
            "https://letterboxd.com/viewer/tags/lists/": "<main><p>No list tags yet</p></main>",
            "https://letterboxd.com/viewer/tag/cinema/diary/": tag_diary_page,
        }
        scraper.fetch_with_retry = Mock(
            side_effect=lambda url, **kwargs: SimpleNamespace(content=pages[url].encode("utf-8"))
        )

        with patch("scraper_html.time.sleep"):
            scraper.scrape_tags()

        self.assertEqual(scraper.diary_entries[0]["tags"], ["cinema"])
        self.assertEqual(scraper.diary_entries[1]["tags"], ["cinema"])

    def test_parse_tags_json_arrays_keep_sentinel_like_tag_names(self) -> None:
        # A tag literally named "null"/"nan" is real user text when it arrives
        # via the structured JSON path; only delimiter-split cells treat those
        # strings as missing values.
        self.assertEqual(parse_tags('["null", "nan", "NULL"]'), ["null", "nan"])
        self.assertEqual(parse_tags(["None"]), ["None"])
        self.assertEqual(parse_tags("nan, horror"), ["horror"])
        self.assertEqual(parse_tags("[]"), [])

    def test_forbidden_list_detail_marks_lists_surface_unavailable(self) -> None:
        scraper = self._tags_scraper()
        forbidden = SimpleNamespace(
            status_code=403,
            text="Letterboxd - Forbidden: the page you are attempting to access is classified. "
                 "You do not have the correct clearance.",
        )
        scraper.fetch_with_retry = Mock(return_value=forbidden)

        result = scraper._scrape_list_memberships(
            [{"title": "Secret", "url": "/viewer/list/secret/", "film_count": 3}]
        )

        self.assertEqual(result, [])
        self.assertIn("lists", scraper.unavailable_datasets)
        self.assertIn("list_items", scraper.unavailable_datasets)

    def test_scrape_tags_count_mismatch_fails_closed(self) -> None:
        scraper = self._tags_scraper()
        scraper.films_data = [
            {"title": "Challengers", "year": 2024, "film_id": "842301", "slug": "challengers"},
        ]
        index_films = """
            <main><ul class="js-tags-section">
              <li class="hoverable"><a href="/viewer/tag/watched-twice/films/" title="watched-twice">watched-twice</a>
                <span class="detail -has-count">2</span></li>
            </ul></main>
        """
        tag_films_page = """
            <main><ul class="poster-list">
              <li><div class="react-component" data-component-class="LazyPoster"
                   data-item-name="Challengers (2024)" data-item-slug="challengers"
                   data-item-link="/film/challengers/"
                   data-postered-identifier='{"uid":"film:842301"}'></div></li>
            </ul></main>
        """
        pages = {
            "https://letterboxd.com/viewer/tags/films/": index_films,
            "https://letterboxd.com/viewer/tags/diary/": "<main><p>No diary tags yet</p></main>",
            "https://letterboxd.com/viewer/tags/reviews/": "<main><p>No review tags yet</p></main>",
            "https://letterboxd.com/viewer/tags/lists/": "<main><p>No list tags yet</p></main>",
            "https://letterboxd.com/viewer/tag/watched-twice/films/": tag_films_page,
        }
        scraper.fetch_with_retry = Mock(
            side_effect=lambda url, **kwargs: SimpleNamespace(content=pages[url].encode("utf-8"))
        )

        with patch("scraper_html.time.sleep"):
            with self.assertRaisesRegex(ScrapeValidationError, "reported 2 entries"):
                scraper.scrape_tags()

    def test_attach_tags_rejects_unknown_viewing_and_list(self) -> None:
        scraper = self._tags_scraper()

        with self.assertRaisesRegex(ScrapeValidationError, "not found in scraped diary"):
            scraper._attach_tags({}, {"999": {"tag"}}, {}, {})
        with self.assertRaisesRegex(ScrapeValidationError, "not found in scraped lists"):
            scraper._attach_tags({}, {}, {}, {"/viewer/list/gone/": {"tag"}})

    def test_review_listing_rewatch_and_viewing_id_extraction(self) -> None:
        article = BeautifulSoup(
            """
            <article class="production-viewing" data-object-id="viewing:1421719449">
              <span class="attribution-detail">
                <a href="/viewer/film/elysium-2013/" class="context"> Rewatched </a>
                <span class="date"><time class="timestamp" datetime="2026-07-29">29 Jul 2026</time></span>
              </span>
            </article>
            """,
            "html.parser",
        ).article
        watched = BeautifulSoup(
            '<article><a class="context"> Watched </a></article>', "html.parser"
        ).article

        self.assertEqual(EnhancedLetterboxdScraper._extract_viewing_id(article), "1421719449")
        self.assertTrue(EnhancedLetterboxdScraper._extract_review_rewatch(article))
        self.assertFalse(EnhancedLetterboxdScraper._extract_review_rewatch(watched))
        self.assertEqual(EnhancedLetterboxdScraper._extract_viewing_id(watched), "")

    def test_list_detail_metadata_extraction(self) -> None:
        ranked = BeautifulSoup(
            """
            <main>
              <p class="list-date">
                <span class="published is-updated">Published
                  <time datetime="2026-01-11T07:15:06.720Z" class="timeago"></time></span>
                <span class="updated">Updated
                  <time datetime="2026-07-25T14:25:26.004Z" class="timeago"></time></span>
              </p>
              <ul class="poster-list -grid">
                <li class="posteritem numbered-list-item" data-owner-rating="10">
                  <p class="list-number">1</p>
                </li>
              </ul>
            </main>
            """,
            "html.parser",
        )
        unranked = BeautifulSoup(
            """
            <main>
              <p class="list-date"><span class="published">Published
                <time datetime="2024-02-01T00:00:00Z" class="timeago"></time></span></p>
              <ul class="poster-list"><li class="posteritem"></li></ul>
            </main>
            """,
            "html.parser",
        )

        ranked_meta = EnhancedLetterboxdScraper._extract_list_detail_metadata(ranked)
        unranked_meta = EnhancedLetterboxdScraper._extract_list_detail_metadata(unranked)

        self.assertEqual(
            ranked_meta,
            {
                "is_ranked": True,
                "published_date": "2026-01-11T07:15:06.720Z",
                "updated_date": "2026-07-25T14:25:26.004Z",
            },
        )
        self.assertEqual(
            unranked_meta,
            {"is_ranked": False, "published_date": "2024-02-01T00:00:00Z", "updated_date": ""},
        )


if __name__ == "__main__":
    unittest.main()
