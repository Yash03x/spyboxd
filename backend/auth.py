from __future__ import annotations

"""
Clerk JWT verification dependency for FastAPI.

Usage:
    from auth import get_current_user, ClerkUser

    @app.get("/protected")
    async def protected_route(user: ClerkUser = Depends(get_current_user)):
        return {"user_id": user.user_id}
"""

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from dataclasses import dataclass
import jwt
from jwt import PyJWKClient, PyJWKClientError
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"

# Ensure auth can resolve env vars even if imported before main.py loads dotenv.
load_dotenv(REPO_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env", override=False)

bearer_scheme = HTTPBearer(auto_error=False)
upload_token_scheme = APIKeyHeader(name="X-Upload-Token", auto_error=False)


def _resolve_clerk_jwks_url() -> str:
    explicit = os.environ.get("CLERK_JWKS_URL", "").strip()
    if explicit:
        return explicit

    frontend_api = os.environ.get("CLERK_FRONTEND_API", "").strip().rstrip("/")
    if frontend_api:
        return f"{frontend_api}/.well-known/jwks.json"

    return ""


def _resolve_clerk_issuer() -> str:
    explicit = os.environ.get("CLERK_ISSUER", "").strip().rstrip("/")
    if explicit:
        return explicit

    frontend_api = os.environ.get("CLERK_FRONTEND_API", "").strip().rstrip("/")
    if frontend_api:
        return frontend_api

    jwks_url = _resolve_clerk_jwks_url()
    suffix = "/.well-known/jwks.json"
    if jwks_url.endswith(suffix):
        return jwks_url[: -len(suffix)].rstrip("/")
    return ""


def _normalize_web_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("authorized parties must be HTTP(S) origins")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("authorized party has an invalid port") from exc
    hostname = parsed.hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    default_port = (parsed.scheme.lower() == "http" and port == 80) or (
        parsed.scheme.lower() == "https" and port == 443
    )
    authority = hostname if port is None or default_port else f"{hostname}:{port}"
    return f"{parsed.scheme.lower()}://{authority}"


def _configured_authorized_parties() -> set[str]:
    explicit = [
        value.strip()
        for value in os.environ.get("CLERK_AUTHORIZED_PARTIES", "").split(",")
        if value.strip()
    ]
    if explicit:
        values = explicit
    else:
        frontend_url = os.environ.get("FRONTEND_URL", "").strip()
        if frontend_url:
            values = [frontend_url]
        else:
            # A zero-config fallback is intentionally limited to local development.
            values = ["http://localhost:3000", "http://127.0.0.1:3000"]
    try:
        return {_normalize_web_origin(value) for value in values}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Clerk authorized parties configuration is invalid",
        ) from exc


@lru_cache(maxsize=4)
def _get_jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_keys=True)


@dataclass
class ClerkUser:
    user_id: str
    session_id: Optional[str]
    is_admin: bool = False
    letterboxd_username: Optional[str] = None


def _configured_admin_user_ids() -> set[str]:
    return {
        value.strip()
        for value in os.environ.get("CLERK_ADMIN_USER_IDS", "").split(",")
        if value.strip()
    }


def _payload_grants_admin(payload: dict, user_id: str) -> bool:
    metadata = (
        payload.get("metadata")
        or payload.get("public_metadata")
        or payload.get("publicMetadata")
        or {}
    )
    metadata_admin = isinstance(metadata, dict) and metadata.get("is_admin") is True
    direct_admin = payload.get("is_admin") is True
    return metadata_admin or direct_admin or user_id in _configured_admin_user_ids()


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> ClerkUser:
    """Extract and verify Clerk JWT from Authorization: Bearer <token> header."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    clerk_jwks_url = _resolve_clerk_jwks_url()
    if not clerk_jwks_url or clerk_jwks_url.startswith("/.well-known"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Clerk JWKS URL is not configured on the API",
        )

    try:
        jwks_client = _get_jwks_client(clerk_jwks_url)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        issuer = _resolve_clerk_issuer()
        decode_options = {
            "verify_exp": True,
            "verify_nbf": True,
            "verify_aud": False,
            "verify_iss": bool(issuer),
        }
        decode_kwargs = {
            "algorithms": ["RS256"],
            "options": decode_options,
        }
        if issuer:
            decode_kwargs["issuer"] = issuer
        payload = jwt.decode(token, signing_key.key, **decode_kwargs)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except PyJWKClientError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token signature verification failed: {e}",
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )

    user_id = payload.get("sub")
    session_id = payload.get("sid")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
        )

    authorized_party = payload.get("azp")
    if authorized_party is not None:
        try:
            normalized_party = (
                _normalize_web_origin(authorized_party)
                if isinstance(authorized_party, str)
                else None
            )
        except ValueError:
            normalized_party = None
        if normalized_party not in _configured_authorized_parties():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token authorized party is not allowed",
            )

    is_admin = _payload_grants_admin(payload, user_id)
    raw_letterboxd_username = payload.get("letterboxd_username")
    letterboxd_username = (
        raw_letterboxd_username.strip()
        if isinstance(raw_letterboxd_username, str)
        and raw_letterboxd_username.strip()
        else None
    )

    return ClerkUser(
        user_id=user_id,
        session_id=session_id,
        is_admin=is_admin,
        letterboxd_username=letterboxd_username,
    )


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[ClerkUser]:
    """Same as get_current_user but returns None instead of raising for public routes."""
    if credentials is None:
        return None
    try:
        return get_current_user(credentials)
    except HTTPException:
        return None


def get_admin_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> ClerkUser:
    user = get_current_user(credentials)
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user


def get_upload_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    upload_token: Optional[str] = Depends(upload_token_scheme),
) -> ClerkUser:
    """
    Allow uploads via the normal Clerk bearer token or a trusted ingestion token.
    The ingestion token exists to support a residential-IP companion scraper.
    """
    expected_upload_token = os.environ.get("INGESTION_API_TOKEN", "").strip()
    if upload_token:
        if not expected_upload_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Upload token auth is not configured on the API",
            )
        if not secrets.compare_digest(upload_token, expected_upload_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid upload token",
            )
        return ClerkUser(user_id="ingestion-token", session_id=None, is_admin=True)

    return get_admin_user(credentials)
