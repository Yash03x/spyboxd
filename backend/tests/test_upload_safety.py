from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import zipfile

from fastapi import HTTPException

from main import extract_zip_file


def archive_with(filename: str, content: str = "ok") -> BytesIO:
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(filename, content)
    payload.seek(0)
    return payload


def archive_with_files(files: dict[str, str]) -> BytesIO:
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        for filename, content in files.items():
            archive.writestr(filename, content)
    payload.seek(0)
    return payload


class UploadExtractionTests(unittest.TestCase):
    def test_extracts_a_normal_letterboxd_archive(self) -> None:
        upload = SimpleNamespace(
            filename="profile.zip",
            file=archive_with("profile/ratings.csv", "Name,Year,Rating\nFilm,2026,4"),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            extracted = extract_zip_file(upload, temp_dir)

            self.assertTrue(extracted.endswith("profile"))

    def test_rejects_zip_slip_paths(self) -> None:
        upload = SimpleNamespace(
            filename="profile.zip",
            file=archive_with("../../outside.csv"),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(HTTPException) as raised:
                extract_zip_file(upload, temp_dir)

        self.assertEqual(raised.exception.status_code, 400)

    def test_identical_upload_basenames_get_isolated_extraction_trees(self) -> None:
        first = SimpleNamespace(
            filename="letterboxd-export.zip",
            file=archive_with_files(
                {
                    "bundle/profile.csv": "Username\nfirst\n",
                    "bundle/ratings.csv": "Name\nPrivate First Film\n",
                }
            ),
        )
        second = SimpleNamespace(
            filename="letterboxd-export.zip",
            file=archive_with_files(
                {"bundle/watched.csv": "Name\nSecond Film\n"}
            ),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            first_path = Path(extract_zip_file(first, temp_dir))
            second_path = Path(extract_zip_file(second, temp_dir))

            self.assertNotEqual(first_path, second_path)
            self.assertTrue((first_path / "ratings.csv").is_file())
            self.assertTrue((second_path / "watched.csv").is_file())
            self.assertFalse((second_path / "ratings.csv").exists())
            self.assertFalse((second_path / "profile.csv").exists())


if __name__ == "__main__":
    unittest.main()
