"""Account-private MAL export intake and personal insights."""
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from auth import ClerkUser, get_current_user
from database.connection import get_db
from services.anime_export import AnimeImportError, MAX_UPLOAD_BYTES, import_snapshot, snapshot_response
from services.anime_metadata import add_metadata
from services.profile_access import ensure_app_user

router = APIRouter(prefix="/api/anime", tags=["personal-anime"])


def _today(zone: str):
    # MAL's dates have no time or offset. Use the viewer's calendar day, not
    # yesterday in UTC, when checking dates shortly after local midnight.
    try:
        return datetime.now(ZoneInfo(zone)).date()
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise HTTPException(status_code=400, detail="Choose a valid IANA time zone.") from exc


@router.get("")
def get_anime(
    response: Response,
    snapshot_id: int | None = Query(default=None, ge=1),
    timezone: str = Query(default="UTC", max_length=64),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    owner = ensure_app_user(db, user)
    response.headers["Cache-Control"] = "private, no-store"
    result = snapshot_response(db, owner.id, snapshot_id=snapshot_id, today=_today(timezone))
    if snapshot_id and result["snapshot"] is None:
        raise HTTPException(status_code=404, detail="No such snapshot in your Anime workspace.")
    return add_metadata(db, result)


@router.post("/import")
def post_anime_import(
    response: Response,
    file: UploadFile = File(...),
    timezone: str = Query(default="UTC", max_length=64),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    owner = ensure_app_user(db, user)
    response.headers["Cache-Control"] = "private, no-store"
    today = _today(timezone)
    try:
        content = file.file.read(MAX_UPLOAD_BYTES + 1)
        snapshot, created = import_snapshot(db, owner, content, file.filename or "animelist.xml")
    except AnimeImportError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        file.file.close()
    return {"created": created, "imported_snapshot_id": snapshot.id,
            "message": "Anime export imported privately." if created else "This export was already imported; no duplicate data was added.",
            **add_metadata(db, snapshot_response(db, owner.id, today=today))}
