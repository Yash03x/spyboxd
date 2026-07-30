from __future__ import annotations

import json

from backend.main import PublicDashboardResponse, _public_dashboard_payload


def test_public_dashboard_payload_strictly_removes_identity_and_title_fields():
    sentinel = "private-user-sentinel"
    snapshot = {
        "system_stats": {
            "total_profiles": 13,
            "total_movies_tracked": 4000,
            "total_reviews": 700,
            "global_avg_rating": 3.75,
            "last_updated": "2026-07-30T10:00:00Z",
        },
        "top_rated_movies": [{"title": "Private Film Sentinel"}],
        "rating_distribution": {"4.0": 250, sentinel: 1},
        "activity_data": [
            {"month": "2026-07", "movies_watched": 80, "average_rating": 3.8},
            {"month": sentinel, "movies_watched": 1, "average_rating": 5.0},
        ],
        "group_signals": {
            "summary": {
                "profiles_analyzed": 13,
                "profiles_with_diary_dates": 12,
                "shared_titles": 300,
                "same_day_events": 20,
                "one_day_gap_events": 8,
                "same_day_pair_hits": 24,
                "one_day_gap_pair_hits": 9,
                "strongest_alignment_pair": {"profiles": [sentinel, "other"]},
                "most_shared_title": {"title": "Private Film Sentinel"},
            },
            "same_day_events": [
                {"participants": [{"username": sentinel}], "title": "Private Film Sentinel"}
            ],
        },
        "timestamp": "2026-07-30T10:00:00Z",
    }

    payload = _public_dashboard_payload(
        snapshot,
        {
            "active_profiles": 14,
            "completed_profiles": 13,
            "last_synced_at": "2026-07-30T09:55:00Z",
        },
    )
    validated = PublicDashboardResponse.model_validate(payload).model_dump(mode="json")

    assert set(validated) == {
        "system_stats",
        "rating_distribution",
        "activity_data",
        "signal_counts",
        "data_health",
        "timestamp",
    }
    assert set(validated["signal_counts"]) == {
        "profiles_analyzed",
        "profiles_with_diary_dates",
        "shared_titles",
        "same_day_events",
        "one_day_gap_events",
        "same_day_pair_hits",
        "one_day_gap_pair_hits",
    }
    serialized = json.dumps(validated).lower()
    assert sentinel not in serialized
    assert "private film sentinel" not in serialized
    for forbidden_key in ("username", "profiles", "participants", "title", "profile_id"):
        assert f'"{forbidden_key}"' not in serialized
