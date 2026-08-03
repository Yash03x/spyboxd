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
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Query, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from api.dependencies import get_active_upload_user
from api.routes.activity import router as activity_router
from api.routes.film_ratings import router as film_ratings_router
from api.routes.follow_graph import router as follow_graph_router
from api.routes.insights import router as insights_router
from api.routes.library import router as library_router
from api.routes.member_archive import router as member_archive_router
from api.routes.obscurity import router as obscurity_router
from api.routes.people import router as people_router
from api.routes.profile_access import router as profile_access_router
from api.routes.profile_stats import router as profile_stats_router
from api.routes.watchlist_insights import router as watchlist_insights_router
from api.routes.rating_comparison import router as rating_comparison_router
from auth import ClerkUser, get_admin_user, get_current_user, get_upload_user
from database.connection import engine, get_db, init_db
from database.models import Movie, Profile, ProfileFavoriteMovie, ProfileFilm, WatchEvent
from database.repository import (
    ProfileRepository, RatingRepository, ReviewRepository, AnalyticsRepository
)
from pydantic import BaseModel, Field
from services.data_coverage import (
    extract_data_coverage,
)
from services.ingestion import unified_data_loader
from services.profile_loader import load_profile_data, validate_import_bundle
from services.profile_access import (
    accessible_profiles,
    authorize_profile_usernames,
    ensure_app_user,
    fulfill_pending_requests,
    reopen_fulfilled_requests_for_profile,
    require_profile_access,
    tracked_profiles,
)
from services.operational_health import (
    application_revision,
    readiness_report,
    rss_operational_report,
)
from sqlalchemy import func
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


class ProfileRename(BaseModel):
    new_username: str


class PublicSystemStats(BaseModel):
    total_profiles: int = Field(ge=0)
    total_movies_tracked: int = Field(ge=0)
    total_reviews: int = Field(ge=0)
    global_avg_rating: float = Field(ge=0, le=5)


class PublicActivityPoint(BaseModel):
    month: str
    movies_watched: int = Field(ge=0)
    unique_movies: int = Field(ge=0)
    average_rating: Optional[float] = Field(default=None, ge=0, le=5)
    is_partial: bool


class PublicSignalCounts(BaseModel):
    profiles_analyzed: int = Field(ge=0)
    profiles_with_diary_dates: int = Field(ge=0)
    shared_titles: int = Field(ge=0)
    same_day_events: int = Field(ge=0)
    one_day_gap_events: int = Field(ge=0)
    same_day_pair_hits: int = Field(ge=0)
    one_day_gap_pair_hits: int = Field(ge=0)


class PublicDataHealth(BaseModel):
    active_profiles: int = Field(ge=0)
    completed_profiles: int = Field(ge=0)
    last_synced_at: Optional[datetime]


class PublicDashboardResponse(BaseModel):
    system_stats: PublicSystemStats
    rating_distribution: dict[str, int]
    activity_data: list[PublicActivityPoint]
    signal_counts: PublicSignalCounts
    data_health: PublicDataHealth
    timestamp: datetime


def _safe_nonnegative_int(value) -> int:
    if isinstance(value, bool):
        return 0
    try:
        numeric = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, numeric)


def _safe_public_timestamp(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _safe_public_rating(value, default: Optional[float] = None) -> Optional[float]:
    numeric = _safe_json_float(value)
    if numeric is None or not 0 <= numeric <= 5:
        return default
    return numeric


def _public_dashboard_payload(
    snapshot: dict,
    profile_health: dict,
) -> dict:
    """Allowlist an aggregate-only dashboard response.

    The cached internal snapshot deliberately contains usernames, profile pairs,
    titles, watch dates, and other private workspace details. Never return or
    shallow-copy that object from an anonymous endpoint.
    """

    system_stats = snapshot.get("system_stats") or {}
    raw_summary = (snapshot.get("group_signals") or {}).get("summary") or {}
    activity_data = snapshot.get("activity_data") or []
    rating_distribution = {}
    for rating, count in (snapshot.get("rating_distribution") or {}).items():
        numeric_rating = _safe_json_float(rating)
        if (
            numeric_rating is None
            or not 0.5 <= numeric_rating <= 5.0
            or abs(numeric_rating * 2 - round(numeric_rating * 2)) > 1e-9
        ):
            continue
        rating_distribution[f"{numeric_rating:.1f}"] = _safe_nonnegative_int(count)

    return {
        "system_stats": {
            "total_profiles": _safe_nonnegative_int(system_stats.get("total_profiles")),
            "total_movies_tracked": _safe_nonnegative_int(system_stats.get("total_movies_tracked")),
            "total_reviews": _safe_nonnegative_int(system_stats.get("total_reviews")),
            "global_avg_rating": _safe_public_rating(
                system_stats.get("global_avg_rating"),
                0.0,
            ) or 0.0,
        },
        "rating_distribution": rating_distribution,
        "activity_data": [
            {
                "month": point["month"],
                "movies_watched": _safe_nonnegative_int(point.get("movies_watched")),
                "unique_movies": _safe_nonnegative_int(point.get("unique_movies")),
                "average_rating": _safe_public_rating(point.get("average_rating")),
                "is_partial": point.get("is_partial") is True,
            }
            for point in activity_data
            if isinstance(point, dict)
            and isinstance(point.get("month"), str)
            and re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", point["month"])
        ],
        "signal_counts": {
            key: _safe_nonnegative_int(raw_summary.get(key))
            for key in (
                "profiles_analyzed",
                "profiles_with_diary_dates",
                "shared_titles",
                "same_day_events",
                "one_day_gap_events",
                "same_day_pair_hits",
                "one_day_gap_pair_hits",
            )
        },
        "data_health": {
            "active_profiles": _safe_nonnegative_int(profile_health.get("active_profiles")),
            "completed_profiles": _safe_nonnegative_int(profile_health.get("completed_profiles")),
            "last_synced_at": (
                _safe_public_timestamp(profile_health.get("last_synced_at"))
                if profile_health.get("last_synced_at")
                else None
            ),
        },
        "timestamp": _safe_public_timestamp(snapshot.get("timestamp")),
    }


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


def _safe_tag_list(value) -> List[str]:
    """Coerce a stored tags JSON value into a clean list of tag strings."""
    if not isinstance(value, list):
        return []
    tags: List[str] = []
    for tag in value:
        if isinstance(tag, str):
            cleaned = tag.strip()
            if cleaned:
                tags.append(cleaned)
    return tags


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


def _bundle_person_id(analyzer_profile) -> Optional[int]:
    """The stable Letterboxd member id claimed by a bundle's profile.csv."""
    info = getattr(analyzer_profile, "profile_info", {}) or {}
    raw = info.get("Person_ID") or info.get("Person ID")
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _record_owner_export_publication_consent(analyzer_profile, publish_owner_data: bool) -> None:
    """Require an explicit admin attestation before owner-export data becomes shared.

    Official exports can contain records that are not visible on a public
    Letterboxd profile. Spyboxd stores profiles once for its signed-in shared
    workspace, so importing an export is a publication action to authorized
    users, not merely a private file upload.
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
app.include_router(profile_access_router)
app.include_router(follow_graph_router)
app.include_router(member_archive_router)
app.include_router(profile_stats_router)
app.include_router(rating_comparison_router)
app.include_router(watchlist_insights_router)
app.include_router(obscurity_router)
app.include_router(people_router)
app.include_router(library_router)
# Letterboxd film ratings can only be scraped from a residential IP, so they
# arrive over the same ingestion-token boundary as /upload/ rather than being
# enriched on this server the way TMDB data is.
app.include_router(film_ratings_router)

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
async def get_public_profile(
    username: str,
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """
    Signed-in profile snapshot used by the legacy share-page URL.
    Access is limited to profiles visible to the caller.
    """
    rating_repo = RatingRepository(db)

    profile = require_profile_access(db, user, username)
    if not profile.is_active:
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
def _serialize_profiles(db: Session, profiles) -> dict:
    rating_repo = RatingRepository(db)
    profile_list = []
    active = [profile for profile in profiles if profile.is_active]
    # Letterboxd does not publish a join date on a public profile page -- it
    # only appears in an account's own export -- so every scraped profile has
    # none and the card read "Member Since: Unknown" for all but one. The first
    # logged diary entry is something we do hold for everyone, and for the one
    # profile that has both they agree to within a week.
    first_logged: Dict[int, Any] = {}
    if active:
        first_logged = dict(
            db.query(WatchEvent.profile_id, func.min(WatchEvent.watched_date))
            .filter(WatchEvent.profile_id.in_([profile.id for profile in active]))
            .group_by(WatchEvent.profile_id)
            .all()
        )
    for profile in active:
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
        earliest = first_logged.get(profile.id)
        profile_dict['first_logged_date'] = earliest.isoformat() if earliest else None
            
        profile_list.append(profile_dict)
    
    return {"profiles": profile_list}


@app.get("/profiles/")
async def list_profiles(
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Get the caller's profiles, or the managed global library for admins."""

    return _serialize_profiles(db, accessible_profiles(db, user))


@app.get("/profiles/tracked")
async def list_tracked_profiles(
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Get the caller's personal monitoring set without an admin bypass."""

    return _serialize_profiles(db, tracked_profiles(db, user))


@app.get("/api/dashboard/analytics")
async def get_consolidated_dashboard_analytics(
    scope: Optional[str] = Query(default=None, pattern="^(tracked|global)$"),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Get dashboard analytics with backward-compatible admin defaults."""
    analytics_repo = AnalyticsRepository(db)
    effective_scope = scope or ("global" if user.is_admin else "tracked")
    if effective_scope == "global":
        ensure_app_user(db, user)
        if not user.is_admin:
            raise HTTPException(status_code=403, detail="Admin role required for global analytics")
        return analytics_repo.get_dashboard_analytics_snapshot(
            group_limit=6,
            top_movies_limit=10,
        )

    usernames = [
        profile.username
        for profile in tracked_profiles(db, user)
        if profile.is_active and profile.scraping_status == "completed"
    ]
    return analytics_repo.build_dashboard_analytics_snapshot(
        group_limit=6,
        top_movies_limit=10,
        usernames=usernames,
    )


@app.get("/api/public/dashboard", response_model=PublicDashboardResponse)
async def get_public_dashboard_analytics(
    response: Response,
    db: Session = Depends(get_db),
):
    """Return one identity-free aggregate snapshot for the public homepage."""

    analytics_repo = AnalyticsRepository(db)
    snapshot = analytics_repo.get_dashboard_analytics_snapshot(
        group_limit=6,
        top_movies_limit=10,
    )
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=300"
    return _public_dashboard_payload(
        snapshot,
        analytics_repo.get_public_profile_health(),
    )


@app.get("/api/spy-signals")
async def get_spy_signals(
    profiles: Optional[List[str]] = Query(default=None),
    gap_days: int = Query(default=1, ge=0, le=7),
    event_source: str = Query(default="ratings", pattern="^(ratings|events)$"),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Compare timing and rating signals for two or more completed profiles."""
    profiles = authorize_profile_usernames(db, user, profiles)
    profile_repo = ProfileRepository(db)
    all_profiles = profile_repo.get_all_profiles(active_only=False)
    profiles_by_username = {profile.username: profile for profile in all_profiles}

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
            if username not in profiles_by_username
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
            if not profiles_by_username[username].is_active
            or profiles_by_username[username].scraping_status != "completed"
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
            profiles_by_username[username].username
            for username in requested_profiles
        ]
    elif user.is_admin:
        selected_profiles = sorted(
            profile.username
            for profile in all_profiles
            if profile.is_active and profile.scraping_status == "completed"
        )
    else:
        selected_profiles = []

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


def _safe_external_url(value) -> Optional[str]:
    """Normalize a member-supplied website into a link-safe absolute URL.

    Letterboxd stores the website exactly as the member typed it, so the value
    is frequently scheme-less ("example.com") and is never trustworthy enough
    to hand to an href unchecked. Anything that is not plain http(s) is
    dropped rather than rendered.
    """
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    lowered = candidate.casefold()
    if lowered.startswith(("http://", "https://")):
        return candidate
    if "://" in candidate or ":" in candidate.split("/", 1)[0]:
        return None
    return f"https://{candidate}"


def _profile_external_links(profile: Profile) -> List[dict]:
    """The member's external profile links, each re-validated before serving."""
    raw = profile.external_links if isinstance(profile.external_links, list) else []
    links: List[dict] = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        url = _safe_external_url(entry.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        label = str(entry.get("label") or "").strip()
        links.append({"label": label or url, "url": url})
    return links


def _profile_favorite_films(db: Session, profile_id: int) -> List[dict]:
    """Letterboxd's four favourite films for a profile, in display order."""
    rows = (
        db.query(ProfileFavoriteMovie, Movie)
        .join(Movie, Movie.id == ProfileFavoriteMovie.movie_id)
        .filter(ProfileFavoriteMovie.profile_id == profile_id)
        .order_by(ProfileFavoriteMovie.position.asc())
        .all()
    )
    # A stated favourite and a logged one are different claims, and the gap
    # between them is the interesting part: across the tracked profiles, four
    # favourites are absent from their owner's diary entirely and five more are
    # logged without ever being rated.
    library = {
        movie_id: rating
        for movie_id, rating in db.query(ProfileFilm.movie_id, ProfileFilm.rating)
        .filter(
            ProfileFilm.profile_id == profile_id,
            ProfileFilm.removed_at.is_(None),
        )
        .all()
    }
    favorites: List[dict] = []
    for favorite, movie in rows:
        letterboxd_url = movie.letterboxd_url
        if not letterboxd_url and movie.letterboxd_slug:
            letterboxd_url = f"https://letterboxd.com/film/{movie.letterboxd_slug}/"
        favorites.append(
            {
                "position": favorite.position,
                "title": movie.title,
                "year": movie.release_year,
                "poster_url": movie.poster_url,
                "letterboxd_url": letterboxd_url,
                # None means "not in their diary at all"; a row present with a
                # null rating means watched but never scored. The two read very
                # differently under a picture somebody chose as a favourite.
                "in_library": favorite.movie_id in library,
                "own_rating": (
                    float(library[favorite.movie_id])
                    if library.get(favorite.movie_id) is not None
                    else None
                ),
            }
        )
    return favorites


def _profile_header_payload(
    db: Session,
    profile: Profile,
    *,
    films_this_year: Optional[int] = None,
    total_films: Optional[int] = None,
) -> dict:
    """Serialize everything Letterboxd's own profile header shows, plus ours.

    Every field is optional on purpose: the public HTML scrape, the RSS feed,
    and the official export each observe a different subset (badge, pronoun,
    and the stats page in particular are usually unknown), so consumers must
    treat null as "not observed" and render nothing for it.
    """
    stats_snapshot = profile.stats_snapshot if isinstance(profile.stats_snapshot, dict) else None
    return {
        "username": profile.username,
        "display_name": profile.display_name,
        "bio": profile.bio,
        "location": profile.location,
        "website": profile.website,
        "website_url": _safe_external_url(profile.website),
        "external_links": _profile_external_links(profile),
        "pronoun": profile.pronoun,
        "member_badge": profile.member_badge,
        "avatar_url": profile.profile_image_url,
        "letterboxd_url": f"https://letterboxd.com/{profile.username}/",
        "letterboxd_person_id": profile.letterboxd_person_id,
        "join_date": profile.join_date.isoformat() if profile.join_date else None,
        # Letterboxd's own reported counters (its profile header stat row).
        "films_count": profile.reported_total_films,
        "reviews_count": profile.reported_total_reviews,
        "lists_count": profile.reported_total_lists,
        "watchlist_count": profile.reported_watchlist_count,
        "following_count": profile.following_count,
        "followers_count": profile.followers_count,
        # Derived from the synced diary, because Letterboxd's "this year"
        # counter is not carried in any import surface.
        "films_this_year": films_this_year,
        "favorites": _profile_favorite_films(db, profile.id),
        # Spyboxd-only context that Letterboxd's page never shows.
        "synced_films": total_films,
        "avg_rating": _safe_json_float(profile.avg_rating, 0.0),
        "total_reviews": profile.total_reviews,
        "last_scraped_at": profile.last_scraped_at.isoformat() if profile.last_scraped_at else None,
        "metadata_synced_at": profile.metadata_synced_at.isoformat() if profile.metadata_synced_at else None,
        # Letterboxd's own /<user>/stats/ figures, forwarded as observed:
        # the key set varies by account tier, so consumers render generically.
        "stats_snapshot": stats_snapshot,
        "stats_synced_at": profile.stats_synced_at.isoformat() if profile.stats_synced_at else None,
    }


@app.get("/profiles/{username}/analysis")
async def get_analysis(
    username: str,
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Get detailed analysis for a specific profile"""
    profile_repo = ProfileRepository(db)
    rating_repo = RatingRepository(db)
    review_repo = ReviewRepository(db)
    
    profile = require_profile_access(db, user, username)
    if not profile.is_active or profile.scraping_status != "completed":
        raise HTTPException(status_code=404, detail="Profile has no available analysis")

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

    # Letterboxd's header shows a "this year" count that no import surface
    # carries, so derive it from watch dates. A dataset with no watch dates at
    # all cannot answer the question, and reports null instead of a false zero.
    dated_entries = [r for r in all_entries if r.watched_date]
    current_year = datetime.now(timezone.utc).year
    films_this_year = (
        len([r for r in dated_entries if r.watched_date.year == current_year])
        if dated_entries
        else None
    )

    # Aggregate film-level tag usage across every entry for this profile
    tag_usage: dict = {}
    for entry in all_entries:
        for tag in _safe_tag_list(entry.tags):
            tag_usage[tag] = tag_usage.get(tag, 0) + 1
    tag_counts = [
        {"tag": tag, "count": count}
        for tag, count in sorted(tag_usage.items(), key=lambda item: (-item[1], item[0].lower()))
    ]


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
        "profile_header": _profile_header_payload(
            db,
            profile,
            films_this_year=films_this_year,
            total_films=total_films,
        ),
        "rating_distribution": rating_distribution,
        "monthly_stats": monthly_stats,
        "tag_counts": tag_counts,
        "recent_ratings": [
            {
                "movie_title": r.movie_title,
                "movie_year": r.movie_year,
                "rating": _safe_json_float(r.rating),
                "watched_date": r.watched_date.isoformat() if r.watched_date else None,
                "is_rewatch": r.is_rewatch,
                "tags": _safe_tag_list(r.tags)
            } for r in recent_ratings
        ],
        "recent_reviews": [
            {
                "movie_title": r.movie_title,
                "movie_year": r.movie_year,
                "rating": _safe_json_float(r.rating),
                "review_text": r.review_text[:200] + "..." if r.review_text and len(r.review_text) > 200 else r.review_text,
                "contains_spoilers": bool(r.contains_spoilers),
                "published_date": r.published_date.isoformat() if r.published_date else None,
                "likes_count": r.likes_count,
                "tags": _safe_tag_list(r.tags)
            } for r in recent_reviews
        ],
        "recent_watching_trend": [
            {
                "movie_title": r.movie_title,
                "movie_year": r.movie_year,
                "watched_date": r.watched_date.isoformat() if r.watched_date else None,
                "rating": _safe_json_float(r.rating),
                "is_rewatch": r.is_rewatch,
                "tags": _safe_tag_list(r.tags)
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
    ensure_app_user(db, _user)
    profile_repo = ProfileRepository(db)
    
    # Check if profile already exists
    existing_profile = profile_repo.get_profile_by_username(profile_data.username)
    if existing_profile:
        fulfill_pending_requests(
            db,
            existing_profile,
            resolved_by_user_id=_user.user_id,
        )
        raise HTTPException(status_code=409, detail="Profile already exists")
    
    profile = profile_repo.create_profile(
        username=profile_data.username,
        bio=profile_data.bio,
        location=profile_data.location,
        website=profile_data.website
    )

    fulfill_pending_requests(
        db,
        profile,
        resolved_by_user_id=_user.user_id,
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
    ensure_app_user(db, _user)
    profile_repo = ProfileRepository(db)
    
    profile = profile_repo.get_profile_by_username(username)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    # Update profile with provided data
    update_data = profile_data.dict(exclude_unset=True)
    updated_profile = profile_repo.update_profile(profile.id, **update_data)

    fulfill_pending_requests(
        db,
        updated_profile,
        resolved_by_user_id=_user.user_id,
    )

    _refresh_dashboard_snapshot_cache(db)
    
    return {"message": f"Profile updated for {username}", "profile": updated_profile.to_dict()}

@app.post("/profiles/{username}/rename")
async def rename_profile(
    username: str,
    payload: ProfileRename,
    db: Session = Depends(get_db),
    _user: ClerkUser = Depends(get_active_upload_user),
):
    """Carry a profile to a renamed Letterboxd account.

    Letterboxd 404s the old URLs without a redirect, so the residential sync
    workflow needs to rename the canonical profile in place (keeping every
    imported dataset and tracking mapping) before uploading a fresh bundle
    under the new username — otherwise the upload would create a duplicate.
    Shares the ingestion-token trust model with /upload/.
    """
    new_username = payload.new_username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", new_username):
        raise HTTPException(status_code=422, detail="Invalid Letterboxd username")

    profile_repo = ProfileRepository(db)
    profile = profile_repo.get_profile_by_username(username)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    existing = profile_repo.get_profile_by_username(new_username)
    if existing is not None and existing.id != profile.id:
        raise HTTPException(status_code=409, detail="Target username already exists")

    old_username = profile.username
    feed_repointed = profile_repo.rename_profile(profile, new_username)
    _refresh_dashboard_snapshot_cache(db)

    return {
        "message": f"Profile renamed from {old_username} to {new_username}",
        "old_username": old_username,
        "new_username": new_username,
        "feed_repointed": feed_repointed,
    }


@app.delete("/profiles/{username}")
async def delete_profile(
    username: str,
    db: Session = Depends(get_db),
    _user: ClerkUser = Depends(get_admin_user),
):
    """Delete a profile and all associated data"""
    ensure_app_user(db, _user)
    profile_repo = ProfileRepository(db)
    
    profile = profile_repo.get_profile_by_username(username)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    # Clean up any legacy on-disk scrape owned by this canonical profile.
    _remove_scraped_profile_directory(profile.username)
    reopen_fulfilled_requests_for_profile(db, profile, commit=False)
    
    # Delete from database (cascades to ratings, reviews, etc.)
    profile_repo.delete_profile(profile.id)
    _refresh_dashboard_snapshot_cache(db)
    
    return {"message": f"Profile {username} deleted successfully"}

# File Upload Endpoints
@app.post("/upload/")
async def upload_files(
    files: List[UploadFile] = File(...),
    publish_owner_data: bool = Form(default=False),
    require_full_sync: bool = Form(default=False),
    db: Session = Depends(get_db),
    _user: ClerkUser = Depends(get_active_upload_user),
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
                if require_full_sync:
                    validate_import_bundle(analyzer_profile, require_full_manifest=True)
                    if analyzer_profile.source_kind != "full_html_upload":
                        raise ValueError(
                            "Residential imports require a full_html_upload manifest"
                        )
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
                if not existing_profile:
                    # Letterboxd renames leave the stable person id intact: a
                    # bundle under an unknown username that carries a known
                    # person id is an existing profile to rename in place, not
                    # a new account to duplicate.
                    person_id = _bundle_person_id(analyzer_profile)
                    if person_id is not None:
                        renamed_profile = (
                            db.query(Profile)
                            .filter(Profile.letterboxd_person_id == person_id)
                            .one_or_none()
                        )
                        if renamed_profile is not None:
                            old_name = renamed_profile.username
                            profile_repo.rename_profile(renamed_profile, username)
                            LOGGER.info(
                                "Auto-renamed profile %s -> %s via person id %s",
                                old_name, username, person_id,
                            )
                            existing_profile = renamed_profile
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
                db.refresh(profile)
                fulfill_pending_requests(
                    db,
                    profile,
                    resolved_by_user_id=(
                        None if _user.user_id == "ingestion-token" else _user.user_id
                    ),
                )
                
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
    ensure_app_user(db, _user)
    profile_repo = ProfileRepository(db)

    profile = profile_repo.get_profile_by_username(username)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Validate and remove any legacy on-disk scrape before committing the
    # database clear, so a rejected path cannot leave a partial operation.
    _remove_scraped_profile_directory(profile.username)
    reopen_fulfilled_requests_for_profile(db, profile, commit=False)
    profile_repo.clear_profile_data(profile.id)

    _refresh_dashboard_snapshot_cache(db)
    
    return {"message": f"Cleared all scraped data for {username}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
