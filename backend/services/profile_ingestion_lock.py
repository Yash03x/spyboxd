from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


PROFILE_INGESTION_LOCK_NAMESPACE = 5_454_298


def lock_profile_ingestion(db: Session, profile_id: int) -> None:
    """Serialize full-snapshot and RSS mutations for one profile on PostgreSQL."""

    if db.get_bind().dialect.name != "postgresql":
        return
    db.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :profile_id)"),
        {
            "namespace": PROFILE_INGESTION_LOCK_NAMESPACE,
            "profile_id": int(profile_id),
        },
    )
