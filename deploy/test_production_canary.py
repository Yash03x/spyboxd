from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

DEPLOY_DIR = Path(__file__).resolve().parent


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, DEPLOY_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


public_canary = _load_module("spyboxd_public_canary_test", "run-production-canary.py")
auth_canary = _load_module("spyboxd_auth_canary_test", "run-production-auth-canary.py")


SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
REVISION = "a" * 40


def _json_response(payload, status: int = 200, headers: dict[str, str] | None = None):
    return public_canary.Response(
        status,
        {
            **SECURITY_HEADERS,
            "Content-Type": "application/json",
            **(headers or {}),
        },
        json.dumps(payload).encode("utf-8"),
    )


def _html_response(markers: str):
    body = f"<!doctype html><title>Spyboxd</title>{markers}".ljust(1500, " ").encode(
        "utf-8"
    )
    return public_canary.Response(
        200,
        {**SECURITY_HEADERS, "Content-Type": "text/html; charset=utf-8"},
        body,
    )


def _good_dashboard():
    return {
        "activity_data": [],
        "data_health": {
            "active_profiles": 2,
            "completed_profiles": 2,
            "last_synced_at": "2026-07-31T00:00:00Z",
        },
        "rating_distribution": {},
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
            "global_avg_rating": 3.5,
            "total_movies_tracked": 10,
            "total_profiles": 2,
            "total_reviews": 4,
        },
        "timestamp": "2026-07-31T00:00:00Z",
        "future_additive_field": {"accepted": True},
    }


class FakeClient:
    def __init__(self, responses):
        self.responses = responses

    def get(self, url: str):
        return self.responses[url]


def _good_responses():
    web = "https://spyboxd.com"
    api = "https://api.spyboxd.com"
    responses = {
        f"{api}/ready": _json_response(
            {
                "status": "ready",
                "revision": REVISION,
                "checks": {"database": "ok", "schema": "current"},
            }
        ),
        f"{api}/api/public/dashboard": _json_response(_good_dashboard()),
        f"{api}/health/rss": _json_response(
            {
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
        ),
        f"{web}/": _html_response("Spyboxd Letterboxd"),
        f"{web}/sign-in": _html_response("Spyboxd Clerk sign-in"),
    }
    for path in public_canary.PRIVATE_UI_PATHS:
        responses[f"{web}{path}"] = public_canary.Response(
            307,
            {
                **SECURITY_HEADERS,
                "Location": f"{web}/sign-in?redirect_url={web.replace(':', '%3A').replace('/', '%2F')}%2F{path.lstrip('/').replace('/', '%2F')}",
            },
            b"",
        )
    for path in public_canary.PRIVATE_API_PATHS:
        responses[f"{api}{path}"] = _json_response(
            {"detail": "Missing authorization token"},
            status=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return responses


class ProductionCanaryTests(unittest.TestCase):
    def test_complete_public_and_privacy_contract_accepts_additive_dashboard_fields(
        self,
    ):
        result = public_canary.run_canary(
            web_base="https://spyboxd.com",
            api_base="https://api.spyboxd.com",
            validator_path=DEPLOY_DIR / "check-runtime-health.py",
            client=FakeClient(_good_responses()),
        )
        self.assertEqual(result["revision"], REVISION)
        self.assertEqual(result["private_ui_routes"], 7)
        self.assertEqual(result["private_api_routes"], 20)

    def test_private_route_open_redirect_is_rejected(self):
        responses = _good_responses()
        responses["https://spyboxd.com/dashboard"] = public_canary.Response(
            307,
            {
                **SECURITY_HEADERS,
                "Location": "https://evil.example/sign-in?redirect_url=https://spyboxd.com/dashboard",
            },
            b"",
        )
        with self.assertRaisesRegex(
            public_canary.CanaryError, "outside the production sign-in route"
        ):
            public_canary.run_canary(
                web_base="https://spyboxd.com",
                api_base="https://api.spyboxd.com",
                validator_path=DEPLOY_DIR / "check-runtime-health.py",
                client=FakeClient(responses),
            )

    def test_anonymous_private_api_data_leak_is_rejected(self):
        responses = _good_responses()
        responses["https://api.spyboxd.com/profiles/"] = _json_response(
            {"profiles": [{"username": "leaked"}]}
        )
        with self.assertRaisesRegex(public_canary.CanaryError, "returned HTTP 200"):
            public_canary.run_canary(
                web_base="https://spyboxd.com",
                api_base="https://api.spyboxd.com",
                validator_path=DEPLOY_DIR / "check-runtime-health.py",
                client=FakeClient(responses),
            )

    def test_degraded_http_200_rss_payload_is_rejected(self):
        responses = _good_responses()
        responses["https://api.spyboxd.com/health/rss"] = _json_response(
            {
                "status": "degraded",
                "requires_attention": True,
                "profiles": {
                    "active": 2,
                    "configured": 2,
                    "fresh": 1,
                    "stale": 1,
                    "failing": 0,
                },
            }
        )
        with self.assertRaisesRegex(public_canary.CanaryError, "semantic health"):
            public_canary.run_canary(
                web_base="https://spyboxd.com",
                api_base="https://api.spyboxd.com",
                validator_path=DEPLOY_DIR / "check-runtime-health.py",
                client=FakeClient(responses),
            )

    def test_auth_canary_preflight_rejects_cross_user_tracking(self):
        identities = (
            auth_canary.CanaryIdentity("A", "user_A123", "alpha"),
            auth_canary.CanaryIdentity("B", "user_B123", "beta"),
        )
        identity_rows = [
            {
                "clerk_user_id": "user_A123",
                "letterboxd_username": "alpha",
                "is_active": True,
            },
            {
                "clerk_user_id": "user_B123",
                "letterboxd_username": "beta",
                "is_active": True,
            },
        ]
        tracked_rows = [
            {"clerk_user_id": "user_A123", "username": "alpha"},
            {"clerk_user_id": "user_A123", "username": "beta"},
            {"clerk_user_id": "user_B123", "username": "beta"},
        ]
        with self.assertRaisesRegex(auth_canary.AuthCanaryError, "track exactly"):
            auth_canary._validate_database_rows(
                identities, identity_rows, tracked_rows, set()
            )

    def test_auth_canary_preflight_accepts_two_distinct_ordinary_identities(self):
        identities = (
            auth_canary.CanaryIdentity("A", "user_A123", "alpha"),
            auth_canary.CanaryIdentity("B", "user_B123", "beta"),
        )
        self.assertEqual(
            auth_canary._validate_database_rows(
                identities,
                [
                    {
                        "clerk_user_id": "user_A123",
                        "letterboxd_username": "Alpha",
                        "is_active": True,
                    },
                    {
                        "clerk_user_id": "user_B123",
                        "letterboxd_username": "Beta",
                        "is_active": True,
                    },
                ],
                [
                    {"clerk_user_id": "user_A123", "username": "Alpha"},
                    {"clerk_user_id": "user_B123", "username": "Beta"},
                ],
                set(),
            ),
            auth_canary.DATABASE_STATE_PROVISIONED,
        )

    def test_auth_canary_first_run_accepts_two_completed_unclaimed_profiles(self):
        identities = (
            auth_canary.CanaryIdentity("A", "user_A123", "alpha"),
            auth_canary.CanaryIdentity("B", "user_B123", "beta"),
        )
        self.assertEqual(
            auth_canary._validate_database_rows(
                identities,
                [],
                [],
                set(),
                [
                    {
                        "username": "Alpha",
                        "is_active": True,
                        "scraping_status": "completed",
                    },
                    {
                        "username": "Beta",
                        "is_active": True,
                        "scraping_status": "completed",
                    },
                ],
                [],
            ),
            auth_canary.DATABASE_STATE_BOOTSTRAP,
        )

    def test_auth_canary_first_run_rejects_partial_incomplete_or_claimed_state(self):
        identities = (
            auth_canary.CanaryIdentity("A", "user_A123", "alpha"),
            auth_canary.CanaryIdentity("B", "user_B123", "beta"),
        )
        completed_profiles = [
            {
                "username": "alpha",
                "is_active": True,
                "scraping_status": "completed",
            },
            {
                "username": "beta",
                "is_active": True,
                "scraping_status": "completed",
            },
        ]
        with self.assertRaisesRegex(auth_canary.AuthCanaryError, "both absent"):
            auth_canary._validate_database_rows(
                identities,
                [
                    {
                        "clerk_user_id": "user_A123",
                        "letterboxd_username": "alpha",
                        "is_active": True,
                    }
                ],
                [{"clerk_user_id": "user_A123", "username": "alpha"}],
                set(),
                completed_profiles,
                [],
            )
        with self.assertRaisesRegex(auth_canary.AuthCanaryError, "not completed"):
            auth_canary._validate_database_rows(
                identities,
                [],
                [],
                set(),
                [
                    {**completed_profiles[0], "scraping_status": "pending"},
                    completed_profiles[1],
                ],
                [],
            )
        with self.assertRaisesRegex(auth_canary.AuthCanaryError, "already claimed"):
            auth_canary._validate_database_rows(
                identities,
                [],
                [],
                set(),
                completed_profiles,
                [
                    {
                        "clerk_user_id": "user_someone_else",
                        "letterboxd_username": "alpha",
                    }
                ],
            )

    def test_auth_canary_bootstrap_verifies_clerk_usernames(self):
        identities = (
            auth_canary.CanaryIdentity("A", "user_A123", "alpha"),
            auth_canary.CanaryIdentity("B", "user_B123", "beta"),
        )
        responses = [
            auth_canary.HttpResponse(
                200,
                json.dumps({"id": "user_A123", "username": "Alpha"}).encode(),
                {},
            ),
            auth_canary.HttpResponse(
                200,
                json.dumps({"id": "user_B123", "username": "Beta"}).encode(),
                {},
            ),
        ]
        with mock.patch.object(
            auth_canary, "_request", side_effect=responses
        ) as request:
            auth_canary._verify_bootstrap_clerk_usernames("sk_live_test", identities)
        self.assertEqual(request.call_count, 2)
        self.assertTrue(
            all(call.kwargs["clerk_backend"] for call in request.call_args_list)
        )

        responses[1] = auth_canary.HttpResponse(
            200,
            json.dumps({"id": "user_B123", "username": "someone_else"}).encode(),
            {},
        )
        with (
            mock.patch.object(auth_canary, "_request", side_effect=responses),
            self.assertRaisesRegex(auth_canary.AuthCanaryError, "does not match"),
        ):
            auth_canary._verify_bootstrap_clerk_usernames("sk_live_test", identities)

    def test_auth_canary_requires_provisioned_database_state_after_browser(self):
        auth_canary._require_post_browser_provisioning(
            auth_canary.DATABASE_STATE_PROVISIONED
        )
        with self.assertRaisesRegex(auth_canary.AuthCanaryError, "did not provision"):
            auth_canary._require_post_browser_provisioning(
                auth_canary.DATABASE_STATE_BOOTSTRAP
            )

    def test_authenticated_workflow_stages_and_deletes_ephemeral_identity_config(self):
        workflow = (
            DEPLOY_DIR.parent / ".github" / "workflows" / "production-canary.yml"
        ).read_text(encoding="utf-8")
        for name in (
            "SPYBOXD_CANARY_USER_A_ID",
            "SPYBOXD_CANARY_PROFILE_A",
            "SPYBOXD_CANARY_USER_B_ID",
            "SPYBOXD_CANARY_PROFILE_B",
        ):
            self.assertIn(f"secrets.{name}", workflow)
        self.assertIn('local_env="${RUNNER_TEMP}/spyboxd-auth-canary.env"', workflow)
        self.assertIn('--canary-env "${canary_env_path}"', workflow)
        self.assertIn("shred --force --iterations=1 --zero --remove", workflow)
        self.assertNotIn("/etc/spyboxd/canary.env", workflow)

    def test_authenticated_canary_pins_the_documented_clerk_api_version_header(self):
        class Opened:
            status = 200

            def __init__(self):
                self.headers: dict[str, str] = {}

            def read(self, _size: int) -> bytes:
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with mock.patch.object(
            auth_canary._CLERK_OPENER, "open", return_value=Opened()
        ) as open_request:
            auth_canary._request(
                "https://api.clerk.com/v1/agents/tasks",
                method="POST",
                bearer="sk_live_test",
                payload={"permissions": "*"},
                clerk_backend=True,
            )
        request = open_request.call_args.args[0]
        headers = {name.lower(): value for name, value in request.header_items()}
        self.assertEqual(headers["clerk-api-version"], "2026-05-12")
        self.assertNotIn("clerk-version", headers)

    def test_authenticated_canary_never_follows_clerk_redirects(self):
        redirect = auth_canary.urllib.error.HTTPError(
            "https://api.clerk.com/v1/sessions",
            302,
            "Found",
            {"Location": "https://evil.example/collect"},
            io.BytesIO(b""),
        )
        with mock.patch.object(
            auth_canary._CLERK_OPENER, "open", side_effect=redirect
        ) as open_request:
            response = auth_canary._request(
                "https://api.clerk.com/v1/sessions",
                bearer="sk_live_test",
                clerk_backend=True,
            )
        self.assertEqual(response.status, 302)
        self.assertEqual(open_request.call_count, 1)
        self.assertEqual(
            open_request.call_args.args[0].full_url,
            "https://api.clerk.com/v1/sessions",
        )

    def test_authenticated_canary_requires_explicit_complete_session_pagination(self):
        session = {
            "id": "sess_A123456",
            "user_id": "user_A123",
            "status": "active",
        }
        response = auth_canary.HttpResponse(
            200,
            json.dumps({"data": [session], "total_count": 1}).encode(),
            {},
        )
        with mock.patch.object(auth_canary, "_request", return_value=response) as request:
            self.assertEqual(
                auth_canary._list_sessions(
                    "sk_live_test", "user_A123", "active"
                ),
                [session],
            )
        self.assertIn("paginated=true", request.call_args.args[0])

        invalid_payloads = (
            [session],
            {"data": [session], "total_count": 2},
            {"data": [session], "total_count": True},
            {"data": [session] * 100, "total_count": 100},
        )
        for payload in invalid_payloads:
            with self.subTest(payload_type=type(payload).__name__):
                response = auth_canary.HttpResponse(
                    200, json.dumps(payload).encode(), {}
                )
                with (
                    mock.patch.object(auth_canary, "_request", return_value=response),
                    self.assertRaises(auth_canary.AuthCanaryError),
                ):
                    auth_canary._list_sessions(
                        "sk_live_test", "user_A123", "active"
                    )

    def test_authenticated_canary_records_task_id_before_url_validation(self):
        identity = auth_canary.CanaryIdentity("A", "user_A123", "alpha")
        response = auth_canary.HttpResponse(
            200,
            json.dumps(
                {
                    "agent_task_id": "agent_task_A123456",
                    "url": "https://evil.example/v1/agent-tasks/ticket",
                }
            ).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        recorded: list[str] = []
        with (
            mock.patch.object(
                auth_canary, "_request", return_value=response
            ) as request,
            self.assertRaisesRegex(auth_canary.AuthCanaryError, "unsafe task URL"),
        ):
            auth_canary._create_agent_task(
                "sk_live_test",
                identity,
                allowed_frontend_origins={"https://clerk.spyboxd.com"},
                app_origin="https://spyboxd.com",
                record_task_id=recorded.append,
            )
        self.assertEqual(recorded, ["agent_task_A123456"])
        self.assertEqual(
            request.call_args.kwargs["payload"]["session_max_duration_in_seconds"],
            auth_canary.SESSION_MAX_DURATION_SECONDS,
        )
        self.assertEqual(
            request.call_args.kwargs["payload"]["redirect_url"],
            "https://spyboxd.com/",
        )

    def test_authenticated_browser_plan_assigns_sign_out_and_expiry_proofs(self):
        tasks = [
            {
                "label": "A",
                "user_id": "user_A123",
                "profile": "alpha",
                "task_url": "https://clerk.spyboxd.com/task-a",
                "task_origin": "https://clerk.spyboxd.com",
            },
            {
                "label": "B",
                "user_id": "user_B123",
                "profile": "beta",
                "task_url": "https://clerk.spyboxd.com/task-b",
                "task_origin": "https://clerk.spyboxd.com",
            },
        ]
        plan = auth_canary._build_browser_plan(
            api_base="https://api.spyboxd.com",
            app_origin="https://spyboxd.com",
            task_origin="https://clerk.spyboxd.com",
            tasks=tasks,
        )
        self.assertEqual(plan["version"], auth_canary.BROWSER_PLAN_VERSION)
        self.assertEqual(
            plan["session_max_duration_seconds"],
            auth_canary.SESSION_MAX_DURATION_SECONDS,
        )
        self.assertEqual(
            [task["closure"] for task in plan["tasks"]],
            ["sign_out", "session_expiry"],
        )
        self.assertNotIn("closure", tasks[0])
        self.assertNotIn("closure", tasks[1])

    def test_authenticated_browser_plan_rejects_duplicate_or_inconsistent_tasks(self):
        base = {
            "label": "A",
            "user_id": "user_A123",
            "profile": "alpha",
            "task_url": "https://clerk.spyboxd.com/task-a",
            "task_origin": "https://clerk.spyboxd.com",
        }
        with self.assertRaisesRegex(auth_canary.AuthCanaryError, "task labels"):
            auth_canary._build_browser_plan(
                api_base="https://api.spyboxd.com",
                app_origin="https://spyboxd.com",
                task_origin="https://clerk.spyboxd.com",
                tasks=[base, {**base, "user_id": "user_B123", "profile": "beta"}],
            )
        with self.assertRaisesRegex(auth_canary.AuthCanaryError, "task origins"):
            auth_canary._build_browser_plan(
                api_base="https://api.spyboxd.com",
                app_origin="https://spyboxd.com",
                task_origin="https://clerk.spyboxd.com",
                tasks=[
                    base,
                    {
                        "label": "B",
                        "user_id": "user_B123",
                        "profile": "beta",
                        "task_url": "https://clerk.spyboxd.com/task-b",
                        "task_origin": "https://other.example",
                    },
                ],
            )

    def test_authenticated_canary_refuses_users_with_preexisting_sessions(self):
        identities = (
            auth_canary.CanaryIdentity("A", "user_A123", "alpha"),
            auth_canary.CanaryIdentity("B", "user_B123", "beta"),
        )
        with (
            mock.patch.object(
                auth_canary,
                "_list_live_sessions",
                side_effect=[{"sess_existing"}, set()],
            ),
            self.assertRaisesRegex(
                auth_canary.AuthCanaryError, "already has a live session"
            ),
        ):
            auth_canary._require_zero_live_sessions("sk_live_test", identities)

    def test_authenticated_canary_only_queries_valid_active_session_status(self):
        with mock.patch.object(
            auth_canary, "_list_sessions", return_value=[]
        ) as list_sessions:
            self.assertEqual(
                auth_canary._list_live_sessions("sk_live_test", "user_A123"), set()
            )
        list_sessions.assert_called_once_with("sk_live_test", "user_A123", "active")

    def test_cleanup_retires_tasks_and_re_lists_every_new_session(self):
        state = {
            "version": 1,
            "lease_id": "gha-123-1",
            "phase": "waiting_for_browser",
            "session_baseline_proven_zero": True,
            "identities": [
                {"label": "A", "user_id": "user_A123", "profile": "alpha"},
                {"label": "B", "user_id": "user_B123", "profile": "beta"},
            ],
            "task_ids": ["agent_task_A123456", "agent_task_B123456"],
        }
        with (
            mock.patch.object(auth_canary, "_retire_agent_task") as retire,
            mock.patch.object(
                auth_canary,
                "_list_live_sessions",
                side_effect=[
                    {"sess_A123"},
                    {"sess_B123"},
                    set(),
                    set(),
                    set(),
                    set(),
                ],
            ) as list_sessions,
            mock.patch.object(auth_canary, "_revoke_session") as revoke,
            mock.patch.object(auth_canary.time, "sleep"),
        ):
            auth_canary._cleanup_state("sk_live_test", state)
        self.assertEqual(retire.call_count, 2)
        self.assertEqual(list_sessions.call_count, 6)
        self.assertEqual(
            {call.args[1] for call in revoke.call_args_list},
            {"sess_A123", "sess_B123"},
        )

    def test_failed_cleanup_removes_plan_but_retains_recoverable_state(self):
        state = {
            "version": 1,
            "lease_id": "gha-123-1",
            "phase": "waiting_for_browser",
            "session_baseline_proven_zero": True,
            "identities": [
                {"label": "A", "user_id": "user_A123", "profile": "alpha"},
                {"label": "B", "user_id": "user_B123", "profile": "beta"},
            ],
            "task_ids": ["agent_task_A123456"],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            lease = Path(temporary_directory)
            auth_canary._write_private_json(lease / auth_canary.STATE_NAME, state)
            auth_canary._write_private_json(
                lease / auth_canary.PLAN_NAME,
                {"version": 1, "task_url": "https://clerk.example/one-use"},
            )
            with (
                mock.patch.object(
                    auth_canary,
                    "_cleanup_state",
                    side_effect=auth_canary.AuthCanaryError("synthetic outage"),
                ),
                self.assertRaisesRegex(auth_canary.AuthCanaryError, "synthetic outage"),
            ):
                auth_canary._cleanup_stored_lease(lease, "sk_live_test")
            self.assertFalse((lease / auth_canary.PLAN_NAME).exists())
            retained = auth_canary._read_private_json(lease / auth_canary.STATE_NAME)
            self.assertEqual(retained["phase"], "cleanup_failed")

    def test_guardian_status_distinguishes_primary_and_cleanup_failures(self):
        primary = auth_canary.AuthCanaryError("browser failed")
        cleanup = auth_canary.AuthCanaryError("cleanup failed")
        self.assertEqual(auth_canary._guardian_result_status(None, None), "passed")
        self.assertEqual(
            auth_canary._guardian_result_status(primary, None), "failed"
        )
        self.assertEqual(
            auth_canary._guardian_result_status(None, cleanup), "cleanup_failed"
        )
        self.assertEqual(
            auth_canary._guardian_result_status(primary, cleanup), "cleanup_failed"
        )

    def test_consumed_agent_task_is_safe_only_for_the_exact_clerk_error(self):
        response = auth_canary.HttpResponse(
            400,
            json.dumps({"errors": [{"code": "agent_task_cannot_be_revoked"}]}).encode(
                "utf-8"
            ),
            {"Content-Type": "application/json"},
        )
        with mock.patch.object(auth_canary, "_request", return_value=response):
            self.assertTrue(
                auth_canary._retire_agent_task(
                    "sk_live_test",
                    "agent_task_A123456",
                )
            )

    def test_secure_env_parser_rejects_world_readable_configuration(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "canary.env"
            path.write_text("SPYBOXD_CANARY_USER_A_ID=user_A123\n", encoding="utf-8")
            unsafe_metadata = mock.Mock(st_mode=stat.S_IFREG | 0o604)
            with mock.patch.object(Path, "lstat", return_value=unsafe_metadata):
                with self.assertRaisesRegex(
                    auth_canary.AuthCanaryError, "world-accessible"
                ):
                    auth_canary._read_secure_env(path)


if __name__ == "__main__":
    unittest.main()
