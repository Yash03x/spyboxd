"""Reset the canary identities to the guardian's bootstrap state, on the VPS.

The authenticated canary accepts exactly two starting states: both canary
identities absent from ``app_users`` (bootstrap — the browser flow provisions
them itself), or both fully provisioned. Replacing a deleted Clerk account
leaves a third state the guardian rightly refuses: the survivor still
provisioned, the newcomer absent, and an orphaned row from the dead account
still claiming a canary profile.

This script deletes exactly the canary rows and nothing else:

- ``app_users`` rows whose ``clerk_user_id`` is one of the two configured
  canary IDs, or whose ``letterboxd_username`` is one of the two configured
  canary profiles (that second clause is what catches the orphan)
- their ``user_tracked_profiles`` rows
- their ``profile_access_requests`` rows (a mis-onboarded canary files a
  request for a profile that does not exist, which otherwise sits in the
  admin queue forever)

Profiles and imported history are never touched: untracking and unclaiming
delete nothing from the append-only store.

DRY RUN BY DEFAULT. Without ``--execute`` it reports what it would delete and
changes nothing. It refuses outright if any matched row belongs to a
configured administrator, whatever flags are set.
"""

from __future__ import annotations

import argparse
import re
import stat
import sys
from pathlib import Path


USER_ID_PATTERN = re.compile(r"^user_[A-Za-z0-9]+$")
PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9_]{2,15}$")
DATABASE_CONNECT_TIMEOUT_SECONDS = 10


class CanaryResetError(RuntimeError):
    pass


def _read_secure_env(path: Path) -> dict[str, str]:
    """The guardian's reader, byte for byte in behaviour: regular file, not
    world-accessible, KEY=VALUE lines."""

    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CanaryResetError("a required VPS configuration file is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CanaryResetError("VPS configuration must use regular files")
    if metadata.st_mode & 0o007:
        raise CanaryResetError("VPS configuration must not be world-accessible")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise CanaryResetError("a required VPS configuration file could not be read") from exc
    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _mask(value: str) -> str:
    """Enough to recognise, not enough to reuse."""

    if len(value) <= 6:
        return "…"
    return f"{value[:5]}…{value[-3:]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True,
                        help="staged file carrying the four SPYBOXD_CANARY_* values")
    parser.add_argument("--api-env", type=Path, default=Path("/etc/spyboxd/api.env"))
    parser.add_argument("--execute", action="store_true",
                        help="actually delete; the default is a dry run that changes nothing")
    args = parser.parse_args()

    staged = _read_secure_env(args.env_file)
    user_ids = []
    profiles = []
    for label in ("A", "B"):
        user_id = staged.get(f"SPYBOXD_CANARY_USER_{label}_ID", "")
        profile = staged.get(f"SPYBOXD_CANARY_PROFILE_{label}", "")
        if not USER_ID_PATTERN.fullmatch(user_id):
            raise CanaryResetError(f"canary user id {label} is malformed")
        if not PROFILE_PATTERN.fullmatch(profile):
            raise CanaryResetError(f"canary profile {label} is malformed")
        user_ids.append(user_id)
        profiles.append(profile.casefold())
    if len(set(user_ids)) != 2 or len(set(profiles)) != 2:
        raise CanaryResetError("canary identities must be two distinct users and profiles")

    api_values = _read_secure_env(args.api_env)
    database_url = api_values.get("DATABASE_URL", "")
    if not database_url:
        raise CanaryResetError("the production database URL is unavailable")
    admin_ids = {
        value.strip()
        for value in api_values.get("CLERK_ADMIN_USER_IDS", "").split(",")
        if value.strip()
    }
    if set(user_ids) & admin_ids:
        raise CanaryResetError("a configured canary identity is an administrator; refusing")

    try:
        from sqlalchemy import create_engine, text
    except ImportError as exc:
        raise CanaryResetError("the backend environment cannot reach the database") from exc

    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": DATABASE_CONNECT_TIMEOUT_SECONDS},
    )
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            rows = connection.execute(
                text(
                    """
                    SELECT id, clerk_user_id, letterboxd_username
                    FROM app_users
                    WHERE clerk_user_id = ANY(:user_ids)
                       OR lower(coalesce(letterboxd_username, '')) = ANY(:profiles)
                    """
                ),
                {"user_ids": user_ids, "profiles": profiles},
            ).fetchall()

            for row in rows:
                if row.clerk_user_id in admin_ids:
                    raise CanaryResetError(
                        "a matched row belongs to an administrator; refusing to touch anything"
                    )

            if not rows:
                print("canary reset: nothing matched — state is already bootstrap")
                return 0

            ids = [row.id for row in rows]
            tracked = connection.execute(
                text("SELECT count(*) FROM user_tracked_profiles WHERE user_id = ANY(:ids)"),
                {"ids": ids},
            ).scalar_one()
            requests = connection.execute(
                text("SELECT count(*) FROM profile_access_requests WHERE user_id = ANY(:ids)"),
                {"ids": ids},
            ).scalar_one()

            for row in rows:
                origin = "configured id" if row.clerk_user_id in user_ids else "orphan claiming a canary profile"
                print(
                    f"canary reset: matched app_user {_mask(row.clerk_user_id)} "
                    f"bound to {row.letterboxd_username or '(no profile)'} — {origin}"
                )
            print(
                f"canary reset: {'deleting' if args.execute else 'DRY RUN — would delete'} "
                f"{len(rows)} identity row(s), {tracked} tracked-profile row(s), "
                f"{requests} pending request(s). Profiles and history are untouched."
            )

            if not args.execute:
                # The no-write promise is structural: the transaction that saw
                # the rows is rolled back, never committed.
                transaction.rollback()
                return 0

            connection.execute(
                text("DELETE FROM user_tracked_profiles WHERE user_id = ANY(:ids)"), {"ids": ids}
            )
            connection.execute(
                text("DELETE FROM profile_access_requests WHERE user_id = ANY(:ids)"),
                {"ids": ids},
            )
            connection.execute(text("DELETE FROM app_users WHERE id = ANY(:ids)"), {"ids": ids})
            transaction.commit()
            print("canary reset: done — the guardian will provision both identities on its next run")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CanaryResetError as error:
        print(f"canary reset failed: {error}", file=sys.stderr)
        sys.exit(1)
