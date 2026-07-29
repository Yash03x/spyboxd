"""Production health checks that do not expose operational secrets.

Liveness deliberately remains independent of the database.  Readiness verifies
that PostgreSQL is reachable and stamped at the exact Alembic head shipped with
this checkout.  RSS status is aggregate-only so it is safe to expose to an
external monitor without leaking profile names, feed URLs, or raw error text.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import case, func, or_, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from database.models import Profile, ProfileFeedState


REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = REPO_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_PATH = REPO_ROOT / "alembic"
DEFAULT_RSS_INTERVAL_SECONDS = 2 * 60 * 60
DEFAULT_RSS_STALE_AFTER_SECONDS = 4 * DEFAULT_RSS_INTERVAL_SECONDS


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def repository_schema_heads() -> set[str]:
    """Return the migration heads bundled with this application checkout."""

    config = Config(str(ALEMBIC_CONFIG_PATH))
    # An absolute location makes the check independent of the process cwd.
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_PATH))
    return set(ScriptDirectory.from_config(config).get_heads())


def readiness_report(database_engine: Engine, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Check database connectivity and exact Alembic revision parity.

    The result contains stable reason codes rather than exception messages so a
    failed probe cannot reveal a database URL, hostname, driver detail, or SQL.
    """

    checked_at = _iso_utc(now or _utc_now())
    try:
        expected_heads = repository_schema_heads()
    except Exception:
        return {
            "status": "not_ready",
            "checked_at": checked_at,
            "reason": "repository_schema_unavailable",
            "checks": {"database": "unknown", "schema": "unavailable"},
        }

    try:
        with database_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return {
            "status": "not_ready",
            "checked_at": checked_at,
            "reason": "database_unavailable",
            "checks": {"database": "unavailable", "schema": "unknown"},
            "schema": {"expected_revisions": sorted(expected_heads)},
        }

    try:
        with database_engine.connect() as connection:
            current_heads = {
                str(row[0])
                for row in connection.execute(text("SELECT version_num FROM alembic_version"))
            }
    except Exception:
        return {
            "status": "not_ready",
            "checked_at": checked_at,
            "reason": "schema_revision_unavailable",
            "checks": {"database": "ok", "schema": "unavailable"},
            "schema": {"expected_revisions": sorted(expected_heads)},
        }

    if current_heads != expected_heads:
        return {
            "status": "not_ready",
            "checked_at": checked_at,
            "reason": "schema_revision_mismatch",
            "checks": {"database": "ok", "schema": "mismatch"},
            "schema": {
                "current_revisions": sorted(current_heads),
                "expected_revisions": sorted(expected_heads),
            },
        }

    return {
        "status": "ready",
        "checked_at": checked_at,
        "checks": {"database": "ok", "schema": "current"},
        "schema": {"current_revisions": sorted(current_heads)},
    }


def rss_stale_after_seconds() -> int:
    """Resolve a forgiving monitoring window from production configuration."""

    interval = _positive_int_env(
        "SPYBOXD_RSS_POLL_INTERVAL_SECONDS",
        DEFAULT_RSS_INTERVAL_SECONDS,
    )
    return _positive_int_env(
        "SPYBOXD_RSS_HEALTH_STALE_AFTER_SECONDS",
        max(interval * 4, DEFAULT_RSS_STALE_AFTER_SECONDS),
    )


def rss_operational_report(
    db: Session,
    *,
    now: Optional[datetime] = None,
    stale_after_seconds: Optional[int] = None,
) -> dict[str, Any]:
    """Return aggregate freshness and reconciliation state for active profiles."""

    instant = now or _utc_now()
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    freshness_seconds = max(
        int(stale_after_seconds or rss_stale_after_seconds()),
        60,
    )
    stale_before = instant - timedelta(seconds=freshness_seconds)

    state_present = ProfileFeedState.profile_id.is_not(None)
    fresh_state = ProfileFeedState.last_success_at >= stale_before
    due_state = or_(
        ProfileFeedState.profile_id.is_(None),
        ProfileFeedState.next_poll_at.is_(None),
        ProfileFeedState.next_poll_at <= instant,
    )

    row = db.execute(
        select(
            func.count(Profile.id).label("active"),
            func.sum(case((state_present, 1), else_=0)).label("configured"),
            func.sum(case((fresh_state, 1), else_=0)).label("fresh"),
            func.sum(
                case(
                    (
                        state_present & ProfileFeedState.last_success_at.is_(None),
                        1,
                    ),
                    else_=0,
                )
            ).label("never_succeeded"),
            func.sum(
                case((ProfileFeedState.consecutive_failures > 0, 1), else_=0)
            ).label("failing"),
            func.sum(
                case((ProfileFeedState.requires_full_sync.is_(True), 1), else_=0)
            ).label("reconciliation_required"),
            func.sum(case((due_state, 1), else_=0)).label("due"),
            func.sum(
                case((ProfileFeedState.lease_until > instant, 1), else_=0)
            ).label("leased"),
            func.min(ProfileFeedState.last_success_at).label("oldest_success_at"),
            func.max(ProfileFeedState.last_success_at).label("latest_success_at"),
        )
        .select_from(Profile)
        .outerjoin(ProfileFeedState, ProfileFeedState.profile_id == Profile.id)
        .where(Profile.is_active.is_(True))
    ).one()

    active = int(row.active or 0)
    configured = int(row.configured or 0)
    fresh = int(row.fresh or 0)
    counts = {
        "active": active,
        "configured": configured,
        "unconfigured": max(active - configured, 0),
        "fresh": fresh,
        "stale": max(active - fresh, 0),
        "never_succeeded": int(row.never_succeeded or 0),
        "failing": int(row.failing or 0),
        "reconciliation_required": int(row.reconciliation_required or 0),
        "due": int(row.due or 0),
        "leased": int(row.leased or 0),
    }
    requires_attention = any(
        counts[key] > 0
        for key in ("unconfigured", "stale", "failing", "reconciliation_required")
    )
    status = "idle" if active == 0 else ("degraded" if requires_attention else "healthy")

    return {
        "status": status,
        "checked_at": _iso_utc(instant),
        "requires_attention": requires_attention,
        "freshness_window_seconds": freshness_seconds,
        "profiles": counts,
        "oldest_success_at": _iso_utc(row.oldest_success_at),
        "latest_success_at": _iso_utc(row.latest_success_at),
    }
