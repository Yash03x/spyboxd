from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import false, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from auth import ClerkUser
from database.models import (
    AppUser,
    Profile,
    ProfileAccessRequest,
    Rating,
    UserTrackedProfile,
)


PROFILE_USERNAME = re.compile(r"[A-Za-z0-9_]{2,15}")
REQUEST_STATUSES = {"pending", "approved", "rejected", "fulfilled"}
ADMIN_DECISIONS = {"approved", "rejected"}


def _positive_limit(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def normalize_profile_username(raw_username: str) -> tuple[str, str]:
    username = (raw_username or "").strip().lstrip("@")
    if not PROFILE_USERNAME.fullmatch(username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Enter a valid Letterboxd username.",
        )
    return username, username.casefold()


def _normalize_stored_profile_lookup(raw_username: str) -> str:
    """Normalize an existing profile key without re-validating legacy data.

    New identities and requests must follow Letterboxd's current username
    rules. Existing rows may predate that validation, however, and users must
    still be able to remove one from their monitoring set.
    """

    username = (raw_username or "").strip().lstrip("@")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Enter a profile username.",
        )
    return username.casefold()


def ensure_app_user(db: Session, clerk_user: ClerkUser) -> AppUser:
    # Every authenticated entry point goes through identity provisioning. This
    # prevents a new account from bypassing mandatory onboarding by visiting a
    # route other than /api/me first.
    provision_app_user_identity(db, clerk_user)
    return (
        db.query(AppUser)
        .filter(AppUser.clerk_user_id == clerk_user.user_id)
        .one()
    )


def _tracked_profile_mapping(db: Session, app_user_id: int) -> dict[str, Profile]:
    rows = (
        db.query(Profile)
        .join(UserTrackedProfile, UserTrackedProfile.profile_id == Profile.id)
        .filter(UserTrackedProfile.user_id == app_user_id)
        .all()
    )
    mapping: dict[str, Profile] = {}
    for profile in rows:
        normalized = profile.username.casefold()
        existing = mapping.get(normalized)
        if existing is not None and existing.id != profile.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Case-insensitive profile username collision requires admin resolution.",
            )
        mapping[normalized] = profile
    return mapping


def _single_profile_by_normalized_username(
    db: Session,
    normalized_username: str,
    *,
    tracked_by_user_id: Optional[int] = None,
) -> Optional[Profile]:
    query = db.query(Profile)
    if tracked_by_user_id is not None:
        query = query.join(
            UserTrackedProfile,
            UserTrackedProfile.profile_id == Profile.id,
        ).filter(UserTrackedProfile.user_id == tracked_by_user_id)
    matches = (
        query.filter(func.lower(Profile.username) == normalized_username)
        .order_by(Profile.id.asc())
        .limit(2)
        .all()
    )
    if len(matches) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Case-insensitive profile username collision requires admin resolution.",
        )
    return matches[0] if matches else None


def accessible_profiles(db: Session, clerk_user: ClerkUser) -> list[Profile]:
    app_user = ensure_app_user(db, clerk_user)
    if clerk_user.is_admin:
        return db.query(Profile).order_by(Profile.updated_at.desc()).all()
    return tracked_profiles(db, clerk_user, app_user=app_user)


def tracked_profiles(
    db: Session,
    clerk_user: ClerkUser,
    *,
    app_user: Optional[AppUser] = None,
) -> list[Profile]:
    """Return only the caller's personal monitoring set, including for admins."""

    resolved_user = app_user or ensure_app_user(db, clerk_user)
    return (
        db.query(Profile)
        .join(UserTrackedProfile, UserTrackedProfile.profile_id == Profile.id)
        .filter(UserTrackedProfile.user_id == resolved_user.id)
        .order_by(Profile.updated_at.desc())
        .all()
    )


def list_profile_catalog(
    db: Session,
    clerk_user: ClerkUser,
    *,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """List completed profiles a signed-in user can choose to monitor.

    The catalog intentionally exposes only recognition fields and aggregate film
    counts. Pending, errored, and inactive profiles stay in the admin library
    and are never offered as selectable monitoring targets.
    """

    app_user = ensure_app_user(db, clerk_user)
    tracked_profile_ids = {
        profile_id
        for (profile_id,) in (
            db.query(UserTrackedProfile.profile_id)
            .filter(UserTrackedProfile.user_id == app_user.id)
            .all()
        )
    }

    query = db.query(Profile).filter(
        Profile.is_active.is_(True),
        Profile.scraping_status == "completed",
    )
    normalized_search = (search or "").strip().casefold()
    if normalized_search:
        pattern = f"%{normalized_search}%"
        query = query.filter(
            func.lower(Profile.username).like(pattern)
            | func.lower(func.coalesce(Profile.display_name, "")).like(pattern)
        )

    total = query.count()
    profiles = (
        query.order_by(func.lower(Profile.username).asc(), Profile.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    profile_ids = [profile.id for profile in profiles]
    rating_counts = {
        profile_id: count
        for profile_id, count in (
            db.query(Rating.profile_id, func.count(Rating.id))
            .filter(Rating.profile_id.in_(profile_ids) if profile_ids else false())
            .group_by(Rating.profile_id)
            .all()
        )
    }

    return {
        "profiles": [
            {
                "id": profile.id,
                "username": profile.username,
                "display_name": profile.display_name,
                "profile_image_url": profile.profile_image_url,
                "total_films": rating_counts.get(profile.id, 0),
                "is_tracked": profile.id in tracked_profile_ids,
            }
            for profile in profiles
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def track_profile_by_id(
    db: Session,
    clerk_user: ClerkUser,
    profile_id: int,
) -> dict[str, Any]:
    """Idempotently monitor one selectable catalog profile for this user."""

    app_user = ensure_app_user(db, clerk_user)
    profile = (
        db.query(Profile)
        .filter(
            Profile.id == profile_id,
            Profile.is_active.is_(True),
            Profile.scraping_status == "completed",
        )
        .first()
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Selectable profile not found")

    _add_tracking(
        db,
        app_user_id=app_user.id,
        profile_id=profile.id,
        source="direct",
    )
    db.commit()
    return {
        "message": f"{profile.username} is now monitored.",
        "status": "tracked",
        "profile": profile_summary(profile),
    }


def authorize_profile_usernames(
    db: Session,
    clerk_user: ClerkUser,
    requested: Optional[Sequence[str]],
) -> list[str]:
    """Return a canonical, access-checked selection for an analytics request.

    An omitted selection expands only to the caller's completed tracked profiles.
    Explicit untracked names are rejected with 403 before analytics code runs.
    """

    cleaned: list[str] = []
    seen: set[str] = set()
    for value in requested or []:
        username = (value or "").strip()
        key = username.casefold()
        if username and key not in seen:
            cleaned.append(username)
            seen.add(key)

    app_user = ensure_app_user(db, clerk_user)
    if clerk_user.is_admin:
        if not cleaned:
            return []
        matches = (
            db.query(Profile)
            .filter(func.lower(Profile.username).in_(seen))
            .all()
        )
        by_username: dict[str, Profile] = {}
        for profile in matches:
            normalized = profile.username.casefold()
            existing = by_username.get(normalized)
            if existing is not None and existing.id != profile.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Case-insensitive profile username collision requires admin resolution.",
                )
            by_username[normalized] = profile
        return [
            by_username[value.casefold()].username
            if value.casefold() in by_username
            else value
            for value in cleaned
        ]

    tracked = _tracked_profile_mapping(db, app_user.id)
    if cleaned:
        forbidden = [value for value in cleaned if value.casefold() not in tracked]
        if forbidden:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": "Track every requested profile before using it in analytics.",
                    "untracked_profiles": forbidden,
                },
            )
        return [tracked[value.casefold()].username for value in cleaned]

    return sorted(
        profile.username
        for profile in tracked.values()
        if profile.is_active and profile.scraping_status == "completed"
    )


def require_profile_access(
    db: Session,
    clerk_user: ClerkUser,
    username: str,
) -> Profile:
    normalized = username.strip().casefold()
    app_user = ensure_app_user(db, clerk_user)
    if clerk_user.is_admin:
        profile = _single_profile_by_normalized_username(db, normalized)
        if profile is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        return profile

    profile = _single_profile_by_normalized_username(
        db,
        normalized,
        tracked_by_user_id=app_user.id,
    )
    if profile is None:
        existing = _single_profile_by_normalized_username(db, normalized)
        if existing is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Track this profile before accessing its analytics.",
        )
    return profile


def _lock_user_access_mutations(db: Session, app_user_id: int) -> None:
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        # Transaction-scoped and stable across every process serving this DB.
        db.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :user_id)"),
            {"namespace": 5_454_297, "user_id": app_user_id},
        )


def _add_tracking(
    db: Session,
    *,
    app_user_id: int,
    profile_id: int,
    source: str,
    enforce_limit: bool = True,
) -> UserTrackedProfile:
    # Serialize count-and-insert for one user so concurrent requests cannot
    # both observe a free slot and exceed the per-user tracking cap.
    _lock_user_access_mutations(db, app_user_id)

    tracked = (
        db.query(UserTrackedProfile)
        .filter(
            UserTrackedProfile.user_id == app_user_id,
            UserTrackedProfile.profile_id == profile_id,
        )
        .first()
    )
    if tracked is None:
        if enforce_limit:
            tracked_count = (
                db.query(UserTrackedProfile.id)
                .filter(UserTrackedProfile.user_id == app_user_id)
                .count()
            )
            max_tracked = _positive_limit("SPYBOXD_MAX_TRACKED_PROFILES_PER_USER", 25)
            if tracked_count >= max_tracked:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"You can track at most {max_tracked} profiles.",
                )
        tracked = UserTrackedProfile(
            user_id=app_user_id,
            profile_id=profile_id,
            source=source,
        )
        try:
            with db.begin_nested():
                db.add(tracked)
                db.flush()
        except IntegrityError:
            # The unique constraint is the final idempotency guard during a
            # mixed-version deploy or on databases without advisory locks.
            tracked = (
                db.query(UserTrackedProfile)
                .filter(
                    UserTrackedProfile.user_id == app_user_id,
                    UserTrackedProfile.profile_id == profile_id,
                )
                .first()
            )
            if tracked is None:
                raise
    return tracked


def profile_summary(profile: Profile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "username": profile.username,
        "display_name": profile.display_name,
        "profile_image_url": profile.profile_image_url,
        "scraping_status": profile.scraping_status,
        "is_active": bool(profile.is_active),
    }


def _missing_required_identity() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "Your account is missing its required Letterboxd username. "
            "Sign out and complete sign-up again, or contact an administrator."
        ),
    )


def _identity_status_without_provisioning(
    db: Session,
    *,
    app_user: AppUser,
    username: str,
    normalized_username: str,
) -> dict[str, Any]:
    """Describe a grandfathered identity without creating access or a request."""

    profile = _single_profile_by_normalized_username(db, normalized_username)
    if profile is not None:
        tracked = (
            db.query(UserTrackedProfile.id)
            .filter(
                UserTrackedProfile.user_id == app_user.id,
                UserTrackedProfile.profile_id == profile.id,
            )
            .first()
        )
        if tracked is not None:
            return {
                "letterboxd_username": username,
                "primary_profile_status": "tracked",
            }

    request = (
        db.query(ProfileAccessRequest)
        .filter(
            ProfileAccessRequest.user_id == app_user.id,
            ProfileAccessRequest.normalized_username == normalized_username,
        )
        .first()
    )
    if request is not None:
        request_status = (
            request.status
            if request.status in {"pending", "approved", "rejected"}
            else "unlinked"
        )
        return {
            "letterboxd_username": username,
            "primary_profile_status": request_status,
        }

    if (
        profile is not None
        and profile.is_active
        and profile.scraping_status == "completed"
    ):
        return {
            "letterboxd_username": username,
            "primary_profile_status": "available",
        }

    return {
        "letterboxd_username": username,
        "primary_profile_status": "unlinked",
    }


def _provision_app_user_identity_once(
    db: Session,
    clerk_user: ClerkUser,
    *,
    claimed_username: Optional[str],
    claimed_normalized_username: Optional[str],
) -> dict[str, Any]:
    app_user = (
        db.query(AppUser)
        .filter(AppUser.clerk_user_id == clerk_user.user_id)
        .first()
    )
    if app_user is None:
        if claimed_username is None and not clerk_user.is_admin:
            raise _missing_required_identity()
        app_user = AppUser(
            clerk_user_id=clerk_user.user_id,
            letterboxd_username=claimed_username,
            # Admin/service compatibility is intentionally exempt. All new
            # ordinary accounts must finish the primary-profile flow.
            primary_profile_required=not clerk_user.is_admin,
        )
        db.add(app_user)
        db.flush()
    elif not app_user.is_active:
        raise HTTPException(status_code=403, detail="User access is disabled")

    # Admin identities remain compatible even if an older application process
    # inserted their row after the migration's grandfathering UPDATE.
    if clerk_user.is_admin and app_user.primary_profile_required:
        app_user.primary_profile_required = False
        db.flush()

    stored_username: Optional[str] = app_user.letterboxd_username
    stored_normalized_username: Optional[str] = None
    if stored_username is not None:
        stored_username, stored_normalized_username = normalize_profile_username(
            stored_username
        )

    if claimed_username is not None:
        if stored_username is None:
            app_user.letterboxd_username = claimed_username
            stored_username = claimed_username
            stored_normalized_username = claimed_normalized_username
            db.flush()
        elif stored_normalized_username != claimed_normalized_username:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Your Clerk username no longer matches the Letterboxd username "
                    "linked to this Spyboxd account. Contact an administrator to migrate it."
                ),
            )

    if stored_username is None or stored_normalized_username is None:
        if app_user.primary_profile_required:
            raise _missing_required_identity()
        db.commit()
        return {
            "letterboxd_username": None,
            "primary_profile_status": "unconfigured",
        }

    if not app_user.primary_profile_required:
        identity = _identity_status_without_provisioning(
            db,
            app_user=app_user,
            username=stored_username,
            normalized_username=stored_normalized_username,
        )
        db.commit()
        return identity

    _lock_user_access_mutations(db, app_user.id)
    profile = _single_profile_by_normalized_username(
        db,
        stored_normalized_username,
    )
    tracked = None
    if profile is not None:
        tracked = (
            db.query(UserTrackedProfile)
            .filter(
                UserTrackedProfile.user_id == app_user.id,
                UserTrackedProfile.profile_id == profile.id,
            )
            .first()
        )
    if tracked is not None:
        db.commit()
        return {
            "letterboxd_username": stored_username,
            "primary_profile_status": "tracked",
        }

    request = (
        db.query(ProfileAccessRequest)
        .filter(
            ProfileAccessRequest.user_id == app_user.id,
            ProfileAccessRequest.normalized_username
            == stored_normalized_username,
        )
        .first()
    )

    # An automatic first-login retry must not undo a moderator's rejection.
    if request is not None and request.status == "rejected":
        db.commit()
        return {
            "letterboxd_username": stored_username,
            "primary_profile_status": "rejected",
        }

    if (
        profile is not None
        and profile.is_active
        and profile.scraping_status == "completed"
    ):
        _add_tracking(
            db,
            app_user_id=app_user.id,
            profile_id=profile.id,
            source="direct",
            # The mandatory primary identity is not an optional monitoring slot.
            enforce_limit=False,
        )
        if request is not None:
            request.status = "fulfilled"
            request.fulfilled_profile_id = profile.id
            request.resolved_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "letterboxd_username": stored_username,
            "primary_profile_status": "tracked",
        }

    if request is not None:
        request_status = (
            request.status
            if request.status in {"pending", "approved", "rejected"}
            else "unlinked"
        )
        db.commit()
        return {
            "letterboxd_username": stored_username,
            "primary_profile_status": request_status,
        }

    db.add(
        ProfileAccessRequest(
            user_id=app_user.id,
            requested_username=stored_username,
            normalized_username=stored_normalized_username,
            status="pending",
        )
    )
    db.flush()
    db.commit()
    return {
        "letterboxd_username": stored_username,
        "primary_profile_status": "pending",
    }


def provision_app_user_identity(
    db: Session,
    clerk_user: ClerkUser,
) -> dict[str, Any]:
    """Atomically bind a Clerk identity to its mandatory Letterboxd profile.

    Clerk's stable subject remains the authorization key. The signed username is
    copied once into the local user row, then the existing shared-profile access
    model either grants the completed profile or queues exactly one sync request.
    A migration marker keeps pre-existing users and admins on their old behavior.
    """

    if clerk_user.user_id == "ingestion-token" and clerk_user.session_id is None:
        return {
            "letterboxd_username": None,
            "primary_profile_status": "unconfigured",
        }

    claimed_username: Optional[str] = None
    claimed_normalized_username: Optional[str] = None
    if clerk_user.letterboxd_username is not None:
        claimed_username, claimed_normalized_username = normalize_profile_username(
            clerk_user.letterboxd_username
        )

    for attempt in range(2):
        try:
            return _provision_app_user_identity_once(
                db,
                clerk_user,
                claimed_username=claimed_username,
                claimed_normalized_username=claimed_normalized_username,
            )
        except IntegrityError as exc:
            db.rollback()
            concurrent_user = (
                db.query(AppUser)
                .filter(AppUser.clerk_user_id == clerk_user.user_id)
                .first()
            )
            if concurrent_user is not None and attempt == 0:
                continue
            if claimed_normalized_username is not None:
                conflicting_user = (
                    db.query(AppUser)
                    .filter(
                        func.lower(AppUser.letterboxd_username)
                        == claimed_normalized_username
                    )
                    .first()
                )
                if conflicting_user is not None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="This Letterboxd username is already linked to another Spyboxd account.",
                    ) from exc
            raise
        except Exception:
            db.rollback()
            raise

    raise RuntimeError("Unreachable identity provisioning retry state")


def request_summary(
    request: ProfileAccessRequest,
    *,
    include_admin_fields: bool = False,
) -> dict[str, Any]:
    summary = {
        "id": request.id,
        "requested_username": request.requested_username,
        "status": request.status,
        "requested_at": request.requested_at.isoformat() if request.requested_at else None,
        "updated_at": request.updated_at.isoformat() if request.updated_at else None,
        "resolved_at": request.resolved_at.isoformat() if request.resolved_at else None,
        "profile": (
            profile_summary(request.fulfilled_profile)
            if request.fulfilled_profile is not None
            else None
        ),
    }
    if include_admin_fields:
        summary.update(
            {
                "requester_user_id": (
                    request.user.clerk_user_id if request.user else None
                ),
                "note": request.admin_note,
                "resolved_by_user_id": request.resolved_by_clerk_user_id,
            }
        )
    return summary


def _request_is_required_primary(request: ProfileAccessRequest) -> bool:
    app_user = request.user
    return bool(
        app_user is not None
        and app_user.primary_profile_required
        and app_user.letterboxd_username
        and app_user.letterboxd_username.casefold()
        == request.normalized_username.casefold()
    )


def fulfill_pending_requests(
    db: Session,
    profile: Profile,
    *,
    resolved_by_user_id: Optional[str] = None,
    commit: bool = True,
) -> int:
    if not getattr(profile, "is_active", False) or getattr(profile, "scraping_status", None) != "completed":
        return 0
    normalized = profile.username.casefold()
    requests = (
        db.query(ProfileAccessRequest)
        .options(joinedload(ProfileAccessRequest.user))
        .filter(
            ProfileAccessRequest.normalized_username == normalized,
            ProfileAccessRequest.status.in_(("pending", "approved")),
        )
        .order_by(ProfileAccessRequest.user_id.asc(), ProfileAccessRequest.id.asc())
        .all()
    )
    now = datetime.now(timezone.utc)
    fulfilled_count = 0
    for request in requests:
        try:
            _add_tracking(
                db,
                app_user_id=request.user_id,
                profile_id=profile.id,
                source="request_fulfillment",
                enforce_limit=not _request_is_required_primary(request),
            )
        except HTTPException as exc:
            if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                continue
            raise
        request.status = "fulfilled"
        request.fulfilled_profile_id = profile.id
        request.resolved_at = now
        request.resolved_by_clerk_user_id = resolved_by_user_id
        fulfilled_count += 1
    if commit and fulfilled_count:
        db.commit()
    return fulfilled_count


def preserve_profile_tracking_requests(
    db: Session,
    profile: Profile,
    *,
    commit: bool = True,
) -> int:
    normalized = profile.username.casefold()
    tracked_user_ids = {
        user_id
        for (user_id,) in (
            db.query(UserTrackedProfile.user_id)
            .filter(UserTrackedProfile.profile_id == profile.id)
            .all()
        )
    }
    requests = (
        db.query(ProfileAccessRequest)
        .filter(
            ProfileAccessRequest.normalized_username == normalized,
            (
                ProfileAccessRequest.fulfilled_profile_id == profile.id
            )
            | ProfileAccessRequest.user_id.in_(tracked_user_ids),
        )
        .all()
    )
    by_user_id = {request.user_id: request for request in requests}
    preserved_user_ids = set(tracked_user_ids)
    preserved_user_ids.update(
        request.user_id
        for request in requests
        if request.fulfilled_profile_id == profile.id
        and request.status == "fulfilled"
    )
    changed = 0
    for user_id in preserved_user_ids:
        request = by_user_id.get(user_id)
        if request is None:
            request = ProfileAccessRequest(
                user_id=user_id,
                requested_username=profile.username,
                normalized_username=normalized,
                status="approved",
            )
            db.add(request)
        else:
            request.requested_username = profile.username
            request.normalized_username = normalized
            request.status = "approved"
            request.fulfilled_profile_id = None
        changed += 1
    if commit and changed:
        db.commit()
    return changed


def reopen_fulfilled_requests_for_profile(
    db: Session,
    profile: Profile,
    *,
    commit: bool = True,
) -> int:
    """Backward-compatible name for preserving access across destructive syncs."""

    return preserve_profile_tracking_requests(db, profile, commit=commit)


def track_or_request_profile(
    db: Session,
    clerk_user: ClerkUser,
    raw_username: str,
) -> dict[str, Any]:
    username, normalized = normalize_profile_username(raw_username)
    app_user = ensure_app_user(db, clerk_user)
    _lock_user_access_mutations(db, app_user.id)
    profile = _single_profile_by_normalized_username(db, normalized)
    if (
        profile is not None
        and profile.is_active
        and profile.scraping_status == "completed"
    ):
        _add_tracking(
            db,
            app_user_id=app_user.id,
            profile_id=profile.id,
            source="direct",
        )
        own_request = (
            db.query(ProfileAccessRequest)
            .filter(
                ProfileAccessRequest.user_id == app_user.id,
                ProfileAccessRequest.normalized_username == normalized,
            )
            .first()
        )
        if own_request is not None and own_request.status != "fulfilled":
            own_request.status = "fulfilled"
            own_request.fulfilled_profile_id = profile.id
            own_request.resolved_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "message": f"{profile.username} is now tracked.",
            "status": "tracked",
            "profile": profile_summary(profile),
            "request": request_summary(own_request) if own_request is not None else None,
        }

    request = (
        db.query(ProfileAccessRequest)
        .options(joinedload(ProfileAccessRequest.user))
        .filter(
            ProfileAccessRequest.user_id == app_user.id,
            ProfileAccessRequest.normalized_username == normalized,
        )
        .first()
    )
    if request is None:
        active_request_count = (
            db.query(ProfileAccessRequest.id)
            .filter(
                ProfileAccessRequest.user_id == app_user.id,
                ProfileAccessRequest.status.in_(("pending", "approved")),
            )
            .count()
        )
        max_pending = _positive_limit("SPYBOXD_MAX_PENDING_PROFILE_REQUESTS_PER_USER", 10)
        if active_request_count >= max_pending:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"You can have at most {max_pending} active profile requests.",
            )
        new_request = ProfileAccessRequest(
            user_id=app_user.id,
            requested_username=username,
            normalized_username=normalized,
            status="pending",
        )
        try:
            with db.begin_nested():
                db.add(new_request)
                db.flush()
            request = new_request
        except IntegrityError:
            request = (
                db.query(ProfileAccessRequest)
                .options(joinedload(ProfileAccessRequest.user))
                .filter(
                    ProfileAccessRequest.user_id == app_user.id,
                    ProfileAccessRequest.normalized_username == normalized,
                )
                .one()
            )
    elif request.status == "rejected":
        active_request_count = (
            db.query(ProfileAccessRequest.id)
            .filter(
                ProfileAccessRequest.user_id == app_user.id,
                ProfileAccessRequest.status.in_(("pending", "approved")),
            )
            .count()
        )
        max_pending = _positive_limit("SPYBOXD_MAX_PENDING_PROFILE_REQUESTS_PER_USER", 10)
        if active_request_count >= max_pending:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"You can have at most {max_pending} active profile requests.",
            )
        request.status = "pending"
        request.requested_username = username
        request.admin_note = None
        request.resolved_at = None
        request.resolved_by_clerk_user_id = None
    db.commit()
    db.refresh(request)
    return {
        "message": f"{username} was requested for the next residential sync.",
        "status": "pending",
        "profile": profile_summary(profile) if profile is not None else None,
        "request": request_summary(request),
    }


def list_profile_requests(
    db: Session,
    clerk_user: ClerkUser,
    *,
    include_all: bool = False,
    request_status: Optional[str] = None,
) -> list[dict[str, Any]]:
    app_user = ensure_app_user(db, clerk_user)
    if request_status is not None and request_status not in REQUEST_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid request status")
    query = db.query(ProfileAccessRequest).options(
        joinedload(ProfileAccessRequest.user),
        joinedload(ProfileAccessRequest.fulfilled_profile),
    )
    if include_all:
        if not clerk_user.is_admin:
            raise HTTPException(status_code=403, detail="Admin role required")
    else:
        query = query.filter(ProfileAccessRequest.user_id == app_user.id)
    if request_status is not None:
        query = query.filter(ProfileAccessRequest.status == request_status)
    requests = query.order_by(
        ProfileAccessRequest.requested_at.desc(),
        ProfileAccessRequest.id.desc(),
    ).all()
    return [
        request_summary(request, include_admin_fields=include_all)
        for request in requests
    ]


def decide_profile_request(
    db: Session,
    clerk_user: ClerkUser,
    request_id: int,
    *,
    decision: str,
    note: Optional[str],
) -> dict[str, Any]:
    ensure_app_user(db, clerk_user)
    if not clerk_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required")
    if decision not in ADMIN_DECISIONS:
        raise HTTPException(status_code=400, detail="Status must be approved or rejected")
    request = (
        db.query(ProfileAccessRequest)
        .options(joinedload(ProfileAccessRequest.user))
        .filter(ProfileAccessRequest.id == request_id)
        .first()
    )
    if request is None:
        raise HTTPException(status_code=404, detail="Profile request not found")
    if request.status == "fulfilled":
        raise HTTPException(
            status_code=409,
            detail="Fulfilled access must be removed through profile tracking.",
        )

    request.status = decision
    request.admin_note = (note or "").strip() or None
    request.resolved_by_clerk_user_id = clerk_user.user_id
    request.resolved_at = datetime.now(timezone.utc)
    if decision == "approved":
        profile = _single_profile_by_normalized_username(
            db,
            request.normalized_username,
        )
        if (
            profile is not None
            and profile.is_active
            and profile.scraping_status == "completed"
        ):
            try:
                _add_tracking(
                    db,
                    app_user_id=request.user_id,
                    profile_id=profile.id,
                    source="request_fulfillment",
                    enforce_limit=not _request_is_required_primary(request),
                )
            except HTTPException as exc:
                if exc.status_code != status.HTTP_429_TOO_MANY_REQUESTS:
                    raise
            else:
                request.status = "fulfilled"
                request.fulfilled_profile_id = profile.id
    db.commit()
    db.refresh(request)
    return request_summary(request, include_admin_fields=True)


def untrack_profile(db: Session, clerk_user: ClerkUser, username: str) -> bool:
    normalized = _normalize_stored_profile_lookup(username)
    app_user = ensure_app_user(db, clerk_user)
    primary_username = app_user.letterboxd_username
    if app_user.primary_profile_required and primary_username is not None:
        normalized_primary = primary_username.casefold()
        if normalized == normalized_primary:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Your primary Letterboxd profile cannot be untracked.",
            )
    _lock_user_access_mutations(db, app_user.id)
    profile = _single_profile_by_normalized_username(
        db,
        normalized,
        tracked_by_user_id=app_user.id,
    )
    if profile is None:
        return False
    deleted = (
        db.query(UserTrackedProfile)
        .filter(
            UserTrackedProfile.user_id == app_user.id,
            UserTrackedProfile.profile_id == profile.id,
        )
        .delete(synchronize_session=False)
    )
    if deleted:
        db.query(ProfileAccessRequest).filter(
            ProfileAccessRequest.user_id == app_user.id,
            ProfileAccessRequest.fulfilled_profile_id == profile.id,
            ProfileAccessRequest.status == "fulfilled",
        ).delete(synchronize_session=False)
    db.commit()
    return bool(deleted)
