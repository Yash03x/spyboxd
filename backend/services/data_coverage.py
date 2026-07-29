from __future__ import annotations

from typing import Any, Dict, Optional


RSS_RECENT_WINDOW_MODE = "rss_recent_window"
FULL_HTML_UPLOAD_MODE = "full_html_upload"
UNKNOWN_MODE = "unknown"

RSS_RECENT_WINDOW_SUMMARY = (
    "Letterboxd RSS supplied an additions-only recent activity window over the latest "
    "authoritative full profile snapshot."
)

RSS_RECENT_WINDOW_LIMITATIONS = [
    "Feed disappearance is never treated as deletion because RSS is a rolling window.",
    "Watchlist, complete lists, favorites, private activity, and profile metadata require a full sync.",
]


def build_rss_recent_window_coverage(
    *,
    captured_unique_films: int,
    captured_diary_entries: int,
    captured_reviews: int,
) -> Dict[str, Any]:
    return {
        "mode": RSS_RECENT_WINDOW_MODE,
        "source": "rss_feed",
        "is_partial": True,
        "summary": RSS_RECENT_WINDOW_SUMMARY,
        "limitations": RSS_RECENT_WINDOW_LIMITATIONS,
        "stats_label": "captured",
        "captured_unique_films": captured_unique_films,
        "captured_diary_entries": captured_diary_entries,
        "captured_reviews": captured_reviews,
        "profile_metadata_available": False,
        "watchlist_available": False,
        "lists_available": False,
    }


def build_uploaded_files_coverage() -> Dict[str, Any]:
    return {
        "mode": FULL_HTML_UPLOAD_MODE,
        "source": "local_full_sync",
        "is_partial": False,
        "summary": "This profile was loaded from the local full HTML sync workflow.",
        "limitations": [],
        "stats_label": "synced",
        "profile_metadata_available": True,
        "watchlist_available": True,
        "lists_available": True,
    }


def default_data_coverage() -> Dict[str, Any]:
    return {
        "mode": UNKNOWN_MODE,
        "source": "unknown",
        "is_partial": None,
        "summary": "Coverage metadata is unavailable for this profile.",
        "limitations": [],
        "stats_label": "tracked",
    }


def merge_data_coverage(
    existing_metrics: Optional[Dict[str, Any]],
    data_coverage: Dict[str, Any],
) -> Dict[str, Any]:
    merged = dict(existing_metrics or {})
    merged["data_coverage"] = data_coverage
    return merged


def extract_data_coverage(metrics: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(metrics, dict):
        coverage = metrics.get("data_coverage")
        if isinstance(coverage, dict):
            return coverage
    return default_data_coverage()
