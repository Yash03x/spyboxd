from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from backend import auth


def _credentials() -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="session-token")


def _stub_jwks(monkeypatch) -> None:
    client = SimpleNamespace(
        get_signing_key_from_jwt=lambda _token: SimpleNamespace(key="public-key")
    )
    monkeypatch.setattr(auth, "_get_jwks_client", lambda _url: client)


def test_current_user_validates_exact_issuer_and_authorized_party(monkeypatch):
    monkeypatch.setenv("CLERK_JWKS_URL", "https://clerk.example/.well-known/jwks.json")
    monkeypatch.setenv("CLERK_ISSUER", "https://clerk.example")
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "https://spyboxd.com")
    _stub_jwks(monkeypatch)
    captured = {}

    def decode(_token, _key, **kwargs):
        captured.update(kwargs)
        return {
            "sub": "user_one",
            "sid": "session_one",
            "iss": "https://clerk.example",
            "azp": "https://spyboxd.com",
        }

    monkeypatch.setattr(auth.jwt, "decode", decode)

    user = auth.get_current_user(_credentials())

    assert user.user_id == "user_one"
    assert captured["issuer"] == "https://clerk.example"
    assert captured["options"]["verify_iss"] is True
    assert captured["options"]["verify_nbf"] is True


def test_current_user_rejects_invalid_issuer(monkeypatch):
    monkeypatch.setenv("CLERK_JWKS_URL", "https://clerk.example/.well-known/jwks.json")
    monkeypatch.setenv("CLERK_ISSUER", "https://clerk.example")
    _stub_jwks(monkeypatch)
    monkeypatch.setattr(
        auth.jwt,
        "decode",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            auth.jwt.InvalidIssuerError("Invalid issuer")
        ),
    )

    with pytest.raises(HTTPException) as raised:
        auth.get_current_user(_credentials())

    assert raised.value.status_code == 401
    assert "Invalid issuer" in raised.value.detail


def test_current_user_rejects_unapproved_authorized_party(monkeypatch):
    monkeypatch.setenv("CLERK_JWKS_URL", "https://clerk.example/.well-known/jwks.json")
    monkeypatch.setenv("CLERK_ISSUER", "https://clerk.example")
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "https://spyboxd.com")
    _stub_jwks(monkeypatch)
    monkeypatch.setattr(
        auth.jwt,
        "decode",
        lambda *_args, **_kwargs: {
            "sub": "user_one",
            "sid": "session_one",
            "azp": "https://attacker.example",
        },
    )

    with pytest.raises(HTTPException) as raised:
        auth.get_current_user(_credentials())

    assert raised.value.status_code == 401
    assert raised.value.detail == "Token authorized party is not allowed"


def test_local_development_defaults_accept_localhost_azp(monkeypatch):
    monkeypatch.setenv("CLERK_JWKS_URL", "https://clerk.example/.well-known/jwks.json")
    monkeypatch.delenv("CLERK_ISSUER", raising=False)
    monkeypatch.delenv("CLERK_FRONTEND_API", raising=False)
    monkeypatch.delenv("CLERK_AUTHORIZED_PARTIES", raising=False)
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    _stub_jwks(monkeypatch)
    monkeypatch.setattr(
        auth.jwt,
        "decode",
        lambda *_args, **_kwargs: {
            "sub": "local_user",
            "sid": "local_session",
            "azp": "http://localhost:3000",
        },
    )

    assert auth.get_current_user(_credentials()).user_id == "local_user"
