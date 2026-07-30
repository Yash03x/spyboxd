#!/usr/bin/env python3
"""Fail closed when a production build or runtime uses Clerk development config."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import shlex
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


PUBLIC_KEY_ENV = "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY"
SECRET_KEY_ENV = "CLERK_SECRET_KEY"
AUTH_BYPASS_ENV = "SPYBOXD_E2E_AUTH_BYPASS"
PUBLIC_URL_KEYS = (
    "NEXT_PUBLIC_CLERK_SIGN_IN_URL",
    "NEXT_PUBLIC_CLERK_SIGN_UP_URL",
    "NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL",
    "NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL",
)
KEY_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LIVE_PUBLIC_KEY_RE = re.compile(r"^pk_live_[A-Za-z0-9_-]+$")
TEST_PUBLIC_KEY_RE = re.compile(r"^pk_test_[A-Za-z0-9_-]+$")
LIVE_SECRET_KEY_RE = re.compile(r"^sk_live_[A-Za-z0-9_-]{20,}$")
CLERK_BACKEND_INSTANCE_URL = "https://api.clerk.com/v1/instance"
CLERK_BACKEND_JWKS_URL = "https://api.clerk.com/v1/jwks"
REMOTE_REQUEST_TIMEOUT_SECONDS = 10
MAX_REMOTE_RESPONSE_BYTES = 1_000_000
REQUIRED_AUTHORIZED_PARTY = "https://spyboxd.com"
ALLOWED_AUTHORIZED_PARTIES = frozenset(
    {
        REQUIRED_AUTHORIZED_PARTY,
        "https://www.spyboxd.com",
    }
)


class ConfigurationError(ValueError):
    """A production Clerk invariant is not satisfied."""


class _RejectRedirects(HTTPRedirectHandler):
    """Keep the Clerk secret on the single, fixed Backend API origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _fetch_json(url: str, *, secret_key: str | None = None) -> Any:
    headers = {
        "Accept": "application/json",
        "User-Agent": "spyboxd-clerk-production-validator/1",
    }
    if secret_key is not None:
        headers["Authorization"] = f"Bearer {secret_key}"
    request = Request(url, headers=headers, method="GET")
    try:
        with build_opener(_RejectRedirects()).open(
            request,
            timeout=REMOTE_REQUEST_TIMEOUT_SECONDS,
        ) as response:
            payload = response.read(MAX_REMOTE_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise ConfigurationError(
            f"remote Clerk verification failed with HTTP {exc.code}"
        ) from None
    except (URLError, TimeoutError, OSError):
        raise ConfigurationError("remote Clerk verification request failed") from None

    if len(payload) > MAX_REMOTE_RESPONSE_BYTES:
        raise ConfigurationError("remote Clerk verification response is too large")
    try:
        return json.loads(payload)
    except (UnicodeError, ValueError):
        raise ConfigurationError("remote Clerk verification returned invalid JSON") from None


def _parse_env_file(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError(f"environment path is not a regular file: {path}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigurationError(f"cannot read environment file {path}") from exc

    values: dict[str, str] = {}
    for line_number, original_line in enumerate(lines, start=1):
        line = original_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            raise ConfigurationError(
                f"invalid environment assignment in {path} at line {line_number}"
            )
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not KEY_NAME_RE.fullmatch(key):
            raise ConfigurationError(
                f"invalid environment key in {path} at line {line_number}"
            )

        lexer = shlex.shlex(raw_value, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = "#"
        try:
            tokens = list(lexer)
        except ValueError as exc:
            raise ConfigurationError(
                f"invalid environment value in {path} at line {line_number}"
            ) from exc
        if len(tokens) > 1:
            raise ConfigurationError(
                f"unquoted whitespace in {path} at line {line_number}"
            )
        values[key] = tokens[0] if tokens else ""
    return values


def _require_value(values: dict[str, str], key: str, source: str) -> str:
    value = values.get(key, "").strip()
    if not value or "REPLACE_WITH" in value:
        raise ConfigurationError(f"{source} is missing {key}")
    return value


def _reject_auth_bypass(values: dict[str, str], source: str) -> None:
    if values.get(AUTH_BYPASS_ENV, "").strip():
        raise ConfigurationError(f"{source} enables {AUTH_BYPASS_ENV}")


def _decode_publishable_host(publishable_key: str, prefix: str = "pk_live_") -> str:
    encoded_host = publishable_key.removeprefix(prefix)
    encoded_host += "=" * (-len(encoded_host) % 4)
    try:
        decoded = base64.urlsafe_b64decode(encoded_host).decode("ascii")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ConfigurationError(
            f"{PUBLIC_KEY_ENV} does not contain a decodable Clerk frontend host"
        ) from exc

    if not decoded.endswith("$"):
        raise ConfigurationError(
            f"{PUBLIC_KEY_ENV} does not use the expected Clerk key encoding"
        )
    decoded = decoded.removesuffix("$").strip()
    parsed = urlparse(decoded if "://" in decoded else f"https://{decoded}")
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError(
            f"{PUBLIC_KEY_ENV} does not contain a valid Clerk frontend host"
        ) from exc
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ConfigurationError(
            f"{PUBLIC_KEY_ENV} does not contain a valid Clerk frontend host"
        )
    return host


def _require_live_publishable_key(values: dict[str, str], source: str) -> tuple[str, str]:
    key = _require_value(values, PUBLIC_KEY_ENV, source)
    if key.startswith("pk_test_"):
        raise ConfigurationError(f"{source} uses a Clerk development publishable key")
    if not LIVE_PUBLIC_KEY_RE.fullmatch(key):
        raise ConfigurationError(f"{source} does not contain a valid Clerk live publishable key")
    host = _decode_publishable_host(key)
    if host.endswith(".clerk.accounts.dev"):
        raise ConfigurationError(f"{source} resolves to a Clerk development frontend host")
    return key, host


def _validate_https_origin(value: str, variable_name: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError(f"{variable_name} must be a plain HTTPS Clerk origin") from exc
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ConfigurationError(f"{variable_name} must be a plain HTTPS Clerk origin")
    if host.endswith(".clerk.accounts.dev"):
        raise ConfigurationError(f"{variable_name} points to a Clerk development instance")
    return host


def _require_exact_https_origin(value: str, variable_name: str) -> tuple[str, str]:
    host = _validate_https_origin(value, variable_name)
    canonical_origin = f"https://{host}"
    if value != canonical_origin:
        raise ConfigurationError(
            f"{variable_name} must contain canonical HTTPS origins without paths or ports"
        )
    return canonical_origin, host


def _validate_authorized_parties(api_values: dict[str, str]) -> None:
    raw_value = _require_value(
        api_values,
        "CLERK_AUTHORIZED_PARTIES",
        "API runtime environment",
    )
    values = [value.strip() for value in raw_value.split(",")]
    if not values or any(not value for value in values):
        raise ConfigurationError(
            "CLERK_AUTHORIZED_PARTIES must be a comma-separated list of HTTPS origins"
        )

    origins: set[str] = set()
    for value in values:
        origin, _ = _require_exact_https_origin(value, "CLERK_AUTHORIZED_PARTIES")
        if origin not in ALLOWED_AUTHORIZED_PARTIES:
            raise ConfigurationError(
                "CLERK_AUTHORIZED_PARTIES contains an origin outside the Spyboxd production sites"
            )
        if origin in origins:
            raise ConfigurationError("CLERK_AUTHORIZED_PARTIES contains a duplicate origin")
        origins.add(origin)

    if REQUIRED_AUTHORIZED_PARTY not in origins:
        raise ConfigurationError(
            f"CLERK_AUTHORIZED_PARTIES must include {REQUIRED_AUTHORIZED_PARTY}"
        )


def _validate_jwks_url(value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError(
            "CLERK_JWKS_URL must be an HTTPS Clerk origin followed by /.well-known/jwks.json"
        ) from exc
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.path != "/.well-known/jwks.json"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError(
            "CLERK_JWKS_URL must be an HTTPS Clerk origin followed by /.well-known/jwks.json"
        )
    if host.endswith(".clerk.accounts.dev"):
        raise ConfigurationError("CLERK_JWKS_URL points to a Clerk development instance")
    return host


def _backend_clerk_host(api_values: dict[str, str]) -> str:
    jwks_url = api_values.get("CLERK_JWKS_URL", "").strip()
    frontend_api = api_values.get("CLERK_FRONTEND_API", "").strip().rstrip("/")
    if not jwks_url and not frontend_api:
        raise ConfigurationError(
            "API environment is missing CLERK_JWKS_URL or CLERK_FRONTEND_API"
        )

    jwks_host = _validate_jwks_url(jwks_url) if jwks_url else ""
    frontend_host = (
        _validate_https_origin(frontend_api, "CLERK_FRONTEND_API")
        if frontend_api
        else ""
    )
    if jwks_host and frontend_host and jwks_host != frontend_host:
        raise ConfigurationError(
            "CLERK_JWKS_URL and CLERK_FRONTEND_API identify different Clerk instances"
        )
    return jwks_host or frontend_host


def _jwks_key_identities(document: Any, source: str) -> set[str]:
    if not isinstance(document, dict) or not isinstance(document.get("keys"), list):
        raise ConfigurationError(f"{source} did not return a valid JWKS document")

    identities: set[str] = set()
    for key in document["keys"]:
        if not isinstance(key, dict):
            continue
        key_type = key.get("kty")
        key_id = key.get("kid")
        if not isinstance(key_type, str) or not isinstance(key_id, str) or not key_id:
            continue

        material_names: tuple[str, ...]
        if key_type == "RSA":
            material_names = ("n", "e")
        elif key_type == "EC":
            material_names = ("crv", "x", "y")
        elif key_type == "OKP":
            material_names = ("crv", "x")
        else:
            continue
        material = {name: key.get(name) for name in material_names}
        if not all(isinstance(value, str) and value for value in material.values()):
            continue
        identities.add(
            json.dumps(
                {"kid": key_id, "kty": key_type, **material},
                sort_keys=True,
                separators=(",", ":"),
            )
        )

    if not identities:
        raise ConfigurationError(f"{source} did not expose any usable signing keys")
    return identities


def _verify_remote_clerk_instance(secret_key: str, frontend_host: str) -> None:
    instance = _fetch_json(CLERK_BACKEND_INSTANCE_URL, secret_key=secret_key)
    if not isinstance(instance, dict):
        raise ConfigurationError("Clerk Backend API returned an invalid instance response")
    instance_id = instance.get("id")
    if not isinstance(instance_id, str) or not instance_id:
        raise ConfigurationError("Clerk Backend API returned an invalid instance response")
    environment_type = instance.get("environment_type", instance.get("environmentType"))
    if environment_type != "production":
        raise ConfigurationError(
            "Clerk secret key does not authenticate a production instance"
        )

    secret_jwks = _jwks_key_identities(
        _fetch_json(CLERK_BACKEND_JWKS_URL, secret_key=secret_key),
        "Clerk Backend API",
    )
    configured_jwks = _jwks_key_identities(
        _fetch_json(f"https://{frontend_host}/.well-known/jwks.json"),
        "configured Clerk frontend",
    )
    if secret_jwks.isdisjoint(configured_jwks):
        raise ConfigurationError(
            "Clerk secret key and publishable/JWKS configuration identify different instances"
        )


def _load_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError("release manifest is not a regular file")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ConfigurationError("release manifest cannot be decoded") from exc
    if not isinstance(manifest, dict):
        raise ConfigurationError("release manifest is not a JSON object")
    return manifest


def _validate_manifest(path: Path, publishable_key: str) -> None:
    manifest = _load_manifest(path)
    manifest_environment = manifest.get("frontend_public_environment")
    if not isinstance(manifest_environment, dict):
        raise ConfigurationError("release manifest has no public frontend environment")
    if manifest_environment.get(PUBLIC_KEY_ENV) != publishable_key:
        raise ConfigurationError(
            "release manifest Clerk publishable key does not match the runtime environment"
        )


def validate_development_manifest(path: Path, expected_revision: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", expected_revision):
        raise ConfigurationError("bridge source revision is not a lowercase full Git SHA")
    manifest = _load_manifest(path)
    if manifest.get("format_version") != 1 or manifest.get("revision") != expected_revision:
        raise ConfigurationError("bridge source manifest identity does not match its release")
    manifest_environment = manifest.get("frontend_public_environment")
    if not isinstance(manifest_environment, dict):
        raise ConfigurationError("bridge source manifest has no public frontend environment")
    publishable_key = manifest_environment.get(PUBLIC_KEY_ENV)
    if not isinstance(publishable_key, str) or not TEST_PUBLIC_KEY_RE.fullmatch(publishable_key):
        raise ConfigurationError("bridge source manifest is not a Clerk development artifact")
    host = _decode_publishable_host(publishable_key, prefix="pk_test_")
    if not host.endswith(".clerk.accounts.dev"):
        raise ConfigurationError("bridge source manifest is not a Clerk development artifact")


def validate_build_environment() -> None:
    build_environment = dict(os.environ)
    _reject_auth_bypass(build_environment, "production build environment")
    _require_live_publishable_key(build_environment, "production build environment")


def validate_runtime(
    frontend_env: Path,
    api_env: Path,
    manifest: Path | None,
    *,
    verify_remote: bool = False,
) -> None:
    frontend_values = _parse_env_file(frontend_env)
    api_values = _parse_env_file(api_env)
    _reject_auth_bypass(dict(os.environ), "release process environment")
    _reject_auth_bypass(frontend_values, "frontend runtime environment")
    _reject_auth_bypass(api_values, "API runtime environment")
    publishable_key, publishable_host = _require_live_publishable_key(
        frontend_values,
        "frontend runtime environment",
    )

    secret_key = _require_value(frontend_values, SECRET_KEY_ENV, "frontend runtime environment")
    if secret_key.startswith("sk_test_"):
        raise ConfigurationError("frontend runtime environment uses a Clerk development secret key")
    if not LIVE_SECRET_KEY_RE.fullmatch(secret_key):
        raise ConfigurationError(
            "frontend runtime environment does not contain a valid Clerk live secret key"
        )

    for key in PUBLIC_URL_KEYS:
        _require_value(frontend_values, key, "frontend runtime environment")

    backend_host = _backend_clerk_host(api_values)
    if backend_host != publishable_host:
        raise ConfigurationError(
            "frontend publishable key and backend JWKS configuration identify different Clerk instances"
        )

    issuer = _require_value(api_values, "CLERK_ISSUER", "API runtime environment")
    _, issuer_host = _require_exact_https_origin(issuer, "CLERK_ISSUER")
    if issuer_host != publishable_host:
        raise ConfigurationError(
            "CLERK_ISSUER and publishable/JWKS configuration identify different Clerk instances"
        )
    _validate_authorized_parties(api_values)

    if manifest is not None:
        _validate_manifest(manifest, publishable_key)

    if verify_remote:
        _verify_remote_clerk_instance(secret_key, publishable_host)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("build", help="validate production build environment variables")

    runtime = subparsers.add_parser("runtime", help="validate production runtime files")
    runtime.add_argument("--frontend-env", required=True, type=Path)
    runtime.add_argument("--api-env", required=True, type=Path)
    runtime.add_argument("--manifest", type=Path)
    runtime.add_argument(
        "--verify-remote",
        action="store_true",
        help="verify the secret key and signing keys against Clerk before a release",
    )

    bridge_manifest = subparsers.add_parser(
        "development-manifest",
        help="validate the exact development artifact permitted for a one-time Clerk bridge",
    )
    bridge_manifest.add_argument("--manifest", required=True, type=Path)
    bridge_manifest.add_argument("--expected-revision", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "build":
            validate_build_environment()
        elif args.command == "runtime":
            validate_runtime(
                args.frontend_env,
                args.api_env,
                args.manifest,
                verify_remote=args.verify_remote,
            )
        else:
            validate_development_manifest(args.manifest, args.expected_revision)
    except ConfigurationError as exc:
        print(f"Clerk production configuration is invalid: {exc}", file=sys.stderr)
        return 1
    if args.command == "development-manifest":
        print("Clerk development bridge manifest is valid.")
    else:
        print("Clerk production configuration is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
