from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import re
import secrets
import tempfile
import unittest

from deploy import postgres_restore_drill as drill


TEST_DATABASE_NAME_PATTERN = re.compile(r"(?:^|[_-])(?:ci|test|testing)(?:$|[_-])")


def _temporary_database_name() -> str:
    return (
        f"spyboxd_restore_verify_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_"
        f"{secrets.token_hex(4)}"
    )


class PostgreSQLRestoreIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        raw_url = os.getenv("SPYBOXD_TEST_DATABASE_URL", "").strip()
        if not raw_url:
            raise unittest.SkipTest(
                "Set SPYBOXD_TEST_DATABASE_URL to run the PostgreSQL restore test."
            )
        cls.connection = drill.parse_database_url(raw_url)
        if not TEST_DATABASE_NAME_PATTERN.search(
            str(cls.connection["database"]).casefold()
        ):
            raise RuntimeError(
                "restore integration tests require a loopback database with a "
                "standalone test, testing, or ci marker"
            )

    def test_custom_archive_restores_and_passes_the_production_contract(self) -> None:
        source_database = _temporary_database_name()
        restored_database = _temporary_database_name()
        created_databases: list[str] = []
        try:
            drill.create_temporary_database(self.connection, source_database)
            created_databases.append(source_database)
            with drill.connect(self.connection, source_database) as source:
                with source.cursor() as cursor:
                    for table in drill.REQUIRED_TABLES:
                        cursor.execute(
                            f'CREATE TABLE "{table}" (id integer PRIMARY KEY, value text NOT NULL)'
                        )
                        cursor.execute(
                            f'INSERT INTO "{table}" (id, value) VALUES (1, %s)',
                            (f"fixture-{table}",),
                        )
                    cursor.execute(
                        "CREATE TABLE alembic_version (version_num text PRIMARY KEY)"
                    )
                    cursor.execute(
                        "INSERT INTO alembic_version (version_num) VALUES (%s)",
                        ("restore_integration_fixture",),
                    )

            pg_dump = drill.trusted_postgres_executable("pg_dump")
            pg_restore = drill.trusted_postgres_executable("pg_restore")
            with tempfile.TemporaryDirectory() as temporary_directory:
                archive = Path(temporary_directory) / "database.dump"
                drill.run_command(
                    [
                        pg_dump,
                        "--format=custom",
                        "--compress=6",
                        "--no-password",
                        "--file",
                        str(archive),
                    ],
                    environment=drill.command_environment(
                        self.connection, source_database
                    ),
                )
                self.assertGreater(archive.stat().st_size, 0)
                listing = drill.run_command(
                    [pg_restore, "--list", str(archive)],
                    environment=drill.command_environment(
                        self.connection, source_database
                    ),
                    capture_output=True,
                ).stdout
                self.assertTrue(drill.archive_contains_required_data(listing))

                drill.create_temporary_database(self.connection, restored_database)
                created_databases.append(restored_database)
                drill.run_command(
                    [
                        pg_restore,
                        "--exit-on-error",
                        "--single-transaction",
                        "--no-owner",
                        "--no-privileges",
                        "--no-password",
                        "--dbname",
                        restored_database,
                        str(archive),
                    ],
                    environment=drill.command_environment(
                        self.connection, restored_database
                    ),
                )
                drill.validate_restored_database(
                    self.connection, restored_database
                )
                self.assertRegex(drill.sha256_file(archive), r"^[0-9a-f]{64}$")
        finally:
            for database in reversed(created_databases):
                drill.drop_temporary_database(self.connection, database)


if __name__ == "__main__":
    unittest.main()
