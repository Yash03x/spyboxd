"""Call every panel builder against real production data, and prove it.

The gap this closes
-------------------
Four verification layers already run, and none of them answers the question
"do the panels work against the real data":

- pytest exercises the builders against SQLite, with fixtures;
- Playwright exercises the panels against *mocked* API responses;
- the public canary checks health, the aggregate dashboard, RSS, redirects and
  that every private route stays private;
- the authenticated canary checks identity and cross-profile isolation.

Every production defect this project has actually shipped lived in the space
none of those cover -- SQL that is valid in SQLite and wrong in Postgres, a
query that is instant on a fixture and twelve seconds on the real table, a
column whose real-world size took the API down. Those only appear when the real
builders meet the real database at its real size, which is what this does.

Safety
------
Read-only by construction, three ways over:

1. the transaction is opened READ ONLY, so a write raises rather than lands;
2. only `build_*` functions are called, and every other db-taking function is
   listed below with the reason it is excluded;
3. the session is rolled back and closed in a finally, never committed.

Completeness
------------
The builder list is derived by walking the API's own `services` package, not hand-written. A
function taking a database session that is neither swept nor explicitly
excluded fails the sweep. A new panel builder is therefore covered the moment
it exists, and a new writer has to be named before this passes -- silence is
never mistaken for coverage.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import pkgutil
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


# Functions that take a database session and are deliberately NOT called.
# Each entry is a promise that the exclusion was a decision, not an oversight;
# the sweep fails on anything reaching a session that is not named here or
# swept below.
EXCLUDED: Dict[str, str] = {
    # --- writers: excluded because this sweep must not mutate production ---
    "letterboxd_ratings.sync_letterboxd_ratings": "writes ratings; scraping job, not a panel",
    "tmdb_enrichment.enrich_movies": "writes enrichment rows; batch job, not a panel",
    "rss_incremental.poll_profile_feed": "writes watch events and performs network I/O",
    "rss_incremental.acquire_profile_feed_lease": "takes a lease other workers honour",
    "profile_ingestion_lock.lock_profile_ingestion": "takes an advisory lock ingestion honours",
    "profile_changes.capture_profile_state": "snapshot step of the change writer",
    "profile_changes.record_profile_changes": "writes the change ledger",
    "profile_access.ensure_app_user": "creates an app user row",
    "profile_access.provision_app_user_identity": "writes identity onto an app user",
    "profile_access.track_profile_by_id": "writes a tracking row",
    "profile_access.track_or_request_profile": "writes a tracking row or a request",
    "profile_access.untrack_profile": "deletes a tracking row",
    "profile_access.decide_profile_request": "resolves a request",
    "profile_access.fulfill_pending_requests": "resolves requests for a profile",
    "profile_access.reopen_fulfilled_requests_for_profile": "reopens requests",
    "profile_access.preserve_profile_tracking_requests": "rewrites request rows",
    # --- read-only, but need a Clerk identity this sweep deliberately lacks ---
    # Authorisation is what the authenticated canary proves, with a real
    # session and a real account. Faking a ClerkUser here would test this
    # script's idea of an identity rather than production's.
    "profile_access.accessible_profiles": "needs a real Clerk identity; covered by the auth canary",
    "profile_access.tracked_profiles": "needs a real Clerk identity; covered by the auth canary",
    "profile_access.list_profile_catalog": "needs a real Clerk identity; covered by the auth canary",
    "profile_access.authorize_profile_usernames": "authorisation path; covered by the auth canary",
    "profile_access.require_profile_access": "authorisation path; covered by the auth canary",
    "profile_access.list_profile_requests": "needs a real Clerk identity; covered by the auth canary",
    # --- read-only infrastructure with no panel behind it ---
    "rss_incremental.due_profiles": "scheduler input; RSS health is a canary check",
    "operational_health.rss_operational_report": "already asserted by the public canary",
    "profile_changes.get_recent_profile_changes": "swept through its own entry below",
}

# Latency ceilings, in seconds, measured on the real table. Generous on
# purpose: this is a regression alarm, not a benchmark. The filmographies panel
# once took twelve seconds in production while every test passed, which is the
# failure this budget exists to catch a second time.
DEFAULT_BUDGET_SECONDS = 4.0
BUDGET_OVERRIDES: Dict[str, float] = {
    # Genuinely heavy joins over the whole catalogue.
    "films.build_filmographies": 8.0,
    "films.build_atlas": 8.0,
    "films.build_keywords": 8.0,
    "tonight.build_availability": 8.0,
    "people.build_pair_blind_spots": 8.0,
}

# Single-profile builders run once per profile, which at twenty profiles would
# dominate the run. A sample is enough to prove the query executes and is
# quick; the group builders already touch every profile's rows.
SINGLE_PROFILE_SAMPLE = 3


@dataclass
class Result:
    name: str
    subject: str
    seconds: float
    size: Optional[int] = None
    error: Optional[str] = None
    over_budget: bool = False


@dataclass
class Sweep:
    results: List[Result] = field(default_factory=list)
    undeclared: List[str] = field(default_factory=list)
    stale_exclusions: List[str] = field(default_factory=list)

    @property
    def failures(self) -> List[Result]:
        return [r for r in self.results if r.error or r.over_budget]

    @property
    def ok(self) -> bool:
        return not self.failures and not self.undeclared and not self.stale_exclusions


def discover_session_functions(package: Any) -> Dict[str, Callable[..., Any]]:
    """Every public function in `services` whose first argument is a
    database session.

    Walked rather than listed: a builder that exists but is not swept is the
    exact blind spot this script is for.
    """

    found: Dict[str, Callable[..., Any]] = {}
    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        for attribute_name, attribute in vars(module).items():
            if attribute_name.startswith("_") or not inspect.isfunction(attribute):
                continue
            # Defined here, not imported from elsewhere -- otherwise a helper
            # re-exported across modules is swept several times.
            if attribute.__module__ != module.__name__:
                continue
            parameters = list(inspect.signature(attribute).parameters)
            if parameters and parameters[0] in {"db", "session", "db_session"}:
                found[f"{module_info.name}.{attribute_name}"] = attribute
    return found


def plan_call(
    name: str,
    function: Callable[..., Any],
    profiles: Sequence[Any],
) -> List[Tuple[str, Callable[[Any], Any]]]:
    """How to call one builder, from the shape of its signature.

    Deriving this from the signature rather than a table is what keeps a new
    `build_x(db, profiles)` covered without anybody remembering to add it.
    """

    parameters = list(inspect.signature(function).parameters)
    second = parameters[1] if len(parameters) > 1 else None

    if second == "profiles":
        return [("all profiles", lambda db: function(db, profiles))]
    if second == "profile":
        return [
            (profile.username, (lambda p: lambda db: function(db, p))(profile))
            for profile in profiles[:SINGLE_PROFILE_SAMPLE]
        ]
    if second == "pair" and len(profiles) >= 2:
        pair = list(profiles[:2])
        subject = " + ".join(profile.username for profile in pair)
        return [(subject, lambda db: function(db, pair, profiles))]
    return []


def measure(result_size: Any) -> Optional[int]:
    """A rough size signal, so a builder that starts returning nothing is
    visible in the log even when it does not raise."""

    if isinstance(result_size, dict):
        for key in ("entries", "rows", "items", "films", "profiles", "people"):
            value = result_size.get(key)
            if isinstance(value, list):
                return len(value)
        return len(result_size)
    if isinstance(result_size, list):
        return len(result_size)
    return None


def make_read_only(db: Any) -> None:
    """Ask Postgres to reject writes for this transaction.

    Silently a no-op on any engine without the statement (SQLite), because the
    exclusion list and the unconditional rollback are the guarantees that hold
    everywhere; this is the extra one that holds where it counts.
    """

    dialect = getattr(getattr(db, "bind", None), "dialect", None)
    if getattr(dialect, "name", None) != "postgresql":
        return

    # Imported after the check, not before it: on the path where this function
    # does nothing it should also need nothing, so the safety tests can run
    # anywhere without the database stack installed.
    from sqlalchemy import text

    db.execute(text("SET TRANSACTION READ ONLY"))


def run_sweep(session_factory: Callable[[], Any], profile_loader: Callable[[Any], List[Any]]) -> Sweep:
    import services as services_package

    sweep = Sweep()
    discovered = discover_session_functions(services_package)

    db = session_factory()
    try:
        # Belt and braces over the exclusion list: in a read-only transaction a
        # stray write raises instead of landing on production data. Postgres
        # only -- SQLite has no such statement, and the sweep's real run is
        # against Postgres, so a local SQLite run leans on the exclusion list
        # and the rollback alone.
        make_read_only(db)
        profiles = profile_loader(db)
        if len(profiles) < 2:
            raise SystemExit(
                f"the sweep needs at least two completed profiles, found {len(profiles)}"
            )

        for name in sorted(discovered):
            function = discovered[name]
            if name in EXCLUDED:
                continue
            if not name.split(".", 1)[1].startswith("build_"):
                sweep.undeclared.append(name)
                continue
            calls = plan_call(name, function, profiles)
            if not calls:
                sweep.undeclared.append(name)
                continue
            budget = BUDGET_OVERRIDES.get(name, DEFAULT_BUDGET_SECONDS)
            for subject, call in calls:
                started = time.monotonic()
                try:
                    payload = call(db)
                except Exception:  # noqa: BLE001 - the point is to report any failure
                    elapsed = time.monotonic() - started
                    sweep.results.append(
                        Result(name, subject, elapsed, error=traceback.format_exc(limit=6))
                    )
                    # A failed builder can leave the transaction unusable.
                    db.rollback()
                    make_read_only(db)
                    continue
                elapsed = time.monotonic() - started
                sweep.results.append(
                    Result(
                        name,
                        subject,
                        elapsed,
                        size=measure(payload),
                        over_budget=elapsed > budget,
                    )
                )
    finally:
        db.rollback()
        db.close()

    # An exclusion naming a function that no longer exists is a stale promise,
    # and hides the next function that takes its name.
    sweep.stale_exclusions = sorted(set(EXCLUDED) - set(discovered))
    return sweep


def load_completed_profiles(db: Any) -> List[Any]:
    from database.models import Profile

    return (
        db.query(Profile)
        .filter(Profile.scraping_status == "completed")
        .order_by(Profile.username)
        .all()
    )


def report(sweep: Sweep, *, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                {
                    "ok": sweep.ok,
                    "checked": len(sweep.results),
                    "undeclared": sweep.undeclared,
                    "stale_exclusions": sweep.stale_exclusions,
                    "failures": [
                        {
                            "builder": r.name,
                            "subject": r.subject,
                            "seconds": round(r.seconds, 3),
                            "error": r.error,
                            "over_budget": r.over_budget,
                        }
                        for r in sweep.failures
                    ],
                    "slowest": [
                        {"builder": r.name, "subject": r.subject, "seconds": round(r.seconds, 3)}
                        for r in sorted(sweep.results, key=lambda r: -r.seconds)[:10]
                    ],
                },
                indent=2,
            )
        )
        return

    print(f"panel sweep: {len(sweep.results)} builder calls against production data")
    for result in sorted(sweep.results, key=lambda r: -r.seconds)[:10]:
        size = "-" if result.size is None else str(result.size)
        print(f"  {result.seconds:6.2f}s  {size:>6}  {result.name} [{result.subject}]")

    for name in sweep.undeclared:
        print(f"UNDECLARED: {name} reaches the database and is neither swept nor excluded", file=sys.stderr)
    for name in sweep.stale_exclusions:
        print(f"STALE EXCLUSION: {name} no longer exists", file=sys.stderr)
    for result in sweep.failures:
        if result.error:
            print(f"FAILED: {result.name} [{result.subject}]\n{result.error}", file=sys.stderr)
        else:
            budget = BUDGET_OVERRIDES.get(result.name, DEFAULT_BUDGET_SECONDS)
            print(
                f"SLOW: {result.name} [{result.subject}] took {result.seconds:.2f}s, budget {budget:.1f}s",
                file=sys.stderr,
            )


def read_database_url(env_file: str) -> str:
    """Take only DATABASE_URL out of the API's environment file.

    Parsed here rather than in the calling shell for two reasons: the sweep
    needs one value out of a file full of production secrets, and sourcing the
    file would hand it all of them; and a `sed` inside a heredoc inside YAML is
    three quoting layers deep, which is where the last one of these went wrong.

    A value may be quoted, may be `export`ed, and may itself contain '=' -- a
    password routinely does -- so it is split once and unwrapped, not matched.
    """

    from pathlib import Path

    url: Optional[str] = None
    for raw_line in Path(env_file).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, separator, value = line.partition("=")
        if separator and key.strip() == "DATABASE_URL":
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            url = value
    if not url:
        raise SystemExit(f"{env_file} has no DATABASE_URL")
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--application-root",
        default=os.getenv("SPYBOXD_APPLICATION_ROOT", "/opt/spyboxd/current/backend"),
        help="the API's own import root -- the same PYTHONPATH the service unit uses,\n"
        "so the sweep imports exactly what production runs",
    )
    parser.add_argument(
        "--database-env-file",
        default=os.getenv("SPYBOXD_DATABASE_ENV_FILE"),
        help="file holding DATABASE_URL; only that one value is read from it",
    )
    arguments = parser.parse_args()

    if arguments.application_root not in sys.path:
        sys.path.insert(0, arguments.application_root)
    if arguments.database_env_file:
        os.environ["DATABASE_URL"] = read_database_url(arguments.database_env_file)

    from database.connection import SessionLocal

    sweep = run_sweep(SessionLocal, load_completed_profiles)
    report(sweep, as_json=arguments.json)
    return 0 if sweep.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
