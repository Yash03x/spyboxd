"""Read one value out of a deployment environment file.

Operational scripts that run on the VPS need DATABASE_URL, which lives in
/etc/spyboxd/api.env alongside every other production secret. They need that
one line and nothing else, so this takes one key rather than sourcing the file
or exporting it into the environment.

Deliberately dependency-free: callers import this *before* importing
`database.connection`, which resolves DATABASE_URL at import time and raises
without one. Anything imported here would have to survive that ordering.

Not parsed with a regex or `sed`. A value may be quoted, may be `export`ed, and
routinely contains '=' and '@' because it holds a password — so the line is
split once on the first '=' and then unwrapped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def read_env_value(env_file: str, key: str) -> Optional[str]:
    """The last assignment of `key` in `env_file`, or None.

    Last rather than first: a later line overrides an earlier one when the file
    is sourced, so anything else would disagree with how the services read it.
    """

    found: Optional[str] = None
    for raw_line in Path(env_file).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        name, separator, value = line.partition("=")
        if not separator or name.strip() != key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        found = value
    return found or None


def read_database_url(env_file: str) -> str:
    """DATABASE_URL from a deployment environment file, or a clear failure."""

    url = read_env_value(env_file, "DATABASE_URL")
    if not url:
        raise SystemExit(f"{env_file} has no DATABASE_URL")
    return url
