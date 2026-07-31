from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).with_name("check-runtime-health.py")
SPEC = importlib.util.spec_from_file_location("check_runtime_health", MODULE_PATH)
assert SPEC and SPEC.loader
health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health)


def dashboard_payload() -> dict:
    return {
        "activity_data": [],
        "data_health": {
            "active_profiles": 2,
            "completed_profiles": 2,
            "last_synced_at": "2026-07-31T00:00:00Z",
        },
        "rating_distribution": {"4.0": 3},
        "signal_counts": {
            "one_day_gap_events": 1,
            "one_day_gap_pair_hits": 1,
            "profiles_analyzed": 2,
            "profiles_with_diary_dates": 2,
            "same_day_events": 1,
            "same_day_pair_hits": 1,
            "shared_titles": 1,
        },
        "system_stats": {
            "global_avg_rating": 4.0,
            "total_movies_tracked": 3,
            "total_profiles": 2,
            "total_reviews": 1,
        },
        "timestamp": "2026-07-31T00:00:00Z",
    }


class RuntimeHealthValidationTests(unittest.TestCase):
    def test_dashboard_accepts_additive_fields(self) -> None:
        payload = dashboard_payload()
        payload["future_addition"] = {"safe": True}
        payload["system_stats"]["future_metric"] = 7
        payload["signal_counts"]["future_annotation"] = {"safe": True}
        health.validate_dashboard(payload)

    def test_dashboard_rejects_missing_or_invalid_contract(self) -> None:
        mutations = (
            lambda payload: payload.pop("signal_counts"),
            lambda payload: payload.__setitem__("activity_data", {}),
            lambda payload: payload["system_stats"].__setitem__("total_profiles", -1),
            lambda payload: payload["system_stats"].__setitem__(
                "total_movies_tracked", 0
            ),
            lambda payload: payload["data_health"].__setitem__("active_profiles", 0),
            lambda payload: payload["data_health"].__setitem__(
                "completed_profiles", 3
            ),
            lambda payload: payload["data_health"].__setitem__(
                "last_synced_at", None
            ),
            lambda payload: payload["signal_counts"].__setitem__(
                "profiles_with_diary_dates", 3
            ),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                payload = dashboard_payload()
                mutate(payload)
                with self.assertRaises(health.HealthValidationError):
                    health.validate_dashboard(payload)

    def test_ready_requires_matching_revision_and_database_schema(self) -> None:
        healthy = {
            "status": "ready",
            "revision": "a" * 40,
            "checks": {"database": "ok", "schema": "current"},
        }
        health.validate_ready(healthy, "a" * 40)

        invalid = (
            {**healthy, "revision": "b" * 40},
            {**healthy, "checks": {"database": "unavailable", "schema": "current"}},
            {**healthy, "checks": {"database": "ok", "schema": "pending"}},
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(health.HealthValidationError):
                    health.validate_ready(payload, "a" * 40)

    def test_rss_rejects_degraded_http_200_payload(self) -> None:
        healthy = {
            "status": "healthy",
            "requires_attention": False,
            "profiles": {
                "active": 2,
                "configured": 2,
                "fresh": 2,
                "stale": 0,
                "failing": 0,
            },
        }
        health.validate_rss(healthy)
        invalid_payloads = (
            {**healthy, "status": "degraded", "requires_attention": True},
            {
                **healthy,
                "profiles": {
                    **healthy["profiles"],
                    "active": 0,
                    "configured": 0,
                    "fresh": 0,
                },
            },
            {
                **healthy,
                "profiles": {**healthy["profiles"], "fresh": 1, "stale": 1},
            },
            {
                **healthy,
                "profiles": {**healthy["profiles"], "failing": 1},
            },
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(health.HealthValidationError):
                    health.validate_rss(payload)


if __name__ == "__main__":
    unittest.main()
