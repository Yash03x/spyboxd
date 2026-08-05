"""Where the data came from, and what is missing.

This is the section every other panel's caveat eventually points at. Its job is
to make "why is this empty" answerable without reading the code, so each
function reports what was read, when, by what, and what it could not reach.

Nothing here guesses. A surface that was never read is null, not zero; a
profile Letterboxd reports as larger than our copy is a stated gap rather than
a silently truncated total.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from services.import_contracts import IMPORTER_VERSION

# The incremental RSS top-up. It is not a read of a profile: it layers the last
# few activity items onto an authoritative full snapshot, writes non-
# authoritative dataset rows carrying only those items, and stamps its own
# importer version. Because it runs on a feed schedule it is almost always the
# newest sync a profile has, so any panel that means "the last authoritative
# read" must exclude it or it reports the top-up's shape as the library's.
INCREMENTAL_SOURCE_KIND = "rss_incremental"

# Sort floor for runs with no usable timestamp, so ranking never compares a
# datetime against None.
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

from database.models import (
    LostEntry,
    MemberComment,
    MemberContentLike,
    MovieList,
    MovieListItem,
    Profile,
    ProfileFeedState,
    ProfileFilm,
    ProfileFollowEdge,
    ProfileSync,
    Review,
    SyncDataset,
    WatchEvent,
    WatchlistItem,
)


# The dataset names an importer writes, in the order a reader cares about them.
SURFACE_ORDER = [
    ("films", "Diary"),
    ("ratings", "Ratings"),
    ("watchlist", "Watchlist"),
    ("lists", "Lists"),
    # The importer writes "following" and "followers"; it has never written a
    # dataset called "follows". That row could therefore only ever report
    # "never read", which the follow graph in People flatly contradicted.
    ("following", "Following"),
    ("followers", "Followers"),
    ("reviews", "Reviews"),
    ("likes", "Likes · comments"),
    ("comments", "Comments"),
]


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    """Treat a naive timestamp as UTC — see the note in services/tonight.py."""

    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _latest_syncs(
    db: Session, profile_ids: Sequence[int], *, full_only: bool = False
) -> Dict[int, ProfileSync]:
    """The most recent completed sync per profile.

    ``full_only`` excludes the incremental RSS top-ups. They run every few
    minutes and complete in under a second, so for any feed-watched profile the
    newest sync of *any* kind is always one of them — which is the wrong answer
    to every question of the form "when was this profile actually read, and by
    what". See INCREMENTAL_SOURCE_KIND.
    """

    if not profile_ids:
        return {}
    query = db.query(ProfileSync).filter(
        ProfileSync.profile_id.in_(profile_ids), ProfileSync.status == "completed"
    )
    if full_only:
        query = query.filter(ProfileSync.source_kind != INCREMENTAL_SOURCE_KIND)
    syncs = query.order_by(ProfileSync.profile_id, ProfileSync.started_at.desc()).all()
    latest: Dict[int, ProfileSync] = {}
    for sync in syncs:
        latest.setdefault(sync.profile_id, sync)
    return latest


def build_ledger(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """Per-surface refresh ledger: what was read, when, and what came back.

    This was buried in admin, and it is the honest answer to "why is this panel
    empty" for most of the product.
    """

    profile_ids = [profile.id for profile in profiles]

    # Per profile *and surface*, not per profile. Scoped to the single latest
    # sync, a surface an older run had read and a newer one did not touch was
    # reported as "never read for any selected profile" — which the working
    # follow graph in People flatly contradicted. Each surface now reports the
    # most recent run that actually carried it.
    rows: List[Dict[str, Any]] = []
    if profile_ids:
        datasets = (
            db.query(SyncDataset, ProfileSync)
            .join(ProfileSync, ProfileSync.id == SyncDataset.profile_sync_id)
            .filter(
                ProfileSync.profile_id.in_(profile_ids),
                ProfileSync.status == "completed",
            )
            .all()
        )
        # Per (surface, profile): the newest AUTHORITATIVE run wins, and an
        # incremental top-up is used only where no authoritative run exists.
        # Ranking purely by recency let the RSS top-up — which carries a
        # handful of recent items and is authoritative for nothing — stand in
        # for the full snapshot underneath it, so the five surfaces RSS touches
        # reported the group's whole diary as a few hundred rows and "none
        # authoritative", while the four it does not touch reported the truth.
        newest: Dict[tuple, Any] = {}
        for dataset, sync in datasets:
            key = (dataset.dataset_name, sync.profile_id)
            when = _aware(sync.completed_at or sync.started_at)
            rank = (bool(dataset.is_authoritative), when or _EPOCH)
            current = newest.get(key)
            if current is None or rank > current[3]:
                newest[key] = (dataset, sync, when, rank)

        by_surface: Dict[str, List[Any]] = defaultdict(list)
        for (name, _profile_id), (dataset, sync, _when, _rank) in newest.items():
            by_surface[name].append((dataset, sync))

        for name, label in SURFACE_ORDER:
            entries = by_surface.get(name, [])
            if not entries:
                rows.append(
                    {
                        "surface": label,
                        "dataset": name,
                        "profiles_covered": 0,
                        "profiles_selected": len(profiles),
                        "rows": 0,
                        "authoritative_profiles": 0,
                        "last_run": None,
                        "result": "Never read for any selected profile",
                    }
                )
                continue

            imported = sum(dataset.imported_row_count for dataset, _ in entries)
            authoritative = sum(1 for dataset, _ in entries if dataset.is_authoritative)
            last_run = max(
                (
                    when
                    for when in (_aware(sync.completed_at or sync.started_at) for _, sync in entries)
                    if when is not None
                ),
                default=None,
            )
            rows.append(
                {
                    "surface": label,
                    "dataset": name,
                    "profiles_covered": len(entries),
                    "profiles_selected": len(profiles),
                    "rows": imported,
                    "authoritative_profiles": authoritative,
                    "last_run": last_run.isoformat() if last_run else None,
                    "result": (
                        f"Complete for {authoritative} of {len(profiles)}"
                        if authoritative
                        else f"Read for {len(entries)} of {len(profiles)}, none authoritative"
                    ),
                }
            )

    return {
        "surfaces": rows,
        "caveat": (
            "Each surface reports its most recent authoritative read, falling back to an "
            "incremental top-up only where no full read exists — a top-up carries the last few "
            "items and does not replace the snapshot beneath it, and a refresh that skips a "
            "surface does not unread it. A surface with no row was never read for anybody in "
            "this selection, which is different from being read and coming back empty, and the "
            "two must not look alike."
        ),
    }


def build_feeds(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """Feed health and backoff.

    When a feed refuses us we slow down rather than retry harder. The wait is
    published because it explains a stale panel better than a spinner does.
    """

    profile_ids = [profile.id for profile in profiles]
    names = {profile.id: profile.username for profile in profiles}
    states = (
        db.query(ProfileFeedState).filter(ProfileFeedState.profile_id.in_(profile_ids)).all()
        if profile_ids
        else []
    )

    entries = []
    for state in states:
        if state.consecutive_failures:
            why = (
                f"{state.consecutive_failures} consecutive failure"
                f"{'s' if state.consecutive_failures != 1 else ''} — backing off"
            )
            if state.last_http_status:
                why += f" after HTTP {state.last_http_status}"
            tone = "bad"
        elif state.requires_full_sync:
            why = state.reconciliation_reason or "The feed disagreed with our snapshot — a full refresh is queued"
            tone = "warn"
        else:
            why = "Nothing wrong — normal schedule"
            tone = "ok"

        entries.append(
            {
                "username": names.get(state.profile_id, "?"),
                "next_poll_at": state.next_poll_at.isoformat() if state.next_poll_at else None,
                "last_success_at": state.last_success_at.isoformat() if state.last_success_at else None,
                "consecutive_failures": state.consecutive_failures,
                "last_http_status": state.last_http_status,
                "requires_full_sync": bool(state.requires_full_sync),
                "why": why,
                "tone": tone,
            }
        )

    entries.sort(key=lambda item: (-item["consecutive_failures"], item["username"]))
    unwatched = [profile.username for profile in profiles if profile.id not in {state.profile_id for state in states}]

    return {
        "feeds": entries,
        "without_feed": unwatched,
        "caveat": (
            f"{len(entries)} of {len(profiles)} selected profiles have an incremental feed. "
            "The rest are refreshed on demand only, so they have no backoff state rather than a "
            "healthy one."
        ),
    }


def build_importers(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """Profiles last read by an importer older than the current one.

    A full refresh fixes it. Until then the fields that importer never
    collected are marked rather than faked.
    """

    # Full reads only. The RSS top-up carries its own importer version, and
    # since it is always the newest sync a feed-watched profile has, reading
    # the newest row of any kind flagged every healthy profile in the product
    # as "read by an older importer" while its real full sync was current.
    latest = _latest_syncs(db, [profile.id for profile in profiles], full_only=True)
    # The importer that ships with this deployment, not the newest version seen
    # in the selection: derived from the selection's own syncs, a set of
    # profiles ALL last read by an old importer reported itself "Up to date".
    current = IMPORTER_VERSION

    entries = []
    for profile in profiles:
        sync = latest.get(profile.id)
        if sync is None:
            entries.append(
                {
                    "username": profile.username,
                    "importer_version": None,
                    "is_current": False,
                    "missing": "Never completed a full read, so nothing has been collected at all",
                }
            )
            continue
        is_current = sync.importer_version == current
        entries.append(
            {
                "username": profile.username,
                "importer_version": sync.importer_version,
                "is_current": is_current,
                "missing": (
                    "Up to date"
                    if is_current
                    else "Read by an older importer — fields it never collected are marked, not faked"
                ),
            }
        )

    entries.sort(key=lambda item: (item["is_current"], item["username"]))

    return {
        "profiles": entries,
        "current_version": current,
        "caveat": (
            f"Current importer: {current or 'unknown'}. A profile read by an older one is not "
            "wrong, it is thinner — and the panels that depend on what it skipped say so rather "
            "than showing a zero."
        ),
    }


def build_counts(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """Letterboxd's own stated total against ours.

    Where ours is lower we say so. That difference is the single most honest
    number in the product.
    """

    entries = []
    for profile in profiles:
        ours = (
            db.query(func.count(ProfileFilm.id))
            .filter(ProfileFilm.profile_id == profile.id, ProfileFilm.removed_at.is_(None))
            .scalar()
            or 0
        )
        theirs = profile.reported_total_films
        entries.append(
            {
                "username": profile.username,
                "theirs": theirs,
                "ours": ours,
                "gap": (theirs - ours) if theirs is not None else None,
            }
        )

    entries.sort(key=lambda item: (item["gap"] is None, -(item["gap"] or 0)))
    measured = [entry for entry in entries if entry["gap"] is not None]
    total_gap = sum(max(entry["gap"] or 0, 0) for entry in measured)

    return {
        "profiles": entries,
        "total_gap": total_gap,
        "caveat": (
            f"{total_gap:,} film{'' if total_gap == 1 else 's'} across the selection that Letterboxd reports and we do not hold. "
            "Mostly private diary entries and pages that stopped answering mid-read. A profile "
            "whose header was never fetched has no stated total, which is not a gap of zero."
            if measured
            else "No profile in this selection has a stated total to compare against yet."
        ),
    }


def build_private(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """Surfaces we can tell exist without being able to read them.

    Saying so is better than an empty panel that looks like nothing happened.
    """

    entries = []
    for profile in profiles:
        hidden: List[str] = []

        watchlist_rows = (
            db.query(func.count(WatchlistItem.id))
            .filter(WatchlistItem.profile_id == profile.id, WatchlistItem.removed_at.is_(None))
            .scalar()
            or 0
        )
        if profile.reported_watchlist_count and not watchlist_rows:
            hidden.append(
                f"Watchlist is private — Letterboxd reports {profile.reported_watchlist_count:,} entries we cannot read"
            )

        list_rows = (
            db.query(func.count(MovieList.id))
            .filter(MovieList.profile_id == profile.id)
            .scalar()
            or 0
        )
        if profile.reported_total_lists and list_rows < profile.reported_total_lists:
            hidden.append(
                f"{profile.reported_total_lists - list_rows} of {profile.reported_total_lists} lists are not public"
            )

        review_rows = (
            db.query(func.count(Review.id))
            .filter(Review.profile_id == profile.id, Review.removed_at.is_(None))
            .scalar()
            or 0
        )
        if profile.reported_total_reviews and review_rows < profile.reported_total_reviews:
            hidden.append(
                f"{profile.reported_total_reviews - review_rows} of {profile.reported_total_reviews} reviews are not readable"
            )

        if hidden:
            entries.append({"username": profile.username, "hidden": hidden})

    return {
        "profiles": entries,
        "caveat": (
            "Inferred by comparing Letterboxd's own stated totals against what we hold. A surface "
            "with no stated total cannot be checked this way at all, so an absence here is not a "
            "guarantee that everything is public."
        ),
    }


def build_removed(db: Session, profiles: Sequence[Profile], *, limit: int = 20) -> Dict[str, Any]:
    """Rows that were there last time and are not now.

    Was "soft-removed". Nothing is deleted: it is marked with the date we
    noticed and moves here, then to Lost & found.
    """

    profile_ids = [profile.id for profile in profiles]
    names = {profile.id: profile.username for profile in profiles}
    entries: List[Dict[str, Any]] = []

    if profile_ids:
        for model, kind in (
            (ProfileFilm, "film"),
            (WatchlistItem, "watchlist"),
            (Review, "review"),
            (MovieListItem, "list item"),
            (ProfileFollowEdge, "follow"),
            (MemberContentLike, "like"),
            (MemberComment, "comment"),
        ):
            if not hasattr(model, "removed_at"):
                continue
            profile_column = getattr(model, "profile_id", None)
            if profile_column is None:
                continue
            rows = (
                db.query(profile_column, func.count(model.id), func.max(model.removed_at))
                .filter(profile_column.in_(profile_ids), model.removed_at.isnot(None))
                .group_by(profile_column)
                .all()
            )
            for profile_id, count, last_seen in rows:
                entries.append(
                    {
                        "username": names.get(profile_id, "?"),
                        "kind": kind,
                        "rows": count,
                        "noticed_at": last_seen.isoformat() if last_seen else None,
                    }
                )

    entries.sort(key=lambda item: (item["noticed_at"] or "", item["rows"]), reverse=True)

    return {
        "removed": entries[:limit],
        "count": len(entries),
        "caveat": (
            "A row that stops appearing is marked with the date we noticed, never deleted. Two "
            "authoritative reads are needed before anything can appear here at all — a first "
            "import has nothing to compare against."
        ),
    }


def build_request_latency(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """How long a completed sync actually takes, measured rather than promised."""

    profile_ids = [profile.id for profile in profiles]
    if not profile_ids:
        return {"runs": 0, "median_seconds": None, "worst_seconds": None, "caveat": "No profiles selected."}

    # Full reads only. An RSS top-up finishes in well under a second, and it
    # runs on a feed schedule, so the last 30 syncs of any kind are all
    # top-ups: the panel measured them and answered "a request takes 0s"
    # beside a request queue whose real answer is minutes.
    syncs = (
        db.query(ProfileSync.started_at, ProfileSync.completed_at)
        .filter(
            ProfileSync.profile_id.in_(profile_ids),
            ProfileSync.status == "completed",
            ProfileSync.completed_at.isnot(None),
            ProfileSync.source_kind != INCREMENTAL_SOURCE_KIND,
        )
        .order_by(ProfileSync.started_at.desc())
        .limit(30)
        .all()
    )

    durations = sorted(
        (completed - started).total_seconds()
        for started, completed in syncs
        if completed and started and completed >= started
    )

    if not durations:
        return {
            "runs": 0,
            "median_seconds": None,
            "worst_seconds": None,
            "caveat": (
                "No completed full read in this selection carries both a start and an end time, "
                "so there is nothing to measure. An estimate would be a promise rather than a "
                "figure."
            ),
        }

    median = durations[len(durations) // 2]
    return {
        "runs": len(durations),
        "median_seconds": round(median),
        "worst_seconds": round(durations[-1]),
        "caveat": (
            f"Median of the last {len(durations)} completed full reads, so the estimate is "
            "measured rather than promised. Incremental feed top-ups are excluded: they finish "
            "in under a second and answer a different question. A large diary dominates the "
            "worst case — a big profile read at a rate that does not trip the feed."
        ),
    }


def build_lost_and_found(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """Deleted history we still hold, from official exports only."""

    profile_ids = [profile.id for profile in profiles]
    names = {profile.id: profile.username for profile in profiles}

    rows = (
        db.query(
            LostEntry.profile_id,
            LostEntry.entry_type,
            LostEntry.lost_kind,
            func.count(LostEntry.id),
            func.min(LostEntry.entry_date),
        )
        .filter(LostEntry.profile_id.in_(profile_ids))
        .group_by(LostEntry.profile_id, LostEntry.entry_type, LostEntry.lost_kind)
        .all()
        if profile_ids
        else []
    )

    grouped: Dict[str, Dict[str, Any]] = {}
    for profile_id, entry_type, lost_kind, count, oldest in rows:
        entry = grouped.setdefault(
            f"{entry_type}:{lost_kind}",
            {"entry_type": entry_type, "lost_kind": lost_kind, "rows": 0, "oldest": None, "profiles": []},
        )
        entry["rows"] += count
        entry["profiles"].append(names.get(profile_id, "?"))
        if oldest and (entry["oldest"] is None or oldest.isoformat() < entry["oldest"]):
            entry["oldest"] = oldest.isoformat()

    entries = sorted(grouped.values(), key=lambda item: -item["rows"])
    with_exports = sorted({names.get(profile_id, "?") for profile_id, *_ in rows})

    return {
        "entries": entries,
        "profiles_with_exports": with_exports,
        "profiles_selected": len(profiles),
        "caveat": (
            f"Held for {len(with_exports)} of {len(profiles)} selected profiles. This is the only "
            "part of the product that can show somebody their own deleted past, and it exists "
            "solely because they handed over an export."
        ),
    }


def build_lost_list_films(db: Session, profiles: Sequence[Profile], *, limit: int = 12) -> Dict[str, Any]:
    """Films from lists that no longer exist.

    A list was deleted, but we still hold what was in it — often the most
    considered version of somebody's taste, thrown away in a tidy-up.
    """

    profile_ids = [profile.id for profile in profiles]
    if not profile_ids:
        return {"films": [], "count": 0, "caveat": "No profiles selected."}

    rows = (
        db.query(MovieListItem, MovieList, Profile.username)
        .join(MovieList, MovieList.id == MovieListItem.movie_list_id)
        .join(Profile, Profile.id == MovieList.profile_id)
        .filter(MovieList.profile_id.in_(profile_ids), MovieList.removed_at.isnot(None))
        .order_by(MovieList.removed_at.desc(), MovieListItem.position)
        .all()
    )

    films = []
    for item, movie_list, username in rows:
        films.append(
            {
                "title": item.movie.title if item.movie else "Unknown film",
                "year": item.movie.release_year if item.movie else None,
                "poster_url": item.movie.poster_url if item.movie else None,
                "list_name": movie_list.name,
                "username": username,
                "position": item.position,
                "removed_at": movie_list.removed_at.isoformat() if movie_list.removed_at else None,
            }
        )

    return {
        "films": films[:limit],
        "count": len(films),
        "caveat": (
            f"{len(films)} films held from lists that have since disappeared. The list is gone "
            "from Letterboxd; the ordering it carried is not, because nothing here is deleted."
            if films
            else "No list in this selection has disappeared between two reads. Nothing to recover."
        ),
    }


def build_removed_summary(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """Small helper used by the Overview strip: how much has gone missing."""

    detail = build_removed(db, profiles, limit=5)
    return {"count": detail["count"], "recent": detail["removed"], "caveat": detail["caveat"]}


def build_watch_event_freshness(db: Session, profiles: Sequence[Profile]) -> Dict[str, Any]:
    """When each profile was last read, and how much came back."""

    now = datetime.now(timezone.utc)
    latest = _latest_syncs(db, [profile.id for profile in profiles])

    entries = []
    for profile in profiles:
        sync = latest.get(profile.id)
        when: Optional[datetime] = _aware(
            sync.completed_at if sync else profile.last_scraped_at
        )
        events = (
            db.query(func.count(WatchEvent.id))
            .filter(WatchEvent.profile_id == profile.id, WatchEvent.superseded_at.is_(None))
            .scalar()
            or 0
        )
        entries.append(
            {
                "username": profile.username,
                "last_read_at": when.isoformat() if when else None,
                "hours_ago": round((now - when).total_seconds() / 3600, 1) if when else None,
                "watch_events": events,
                # Letterboxd's own header figure, and null when the header has
                # never been read. The panel used to source this from the
                # tracked-profile list instead, which does not cover every
                # profile on screen, so a profile missing from that list
                # rendered a confident "0" beside its 299 watches.
                "films_held": profile.reported_total_films,
            }
        )

    entries.sort(key=lambda item: (item["hours_ago"] is None, item["hours_ago"] or 0))
    unread = sum(1 for entry in entries if entry["films_held"] is None)
    return {
        "profiles": entries,
        "caveat": (
            "Read time comes from the latest completed sync, falling back to the profile's own "
            "last-scraped stamp. A profile with neither has never been read at all."
            + (
                f" {unread} of these carry no film total: that figure comes from the profile "
                "header, and a header nobody has read holds no number rather than a zero."
                if unread
                else ""
            )
        ),
    }
