"""Account-private MAL export intake and personal insights."""
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session
from pydantic import BaseModel, StrictBool

from auth import ClerkUser, get_current_user
from database.connection import get_db
from services.anime_export import AnimeImportError, MAX_UPLOAD_BYTES, compare_snapshots, import_snapshot, snapshot_response
from services.anime_metadata import add_metadata
from services.mal_client import MALError
from services.personal_anime_sync import SyncUnavailable, set_enabled, sync_owner, sync_status
from services.profile_access import ensure_app_user

router = APIRouter(prefix="/api/anime", tags=["personal-anime"])


@router.get("/compare")
def get_comparison(response: Response, before: int = Query(ge=1), after: int = Query(ge=1),
                   db: Session = Depends(get_db), user: ClerkUser = Depends(get_current_user)):
    owner = ensure_app_user(db, user)
    response.headers["Cache-Control"] = "private, no-store"
    try:
        result = compare_snapshots(db, owner.id, before, after)
    except AnimeImportError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "No such snapshots in your Anime workspace.")
    return result


@router.get("/sync")
def get_sync(response: Response, db: Session = Depends(get_db), user: ClerkUser = Depends(get_current_user)):
    owner = ensure_app_user(db, user)
    response.headers["Cache-Control"] = "private, no-store"
    return sync_status(db, owner.id)


class SyncSettings(BaseModel):
    enabled: StrictBool


@router.patch("/sync")
def update_sync(settings: SyncSettings, response: Response, db: Session = Depends(get_db), user: ClerkUser = Depends(get_current_user)):
    owner = ensure_app_user(db, user)
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return set_enabled(db, owner, settings.enabled)
    except SyncUnavailable as exc:
        db.rollback()
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/sync")
def post_sync(response: Response, db: Session = Depends(get_db), user: ClerkUser = Depends(get_current_user)):
    owner = ensure_app_user(db, user)
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return sync_owner(db, owner.id)
    except SyncUnavailable as exc:
        db.rollback()
        raise HTTPException(exc.status, str(exc)) from exc
    except (MALError, AnimeImportError) as exc:
        db.rollback()
        raise HTTPException(502, "MAL sync could not complete. Your previous snapshots are unchanged. Check that the list is public and retry later.") from exc


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
