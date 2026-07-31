from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).with_name("postgres_restore_drill.py")
SPEC = importlib.util.spec_from_file_location("postgres_restore_drill", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
restore_drill = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(restore_drill)


class DatabaseUrlTests(unittest.TestCase):
    def test_postgres_tools_use_the_versioned_root_owned_installation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            install_root = Path(temporary_directory)
            expected = install_root / "16" / "bin" / "pg_dump"
            older = install_root / "15" / "bin" / "pg_dump"
            for candidate in (expected, older):
                candidate.parent.mkdir(parents=True)
                candidate.write_text("#!/bin/sh\n", encoding="utf-8")
                candidate.chmod(0o755)

            trusted_metadata = mock.Mock(st_mode=0o100755, st_uid=0)
            with (
                mock.patch.object(
                    restore_drill, "POSTGRES_INSTALL_ROOT", install_root
                ),
                mock.patch.object(
                    restore_drill.Path,
                    "lstat",
                    return_value=trusted_metadata,
                ),
            ):
                self.assertEqual(
                    restore_drill.trusted_postgres_executable("pg_dump"),
                    str(expected),
                )

    def test_parses_local_sqlalchemy_postgres_url_without_exposing_password(
        self,
    ) -> None:
        parsed = restore_drill.parse_database_url(
            "postgresql+psycopg://spyboxd:p%40ss%3Aword@127.0.0.1:5432/spyboxd"
        )

        self.assertEqual(parsed["host"], "127.0.0.1")
        self.assertEqual(parsed["port"], 5432)
        self.assertEqual(parsed["user"], "spyboxd")
        self.assertEqual(parsed["password"], "p@ss:word")
        self.assertEqual(parsed["database"], "spyboxd")

    def test_rejects_a_remote_database_host(self) -> None:
        with self.assertRaisesRegex(restore_drill.DrillError, "loopback"):
            restore_drill.parse_database_url(
                "postgresql+psycopg://spyboxd:secret@db.example.com/spyboxd"
            )

    def test_reads_one_strict_database_url_from_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_file = Path(temporary_directory) / "api.env"
            env_file.write_text(
                "OTHER=value\n"
                "DATABASE_URL='postgresql+psycopg://user:secret@127.0.0.1/db' # local\n",
                encoding="utf-8",
            )

            self.assertEqual(
                restore_drill.read_database_url(env_file),
                "postgresql+psycopg://user:secret@127.0.0.1/db",
            )

    def test_rejects_duplicate_database_url_definitions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_file = Path(temporary_directory) / "api.env"
            env_file.write_text(
                "DATABASE_URL=postgresql://user:one@127.0.0.1/db\n"
                "DATABASE_URL=postgresql://user:two@127.0.0.1/db\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(restore_drill.DrillError, "more than once"):
                restore_drill.read_database_url(env_file)

    def test_command_environment_replaces_inherited_postgres_settings(self) -> None:
        connection = {
            "host": "127.0.0.1",
            "port": 5432,
            "user": "spyboxd",
            "password": "correct-secret",
            "database": "spyboxd",
        }
        inherited = {
            "DATABASE_URL": "wrong",
            "PGHOST": "remote",
            "PGPASSWORD": "wrong-secret",
            "PATH": "/usr/bin",
        }

        with mock.patch.dict(os.environ, inherited, clear=True):
            environment = restore_drill.command_environment(connection, "restore_db")

        self.assertNotIn("DATABASE_URL", environment)
        self.assertEqual(environment["PGHOST"], "127.0.0.1")
        self.assertEqual(environment["PGPASSWORD"], "correct-secret")
        self.assertEqual(environment["PGDATABASE"], "restore_db")
        self.assertEqual(environment["PATH"], "/usr/bin")

    def test_failed_database_command_does_not_relay_private_stderr(self) -> None:
        relayed_stderr = io.StringIO()
        with contextlib.redirect_stderr(relayed_stderr):
            with self.assertRaisesRegex(restore_drill.DrillError, "python"):
                restore_drill.run_command(
                    [
                        sys.executable,
                        "-c",
                        "import sys; print('private-row-data', file=sys.stderr); sys.exit(1)",
                    ],
                    environment=os.environ.copy(),
                )

        self.assertNotIn("private-row-data", relayed_stderr.getvalue())

    def test_database_env_path_is_restricted_to_trusted_files(self) -> None:
        with mock.patch.dict(
            os.environ, {"SPYBOXD_DATABASE_ENV_FILE": "/tmp/untrusted.env"}, clear=False
        ):
            with self.assertRaisesRegex(restore_drill.DrillError, "trusted"):
                restore_drill.database_env_file()

    def test_database_env_defaults_only_to_dedicated_restore_credentials(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                restore_drill.database_env_file(),
                restore_drill.RESTORE_DATABASE_ENV_FILE,
            )

    def test_preflight_requires_createdb_but_rejects_superuser(self) -> None:
        accepted = ("spyboxd", "spyboxd_restore", True, False, False, 1024)
        self.assertEqual(
            restore_drill._validate_preflight_row(
                accepted,
                expected_database="spyboxd",
                expected_user="spyboxd_restore",
            ),
            1024,
        )
        with self.assertRaisesRegex(restore_drill.DrillError, "superuser"):
            restore_drill._validate_preflight_row(
                ("spyboxd", "spyboxd_restore", True, True, False, 1024),
                expected_database="spyboxd",
                expected_user="spyboxd_restore",
            )
        with self.assertRaisesRegex(restore_drill.DrillError, "NOCREATEDB"):
            restore_drill._validate_preflight_row(
                ("spyboxd", "spyboxd_restore", False, False, False, 1024),
                expected_database="spyboxd",
                expected_user="spyboxd_restore",
            )


class ArchiveSafetyTests(unittest.TestCase):
    def test_backup_parent_requires_exact_private_shared_directory_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            shared_dir = Path(temporary_directory).resolve() / "shared"
            backup_dir = shared_dir / "backups" / "postgresql"
            shared_dir.mkdir(mode=0o750)
            shared_dir.chmod(0o770)
            with (
                mock.patch.object(restore_drill, "SHARED_DIR", shared_dir),
                mock.patch.object(restore_drill, "BACKUP_DIR", backup_dir),
                self.assertRaisesRegex(restore_drill.DrillError, "exact mode 0750"),
            ):
                restore_drill.prepare_backup_directory()

            shared_dir.chmod(0o750)
            with (
                mock.patch.object(restore_drill, "SHARED_DIR", shared_dir),
                mock.patch.object(restore_drill, "BACKUP_DIR", backup_dir),
            ):
                self.assertEqual(restore_drill.prepare_backup_directory(), backup_dir)
            self.assertEqual(backup_dir.stat().st_mode & 0o777, 0o700)

    def test_stale_database_cleanup_accepts_only_exact_restore_role_owned_names(
        self,
    ) -> None:
        valid_name = "spyboxd_restore_verify_20260731014500_abcdef12"
        self.assertEqual(
            restore_drill._validated_stale_database_names(
                [(valid_name, "spyboxd_restore")],
                expected_owner="spyboxd_restore",
            ),
            [valid_name],
        )
        for rows in (
            [("spyboxd", "spyboxd_restore")],
            [(valid_name, "spyboxd")],
            [(valid_name, "spyboxd_restore"), (valid_name, "spyboxd_restore")],
        ):
            with self.assertRaises(restore_drill.DrillError):
                restore_drill._validated_stale_database_names(
                    rows,
                    expected_owner="spyboxd_restore",
                )

    def test_archive_listing_requires_every_core_dataset(self) -> None:
        valid_listing = "\n".join(
            f"123; 0 1 TABLE DATA public {table} spyboxd"
            for table in restore_drill.REQUIRED_TABLES
        )
        self.assertTrue(restore_drill.archive_contains_required_data(valid_listing))
        self.assertFalse(
            restore_drill.archive_contains_required_data(
                valid_listing.replace(
                    "TABLE DATA public reviews", "TABLE public reviews"
                )
            )
        )

    def test_retention_only_removes_exact_regular_archive_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            backup_dir = Path(temporary_directory)
            names = [
                "spyboxd-20260728T010000Z-00000001.dump",
                "spyboxd-20260729T010000Z-00000002.dump",
                "spyboxd-20260730T010000Z-00000003.dump",
                "spyboxd-20260731T010000Z-00000004.dump",
            ]
            for name in names:
                (backup_dir / name).write_bytes(b"archive")
                (backup_dir / f"{name}.sha256").write_text("checksum\n")
            unrelated = backup_dir / "operator-note.txt"
            unrelated.write_text("keep\n")
            symlink = backup_dir / "spyboxd-20260727T010000Z-00000000.dump"
            symlink.symlink_to(unrelated)

            restore_drill.prune_old_archives(backup_dir, retention=2)

            self.assertFalse((backup_dir / names[0]).exists())
            self.assertFalse((backup_dir / names[1]).exists())
            self.assertTrue((backup_dir / names[2]).exists())
            self.assertTrue((backup_dir / names[3]).exists())
            self.assertTrue(unrelated.exists())
            self.assertTrue(symlink.is_symlink())

    def test_retention_bounds_are_small_and_explicit(self) -> None:
        self.assertEqual(restore_drill.parse_retention(None), 3)
        self.assertEqual(restore_drill.parse_retention("2"), 2)
        self.assertEqual(restore_drill.parse_retention("7"), 7)
        for invalid in ("0", "1", "8", "all"):
            with self.assertRaises(restore_drill.DrillError):
                restore_drill.parse_retention(invalid)

    def test_stale_cleanup_only_removes_exact_work_dirs_and_orphan_checksums(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            backup_dir = Path(temporary_directory)
            stale_work = backup_dir / ".restore-drill-AbCd1234"
            stale_work.mkdir()
            (stale_work / "partial.dump").write_bytes(b"private")
            unrelated = backup_dir / ".restore-drill-not-an-exact-name"
            unrelated.mkdir()
            archive = backup_dir / "spyboxd-20260731T010000Z-00000004.dump"
            archive.write_bytes(b"archive")
            paired_checksum = backup_dir / f"{archive.name}.sha256"
            paired_checksum.write_text("keep\n")
            orphan_checksum = (
                backup_dir / "spyboxd-20260730T010000Z-00000003.dump.sha256"
            )
            orphan_checksum.write_text("remove\n")

            restore_drill.clean_stale_work_files(backup_dir)

            self.assertFalse(stale_work.exists())
            self.assertTrue(unrelated.exists())
            self.assertTrue(archive.exists())
            self.assertTrue(paired_checksum.exists())
            self.assertFalse(orphan_checksum.exists())

    def test_capacity_guard_requires_space_for_dump_restore_and_wal(self) -> None:
        disk_usage = mock.Mock()
        disk_usage.free = 4_000_000_000
        with mock.patch.object(
            restore_drill.shutil, "disk_usage", return_value=disk_usage
        ):
            restore_drill.require_restore_capacity(1_000_000_000, Path("/tmp"))

        disk_usage.free = 2_000_000_000
        with mock.patch.object(
            restore_drill.shutil, "disk_usage", return_value=disk_usage
        ):
            with self.assertRaisesRegex(restore_drill.DrillError, "insufficient"):
                restore_drill.require_restore_capacity(1_000_000_000, Path("/tmp"))


if __name__ == "__main__":
    unittest.main()
