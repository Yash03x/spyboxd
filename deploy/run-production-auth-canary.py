#!/usr/bin/env python3
"""Fail-safe Clerk-backed production isolation canary, run on the VPS."""

from __future__ import annotations

import argparse
import ast
import fcntl
import json
import os
import re
import secrets
import signal
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_STATE_BYTES = 64 * 1024
USER_ID_PATTERN = re.compile(r"user_[A-Za-z0-9]+")
PROFILE_PATTERN = re.compile(r"[A-Za-z0-9_]{2,15}")
SESSION_ID_PATTERN = re.compile(r"sess_[A-Za-z0-9]+")
OPAQUE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{8,200}")
LEASE_ID_PATTERN = re.compile(r"gha-[1-9][0-9]{0,19}-[1-9][0-9]{0,9}")
APP_ORIGIN = "https://spyboxd.com"
DEFAULT_API_BASE = "https://api.spyboxd.com"
DEFAULT_SHARED_DIR = Path("/opt/spyboxd/shared")
LEASE_ROOT_NAME = "auth-canary-leases"
STATE_NAME = "state.json"
PLAN_NAME = "plan.json"
DONE_NAME = "done"
STATUS_NAME = "status.json"
LOCK_NAME = ".auth-canary.lock"
LIVE_SESSION_STATUSES = ("active",)
SESSION_MAX_DURATION_SECONDS = 120
SESSION_EXPIRY_GRACE_SECONDS = 5
BROWSER_PLAN_VERSION = 2
BROWSER_CLOSURE_BY_LABEL = {
    "A": "sign_out",
    "B": "session_expiry",
}
DATABASE_STATE_BOOTSTRAP = "bootstrap"
DATABASE_STATE_PROVISIONED = "provisioned"


class AuthCanaryError(RuntimeError):
    pass


class GuardianInterrupted(AuthCanaryError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, request, file_pointer, code, message, headers, new_url  # noqa: ANN001
    ):
        return None


_CLERK_OPENER = urllib.request.build_opener(_NoRedirect)


@dataclass(frozen=True)
class CanaryIdentity:
    label: str
    user_id: str
    profile: str


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]


def _read_secure_env(path: Path) -> dict[str, str]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise AuthCanaryError(
            "a required VPS configuration file is unavailable"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise AuthCanaryError("VPS canary configuration must use regular files")
    if metadata.st_mode & 0o007:
        raise AuthCanaryError("VPS canary configuration must not be world-accessible")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise AuthCanaryError(
            "a required VPS configuration file could not be read"
        ) from exc
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or "=" not in line:
            raise AuthCanaryError(
                f"VPS configuration line {line_number} has an unsupported form"
            )
        key, raw_value = line.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
            raise AuthCanaryError(
                f"VPS configuration line {line_number} has an invalid key"
            )
        if raw_value[:1] in {"'", '"'}:
            try:
                parsed_value = ast.literal_eval(raw_value)
            except (SyntaxError, ValueError) as exc:
                raise AuthCanaryError(
                    f"VPS configuration line {line_number} has invalid quoting"
                ) from exc
            if not isinstance(parsed_value, str):
                raise AuthCanaryError(
                    f"VPS configuration line {line_number} must contain text"
                )
            value = parsed_value
        else:
            if any(character.isspace() for character in raw_value) or "#" in raw_value:
                raise AuthCanaryError(
                    f"VPS configuration line {line_number} must quote complex values"
                )
            value = raw_value
        values[key] = value
    return values


def _require(values: Mapping[str, str], key: str, label: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise AuthCanaryError(f"{label} is missing from VPS configuration")
    return value


def _load_identities(
    canary_values: Mapping[str, str],
) -> tuple[CanaryIdentity, CanaryIdentity]:
    identities = (
        CanaryIdentity(
            "A",
            _require(canary_values, "SPYBOXD_CANARY_USER_A_ID", "canary identity A"),
            _require(canary_values, "SPYBOXD_CANARY_PROFILE_A", "canary profile A"),
        ),
        CanaryIdentity(
            "B",
            _require(canary_values, "SPYBOXD_CANARY_USER_B_ID", "canary identity B"),
            _require(canary_values, "SPYBOXD_CANARY_PROFILE_B", "canary profile B"),
        ),
    )
    for identity in identities:
        if not USER_ID_PATTERN.fullmatch(identity.user_id):
            raise AuthCanaryError(
                f"canary identity {identity.label} has an invalid Clerk ID"
            )
        if not PROFILE_PATTERN.fullmatch(identity.profile):
            raise AuthCanaryError(
                f"canary profile {identity.label} has an invalid Letterboxd username"
            )
    if identities[0].user_id == identities[1].user_id:
        raise AuthCanaryError(
            "authenticated isolation requires two distinct Clerk identities"
        )
    if identities[0].profile.casefold() == identities[1].profile.casefold():
        raise AuthCanaryError("authenticated isolation requires two distinct profiles")
    return identities


def _validate_database_rows(
    identities: tuple[CanaryIdentity, CanaryIdentity],
    identity_rows: Iterable[Mapping[str, Any]],
    tracked_rows: Iterable[Mapping[str, Any]],
    configured_admin_ids: set[str],
    profile_rows: Iterable[Mapping[str, Any]] = (),
    claimed_rows: Iterable[Mapping[str, Any]] = (),
) -> str:
    expected_ids = {identity.user_id for identity in identities}
    if expected_ids & configured_admin_ids:
        raise AuthCanaryError("a configured canary identity is an administrator")

    identity_row_list = list(identity_rows)
    by_user = {str(row["clerk_user_id"]): row for row in identity_row_list}
    if len(identity_row_list) != len(by_user):
        raise AuthCanaryError("the canary identity database state is ambiguous")
    if not by_user:
        expected_profiles = {identity.profile.casefold() for identity in identities}
        profile_row_list = list(profile_rows)
        by_profile: dict[str, Mapping[str, Any]] = {}
        for row in profile_row_list:
            username = row.get("username")
            if not isinstance(username, str):
                raise AuthCanaryError("a bootstrap canary profile is invalid")
            normalized = username.casefold()
            if normalized in by_profile:
                raise AuthCanaryError("the bootstrap canary profile state is ambiguous")
            by_profile[normalized] = row
        if set(by_profile) != expected_profiles:
            raise AuthCanaryError(
                "both bootstrap canary profiles must already exist in Spyboxd"
            )
        for identity in identities:
            row = by_profile[identity.profile.casefold()]
            if (
                row.get("is_active") is not True
                or row.get("scraping_status") != "completed"
            ):
                raise AuthCanaryError(
                    f"bootstrap canary profile {identity.label} is not completed "
                    "and active"
                )
        if list(claimed_rows):
            raise AuthCanaryError(
                "a bootstrap canary profile is already claimed by another "
                "Spyboxd identity"
            )
        if list(tracked_rows):
            raise AuthCanaryError("the bootstrap canary identity state is inconsistent")
        return DATABASE_STATE_BOOTSTRAP

    if set(by_user) != expected_ids:
        raise AuthCanaryError(
            "canary identities must be either both absent or both provisioned "
            "in Spyboxd"
        )

    tracked: dict[str, set[str]] = {identity.user_id: set() for identity in identities}
    for row in tracked_rows:
        user_id = str(row["clerk_user_id"])
        if user_id in tracked:
            tracked[user_id].add(str(row["username"]).casefold())

    for identity in identities:
        row = by_user[identity.user_id]
        if row.get("is_active") is not True:
            raise AuthCanaryError(f"canary identity {identity.label} is not active")
        stored_profile = row.get("letterboxd_username")
        if (
            not isinstance(stored_profile, str)
            or stored_profile.casefold() != identity.profile.casefold()
        ):
            raise AuthCanaryError(
                f"canary identity {identity.label} is not bound to its expected profile"
            )
        if tracked[identity.user_id] != {identity.profile.casefold()}:
            raise AuthCanaryError(
                f"canary identity {identity.label} must track exactly its own profile"
            )
    return DATABASE_STATE_PROVISIONED


def _database_preflight(
    database_url: str,
    identities: tuple[CanaryIdentity, CanaryIdentity],
    configured_admin_ids: set[str],
) -> str:
    try:
        from sqlalchemy import create_engine, text
    except ImportError as exc:
        raise AuthCanaryError(
            "the active backend environment cannot inspect canary identity state"
        ) from exc

    engine = None
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            identity_rows = (
                connection.execute(
                    text(
                        """
                    SELECT clerk_user_id, letterboxd_username, is_active
                    FROM app_users
                    WHERE clerk_user_id IN (:user_a, :user_b)
                    """
                    ),
                    {"user_a": identities[0].user_id, "user_b": identities[1].user_id},
                )
                .mappings()
                .all()
            )
            tracked_rows = (
                connection.execute(
                    text(
                        """
                    SELECT au.clerk_user_id, p.username
                    FROM app_users AS au
                    JOIN user_tracked_profiles AS utp ON utp.user_id = au.id
                    JOIN profiles AS p ON p.id = utp.profile_id
                    WHERE au.clerk_user_id IN (:user_a, :user_b)
                    """
                    ),
                    {"user_a": identities[0].user_id, "user_b": identities[1].user_id},
                )
                .mappings()
                .all()
            )
            profile_rows = (
                connection.execute(
                    text(
                        """
                    SELECT username, is_active, scraping_status
                    FROM profiles
                    WHERE lower(username) IN (:profile_a, :profile_b)
                    """
                    ),
                    {
                        "profile_a": identities[0].profile.casefold(),
                        "profile_b": identities[1].profile.casefold(),
                    },
                )
                .mappings()
                .all()
            )
            claimed_rows = (
                connection.execute(
                    text(
                        """
                    SELECT clerk_user_id, letterboxd_username
                    FROM app_users
                    WHERE lower(letterboxd_username) IN (:profile_a, :profile_b)
                    """
                    ),
                    {
                        "profile_a": identities[0].profile.casefold(),
                        "profile_b": identities[1].profile.casefold(),
                    },
                )
                .mappings()
                .all()
            )
    except Exception as exc:
        raise AuthCanaryError("the canary database preflight failed") from exc
    finally:
        if engine is not None:
            engine.dispose()
    return _validate_database_rows(
        identities,
        identity_rows,
        tracked_rows,
        configured_admin_ids,
        profile_rows,
        claimed_rows,
    )


def _bounded_body(opened: Any) -> bytes:
    body = opened.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise AuthCanaryError("a canary HTTP response exceeded the size limit")
    return body


def _request(
    url: str,
    *,
    method: str = "GET",
    bearer: str | None = None,
    payload: Mapping[str, Any] | None = None,
    clerk_backend: bool = False,
) -> HttpResponse:
    try:
        parsed_url = urllib.parse.urlsplit(url)
        parsed_port = parsed_url.port
    except ValueError as exc:
        raise AuthCanaryError("authenticated canary dependency URL is invalid") from exc
    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname != "api.clerk.com"
        or parsed_port not in {None, 443}
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.fragment
    ):
        raise AuthCanaryError("authenticated canary dependency origin is unexpected")
    headers = {
        "Accept": "application/json",
        "Cache-Control": "no-cache",
        "User-Agent": "spyboxd-production-auth-canary/1",
    }
    body = None
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if clerk_backend:
        headers["Clerk-API-Version"] = "2026-05-12"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        # Safe because the parsed HTTPS origin is pinned to api.clerk.com above.
        opened = _CLERK_OPENER.open(request, timeout=10)
    except urllib.error.HTTPError as exc:
        try:
            return HttpResponse(exc.code, _bounded_body(exc), exc.headers)
        finally:
            exc.close()
    except (OSError, urllib.error.URLError) as exc:
        raise AuthCanaryError(
            "an authenticated canary dependency could not be reached"
        ) from exc
    with opened:
        return HttpResponse(opened.status, _bounded_body(opened), opened.headers)


def _json(response: HttpResponse, label: str, expected_status: int) -> Any:
    if response.status != expected_status:
        raise AuthCanaryError(f"{label} returned HTTP {response.status}")
    try:
        return json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthCanaryError(f"{label} returned invalid JSON") from exc


def _verify_bootstrap_clerk_usernames(
    secret_key: str,
    identities: tuple[CanaryIdentity, CanaryIdentity],
) -> None:
    for identity in identities:
        payload = _json(
            _request(
                "https://api.clerk.com/v1/users/"
                + urllib.parse.quote(identity.user_id, safe=""),
                bearer=secret_key,
                clerk_backend=True,
            ),
            f"Clerk user lookup for bootstrap canary {identity.label}",
            200,
        )
        username = payload.get("username") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("id") != identity.user_id
            or not isinstance(username, str)
            or username.casefold() != identity.profile.casefold()
        ):
            raise AuthCanaryError(
                f"bootstrap canary {identity.label} Clerk username does not "
                "match its configured profile"
            )


def _require_post_browser_provisioning(database_state: str) -> None:
    if database_state != DATABASE_STATE_PROVISIONED:
        raise AuthCanaryError(
            "the browser flow did not provision both canary identities with "
            "one-profile tracking"
        )


def _origin(value: str, label: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise AuthCanaryError(
            f"{label} must be a valid production HTTPS origin"
        ) from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise AuthCanaryError(f"{label} must be a production HTTPS origin")
    return urllib.parse.urlunsplit(("https", parsed.netloc, "", "", ""))


def _error_codes(response: HttpResponse) -> set[str]:
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict) or not isinstance(payload.get("errors"), list):
        return set()
    return {
        error["code"]
        for error in payload["errors"]
        if isinstance(error, dict) and isinstance(error.get("code"), str)
    }


def _retire_agent_task(secret_key: str, agent_task_id: str) -> bool:
    response = _request(
        f"https://api.clerk.com/v1/agents/tasks/{urllib.parse.quote(agent_task_id, safe='')}/revoke",
        method="POST",
        bearer=secret_key,
        clerk_backend=True,
    )
    if response.status == 200:
        return False
    if response.status == 404:
        # The ticket is no longer usable, but it may already have produced a
        # bounded Agent Task session.
        return True
    if response.status == 400 and "agent_task_cannot_be_revoked" in _error_codes(
        response
    ):
        # Clerk only allows pending tasks to be revoked. This exact response proves
        # the one-use task is no longer pending; session cleanup is verified below.
        return True
    raise AuthCanaryError("a Clerk canary task could not be proven inactive")


def _create_agent_task(
    secret_key: str,
    identity: CanaryIdentity,
    *,
    allowed_frontend_origins: set[str],
    app_origin: str,
    record_task_id: Callable[[str], None],
) -> dict[str, str]:
    created = _json(
        _request(
            "https://api.clerk.com/v1/agents/tasks",
            method="POST",
            bearer=secret_key,
            payload={
                "on_behalf_of": {"user_id": identity.user_id},
                "permissions": "*",
                "agent_name": "spyboxd-production-canary",
                "task_description": "Read-only non-admin privacy and isolation check",
                # Land on the only public application route first. Clerk's
                # frontend SDK must finish the Agent Task handoff and write the
                # app-scoped session token before middleware can admit the
                # browser to a protected route.
                "redirect_url": f"{app_origin}/",
                "session_max_duration_in_seconds": SESSION_MAX_DURATION_SECONDS,
            },
            clerk_backend=True,
        ),
        f"Clerk agent task creation for canary {identity.label}",
        200,
    )
    task_id = created.get("agent_task_id") if isinstance(created, dict) else None
    if not isinstance(task_id, str) or not OPAQUE_ID_PATTERN.fullmatch(task_id):
        raise AuthCanaryError(
            f"Clerk returned an invalid agent task for canary {identity.label}"
        )

    # Persist the cleanup handle before validating or exporting the one-time URL.
    record_task_id(task_id)
    task_url = created.get("url") if isinstance(created, dict) else None
    if not isinstance(task_url, str):
        raise AuthCanaryError(
            f"Clerk omitted the agent task URL for canary {identity.label}"
        )
    try:
        parsed_task = urllib.parse.urlsplit(task_url)
        _ = parsed_task.port
    except ValueError as exc:
        raise AuthCanaryError(
            f"Clerk returned an invalid task URL for canary {identity.label}"
        ) from exc
    task_origin = urllib.parse.urlunsplit(
        (parsed_task.scheme, parsed_task.netloc, "", "", "")
    )
    if (
        parsed_task.scheme != "https"
        or not parsed_task.hostname
        or parsed_task.username is not None
        or parsed_task.password is not None
        or parsed_task.fragment
        or task_origin not in allowed_frontend_origins
    ):
        raise AuthCanaryError(
            f"Clerk returned an unsafe task URL for canary {identity.label}"
        )
    return {
        "label": identity.label,
        "user_id": identity.user_id,
        "profile": identity.profile,
        "task_url": task_url,
        "task_origin": task_origin,
    }


def _build_browser_plan(
    *,
    api_base: str,
    app_origin: str,
    task_origin: str,
    tasks: list[Mapping[str, Any]],
) -> dict[str, Any]:
    if len(tasks) != len(BROWSER_CLOSURE_BY_LABEL):
        raise AuthCanaryError("authenticated browser plan requires exactly two tasks")

    planned_tasks: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for task in tasks:
        label = task.get("label")
        if not isinstance(label, str):
            raise AuthCanaryError("authenticated browser plan has invalid task labels")
        closure = BROWSER_CLOSURE_BY_LABEL.get(label)
        if closure is None or label in seen_labels:
            raise AuthCanaryError("authenticated browser plan has invalid task labels")
        if task.get("task_origin") != task_origin:
            raise AuthCanaryError(
                "authenticated browser plan has inconsistent task origins"
            )
        seen_labels.add(label)
        planned_tasks.append(
            {
                **{key: value for key, value in task.items() if key != "task_origin"},
                "closure": closure,
            }
        )

    if seen_labels != set(BROWSER_CLOSURE_BY_LABEL):
        raise AuthCanaryError("authenticated browser plan is missing a task label")
    return {
        "version": BROWSER_PLAN_VERSION,
        "api_base": api_base,
        "app_origin": app_origin,
        "task_origin": task_origin,
        "session_max_duration_seconds": SESSION_MAX_DURATION_SECONDS,
        "tasks": planned_tasks,
    }


def _list_sessions(
    secret_key: str, user_id: str, status_filter: str
) -> list[dict[str, Any]]:
    limit = 100
    query = urllib.parse.urlencode(
        {
            "user_id": user_id,
            "status": status_filter,
            "limit": limit,
            "paginated": "true",
        }
    )
    payload = _json(
        _request(
            f"https://api.clerk.com/v1/sessions?{query}",
            bearer=secret_key,
            clerk_backend=True,
        ),
        "Clerk canary session listing",
        200,
    )
    if not isinstance(payload, dict):
        raise AuthCanaryError("Clerk returned an invalid session list")
    raw_sessions = payload.get("data")
    total_count = payload.get("total_count")
    if (
        not isinstance(raw_sessions, list)
        or isinstance(total_count, bool)
        or not isinstance(total_count, int)
        or total_count < 0
    ):
        raise AuthCanaryError("Clerk returned an invalid session list")
    if total_count != len(raw_sessions):
        raise AuthCanaryError("Clerk returned an ambiguous paginated session list")
    if total_count >= limit:
        raise AuthCanaryError("a dedicated canary user has too many sessions")
    sessions: list[dict[str, Any]] = []
    for item in raw_sessions:
        if not isinstance(item, dict):
            raise AuthCanaryError("Clerk returned an invalid session entry")
        session_id = item.get("id")
        if (
            not isinstance(session_id, str)
            or not SESSION_ID_PATTERN.fullmatch(session_id)
            or item.get("user_id") != user_id
            or item.get("status") != status_filter
        ):
            raise AuthCanaryError("Clerk returned an unexpected canary session")
        sessions.append(item)
    return sessions


def _list_live_sessions(secret_key: str, user_id: str) -> set[str]:
    live: set[str] = set()
    for status_filter in LIVE_SESSION_STATUSES:
        live.update(
            str(session["id"])
            for session in _list_sessions(secret_key, user_id, status_filter)
        )
    return live


def _require_zero_live_sessions(
    secret_key: str, identities: tuple[CanaryIdentity, CanaryIdentity]
) -> None:
    for identity in identities:
        if _list_live_sessions(secret_key, identity.user_id):
            raise AuthCanaryError(
                f"dedicated canary identity {identity.label} already has a live session"
            )


def _revoke_session(secret_key: str, session_id: str) -> None:
    response = _request(
        f"https://api.clerk.com/v1/sessions/{urllib.parse.quote(session_id, safe='')}/revoke",
        method="POST",
        bearer=secret_key,
        clerk_backend=True,
    )
    if response.status in {200, 404}:
        return
    raise AuthCanaryError("a temporary Clerk canary session could not be revoked")


def _state_identities(
    state: Mapping[str, Any],
) -> tuple[CanaryIdentity, CanaryIdentity]:
    raw_identities = state.get("identities")
    if not isinstance(raw_identities, list) or len(raw_identities) != 2:
        raise AuthCanaryError("stored authenticated canary identities are invalid")
    identities: list[CanaryIdentity] = []
    for raw in raw_identities:
        if not isinstance(raw, dict):
            raise AuthCanaryError("stored authenticated canary identities are invalid")
        identity = CanaryIdentity(
            str(raw.get("label", "")),
            str(raw.get("user_id", "")),
            str(raw.get("profile", "")),
        )
        if (
            identity.label not in {"A", "B"}
            or not USER_ID_PATTERN.fullmatch(identity.user_id)
            or not PROFILE_PATTERN.fullmatch(identity.profile)
        ):
            raise AuthCanaryError("stored authenticated canary identities are invalid")
        identities.append(identity)
    if {identity.label for identity in identities} != {"A", "B"}:
        raise AuthCanaryError("stored authenticated canary identities are duplicated")
    identities.sort(key=lambda identity: identity.label)
    return identities[0], identities[1]


def _state_task_ids(state: Mapping[str, Any]) -> list[str]:
    task_ids = state.get("task_ids")
    if (
        not isinstance(task_ids, list)
        or len(task_ids) > 2
        or any(
            not isinstance(task_id, str) or not OPAQUE_ID_PATTERN.fullmatch(task_id)
            for task_id in task_ids
        )
        or len(set(task_ids)) != len(task_ids)
    ):
        raise AuthCanaryError("stored authenticated canary task IDs are invalid")
    return task_ids


def _cleanup_state(secret_key: str, state: Mapping[str, Any]) -> None:
    identities = _state_identities(state)
    task_ids = _state_task_ids(state)
    baseline_zero = state.get("session_baseline_proven_zero") is True
    if task_ids and not baseline_zero:
        raise AuthCanaryError("stored task state lacks a proven clean session baseline")

    cleanup_errors: list[Exception] = []
    expiry_guard_required = False
    # Retire one-use capabilities first, preventing a pending ticket from racing
    # the authoritative server-side session sweep.
    for task_id in task_ids:
        try:
            expiry_guard_required = (
                _retire_agent_task(secret_key, task_id) or expiry_guard_required
            )
        except Exception as exc:  # noqa: BLE001 - cleanup must attempt every resource
            cleanup_errors.append(exc)

    if baseline_zero:
        live_sessions: set[str] = set()
        session_listing_failed = False
        for identity in identities:
            try:
                live_sessions.update(_list_live_sessions(secret_key, identity.user_id))
            except Exception as exc:  # noqa: BLE001 - cleanup continues after one API failure
                cleanup_errors.append(exc)
                session_listing_failed = True
        for session_id in sorted(live_sessions):
            try:
                _revoke_session(secret_key, session_id)
            except Exception as exc:  # noqa: BLE001 - cleanup continues after one API failure
                cleanup_errors.append(exc)

        if expiry_guard_required:
            # Clerk guarantees these Agent Task sessions cannot outlive this
            # ceiling. Waiting after every ticket is no longer pending closes
            # the list-sessions visibility race even if the first samples lag.
            time.sleep(SESSION_MAX_DURATION_SECONDS + SESSION_EXPIRY_GRACE_SECONDS)

        # Require two consecutive empty server-side samples. If consumption won
        # a race with task retirement, a newly visible session is revoked here.
        empty_samples = 0
        for sample in range(4) if not session_listing_failed else ():
            remaining: set[str] = set()
            sample_failed = False
            for identity in identities:
                try:
                    remaining.update(_list_live_sessions(secret_key, identity.user_id))
                except Exception as exc:  # noqa: BLE001 - collect every failure
                    cleanup_errors.append(exc)
                    sample_failed = True
            if sample_failed:
                break
            if remaining:
                empty_samples = 0
                for session_id in sorted(remaining):
                    try:
                        _revoke_session(secret_key, session_id)
                    except Exception as exc:  # noqa: BLE001 - keep proving cleanup
                        cleanup_errors.append(exc)
            else:
                empty_samples += 1
                if empty_samples >= 2:
                    break
            if sample < 3:
                time.sleep(0.5)
        if empty_samples < 2:
            cleanup_errors.append(
                AuthCanaryError("temporary Clerk sessions remain live")
            )

    if cleanup_errors:
        raise AuthCanaryError(
            "temporary Clerk canary state could not be proven inactive"
        )


def _guardian_result_status(
    primary_error: BaseException | None,
    cleanup_error: BaseException | None,
) -> str:
    if cleanup_error is not None:
        return "cleanup_failed"
    if primary_error is not None:
        return "failed"
    return "passed"


def _validate_lease_id(lease_id: str) -> str:
    if not LEASE_ID_PATTERN.fullmatch(lease_id):
        raise AuthCanaryError("authenticated canary lease ID is invalid")
    return lease_id


def _secure_directory(path: Path, *, mode: int, create: bool = False) -> None:
    if create:
        try:
            path.mkdir(mode=mode, exist_ok=True)
        except OSError as exc:
            raise AuthCanaryError("authenticated canary state is unavailable") from exc
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise AuthCanaryError("authenticated canary state is unavailable") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
    ):
        raise AuthCanaryError("authenticated canary state directory is unsafe")
    if stat.S_IMODE(metadata.st_mode) != mode and (
        path.name == LEASE_ROOT_NAME or LEASE_ID_PATTERN.fullmatch(path.name)
    ):
        raise AuthCanaryError("authenticated canary lease directory has unsafe mode")


def _lease_root(shared_dir: Path) -> Path:
    _secure_directory(shared_dir, mode=0o750)
    root = shared_dir / LEASE_ROOT_NAME
    _secure_directory(root, mode=0o700, create=True)
    return root


def _lease_directory(shared_dir: Path, lease_id: str) -> Path:
    return _lease_root(shared_dir) / _validate_lease_id(lease_id)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    if len(encoded) > MAX_STATE_BYTES:
        raise AuthCanaryError("authenticated canary state is too large")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}")
    descriptor = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as opened:
            descriptor = None
            opened.write(encoded)
            opened.flush()
            os.fsync(opened.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise AuthCanaryError(
            "authenticated canary state could not be persisted"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _read_private_json(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise AuthCanaryError("authenticated canary state is missing") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
        or metadata.st_size > MAX_STATE_BYTES
    ):
        raise AuthCanaryError("authenticated canary state file is unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthCanaryError("authenticated canary state is invalid") from exc
    if not isinstance(payload, dict):
        raise AuthCanaryError("authenticated canary state is invalid")
    return payload


def _safe_unlink(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise AuthCanaryError(
            "authenticated canary state could not be inspected"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise AuthCanaryError("refusing to remove unsafe authenticated canary state")
    try:
        path.unlink()
    except OSError as exc:
        raise AuthCanaryError(
            "authenticated canary state could not be removed"
        ) from exc


def _remove_completed_lease(lease_dir: Path) -> None:
    for name in (PLAN_NAME, DONE_NAME, STATE_NAME, STATUS_NAME):
        _safe_unlink(lease_dir / name)
    unexpected = list(lease_dir.iterdir())
    if unexpected:
        raise AuthCanaryError("authenticated canary lease contains unexpected files")
    try:
        lease_dir.rmdir()
    except OSError as exc:
        raise AuthCanaryError(
            "authenticated canary lease could not be removed"
        ) from exc


@contextmanager
def _exclusive_guardian_lock(shared_dir: Path) -> Iterator[None]:
    root = _lease_root(shared_dir)
    lock_path = root / LOCK_NAME
    descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise AuthCanaryError("authenticated canary lock is unsafe")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AuthCanaryError(
                "another authenticated canary guardian is still active"
            ) from exc
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _load_secret(frontend_env: Path) -> str:
    frontend_values = _read_secure_env(frontend_env)
    secret_key = _require(
        frontend_values, "CLERK_SECRET_KEY", "production Clerk secret"
    )
    if not secret_key.startswith("sk_live_"):
        raise AuthCanaryError("authenticated canary requires a production Clerk secret")
    return secret_key


def _cleanup_stored_lease(lease_dir: Path, secret_key: str) -> None:
    # Never retain the one-use URL, including when Clerk cleanup is unavailable.
    _safe_unlink(lease_dir / PLAN_NAME)
    _safe_unlink(lease_dir / DONE_NAME)
    state_path = lease_dir / STATE_NAME
    state = _read_private_json(state_path)
    try:
        _cleanup_state(secret_key, state)
    except Exception:
        state["phase"] = "cleanup_failed"
        _write_private_json(state_path, state)
        raise
    _safe_unlink(state_path)


def _sweep_stale_leases(root: Path, secret_key: str) -> None:
    for lease_dir in sorted(root.iterdir()):
        if lease_dir.name == LOCK_NAME:
            continue
        metadata = lease_dir.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or not LEASE_ID_PATTERN.fullmatch(lease_dir.name)
        ):
            raise AuthCanaryError("authenticated canary lease root is unsafe")
        state_path = lease_dir / STATE_NAME
        if state_path.exists():
            _cleanup_stored_lease(lease_dir, secret_key)
        _remove_completed_lease(lease_dir)


def _done_requested(lease_dir: Path) -> bool:
    path = lease_dir / DONE_NAME
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise AuthCanaryError(
            "authenticated canary completion marker is unavailable"
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
    ):
        raise AuthCanaryError("authenticated canary completion marker is unsafe")
    return True


def _signal_handler(signum: int, _frame: Any) -> None:
    raise GuardianInterrupted(f"authenticated canary guardian received signal {signum}")


def run_guardian(
    *,
    lease_id: str,
    max_wait_seconds: int,
    api_base: str,
    api_env: Path,
    frontend_env: Path,
    canary_env: Path,
    shared_dir: Path,
) -> bool:
    if not 30 <= max_wait_seconds <= 600:
        raise AuthCanaryError("authenticated canary guardian timeout is invalid")
    lease_id = _validate_lease_id(lease_id)
    api_base = _origin(api_base, "authenticated canary API")
    if api_base != DEFAULT_API_BASE:
        raise AuthCanaryError("authenticated canary API origin is unexpected")

    api_values = _read_secure_env(api_env)
    frontend_values = _read_secure_env(frontend_env)
    canary_values = _read_secure_env(canary_env)
    database_url = _require(api_values, "DATABASE_URL", "production database URL")
    secret_key = _require(
        frontend_values, "CLERK_SECRET_KEY", "production Clerk secret"
    )
    if not secret_key.startswith("sk_live_"):
        raise AuthCanaryError("authenticated canary requires a production Clerk secret")
    identities = _load_identities(canary_values)
    configured_frontend_urls = {
        api_values.get("CLERK_FRONTEND_API", "").strip(),
        api_values.get("CLERK_ISSUER", "").strip(),
    }
    allowed_frontend_origins = {
        _origin(value, "configured Clerk frontend origin")
        for value in configured_frontend_urls
        if value
    }
    if not allowed_frontend_origins:
        raise AuthCanaryError("a configured Clerk frontend origin is required")
    configured_admin_ids = {
        value.strip()
        for value in api_values.get("CLERK_ADMIN_USER_IDS", "").split(",")
        if value.strip()
    }

    with _exclusive_guardian_lock(shared_dir):
        root = _lease_root(shared_dir)
        _sweep_stale_leases(root, secret_key)
        lease_dir = root / lease_id
        try:
            lease_dir.mkdir(mode=0o700)
        except OSError as exc:
            raise AuthCanaryError(
                "authenticated canary lease could not be created"
            ) from exc
        _secure_directory(lease_dir, mode=0o700)

        state: dict[str, Any] = {
            "version": 1,
            "lease_id": lease_id,
            "phase": "preflight",
            "session_baseline_proven_zero": False,
            "identities": [
                {
                    "label": identity.label,
                    "user_id": identity.user_id,
                    "profile": identity.profile,
                }
                for identity in identities
            ],
            "task_ids": [],
        }
        state_path = lease_dir / STATE_NAME
        _write_private_json(state_path, state)
        primary_error: BaseException | None = None
        cleanup_error: BaseException | None = None
        previous_handlers: dict[signal.Signals, Any] = {}
        for signal_number in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
            previous_handlers[signal_number] = signal.signal(
                signal_number, _signal_handler
            )
        try:
            database_state = _database_preflight(
                database_url, identities, configured_admin_ids
            )
            if database_state == DATABASE_STATE_BOOTSTRAP:
                _verify_bootstrap_clerk_usernames(secret_key, identities)
            _require_zero_live_sessions(secret_key, identities)
            state["session_baseline_proven_zero"] = True
            state["phase"] = "creating_tasks"
            _write_private_json(state_path, state)

            def record_task_id(task_id: str) -> None:
                state["task_ids"].append(task_id)
                _write_private_json(state_path, state)

            tasks = [
                _create_agent_task(
                    secret_key,
                    identity,
                    allowed_frontend_origins=allowed_frontend_origins,
                    app_origin=APP_ORIGIN,
                    record_task_id=record_task_id,
                )
                for identity in identities
            ]
            task_origins = {task.get("task_origin") for task in tasks}
            if len(task_origins) != 1:
                raise AuthCanaryError("Clerk returned inconsistent task origins")
            plan = _build_browser_plan(
                api_base=api_base,
                app_origin=APP_ORIGIN,
                task_origin=next(iter(task_origins)),
                tasks=tasks,
            )
            state["phase"] = "waiting_for_browser"
            _write_private_json(state_path, state)
            _write_private_json(lease_dir / PLAN_NAME, plan)

            deadline = time.monotonic() + max_wait_seconds
            while not _done_requested(lease_dir):
                if time.monotonic() >= deadline:
                    raise AuthCanaryError(
                        "authenticated browser canary did not finish before its deadline"
                    )
                time.sleep(0.5)
            state["phase"] = "verifying_database_provisioning"
            _write_private_json(state_path, state)
            _require_post_browser_provisioning(
                _database_preflight(database_url, identities, configured_admin_ids)
            )
        except BaseException as exc:  # noqa: BLE001 - signals must enter the cleanup path
            primary_error = exc
        finally:
            # Once shutdown starts, finish cleanup even if SSH disconnects send
            # another HUP/TERM. The original handlers are restored afterwards.
            for signal_number in previous_handlers:
                signal.signal(signal_number, signal.SIG_IGN)
            cleanup_failures: list[BaseException] = []
            try:
                for path in (lease_dir / PLAN_NAME, lease_dir / DONE_NAME):
                    try:
                        _safe_unlink(path)
                    except BaseException as exc:  # noqa: BLE001 - keep cleaning
                        cleanup_failures.append(exc)
                try:
                    _cleanup_state(secret_key, state)
                except BaseException as exc:  # noqa: BLE001 - retain failure state
                    cleanup_failures.append(exc)

                if not cleanup_failures:
                    try:
                        _safe_unlink(state_path)
                    except BaseException as exc:  # noqa: BLE001 - retain failure state
                        cleanup_failures.append(exc)
                if cleanup_failures:
                    cleanup_error = cleanup_failures[0]
                    state["phase"] = "cleanup_failed"
                    _write_private_json(state_path, state)

                status = _guardian_result_status(primary_error, cleanup_error)
                _write_private_json(
                    lease_dir / STATUS_NAME, {"version": 1, "status": status}
                )
            finally:
                for signal_number, previous in previous_handlers.items():
                    signal.signal(signal_number, previous)

        if cleanup_error is not None:
            raise AuthCanaryError(
                "authenticated canary cleanup could not be proven"
            ) from cleanup_error
        if primary_error is not None:
            if isinstance(primary_error, AuthCanaryError):
                raise primary_error
            raise AuthCanaryError(
                "authenticated canary guardian failed"
            ) from primary_error
        return True


def signal_completion(*, lease_id: str, shared_dir: Path) -> None:
    lease_dir = _lease_directory(shared_dir, lease_id)
    _secure_directory(lease_dir, mode=0o700)
    marker = lease_dir / DONE_NAME
    try:
        descriptor = os.open(
            marker,
            os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.close(descriptor)
    except OSError as exc:
        raise AuthCanaryError(
            "authenticated canary completion could not be signalled"
        ) from exc


def lease_status(*, lease_id: str, shared_dir: Path) -> str:
    lease_dir = _lease_directory(shared_dir, lease_id)
    try:
        metadata = lease_dir.lstat()
    except FileNotFoundError:
        return "absent"
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise AuthCanaryError("authenticated canary lease is unsafe")
    status_path = lease_dir / STATUS_NAME
    if not status_path.exists():
        return "running"
    payload = _read_private_json(status_path)
    status_value = payload.get("status")
    if payload.get("version") != 1 or status_value not in {
        "passed",
        "failed",
        "cleanup_failed",
    }:
        raise AuthCanaryError("authenticated canary status is invalid")
    return str(status_value)


def cleanup_lease(*, lease_id: str, frontend_env: Path, shared_dir: Path) -> None:
    lease_id = _validate_lease_id(lease_id)
    with _exclusive_guardian_lock(shared_dir):
        lease_dir = _lease_root(shared_dir) / lease_id
        if not lease_dir.exists():
            return
        _secure_directory(lease_dir, mode=0o700)
        state_path = lease_dir / STATE_NAME
        if state_path.exists():
            secret_key = _load_secret(frontend_env)
            _cleanup_stored_lease(lease_dir, secret_key)
        _remove_completed_lease(lease_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    guard = commands.add_parser("guard")
    guard.add_argument("--lease-id", required=True)
    guard.add_argument("--max-wait-seconds", type=int, default=300)
    guard.add_argument("--api-base", default=DEFAULT_API_BASE)
    guard.add_argument("--api-env", type=Path, default=Path("/etc/spyboxd/api.env"))
    guard.add_argument(
        "--frontend-env", type=Path, default=Path("/etc/spyboxd/frontend.env")
    )
    guard.add_argument(
        "--canary-env", type=Path, default=Path("/etc/spyboxd/canary.env")
    )
    guard.add_argument("--shared-dir", type=Path, default=DEFAULT_SHARED_DIR)

    complete = commands.add_parser("complete")
    complete.add_argument("--lease-id", required=True)
    complete.add_argument("--shared-dir", type=Path, default=DEFAULT_SHARED_DIR)

    status_command = commands.add_parser("status")
    status_command.add_argument("--lease-id", required=True)
    status_command.add_argument("--shared-dir", type=Path, default=DEFAULT_SHARED_DIR)

    cleanup = commands.add_parser("cleanup")
    cleanup.add_argument("--lease-id", required=True)
    cleanup.add_argument(
        "--frontend-env", type=Path, default=Path("/etc/spyboxd/frontend.env")
    )
    cleanup.add_argument("--shared-dir", type=Path, default=DEFAULT_SHARED_DIR)

    args = parser.parse_args()
    try:
        if args.command == "guard":
            run_guardian(
                lease_id=args.lease_id,
                max_wait_seconds=args.max_wait_seconds,
                api_base=args.api_base,
                api_env=args.api_env,
                frontend_env=args.frontend_env,
                canary_env=args.canary_env,
                shared_dir=args.shared_dir,
            )
            print("authenticated production canary guardian passed")
        elif args.command == "complete":
            signal_completion(lease_id=args.lease_id, shared_dir=args.shared_dir)
        elif args.command == "status":
            print(lease_status(lease_id=args.lease_id, shared_dir=args.shared_dir))
        else:
            cleanup_lease(
                lease_id=args.lease_id,
                frontend_env=args.frontend_env,
                shared_dir=args.shared_dir,
            )
            print("authenticated production canary cleanup passed")
    except AuthCanaryError as exc:
        print(f"authenticated production canary failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
