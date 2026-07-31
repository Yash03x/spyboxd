#!/usr/bin/env python3
"""Create and prove a recoverable PostgreSQL backup without exporting production data."""

from __future__ import annotations

import fcntl
import hashlib
import ipaddress
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import unquote, urlsplit

RESTORE_DATABASE_ENV_FILE = Path("/etc/spyboxd/restore-drill.env")
ALLOWED_DATABASE_ENV_FILES = {RESTORE_DATABASE_ENV_FILE}
POSTGRES_INSTALL_ROOT = Path("/usr/lib/postgresql")
RELEASE_LOCK = Path("/opt/spyboxd/.release.lock")
SHARED_DIR = Path("/opt/spyboxd/shared")
BACKUP_DIR = SHARED_DIR / "backups" / "postgresql"
ARCHIVE_PATTERN = re.compile(r"^spyboxd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\.dump$")
CHECKSUM_PATTERN = re.compile(r"^spyboxd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\.dump\.sha256$")
WORK_DIRECTORY_PATTERN = re.compile(r"^\.restore-drill-[A-Za-z0-9_-]{8}$")
TEMP_DATABASE_PATTERN = re.compile(r"^spyboxd_restore_verify_[0-9]{14}_[0-9a-f]{8}$")
REQUIRED_TABLES = ("profiles", "movies", "watch_events", "reviews")
DEFAULT_RETENTION = 3
MIN_RETENTION = 2
MAX_RETENTION = 7
COMMAND_TIMEOUT_SECONDS = 30 * 60
MIN_FREE_SPACE_BYTES = 1024 * 1024 * 1024


class DrillError(RuntimeError):
    """A safe, user-facing restore drill failure."""


class TerminationRequested(DrillError):
    """The restore drill was asked to terminate."""


def log(message: str) -> None:
    print(f"[spyboxd-restore-drill] {message}", flush=True)


def fail(message: str) -> NoReturn:
    raise DrillError(message)


def _handle_termination(signum: int, _frame: object) -> NoReturn:
    raise TerminationRequested(f"received signal {signum}")


def _decode_dotenv_value(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""
    lexer = shlex.shlex(value, posix=True)
    lexer.commenters = "#"
    lexer.whitespace_split = True
    tokens = list(lexer)
    if len(tokens) != 1:
        fail("DATABASE_URL in the database environment file is malformed")
    return tokens[0]


def read_database_url(env_path: Path) -> str:
    if env_path.is_symlink() or not env_path.is_file():
        fail("the production database environment file must be a regular file")

    database_url: str | None = None
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DrillError(
            "the production database environment file is not readable"
        ) from exc

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, raw_value = stripped.partition("=")
        if not separator or key.strip() != "DATABASE_URL":
            continue
        if database_url is not None:
            fail(
                "the production database environment file defines DATABASE_URL more than once"
            )
        database_url = _decode_dotenv_value(raw_value)

    if not database_url or "REPLACE_WITH" in database_url:
        fail("the production database environment file has no usable DATABASE_URL")
    return database_url


def parse_database_url(database_url: str) -> dict[str, str | int]:
    normalized = database_url
    if normalized.startswith("postgresql+psycopg://"):
        normalized = "postgresql://" + normalized.removeprefix("postgresql+psycopg://")
    elif normalized.startswith("postgres://"):
        normalized = "postgresql://" + normalized.removeprefix("postgres://")

    parsed = urlsplit(normalized)
    if parsed.scheme != "postgresql" or parsed.query or parsed.fragment:
        fail("DATABASE_URL must be a plain local PostgreSQL URL")
    if not parsed.username or parsed.password is None or not parsed.hostname:
        fail("DATABASE_URL must include a database user, password, and local host")

    try:
        port = parsed.port or 5432
    except ValueError as exc:
        raise DrillError("DATABASE_URL has an invalid port") from exc

    host = parsed.hostname
    if host == "localhost":
        host = "127.0.0.1"
    else:
        try:
            if not ipaddress.ip_address(host).is_loopback:
                fail("the restore drill only accepts a loopback PostgreSQL host")
        except ValueError as exc:
            raise DrillError(
                "the restore drill requires a literal loopback PostgreSQL host"
            ) from exc

    database = unquote(parsed.path.removeprefix("/"))
    username = unquote(parsed.username)
    password = unquote(parsed.password)
    if not database or "/" in database or not username or not password:
        fail("DATABASE_URL contains an invalid database, user, or password")
    if not 1 <= port <= 65535:
        fail("DATABASE_URL has an invalid port")

    return {
        "host": host,
        "port": port,
        "user": username,
        "password": password,
        "database": database,
    }


def parse_retention(raw_value: str | None) -> int:
    if raw_value is None or raw_value == "":
        return DEFAULT_RETENTION
    if not raw_value.isdecimal():
        fail("SPYBOXD_BACKUP_RETENTION must be an integer")
    retention = int(raw_value)
    if not MIN_RETENTION <= retention <= MAX_RETENTION:
        fail(
            f"SPYBOXD_BACKUP_RETENTION must be between {MIN_RETENTION} and "
            f"{MAX_RETENTION}"
        )
    return retention


def database_env_file() -> Path:
    configured = Path(
        os.getenv("SPYBOXD_DATABASE_ENV_FILE", str(RESTORE_DATABASE_ENV_FILE))
    )
    if configured not in ALLOWED_DATABASE_ENV_FILES:
        fail("SPYBOXD_DATABASE_ENV_FILE must name a trusted Spyboxd environment file")
    return configured


@contextmanager
def production_lock():
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(RELEASE_LOCK, flags, 0o600)
    except OSError as exc:
        raise DrillError("the production release lock is unavailable") from exc
    try:
        lock_info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(lock_info.st_mode)
            or lock_info.st_uid != os.geteuid()
            or stat.S_IMODE(lock_info.st_mode) & 0o022
        ):
            fail("the production release lock is not a trusted deploy-owned file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DrillError(
                "another Spyboxd release, rollback, or restore drill is running"
            ) from exc
        yield
    finally:
        os.close(descriptor)


def _require_secure_directory(path: Path, *, create: bool) -> None:
    if path.is_symlink():
        fail(f"refusing a symlinked backup path: {path}")
    if not path.exists():
        if not create:
            fail(f"required directory is missing: {path}")
        try:
            path.mkdir(mode=0o700)
        except OSError as exc:
            raise DrillError(
                f"cannot create the on-host backup directory: {path}"
            ) from exc
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise DrillError(f"cannot inspect backup path: {path}") from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        fail(
            f"backup path must be a real directory owned by the deploy account: {path}"
        )
    if stat.S_IMODE(info.st_mode) & 0o077:
        fail(f"backup path must not be accessible to group or other users: {path}")


def prepare_backup_directory() -> Path:
    if SHARED_DIR.is_symlink() or not SHARED_DIR.is_dir():
        fail("the trusted Spyboxd shared directory is unavailable")
    shared_info = SHARED_DIR.stat(follow_symlinks=False)
    if (
        shared_info.st_uid != os.geteuid()
        or stat.S_IMODE(shared_info.st_mode) != 0o750
    ):
        fail(
            "the Spyboxd shared directory must be deploy-owned with exact mode 0750"
        )

    backups_parent = BACKUP_DIR.parent
    _require_secure_directory(backups_parent, create=True)
    _require_secure_directory(BACKUP_DIR, create=True)
    if BACKUP_DIR.resolve(strict=True) != BACKUP_DIR:
        fail("the PostgreSQL backup directory does not resolve to its trusted path")
    return BACKUP_DIR


def clean_stale_work_files(backup_dir: Path) -> None:
    for candidate in backup_dir.iterdir():
        if candidate.is_symlink() or not WORK_DIRECTORY_PATTERN.fullmatch(
            candidate.name
        ):
            continue
        try:
            info = candidate.stat(follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid():
            shutil.rmtree(candidate)

    retained_archives = {
        path.name
        for path in backup_dir.iterdir()
        if path.is_file()
        and not path.is_symlink()
        and ARCHIVE_PATTERN.fullmatch(path.name)
    }
    for candidate in backup_dir.iterdir():
        if (
            candidate.is_file()
            and not candidate.is_symlink()
            and CHECKSUM_PATTERN.fullmatch(candidate.name)
            and candidate.name.removesuffix(".sha256") not in retained_archives
        ):
            candidate.unlink()


def command_environment(
    connection: dict[str, str | int], database: str
) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "DATABASE_URL",
            "PGDATABASE",
            "PGHOST",
            "PGPASSWORD",
            "PGPORT",
            "PGSERVICE",
            "PGSERVICEFILE",
            "PGUSER",
        }
    }
    environment.update(
        {
            "PGCONNECT_TIMEOUT": "10",
            "PGDATABASE": database,
            "PGHOST": str(connection["host"]),
            "PGPASSWORD": str(connection["password"]),
            "PGPORT": str(connection["port"]),
            "PGUSER": str(connection["user"]),
        }
    )
    return environment


def trusted_postgres_executable(name: str) -> str:
    if name not in {"pg_dump", "pg_restore"}:
        fail("only the required PostgreSQL archive tools may be resolved")
    try:
        version_directories = sorted(
            (
                path
                for path in POSTGRES_INSTALL_ROOT.iterdir()
                if path.name.isdigit() and path.is_dir() and not path.is_symlink()
            ),
            key=lambda path: int(path.name),
            reverse=True,
        )
    except OSError as exc:
        raise DrillError("the trusted PostgreSQL installation is unavailable") from exc

    for version_directory in version_directories:
        candidate = version_directory / "bin" / name
        try:
            executable_info = candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise DrillError(f"cannot inspect the {name} executable") from exc
        if (
            stat.S_ISREG(executable_info.st_mode)
            and executable_info.st_uid == 0
            and not stat.S_IMODE(executable_info.st_mode) & 0o022
            and os.access(candidate, os.X_OK)
        ):
            return str(candidate)
        fail(f"{name} must be a root-owned, non-writable system executable")
    fail(
        f"{name} must be installed under "
        "/usr/lib/postgresql/<major>/bin on the production VPS"
    )


def run_command(
    arguments: list[str],
    *,
    environment: dict[str, str],
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments,
            check=True,
            env=environment,
            text=True,
            stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise DrillError(f"timed out while running {Path(arguments[0]).name}") from exc
    except subprocess.CalledProcessError as exc:
        raise DrillError(f"{Path(arguments[0]).name} failed") from exc


def connect(
    connection: dict[str, str | int], database: str, *, autocommit: bool = False
):
    try:
        import psycopg
    except ImportError as exc:
        raise DrillError(
            "the active Spyboxd Python environment has no psycopg"
        ) from exc

    try:
        return psycopg.connect(
            host=connection["host"],
            port=connection["port"],
            user=connection["user"],
            password=connection["password"],
            dbname=database,
            connect_timeout=10,
            autocommit=autocommit,
        )
    except psycopg.Error as exc:
        raise DrillError("could not connect to the local PostgreSQL database") from exc


def _validate_preflight_row(
    row: Any, *, expected_database: str, expected_user: str
) -> int:
    if not isinstance(row, (tuple, list)) or len(row) != 6:
        fail("the PostgreSQL identity preflight returned an unexpected result")
    if row[0] != expected_database or row[1] != expected_user:
        fail("the PostgreSQL identity preflight returned an unexpected result")
    if row[4]:
        fail("the configured production database must not be a template database")
    if row[3]:
        fail("the restore-drill role must not be a PostgreSQL superuser")
    if not row[2]:
        fail(
            "the dedicated restore-drill role cannot create an isolated restore "
            "database; keep the application role NOCREATEDB and provision only the "
            "separate restore role with CREATEDB"
        )
    database_size = row[5]
    if (
        not isinstance(database_size, int)
        or isinstance(database_size, bool)
        or database_size <= 0
    ):
        fail("the production database size preflight returned an invalid result")
    return database_size


def preflight_database(connection: dict[str, str | int]) -> int:
    database = str(connection["database"])
    with connect(connection, database) as database_connection:
        with database_connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    current_database(),
                    current_user,
                    COALESCE(role.rolcreatedb, false),
                    COALESCE(role.rolsuper, false),
                    COALESCE(db.datistemplate, true),
                    pg_database_size(current_database())
                FROM pg_roles AS role
                JOIN pg_database AS db ON db.datname = current_database()
                WHERE role.rolname = current_user
                """
            )
            row = cursor.fetchone()
    return _validate_preflight_row(
        row,
        expected_database=database,
        expected_user=str(connection["user"]),
    )


def require_restore_capacity(database_size: int, backup_dir: Path) -> None:
    required_free = max(MIN_FREE_SPACE_BYTES, database_size * 3)
    root_free = shutil.disk_usage(Path("/")).free
    backup_free = shutil.disk_usage(backup_dir).free
    if min(root_free, backup_free) < required_free:
        fail(
            "insufficient free VPS storage for a backup plus isolated restore; "
            "no archive was created"
        )


def create_temporary_database(
    connection: dict[str, str | int], temporary_database: str
) -> None:
    if not TEMP_DATABASE_PATTERN.fullmatch(temporary_database):
        fail("refusing to create an invalid restore database name")
    from psycopg import sql

    with connect(connection, str(connection["database"]), autocommit=True) as admin:
        with admin.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = %s)",
                (temporary_database,),
            )
            if cursor.fetchone()[0]:
                fail("the generated restore database already exists")
            cursor.execute(
                sql.SQL("CREATE DATABASE {} WITH TEMPLATE template0").format(
                    sql.Identifier(temporary_database)
                )
            )


def drop_temporary_database(
    connection: dict[str, str | int], temporary_database: str
) -> None:
    if not TEMP_DATABASE_PATTERN.fullmatch(temporary_database):
        fail("refusing to drop an invalid restore database name")
    from psycopg import sql

    with connect(connection, str(connection["database"]), autocommit=True) as admin:
        with admin.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(temporary_database)
                )
            )


def _validated_stale_database_names(rows: Any, *, expected_owner: str) -> list[str]:
    if not isinstance(rows, list):
        fail("the stale restore database inventory is invalid")
    names: list[str] = []
    for row in rows:
        if not isinstance(row, (tuple, list)) or len(row) != 2:
            fail("the stale restore database inventory is invalid")
        name, owner = row
        if (
            not isinstance(name, str)
            or not TEMP_DATABASE_PATTERN.fullmatch(name)
            or owner != expected_owner
            or name in names
        ):
            fail("the stale restore database inventory is unsafe")
        names.append(name)
    return names


def clean_stale_restore_databases(connection: dict[str, str | int]) -> None:
    database = str(connection["database"])
    expected_owner = str(connection["user"])
    with connect(connection, database) as database_connection:
        with database_connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT db.datname, role.rolname
                FROM pg_database AS db
                JOIN pg_roles AS role ON role.oid = db.datdba
                WHERE db.datname ~ %s AND role.rolname = current_user
                ORDER BY db.datname
                """,
                (TEMP_DATABASE_PATTERN.pattern,),
            )
            rows = cursor.fetchall()
    stale_databases = _validated_stale_database_names(
        rows,
        expected_owner=expected_owner,
    )
    for stale_database in stale_databases:
        drop_temporary_database(connection, stale_database)
    if stale_databases:
        log(
            f"Removed {len(stale_databases)} stale restore database(s) from an interrupted drill"
        )


def archive_contains_required_data(archive_listing: str) -> bool:
    return all(
        re.search(rf"\bTABLE DATA public {re.escape(table)}\b", archive_listing)
        for table in REQUIRED_TABLES
    )


def validate_restored_database(
    connection: dict[str, str | int], temporary_database: str
) -> None:
    with connect(connection, temporary_database) as restored:
        with restored.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                """
            )
            tables = {row[0] for row in cursor.fetchall()}
            missing_tables = set(REQUIRED_TABLES) - tables
            if missing_tables or "alembic_version" not in tables:
                fail("the isolated restore is missing required application tables")

            for table in REQUIRED_TABLES:
                cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
                if cursor.fetchone()[0] <= 0:
                    fail("the isolated restore contains an empty required dataset")

            cursor.execute("SELECT COUNT(*), MIN(version_num) FROM alembic_version")
            migration_count, migration_version = cursor.fetchone()
            if migration_count != 1 or not migration_version:
                fail("the isolated restore has invalid Alembic migration state")

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM pg_index AS index_state
                JOIN pg_class AS relation ON relation.oid = index_state.indexrelid
                JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public' AND NOT index_state.indisvalid
                """
            )
            if cursor.fetchone()[0] != 0:
                fail("the isolated restore contains invalid indexes")

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM pg_constraint AS constraint_state
                JOIN pg_namespace AS namespace
                  ON namespace.oid = constraint_state.connamespace
                WHERE namespace.nspname = 'public'
                  AND NOT constraint_state.convalidated
                """
            )
            if cursor.fetchone()[0] != 0:
                fail("the isolated restore contains unvalidated constraints")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prune_old_archives(backup_dir: Path, retention: int) -> None:
    archives = sorted(
        (
            path
            for path in backup_dir.iterdir()
            if path.is_file()
            and not path.is_symlink()
            and ARCHIVE_PATTERN.fullmatch(path.name)
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    for archive in archives[retention:]:
        checksum = archive.with_name(f"{archive.name}.sha256")
        archive.unlink()
        if checksum.is_file() and not checksum.is_symlink():
            checksum.unlink()


def run_restore_drill() -> None:
    os.umask(0o077)
    retention = parse_retention(os.getenv("SPYBOXD_BACKUP_RETENTION"))
    env_file = database_env_file()
    database_url = read_database_url(env_file)
    try:
        api_info = env_file.stat(follow_symlinks=False)
    except OSError as exc:
        raise DrillError(
            "the production database environment file is unavailable"
        ) from exc
    if (
        api_info.st_uid != 0
        or api_info.st_gid != os.getegid()
        or stat.S_IMODE(api_info.st_mode) != 0o640
    ):
        fail(
            "the restore-drill environment file must be root-owned, grouped to the "
            "deploy account's primary group, and mode 0640"
        )

    connection = parse_database_url(database_url)
    database_size = preflight_database(connection)
    clean_stale_restore_databases(connection)
    backup_dir = prepare_backup_directory()
    clean_stale_work_files(backup_dir)
    require_restore_capacity(database_size, backup_dir)

    pg_dump = trusted_postgres_executable("pg_dump")
    pg_restore = trusted_postgres_executable("pg_restore")

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    temporary_database = (
        f"spyboxd_restore_verify_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_"
        f"{os.urandom(4).hex()}"
    )
    work_dir = Path(tempfile.mkdtemp(prefix=".restore-drill-", dir=backup_dir))
    archive = work_dir / "database.dump"
    checksum_file = work_dir / "database.dump.sha256"
    restore_database_created = False
    verified = False

    try:
        log("Creating a consistent on-host PostgreSQL archive")
        run_command(
            [
                pg_dump,
                "--format=custom",
                "--compress=6",
                "--serializable-deferrable",
                "--lock-wait-timeout=30s",
                "--no-password",
                "--file",
                str(archive),
            ],
            environment=command_environment(connection, str(connection["database"])),
        )
        if archive.is_symlink() or not archive.is_file() or archive.stat().st_size <= 0:
            fail("pg_dump did not produce a non-empty regular archive")
        archive.chmod(0o600)

        listing = run_command(
            [pg_restore, "--list", str(archive)],
            environment=command_environment(connection, str(connection["database"])),
            capture_output=True,
        ).stdout
        if not archive_contains_required_data(listing):
            fail("the PostgreSQL archive omits required application table data")

        create_temporary_database(connection, temporary_database)
        restore_database_created = True
        log("Restoring the archive into an isolated temporary database")
        run_command(
            [
                pg_restore,
                "--exit-on-error",
                "--single-transaction",
                "--no-owner",
                "--no-privileges",
                "--no-password",
                "--dbname",
                temporary_database,
                str(archive),
            ],
            environment=command_environment(connection, temporary_database),
        )
        validate_restored_database(connection, temporary_database)
        verified = True
    finally:
        drill_failed = sys.exc_info()[0] is not None
        cleanup_error: Exception | None = None
        if restore_database_created:
            try:
                drop_temporary_database(connection, temporary_database)
            except Exception as exc:  # cleanup failure must fail the drill
                cleanup_error = exc
        if drill_failed:
            shutil.rmtree(work_dir, ignore_errors=True)
        if cleanup_error is not None:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise DrillError(
                "could not remove the isolated restore database; manual intervention is required"
            ) from cleanup_error

    if not verified:
        shutil.rmtree(work_dir, ignore_errors=True)
        fail("the PostgreSQL archive did not complete restore verification")

    archive_name = f"spyboxd-{timestamp}-{os.urandom(4).hex()}.dump"
    if not ARCHIVE_PATTERN.fullmatch(archive_name):
        shutil.rmtree(work_dir, ignore_errors=True)
        fail("generated an invalid backup archive name")
    final_archive = backup_dir / archive_name
    final_checksum = backup_dir / f"{archive_name}.sha256"
    digest = sha256_file(archive)
    checksum_file.write_text(f"{digest}  {archive_name}\n", encoding="ascii")
    checksum_file.chmod(0o600)
    if final_archive.exists() or final_archive.is_symlink():
        shutil.rmtree(work_dir, ignore_errors=True)
        fail("refusing to overwrite an existing backup archive")
    if final_checksum.exists() or final_checksum.is_symlink():
        shutil.rmtree(work_dir, ignore_errors=True)
        fail("refusing to overwrite an existing backup checksum")
    try:
        os.link(checksum_file, final_checksum, follow_symlinks=False)
        os.link(archive, final_archive, follow_symlinks=False)
    except OSError as exc:
        final_archive.unlink(missing_ok=True)
        final_checksum.unlink(missing_ok=True)
        shutil.rmtree(work_dir, ignore_errors=True)
        raise DrillError("could not retain the verified on-host archive") from exc
    shutil.rmtree(work_dir)

    if sha256_file(final_archive) != digest:
        final_archive.unlink(missing_ok=True)
        final_checksum.unlink(missing_ok=True)
        fail("the retained on-host archive failed its final checksum")

    prune_old_archives(backup_dir, retention)
    log(
        "Verified a consistent backup through an isolated restore; "
        "retained it only on the production VPS"
    )


def main() -> int:
    for signal_name in ("SIGTERM", "SIGINT", "SIGHUP"):
        if hasattr(signal, signal_name):
            signal.signal(getattr(signal, signal_name), _handle_termination)
    try:
        with production_lock():
            run_restore_drill()
    except DrillError as exc:
        print(f"[spyboxd-restore-drill] ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print(
            "[spyboxd-restore-drill] ERROR: unexpected restore-drill failure",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
