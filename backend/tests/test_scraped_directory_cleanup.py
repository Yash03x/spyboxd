from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.main import _remove_scraped_profile_directory, clear_profile_data


def test_removes_only_the_matching_immediate_profile_directory(tmp_path: Path):
    scrape_root = tmp_path / "scraped"
    target = scrape_root / "target_profile"
    survivor = scrape_root / "survivor"
    target.mkdir(parents=True)
    survivor.mkdir()
    (target / "ratings.csv").write_text("target", encoding="utf-8")
    (survivor / "ratings.csv").write_text("survivor", encoding="utf-8")

    with patch("backend.main.SCRAPED_DATA_DIR", str(scrape_root)):
        _remove_scraped_profile_directory("target_profile")

    assert not target.exists()
    assert (survivor / "ratings.csv").read_text(encoding="utf-8") == "survivor"


@pytest.mark.parametrize(
    "username",
    ["", ".", "..", "../outside", "/tmp/outside", "nested/profile", "nested\\profile"],
)
def test_rejects_non_component_profile_names(tmp_path: Path, username: str):
    scrape_root = tmp_path / "scraped"
    scrape_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")

    with (
        patch("backend.main.SCRAPED_DATA_DIR", str(scrape_root)),
        pytest.raises(HTTPException) as raised,
    ):
        _remove_scraped_profile_directory(username)

    assert raised.value.status_code == 400
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_rejects_matching_symlink_without_following_it(tmp_path: Path):
    scrape_root = tmp_path / "scraped"
    scrape_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    link = scrape_root / "target"
    link.symlink_to(outside, target_is_directory=True)

    with (
        patch("backend.main.SCRAPED_DATA_DIR", str(scrape_root)),
        pytest.raises(HTTPException) as raised,
    ):
        _remove_scraped_profile_directory("target")

    assert raised.value.status_code == 400
    assert link.is_symlink()
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_missing_legacy_scrape_root_is_a_no_op(tmp_path: Path):
    with patch("backend.main.SCRAPED_DATA_DIR", str(tmp_path / "missing")):
        _remove_scraped_profile_directory("target")


def test_clear_endpoint_rejects_unsafe_profile_before_database_clear(tmp_path: Path):
    scrape_root = tmp_path / "scraped"
    scrape_root.mkdir()
    repository = MagicMock()
    repository.get_profile_by_username.return_value = SimpleNamespace(
        id=17,
        username="../outside",
    )

    with (
        patch("backend.main.SCRAPED_DATA_DIR", str(scrape_root)),
        patch("backend.main.ProfileRepository", return_value=repository),
        patch("backend.main.ensure_app_user"),
        pytest.raises(HTTPException) as raised,
    ):
        asyncio.run(
            clear_profile_data(
                "../outside",
                db=MagicMock(),
                _user=MagicMock(),
            )
        )

    assert raised.value.status_code == 400
    repository.clear_profile_data.assert_not_called()
