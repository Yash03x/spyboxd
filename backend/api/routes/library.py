"""Films, Tonight and Data: the library, the decision, and the provenance.

One route file for the three sections that arrived together. Every handler
resolves its selection through the same access check the rest of the analytics
surface uses, so an untracked username is a 403 before any query runs.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth import ClerkUser, get_current_user
from database.connection import get_db
from database.models import Profile
from services.data_health import (
    build_counts,
    build_feeds,
    build_importers,
    build_ledger,
    build_lost_and_found,
    build_lost_list_films,
    build_private,
    build_removed,
    build_request_latency,
    build_watch_event_freshness,
)
from services.films import (
    build_atlas,
    build_collections,
    build_decade_divergence,
    build_filmographies,
    build_keywords,
    build_language_ladder,
    build_liked_vs_rated,
    build_match_rate,
    build_metadata_gaps,
    build_queue_age,
    build_runtime,
)
from services.profile_access import accessible_profiles, authorize_profile_usernames
from services.tonight import (
    build_availability,
    build_blind_spot_favourites,
    build_list_cadence,
    build_list_only_films,
    build_list_progress,
)


router = APIRouter(prefix="/api", tags=["library"])


def _selected_profiles(
    db: Session, user: ClerkUser, requested: Optional[List[str]]
) -> List[Profile]:
    """Resolve an access-checked selection to Profile rows.

    Defined above the first decorated handler on purpose: a helper between
    ``@router.get(...)`` and its function binds the decorator to the helper and
    silently drops the route's auth dependency.
    """

    usernames = authorize_profile_usernames(db, user, requested)
    if not usernames:
        return []
    lowered = {username.casefold() for username in usernames}
    visible = accessible_profiles(db, user)
    return [profile for profile in visible if profile.username.casefold() in lowered]


# --------------------------------------------------------------------------
# 05 Films
# --------------------------------------------------------------------------


@router.get("/films/keywords")
def get_keywords(
    profiles: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Subjects the group returns to, from TMDB keywords."""

    return build_keywords(db, _selected_profiles(db, user, profiles), limit=limit)


@router.get("/films/runtime")
def get_runtime(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """What the group adds against what it finishes, by runtime band."""

    return build_runtime(db, _selected_profiles(db, user, profiles))


@router.get("/films/atlas")
def get_atlas(
    profiles: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Countries, and how much of the library needs reading."""

    return build_atlas(db, _selected_profiles(db, user, profiles), limit=limit)


@router.get("/films/filmographies")
def get_filmographies(
    profiles: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Directors the group holds more than one film from."""

    return build_filmographies(db, _selected_profiles(db, user, profiles), limit=limit)


@router.get("/films/collections")
def get_collections(
    profiles: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Series worked through, counted over films held."""

    return build_collections(db, _selected_profiles(db, user, profiles), limit=limit)


@router.get("/films/liked-vs-rated")
def get_liked_vs_rated(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """The four corners a heart and a score make between them."""

    return build_liked_vs_rated(db, _selected_profiles(db, user, profiles))


@router.get("/films/decade-divergence")
def get_decade_divergence(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Divergence from the crowd, split by the film's decade."""

    return build_decade_divergence(db, _selected_profiles(db, user, profiles))


@router.get("/films/queue-age")
def get_queue_age(
    profiles: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Queue entries that have survived every refresh since they were added."""

    return build_queue_age(db, _selected_profiles(db, user, profiles), limit=limit)


@router.get("/films/language-ladder")
def get_language_ladder(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Non-English share, year over year."""

    return build_language_ladder(db, _selected_profiles(db, user, profiles))


@router.get("/films/metadata-gaps")
def get_metadata_gaps(
    profiles: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Unenriched films, ranked by how often they appear on screen."""

    return build_metadata_gaps(db, _selected_profiles(db, user, profiles), limit=limit)


@router.get("/films/match-rate")
def get_match_rate(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """The ceiling on every metadata panel in the product."""

    return build_match_rate(db, _selected_profiles(db, user, profiles))


# --------------------------------------------------------------------------
# 04 Tonight
# --------------------------------------------------------------------------


@router.get("/tonight/blind-spot-favourites")
def get_blind_spot_favourites(
    profiles: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Top-rated by one person, unlogged by everybody else in the room."""

    return build_blind_spot_favourites(db, _selected_profiles(db, user, profiles), limit=limit)


@router.get("/tonight/list-progress")
def get_list_progress(
    profiles: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """How far the group has got through each readable list."""

    return build_list_progress(db, _selected_profiles(db, user, profiles), limit=limit)


@router.get("/tonight/list-only-films")
def get_list_only_films(
    profiles: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Films on several readable lists that nobody has watched."""

    return build_list_only_films(db, _selected_profiles(db, user, profiles), limit=limit)


@router.get("/tonight/list-cadence")
def get_list_cadence(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Who keeps their lists alive."""

    return build_list_cadence(db, _selected_profiles(db, user, profiles))


@router.get("/tonight/availability")
def get_availability(
    profiles: Optional[List[str]] = Query(default=None),
    region: str = Query(default="IN", min_length=2, max_length=2),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Where a queued film can be streamed, and how fresh that reading is."""

    return build_availability(db, _selected_profiles(db, user, profiles), region=region.upper())


# --------------------------------------------------------------------------
# 06 Data
# --------------------------------------------------------------------------


@router.get("/data-health/ledger")
def get_ledger(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Per-surface refresh ledger: what was read, when, and what came back."""

    return build_ledger(db, _selected_profiles(db, user, profiles))


@router.get("/data-health/feeds")
def get_feeds(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Feed health and backoff."""

    return build_feeds(db, _selected_profiles(db, user, profiles))


@router.get("/data-health/importers")
def get_importers(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Profiles last read by an importer older than the current one."""

    return build_importers(db, _selected_profiles(db, user, profiles))


@router.get("/data-health/counts")
def get_counts(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Letterboxd's own stated total against ours."""

    return build_counts(db, _selected_profiles(db, user, profiles))


@router.get("/data-health/private")
def get_private(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Surfaces we can tell exist without being able to read them."""

    return build_private(db, _selected_profiles(db, user, profiles))


@router.get("/data-health/removed")
def get_removed(
    profiles: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Rows that were there last time and are not now."""

    return build_removed(db, _selected_profiles(db, user, profiles), limit=limit)


@router.get("/data-health/request-latency")
def get_request_latency(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """How long a completed sync actually takes, measured rather than promised."""

    return build_request_latency(db, _selected_profiles(db, user, profiles))


@router.get("/data-health/freshness")
def get_freshness(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """When each profile was last read, and how much came back."""

    return build_watch_event_freshness(db, _selected_profiles(db, user, profiles))


@router.get("/data-health/lost")
def get_lost(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Deleted history we still hold, from official exports only."""

    return build_lost_and_found(db, _selected_profiles(db, user, profiles))


@router.get("/data-health/lost-lists")
def get_lost_lists(
    profiles: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Films from lists that no longer exist."""

    return build_lost_list_films(db, _selected_profiles(db, user, profiles), limit=limit)
