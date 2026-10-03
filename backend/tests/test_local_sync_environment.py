from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from dotenv import dotenv_values

from scripts import local_full_sync
from scripts.local_full_sync import load_local_environment, validate_username


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "username,expected",
    [
        ("filmfan_7", True),
        ("ab", True),
        ("a", False),
        ("film-fan", False),
        ("1234567890123456", False),
    ],
)
def test_residential_sync_uses_the_storable_username_contract(
    username: str,
    expected: bool,
) -> None:
    assert validate_username(username) is expected


def test_local_sync_loads_ignored_root_environment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SPYBOXD_API_BASE_URL=https://api.example.test\n"
        "INGESTION_API_TOKEN=local-upload-token\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("SPYBOXD_API_BASE_URL", raising=False)
    monkeypatch.delenv("INGESTION_API_TOKEN", raising=False)

    load_local_environment(env_file)

    assert os.environ["SPYBOXD_API_BASE_URL"] == "https://api.example.test"
    assert os.environ["INGESTION_API_TOKEN"] == "local-upload-token"


def test_local_sync_does_not_override_explicit_shell_values(
    monkeypatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("INGESTION_API_TOKEN=file-token\n", encoding="utf-8")
    monkeypatch.setenv("INGESTION_API_TOKEN", "shell-token")

    load_local_environment(env_file)

    assert os.environ["INGESTION_API_TOKEN"] == "shell-token"


@pytest.mark.parametrize("skip_liked_content,skip_tags", [(False, False), (True, False), (False, True), (True, True)])
def test_local_sync_only_skips_liked_content_when_explicitly_requested(
    monkeypatch, tmp_path: Path, skip_liked_content: bool, skip_tags: bool,
) -> None:
    scraper = Mock()
    monkeypatch.setattr(local_full_sync, "EnhancedLetterboxdScraper", Mock(return_value=scraper))
    monkeypatch.setattr(local_full_sync, "upload_archive", Mock(return_value={"status": "ok"}))

    result = local_full_sync.sync_profile(
        username="viewer",
        api_base_url="http://localhost:8000",
        upload_token="test-upload-token",
        bearer_token=None,
        output_dir=str(tmp_path),
        skip_liked_content=skip_liked_content,
        skip_tags=skip_tags,
    )

    assert result == {"status": "ok"}
    expected_options = {}
    if skip_liked_content:
        expected_options['skip_liked_content'] = True
    if skip_tags:
        expected_options['skip_tags'] = True
    scraper.scrape_all.assert_called_once_with(**expected_options)


def test_root_example_covers_compose_and_residential_sync() -> None:
    values = dotenv_values(REPO_ROOT / ".env.example")
    expected_names = {
        "POSTGRES_PASSWORD",
        "NEXT_PUBLIC_API_BASE_URL",
        "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
        "CLERK_SECRET_KEY",
        "NEXT_PUBLIC_CLERK_SIGN_IN_URL",
        "NEXT_PUBLIC_CLERK_SIGN_UP_URL",
        "NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL",
        "NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL",
        "SPYBOXD_API_BASE_URL",
        "SPYBOXD_SYNC_CONFIG",
        "INGESTION_API_TOKEN",
        "SPYBOXD_BEARER_TOKEN",
    }

    assert expected_names <= values.keys()


def test_tmdb_example_stays_within_the_runner_limit() -> None:
    values = dotenv_values(REPO_ROOT / "deploy/env/api.env.example")

    assert 1 <= int(values["TMDB_ENRICHMENT_LIMIT"]) <= 100
