from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database.connection import get_db
from services.insights import InsightRequestError, InsightsService


router = APIRouter(prefix="/api", tags=["insights"])


def _service(db: Session) -> InsightsService:
    return InsightsService(db)


def _translate_request_error(exc: InsightRequestError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/data-coverage")
def get_data_coverage(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Report source-backed coverage before an insight is presented as complete."""
    try:
        return _service(db).data_coverage(profiles or [])
    except InsightRequestError as exc:
        raise _translate_request_error(exc) from exc


@router.get("/pair-dossier")
def get_pair_dossier(
    profiles: List[str] = Query(...),
    gap_days: int = Query(default=7, ge=0, le=30),
    db: Session = Depends(get_db),
):
    """Deep comparison for exactly two profiles, including timing evidence."""
    try:
        return _service(db).pair_dossier(profiles, gap_days=gap_days)
    except InsightRequestError as exc:
        raise _translate_request_error(exc) from exc


@router.get("/signal-calendar")
def get_signal_calendar(
    profiles: List[str] = Query(...),
    gap_days: int = Query(default=1, ge=0, le=30),
    from_date: Optional[date] = Query(default=None, alias="from"),
    to_date: Optional[date] = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
):
    """Calendar-ready co-watch events for a selected group."""
    try:
        return _service(db).signal_calendar(
            profiles,
            gap_days=gap_days,
            from_date=from_date,
            to_date=to_date,
        )
    except InsightRequestError as exc:
        raise _translate_request_error(exc) from exc


@router.get("/rewatch-echoes")
def get_rewatch_echoes(
    profiles: List[str] = Query(...),
    gap_days: int = Query(default=1, ge=0, le=30),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Find close-watch signals where at least one observed watch is a rewatch."""
    try:
        return _service(db).rewatch_echoes(
            profiles,
            gap_days=gap_days,
            limit=limit,
        )
    except InsightRequestError as exc:
        raise _translate_request_error(exc) from exc


@router.get("/taste-dna")
def get_taste_dna(
    profiles: List[str] = Query(...),
    dimensions: str = Query(
        default="genre,director,actor,language,country,decade,keyword,runtime",
    ),
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Explain shared and contrasting taste traits from observed ratings."""
    requested_dimensions = [
        value.strip().lower()
        for value in dimensions.split(",")
        if value.strip()
    ]
    try:
        return _service(db).taste_dna(
            profiles,
            dimensions=requested_dimensions,
            limit=limit,
        )
    except InsightRequestError as exc:
        raise _translate_request_error(exc) from exc


@router.get("/taste-timeline")
def get_taste_timeline(
    profiles: List[str] = Query(...),
    dimensions: str = Query(default="genre,director,decade"),
    from_year: Optional[int] = Query(default=None, ge=1800, le=2200),
    to_year: Optional[int] = Query(default=None, ge=1800, le=2200),
    trait_limit: int = Query(default=5, ge=1, le=20),
    year_limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Summarize dated, event-level taste by year and meteorological season."""
    requested_dimensions = [
        value.strip().lower()
        for value in dimensions.split(",")
        if value.strip()
    ]
    try:
        return _service(db).taste_timeline(
            profiles,
            dimensions=requested_dimensions,
            from_year=from_year,
            to_year=to_year,
            trait_limit=trait_limit,
            year_limit=year_limit,
        )
    except InsightRequestError as exc:
        raise _translate_request_error(exc) from exc


@router.get("/public-lists")
def get_public_lists(
    profiles: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List bounded, public list missions available for the selected profiles."""
    try:
        return _service(db).public_lists(profiles or [], limit=limit)
    except InsightRequestError as exc:
        raise _translate_request_error(exc) from exc


@router.get("/watch-together")
def get_watch_together(
    profiles: List[str] = Query(...),
    mode: str = Query(
        default="unseen_pick",
        pattern="^(watchlist_overlap|unseen_pick|collective_blind_spots|list_mission)$",
    ),
    list_id: Optional[int] = Query(default=None, ge=1),
    region: str = Query(default="ALL", pattern="^(?:[A-Za-z]{2}|[Aa][Ll][Ll])$"),
    max_runtime: Optional[int] = Query(default=None, ge=1, le=1000),
    genre: Optional[str] = Query(default=None, max_length=100),
    availability: Optional[str] = Query(default=None, max_length=100),
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Recommend transparent group candidates without inventing missing watchlists."""
    try:
        return _service(db).watch_together(
            profiles,
            mode=mode,
            region=region.upper(),
            max_runtime=max_runtime,
            genre=genre,
            availability=availability,
            limit=limit,
            list_id=list_id,
        )
    except InsightRequestError as exc:
        raise _translate_request_error(exc) from exc


@router.get("/watch-provider-regions")
def get_watch_provider_regions(db: Session = Depends(get_db)):
    """List countries represented in the cached TMDB watch-provider payloads."""

    return _service(db).watch_provider_regions()
