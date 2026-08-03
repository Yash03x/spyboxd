#!/usr/bin/env python3
"""Read-only production canary for Spyboxd's public and anonymous boundaries."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")
# The redesigned sections. The pre-redesign paths (/dashboard, /spy-signals,
# /analysis, /compare, /network) are permanent redirects now, so they answer
# 308 to their new home rather than bouncing an anonymous caller to sign-in --
# checking them would prove the redirect, not the protection.
PRIVATE_UI_PATHS = (
    "/overview",
    "/overlaps",
    "/people",
    "/tonight",
    "/films",
    "/data",
    "/profiles",
    "/u/privacy-check",
)

# The pre-redesign paths, which are permanent redirects rather than guarded
# routes. They were left in PRIVATE_UI_PATHS after the sections were renamed,
# so the canary asserted /analysis sends anonymous traffic to /sign-in when it
# now sends everybody to /people — and failed on a working deployment. They are
# still worth checking, against what they actually do.
LEGACY_UI_REDIRECTS = (
    ("/dashboard", "/overview"),
    ("/spy-signals", "/overlaps"),
    ("/analysis", "/people"),
    ("/compare", "/people"),
    ("/network", "/people"),
    ("/watch-together", "/tonight"),
)
PRIVATE_API_PATHS = (
    "/api/me",
    "/profiles/",
    "/profiles/tracked",
    "/profiles/catalog",
    "/public/profile/privacy-check",
    "/api/dashboard/analytics",
    "/api/spy-signals",
    "/api/activity/marathons",
    "/api/activity/weekday",
    "/api/insights/shared-firsts",
    "/profiles/privacy-check/analysis",
    "/api/data-coverage",
    "/api/pair-dossier",
    "/api/signal-calendar",
    "/api/rewatch-echoes",
    "/api/taste-dna",
    "/api/taste-timeline",
    "/api/public-lists",
    "/api/watch-together",
    "/api/watch-provider-regions",
    "/api/recent-changes",
    "/profiles/requests",
    "/admin/profile-requests",
)


class CanaryError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):  # noqa: ANN001
        return None


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes


class RequestClient:
    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._opener = urllib.request.build_opener(_NoRedirect)

    def get(self, url: str) -> Response:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json, text/html;q=0.9",
                "Cache-Control": "no-cache",
                "User-Agent": "spyboxd-production-canary/1",
            },
            method="GET",
        )
        try:
            opened = self._opener.open(request, timeout=self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            return Response(exc.code, exc.headers, _bounded_read(exc))
        except (OSError, urllib.error.URLError) as exc:
            raise CanaryError("production endpoint could not be reached") from exc
        with opened:
            return Response(opened.status, opened.headers, _bounded_read(opened))


def _bounded_read(stream) -> bytes:  # noqa: ANN001
    body = stream.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise CanaryError("production response exceeded the canary size limit")
    return body


def _base_url(raw: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(raw)
        parsed.port
    except ValueError as exc:
        raise CanaryError("production base URLs must be valid HTTPS origins") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (parsed.path not in ("", "/"))
    ):
        raise CanaryError("production base URLs must be bare HTTPS origins")
    return urllib.parse.urlunsplit(("https", parsed.netloc, "", "", ""))


def _header(response: Response, name: str) -> str:
    for key, value in response.headers.items():
        if key.casefold() == name.casefold():
            return str(value)
    return ""


def _validate_security_headers(response: Response, label: str) -> None:
    hsts = _header(response, "Strict-Transport-Security").casefold()
    if "max-age=" not in hsts:
        raise CanaryError(f"{label} is missing HSTS")
    if _header(response, "X-Content-Type-Options").casefold() != "nosniff":
        raise CanaryError(f"{label} is missing nosniff")
    if _header(response, "X-Frame-Options").casefold() not in {"deny", "sameorigin"}:
        raise CanaryError(f"{label} is missing frame protection")


def _json_response(response: Response, label: str, expected_status: int = 200) -> Any:
    if response.status != expected_status:
        raise CanaryError(f"{label} returned HTTP {response.status}")
    _validate_security_headers(response, label)
    if "application/json" not in _header(response, "Content-Type").casefold():
        raise CanaryError(f"{label} did not return JSON")
    try:
        return json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanaryError(f"{label} returned invalid JSON") from exc


def _html_response(
    response: Response, label: str, required_markers: tuple[str, ...]
) -> None:
    if response.status != 200:
        raise CanaryError(f"{label} returned HTTP {response.status}")
    _validate_security_headers(response, label)
    if "text/html" not in _header(response, "Content-Type").casefold():
        raise CanaryError(f"{label} did not return HTML")
    try:
        document = response.body.decode("utf-8").casefold()
    except UnicodeDecodeError as exc:
        raise CanaryError(f"{label} returned invalid UTF-8") from exc
    if len(document) < 1024:
        raise CanaryError(f"{label} returned an unexpectedly small document")
    if any(marker.casefold() not in document for marker in required_markers):
        raise CanaryError(f"{label} is missing its expected application shell")
    if any(
        marker in document
        for marker in ("__next_error__", "application error", "internal server error")
    ):
        raise CanaryError(f"{label} contains a framework error marker")


def _load_health_validator(path: Path) -> ModuleType:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CanaryError(
            "the checked-out runtime health validator is unavailable"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CanaryError("the runtime health validator must be a regular file")
    spec = importlib.util.spec_from_file_location(
        "spyboxd_runtime_health_validator", path
    )
    if spec is None or spec.loader is None:
        raise CanaryError("the runtime health validator could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("validate_ready", "validate_dashboard", "validate_rss"):
        if not callable(getattr(module, name, None)):
            raise CanaryError("the runtime health validator has an invalid interface")
    return module


def _validate_legacy_redirect(
    web_base: str, path: str, destination: str, response: Response
) -> None:
    """A pre-redesign path must land on its new home, not on sign-in.

    Guarding it as a private route instead is what made a healthy deployment
    look broken; asserting the destination is what actually protects the
    inbound links people already hold.
    """

    label = f"legacy redirect {path}"
    if response.status != 308:
        raise CanaryError(f"{label} did not answer with a permanent redirect")
    # Next serves these with a relative Location, so it is resolved against the
    # request rather than compared raw -- and resolving keeps the cross-origin
    # check meaningful for an absolute one.
    location = _header(response, "Location")
    parsed = urllib.parse.urlsplit(
        urllib.parse.urljoin(f"{web_base}{path}", location)
    )
    expected_origin = urllib.parse.urlsplit(web_base)
    if (
        parsed.scheme != expected_origin.scheme
        or parsed.netloc != expected_origin.netloc
        or parsed.path.rstrip("/") != destination
    ):
        raise CanaryError(f"{label} no longer points at {destination}")


def _validate_private_redirect(web_base: str, path: str, response: Response) -> None:
    label = "private application route"
    if response.status not in {301, 302, 303, 307, 308}:
        raise CanaryError(f"{label} did not redirect anonymous traffic")
    _validate_security_headers(response, label)
    location = _header(response, "Location")
    parsed = urllib.parse.urlsplit(location)
    expected_origin = urllib.parse.urlsplit(web_base)
    if (
        parsed.scheme != expected_origin.scheme
        or parsed.netloc != expected_origin.netloc
        or parsed.path.rstrip("/") != "/sign-in"
    ):
        raise CanaryError(f"{label} redirected outside the production sign-in route")
    try:
        redirect_targets = urllib.parse.parse_qs(parsed.query, strict_parsing=True).get(
            "redirect_url", []
        )
    except ValueError as exc:
        raise CanaryError(f"{label} returned a malformed sign-in destination") from exc
    if redirect_targets != [f"{web_base}{path}"]:
        raise CanaryError(
            f"{label} did not preserve its exact same-origin return target"
        )


def _validate_anonymous_api(response: Response) -> None:
    payload = _json_response(response, "private API route", expected_status=401)
    if (
        not isinstance(payload, dict)
        or payload.get("detail") != "Missing authorization token"
    ):
        raise CanaryError(
            "private API route did not return the application auth boundary"
        )
    if _header(response, "WWW-Authenticate").casefold() != "bearer":
        raise CanaryError("private API route did not advertise bearer authentication")


def run_canary(
    *,
    web_base: str,
    api_base: str,
    validator_path: Path,
    expected_revision: str | None = None,
    client: RequestClient | Any | None = None,
) -> dict[str, Any]:
    web_base = _base_url(web_base)
    api_base = _base_url(api_base)
    health_validator = _load_health_validator(validator_path)
    request_client = client or RequestClient()

    ready_payload = _json_response(
        request_client.get(f"{api_base}/ready"), "readiness endpoint"
    )
    if not isinstance(ready_payload, dict):
        raise CanaryError("readiness endpoint did not return an object")
    revision = ready_payload.get("revision")
    if not isinstance(revision, str) or not REVISION_PATTERN.fullmatch(revision):
        raise CanaryError("readiness endpoint did not identify an immutable release")
    if expected_revision is not None and revision != expected_revision:
        raise CanaryError("production revision does not match the requested release")
    try:
        health_validator.validate_ready(ready_payload, revision)
    except Exception as exc:  # The checked-out validator owns its detailed contract.
        raise CanaryError("readiness database or schema contract failed") from exc

    dashboard_payload = _json_response(
        request_client.get(f"{api_base}/api/public/dashboard"),
        "public dashboard endpoint",
    )
    rss_payload = _json_response(
        request_client.get(f"{api_base}/health/rss"), "RSS health endpoint"
    )
    try:
        health_validator.validate_dashboard(dashboard_payload)
        health_validator.validate_rss(rss_payload)
    except Exception as exc:
        raise CanaryError("public data or RSS semantic health contract failed") from exc

    _html_response(
        request_client.get(f"{web_base}/"), "public homepage", ("spyboxd", "letterboxd")
    )
    _html_response(
        request_client.get(f"{web_base}/sign-in"),
        "sign-in page",
        ("spyboxd", "clerk", "sign-in"),
    )

    for path in PRIVATE_UI_PATHS:
        _validate_private_redirect(
            web_base, path, request_client.get(f"{web_base}{path}")
        )
    for path, destination in LEGACY_UI_REDIRECTS:
        _validate_legacy_redirect(
            web_base, path, destination, request_client.get(f"{web_base}{path}")
        )
    for path in PRIVATE_API_PATHS:
        _validate_anonymous_api(request_client.get(f"{api_base}{path}"))

    return {
        "revision": revision,
        "private_api_routes": len(PRIVATE_API_PATHS),
        "private_ui_routes": len(PRIVATE_UI_PATHS),
        "legacy_ui_redirects": len(LEGACY_UI_REDIRECTS),
    }


def _write_revision(path: Path, revision: str) -> None:
    if not path.is_absolute() or path.parent.is_symlink() or not path.parent.is_dir():
        raise CanaryError(
            "revision output must be inside an existing absolute directory"
        )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise CanaryError("could not safely create the revision output") from exc
    with os.fdopen(descriptor, "w", encoding="ascii") as output:
        output.write(f"{revision}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web-base", default="https://spyboxd.com")
    parser.add_argument("--api-base", default="https://api.spyboxd.com")
    parser.add_argument("--health-validator", type=Path, required=True)
    parser.add_argument("--expected-revision", default=None)
    parser.add_argument("--write-revision", type=Path, default=None)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--retry-delay-seconds", type=float, default=10.0)
    args = parser.parse_args()
    if (
        args.attempts < 1
        or args.attempts > 6
        or not 0 <= args.retry_delay_seconds <= 60
    ):
        parser.error("attempt and retry settings are outside the safe range")
    if args.expected_revision is not None and not REVISION_PATTERN.fullmatch(
        args.expected_revision
    ):
        parser.error("--expected-revision must be a lowercase full Git SHA")

    last_error: CanaryError | None = None
    for attempt in range(1, args.attempts + 1):
        try:
            result = run_canary(
                web_base=args.web_base,
                api_base=args.api_base,
                validator_path=args.health_validator,
                expected_revision=args.expected_revision,
            )
            if args.write_revision is not None:
                _write_revision(args.write_revision, result["revision"])
            print(
                "production canary passed: "
                f"revision={result['revision']} "
                f"private_ui_routes={result['private_ui_routes']} "
                f"private_api_routes={result['private_api_routes']}"
            )
            return 0
        except CanaryError as exc:
            last_error = exc
            if attempt < args.attempts:
                print(
                    f"production canary attempt {attempt} failed; retrying",
                    file=sys.stderr,
                )
                time.sleep(args.retry_delay_seconds)
    print(f"production canary failed: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
