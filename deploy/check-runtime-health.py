#!/usr/bin/env python3
"""Strict, reusable validators for Spyboxd operational JSON endpoints."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from typing import Any


class HealthValidationError(ValueError):
    pass


def _object(payload: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(payload, dict):
        raise HealthValidationError(f"{label} must be a JSON object")
    return payload


def _require_keys(payload: Mapping[str, Any], required: set[str], label: str) -> None:
    missing = sorted(required - payload.keys())
    if missing:
        raise HealthValidationError(
            f"{label} is missing required keys: {', '.join(missing)}"
        )


def _non_negative_number(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise HealthValidationError(f"{label} must be a non-negative number")


def validate_ready(payload: Any, expected_revision: str) -> None:
    report = _object(payload, "readiness report")
    if report.get("status") != "ready":
        raise HealthValidationError("readiness status is not ready")
    if report.get("revision") != expected_revision:
        raise HealthValidationError("readiness revision does not match the release")
    checks = _object(report.get("checks"), "readiness checks")
    if checks.get("database") != "ok" or checks.get("schema") != "current":
        raise HealthValidationError("database or schema readiness check failed")


def validate_dashboard(payload: Any) -> None:
    report = _object(payload, "public dashboard")
    _require_keys(
        report,
        {
            "activity_data",
            "data_health",
            "rating_distribution",
            "signal_counts",
            "system_stats",
            "timestamp",
        },
        "public dashboard",
    )
    if not isinstance(report["activity_data"], list):
        raise HealthValidationError("activity_data must be an array")
    if not isinstance(report["rating_distribution"], dict):
        raise HealthValidationError("rating_distribution must be an object")
    if not isinstance(report["timestamp"], str) or not report["timestamp"].strip():
        raise HealthValidationError("timestamp must be a non-empty string")

    system_stats = _object(report["system_stats"], "system_stats")
    _require_keys(
        system_stats,
        {
            "global_avg_rating",
            "total_movies_tracked",
            "total_profiles",
            "total_reviews",
        },
        "system_stats",
    )
    for key in (
        "global_avg_rating",
        "total_movies_tracked",
        "total_profiles",
        "total_reviews",
    ):
        _non_negative_number(system_stats[key], f"system_stats.{key}")
    if system_stats["total_profiles"] <= 0 or system_stats["total_movies_tracked"] <= 0:
        raise HealthValidationError(
            "public dashboard must contain profiles and tracked movies"
        )

    data_health = _object(report["data_health"], "data_health")
    _require_keys(
        data_health,
        {"active_profiles", "completed_profiles", "last_synced_at"},
        "data_health",
    )
    _non_negative_number(data_health["active_profiles"], "data_health.active_profiles")
    _non_negative_number(
        data_health["completed_profiles"], "data_health.completed_profiles"
    )
    if data_health["active_profiles"] <= 0:
        raise HealthValidationError("data_health.active_profiles must be positive")
    if data_health["completed_profiles"] > data_health["active_profiles"]:
        raise HealthValidationError(
            "completed profile count cannot exceed active profile count"
        )
    if (
        not isinstance(data_health["last_synced_at"], str)
        or not data_health["last_synced_at"].strip()
    ):
        raise HealthValidationError("data_health.last_synced_at must be present")

    signal_counts = _object(report["signal_counts"], "signal_counts")
    required_signals = {
        "one_day_gap_events",
        "one_day_gap_pair_hits",
        "profiles_analyzed",
        "profiles_with_diary_dates",
        "same_day_events",
        "same_day_pair_hits",
        "shared_titles",
    }
    _require_keys(signal_counts, required_signals, "signal_counts")
    for key in required_signals:
        _non_negative_number(signal_counts[key], f"signal_counts.{key}")
    if signal_counts["profiles_analyzed"] <= 0:
        raise HealthValidationError("signal_counts.profiles_analyzed must be positive")
    if signal_counts["profiles_with_diary_dates"] > signal_counts["profiles_analyzed"]:
        raise HealthValidationError(
            "dated profile count cannot exceed analyzed profile count"
        )
    if signal_counts["profiles_analyzed"] > data_health["active_profiles"]:
        raise HealthValidationError(
            "analyzed profile count cannot exceed active profile count"
        )


def validate_rss(payload: Any) -> None:
    report = _object(payload, "RSS health report")
    if report.get("status") != "healthy":
        raise HealthValidationError("RSS status is not healthy")
    if report.get("requires_attention") is not False:
        raise HealthValidationError("RSS health requires attention")
    profiles = _object(report.get("profiles"), "RSS profile counters")
    _require_keys(
        profiles,
        {"active", "configured", "fresh", "stale", "failing"},
        "RSS profile counters",
    )
    for key in ("active", "configured", "fresh", "stale", "failing"):
        _non_negative_number(profiles[key], f"profiles.{key}")
    if not (
        profiles["active"]
        == profiles["configured"]
        == profiles["fresh"]
        > 0
    ):
        raise HealthValidationError(
            "all configured RSS profiles must be active and fresh"
        )
    if profiles["stale"] != 0 or profiles["failing"] != 0:
        raise HealthValidationError("RSS health contains stale or failing profiles")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("ready", "dashboard", "rss"))
    parser.add_argument("--revision", default="")
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
        if args.kind == "ready":
            if not args.revision:
                raise HealthValidationError(
                    "--revision is required for readiness validation"
                )
            validate_ready(payload, args.revision)
        elif args.kind == "dashboard":
            validate_dashboard(payload)
        else:
            validate_rss(payload)
    except (HealthValidationError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"health validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
