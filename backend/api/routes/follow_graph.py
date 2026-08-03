from __future__ import annotations

from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional, Sequence

from fastapi import APIRouter, Depends, Query
from sqlalchemy import false, func
from sqlalchemy.orm import Session

from auth import ClerkUser, get_current_user
from database.connection import get_db
from database.models import Profile, ProfileFollowEdge
from services.profile_access import (
    accessible_profiles,
    authorize_profile_usernames,
    require_profile_access,
)


router = APIRouter(prefix="/api", tags=["follow graph"])


def _imported_profile_flags(
    db: Session,
    counterpart_profile_ids: Iterable[Optional[int]],
) -> Dict[int, bool]:
    """Bulk-resolve which linked counterpart profiles are selectable imports.

    A counterpart only counts as imported when its canonical profile is active
    and completed, matching the catalog rules behind ``track_profile_by_id``.
    """

    profile_ids = {profile_id for profile_id in counterpart_profile_ids if profile_id is not None}
    if not profile_ids:
        return {}
    rows = (
        db.query(Profile.id, Profile.is_active, Profile.scraping_status)
        .filter(Profile.id.in_(profile_ids))
        .all()
    )
    return {
        profile_id: bool(is_active) and scraping_status == "completed"
        for profile_id, is_active, scraping_status in rows
    }


@router.get("/profiles/{username}/follow-graph")
def get_profile_follow_graph(
    username: str,
    direction: str = Query(default="both", pattern="^(following|followers|both)$"),
    include_removed: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Return one tracked profile's observed following/followers edges."""

    profile = require_profile_access(db, user, username)

    query = db.query(ProfileFollowEdge).filter(
        ProfileFollowEdge.profile_id == profile.id
    )
    if direction == "following":
        query = query.filter(ProfileFollowEdge.direction == "following")
    elif direction == "followers":
        query = query.filter(ProfileFollowEdge.direction == "follower")
    if not include_removed:
        query = query.filter(ProfileFollowEdge.removed_at.is_(None))

    total = query.count()
    edges = (
        query.order_by(
            ProfileFollowEdge.direction.asc(),
            ProfileFollowEdge.position.asc().nulls_last(),
            ProfileFollowEdge.counterpart_username_normalized.asc(),
            ProfileFollowEdge.id.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    imported_flags = _imported_profile_flags(
        db,
        (edge.counterpart_profile_id for edge in edges),
    )

    return {
        "username": profile.username,
        "following_count": profile.following_count,
        "followers_count": profile.followers_count,
        "edges": [
            {
                "direction": edge.direction,
                "counterpart_username": edge.counterpart_username,
                "counterpart_display_name": edge.counterpart_display_name,
                "counterpart_avatar_url": edge.counterpart_avatar_url,
                "counterpart_profile_url": edge.counterpart_profile_url,
                "position": edge.position,
                "is_imported_profile": imported_flags.get(
                    edge.counterpart_profile_id, False
                ),
                "counterpart_profile_id": edge.counterpart_profile_id,
                "removed_at": edge.removed_at.isoformat() if edge.removed_at else None,
            }
            for edge in edges
        ],
        "total": total,
    }


def _active_edge_pairs(
    db: Session,
    profile_ids: Sequence[int],
    normalized_usernames: Sequence[str],
) -> tuple[set[tuple[int, str]], set[tuple[int, str]]]:
    """Load active edges among a group as (profile_id, counterpart) key sets."""

    if not profile_ids or not normalized_usernames:
        return set(), set()
    rows = (
        db.query(
            ProfileFollowEdge.profile_id,
            ProfileFollowEdge.direction,
            ProfileFollowEdge.counterpart_username_normalized,
        )
        .filter(
            ProfileFollowEdge.profile_id.in_(profile_ids),
            ProfileFollowEdge.counterpart_username_normalized.in_(normalized_usernames),
            ProfileFollowEdge.removed_at.is_(None),
        )
        .all()
    )
    following_pairs: set[tuple[int, str]] = set()
    follower_pairs: set[tuple[int, str]] = set()
    for profile_id, edge_direction, counterpart in rows:
        if edge_direction == "following":
            following_pairs.add((profile_id, counterpart))
        elif edge_direction == "follower":
            follower_pairs.add((profile_id, counterpart))
    return following_pairs, follower_pairs


@router.get("/follow-graph/mutuals")
def get_follow_graph_mutuals(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Report mutual/one-way follow relationships within a selected group."""

    selection = authorize_profile_usernames(db, user, profiles)
    if user.is_admin and profiles is None:
        selection = sorted(
            (profile.username for profile in accessible_profiles(db, user)),
            key=str.casefold,
        )

    profile_rows = (
        db.query(Profile)
        .filter(
            func.lower(Profile.username).in_(
                {username.casefold() for username in selection}
            )
            if selection
            else false()
        )
        .all()
    )
    profile_id_by_normalized = {
        profile.username.casefold(): profile.id for profile in profile_rows
    }
    normalized_selection = [username.casefold() for username in selection]
    following_pairs, follower_pairs = _active_edge_pairs(
        db,
        list(profile_id_by_normalized.values()),
        normalized_selection,
    )

    def _follows(source: str, target: str) -> bool:
        """Active (source, 'following', target) with (target, 'follower', source) corroboration."""

        source_id = profile_id_by_normalized.get(source)
        target_id = profile_id_by_normalized.get(target)
        if source_id is not None and (source_id, target) in following_pairs:
            return True
        return target_id is not None and (target_id, source) in follower_pairs

    pairs: List[Dict[str, Any]] = []
    follows_in_group: Dict[str, int] = {username: 0 for username in selection}
    followed_by_in_group: Dict[str, int] = {username: 0 for username in selection}
    for username_a, username_b in combinations(selection, 2):
        a_follows_b = _follows(username_a.casefold(), username_b.casefold())
        b_follows_a = _follows(username_b.casefold(), username_a.casefold())
        pairs.append(
            {
                "a": username_a,
                "b": username_b,
                "a_follows_b": a_follows_b,
                "b_follows_a": b_follows_a,
                "mutual": a_follows_b and b_follows_a,
            }
        )
        if a_follows_b:
            follows_in_group[username_a] += 1
            followed_by_in_group[username_b] += 1
        if b_follows_a:
            follows_in_group[username_b] += 1
            followed_by_in_group[username_a] += 1

    return {
        "profiles": selection,
        "pairs": pairs,
        "rollups": {
            username: {
                "follows_in_group": follows_in_group[username],
                "followed_by_in_group": followed_by_in_group[username],
            }
            for username in selection
        },
    }


@router.get("/follow-graph/suggestions")
def get_follow_graph_suggestions(
    limit: int = Query(default=20, ge=1, le=100),
    min_overlap: int = Query(default=2, ge=1, le=100),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Suggest counterparts followed by several of the caller's profiles."""

    scoped = accessible_profiles(db, user)
    scoped_ids = [profile.id for profile in scoped]
    scoped_username_by_id = {profile.id: profile.username for profile in scoped}
    scoped_normalized = {profile.username.casefold() for profile in scoped}

    overlap_count = func.count(func.distinct(ProfileFollowEdge.profile_id))
    scope_filters = [
        ProfileFollowEdge.direction == "following",
        ProfileFollowEdge.removed_at.is_(None),
        ProfileFollowEdge.profile_id.in_(scoped_ids) if scoped_ids else false(),
    ]
    if scoped_normalized:
        scope_filters.append(
            ProfileFollowEdge.counterpart_username_normalized.notin_(scoped_normalized)
        )
    aggregate_rows = (
        db.query(
            ProfileFollowEdge.counterpart_username_normalized.label("normalized"),
            func.max(ProfileFollowEdge.counterpart_username).label("username"),
            overlap_count.label("followed_by_count"),
        )
        .filter(*scope_filters)
        .group_by(ProfileFollowEdge.counterpart_username_normalized)
        .having(overlap_count >= min_overlap)
        .order_by(
            overlap_count.desc(),
            func.max(ProfileFollowEdge.counterpart_username).asc(),
        )
        .limit(limit)
        .all()
    )
    selected_normalized = [row.normalized for row in aggregate_rows]
    if not selected_normalized:
        return {"suggestions": [], "monitored_profiles": len(scoped_ids)}

    followed_by: Dict[str, List[str]] = {
        normalized: [] for normalized in selected_normalized
    }
    followed_by_rows = (
        db.query(
            ProfileFollowEdge.counterpart_username_normalized,
            ProfileFollowEdge.profile_id,
        )
        .filter(
            ProfileFollowEdge.direction == "following",
            ProfileFollowEdge.removed_at.is_(None),
            ProfileFollowEdge.profile_id.in_(scoped_ids),
            ProfileFollowEdge.counterpart_username_normalized.in_(selected_normalized),
        )
        .distinct()
        .all()
    )
    for normalized, profile_id in followed_by_rows:
        username = scoped_username_by_id.get(profile_id)
        if username is not None:
            followed_by[normalized].append(username)

    follows_back_counts = {
        normalized: count
        for normalized, count in (
            db.query(
                ProfileFollowEdge.counterpart_username_normalized,
                func.count(func.distinct(ProfileFollowEdge.profile_id)),
            )
            .filter(
                ProfileFollowEdge.direction == "follower",
                ProfileFollowEdge.removed_at.is_(None),
                ProfileFollowEdge.profile_id.in_(scoped_ids),
                ProfileFollowEdge.counterpart_username_normalized.in_(
                    selected_normalized
                ),
            )
            .group_by(ProfileFollowEdge.counterpart_username_normalized)
            .all()
        )
    }

    # Recognition fields come from any active edge row naming the counterpart.
    annotations = {
        normalized: (display_name, avatar_url, linked_profile_id)
        for normalized, display_name, avatar_url, linked_profile_id in (
            db.query(
                ProfileFollowEdge.counterpart_username_normalized,
                func.max(ProfileFollowEdge.counterpart_display_name),
                func.max(ProfileFollowEdge.counterpart_avatar_url),
                func.max(ProfileFollowEdge.counterpart_profile_id),
            )
            .filter(
                ProfileFollowEdge.removed_at.is_(None),
                ProfileFollowEdge.profile_id.in_(scoped_ids),
                ProfileFollowEdge.counterpart_username_normalized.in_(
                    selected_normalized
                ),
            )
            .group_by(ProfileFollowEdge.counterpart_username_normalized)
            .all()
        )
    }
    imported_flags = _imported_profile_flags(
        db,
        (linked_profile_id for _, _, linked_profile_id in annotations.values()),
    )

    suggestions = []
    for row in aggregate_rows:
        display_name, avatar_url, linked_profile_id = annotations.get(
            row.normalized, (None, None, None)
        )
        suggestions.append(
            {
                "username": row.username,
                "display_name": display_name,
                "avatar_url": avatar_url,
                "followed_by": sorted(followed_by[row.normalized], key=str.casefold),
                "followed_by_count": row.followed_by_count,
                "follows_back_count": follows_back_counts.get(row.normalized, 0),
                "already_imported": imported_flags.get(linked_profile_id, False),
                "profile_id": linked_profile_id,
            }
        )
    # The counts above are taken across every monitored profile, not across a
    # tab's current selection. Without saying so, a caller that supplied its
    # own denominator rendered "10 of 6".
    return {"suggestions": suggestions, "monitored_profiles": len(scoped_ids)}
