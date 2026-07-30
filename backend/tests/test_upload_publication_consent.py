import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.auth import ClerkUser
from backend.main import _record_owner_export_publication_consent, upload_files


def test_public_bundle_does_not_require_owner_export_consent():
    bundle = SimpleNamespace(source_kind="full_html_upload", manifest={})

    _record_owner_export_publication_consent(bundle, publish_owner_data=False)

    assert bundle.manifest == {}


def test_owner_export_is_rejected_without_explicit_publication_consent():
    export = SimpleNamespace(source_kind="letterboxd_export", manifest={})

    with pytest.raises(PermissionError, match="publication consent is required"):
        _record_owner_export_publication_consent(export, publish_owner_data=False)

    assert export.manifest == {}


def test_residential_import_rejects_a_bundle_without_a_full_sync_manifest():
    bundle = SimpleNamespace(
        username="viewer",
        source_kind="full_html_upload",
        manifest={},
    )
    uploaded = SimpleNamespace(filename="viewer.zip")
    db = MagicMock()
    profile_repo = MagicMock()

    with (
        patch("backend.main.ProfileRepository", return_value=profile_repo),
        patch("backend.main.extract_zip_file", return_value="/tmp/viewer"),
        patch("backend.main.load_profile_data", return_value=bundle),
        pytest.raises(HTTPException) as raised,
    ):
        asyncio.run(
            upload_files(
                files=[uploaded],
                publish_owner_data=False,
                require_full_sync=True,
                db=db,
                _user=ClerkUser(user_id="admin", session_id=None, is_admin=True),
            )
        )

    assert raised.value.status_code == 400
    assert profile_repo.mock_calls == []
    assert db.mock_calls == []


def test_upload_rejects_owner_export_before_any_database_access_without_consent():
    export = SimpleNamespace(
        username="owner",
        source_kind="letterboxd_export",
        manifest={},
    )
    uploaded = SimpleNamespace(filename="letterboxd-owner.zip")
    db = MagicMock()

    with (
        patch("backend.main.extract_zip_file", return_value="/tmp/export"),
        patch("backend.main.load_profile_data", return_value=export),
        pytest.raises(HTTPException) as raised,
    ):
        asyncio.run(
            upload_files(
                files=[uploaded],
                publish_owner_data=False,
                require_full_sync=False,
                db=db,
                _user=ClerkUser(user_id="admin", session_id=None, is_admin=True),
            )
        )

    assert raised.value.status_code == 400
    assert "publication consent is required" in str(raised.value.detail)
    assert db.mock_calls == []


def test_owner_export_consent_is_recorded_in_sync_manifest():
    export = SimpleNamespace(source_kind="letterboxd_export", manifest={"source": "official"})

    _record_owner_export_publication_consent(export, publish_owner_data=True)

    assert export.manifest["source"] == "official"
    assert export.manifest["publication_consent"]["granted"] is True
    assert export.manifest["publication_consent"]["scope"] == "public_spyboxd_instance"
    assert export.manifest["publication_consent"]["policy_version"] == 1
    assert export.manifest["publication_consent"]["recorded_at"].endswith("Z")
