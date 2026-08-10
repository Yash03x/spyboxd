"""Taking one value out of a file full of production secrets.

Operational scripts on the VPS need DATABASE_URL and nothing else out of
/etc/spyboxd/api.env. Sourcing the file would hand a read-only checker every
credential the API holds, and a `sed` inside a heredoc inside YAML is three
quoting layers deep -- which is where an earlier attempt at this went wrong.
"""
from __future__ import annotations

import pytest

from env_file import read_database_url, read_env_value


def _write(tmp_path, text: str) -> str:
    path = tmp_path / "api.env"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_a_password_containing_equals_and_at_survives(tmp_path) -> None:
    """Split once on the first '=', not matched: production passwords
    routinely contain both characters and a greedy parse mangles the URL."""

    env = _write(
        tmp_path,
        'CLERK_SECRET_KEY=sk_live_do_not_read_me\n'
        'export DATABASE_URL="postgresql+psycopg://user:p=ss@w0rd@db:5432/spyboxd"\n'
        "TMDB_API_KEY='another secret'\n",
    )

    assert read_database_url(env) == "postgresql+psycopg://user:p=ss@w0rd@db:5432/spyboxd"


def test_only_the_requested_key_is_returned(tmp_path) -> None:
    env = _write(tmp_path, "DATABASE_URL=postgresql://x/y\nCLERK_SECRET_KEY=sk_live_secret\n")

    assert read_env_value(env, "DATABASE_URL") == "postgresql://x/y"
    assert read_env_value(env, "NOT_PRESENT") is None


def test_the_last_assignment_wins(tmp_path) -> None:
    """Matching how the file behaves when a service sources it."""

    env = _write(tmp_path, "DATABASE_URL=postgresql://first/db\nDATABASE_URL=postgresql://second/db\n")

    assert read_env_value(env, "DATABASE_URL") == "postgresql://second/db"


def test_a_commented_assignment_is_not_read(tmp_path) -> None:
    env = _write(tmp_path, "# DATABASE_URL=postgresql://commented/db\nDATABASE_URL=postgresql://real/db\n")

    assert read_env_value(env, "DATABASE_URL") == "postgresql://real/db"


def test_single_and_double_quotes_are_unwrapped(tmp_path) -> None:
    assert read_env_value(_write(tmp_path, "K='v'\n"), "K") == "v"
    assert read_env_value(_write(tmp_path, 'K="v"\n'), "K") == "v"
    # An unbalanced quote is part of the value, not a wrapper to strip.
    assert read_env_value(_write(tmp_path, 'K="v\n'), "K") == '"v'


def test_a_file_without_the_url_stops_rather_than_guessing(tmp_path) -> None:
    env = _write(tmp_path, "CLERK_SECRET_KEY=sk_live\n")

    with pytest.raises(SystemExit, match="has no DATABASE_URL"):
        read_database_url(env)


def test_an_empty_assignment_is_absent_rather_than_an_empty_url(tmp_path) -> None:
    """An empty DATABASE_URL would otherwise be exported and fail much later,
    inside SQLAlchemy, with a worse message."""

    with pytest.raises(SystemExit, match="has no DATABASE_URL"):
        read_database_url(_write(tmp_path, "DATABASE_URL=\n"))
