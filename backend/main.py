import logging
import math
import os
import re
import shutil
import stat
import tempfile
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from api.routes.activity import router as activity_router
from api.routes.insights import router as insights_router
from auth import ClerkUser, get_admin_user, get_upload_user
from database.connection import engine, get_db, init_db
from database.repository import (
    ProfileRepository, RatingRepository, ReviewRepository, AnalyticsRepository
)
from pydantic import BaseModel
from services.data_coverage import (
    extract_data_coverage,
)
from services.ingestion import unified_data_loader
from services.profile_loader import load_profile_data
from services.operational_health import (
    application_revision,
    readiness_report,
    rss_operational_report,
)
from sqlalchemy.orm import Session

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)

# Support both repo-level .env and legacy backend/.env.
load_dotenv(os.path.join(REPO_ROOT, ".env"))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=False)
DATA_DIR = os.path.join(BASE_DIR, "..", "data")
SCRAPED_DATA_DIR = os.path.join(DATA_DIR, "scraped")
LOGGER = logging.getLogger("spyboxd.api")

_OWNER_EXPORT_CONSENT_ERROR = (
    "Owner-export publication consent is required because official exports "
    "can contain private or deleted account data."
)
_UNEXPECTED_UPLOAD_ERROR = "An unexpected processing error occurred."
_PROFILE_DIRECTORY_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


class _OwnerExportPublicationConsentRequired(PermissionError):
    """Expected upload validation failure with a fixed, public-safe message."""


def _remove_scraped_profile_directory(username: str) -> None:
    """Remove one legacy scrape directory without deriving a path from input.

    Profile data now lives in PostgreSQL, but older installations may still
    have a per-profile directory below ``SCRAPED_DATA_DIR``. Enumerating that
    fixed root keeps the deletion target filesystem-derived, while the strict
    component check and symlink rejection prevent traversal outside it.
    """

    if not _PROFILE_DIRECTORY_COMPONENT.fullmatch(username):
        raise HTTPException(status_code=400, detail="Invalid username/path")

    try:
        entries = os.scandir(SCRAPED_DATA_DIR)
    except FileNotFoundError:
        return

    with entries:
        for entry in entries:
            if entry.name != username:
                continue
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                raise HTTPException(status_code=400, detail="Invalid profile data path")
            shutil.rmtree(entry.path)
            return

# Pydantic models for request/response
class ProfileCreate(BaseModel):
    username: str
    bio: Optional[str] = None
    location: Optional[str] = None
    website: Optional[str] = None

class ProfileUpdate(BaseModel):
    bio: Optional[str] = None
    location: Optional[str] = None
    website: Optional[str] = None
    is_active: Optional[bool] = None


def _get_cors_origins() -> List[str]:
    configured = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]

    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    defaults = [
        frontend_url,
        "http://localhost:3000",
        "https://spyboxd.com",
        "https://www.spyboxd.com",
    ]

    deduped: List[str] = []
    seen = set()
    for origin in defaults:
        if origin and origin not in seen:
            deduped.append(origin)
            seen.add(origin)
    return deduped


def _safe_json_float(value, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric):
        return default
    return numeric


def _refresh_dashboard_snapshot_cache(db: Session) -> None:
    try:
        AnalyticsRepository(db).refresh_dashboard_analytics_snapshot(
            group_limit=6,
            top_movies_limit=10,
        )
    except Exception as exc:
        print(f"Warning: failed to refresh dashboard analytics snapshot: {exc}")


def _record_owner_export_publication_consent(analyzer_profile, publish_owner_data: bool) -> None:
    """Require an explicit admin attestation before owner-export data becomes public.

    Official exports can contain records that are not visible on a public
    Letterboxd profile. Spyboxd's analytics routes are public, so importing an
    export is a publication action, not merely a file upload.
    """
    if getattr(analyzer_profile, "source_kind", None) != "letterboxd_export":
        return
    if not publish_owner_data:
        raise _OwnerExportPublicationConsentRequired(_OWNER_EXPORT_CONSENT_ERROR)

    manifest = dict(getattr(analyzer_profile, "manifest", {}) or {})
    manifest["publication_consent"] = {
        "granted": True,
        "scope": "public_spyboxd_instance",
        "policy_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    analyzer_profile.manifest = manifest


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    print("🎬 Spyboxd API started successfully!")
    yield


app = FastAPI(
    title="Spyboxd API",
    description="Analytics and insights for Letterboxd profiles",
    version="2.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# New insight surfaces are additive; all legacy endpoints above and below remain intact.
app.include_router(insights_router)
app.include_router(activity_router)

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "revision": application_revision(),
    }


@app.get("/ready")
def readiness_check():
    """Report whether this instance can safely receive production traffic."""

    report = readiness_report(engine)
    if report["status"] != "ready":
        return JSONResponse(status_code=503, content=report)
    return report


@app.get("/health/rss")
def rss_health_check(db: Session = Depends(get_db)):
    """Expose aggregate RSS worker freshness without profile or error details."""

    try:
        return rss_operational_report(db)
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "reason": "rss_state_unavailable",
                "requires_attention": True,
            },
        )


@app.get("/public/profile/{username}")
async def get_public_profile(username: str, db: Session = Depends(get_db)):
    """
    Public profile snapshot used by share pages/OG images.
    Only exposes completed, active profiles.
    """
    profile_repo = ProfileRepository(db)
    rating_repo = RatingRepository(db)

    profile = profile_repo.get_profile_by_username(username)
    if not profile or not profile.is_active:
        raise HTTPException(status_code=404, detail="Profile not found")

    if profile.scraping_status != "completed":
        raise HTTPException(status_code=404, detail="Profile has no public data yet")

    all_entries = rating_repo.get_ratings_by_profile(profile.id)
    total_films = len(all_entries)
    rated_films = len([entry for entry in all_entries if entry.rating is not None and entry.rating > 0])
    liked_films = len([entry for entry in all_entries if entry.is_liked])
    avg_rating = _safe_json_float(profile.avg_rating, 0.0)

    return {
        "username": profile.username,
        "total_films": total_films,
        "rated_films": rated_films,
        "liked_films": liked_films,
        "avg_rating": avg_rating,
        "total_reviews": profile.total_reviews or 0,
        "profile_image_url": profile.profile_image_url,
        "bio": profile.bio,
        "location": profile.location,
        "website": profile.website,
        "last_scraped_at": profile.last_scraped_at.isoformat() if profile.last_scraped_at else None,
        "data_coverage": extract_data_coverage(profile.enhanced_metrics),
    }

def extract_zip_file(uploaded_file, temp_dir):
    """Extract a bounded ZIP without allowing archive paths to escape temp_dir."""
    safe_filename = os.path.basename(uploaded_file.filename or "letterboxd-export.zip")
    if not safe_filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP archives are supported")

    zip_path = os.path.join(temp_dir, safe_filename)
    with open(zip_path, "wb") as f:
        shutil.copyfileobj(uploaded_file.file, f)

    extract_dir = os.path.join(temp_dir, os.path.splitext(safe_filename)[0] or "archive")
    os.makedirs(extract_dir, exist_ok=True)
    extract_root = os.path.realpath(extract_dir)
    max_members = int(os.getenv("UPLOAD_MAX_ARCHIVE_MEMBERS", "50000"))
    max_uncompressed_bytes = int(
        os.getenv("UPLOAD_MAX_UNCOMPRESSED_BYTES", str(2 * 1024 * 1024 * 1024))
    )
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        members = zip_ref.infolist()
        if len(members) > max_members:
            raise HTTPException(status_code=400, detail="ZIP archive contains too many files")
        if sum(member.file_size for member in members) > max_uncompressed_bytes:
            raise HTTPException(status_code=400, detail="ZIP archive is too large when extracted")

        for member in members:
            member_name = member.filename.replace("\\", "/")
            target = os.path.realpath(os.path.join(extract_root, member_name))
            if os.path.commonpath([extract_root, target]) != extract_root:
                raise HTTPException(status_code=400, detail="ZIP archive contains an unsafe path")
            member_type = (member.external_attr >> 16) & 0o170000
            if member_type == stat.S_IFLNK:
                raise HTTPException(status_code=400, detail="ZIP archive contains a symbolic link")
        zip_ref.extractall(extract_dir)

    # Find the actual data directory (might be nested)
    for root, dirs, files in os.walk(extract_dir):
        if any(f in files for f in ['ratings.csv', 'watched.csv', 'reviews.csv']):
            return root

    return extract_dir

# Profile Management Endpoints
@app.get("/profiles/")
async def list_profiles(
    db: Session = Depends(get_db),
):
    """Get all active profiles with their basic information"""
    profile_repo = ProfileRepository(db)
    rating_repo = RatingRepository(db)
    
    profiles = profile_repo.get_all_profiles(active_only=True)
    
    profile_list = []
    for profile in profiles:
        profile_dict = profile.to_dict()
        all_entries = rating_repo.get_ratings_by_profile(profile.id)
        
        # Calculate separate counts
        total_films = len(all_entries)  # All films in database (watched/rated/liked)
        rated_films = len([r for r in all_entries if r.rating is not None and r.rating > 0])  # Only films with actual ratings
        liked_films = len([r for r in all_entries if r.is_liked])  # Films that are liked
        
        profile_dict['total_films'] = total_films  # All films discovered
        profile_dict['rated_films'] = rated_films  # Only films with ratings
        profile_dict['liked_films'] = liked_films  # Only films that are liked
        # Remove total_movies to avoid confusion - use total_films instead
        
        if rated_films > 0:
            profile_dict['avg_rating'] = sum(r.rating for r in all_entries if r.rating and r.rating > 0) / rated_films
        else:
            profile_dict['avg_rating'] = 0

        profile_dict['data_coverage'] = extract_data_coverage(profile.enhanced_metrics)
            
        profile_list.append(profile_dict)
    
    return {"profiles": profile_list}

@app.get("/api/dashboard/analytics")
async def get_consolidated_dashboard_analytics(
    db: Session = Depends(get_db),
):
    """Get consolidated system-wide analytics for the main dashboard."""
    analytics_repo = AnalyticsRepository(db)
    return analytics_repo.get_dashboard_analytics_snapshot(
        group_limit=6,
        top_movies_limit=10,
    )


@app.get("/api/spy-signals")
async def get_spy_signals(
    profiles: Optional[List[str]] = Query(default=None),
    gap_days: int = Query(default=1, ge=0, le=7),
    event_source: str = Query(default="ratings", pattern="^(ratings|events)$"),
    db: Session = Depends(get_db),
):
    """Compare timing and rating signals for two or more completed profiles."""
    profile_repo = ProfileRepository(db)
    all_profiles = profile_repo.get_all_profiles(active_only=False)
    profiles_by_username = {profile.username.casefold(): profile for profile in all_profiles}

    requested_profiles: List[str] = []
    seen_profiles = set()
    for requested in profiles or []:
        normalized = requested.strip()
        dedupe_key = normalized.casefold()
        if normalized and dedupe_key not in seen_profiles:
            requested_profiles.append(normalized)
            seen_profiles.add(dedupe_key)

    if requested_profiles:
        unknown_profiles = [
            username
            for username in requested_profiles
            if username.casefold() not in profiles_by_username
        ]
        if unknown_profiles:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "One or more profiles were not found",
                    "unknown_profiles": unknown_profiles,
                },
            )

        unavailable_profiles = [
            username
            for username in requested_profiles
            if not profiles_by_username[username.casefold()].is_active
            or profiles_by_username[username.casefold()].scraping_status != "completed"
        ]
        if unavailable_profiles:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "One or more profiles are inactive or do not have completed data",
                    "unavailable_profiles": unavailable_profiles,
                },
            )

        selected_profiles = [
            profiles_by_username[username.casefold()].username
            for username in requested_profiles
        ]
    else:
        selected_profiles = sorted(
            profile.username
            for profile in all_profiles
            if profile.is_active and profile.scraping_status == "completed"
        )

    if len(selected_profiles) < 2:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "At least two active profiles with completed data are required",
                "selected_profiles": selected_profiles,
            },
        )

    group_signals = AnalyticsRepository(db).get_group_correlation_metrics(
        usernames=selected_profiles,
        limit=100,
        gap_days=gap_days,
        event_source=event_source,
    )
    return {
        "selected_profiles": selected_profiles,
        "gap_days": gap_days,
        "group_signals": group_signals,
    }


@app.get("/profiles/{username}/analysis")
async def get_analysis(
    username: str,
    db: Session = Depends(get_db),
):
    """Get detailed analysis for a specific profile"""
    profile_repo = ProfileRepository(db)
    rating_repo = RatingRepository(db)
    review_repo = ReviewRepository(db)
    
    profile = profile_repo.get_profile_by_username(username)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Get rating distribution
    rating_distribution = rating_repo.get_rating_distribution(profile.id)
    
    # Get monthly stats
    monthly_stats = rating_repo.get_monthly_watch_stats(profile.id, months=12)
    
    # Get recent ratings and reviews
    recent_ratings = rating_repo.get_ratings_by_profile(profile.id, limit=20)
    recent_reviews = review_repo.get_reviews_by_profile(profile.id, limit=10)
    
    # Get recent watching trend (movies with watched dates)
    recent_watching = rating_repo.get_ratings_by_profile(profile.id)
    recent_watching_with_dates = [r for r in recent_watching if r.watched_date]
    recent_watching_sorted = sorted(recent_watching_with_dates, key=lambda x: x.watched_date, reverse=True)[:10]
    
    # Calculate detailed film counts
    all_entries = rating_repo.get_ratings_by_profile(profile.id)
    total_films = len(all_entries)
    rated_films = len([r for r in all_entries if r.rating is not None and r.rating > 0])
    liked_films = len([r for r in all_entries if r.is_liked])
    
    analysis = {
        "username": profile.username,
        "total_films": total_films,
        "rated_films": rated_films,
        "liked_films": liked_films,
        "avg_rating": _safe_json_float(profile.avg_rating, 0.0),
        "total_reviews": profile.total_reviews,
        "join_date": profile.join_date.isoformat() if profile.join_date else None,
        "last_scraped_at": profile.last_scraped_at.isoformat() if profile.last_scraped_at else None,
        "scraping_status": profile.scraping_status,
        "enhanced_metrics": profile.enhanced_metrics or {},
        "data_coverage": extract_data_coverage(profile.enhanced_metrics),
        "rating_distribution": rating_distribution,
        "monthly_stats": monthly_stats,
        "recent_ratings": [
            {
                "movie_title": r.movie_title,
                "movie_year": r.movie_year,
                "rating": _safe_json_float(r.rating),
                "watched_date": r.watched_date.isoformat() if r.watched_date else None,
                "is_rewatch": r.is_rewatch
            } for r in recent_ratings
        ],
        "recent_reviews": [
            {
                "movie_title": r.movie_title,
                "movie_year": r.movie_year,
                "rating": _safe_json_float(r.rating),
                "review_text": r.review_text[:200] + "..." if r.review_text and len(r.review_text) > 200 else r.review_text,
                "published_date": r.published_date.isoformat() if r.published_date else None,
                "likes_count": r.likes_count
            } for r in recent_reviews
        ],
        "recent_watching_trend": [
            {
                "movie_title": r.movie_title,
                "movie_year": r.movie_year,
                "watched_date": r.watched_date.isoformat() if r.watched_date else None,
                "rating": _safe_json_float(r.rating),
                "is_rewatch": r.is_rewatch
            } for r in recent_watching_sorted
        ]
    }

    return analysis

@app.post("/profiles/create")
async def create_profile(
    profile_data: ProfileCreate,
    db: Session = Depends(get_db),
    _user: ClerkUser = Depends(get_admin_user),
):
    """Create a new profile"""
    profile_repo = ProfileRepository(db)
    
    # Check if profile already exists
    existing_profile = profile_repo.get_profile_by_username(profile_data.username)
    if existing_profile:
        raise HTTPException(status_code=409, detail="Profile already exists")
    
    profile = profile_repo.create_profile(
        username=profile_data.username,
        bio=profile_data.bio,
        location=profile_data.location,
        website=profile_data.website
    )

    _refresh_dashboard_snapshot_cache(db)
    
    return {"message": f"Profile created for {profile_data.username}", "profile": profile.to_dict()}

@app.put("/profiles/{username}")
async def update_profile(
    username: str,
    profile_data: ProfileUpdate,
    db: Session = Depends(get_db),
    _user: ClerkUser = Depends(get_admin_user),
):
    """Update an existing profile"""
    profile_repo = ProfileRepository(db)
    
    profile = profile_repo.get_profile_by_username(username)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    # Update profile with provided data
    update_data = profile_data.dict(exclude_unset=True)
    updated_profile = profile_repo.update_profile(profile.id, **update_data)

    _refresh_dashboard_snapshot_cache(db)
    
    return {"message": f"Profile updated for {username}", "profile": updated_profile.to_dict()}

@app.delete("/profiles/{username}")
async def delete_profile(
    username: str,
    db: Session = Depends(get_db),
    _user: ClerkUser = Depends(get_admin_user),
):
    """Delete a profile and all associated data"""
    profile_repo = ProfileRepository(db)
    
    profile = profile_repo.get_profile_by_username(username)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    # Clean up any legacy on-disk scrape owned by this canonical profile.
    _remove_scraped_profile_directory(profile.username)
    
    # Delete from database (cascades to ratings, reviews, etc.)
    profile_repo.delete_profile(profile.id)
    _refresh_dashboard_snapshot_cache(db)
    
    return {"message": f"Profile {username} deleted successfully"}

# File Upload Endpoints
@app.post("/upload/")
async def upload_files(
    files: List[UploadFile] = File(...),
    publish_owner_data: bool = Form(default=False),
    db: Session = Depends(get_db),
    _user: ClerkUser = Depends(get_upload_user),
):
    """Upload multiple ZIP files containing Letterboxd data"""
    profile_repo = ProfileRepository(db)
    
    loaded_profiles = []
    loaded_imports = []
    errors = []
    
    with tempfile.TemporaryDirectory() as temp_dir:
        for file in files:
            if not file.filename.endswith('.zip'):
                errors.append(f"Invalid file type for {file.filename}. Please upload ZIP files only.")
                continue
                
            try:
                # Extract username from filename (remove .zip extension)
                username = file.filename.replace('.zip', '').replace('letterboxd-', '')
                
                profile_path = extract_zip_file(file, temp_dir)
                
                # Load profile data from extracted CSVs
                analyzer_profile = load_profile_data(profile_path, username)
                # Official Letterboxd exports carry the authoritative account
                # username in profile.csv. Schema-v2 full-sync bundles retain
                # their strict manifest identity inside load_profile_data.
                username = analyzer_profile.username
                _record_owner_export_publication_consent(
                    analyzer_profile,
                    publish_owner_data=publish_owner_data,
                )
                
                # The unified loader owns snapshot metadata updates so an
                # already-completed source replay remains a true no-op.
                existing_profile = profile_repo.get_profile_by_username(username)
                if existing_profile:
                    profile = existing_profile
                else:
                    profile = profile_repo.create_profile(
                        username=username,
                        scraping_status="processing",
                    )
                
                # Use unified data loader to prevent duplicates
                movies_loaded = unified_data_loader(analyzer_profile, profile.id, db)
                print(f"Loaded {movies_loaded} movies for {username} via upload")
                
                loaded_profiles.append(username)
                loaded_imports.append(
                    {
                        "username": username,
                        "source_kind": analyzer_profile.source_kind,
                        "movies_loaded": movies_loaded,
                    }
                )
                
            except _OwnerExportPublicationConsentRequired:
                errors.append(
                    f"Failed to process {file.filename}: {_OWNER_EXPORT_CONSENT_ERROR}"
                )
            except Exception:
                LOGGER.exception(
                    "Unexpected error while processing upload %r",
                    file.filename,
                )
                errors.append(
                    f"Failed to process {file.filename}: {_UNEXPECTED_UPLOAD_ERROR}"
                )
    
    result = {"loaded_profiles": loaded_profiles, "imports": loaded_imports}
    if errors:
        result["errors"] = errors
    
    if not loaded_profiles:
        raise HTTPException(
            status_code=400,
            detail={"message": "No profiles could be loaded", "errors": errors},
        )

    _refresh_dashboard_snapshot_cache(db)
    
    return result

@app.delete("/profiles/{username}/data")
async def clear_profile_data(
    username: str,
    db: Session = Depends(get_db),
    _user: ClerkUser = Depends(get_admin_user),
):
    """Clear scraped data for a user."""
    profile_repo = ProfileRepository(db)

    profile = profile_repo.get_profile_by_username(username)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Validate and remove any legacy on-disk scrape before committing the
    # database clear, so a rejected path cannot leave a partial operation.
    _remove_scraped_profile_directory(profile.username)
    profile_repo.clear_profile_data(profile.id)

    _refresh_dashboard_snapshot_cache(db)
    
    return {"message": f"Cleared all scraped data for {username}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
