import math
from collections import defaultdict
from itertools import combinations
from sqlalchemy.orm import Session
from sqlalchemy import and_, case, desc, extract, false, func, or_
from .models import (
    AppUser,
    Movie,
    MovieList,
    MovieListItem,
    Profile,
    ProfileDataChange,
    ProfileFavoriteMovie,
    ProfileFeedState,
    ProfileFilm,
    ProfileSourceActivity,
    ProfileSync,
    Rating,
    Review,
    SyncDataset,
    SystemMetrics,
    WatchEvent,
    WatchlistItem,
)
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Tuple


def _format_month_bucket(year: int, month: int) -> str:
    return f"{int(year):04d}-{int(month):02d}"



# Films two profiles must both have rated before their rating correlation is
# trusted at full weight. Below it the correlation is pulled toward the
# no-correlation midpoint: a perfect 1.0 from two shared ratings says nothing,
# because any two points lie on a line.
CORRELATION_PRIOR_FILMS = 8

RATING_MIN = 0.0
RATING_MAX = 5.0
DASHBOARD_SNAPSHOT_FORMAT_VERSION = 3
DASHBOARD_ACTIVITY_MONTHS = 12


def _shift_month_start(month_start: date, offset: int) -> date:
    """Move a first-of-month date by ``offset`` calendar months."""
    month_index = month_start.year * 12 + month_start.month - 1 + offset
    year, zero_based_month = divmod(month_index, 12)
    return date(year, zero_based_month + 1, 1)


def _coerce_utc_now(value: Optional[datetime] = None) -> datetime:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _dashboard_snapshot_meta(as_of: date) -> Dict[str, Any]:
    current_month_start = as_of.replace(day=1)
    return {
        "format_version": DASHBOARD_SNAPSHOT_FORMAT_VERSION,
        "activity_window_start": _shift_month_start(
            current_month_start,
            -(DASHBOARD_ACTIVITY_MONTHS - 1),
        ).isoformat(),
        "activity_as_of": as_of.isoformat(),
    }


def _coerce_finite_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _safe_round(value: Any, digits: int = 2) -> Optional[float]:
    numeric = _coerce_finite_float(value)
    if numeric is None:
        return None
    return round(numeric, digits)


def _naive_utc(timestamp: Optional[datetime]) -> Optional[datetime]:
    if timestamp is None:
        return None
    if timestamp.tzinfo is not None:
        return timestamp.astimezone(timezone.utc).replace(tzinfo=None)
    return timestamp


def _movie_identity_key(
    movie_title: Optional[str],
    movie_year: Optional[int],
    film_slug: Optional[str],
    letterboxd_id: Optional[str],
) -> str:
    normalized_title = " ".join((movie_title or "").strip().lower().split())
    if normalized_title:
        return f"title:{normalized_title}|year:{movie_year if movie_year is not None else 'na'}"
    if film_slug:
        return f"slug:{film_slug}"
    if letterboxd_id:
        return f"id:{letterboxd_id}"
    return "unknown-movie"


def _average(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _population_stddev(values: List[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def _pearson_correlation(left: List[float], right: List[float]) -> Optional[float]:
    if len(left) != len(right) or len(left) < 2:
        return None

    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    covariance = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right)
    )
    left_variance = sum((value - left_mean) ** 2 for value in left)
    right_variance = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_variance * right_variance)
    if not denominator:
        return None
    return covariance / denominator


def _build_movie_summary(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    ratings = [entry["rating"] for entry in entries if entry["rating"] is not None]
    average_rating = _average(ratings)
    rating_stddev = _population_stddev(ratings)
    max_rating_gap = None
    if len(ratings) >= 2:
        max_rating_gap = max(ratings) - min(ratings)

    return {
        "title": entries[0]["movie_title"],
        "year": entries[0]["movie_year"],
        "profile_count": len(entries),
        "profiles": sorted(entry["username"] for entry in entries),
        "rating_count": len(ratings),
        "average_rating": _safe_round(average_rating, 2),
        "rating_stddev": _safe_round(rating_stddev, 2),
        "max_rating_gap": _safe_round(max_rating_gap, 2),
        "liked_count": sum(1 for entry in entries if entry.get("is_liked")),
        "rewatch_count": sum(1 for entry in entries if entry.get("is_rewatch")),
    }


def _build_watch_event(entries: List[Dict[str, Any]], start_date, end_date, pair_count: int) -> Dict[str, Any]:
    ratings = [entry["rating"] for entry in entries if entry["rating"] is not None]
    average_rating = _average(ratings)
    max_rating_gap = None
    if len(ratings) >= 2:
        max_rating_gap = max(ratings) - min(ratings)

    participants = sorted(
        [
            {
                "username": entry["username"],
                "rating": _safe_round(entry["rating"], 2),
                "watched_date": entry["watched_date"].isoformat() if entry["watched_date"] else None,
                "is_rewatch": bool(entry["is_rewatch"]),
            }
            for entry in entries
        ],
        key=lambda participant: (
            participant["watched_date"] or "",
            participant["username"],
        ),
    )

    return {
        "title": entries[0]["movie_title"],
        "year": entries[0]["movie_year"],
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "profile_count": len(entries),
        "pair_count": pair_count,
        "profiles": sorted(entry["username"] for entry in entries),
        "participants": participants,
        "average_rating": _safe_round(average_rating, 2),
        "max_rating_gap": _safe_round(max_rating_gap, 2),
        "rewatch_count": sum(1 for entry in entries if entry.get("is_rewatch")),
    }


def _timing_profile_key(entry: Dict[str, Any]) -> str:
    profile_id = entry.get("profile_id")
    if profile_id is not None:
        return f"id:{profile_id}"
    return f"username:{str(entry.get('username') or '').casefold()}"


def _timing_movie_key(entry: Dict[str, Any]) -> str:
    """Prefer the normalized movie identity without changing legacy grouping."""
    movie_id = entry.get("movie_id")
    if movie_id is not None:
        return f"movie:{movie_id}"
    letterboxd_id = entry.get("letterboxd_id")
    if letterboxd_id:
        return f"id:{letterboxd_id}"
    film_slug = entry.get("film_slug")
    if film_slug:
        return f"slug:{film_slug}"
    return _movie_identity_key(
        movie_title=entry.get("movie_title"),
        movie_year=entry.get("movie_year"),
        film_slug=None,
        letterboxd_id=None,
    )


def _coalesce_timing_participants(
    entries: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Collapse repeat events to one participant without losing rewatch evidence."""
    by_profile: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        key = _timing_profile_key(entry)
        current = by_profile.get(key)
        if current is None:
            by_profile[key] = dict(entry)
            continue
        current["is_rewatch"] = bool(current.get("is_rewatch")) or bool(
            entry.get("is_rewatch")
        )
        current["is_liked"] = bool(current.get("is_liked")) or bool(
            entry.get("is_liked")
        )
        if current.get("rating") is None and entry.get("rating") is not None:
            current["rating"] = entry["rating"]
        current_date = current.get("watched_date")
        candidate_date = entry.get("watched_date")
        if candidate_date is not None and (
            current_date is None or candidate_date < current_date
        ):
            current["watched_date"] = candidate_date
    return sorted(
        by_profile.values(),
        key=lambda entry: (
            entry.get("watched_date") or datetime.min.date(),
            str(entry.get("username") or "").casefold(),
        ),
    )


def _build_event_source_watch_event(
    entries: List[Dict[str, Any]],
    start_date,
    end_date,
    pair_count: int,
) -> Dict[str, Any]:
    participants = _coalesce_timing_participants(entries)
    ratings = [entry["rating"] for entry in participants if entry.get("rating") is not None]
    return {
        "title": entries[0]["movie_title"],
        "year": entries[0]["movie_year"],
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "profile_count": len(participants),
        "pair_count": pair_count,
        "profiles": sorted(entry["username"] for entry in participants),
        "participants": [
            {
                "username": entry["username"],
                "rating": _safe_round(entry.get("rating"), 2),
                "watched_date": (
                    entry["watched_date"].isoformat()
                    if entry.get("watched_date")
                    else None
                ),
                "is_rewatch": bool(entry.get("is_rewatch")),
            }
            for entry in participants
        ],
        "average_rating": _safe_round(_average(ratings), 2),
        "max_rating_gap": (
            _safe_round(max(ratings) - min(ratings), 2)
            if len(ratings) >= 2
            else None
        ),
        "rewatch_count": sum(bool(entry.get("is_rewatch")) for entry in participants),
    }


def _calculate_event_source_timing(
    entries: List[Dict[str, Any]],
    *,
    gap_days: Optional[int],
) -> Dict[str, Any]:
    """Calculate timing-only signals from occurrence-level watch entries."""
    movies_by_key: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    profiles_with_dates = set()
    for entry in entries:
        watched_date = entry.get("watched_date")
        if watched_date is None:
            continue
        profiles_with_dates.add(entry["username"])
        movies_by_key[_timing_movie_key(entry)].append(entry)

    pair_metrics: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(
        lambda: {
            "same_day_count": 0,
            "one_day_gap_count": 0,
            "tight_window_count": 0,
            "within_gap_count": 0,
            "movie_keys": set(),
            "sample_titles": [],
        }
    )
    follow_paths: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "sample_titles": []}
    )
    same_day_events: List[Dict[str, Any]] = []
    one_day_gap_events: List[Dict[str, Any]] = []
    gap_events: List[Dict[str, Any]] = []

    def add_sample(metrics: Dict[str, Any], entry: Dict[str, Any]) -> None:
        sample = {"title": entry["movie_title"], "year": entry["movie_year"]}
        if sample not in metrics["sample_titles"] and len(metrics["sample_titles"]) < 3:
            metrics["sample_titles"].append(sample)

    for movie_key, movie_entries in movies_by_key.items():
        by_date: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
        for entry in movie_entries:
            by_date[entry["watched_date"]].append(entry)
        participants_by_date = {
            watched_date: _coalesce_timing_participants(raw_bucket)
            for watched_date, raw_bucket in by_date.items()
        }

        for watched_date, raw_bucket in by_date.items():
            bucket = participants_by_date[watched_date]
            if len(bucket) < 2:
                continue
            profile_pairs = list(combinations(bucket, 2))
            watch_event = _build_event_source_watch_event(
                raw_bucket,
                watched_date,
                watched_date,
                len(profile_pairs),
            )
            same_day_events.append(watch_event)
            if gap_days is not None:
                gap_events.append({**watch_event, "day_gap": 0})

        dates = sorted(by_date)
        max_window = max(gap_days or 0, 1)
        for start_index, start_date in enumerate(dates):
            for end_date in dates[start_index + 1 :]:
                day_gap = (end_date - start_date).days
                if day_gap > max_window:
                    break

                start_bucket = participants_by_date[start_date]
                end_bucket = participants_by_date[end_date]
                cross_pairs: Dict[Tuple[str, str], Tuple[Dict[str, Any], Dict[str, Any]]] = {}
                for left in start_bucket:
                    for right in end_bucket:
                        if _timing_profile_key(left) == _timing_profile_key(right):
                            continue
                        pair_key = tuple(sorted((left["username"], right["username"])))
                        cross_pairs.setdefault(pair_key, (left, right))
                if not cross_pairs:
                    continue

                watch_event = _build_event_source_watch_event(
                    [*by_date[start_date], *by_date[end_date]],
                    start_date,
                    end_date,
                    len(cross_pairs),
                )
                if day_gap == 1:
                    one_day_gap_events.append(watch_event)
                if gap_days is not None and day_gap <= gap_days:
                    gap_events.append({**watch_event, "day_gap": day_gap})

        # Repeated watches may produce multiple useful feed events, but a
        # profile pair contributes to alignment at most once per movie. Use the
        # closest occurrence pair so prolific rewatchers cannot dominate.
        by_profile: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for bucket in participants_by_date.values():
            for entry in bucket:
                by_profile[_timing_profile_key(entry)].append(entry)

        profile_event_groups = sorted(
            by_profile.values(),
            key=lambda group: str(group[0].get("username") or "").casefold(),
        )
        for left_events, right_events in combinations(profile_event_groups, 2):
            left_username = left_events[0]["username"]
            right_username = right_events[0]["username"]
            pair_key = tuple(sorted((left_username, right_username)))
            date_deltas = [
                (right["watched_date"] - left["watched_date"]).days
                for left in left_events
                for right in right_events
            ]
            minimum_gap = min(abs(delta) for delta in date_deltas)

            metrics = pair_metrics[pair_key]
            metrics["movie_keys"].add(movie_key)
            add_sample(metrics, movie_entries[0])
            if minimum_gap == 0:
                metrics["same_day_count"] += 1
            elif minimum_gap == 1:
                metrics["one_day_gap_count"] += 1
            if minimum_gap <= 1:
                metrics["tight_window_count"] += 1
            if gap_days is not None and minimum_gap <= gap_days:
                metrics["within_gap_count"] += 1

            if minimum_gap != 1:
                continue
            closest_directions = {
                (left_username, right_username)
                if delta > 0
                else (right_username, left_username)
                for delta in date_deltas
                if abs(delta) == minimum_gap
            }
            if len(closest_directions) != 1:
                # Equally close observations in opposite directions are
                # ambiguous and should not invent a leader/follower path.
                continue
            leader, follower = next(iter(closest_directions))
            path = follow_paths[(leader, follower)]
            path["count"] += 1
            add_sample(path, movie_entries[0])

    # These three lists are the Signal Feed, and the feed is presented newest
    # first. They are truncated to `limit` further down, so whatever leads this
    # sort decides which events survive -- and leading with crowd size meant the
    # 100 kept rows were the biggest gatherings, not the latest ones. At a
    # three-day gap that dropped every match from the most recent week while the
    # header still said "most recent first". Recency leads; crowd size stays as
    # the tiebreaker so a busy day still ranks its own events sensibly.
    feed_order = lambda event: (
        -int(event["start_date"].replace("-", "")),
        -event["profile_count"],
        -event["pair_count"],
        event["title"],
    )
    same_day_events.sort(key=feed_order)
    one_day_gap_events.sort(key=feed_order)
    if gap_days is not None:
        gap_events.sort(
            key=lambda event: (
                -int(event["start_date"].replace("-", "")),
                -event["profile_count"],
                event["day_gap"],
                -event["pair_count"],
                event["title"],
            )
        )

    return {
        "profiles_with_dates": profiles_with_dates,
        "same_day_events": same_day_events,
        "one_day_gap_events": one_day_gap_events,
        "gap_events": gap_events,
        "pair_metrics": pair_metrics,
        "follow_paths": follow_paths,
    }


def _merge_event_source_timing(
    baseline: Dict[str, Any],
    timing: Dict[str, Any],
    *,
    limit: int,
    gap_days: Optional[int],
) -> Dict[str, Any]:
    """Replace only timing fields while preserving legacy rating/title analysis."""
    aligned_by_pair = {
        tuple(pair["profiles"]): pair
        for pair in baseline.get("aligned_pairs", [])
    }
    timing_metrics: Dict[Tuple[str, str], Dict[str, Any]] = timing["pair_metrics"]
    for pair_key in set(aligned_by_pair) | set(timing_metrics):
        metrics = timing_metrics.get(pair_key, {})
        pair = aligned_by_pair.get(pair_key)
        is_existing_pair = pair is not None
        if pair is None:
            pair = {
                "profiles": list(pair_key),
                "shared_titles": len(metrics.get("movie_keys", set())),
                "rating_overlap_count": 0,
                "rating_correlation": None,
                "average_rating_gap": None,
                "sample_titles": list(metrics.get("sample_titles", [])),
            }
            aligned_by_pair[pair_key] = pair

        old_timing = (
            pair.get("same_day_count", 0),
            pair.get("one_day_gap_count", 0),
            pair.get("tight_window_count", 0),
            pair.get("within_gap_count", 0),
        )
        pair["same_day_count"] = int(metrics.get("same_day_count", 0))
        pair["one_day_gap_count"] = int(metrics.get("one_day_gap_count", 0))
        pair["tight_window_count"] = int(metrics.get("tight_window_count", 0))
        if gap_days is not None:
            pair["within_gap_count"] = int(metrics.get("within_gap_count", 0))
        else:
            pair.pop("within_gap_count", None)
        new_timing = (
            pair["same_day_count"],
            pair["one_day_gap_count"],
            pair["tight_window_count"],
            pair.get("within_gap_count", 0),
        )

        # Preserve the exact legacy score when timing is unchanged. When
        # occurrence-level events change it, recompute from the same public
        # components without altering response shape.
        if not is_existing_pair or old_timing != new_timing:
            correlation = _coerce_finite_float(pair.get("rating_correlation"))
            overlap_count = int(pair.get("rating_overlap_count") or 0)
            if correlation is not None:
                correlation_component = (correlation + 1) / 2
            elif overlap_count == 1:
                correlation_component = 0.5
            else:
                correlation_component = 0.0
            # A correlation over two films is structurally +/-1: two points
            # always sit on a line. Taken at face value that paid the full 45%
            # of the score, so a pair who had rated two films in common and
            # happened to agree scored 80 -- level with a pair sharing 95 films
            # and 48 ratings. Thin overlaps are pulled toward 0.5, which is the
            # "no correlation" midpoint, in proportion to how thin they are.
            correlation_weight = overlap_count / (overlap_count + CORRELATION_PRIOR_FILMS)
            correlation_component = (
                correlation_weight * correlation_component
                + (1 - correlation_weight) * 0.5
            )
            shared_titles = int(pair.get("shared_titles") or 0)
            shared_component = min(shared_titles / 20, 1.0)
            timing_component = min(
                pair["tight_window_count"] / max(shared_titles, 1),
                1.0,
            )
            average_gap = _coerce_finite_float(pair.get("average_rating_gap"))
            gap_component = (
                max(0.0, 1.0 - (average_gap / 2.5))
                if average_gap is not None
                else 1.0
            )
            # The same thinness applies here: a 0.0 average gap across two films
            # is not agreement, it is a coincidence with a small sample.
            gap_component = (
                correlation_weight * gap_component + (1 - correlation_weight) * 0.5
            )
            pair["alignment_score"] = _safe_round(
                100
                * (
                    0.45 * correlation_component
                    + 0.25 * shared_component
                    + 0.20 * timing_component
                    + 0.10 * gap_component
                ),
                1,
            ) or 0.0

    aligned_pairs = list(aligned_by_pair.values())
    aligned_pairs.sort(
        key=lambda pair: (
            -(pair.get("alignment_score") or 0),
            -pair.get("shared_titles", 0),
            -pair.get("tight_window_count", 0),
            pair["profiles"],
        )
    )
    follow_path_list = [
        {
            "leader": leader,
            "follower": follower,
            "next_day_overlap_count": metrics["count"],
            "sample_titles": metrics["sample_titles"],
        }
        for (leader, follower), metrics in timing["follow_paths"].items()
        if metrics["count"] > 0
    ]
    follow_path_list.sort(
        key=lambda path: (
            -path["next_day_overlap_count"],
            path["leader"],
            path["follower"],
        )
    )

    same_day_events = timing["same_day_events"]
    one_day_gap_events = timing["one_day_gap_events"]
    gap_events = timing["gap_events"]
    summary = baseline["summary"]
    summary.update(
        {
            "profiles_with_diary_dates": len(timing["profiles_with_dates"]),
            "same_day_events": len(same_day_events),
            "one_day_gap_events": len(one_day_gap_events),
            "same_day_pair_hits": sum(event["pair_count"] for event in same_day_events),
            "one_day_gap_pair_hits": sum(
                event["pair_count"] for event in one_day_gap_events
            ),
            "strongest_alignment_pair": aligned_pairs[0] if aligned_pairs else None,
        }
    )
    if gap_days is not None:
        summary.update(
            {
                "gap_days": gap_days,
                "gap_events": len(gap_events),
                "gap_pair_hits": sum(event["pair_count"] for event in gap_events),
            }
        )

    baseline["same_day_events"] = same_day_events[:limit]
    baseline["one_day_gap_events"] = one_day_gap_events[:limit]
    baseline["most_shared_titles"] = baseline.get("most_shared_titles", [])[:limit]
    baseline["consensus_hits"] = baseline.get("consensus_hits", [])[:limit]
    baseline["divisive_titles"] = baseline.get("divisive_titles", [])[:limit]
    baseline["aligned_pairs"] = aligned_pairs[:limit]
    baseline["follow_paths"] = follow_path_list[:limit]
    if gap_days is not None:
        baseline["gap_events"] = gap_events[:limit]
    return baseline

class ProfileRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_profile_by_username(self, username: str) -> Optional[Profile]:
        return (
            self.db.query(Profile)
            .filter(func.lower(Profile.username) == username.strip().casefold())
            .one_or_none()
        )

    def rename_profile(self, profile: Profile, new_username: str) -> bool:
        """Carry a canonical profile to a new Letterboxd username in place.

        Letterboxd 404s old profile URLs without a redirect after a username
        change, so the imported dataset keeps its identity and the RSS feed
        state is repointed at the new feed URL with its failure backoff
        cleared. App users whose account mirrors the old username follow it.
        Returns whether a feed state row was repointed.
        """
        old_username = profile.username
        profile.username = new_username

        feed_state = self.db.get(ProfileFeedState, profile.id)
        if feed_state is not None:
            # Mirrors services.rss_incremental._default_feed_url; usernames
            # are restricted to [A-Za-z0-9_-] so no quoting is required.
            feed_state.feed_url = f"https://letterboxd.com/{new_username}/rss/"
            feed_state.consecutive_failures = 0
            feed_state.last_error = None
            feed_state.last_http_status = None
            feed_state.next_poll_at = datetime.now(timezone.utc)

        self.db.query(AppUser).filter(
            func.lower(AppUser.letterboxd_username) == old_username.strip().casefold()
        ).update(
            {AppUser.letterboxd_username: new_username},
            synchronize_session=False,
        )

        self.db.commit()
        return feed_state is not None
    
    def get_profile_by_id(self, profile_id: int) -> Optional[Profile]:
        return self.db.query(Profile).filter(Profile.id == profile_id).first()
    
    def get_all_profiles(self, active_only: bool = True) -> List[Profile]:
        query = self.db.query(Profile)
        if active_only:
            query = query.filter(Profile.is_active == True)
        return query.order_by(Profile.updated_at.desc()).all()
    
    def create_profile(self, username: str, **kwargs) -> Profile:
        profile = Profile(username=username, **kwargs)
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(profile)
        return profile
    
    def update_profile(self, profile_id: int, **kwargs) -> Optional[Profile]:
        profile = self.get_profile_by_id(profile_id)
        if profile:
            for key, value in kwargs.items():
                setattr(profile, key, value)
            profile.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(profile)
        return profile
    
    def delete_profile(self, profile_id: int) -> bool:
        profile = self.get_profile_by_id(profile_id)
        if profile:
            self.db.delete(profile)
            self.db.commit()
            return True
        return False

    def clear_profile_data(self, profile_id: int) -> Optional[Dict[str, int]]:
        """Clear imported profile state and lineage in one transaction."""
        profile = self.get_profile_by_id(profile_id)
        if profile is None:
            return None

        try:
            movie_list_ids = [
                movie_list_id
                for (movie_list_id,) in (
                    self.db.query(MovieList.id)
                    .filter(MovieList.profile_id == profile_id)
                    .all()
                )
            ]
            profile_sync_ids = [
                profile_sync_id
                for (profile_sync_id,) in (
                    self.db.query(ProfileSync.id)
                    .filter(ProfileSync.profile_id == profile_id)
                    .all()
                )
            ]

            deleted = {
                "profile_data_changes": self.db.query(ProfileDataChange)
                .filter(ProfileDataChange.profile_id == profile_id)
                .delete(synchronize_session=False),
                "source_activities": self.db.query(ProfileSourceActivity)
                .filter(ProfileSourceActivity.profile_id == profile_id)
                .delete(synchronize_session=False),
                "watch_events": self.db.query(WatchEvent)
                .filter(WatchEvent.profile_id == profile_id)
                .delete(synchronize_session=False),
                "watchlist_items": self.db.query(WatchlistItem)
                .filter(WatchlistItem.profile_id == profile_id)
                .delete(synchronize_session=False),
                "favorite_movies": self.db.query(ProfileFavoriteMovie)
                .filter(ProfileFavoriteMovie.profile_id == profile_id)
                .delete(synchronize_session=False),
                "movie_list_items": (
                    self.db.query(MovieListItem)
                    .filter(MovieListItem.movie_list_id.in_(movie_list_ids))
                    .delete(synchronize_session=False)
                    if movie_list_ids
                    else 0
                ),
                "movie_lists": self.db.query(MovieList)
                .filter(MovieList.profile_id == profile_id)
                .delete(synchronize_session=False),
                "profile_films": self.db.query(ProfileFilm)
                .filter(ProfileFilm.profile_id == profile_id)
                .delete(synchronize_session=False),
                "reviews": self.db.query(Review)
                .filter(Review.profile_id == profile_id)
                .delete(synchronize_session=False),
                "ratings": self.db.query(Rating)
                .filter(Rating.profile_id == profile_id)
                .delete(synchronize_session=False),
            }

            # Break the profile's direct lineage reference before deleting its
            # sync history. Shared canonical Movie rows and TMDB caches remain.
            profile.last_profile_sync_id = None
            profile.metadata_synced_at = None
            profile.reported_total_films = None
            profile.reported_total_reviews = None
            profile.reported_total_lists = None
            profile.scraping_status = "pending"
            profile.last_scraped_at = None
            profile.avg_rating = 0.0
            profile.total_reviews = 0
            profile.enhanced_metrics = None
            self.db.flush()

            deleted["sync_datasets"] = (
                self.db.query(SyncDataset)
                .filter(SyncDataset.profile_sync_id.in_(profile_sync_ids))
                .delete(synchronize_session=False)
                if profile_sync_ids
                else 0
            )
            deleted["profile_syncs"] = self.db.query(ProfileSync).filter(
                ProfileSync.profile_id == profile_id
            ).delete(synchronize_session=False)
            self.db.commit()
            return deleted
        except Exception:
            self.db.rollback()
            raise
    
    def get_profiles_requiring_update(self, hours: int = 24) -> List[Profile]:
        """Get profiles that haven't been updated in X hours"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        return self.db.query(Profile).filter(
            or_(
                Profile.last_scraped_at == None,
                Profile.last_scraped_at < cutoff_time
            )
        ).all()

class RatingRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_ratings_by_profile(self, profile_id: int, limit: int = None) -> List[Rating]:
        query = self.db.query(Rating).filter(Rating.profile_id == profile_id)
        query = query.order_by(Rating.watched_date.desc())
        if limit:
            query = query.limit(limit)
        return query.all()
    
    def create_rating(self, profile_id: int, **kwargs) -> Rating:
        rating = Rating(profile_id=profile_id, **kwargs)
        self.db.add(rating)
        self.db.commit()
        self.db.refresh(rating)
        return rating
    
    def bulk_create_ratings(self, ratings_data: List[Dict]) -> int:
        """Bulk insert ratings for better performance"""
        ratings = [Rating(**data) for data in ratings_data]
        self.db.add_all(ratings)
        self.db.commit()
        return len(ratings)
    
    def delete_ratings_by_profile(self, profile_id: int) -> int:
        """Delete all ratings for a profile"""
        count = self.db.query(Rating).filter(Rating.profile_id == profile_id).count()
        self.db.query(Rating).filter(Rating.profile_id == profile_id).delete()
        self.db.commit()
        return count
    
    def get_rating_distribution(self, profile_id: int) -> Dict[str, int]:
        """Get rating distribution for a profile"""
        results = self.db.query(
            Rating.rating,
            func.count(Rating.id).label('count')
        ).filter(
            Rating.profile_id == profile_id,
            Rating.rating.isnot(None),
            Rating.rating >= RATING_MIN,
            Rating.rating <= RATING_MAX,
        ).group_by(Rating.rating).all()
        
        return {str(rating): count for rating, count in results}
    
    def _get_monthly_watch_activity(
        self,
        profile_ids: Optional[List[int]],
        *,
        months: int,
        as_of: Optional[date] = None,
    ) -> List[Dict]:
        """Aggregate active dated watch occurrences into calendar months."""
        if months <= 0 or (profile_ids is not None and not profile_ids):
            return []

        activity_as_of = as_of or datetime.now(timezone.utc).date()
        current_month_start = activity_as_of.replace(day=1)
        window_start = _shift_month_start(current_month_start, -(months - 1))
        year_bucket = extract("year", WatchEvent.watched_date)
        month_bucket = extract("month", WatchEvent.watched_date)
        valid_rating = case(
            (
                and_(
                    WatchEvent.rating >= 0.5,
                    WatchEvent.rating <= RATING_MAX,
                ),
                WatchEvent.rating,
            ),
            else_=None,
        )

        query = self.db.query(
            year_bucket.label("year"),
            month_bucket.label("month"),
            func.count(WatchEvent.id).label("watch_count"),
            func.count(func.distinct(WatchEvent.movie_id)).label("unique_movie_count"),
            func.avg(valid_rating).label("avg_rating"),
        ).filter(
            WatchEvent.watched_date >= window_start,
            WatchEvent.watched_date <= activity_as_of,
            WatchEvent.superseded_at.is_(None),
        )
        if profile_ids is not None:
            query = query.filter(WatchEvent.profile_id.in_(profile_ids))

        results = (
            query.group_by(year_bucket, month_bucket)
            .order_by(year_bucket, month_bucket)
            .all()
        )
        if not results:
            return []

        activity_by_month = {
            _format_month_bucket(year, month): {
                "movies_watched": int(watch_count),
                "unique_movies": int(unique_movie_count),
                "average_rating": _safe_round(avg_rating, 2),
            }
            for year, month, watch_count, unique_movie_count, avg_rating in results
        }

        activity = []
        for offset in range(months):
            month_start = _shift_month_start(window_start, offset)
            month_key = _format_month_bucket(month_start.year, month_start.month)
            monthly_values = activity_by_month.get(month_key)
            activity.append(
                {
                    "month": month_key,
                    "movies_watched": (
                        monthly_values["movies_watched"] if monthly_values else 0
                    ),
                    "unique_movies": (
                        monthly_values["unique_movies"] if monthly_values else 0
                    ),
                    "average_rating": (
                        monthly_values["average_rating"] if monthly_values else None
                    ),
                    "is_partial": month_start == current_month_start,
                }
            )
        return activity

    def get_monthly_watch_stats(
        self,
        profile_id: int,
        months: int = 12,
        *,
        as_of: Optional[date] = None,
    ) -> List[Dict]:
        """Get calendar-aligned monthly watch-event statistics for one profile."""
        return self._get_monthly_watch_activity(
            [profile_id],
            months=months,
            as_of=as_of,
        )

    def get_global_rating_distribution(
        self,
        profile_ids: Optional[List[int]] = None,
    ) -> Dict[str, int]:
        """Get rating distribution across all or an explicit profile scope."""
        query = self.db.query(
            Rating.rating,
            func.count(Rating.id).label('count')
        ).filter(
            Rating.rating.isnot(None),
            Rating.rating >= RATING_MIN,
            Rating.rating <= RATING_MAX,
        )
        if profile_ids is not None:
            query = query.filter(
                Rating.profile_id.in_(profile_ids) if profile_ids else false()
            )
        results = query.group_by(Rating.rating).all()

        return {str(rating): count for rating, count in results}
    
    def get_global_monthly_activity(
        self,
        profile_ids: Optional[List[int]] = None,
        *,
        months: int = DASHBOARD_ACTIVITY_MONTHS,
        as_of: Optional[date] = None,
    ) -> List[Dict]:
        """Get calendar-aligned monthly watch-event activity for a profile scope."""
        return self._get_monthly_watch_activity(
            profile_ids,
            months=months,
            as_of=as_of,
        )

class ReviewRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_reviews_by_profile(self, profile_id: int, limit: int = None) -> List[Review]:
        query = self.db.query(Review).filter(Review.profile_id == profile_id)
        query = query.order_by(Review.published_date.desc())
        if limit:
            query = query.limit(limit)
        return query.all()
    
    def create_review(self, profile_id: int, **kwargs) -> Review:
        review = Review(profile_id=profile_id, **kwargs)
        self.db.add(review)
        self.db.commit()
        self.db.refresh(review)
        return review
    
    def bulk_create_reviews(self, reviews_data: List[Dict]) -> int:
        """Bulk insert reviews for better performance"""
        reviews = [Review(**data) for data in reviews_data]
        self.db.add_all(reviews)
        self.db.commit()
        return len(reviews)
    
    def delete_reviews_by_profile(self, profile_id: int) -> int:
        """Delete all reviews for a profile"""
        count = self.db.query(Review).filter(Review.profile_id == profile_id).count()
        self.db.query(Review).filter(Review.profile_id == profile_id).delete()
        self.db.commit()
        return count

class AnalyticsRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def _profile_ids_for_usernames(
        self,
        usernames: Optional[List[str]],
    ) -> Optional[List[int]]:
        if usernames is None:
            return None
        canonical_usernames = {username for username in usernames if username.strip()}
        if not canonical_usernames:
            return []
        return [
            profile_id
            for (profile_id,) in (
                self.db.query(Profile.id)
                .filter(
                    Profile.username.in_(canonical_usernames),
                    Profile.is_active.is_(True),
                    Profile.scraping_status == "completed",
                )
                .all()
            )
        ]

    def get_system_stats(
        self,
        usernames: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Get overall statistics across all or an explicit profile scope."""
        profile_ids = self._profile_ids_for_usernames(usernames)
        if profile_ids is None:
            total_profiles = self.db.query(func.count(Profile.id)).scalar()
            rating_scope = self.db.query(Rating)
            review_scope = self.db.query(Review)
        else:
            total_profiles = len(profile_ids)
            rating_scope = self.db.query(Rating).filter(
                Rating.profile_id.in_(profile_ids) if profile_ids else false()
            )
            review_scope = self.db.query(Review).filter(
                Review.profile_id.in_(profile_ids) if profile_ids else false()
            )

        total_unique_movies = rating_scope.with_entities(
            Rating.movie_title,
            Rating.movie_year,
        ).distinct().count()
        total_reviews = review_scope.with_entities(func.count(Review.id)).scalar()
        
        # Global average rating across all ratings
        rating_average_scope = rating_scope.with_entities(func.avg(Rating.rating))
        global_avg_rating = rating_average_scope.filter(
            Rating.rating.isnot(None),
            Rating.rating >= RATING_MIN,
            Rating.rating <= RATING_MAX,
        ).scalar() or 0.0
        
        return {
            "total_profiles": total_profiles,
            "total_movies_tracked": total_unique_movies,
            "total_reviews": total_reviews,
            "global_avg_rating": _safe_round(global_avg_rating, 2) or 0.0,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

    def get_public_profile_health(self) -> Dict[str, Any]:
        """Return aggregate sync health without exposing profile records."""

        active_profiles = self.db.query(Profile).filter(Profile.is_active.is_(True))
        completed_profiles = active_profiles.filter(
            Profile.scraping_status == "completed"
        ).count()
        latest_sync = active_profiles.filter(
            Profile.scraping_status == "completed"
        ).with_entities(func.max(Profile.last_scraped_at)).scalar()
        return {
            "active_profiles": active_profiles.count(),
            "completed_profiles": completed_profiles,
            "last_synced_at": latest_sync.isoformat() if latest_sync else None,
        }
    
    def get_top_rated_movies(
        self,
        limit: int = 50,
        usernames: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Get top-rated movies across all or an explicit profile scope."""
        profile_ids = self._profile_ids_for_usernames(usernames)
        query = self.db.query(
            Rating.movie_title,
            Rating.movie_year,
            func.avg(Rating.rating).label('avg_rating'),
            func.count(Rating.id).label('rating_count')
        ).filter(
            Rating.rating.isnot(None),
            Rating.rating >= RATING_MIN,
            Rating.rating <= RATING_MAX,
        )
        if profile_ids is not None:
            query = query.filter(
                Rating.profile_id.in_(profile_ids) if profile_ids else false()
            )
        results = query.group_by(
            Rating.movie_title, Rating.movie_year
        ).having(
            func.count(Rating.id) >= 3  # At least 3 ratings
        ).order_by(
            desc('avg_rating')
        ).limit(limit).all()
        
        movies: List[Dict[str, Any]] = []
        for title, year, avg_rating, count in results:
            safe_avg = _safe_round(avg_rating, 2)
            if safe_avg is None:
                continue
            movies.append(
                {
                    "title": title,
                    "year": year,
                    "average_rating": safe_avg,
                    "total_ratings": count,
                }
            )
        return movies

    def build_dashboard_analytics_snapshot(
        self,
        group_limit: int = 6,
        top_movies_limit: int = 10,
        usernames: Optional[List[str]] = None,
        *,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        generated_at = _coerce_utc_now(now)
        if usernames is None:
            usernames = [
                username
                for (username,) in (
                    self.db.query(Profile.username)
                    .filter(
                        Profile.is_active.is_(True),
                        Profile.scraping_status == "completed",
                    )
                    .order_by(Profile.id.asc())
                    .all()
                )
            ]
        rating_repo = RatingRepository(self.db)
        profile_ids = self._profile_ids_for_usernames(usernames)

        return {
            "system_stats": self.get_system_stats(usernames=usernames),
            "top_rated_movies": self.get_top_rated_movies(
                limit=top_movies_limit,
                usernames=usernames,
            ),
            "rating_distribution": rating_repo.get_global_rating_distribution(
                profile_ids=profile_ids,
            ),
            "activity_data": rating_repo.get_global_monthly_activity(
                profile_ids=profile_ids,
                as_of=generated_at.date(),
            ),
            "group_signals": self.get_group_correlation_metrics(
                usernames=usernames,
                limit=group_limit,
            ),
            "timestamp": generated_at.isoformat(),
        }

    def _get_latest_metrics_record(self) -> Optional[SystemMetrics]:
        return (
            self.db.query(SystemMetrics)
            .order_by(SystemMetrics.timestamp.desc(), SystemMetrics.id.desc())
            .first()
        )

    def _get_latest_profile_update(self) -> Optional[datetime]:
        latest_profile_update = self.db.query(func.max(Profile.updated_at)).scalar()
        return _naive_utc(latest_profile_update)

    def _get_profile_count(self) -> int:
        return (
            self.db.query(func.count(Profile.id))
            .filter(
                Profile.is_active.is_(True),
                Profile.scraping_status == "completed",
            )
            .scalar()
            or 0
        )

    def get_dashboard_analytics_snapshot(
        self,
        group_limit: int = 6,
        top_movies_limit: int = 10,
        *,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        requested_at = _coerce_utc_now(now)
        expected_meta = _dashboard_snapshot_meta(requested_at.date())
        latest_metrics = self._get_latest_metrics_record()
        latest_profile_update = self._get_latest_profile_update()
        current_profile_count = self._get_profile_count()

        if latest_metrics and isinstance(latest_metrics.metrics, dict):
            dashboard_snapshot = latest_metrics.metrics.get("dashboard_snapshot")
            snapshot_meta = latest_metrics.metrics.get("dashboard_snapshot_meta")
            snapshot_timestamp = _naive_utc(latest_metrics.timestamp)
            cached_profile_count = None
            if isinstance(dashboard_snapshot, dict):
                cached_profile_count = (
                    dashboard_snapshot
                    .get("system_stats", {})
                    .get("total_profiles")
                )
            if dashboard_snapshot and snapshot_meta == expected_meta and (
                cached_profile_count == current_profile_count
                and snapshot_timestamp is not None
                and (
                    latest_profile_update is None
                    or latest_profile_update <= snapshot_timestamp
                )
            ):
                return dashboard_snapshot

        return self.refresh_dashboard_analytics_snapshot(
            group_limit=group_limit,
            top_movies_limit=top_movies_limit,
            now=requested_at,
        )

    def refresh_dashboard_analytics_snapshot(
        self,
        group_limit: int = 6,
        top_movies_limit: int = 10,
        *,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        refreshed_at = _coerce_utc_now(now)
        snapshot = self.build_dashboard_analytics_snapshot(
            group_limit=group_limit,
            top_movies_limit=top_movies_limit,
            now=refreshed_at,
        )
        system_stats = snapshot["system_stats"]
        metrics_payload = {
            "dashboard_snapshot": snapshot,
            "dashboard_snapshot_meta": _dashboard_snapshot_meta(refreshed_at.date()),
        }

        latest_metrics = self._get_latest_metrics_record()
        if latest_metrics:
            existing_metrics = latest_metrics.metrics if isinstance(latest_metrics.metrics, dict) else {}
            latest_metrics.timestamp = refreshed_at
            latest_metrics.total_profiles = system_stats["total_profiles"]
            latest_metrics.total_movies_tracked = system_stats["total_movies_tracked"]
            latest_metrics.total_reviews = system_stats["total_reviews"]
            latest_metrics.active_scraping_jobs = 0
            latest_metrics.metrics = {
                **existing_metrics,
                **metrics_payload,
            }
        else:
            latest_metrics = SystemMetrics(
                timestamp=refreshed_at,
                total_profiles=system_stats["total_profiles"],
                total_movies_tracked=system_stats["total_movies_tracked"],
                total_reviews=system_stats["total_reviews"],
                active_scraping_jobs=0,
                metrics=metrics_payload,
            )
            self.db.add(latest_metrics)

        self.db.commit()
        self.db.refresh(latest_metrics)

        stored_snapshot = None
        if isinstance(latest_metrics.metrics, dict):
            stored_snapshot = latest_metrics.metrics.get("dashboard_snapshot")
        return stored_snapshot or snapshot

    def _get_event_source_timing_entries(
        self,
        usernames: Optional[List[str]],
    ) -> List[Dict[str, Any]]:
        profile_query = self.db.query(Profile.id, Profile.username).filter(
            Profile.is_active.is_(True),
            Profile.scraping_status == "completed",
        )
        if usernames is not None:
            profile_query = profile_query.filter(
                Profile.username.in_(usernames) if usernames else false()
            )
        selected_profiles = dict(profile_query.all())
        profile_ids = list(selected_profiles)
        if not profile_ids:
            return []

        # Authority is intentionally profile-scoped. An authoritative empty
        # diary is still authoritative and must not fall back to a stale
        # one-date Rating snapshot.
        authoritative_profile_ids = {
            profile_id
            for (profile_id,) in (
                self.db.query(ProfileSync.profile_id)
                .join(
                    SyncDataset,
                    SyncDataset.profile_sync_id == ProfileSync.id,
                )
                .filter(
                    ProfileSync.profile_id.in_(profile_ids),
                    ProfileSync.status == "completed",
                    SyncDataset.is_authoritative.is_(True),
                    func.lower(SyncDataset.dataset_name).in_(("diary", "watch_events")),
                )
                .distinct()
                .all()
            )
        }
        fallback_profile_ids = set(profile_ids) - authoritative_profile_ids
        entries: List[Dict[str, Any]] = []

        if authoritative_profile_ids:
            event_rows = (
                self.db.query(
                    WatchEvent.profile_id,
                    WatchEvent.movie_id,
                    Profile.username,
                    Movie.title,
                    Movie.release_year,
                    Movie.letterboxd_slug,
                    Movie.letterboxd_id,
                    WatchEvent.rating,
                    WatchEvent.watched_date,
                    WatchEvent.is_rewatch,
                    WatchEvent.is_liked,
                )
                .join(Profile, Profile.id == WatchEvent.profile_id)
                .join(Movie, Movie.id == WatchEvent.movie_id)
                .filter(
                    WatchEvent.profile_id.in_(authoritative_profile_ids),
                    WatchEvent.superseded_at.is_(None),
                )
                .all()
            )
            for (
                profile_id,
                movie_id,
                username,
                movie_title,
                movie_year,
                film_slug,
                letterboxd_id,
                rating,
                watched_date,
                is_rewatch,
                is_liked,
            ) in event_rows:
                normalized_rating = _coerce_finite_float(rating)
                if normalized_rating is not None and not (
                    RATING_MIN <= normalized_rating <= RATING_MAX
                ):
                    normalized_rating = None
                entries.append(
                    {
                        "profile_id": profile_id,
                        "movie_id": movie_id,
                        "username": username,
                        "movie_title": movie_title,
                        "movie_year": movie_year,
                        "film_slug": film_slug,
                        "letterboxd_id": letterboxd_id,
                        "rating": normalized_rating,
                        "watched_date": watched_date,
                        "is_rewatch": bool(is_rewatch),
                        "is_liked": bool(is_liked),
                    }
                )

        if fallback_profile_ids:
            fallback_rows = (
                self.db.query(
                    Rating.profile_id,
                    Rating.movie_id,
                    Profile.username,
                    Rating.movie_title,
                    Rating.movie_year,
                    Rating.film_slug,
                    Rating.letterboxd_id,
                    Rating.rating,
                    Rating.watched_date,
                    Rating.is_rewatch,
                    Rating.is_liked,
                )
                .join(Profile, Profile.id == Rating.profile_id)
                .filter(
                    Rating.profile_id.in_(fallback_profile_ids),
                    Rating.watched_date.isnot(None),
                )
                .all()
            )
            for (
                profile_id,
                movie_id,
                username,
                movie_title,
                movie_year,
                film_slug,
                letterboxd_id,
                rating,
                watched_date,
                is_rewatch,
                is_liked,
            ) in fallback_rows:
                normalized_rating = _coerce_finite_float(rating)
                if normalized_rating is not None and not (
                    RATING_MIN <= normalized_rating <= RATING_MAX
                ):
                    normalized_rating = None
                entries.append(
                    {
                        "profile_id": profile_id,
                        "movie_id": movie_id,
                        "username": username,
                        "movie_title": movie_title,
                        "movie_year": movie_year,
                        "film_slug": film_slug,
                        "letterboxd_id": letterboxd_id,
                        "rating": normalized_rating,
                        "watched_date": watched_date,
                        "is_rewatch": bool(is_rewatch),
                        "is_liked": bool(is_liked),
                    }
                )
        return entries

    def get_group_correlation_metrics(
        self,
        usernames: Optional[List[str]] = None,
        limit: int = 8,
        gap_days: Optional[int] = None,
        event_source: str = "ratings",
    ) -> Dict[str, Any]:
        """Build shared-profile correlation signals for dashboard and group analysis views."""
        if gap_days is not None and not 0 <= gap_days <= 7:
            raise ValueError("gap_days must be between 0 and 7")
        if event_source not in {"ratings", "events"}:
            raise ValueError("event_source must be 'ratings' or 'events'")
        if event_source == "events":
            normalized_event_usernames = None
            if usernames is not None:
                normalized_event_usernames = list(
                    dict.fromkeys(
                        username.strip()
                        for username in usernames
                        if username and username.strip()
                    )
                )
            # Request a complete internal baseline so a pair outside the
            # caller's display limit can still become the strongest pair after
            # occurrence-level timing is applied.
            baseline = self.get_group_correlation_metrics(
                usernames=usernames,
                limit=max(limit, 10_000),
                gap_days=gap_days,
                event_source="ratings",
            )
            timing_entries = self._get_event_source_timing_entries(
                normalized_event_usernames
            )
            timing = _calculate_event_source_timing(
                timing_entries,
                gap_days=gap_days,
            )
            return _merge_event_source_timing(
                baseline,
                timing,
                limit=limit,
                gap_days=gap_days,
            )

        query = (
            self.db.query(
                Profile.username,
                Rating.movie_title,
                Rating.movie_year,
                Rating.film_slug,
                Rating.letterboxd_id,
                Rating.rating,
                Rating.watched_date,
                Rating.is_rewatch,
                Rating.is_liked,
            )
            .join(Profile, Profile.id == Rating.profile_id)
            .filter(
                Profile.is_active.is_(True),
                Profile.scraping_status == "completed",
            )
        )

        normalized_usernames: Optional[List[str]] = None
        if usernames is not None:
            normalized_usernames = list(
                dict.fromkeys(
                    username.strip()
                    for username in usernames
                    if username and username.strip()
                )
            )
            query = query.filter(
                Profile.username.in_(normalized_usernames)
                if normalized_usernames
                else false()
            )

        rows = query.all()
        if not rows:
            empty_signals = {
                "summary": {
                    "profiles_analyzed": len(normalized_usernames or []),
                    "profiles_with_diary_dates": 0,
                    "shared_titles": 0,
                    "same_day_events": 0,
                    "one_day_gap_events": 0,
                    "same_day_pair_hits": 0,
                    "one_day_gap_pair_hits": 0,
                    "most_shared_title": None,
                    "strongest_alignment_pair": None,
                    "most_divisive_title": None,
                },
                "same_day_events": [],
                "one_day_gap_events": [],
                "most_shared_titles": [],
                "consensus_hits": [],
                "divisive_titles": [],
                "aligned_pairs": [],
                "follow_paths": [],
            }
            if gap_days is not None:
                empty_signals["summary"].update(
                    {
                        "gap_days": gap_days,
                        "gap_events": 0,
                        "gap_pair_hits": 0,
                    }
                )
                empty_signals["gap_events"] = []
            return empty_signals

        movies_by_key: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        pair_metrics: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(
            lambda: {
                "shared_titles": 0,
                "same_day_count": 0,
                "one_day_gap_count": 0,
                "tight_window_count": 0,
                "within_gap_count": 0,
                "left_ratings": [],
                "right_ratings": [],
                "rating_gaps": [],
                "sample_titles": [],
            }
        )
        follow_paths: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "sample_titles": []}
        )
        analyzed_profiles = set()
        profiles_with_diary_dates = set()

        for (
            username,
            movie_title,
            movie_year,
            film_slug,
            letterboxd_id,
            rating,
            watched_date,
            is_rewatch,
            is_liked,
        ) in rows:
            analyzed_profiles.add(username)
            if watched_date:
                profiles_with_diary_dates.add(username)

            normalized_rating = _coerce_finite_float(rating)
            if normalized_rating is not None and not (RATING_MIN <= normalized_rating <= RATING_MAX):
                normalized_rating = None

            entry = {
                "username": username,
                "movie_title": movie_title,
                "movie_year": movie_year,
                "rating": normalized_rating,
                "watched_date": watched_date,
                "is_rewatch": bool(is_rewatch),
                "is_liked": bool(is_liked),
            }
            movies_by_key[
                _movie_identity_key(
                    movie_title=movie_title,
                    movie_year=movie_year,
                    film_slug=film_slug,
                    letterboxd_id=letterboxd_id,
                )
            ].append(entry)

        same_day_events: List[Dict[str, Any]] = []
        one_day_gap_events: List[Dict[str, Any]] = []
        gap_events: List[Dict[str, Any]] = []
        shared_titles: List[Dict[str, Any]] = []
        consensus_candidates: List[Dict[str, Any]] = []
        divisive_candidates: List[Dict[str, Any]] = []

        for entries in movies_by_key.values():
            if len(entries) < 2:
                continue

            movie_summary = _build_movie_summary(entries)
            shared_titles.append(movie_summary)

            if movie_summary["rating_count"] >= 2:
                consensus_candidates.append(movie_summary)
                divisive_candidates.append(movie_summary)

            dated_buckets: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
            for entry in entries:
                if entry["watched_date"]:
                    dated_buckets[entry["watched_date"]].append(entry)

            for watched_date, bucket in dated_buckets.items():
                if len(bucket) < 2:
                    continue
                pair_count = len(bucket) * (len(bucket) - 1) // 2
                same_day_event = _build_watch_event(
                    entries=bucket,
                    start_date=watched_date,
                    end_date=watched_date,
                    pair_count=pair_count,
                )
                same_day_events.append(same_day_event)
                if gap_days is not None:
                    gap_events.append({**same_day_event, "day_gap": 0})

            sorted_dates = sorted(dated_buckets.keys())
            for start_index, start_date in enumerate(sorted_dates):
                for end_date in sorted_dates[start_index + 1:]:
                    day_gap = (end_date - start_date).days
                    if day_gap > max(gap_days or 0, 1):
                        break

                    start_bucket = dated_buckets[start_date]
                    end_bucket = dated_buckets[end_date]
                    combined_entries = start_bucket + end_bucket
                    pair_count = len(start_bucket) * len(end_bucket)
                    if pair_count < 1:
                        continue

                    watch_event = _build_watch_event(
                        entries=combined_entries,
                        start_date=start_date,
                        end_date=end_date,
                        pair_count=pair_count,
                    )
                    if day_gap == 1:
                        one_day_gap_events.append(watch_event)
                    if gap_days is not None and day_gap <= gap_days:
                        gap_events.append({**watch_event, "day_gap": day_gap})

            for left_entry, right_entry in combinations(entries, 2):
                pair_key = tuple(sorted((left_entry["username"], right_entry["username"])))
                metrics = pair_metrics[pair_key]
                metrics["shared_titles"] += 1
                if len(metrics["sample_titles"]) < 3:
                    metrics["sample_titles"].append(
                        {
                            "title": left_entry["movie_title"],
                            "year": left_entry["movie_year"],
                        }
                    )

                ordered_left, ordered_right = (
                    (left_entry, right_entry)
                    if left_entry["username"] == pair_key[0]
                    else (right_entry, left_entry)
                )

                if ordered_left["rating"] is not None and ordered_right["rating"] is not None:
                    metrics["left_ratings"].append(ordered_left["rating"])
                    metrics["right_ratings"].append(ordered_right["rating"])
                    metrics["rating_gaps"].append(abs(ordered_left["rating"] - ordered_right["rating"]))

                if ordered_left["watched_date"] and ordered_right["watched_date"]:
                    day_delta = (ordered_right["watched_date"] - ordered_left["watched_date"]).days
                    abs_delta = abs(day_delta)
                    if abs_delta == 0:
                        metrics["same_day_count"] += 1
                    if abs_delta == 1:
                        metrics["one_day_gap_count"] += 1
                    if abs_delta <= 1:
                        metrics["tight_window_count"] += 1
                    if gap_days is not None and abs_delta <= gap_days:
                        metrics["within_gap_count"] += 1

                    if day_delta == 1:
                        path_metrics = follow_paths[(ordered_left["username"], ordered_right["username"])]
                        path_metrics["count"] += 1
                        if len(path_metrics["sample_titles"]) < 3:
                            path_metrics["sample_titles"].append(
                                {
                                    "title": ordered_left["movie_title"],
                                    "year": ordered_left["movie_year"],
                                }
                            )
                    elif day_delta == -1:
                        path_metrics = follow_paths[(ordered_right["username"], ordered_left["username"])]
                        path_metrics["count"] += 1
                        if len(path_metrics["sample_titles"]) < 3:
                            path_metrics["sample_titles"].append(
                                {
                                    "title": ordered_left["movie_title"],
                                    "year": ordered_left["movie_year"],
                                }
                            )

        aligned_pairs: List[Dict[str, Any]] = []
        for pair_key, metrics in pair_metrics.items():
            rating_overlap_count = len(metrics["left_ratings"])
            rating_correlation = _pearson_correlation(metrics["left_ratings"], metrics["right_ratings"])
            average_rating_gap = _average(metrics["rating_gaps"])

            correlation_component = 0.0
            if rating_correlation is not None:
                correlation_component = (rating_correlation + 1) / 2
            elif rating_overlap_count == 1:
                correlation_component = 0.5

            shared_component = min(metrics["shared_titles"] / 20, 1.0)
            timing_component = min(
                metrics["tight_window_count"] / max(metrics["shared_titles"], 1),
                1.0,
            )
            gap_component = 1.0
            if average_rating_gap is not None:
                gap_component = max(0.0, 1.0 - (average_rating_gap / 2.5))

            # Both of these are rating-derived, and both are meaningless on a
            # handful of films: any two points lie on a line, so a pair who had
            # rated two films in common and agreed on them scored a perfect
            # correlation and a zero gap, taking the full 55% those two
            # components are worth. That put them level with a pair sharing 95
            # films and 48 ratings. Shrink both toward the neutral midpoint in
            # proportion to how thin the overlap is.
            correlation_weight = rating_overlap_count / (
                rating_overlap_count + CORRELATION_PRIOR_FILMS
            )
            correlation_component = (
                correlation_weight * correlation_component
                + (1 - correlation_weight) * 0.5
            )
            gap_component = (
                correlation_weight * gap_component + (1 - correlation_weight) * 0.5
            )

            alignment_score = (
                (correlation_component * 0.45)
                + (shared_component * 0.25)
                + (timing_component * 0.20)
                + (gap_component * 0.10)
            ) * 100

            pair_summary = {
                "profiles": list(pair_key),
                "shared_titles": metrics["shared_titles"],
                "same_day_count": metrics["same_day_count"],
                "one_day_gap_count": metrics["one_day_gap_count"],
                "tight_window_count": metrics["tight_window_count"],
                "rating_overlap_count": rating_overlap_count,
                "rating_correlation": _safe_round(rating_correlation, 2),
                "average_rating_gap": _safe_round(average_rating_gap, 2),
                "alignment_score": _safe_round(alignment_score, 1) or 0.0,
                "sample_titles": metrics["sample_titles"],
            }
            if gap_days is not None:
                pair_summary["within_gap_count"] = metrics["within_gap_count"]
            aligned_pairs.append(pair_summary)

        follow_path_list = [
            {
                "leader": leader,
                "follower": follower,
                "next_day_overlap_count": metrics["count"],
                "sample_titles": metrics["sample_titles"],
            }
            for (leader, follower), metrics in follow_paths.items()
            if metrics["count"] > 0
        ]

        same_day_events.sort(
            key=lambda event: (
                -event["profile_count"],
                -event["pair_count"],
                -int(event["start_date"].replace("-", "")),
                event["title"],
            )
        )
        one_day_gap_events.sort(
            key=lambda event: (
                -event["profile_count"],
                -event["pair_count"],
                -int(event["start_date"].replace("-", "")),
                event["title"],
            )
        )
        if gap_days is not None:
            gap_events.sort(
                key=lambda event: (
                    -event["profile_count"],
                    event["day_gap"],
                    -event["pair_count"],
                    -int(event["start_date"].replace("-", "")),
                    event["title"],
                )
            )
        shared_titles.sort(
            key=lambda title: (
                -title["profile_count"],
                -(title["average_rating"] or 0),
                title["title"],
            )
        )
        consensus_candidates.sort(
            key=lambda title: (
                -(title["average_rating"] or 0),
                title["rating_stddev"] if title["rating_stddev"] is not None else 999,
                -title["profile_count"],
                title["title"],
            )
        )
        divisive_candidates.sort(
            key=lambda title: (
                -(title["rating_stddev"] or 0),
                -title["profile_count"],
                -(title["max_rating_gap"] or 0),
                title["title"],
            )
        )
        aligned_pairs.sort(
            key=lambda pair: (
                -(pair["alignment_score"] or 0),
                -pair["shared_titles"],
                -pair["tight_window_count"],
                pair["profiles"],
            )
        )
        follow_path_list.sort(
            key=lambda path: (
                -path["next_day_overlap_count"],
                path["leader"],
                path["follower"],
            )
        )

        same_day_pair_hits = sum(event["pair_count"] for event in same_day_events)
        one_day_gap_pair_hits = sum(event["pair_count"] for event in one_day_gap_events)

        result = {
            "summary": {
                "profiles_analyzed": len(analyzed_profiles),
                "profiles_with_diary_dates": len(profiles_with_diary_dates),
                "shared_titles": len(shared_titles),
                "same_day_events": len(same_day_events),
                "one_day_gap_events": len(one_day_gap_events),
                "same_day_pair_hits": same_day_pair_hits,
                "one_day_gap_pair_hits": one_day_gap_pair_hits,
                "most_shared_title": shared_titles[0] if shared_titles else None,
                "strongest_alignment_pair": aligned_pairs[0] if aligned_pairs else None,
                "most_divisive_title": divisive_candidates[0] if divisive_candidates else None,
            },
            "same_day_events": same_day_events[:limit],
            "one_day_gap_events": one_day_gap_events[:limit],
            "most_shared_titles": shared_titles[:limit],
            "consensus_hits": consensus_candidates[:limit],
            "divisive_titles": divisive_candidates[:limit],
            "aligned_pairs": aligned_pairs[:limit],
            "follow_paths": follow_path_list[:limit],
        }
        if gap_days is not None:
            result["summary"].update(
                {
                    "gap_days": gap_days,
                    "gap_events": len(gap_events),
                    "gap_pair_hits": sum(event["pair_count"] for event in gap_events),
                }
            )
            result["gap_events"] = gap_events[:limit]
        return result
