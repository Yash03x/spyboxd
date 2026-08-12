from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.resolve_like_targets import resolve


def test_resolver_fetches_an_official_boxd_short_link():
    fetched = []

    def fetch(url):
        fetched.append(url)
        return SimpleNamespace(
            headers={
                "location": (
                    "https://letterboxd.com/filmfan_7/film/"
                    "spider-man-brand-new-day/"
                )
            }
        )

    assert resolve("https://boxd.it/fwSSUD", fetch) == (
        "filmfan_7",
        "spider-man-brand-new-day",
    )
    assert fetched == ["https://boxd.it/fwSSUD"]


@pytest.mark.parametrize(
    "url",
    [
        "http://boxd.it/fwSSUD",
        "https://localhost/fwSSUD",
        "https://127.0.0.1/fwSSUD",
        "https://169.254.169.254/latest/meta-data/",
        "https://boxd.it@127.0.0.1/fwSSUD",
        "https://user:password@boxd.it/fwSSUD",
        "https://boxd.it.evil.example/fwSSUD",
        "https://boxd.it/fwSSUD?next=http://127.0.0.1/",
        "https://boxd.it/fwSSUD/",
    ],
)
def test_resolver_rejects_non_export_urls_before_fetch(url):
    fetched = []

    assert resolve(url, lambda value: fetched.append(value)) == (None, None)
    assert fetched == []
