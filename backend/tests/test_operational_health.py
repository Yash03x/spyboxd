from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database.models import Profile, ProfileFeedState
from main import health_check, readiness_check, rss_health_check
from services.operational_health import (
    application_revision,
    readiness_report,
    repository_schema_heads,
    rss_operational_report,
    rss_stale_after_seconds,
)


NOW = datetime(2026, 7, 29, 12, tzinfo=timezone.utc)


def _revision_engine(revisions: set[str]):
    database_engine = create_engine("sqlite:///:memory:")
    with database_engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)"))
        for revision in revisions:
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": revision},
            )
    return database_engine


def _rss_database():
    database_engine = create_engine("sqlite:///:memory:")
    Profile.__table__.create(database_engine)
    ProfileFeedState.__table__.create(database_engine)
    return database_engine, sessionmaker(bind=database_engine, expire_on_commit=False)()


def test_readiness_accepts_exact_repository_head():
    database_engine = _revision_engine(repository_schema_heads())
    try:
        report = readiness_report(database_engine, now=NOW)
    finally:
        database_engine.dispose()

    assert report["status"] == "ready"
    assert report["revision"] is None
    assert report["checks"] == {"database": "ok", "schema": "current"}


def test_readiness_rejects_schema_revision_mismatch():
    database_engine = _revision_engine({"old_revision"})
    try:
        report = readiness_report(database_engine, now=NOW)
    finally:
        database_engine.dispose()

    assert report["status"] == "not_ready"
    assert report["reason"] == "schema_revision_mismatch"
    assert report["checks"] == {"database": "ok", "schema": "mismatch"}
    assert report["schema"]["current_revisions"] == ["old_revision"]


def test_readiness_rejects_database_without_alembic_revision_table():
    database_engine = create_engine("sqlite:///:memory:")
    try:
        report = readiness_report(database_engine, now=NOW)
    finally:
        database_engine.dispose()

    assert report["status"] == "not_ready"
    assert report["reason"] == "schema_revision_unavailable"
    assert report["checks"] == {"database": "ok", "schema": "unavailable"}


def test_readiness_hides_database_connection_errors():
    database_engine = MagicMock()
    database_engine.connect.side_effect = RuntimeError(
        "postgresql://secret-user:secret-password@private-host/spyboxd"
    )

    report = readiness_report(database_engine, now=NOW)

    assert report["status"] == "not_ready"
    assert report["reason"] == "database_unavailable"
    assert "secret" not in json.dumps(report)
    assert "private-host" not in json.dumps(report)


def test_readiness_endpoint_returns_503_for_failed_check():
    with patch(
        "main.readiness_report",
        return_value={
            "status": "not_ready",
            "reason": "database_unavailable",
            "checks": {"database": "unavailable", "schema": "unknown"},
        },
    ):
        response = readiness_check()

    assert response.status_code == 503
    assert json.loads(response.body)["reason"] == "database_unavailable"


def test_liveness_remains_independent_of_database_and_schema():
    import asyncio

    result = asyncio.run(health_check())

    assert result["status"] == "ok"
    assert result["revision"] is None
    assert set(result) == {"status", "timestamp", "revision"}


def test_application_revision_accepts_only_an_exact_sha(monkeypatch):
    revision = "a" * 40
    monkeypatch.setenv("SPYBOXD_REVISION", revision.upper())
    assert application_revision() == revision

    monkeypatch.setenv("SPYBOXD_REVISION", "main")
    assert application_revision() is None


def test_application_revision_reads_release_marker(monkeypatch, tmp_path):
    revision = "b" * 40
    marker = tmp_path / "REVISION"
    marker.write_text(f"{revision}\n", encoding="utf-8")
    monkeypatch.delenv("SPYBOXD_REVISION", raising=False)
    monkeypatch.setattr("services.operational_health.REVISION_PATH", marker)

    assert application_revision() == revision


def test_default_rss_health_window_covers_four_poll_intervals(monkeypatch):
    monkeypatch.delenv("SPYBOXD_RSS_POLL_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("SPYBOXD_RSS_HEALTH_STALE_AFTER_SECONDS", raising=False)

    assert rss_stale_after_seconds() == 40 * 60


def test_rss_report_is_healthy_when_every_active_feed_is_fresh():
    database_engine, db = _rss_database()
    try:
        db.add(Profile(id=1, username="fresh", is_active=True))
        db.add(
            ProfileFeedState(
                profile_id=1,
                feed_url="https://letterboxd.com/fresh/rss/",
                last_success_at=NOW - timedelta(hours=1),
                next_poll_at=NOW + timedelta(hours=1),
                consecutive_failures=0,
                requires_full_sync=False,
                activity_guids=[],
            )
        )
        db.commit()

        report = rss_operational_report(db, now=NOW, stale_after_seconds=6 * 60 * 60)
    finally:
        db.close()
        database_engine.dispose()

    assert report["status"] == "healthy"
    assert report["requires_attention"] is False
    assert report["profiles"] == {
        "active": 1,
        "configured": 1,
        "unconfigured": 0,
        "fresh": 1,
        "stale": 0,
        "never_succeeded": 0,
        "failing": 0,
        "reconciliation_required": 0,
        "due": 0,
        "leased": 0,
    }


def test_rss_report_aggregates_stale_failures_and_reconciliation_without_details():
    database_engine, db = _rss_database()
    try:
        db.add_all(
            [
                Profile(id=1, username="stale-person", is_active=True),
                Profile(id=2, username="unconfigured-person", is_active=True),
                Profile(id=3, username="ignored-inactive", is_active=False),
            ]
        )
        db.add(
            ProfileFeedState(
                profile_id=1,
                feed_url="https://letterboxd.com/stale-person/rss/?token=do-not-leak",
                last_success_at=NOW - timedelta(hours=10),
                next_poll_at=NOW - timedelta(minutes=1),
                consecutive_failures=2,
                last_error="credential secret should never leave the database",
                requires_full_sync=True,
                reconciliation_reason="internal detail should not leak",
                activity_guids=[],
            )
        )
        db.commit()

        report = rss_operational_report(db, now=NOW, stale_after_seconds=6 * 60 * 60)
    finally:
        db.close()
        database_engine.dispose()

    serialized = json.dumps(report)
    assert report["status"] == "degraded"
    assert report["requires_attention"] is True
    assert report["profiles"] == {
        "active": 2,
        "configured": 1,
        "unconfigured": 1,
        "fresh": 0,
        "stale": 2,
        "never_succeeded": 0,
        "failing": 1,
        "reconciliation_required": 1,
        "due": 2,
        "leased": 0,
    }
    assert "stale-person" not in serialized
    assert "token" not in serialized
    assert "secret" not in serialized
    assert "internal detail" not in serialized


def test_rss_endpoint_returns_sanitized_503_when_state_query_fails():
    db = MagicMock()
    db.execute.side_effect = RuntimeError("secret database hostname")

    response = rss_health_check(db)

    assert response.status_code == 503
    assert json.loads(response.body) == {
        "status": "unavailable",
        "reason": "rss_state_unavailable",
        "requires_attention": True,
    }
    assert "secret" not in response.body.decode()
