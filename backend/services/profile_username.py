"""One storage-safe contract for Letterboxd profile usernames.

Every caller that can persist a profile or app-user identity must agree on this
shape.  In particular, accepting a wider value during a rename can otherwise
write an ``app_users.letterboxd_username`` that authentication rejects on the
very next request.
"""

from __future__ import annotations

import re


PROFILE_USERNAME_PATTERN = r"[A-Za-z0-9_]{2,15}"
_PROFILE_USERNAME = re.compile(PROFILE_USERNAME_PATTERN)
_PROFILE_USERNAME_ERROR = (
    "Letterboxd usernames must be 2-15 characters and use only letters, "
    "numbers, or underscores."
)


def canonical_profile_username(
    raw_username: object,
    *,
    allow_at_prefix: bool = False,
) -> str:
    """Return the canonical storable username or raise ``ValueError``.

    Request forms may allow one decorative ``@`` prefix.  Scraper and archive
    paths use :func:`is_valid_profile_username` instead so a value accepted
    there is already canonical and cannot change after validation.
    """

    if not isinstance(raw_username, str):
        raise ValueError(_PROFILE_USERNAME_ERROR)
    username = raw_username.strip()
    if allow_at_prefix and username.startswith("@"):
        username = username[1:]
    if not _PROFILE_USERNAME.fullmatch(username):
        raise ValueError(_PROFILE_USERNAME_ERROR)
    return username


def is_valid_profile_username(value: object) -> bool:
    """Whether ``value`` is already a canonical profile username."""

    if not isinstance(value, str):
        return False
    try:
        return canonical_profile_username(value) == value
    except ValueError:
        return False
