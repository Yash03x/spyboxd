import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.main import ClerkUser, app, get_db, get_upload_user, upload_files


def _upload_user() -> ClerkUser:
    return ClerkUser(user_id="ingestion-token", session_id=None, is_admin=True)


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: MagicMock()
    app.dependency_overrides[get_upload_user] = _upload_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_upload_hides_unexpected_exception_details_and_keeps_successful_import(
    caplog,
    client,
):
    secret = "postgresql://spyboxd:super-secret@db/private /srv/spyboxd/internal.py"
    files = [
        SimpleNamespace(filename="good.zip"),
        SimpleNamespace(filename="bad.zip"),
    ]
    profile = SimpleNamespace(id=17)
    bundle = SimpleNamespace(
        username="good",
        source_kind="full_html_upload",
        manifest={},
    )
    profile_repo = MagicMock()
    profile_repo.get_profile_by_username.return_value = None
    profile_repo.create_profile.return_value = profile

    with (
        caplog.at_level(logging.ERROR, logger="spyboxd.api"),
        patch("backend.main.ProfileRepository", return_value=profile_repo),
        patch(
            "backend.main.extract_zip_file",
            side_effect=["/tmp/good", RuntimeError(secret)],
        ),
        patch("backend.main.load_profile_data", return_value=bundle),
        patch("backend.main.unified_data_loader", return_value=23),
        patch("backend.main._refresh_dashboard_snapshot_cache"),
    ):
        response = client.post(
            "/upload/",
            files=[
                ("files", (file.filename, b"zip-placeholder", "application/zip"))
                for file in files
            ],
            data={"publish_owner_data": "false"},
        )

    assert response.status_code == 200
    result = response.json()
    serialized_response = response.text
    assert result["loaded_profiles"] == ["good"]
    assert result["imports"] == [
        {
            "username": "good",
            "source_kind": "full_html_upload",
            "movies_loaded": 23,
        }
    ]
    assert result["errors"] == [
        "Failed to process bad.zip: An unexpected processing error occurred."
    ]
    assert secret not in serialized_response
    assert "super-secret" not in serialized_response
    assert secret in caplog.text


def test_upload_hides_unexpected_exception_details_when_every_import_fails(caplog):
    secret = "SELECT password_hash FROM users at /srv/spyboxd/database.py:91"
    uploaded = SimpleNamespace(filename="bad.zip")

    with (
        caplog.at_level(logging.ERROR, logger="spyboxd.api"),
        patch("backend.main.ProfileRepository"),
        patch("backend.main.extract_zip_file", side_effect=RuntimeError(secret)),
        pytest.raises(HTTPException) as raised,
    ):
        asyncio.run(
            upload_files(
                files=[uploaded],
                publish_owner_data=False,
                require_full_sync=False,
                db=MagicMock(),
                _user=_upload_user(),
            )
        )

    serialized_detail = json.dumps(raised.value.detail)
    assert raised.value.status_code == 400
    assert raised.value.detail == {
        "message": "No profiles could be loaded",
        "errors": [
            "Failed to process bad.zip: An unexpected processing error occurred."
        ],
    }
    assert secret not in serialized_detail
    assert "password_hash" not in serialized_detail
    assert secret in caplog.text
