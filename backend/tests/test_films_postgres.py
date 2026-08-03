"""The Films queries against real PostgreSQL, which is the only place they run.

`test_library_sections.py` builds its fixtures on SQLite, so the two dialect
branches in `services/films.py` — the `jsonb_path_query_array` extraction of
director names, and the `->` JSON path into `raw_payload` — are never executed
there. Both are the kind of thing that passes every local test and then fails
in production, so they are exercised here against the database that actually
serves them.

Skipped without SPYBOXD_TEST_DATABASE_URL. CI sets it.
"""
from __future__ import annotations

import os
import unittest
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database.models import (
    Base,
    Movie,
    MovieEnrichment,
    Profile,
    ProfileFilm,
)
from services.films import build_collections, build_filmographies

# This file creates and DROPs a schema, so it reuses the migration suite's
# guard rather than trusting whatever SPYBOXD_TEST_DATABASE_URL points at:
# loopback host, and a database whose name says it is a test database.
from tests.test_additive_migrations import _validated_test_database_url


def _crew(*directors: str):
    """A TMDB-shaped crew: the directors buried among many other jobs."""

    crew = [
        {"job": "Director", "name": name, "department": "Directing", "id": index}
        for index, name in enumerate(directors)
    ]
    crew.extend(
        {"job": "Best Boy", "name": f"Someone {index}", "department": "Lighting", "id": 900 + index}
        for index in range(40)
    )
    return crew


@unittest.skipUnless(
    os.getenv("SPYBOXD_TEST_DATABASE_URL"),
    "Set SPYBOXD_TEST_DATABASE_URL to run the PostgreSQL Films queries.",
)
class FilmsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.database_url = _validated_test_database_url(
            os.environ["SPYBOXD_TEST_DATABASE_URL"]
        )
        cls.schema = f"spyboxd_films_test_{uuid.uuid4().hex[:16]}"
        cls.engine = create_engine(
            cls.database_url,
            future=True,
            pool_pre_ping=True,
            connect_args={"options": f"-csearch_path={cls.schema}"},
        )
        with create_engine(cls.database_url, future=True).begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{cls.schema}"'))
        cls.addClassCleanup(cls._drop_schema)
        # The whole schema: `movies` carries foreign keys into `profile_syncs`,
        # so a hand-picked subset does not create cleanly.
        Base.metadata.create_all(cls.engine)

    @classmethod
    def _drop_schema(cls) -> None:
        cls.engine.dispose()
        with create_engine(cls.database_url, future=True).begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{cls.schema}" CASCADE'))

    def setUp(self) -> None:
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.addCleanup(self.db.close)

    def _seed(self):
        """Two profiles, both holding the same two films, rating them apart."""

        left = Profile(username=f"left{uuid.uuid4().hex[:8]}", scraping_status="completed", is_active=True)
        right = Profile(username=f"right{uuid.uuid4().hex[:8]}", scraping_status="completed", is_active=True)
        self.db.add_all([left, right])
        self.db.flush()

        films = []
        for index, (title, collection) in enumerate(
            [("First", "A Series"), ("Second", "A Series")]
        ):
            movie = Movie(
                canonical_key=f"letterboxd:{title}-{uuid.uuid4().hex[:8]}",
                title=title,
                normalized_title=title.casefold(),
                release_year=2000 + index,
            )
            self.db.add(movie)
            self.db.flush()
            self.db.add(
                MovieEnrichment(
                    movie_id=movie.id,
                    credits={"cast": [{"name": "An Actor"}], "crew": _crew("Akira Kurosawa")},
                    raw_payload={"details": {"belongs_to_collection": {"name": collection}}},
                )
            )
            films.append(movie)

        # 5.0 and 3.0 on both films: the mean is 4.0, and neither holder's own
        # rating is 4.0, so a result of 4.0 can only come from averaging.
        for movie in films:
            self.db.add(ProfileFilm(profile_id=left.id, movie_id=movie.id, rating=5.0, tags=[], watch_count=1))
            self.db.add(ProfileFilm(profile_id=right.id, movie_id=movie.id, rating=3.0, tags=[], watch_count=1))
        self.db.commit()
        return [left, right]

    def test_director_names_come_back_from_the_jsonpath_extraction(self):
        """The crew list never leaves the database on PostgreSQL.

        This is the branch SQLite cannot reach: `jsonb_path_query_array` needs
        a jsonpath-typed argument, and getting that wrong raises
        UndefinedFunction at query time rather than at import.
        """

        profiles = self._seed()

        payload = build_filmographies(self.db, profiles)

        self.assertEqual([entry["director"] for entry in payload["directors"]], ["Akira Kurosawa"])
        self.assertEqual(payload["directors"][0]["films"], 2)
        self.assertEqual(sorted(payload["directors"][0]["titles"]), ["First", "Second"])

    def test_a_film_is_counted_once_however_many_people_hold_it(self):
        """Two holders, two films — not four."""

        profiles = self._seed()

        payload = build_filmographies(self.db, profiles)

        self.assertEqual(payload["directors"][0]["films"], 2)
        self.assertEqual(payload["coverage"]["films"], 2)
        self.assertEqual(payload["coverage"]["enriched"], 2)

    def test_the_rating_is_the_selection_s_mean_not_whoever_came_back_first(self):
        """5.0 and 3.0 average to 4.0; neither holder rated anything 4.0.

        Deduping in Python and keeping the first row's rating made this depend
        on the order the database happened to return.
        """

        profiles = self._seed()

        directors = build_filmographies(self.db, profiles)["directors"]
        series = build_collections(self.db, profiles)["series"]

        self.assertEqual(directors[0]["average_rating"], 4.0)
        self.assertEqual(series[0]["name"], "A Series")
        self.assertEqual(series[0]["average_rating"], 4.0)

    def test_the_collection_is_read_from_the_nested_tmdb_path(self):
        """`raw_payload["details"]["belongs_to_collection"]`, not the top level."""

        profiles = self._seed()

        payload = build_collections(self.db, profiles)

        self.assertEqual([entry["name"] for entry in payload["series"]], ["A Series"])
        self.assertEqual(payload["series"][0]["films"], 2)

    def test_the_crew_list_never_leaves_the_database(self):
        """The whole point of the jsonpath: /api/films/filmographies took 12s.

        Selecting `credits->'crew'` and filtering in Python shipped up to two
        hundred crew members per film, once per holder. The bare column must
        not reappear in a SELECT — only the path expression that reduces it to
        names.
        """

        from sqlalchemy import event  # noqa: PLC0415

        profiles = self._seed()
        statements: list[str] = []

        @event.listens_for(self.engine, "before_cursor_execute")
        def _record(_conn, _cursor, statement, _params, _context, _executemany):
            statements.append(statement)

        build_filmographies(self.db, profiles)
        event.remove(self.engine, "before_cursor_execute", _record)

        selected_crew = [
            statement
            for statement in statements
            if "credits -> " in statement and "jsonb_path_query_array" not in statement
        ]
        self.assertEqual(selected_crew, [], "the crew column was selected whole")
        self.assertTrue(
            any("jsonb_path_query_array" in statement for statement in statements),
            "no jsonpath extraction ran — this guard has stopped guarding",
        )

    def test_an_unenriched_film_contributes_no_director(self):
        """A null crew must not become an empty-string director."""

        profiles = self._seed()
        bare = Movie(
            canonical_key=f"letterboxd:bare-{uuid.uuid4().hex[:8]}",
            title="Unmatched",
            normalized_title="unmatched",
            release_year=1999,
        )
        self.db.add(bare)
        self.db.flush()
        self.db.add(
            ProfileFilm(profile_id=profiles[0].id, movie_id=bare.id, rating=4.0, tags=[], watch_count=1)
        )
        self.db.commit()

        payload = build_filmographies(self.db, profiles)

        self.assertEqual([entry["director"] for entry in payload["directors"]], ["Akira Kurosawa"])
        self.assertEqual(payload["coverage"]["films"], 3)
        self.assertEqual(payload["coverage"]["enriched"], 2)


if __name__ == "__main__":
    unittest.main()
