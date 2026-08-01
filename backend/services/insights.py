from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from itertools import combinations
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy import false, func
from sqlalchemy.orm import Session, load_only

from database.models import (
    Movie,
    MovieEnrichment,
    MovieList,
    MovieListItem,
    MovieWatchProvider,
    Profile,
    ProfileFilm,
    ProfileFollowEdge,
    ProfileSync,
    Review,
    SyncDataset,
    WatchEvent,
    WatchlistItem,
)


ALLOWED_TASTE_DIMENSIONS = {
    "genre",
    "director",
    "actor",
    "language",
    "country",
    "decade",
    "keyword",
    "runtime",
}

# One rated film makes a trait score a perfect 100; below this the number
# says more about coverage than taste, so such traits rank last in alignment.
MIN_ALIGNMENT_SAMPLE = 2

LEGACY_EVENT_SOURCE_KINDS = {
    "legacy_backfill",
    "legacy_rating_backfill",
    "legacy_rating_snapshot",
}
PROVIDER_TYPE_ORDER = ("flatrate", "rent", "buy")
SUPPORTED_PROVIDER_TYPES = set(PROVIDER_TYPE_ORDER)
WORLDWIDE_REGION = "ALL"
TMDB_PROVIDER_LOGO_BASE_URL = "https://image.tmdb.org/t/p/original"
AVAILABILITY_TYPE_ALIASES = {
    "streaming": "flatrate",
    "subscription": "flatrate",
}
TMDB_POSTER_BASE_URL = "https://image.tmdb.org/t/p/w500"
WATCH_TOGETHER_MODES = {
    "watchlist_overlap",
    "unseen_pick",
    "collective_blind_spots",
    "list_mission",
}
# Semantic neighbours: two people watching *different* films that are contextually
# the same thing, close together in time. Only high-signal dimensions qualify --
# "both watched a drama" is not a contextual match, it is a coincidence, and a
# panel that says otherwise is noise. Ordered strongest first; the first
# dimension that matches a pair of films wins, so the stated reason is the
# strongest true one rather than the last one checked.
SEMANTIC_NEIGHBOR_DIMENSIONS = (
    ("director", "Both watched {article} {label} film"),
    ("keyword", "Both explored {label}"),
    ("actor", "Both watched {label}"),
)
SEMANTIC_NEIGHBOR_GAP_DAYS = 21
# TMDB keywords mix themes with production trivia. "Both explored
# duringcreditsstinger" is not an observation about anyone's taste, so the
# non-thematic ones are dropped rather than shown as one.
SEMANTIC_NEIGHBOR_KEYWORD_STOPLIST = {
    "aftercreditsstinger",
    "duringcreditsstinger",
    "woman director",
    "women directors",
    "female director",
    "based on novel or book",
    "based on true story",
    "based on comic",
    "based on young adult novel",
    "live action remake",
    "remake",
    "sequel",
    "prequel",
    "imax",
    "3d",
    "silent film",
}
# A trait shared by this many films across the group is a category, not a
# connection, and pairing every film in it would be quadratic for no insight.
SEMANTIC_NEIGHBOR_MAX_TRAIT_SIZE = 60

SEASON_ORDER = ("winter", "spring", "summer", "autumn")
SEASON_MONTHS = {
    "winter": (12, 1, 2),
    "spring": (3, 4, 5),
    "summer": (6, 7, 8),
    "autumn": (9, 10, 11),
}


class InsightRequestError(ValueError):
    def __init__(self, detail: Any, status_code: int = 400):
        super().__init__(str(detail))
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class StateRow:
    profile_id: int
    username: str
    movie_id: int
    rating: Optional[float]
    liked: bool
    tags: List[str]
    first_watched_date: Optional[date]
    latest_watched_date: Optional[date]
    watch_count: int
    rewatch_count: int
    movie: Movie
    enrichment: Optional[MovieEnrichment]


@dataclass(frozen=True)
class EventRow:
    id: int
    profile_id: int
    username: str
    movie_id: int
    watched_date: date
    logged_date: Optional[date]
    rating: Optional[float]
    liked: bool
    rewatch: bool
    tags: List[str]
    source_kind: str
    movie: Movie

    @property
    def opinion_date(self) -> date:
        """When the opinion was recorded, not when the film was seen.

        Letterboxd lets a member backdate a diary entry to the day they
        actually watched something, so a 2015 watch date can carry a rating
        formed in 2024. Anything charting how taste changed belongs on the
        log date; the watch date is the fallback, since only official account
        exports carry log dates.
        """
        return self.logged_date or self.watched_date


@dataclass(frozen=True)
class ProviderAvailability:
    """A display-ready provider with the countries covered by this record."""

    movie_id: int
    provider_id: int
    provider_name: str
    provider_type: str
    logo_path: Optional[str]
    display_priority: Optional[int]
    regions: Tuple[str, ...]


def _and_unknown(left: Optional[bool], right: Optional[bool]) -> Optional[bool]:
    """Three-valued AND: a known ``False`` decides, an unknown does not.

    Used so "mutual" reads False when one direction is authoritatively absent
    even if the other direction was never observable, instead of pretending an
    unknown is a no.
    """
    if left is False or right is False:
        return False
    if left is None or right is None:
        return None
    return bool(left and right)


@dataclass(frozen=True)
class FollowGraph:
    """Active follow edges among a selected group, loaded once per request.

    A follow edge is a social link one member published on their own
    following/followers pages. It says these two accounts are connected; it is
    not evidence that either member's watch caused the other's. Nothing derived
    from this class may be presented as influence, only as context for a
    co-watch that already exists in the diary data.

    Presence of an edge is positive evidence regardless of import authority,
    because an observed edge cannot be observed by accident. Absence only means
    something when the profile whose page would have listed it carries an
    authoritative social import, so unobservable directions stay ``None``
    rather than collapsing into ``False``.
    """

    # (profile_id, counterpart_username_normalized) for each direction.
    active_following: frozenset
    active_followers: frozenset
    # Profiles whose latest sync owns an authoritative following/followers
    # surface, i.e. the only profiles whose *missing* edges mean anything.
    authoritative_following: frozenset
    authoritative_followers: frozenset
    normalized_username_by_profile_id: Mapping[int, str]
    username_by_profile_id: Mapping[int, str]

    @classmethod
    def unknown(cls, profiles: Sequence[Profile] = ()) -> "FollowGraph":
        """A graph with no observations, so every relationship reads unknown."""
        return cls(
            active_following=frozenset(),
            active_followers=frozenset(),
            authoritative_following=frozenset(),
            authoritative_followers=frozenset(),
            normalized_username_by_profile_id={
                profile.id: profile.username.casefold() for profile in profiles
            },
            username_by_profile_id={
                profile.id: profile.username for profile in profiles
            },
        )

    def has_authoritative_social_sync(self, profile_id: int) -> bool:
        """Whether this profile's own social surface was imported authoritatively."""
        return (
            profile_id in self.authoritative_following
            or profile_id in self.authoritative_followers
        )

    def follows(
        self, source_profile_id: int, target_profile_id: int
    ) -> Optional[bool]:
        """Does ``source`` actively follow ``target``? ``None`` when unobservable.

        ``False`` is only returned when an authoritative import covers the
        direction and did not list the edge. Never read this as a statement
        about who watched what.
        """
        source_normalized = self.normalized_username_by_profile_id.get(source_profile_id)
        target_normalized = self.normalized_username_by_profile_id.get(target_profile_id)
        if source_normalized is None or target_normalized is None:
            return None
        if (source_profile_id, target_normalized) in self.active_following:
            return True
        # The counterpart's own followers page corroborates the same edge.
        if (target_profile_id, source_normalized) in self.active_followers:
            return True
        if (
            source_profile_id in self.authoritative_following
            or target_profile_id in self.authoritative_followers
        ):
            return False
        return None

    def _observed_by(self, left_profile_id: int, right_profile_id: int) -> List[str]:
        return [
            self.username_by_profile_id[profile_id]
            for profile_id in (left_profile_id, right_profile_id)
            if profile_id in self.username_by_profile_id
            and self.has_authoritative_social_sync(profile_id)
        ]

    def relationship(
        self,
        left_profile_id: int,
        right_profile_id: int,
        *,
        left_username: str,
        right_username: str,
        left_date: Optional[date] = None,
        right_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Describe the social link between two profiles in a co-watch event.

        ``follows_earlier_watcher`` is the strongest honest reading available:
        the later watcher already followed the earlier one when this pair of
        diary entries landed. It is a directional hint about reach, not a claim
        that the earlier watch caused the later one, and it is ``None`` whenever
        the order is unknown or the social link is unobservable.
        """
        left_follows_right = self.follows(left_profile_id, right_profile_id)
        right_follows_left = self.follows(right_profile_id, left_profile_id)
        earlier_username: Optional[str] = None
        later_username: Optional[str] = None
        follows_earlier_watcher: Optional[bool] = None
        if left_date is not None and right_date is not None and left_date != right_date:
            if left_date < right_date:
                earlier_username, later_username = left_username, right_username
                follows_earlier_watcher = right_follows_left
            else:
                earlier_username, later_username = right_username, left_username
                follows_earlier_watcher = left_follows_right
        return {
            "a": left_username,
            "b": right_username,
            "a_follows_b": left_follows_right,
            "b_follows_a": right_follows_left,
            "mutual": _and_unknown(left_follows_right, right_follows_left),
            # False means no authoritative social import covers either
            # direction, which is not the same as an observed absence.
            "known": left_follows_right is not None or right_follows_left is not None,
            # Which of the two members' own social imports are authoritative,
            # so a UI can say who the reading is sourced from.
            "observed_by": self._observed_by(left_profile_id, right_profile_id),
            "earlier_watcher": earlier_username,
            "later_watcher": later_username,
            "follows_earlier_watcher": follows_earlier_watcher,
        }


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: Any, digits: int = 2) -> Optional[float]:
    number = _safe_float(value)
    return round(number, digits) if number is not None else None


def _average(values: Iterable[Optional[float]]) -> Optional[float]:
    clean = [value for value in (_safe_float(value) for value in values) if value is not None]
    return sum(clean) / len(clean) if clean else None


def _pearson(left: Sequence[float], right: Sequence[float]) -> Optional[float]:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    denominator = math.sqrt(
        sum((value - left_mean) ** 2 for value in left)
        * sum((value - right_mean) ** 2 for value in right)
    )
    return numerator / denominator if denominator else None


def _as_string_list(value: Any, *, name_key: str = "name") -> List[str]:
    if not isinstance(value, list):
        return []
    output: List[str] = []
    seen = set()
    for item in value:
        if isinstance(item, dict):
            item = item.get(name_key) or item.get("title")
        label = str(item or "").strip()
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            output.append(label)
    return output


def _iso_datetime(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _provider_matches_availability(
    provider: MovieWatchProvider,
    availability: str,
) -> bool:
    wanted = availability.strip().casefold()
    wanted_type = AVAILABILITY_TYPE_ALIASES.get(wanted, wanted)
    return (
        provider.provider_type.casefold() == wanted_type
        or provider.provider_name.casefold() == wanted
    )


def _normalize_availability_filter(value: Optional[str]) -> Optional[str]:
    normalized = str(value or "").strip()
    return None if normalized.casefold() in {"", "all", "any"} else normalized


def _provider_for_availability_reason(
    providers: Sequence[Any],
    availability: Optional[str],
) -> Optional[Any]:
    if not providers:
        return None
    if not availability:
        return providers[0]
    return next(
        (
            provider
            for provider in providers
            if _provider_matches_availability(provider, availability)
        ),
        None,
    )


def _provider_availability_reason(provider: Any, region: str) -> str:
    if region == WORLDWIDE_REGION:
        country_count = len(getattr(provider, "regions", ()) or ())
        country_label = "country" if country_count == 1 else "countries"
        return (
            f"Available from {provider.provider_name} in "
            f"{country_count} {country_label}"
        )
    return f"Available from {provider.provider_name} in {region}"


def _provider_logo_url(value: Any) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith(("https://", "http://")):
        return raw
    return f"{TMDB_PROVIDER_LOGO_BASE_URL}/{raw.lstrip('/')}"


def _provider_priority(value: Any) -> Optional[int]:
    try:
        priority = int(value)
    except (TypeError, ValueError):
        return None
    return priority if priority >= 0 else None


def _raw_watch_provider_results(raw_payload: Any) -> Mapping[str, Any]:
    if not isinstance(raw_payload, Mapping):
        return {}
    watch_providers = raw_payload.get("watch_providers")
    if not isinstance(watch_providers, Mapping):
        return {}
    results = watch_providers.get("results")
    return results if isinstance(results, Mapping) else {}


def _cached_provider_region_codes(raw_payload: Any) -> List[str]:
    """Return cached countries that contain at least one supported offer type."""

    regions: List[str] = []
    for raw_code, country_payload in _raw_watch_provider_results(raw_payload).items():
        code = str(raw_code or "").upper()
        if len(code) != 2 or not code.isalpha() or not isinstance(country_payload, Mapping):
            continue
        if any(isinstance(country_payload.get(kind), list) and country_payload[kind]
               for kind in PROVIDER_TYPE_ORDER):
            regions.append(code)
    return sorted(set(regions))


def _providers_from_cached_tmdb(
    movie_id: int,
    raw_payload: Any,
    *,
    region: str,
) -> List[ProviderAvailability]:
    """Read country availability from the full TMDB payload already in the cache."""

    results = _raw_watch_provider_results(raw_payload)
    requested_region = region.upper()
    region_codes = (
        sorted(
            code.upper()
            for code in results
            if isinstance(code, str) and len(code) == 2 and code.isalpha()
        )
        if requested_region == WORLDWIDE_REGION
        else [requested_region]
    )
    providers: List[ProviderAvailability] = []
    for region_code in region_codes:
        country_payload = results.get(region_code)
        if not isinstance(country_payload, Mapping):
            continue
        for provider_type in PROVIDER_TYPE_ORDER:
            provider_rows = country_payload.get(provider_type)
            if not isinstance(provider_rows, list):
                continue
            for provider in provider_rows:
                if not isinstance(provider, Mapping):
                    continue
                try:
                    provider_id = int(provider.get("provider_id"))
                except (TypeError, ValueError):
                    continue
                provider_name = str(provider.get("provider_name") or "").strip()
                if provider_id < 0 or not provider_name:
                    continue
                providers.append(
                    ProviderAvailability(
                        movie_id=movie_id,
                        provider_id=provider_id,
                        provider_name=provider_name,
                        provider_type=provider_type,
                        logo_path=_provider_logo_url(provider.get("logo_path")),
                        display_priority=_provider_priority(provider.get("display_priority")),
                        regions=(region_code,),
                    )
                )
    return providers


def _merge_provider_availability(
    movie_id: int,
    stored_providers: Sequence[MovieWatchProvider],
    cached_providers: Sequence[ProviderAvailability],
) -> List[ProviderAvailability]:
    """Deduplicate providers while retaining every country where each is offered."""

    grouped: Dict[Tuple[int, str], Dict[str, Any]] = {}
    for provider in [*stored_providers, *cached_providers]:
        provider_type = str(provider.provider_type or "").casefold()
        if provider_type not in SUPPORTED_PROVIDER_TYPES:
            continue
        identity = (int(provider.provider_id), provider_type)
        regions = getattr(provider, "regions", None) or (provider.region,)
        current = grouped.setdefault(
            identity,
            {
                "provider_name": provider.provider_name,
                "logo_path": _provider_logo_url(provider.logo_path),
                "display_priority": provider.display_priority,
                "regions": set(),
            },
        )
        current["regions"].update(
            str(value).upper()
            for value in regions
            if value and len(str(value)) == 2
        )
        candidate_priority = _provider_priority(provider.display_priority)
        current_priority = _provider_priority(current["display_priority"])
        if current_priority is None or (
            candidate_priority is not None and candidate_priority < current_priority
        ):
            current["display_priority"] = candidate_priority
        if not current["logo_path"]:
            current["logo_path"] = _provider_logo_url(provider.logo_path)

    merged = [
        ProviderAvailability(
            movie_id=movie_id,
            provider_id=provider_id,
            provider_name=values["provider_name"],
            provider_type=provider_type,
            logo_path=values["logo_path"],
            display_priority=_provider_priority(values["display_priority"]),
            regions=tuple(sorted(values["regions"])),
        )
        for (provider_id, provider_type), values in grouped.items()
    ]
    return sorted(
        merged,
        key=lambda provider: (
            provider.display_priority is None,
            provider.display_priority if provider.display_priority is not None else 10**9,
            provider.provider_name.casefold(),
            PROVIDER_TYPE_ORDER.index(provider.provider_type),
        ),
    )



def _negated_iso_date(value: str) -> str:
    """Sort key that puts the newest ISO date first.

    ISO dates sort lexically, so reversing them means inverting each digit
    rather than negating a number.
    """

    return "".join(chr(ord("9") - (ord(ch) - ord("0"))) if ch.isdigit() else ch for ch in value)


class InsightsService:
    """Source-backed insight calculations over the additive, event-corrected schema."""

    def __init__(
        self,
        db: Session,
        *,
        allowed_usernames: Optional[Sequence[str]] = None,
        allowed_profile_ids: Optional[Sequence[int]] = None,
    ):
        self.db = db
        self.allowed_profile_ids = (
            {int(profile_id) for profile_id in allowed_profile_ids}
            if allowed_profile_ids is not None
            else None
        )
        self.allowed_usernames = (
            {username.casefold() for username in allowed_usernames}
            if allowed_usernames is not None
            else None
        )

    @staticmethod
    def _profiles_by_normalized_username(
        profiles: Sequence[Profile],
    ) -> Dict[str, Profile]:
        mapping: Dict[str, Profile] = {}
        for profile in profiles:
            normalized = profile.username.casefold()
            existing = mapping.get(normalized)
            if existing is not None and existing.id != profile.id:
                raise InsightRequestError(
                    "Case-insensitive profile username collision requires admin resolution.",
                    status_code=409,
                )
            mapping[normalized] = profile
        return mapping

    def _resolve_profiles(
        self,
        requested: Sequence[str],
        *,
        minimum: int = 1,
        maximum: Optional[int] = None,
    ) -> List[Profile]:
        all_profiles = self.db.query(Profile).all()

        normalized: List[str] = []
        seen = set()
        for raw in requested:
            username = (raw or "").strip()
            key = username.casefold()
            if username and key not in seen:
                normalized.append(username)
                seen.add(key)

        if self.allowed_profile_ids is not None:
            all_profiles = [
                profile
                for profile in all_profiles
                if profile.id in self.allowed_profile_ids
            ]
            by_username = self._profiles_by_normalized_username(all_profiles)
            forbidden = [
                username
                for username in normalized
                if username.casefold() not in by_username
            ]
            if forbidden:
                raise InsightRequestError(
                    {
                        "message": "Track every requested profile before using it in analytics.",
                        "untracked_profiles": forbidden,
                    },
                    status_code=403,
                )
        elif self.allowed_usernames is not None:
            forbidden = [
                username
                for username in normalized
                if username.casefold() not in self.allowed_usernames
            ]
            if forbidden:
                raise InsightRequestError(
                    {
                        "message": "Track every requested profile before using it in analytics.",
                        "untracked_profiles": forbidden,
                    },
                    status_code=403,
                )
            all_profiles = [
                profile
                for profile in all_profiles
                if profile.username.casefold() in self.allowed_usernames
            ]
            by_username = self._profiles_by_normalized_username(all_profiles)
        else:
            by_username = self._profiles_by_normalized_username(all_profiles)

        if not normalized:
            normalized = sorted(
                profile.username
                for profile in all_profiles
                if profile.is_active and profile.scraping_status == "completed"
            )

        unknown = [value for value in normalized if value.casefold() not in by_username]
        if unknown:
            raise InsightRequestError(
                {"message": "One or more profiles were not found", "unknown_profiles": unknown}
            )

        resolved = [by_username[value.casefold()] for value in normalized]
        unavailable = [
            profile.username
            for profile in resolved
            if not profile.is_active or profile.scraping_status != "completed"
        ]
        if unavailable:
            raise InsightRequestError(
                {
                    "message": "One or more profiles are inactive or do not have completed data",
                    "unavailable_profiles": unavailable,
                }
            )

        if len(resolved) < minimum:
            raise InsightRequestError(
                {
                    "message": f"Select at least {minimum} completed profile(s)",
                    "selected_profiles": [profile.username for profile in resolved],
                }
            )
        if maximum is not None and len(resolved) > maximum:
            raise InsightRequestError(
                {
                    "message": f"Select no more than {maximum} profile(s)",
                    "selected_profiles": [profile.username for profile in resolved],
                }
            )
        return resolved

    @staticmethod
    def _profile_ref(profile: Profile, total_films: Optional[int] = None) -> Dict[str, Any]:
        return {
            "username": profile.username,
            "display_name": profile.display_name,
            "avatar_url": profile.profile_image_url,
            "total_films": total_films,
        }

    @staticmethod
    def _movie_summary(
        movie: Movie,
        enrichment: Optional[MovieEnrichment] = None,
    ) -> Dict[str, Any]:
        poster_url = None
        poster_path = str(enrichment.poster_path or "").strip() if enrichment else ""
        if poster_path:
            poster_url = (
                poster_path
                if poster_path.startswith(("http://", "https://"))
                else f"{TMDB_POSTER_BASE_URL}/{poster_path.lstrip('/')}"
            )
        else:
            candidate = str(movie.poster_url or "").strip()
            candidate_lower = candidate.casefold()
            is_letterboxd_image_endpoint = (
                "letterboxd.com/film/" in candidate_lower
                and "/image-" in candidate_lower
            )
            if (
                candidate.startswith(("http://", "https://"))
                and "empty-poster" not in candidate_lower
                and not is_letterboxd_image_endpoint
            ):
                poster_url = candidate
        return {
            "movie_id": movie.id,
            "tmdb_id": movie.tmdb_id,
            "letterboxd_slug": movie.letterboxd_slug,
            "letterboxd_url": movie.letterboxd_url,
            "title": movie.title,
            "year": movie.release_year,
            "poster_url": poster_url,
        }

    def _state_rows(
        self,
        profiles: Sequence[Profile],
        *,
        lightweight_enrichment: bool = False,
        analytical_enrichment: bool = False,
    ) -> List[StateRow]:
        profile_ids = [profile.id for profile in profiles]
        if not profile_ids:
            return []
        query = (
            self.db.query(ProfileFilm, Profile, Movie, MovieEnrichment)
            .join(Profile, Profile.id == ProfileFilm.profile_id)
            .join(Movie, Movie.id == ProfileFilm.movie_id)
            .outerjoin(MovieEnrichment, MovieEnrichment.movie_id == Movie.id)
            .filter(
                ProfileFilm.profile_id.in_(profile_ids),
                ProfileFilm.removed_at.is_(None),
            )
        )
        if lightweight_enrichment:
            # Coverage needs only enrichment presence, while rewatch cards also
            # need the poster. Avoid repeatedly deserializing the much larger
            # TMDB JSON payloads for every profile-film row on these paths.
            query = query.options(
                load_only(MovieEnrichment.movie_id, MovieEnrichment.poster_path)
            )
        elif analytical_enrichment:
            # Taste features need structured metadata but never the large raw
            # TMDB/provider response, overview, or backdrop payload.
            query = query.options(
                load_only(
                    MovieEnrichment.movie_id,
                    MovieEnrichment.poster_path,
                    MovieEnrichment.runtime_minutes,
                    MovieEnrichment.original_language,
                    MovieEnrichment.genres,
                    MovieEnrichment.keywords,
                    MovieEnrichment.credits,
                    MovieEnrichment.production_countries,
                )
            )
        rows = query.all()
        return [
            StateRow(
                profile_id=profile.id,
                username=profile.username,
                movie_id=movie.id,
                rating=_safe_float(profile_film.rating),
                liked=bool(profile_film.is_liked),
                tags=_as_string_list(profile_film.tags),
                first_watched_date=profile_film.first_watched_date,
                latest_watched_date=profile_film.latest_watched_date,
                watch_count=int(profile_film.watch_count or 0),
                rewatch_count=int(profile_film.rewatch_count or 0),
                movie=movie,
                enrichment=enrichment,
            )
            for profile_film, profile, movie, enrichment in rows
        ]

    def _event_rows(self, profiles: Sequence[Profile]) -> List[EventRow]:
        profile_ids = [profile.id for profile in profiles]
        if not profile_ids:
            return []
        rows = (
            self.db.query(WatchEvent, Profile, Movie)
            .join(Profile, Profile.id == WatchEvent.profile_id)
            .join(Movie, Movie.id == WatchEvent.movie_id)
            .filter(
                WatchEvent.profile_id.in_(profile_ids),
                WatchEvent.superseded_at.is_(None),
            )
            .all()
        )
        return [
            EventRow(
                id=event.id,
                profile_id=profile.id,
                username=profile.username,
                movie_id=movie.id,
                watched_date=event.watched_date,
                logged_date=event.logged_date,
                rating=_safe_float(event.rating),
                liked=bool(event.is_liked),
                rewatch=bool(event.is_rewatch),
                tags=_as_string_list(event.tags),
                source_kind=event.source_kind,
                movie=movie,
            )
            for event, profile, movie in rows
        ]

    def _follow_graph(self, profiles: Sequence[Profile]) -> FollowGraph:
        """Load every active follow edge inside the selection in one query.

        Signals run over thousands of films, so the graph is resolved once for
        the selected profiles and then consulted in memory; no event triggers a
        query of its own.
        """
        profile_ids = [profile.id for profile in profiles]
        if not profile_ids or self.db is None:
            return FollowGraph.unknown(profiles)

        normalized_by_profile_id = {
            profile.id: profile.username.casefold() for profile in profiles
        }
        rows = (
            self.db.query(
                ProfileFollowEdge.profile_id,
                ProfileFollowEdge.direction,
                ProfileFollowEdge.counterpart_username_normalized,
            )
            .filter(
                ProfileFollowEdge.profile_id.in_(profile_ids),
                ProfileFollowEdge.counterpart_username_normalized.in_(
                    sorted(set(normalized_by_profile_id.values()))
                ),
                ProfileFollowEdge.removed_at.is_(None),
            )
            .all()
        )
        active_following = set()
        active_followers = set()
        for profile_id, direction, counterpart in rows:
            if direction == "following":
                active_following.add((profile_id, counterpart))
            elif direction == "follower":
                active_followers.add((profile_id, counterpart))

        authoritative_following = set()
        authoritative_followers = set()
        for profile_id, (sync, datasets) in self._latest_sync_context(profiles).items():
            following_dataset = self._dataset(datasets, "following")
            followers_dataset = self._dataset(datasets, "followers")
            if (
                following_dataset is not None
                and following_dataset.is_authoritative
                and not self._dataset_unavailable_reason(
                    sync, following_dataset, "following"
                )
            ):
                authoritative_following.add(profile_id)
            if (
                followers_dataset is not None
                and followers_dataset.is_authoritative
                and not self._dataset_unavailable_reason(
                    sync, followers_dataset, "followers"
                )
            ):
                authoritative_followers.add(profile_id)

        return FollowGraph(
            active_following=frozenset(active_following),
            active_followers=frozenset(active_followers),
            authoritative_following=frozenset(authoritative_following),
            authoritative_followers=frozenset(authoritative_followers),
            normalized_username_by_profile_id=normalized_by_profile_id,
            username_by_profile_id={
                profile.id: profile.username for profile in profiles
            },
        )

    @staticmethod
    def _follow_backed(relationships: Sequence[Mapping[str, Any]]) -> Optional[bool]:
        """Whether any later watcher in this event already followed an earlier one.

        ``True`` records that the social link existed, not that it carried the
        film across. ``False`` needs every ordered pair to be authoritatively
        unconnected; anything unobservable keeps the event undetermined.
        """
        reads = [
            relationship["follows_earlier_watcher"]
            for relationship in relationships
            if relationship["later_watcher"] is not None
        ]
        if not reads:
            return None
        if any(read is True for read in reads):
            return True
        if all(read is False for read in reads):
            return False
        return None

    @staticmethod
    def _follow_graph_summary(
        graph: FollowGraph,
        profiles: Sequence[Profile],
        events: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Count how many gap events sit on an observed follow, and say what is unknown.

        The split is descriptive: a follow-backed gap event is one where the
        later watcher already followed the earlier one. It is never a count of
        films that travelled along the graph, and the undetermined bucket is
        reported rather than folded into either side.
        """
        gap_events = [event for event in events if (event.get("day_gap") or 0) > 0]
        covered = [
            profile.username
            for profile in profiles
            if graph.has_authoritative_social_sync(profile.id)
        ]
        coverage_ratio = len(covered) / len(profiles) if profiles else None
        warnings = [
            "A follow edge is an observed social link, not evidence that one "
            "member's watch caused another's.",
        ]
        if profiles and len(covered) < len(profiles):
            warnings.append(
                f"{len(covered)} of {len(profiles)} selected profiles have an "
                "authoritative following/followers import; pairs without one "
                "stay undetermined rather than counting as unconnected."
            )
        return {
            "gap_events": len(gap_events),
            "follow_backed_gap_events": sum(
                event.get("follow_backed") is True for event in gap_events
            ),
            "coincidental_gap_events": sum(
                event.get("follow_backed") is False for event in gap_events
            ),
            "undetermined_gap_events": sum(
                event.get("follow_backed") is None for event in gap_events
            ),
            "same_day_events": len(events) - len(gap_events),
            "profiles_with_social_sync": covered,
            "social_sync_coverage_ratio": _round(coverage_ratio, 3),
            "warnings": warnings,
        }

    def _latest_sync_context(
        self, profiles: Sequence[Profile]
    ) -> Dict[int, Tuple[Optional[ProfileSync], Dict[str, SyncDataset]]]:
        profile_ids = [profile.id for profile in profiles]
        if not profile_ids:
            return {}

        # Fetch the latest completed syncs and all of their datasets in two
        # bounded queries instead of issuing two queries per profile.
        sync_rows = (
            self.db.query(ProfileSync)
            .filter(
                ProfileSync.profile_id.in_(profile_ids),
                ProfileSync.status == "completed",
                # Incremental sources such as RSS deliberately publish only
                # non-authoritative datasets. Coverage must stay anchored to
                # the newest completed snapshot that owns at least one
                # authoritative surface, regardless of its source label.
                ProfileSync.datasets.any(SyncDataset.is_authoritative.is_(True)),
            )
            .order_by(
                ProfileSync.profile_id.asc(),
                ProfileSync.completed_at.desc().nullslast(),
                ProfileSync.id.desc(),
            )
            .all()
        )
        latest_by_profile: Dict[int, ProfileSync] = {}
        for sync in sync_rows:
            latest_by_profile.setdefault(sync.profile_id, sync)

        # Older installations may have completed legacy sync rows without
        # dataset authority metadata. Preserve their previous fallback while
        # ensuring a newer non-authoritative RSS delta cannot displace a known
        # authoritative baseline.
        missing_profile_ids = [
            profile_id for profile_id in profile_ids if profile_id not in latest_by_profile
        ]
        if missing_profile_ids:
            fallback_rows = (
                self.db.query(ProfileSync)
                .filter(
                    ProfileSync.profile_id.in_(missing_profile_ids),
                    ProfileSync.status == "completed",
                )
                .order_by(
                    ProfileSync.profile_id.asc(),
                    ProfileSync.completed_at.desc().nullslast(),
                    ProfileSync.id.desc(),
                )
                .all()
            )
            for sync in fallback_rows:
                latest_by_profile.setdefault(sync.profile_id, sync)

        datasets_by_sync: Dict[int, Dict[str, SyncDataset]] = defaultdict(dict)
        sync_ids = [sync.id for sync in latest_by_profile.values()]
        if sync_ids:
            for dataset in (
                self.db.query(SyncDataset)
                .filter(SyncDataset.profile_sync_id.in_(sync_ids))
                .all()
            ):
                datasets_by_sync[dataset.profile_sync_id][
                    dataset.dataset_name.casefold()
                ] = dataset

        return {
            profile_id: (
                latest_by_profile.get(profile_id),
                datasets_by_sync.get(latest_by_profile[profile_id].id, {})
                if profile_id in latest_by_profile
                else {},
            )
            for profile_id in profile_ids
        }

    @staticmethod
    def _dataset(
        datasets: Dict[str, SyncDataset], *names: str
    ) -> Optional[SyncDataset]:
        for name in names:
            key = name.casefold()
            if key in datasets:
                return datasets[key]
        for key, value in datasets.items():
            if any(name.casefold() in key for name in names):
                return value
        return None

    @staticmethod
    def _dataset_unavailable_reason(
        sync: Optional[ProfileSync],
        dataset: Optional[SyncDataset],
        *names: str,
    ) -> Optional[str]:
        metadata = dataset.metadata_payload if dataset is not None else None
        if isinstance(metadata, dict):
            reason = str(metadata.get("unavailable_reason") or "").strip()
            if reason:
                return reason

        coverage = sync.coverage if sync is not None else None
        unavailable = coverage.get("unavailable_datasets") if isinstance(coverage, dict) else None
        if isinstance(unavailable, dict):
            for name in names:
                reason = str(unavailable.get(name) or "").strip()
                if reason:
                    return reason
        return None

    @staticmethod
    def _surface(
        surface: str,
        *,
        captured: int,
        expected: Optional[int],
        last_updated: Optional[str],
        authoritative: Optional[bool] = None,
        warnings: Optional[List[str]] = None,
        unavailable_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        warning_list = list(warnings or [])
        unavailable_reason = str(unavailable_reason or "").strip() or None
        availability_status = (
            "unavailable"
            if unavailable_reason
            else "available"
            if authoritative is True
            else "unknown"
        )
        if unavailable_reason:
            warning_list.append(
                f"{surface.replace('_', ' ').title()} source unavailable ({unavailable_reason})."
            )
            warning_list = list(dict.fromkeys(warning_list))

        ratio = None
        # A zero denominator is an authoritative empty surface at best, not a
        # measurable 100% capture ratio. Explicitly unavailable sources also
        # have no meaningful capture ratio, even when prior rows were retained.
        if expected is not None and expected > 0 and not unavailable_reason:
            ratio = min(captured / expected, 1.0)

        if unavailable_reason:
            status = "partial" if captured > 0 else "missing"
        elif authoritative is True and (expected in (None, 0) or ratio in (None, 1.0)):
            status = "complete"
        elif captured > 0:
            status = "partial" if authoritative is not True or (ratio is not None and ratio < 1) else "complete"
        elif authoritative is True and expected == 0:
            status = "complete"
        else:
            status = "missing"

        return {
            "surface": surface,
            "status": status,
            "captured": int(captured),
            "expected": int(expected) if expected is not None else None,
            "ratio": _round(ratio, 3),
            "last_updated": last_updated,
            "warnings": warning_list,
            # Keep the established coverage `status` values for existing
            # clients while exposing source availability additively.
            "availability_status": availability_status,
            "unavailable_reason": unavailable_reason,
        }

    @staticmethod
    def _surface_score(surface: Dict[str, Any]) -> float:
        status = surface["status"]
        if status == "complete":
            return 1.0
        if status == "partial":
            # A complete-looking row count is not complete coverage when the
            # source itself is explicitly non-authoritative.
            #
            # `or 0.5` could not tell "no ratio known" from a ratio of zero, so a
            # surface with nothing in it scored 0.5 and outranked one that had
            # genuinely captured a third of its rows.
            ratio = surface.get("ratio")
            known = 0.5 if ratio is None else float(ratio)
            return min(max(known, 0.25), 0.75)
        if status == "stale":
            return 0.4
        return 0.0

    def _coverage_payload(
        self,
        profiles: Sequence[Profile],
        *,
        states: Optional[Sequence[StateRow]] = None,
        events: Optional[Sequence[EventRow]] = None,
    ) -> Dict[str, Any]:
        sync_context = self._latest_sync_context(profiles)
        state_rows = (
            list(states)
            if states is not None
            else self._state_rows(profiles, lightweight_enrichment=True)
        )
        rows_by_profile: Dict[int, List[StateRow]] = defaultdict(list)
        for row in state_rows:
            rows_by_profile[row.profile_id].append(row)

        event_counts: Dict[int, int] = defaultdict(int)
        rewatch_counts: Dict[int, int] = defaultdict(int)
        if events is not None:
            for event in events:
                event_counts[event.profile_id] += 1
                rewatch_counts[event.profile_id] += int(event.rewatch)
        elif profiles:
            event_aggregates = (
                self.db.query(
                    WatchEvent.profile_id,
                    func.count(WatchEvent.id),
                    func.count(WatchEvent.id).filter(WatchEvent.is_rewatch.is_(True)),
                )
                .filter(
                    WatchEvent.profile_id.in_([profile.id for profile in profiles]),
                    WatchEvent.superseded_at.is_(None),
                )
                .group_by(WatchEvent.profile_id)
                .all()
            )
            for profile_id, event_count, rewatch_count in event_aggregates:
                event_counts[profile_id] = int(event_count or 0)
                rewatch_counts[profile_id] = int(rewatch_count or 0)
        review_counts = dict(
            self.db.query(Review.profile_id, func.count(Review.id))
            .filter(
                Review.profile_id.in_([profile.id for profile in profiles]),
                Review.removed_at.is_(None),
            )
            .group_by(Review.profile_id)
            .all()
        ) if profiles else {}
        watchlist_counts = dict(
            self.db.query(WatchlistItem.profile_id, func.count(WatchlistItem.id))
            .filter(
                WatchlistItem.profile_id.in_([profile.id for profile in profiles]),
                WatchlistItem.removed_at.is_(None),
            )
            .group_by(WatchlistItem.profile_id)
            .all()
        ) if profiles else {}
        list_counts = dict(
            self.db.query(MovieList.profile_id, func.count(MovieList.id))
            .filter(
                MovieList.profile_id.in_([profile.id for profile in profiles]),
                MovieList.removed_at.is_(None),
            )
            .group_by(MovieList.profile_id)
            .all()
        ) if profiles else {}

        profile_payloads: List[Dict[str, Any]] = []
        for profile in profiles:
            state_rows = rows_by_profile[profile.id]
            sync, datasets = sync_context[profile.id]
            last_updated = _iso_datetime(
                (sync.completed_at if sync else None) or profile.last_scraped_at
            )
            ratings_dataset = self._dataset(datasets, "ratings", "films", "watched")
            diary_dataset = self._dataset(datasets, "diary", "watch_events")
            reviews_dataset = self._dataset(datasets, "reviews")
            likes_dataset = self._dataset(datasets, "likes")
            watchlist_dataset = self._dataset(datasets, "watchlist")
            lists_dataset = self._dataset(datasets, "lists")
            metadata_dataset = self._dataset(datasets, "profile", "metadata")

            rated_count = sum(row.rating is not None for row in state_rows)
            liked_count = sum(row.liked for row in state_rows)
            tag_count = sum(bool(row.tags) for row in state_rows)
            enriched_count = sum(row.enrichment is not None for row in state_rows)
            total_watch_count = sum(max(row.watch_count, 1) for row in state_rows)
            total_rewatch_count = sum(row.rewatch_count for row in state_rows)
            expected_watch_events = total_watch_count
            if diary_dataset is not None:
                expected_watch_events = max(
                    expected_watch_events,
                    int(diary_dataset.source_row_count or 0),
                )
            metadata_fields = [
                profile.display_name,
                profile.profile_image_url,
                profile.bio,
                profile.location,
                profile.website,
                profile.join_date,
                profile.followers_count,
                profile.following_count,
            ]
            metadata_count = sum(value not in (None, "") for value in metadata_fields)

            surfaces = [
                self._surface(
                    "profile_metadata",
                    captured=metadata_count,
                    # Bio/location/website/join date are optional on Letterboxd;
                    # an authoritative profile page can therefore be complete with blanks.
                    expected=None,
                    last_updated=last_updated,
                    authoritative=metadata_dataset.is_authoritative if metadata_dataset else False,
                ),
                self._surface(
                    "ratings",
                    captured=rated_count,
                    expected=ratings_dataset.source_row_count if ratings_dataset else None,
                    last_updated=last_updated,
                    authoritative=ratings_dataset.is_authoritative if ratings_dataset else False,
                ),
                self._surface(
                    "watch_events",
                    captured=int(event_counts.get(profile.id, 0)),
                    expected=expected_watch_events,
                    last_updated=last_updated,
                    authoritative=diary_dataset.is_authoritative if diary_dataset else False,
                ),
                self._surface(
                    "rewatches",
                    captured=int(rewatch_counts.get(profile.id, 0)),
                    expected=total_rewatch_count,
                    last_updated=last_updated,
                    authoritative=diary_dataset.is_authoritative if diary_dataset else False,
                ),
                self._surface(
                    "likes",
                    captured=liked_count,
                    expected=None,
                    last_updated=last_updated,
                    authoritative=likes_dataset.is_authoritative if likes_dataset else False,
                ),
                self._surface(
                    "reviews",
                    captured=int(review_counts.get(profile.id, 0)),
                    expected=reviews_dataset.source_row_count if reviews_dataset else None,
                    last_updated=last_updated,
                    authoritative=reviews_dataset.is_authoritative if reviews_dataset else False,
                ),
                self._surface(
                    "tags",
                    captured=tag_count,
                    expected=None,
                    last_updated=last_updated,
                    authoritative=bool(
                        diary_dataset
                        and diary_dataset.is_authoritative
                        and sync
                        and sync.source_kind != "full_html_upload"
                    ),
                    warnings=(
                        ["The public HTML sync does not expose diary tags."]
                        if sync and sync.source_kind == "full_html_upload"
                        else []
                    ),
                ),
                self._surface(
                    "watchlist",
                    captured=int(watchlist_counts.get(profile.id, 0)),
                    expected=watchlist_dataset.source_row_count if watchlist_dataset else None,
                    last_updated=last_updated,
                    authoritative=watchlist_dataset.is_authoritative if watchlist_dataset else False,
                    unavailable_reason=self._dataset_unavailable_reason(
                        sync,
                        watchlist_dataset,
                        "watchlist",
                    ),
                ),
                self._surface(
                    "lists",
                    captured=int(list_counts.get(profile.id, 0)),
                    expected=lists_dataset.source_row_count if lists_dataset else None,
                    last_updated=last_updated,
                    authoritative=lists_dataset.is_authoritative if lists_dataset else False,
                    unavailable_reason=self._dataset_unavailable_reason(
                        sync,
                        lists_dataset,
                        "lists",
                        "list_items",
                    ),
                ),
                self._surface(
                    "tmdb",
                    captured=enriched_count,
                    expected=len(state_rows),
                    last_updated=last_updated,
                    authoritative=enriched_count == len(state_rows) and bool(state_rows),
                ),
            ]
            score = round(
                100 * sum(self._surface_score(surface) for surface in surfaces) / len(surfaces)
            )
            profile_payloads.append(
                {
                    "profile": self._profile_ref(profile, len(state_rows)),
                    "overall_score": score,
                    "surfaces": surfaces,
                }
            )

        def surface_values(name: str) -> List[Dict[str, Any]]:
            return [
                next(surface for surface in item["surfaces"] if surface["surface"] == name)
                for item in profile_payloads
            ]

        event_surfaces = surface_values("watch_events") if profile_payloads else []
        rewatch_surfaces = surface_values("rewatches") if profile_payloads else []
        watchlist_surfaces = surface_values("watchlist") if profile_payloads else []
        list_surfaces = surface_values("lists") if profile_payloads else []
        tmdb_surfaces = surface_values("tmdb") if profile_payloads else []
        ratings_surfaces = surface_values("ratings") if profile_payloads else []

        def readiness(
            feature: str,
            required: Sequence[Dict[str, Any]],
            *,
            warnings: Optional[List[str]] = None,
        ) -> Dict[str, Any]:
            missing = [surface for surface in required if surface["status"] == "missing"]
            partial = [surface for surface in required if surface["status"] in {"partial", "stale"}]
            if missing:
                status = "blocked"
            elif partial:
                status = "partial"
            else:
                status = "ready"
            score = round(
                100 * sum(self._surface_score(surface) for surface in required) / max(len(required), 1)
            )
            blockers = list(
                dict.fromkeys(
                    f"{surface['surface']} is unavailable for one or more selected profiles"
                    for surface in missing
                )
            )
            warning_list = list(
                dict.fromkeys(
                    [
                        *(warnings or []),
                        *(
                            f"{surface['surface']} coverage is partial"
                            for surface in partial
                        ),
                    ]
                )
            )
            return {
                "feature": feature,
                "status": status,
                "score": score,
                "blockers": blockers,
                "warnings": warning_list,
            }

        watch_together_readiness = readiness("watch_together", ratings_surfaces)
        incomplete_watchlists = [
            surface for surface in watchlist_surfaces if surface["status"] != "complete"
        ]
        if incomplete_watchlists and watch_together_readiness["status"] != "blocked":
            watch_together_readiness["status"] = "partial"
            watch_together_readiness["score"] = round(
                100
                * sum(
                    self._surface_score(surface)
                    for surface in [*ratings_surfaces, *watchlist_surfaces]
                )
                / max(len(ratings_surfaces) + len(watchlist_surfaces), 1)
            )
            watch_together_readiness["warnings"] = list(
                dict.fromkeys(
                    [
                        *watch_together_readiness["warnings"],
                        "Watchlist overlap requires an authoritative watchlist import for every selected profile.",
                    ]
                )
            )

        taste_readiness = readiness("taste_dna", ratings_surfaces)
        incomplete_tmdb = [
            surface for surface in tmdb_surfaces if surface["status"] != "complete"
        ]
        if incomplete_tmdb and taste_readiness["status"] != "blocked":
            taste_readiness["status"] = "partial"
            taste_readiness["score"] = round(
                100
                * sum(
                    self._surface_score(surface)
                    for surface in [*ratings_surfaces, *tmdb_surfaces]
                )
                / max(len(ratings_surfaces) + len(tmdb_surfaces), 1)
            )
            taste_readiness["warnings"] = list(
                dict.fromkeys(
                    [
                        *taste_readiness["warnings"],
                        "Decade and rating-shape traits remain available without TMDB.",
                    ]
                )
            )

        feature_readiness = [
            readiness("spy_signals", event_surfaces),
            readiness("pair_dossier", [*ratings_surfaces, *event_surfaces]),
            readiness("signal_calendar", event_surfaces),
            readiness("rewatch_echoes", [*event_surfaces, *rewatch_surfaces]),
            readiness("taste_timeline", [*ratings_surfaces, *event_surfaces]),
            readiness("list_mission", [*ratings_surfaces, *list_surfaces]),
            watch_together_readiness,
            taste_readiness,
        ]
        overall_score = round(
            sum(item["overall_score"] for item in profile_payloads) / max(len(profile_payloads), 1)
        )
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "overall_score": overall_score,
            "profiles": profile_payloads,
            "feature_readiness": feature_readiness,
        }

    def data_coverage(self, requested: Sequence[str]) -> Dict[str, Any]:
        profiles = self._resolve_profiles(requested, minimum=1)
        return self._coverage_payload(profiles)

    def _feature_coverage(
        self,
        profiles: Sequence[Profile],
        feature: str,
        events: Optional[Sequence[EventRow]] = None,
        states: Optional[Sequence[StateRow]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        event_rows = list(events) if events is not None else self._event_rows(profiles)
        payload = payload or self._coverage_payload(
            profiles,
            states=states,
            events=event_rows,
        )
        readiness = next(
            item for item in payload["feature_readiness"] if item["feature"] == feature
        )
        source_kinds = {row.source_kind for row in event_rows}
        warnings = list(dict.fromkeys(readiness["warnings"]))
        if (
            feature in {
                "spy_signals",
                "pair_dossier",
                "signal_calendar",
                "rewatch_echoes",
                "taste_timeline",
            }
            and source_kinds & LEGACY_EVENT_SOURCE_KINDS
        ):
            warnings.append(
                "Some watch dates come from the legacy one-date-per-film backfill; run a fresh full sync for complete rewatch history."
            )
        expected_event_total = sum(
            int(surface["expected"] if surface["expected"] is not None else surface["captured"])
            for profile_payload in payload["profiles"]
            for surface in profile_payload["surfaces"]
            if surface["surface"] == "watch_events"
        )
        total_watch_events = max(expected_event_total, len(event_rows))
        last_updates = [
            profile.last_scraped_at for profile in profiles if profile.last_scraped_at is not None
        ]
        return {
            "status": readiness["status"],
            "score": readiness["score"],
            "dated_watch_events": len(event_rows),
            "total_watch_events": total_watch_events,
            "blockers": list(dict.fromkeys(readiness["blockers"])),
            "warnings": list(dict.fromkeys(warnings)),
            "last_updated": _iso_datetime(max(last_updates)) if last_updates else None,
        }

    @staticmethod
    def _comparison(
        movie: Movie,
        rows: Sequence[StateRow],
        events: Sequence[EventRow],
        reviews: Dict[Tuple[int, int], Review],
    ) -> Dict[str, Any]:
        event_by_profile: Dict[int, List[EventRow]] = defaultdict(list)
        for event in events:
            event_by_profile[event.profile_id].append(event)
        observations = []
        for row in sorted(rows, key=lambda item: item.username.casefold()):
            review = reviews.get((row.profile_id, row.movie_id))
            observations.append(
                {
                    "username": row.username,
                    "rating": _round(row.rating, 1),
                    "watched_dates": sorted(
                        event.watched_date.isoformat()
                        for event in event_by_profile.get(row.profile_id, [])
                    ),
                    "liked": row.liked,
                    "rewatch_count": row.rewatch_count,
                    "review_text": review.review_text if review else None,
                    "contains_spoilers": bool(review.contains_spoilers) if review else False,
                    "review_date": (
                        review.published_date.isoformat()
                        if review and review.published_date
                        else None
                    ),
                }
            )
        ratings = [row.rating for row in rows if row.rating is not None]
        minimum_gap = None
        profile_event_lists = [
            profile_events
            for profile_events in event_by_profile.values()
            if profile_events
        ]
        if len(profile_event_lists) >= 2:
            minimum_gap = min(
                abs((left.watched_date - right.watched_date).days)
                for left_events, right_events in combinations(profile_event_lists, 2)
                for left in left_events
                for right in right_events
            )
        return {
            "movie": InsightsService._movie_summary(
                movie,
                next((row.enrichment for row in rows if row.enrichment is not None), None),
            ),
            "observations": observations,
            "rating_gap": _round(max(ratings) - min(ratings), 1) if len(ratings) >= 2 else None,
            "minimum_watch_gap_days": minimum_gap,
        }

    @staticmethod
    def _event_payload(
        movie: Movie,
        participants: Sequence[EventRow],
        start_date: date,
        end_date: date,
        pair_count: int,
        follow_graph: Optional[FollowGraph] = None,
    ) -> Dict[str, Any]:
        by_profile: Dict[int, EventRow] = {}
        for participant in participants:
            current = by_profile.get(participant.profile_id)
            if current is None or (
                participant.rating is not None and current.rating is None
            ):
                by_profile[participant.profile_id] = participant
        unique = sorted(
            by_profile.values(),
            key=lambda item: (item.watched_date, item.username.casefold()),
        )
        ratings = [item.rating for item in unique if item.rating is not None]

        # Order the pair by each profile's earliest watch inside this window,
        # which is what "watched after" can be said about; the displayed
        # participant row may be a later, better-rated entry for the same
        # profile.
        graph = follow_graph or FollowGraph.unknown()
        earliest_by_profile: Dict[int, date] = {}
        for participant in participants:
            current_date = earliest_by_profile.get(participant.profile_id)
            if current_date is None or participant.watched_date < current_date:
                earliest_by_profile[participant.profile_id] = participant.watched_date
        relationships = [
            graph.relationship(
                left.profile_id,
                right.profile_id,
                left_username=left.username,
                right_username=right.username,
                left_date=earliest_by_profile[left.profile_id],
                right_date=earliest_by_profile[right.profile_id],
            )
            for left, right in combinations(unique, 2)
        ]
        return {
            "title": movie.title,
            "year": movie.release_year,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "profile_count": len(unique),
            "pair_count": pair_count,
            "profiles": sorted(item.username for item in unique),
            "participants": [
                {
                    "username": item.username,
                    "rating": _round(item.rating, 1),
                    "watched_date": item.watched_date.isoformat(),
                    "is_rewatch": item.rewatch,
                }
                for item in unique
            ],
            "average_rating": _round(_average(ratings), 2),
            "max_rating_gap": _round(max(ratings) - min(ratings), 2) if len(ratings) >= 2 else None,
            "rewatch_count": sum(item.rewatch for item in participants),
            "day_gap": (end_date - start_date).days,
            # Social context for the co-watch, additive to the timing evidence
            # above. `follow_relationship` is the two-profile case; group events
            # keep every pair in `follow_relationships` instead of inventing a
            # single relationship that does not exist.
            "follow_relationship": relationships[0] if len(unique) == 2 else None,
            "follow_relationships": relationships,
            "follows_earlier_watcher": (
                relationships[0]["follows_earlier_watcher"] if len(unique) == 2 else None
            ),
            "follow_backed": InsightsService._follow_backed(relationships),
        }

    def _matched_events(
        self,
        events: Sequence[EventRow],
        *,
        gap_days: int,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        follow_graph: Optional[FollowGraph] = None,
    ) -> List[Dict[str, Any]]:
        by_movie: Dict[int, List[EventRow]] = defaultdict(list)
        for event in events:
            by_movie[event.movie_id].append(event)

        matches: List[Dict[str, Any]] = []
        for movie_events in by_movie.values():
            movie = movie_events[0].movie
            by_date: Dict[date, List[EventRow]] = defaultdict(list)
            for event in movie_events:
                by_date[event.watched_date].append(event)
            dates = sorted(by_date)
            for start_index, start in enumerate(dates):
                same_day_profiles = {event.profile_id for event in by_date[start]}
                if len(same_day_profiles) >= 2:
                    pair_count = len(same_day_profiles) * (len(same_day_profiles) - 1) // 2
                    if (from_date is None or start >= from_date) and (to_date is None or start <= to_date):
                        matches.append(
                            self._event_payload(
                                movie,
                                by_date[start],
                                start,
                                start,
                                pair_count,
                                follow_graph,
                            )
                        )
                for end in dates[start_index + 1:]:
                    distance = (end - start).days
                    if distance > gap_days:
                        break
                    left_profiles = {event.profile_id for event in by_date[start]}
                    right_profiles = {event.profile_id for event in by_date[end]}
                    cross_date_pairs = {
                        tuple(sorted((left, right)))
                        for left in left_profiles
                        for right in right_profiles
                        if left != right
                    }
                    pair_count = len(cross_date_pairs)
                    combined_profiles = left_profiles | right_profiles
                    if pair_count < 1 or len(combined_profiles) < 2:
                        continue
                    if (from_date is not None and start < from_date) or (to_date is not None and start > to_date):
                        continue
                    matches.append(
                        self._event_payload(
                            movie,
                            [*by_date[start], *by_date[end]],
                            start,
                            end,
                            pair_count,
                            follow_graph,
                        )
                    )
        matches.sort(
            key=lambda item: (
                item["start_date"],
                item["profile_count"],
                item["pair_count"],
                item["title"],
            ),
            reverse=True,
        )
        return matches

    @staticmethod
    def _classified_daily_events(events: Sequence[EventRow]) -> List[Dict[str, Any]]:
        """Collapse duplicate same-day rows and classify only what the import proves.

        ``first_known_watch`` deliberately does not claim that a member had never
        watched the film before. It means this is their earliest imported,
        unmarked event. A Letterboxd rewatch flag always wins; otherwise an event
        after an earlier imported date is classified as a rewatch from observed
        history.
        """

        grouped: Dict[Tuple[int, int], Dict[date, List[EventRow]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for event in events:
            grouped[(event.profile_id, event.movie_id)][event.watched_date].append(event)

        classified: List[Dict[str, Any]] = []
        for (_profile_id, _movie_id), events_by_date in grouped.items():
            has_earlier_observed_date = False
            for watched_date in sorted(events_by_date):
                same_day = events_by_date[watched_date]
                explicitly_rewatched = any(item.rewatch for item in same_day)
                if explicitly_rewatched:
                    watch_kind = "rewatch"
                    basis = "letterboxd_rewatch_flag"
                elif has_earlier_observed_date:
                    watch_kind = "rewatch"
                    basis = "earlier_observed_event"
                else:
                    watch_kind = "first_known_watch"
                    basis = "earliest_observed_unmarked_event"

                representative = sorted(
                    same_day,
                    key=lambda item: (
                        not item.rewatch,
                        item.rating is None,
                        not item.liked,
                        item.id,
                    ),
                )[0]
                classified.append(
                    {
                        "event": representative,
                        "watched_date": watched_date,
                        "rating": next(
                            (
                                item.rating
                                for item in sorted(same_day, key=lambda row: row.id)
                                if item.rating is not None
                            ),
                            None,
                        ),
                        "liked": any(item.liked for item in same_day),
                        "is_rewatch": watch_kind == "rewatch",
                        "watch_kind": watch_kind,
                        "classification_basis": basis,
                    }
                )
                has_earlier_observed_date = True

        return sorted(
            classified,
            key=lambda item: (
                item["event"].movie_id,
                item["watched_date"],
                item["event"].username.casefold(),
            ),
        )

    def rewatch_echoes(
        self,
        requested: Sequence[str],
        *,
        gap_days: int,
        limit: int,
    ) -> Dict[str, Any]:
        profiles = self._resolve_profiles(requested, minimum=2)
        events = self._event_rows(profiles)
        states = self._state_rows(profiles, lightweight_enrichment=True)
        enrichment_by_movie = {
            state.movie_id: state.enrichment
            for state in states
            if state.enrichment is not None
        }
        classified = self._classified_daily_events(events)
        follow_graph = self._follow_graph(profiles)

        by_movie: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for item in classified:
            by_movie[item["event"].movie_id].append(item)

        echoes: List[Dict[str, Any]] = []
        for movie_id, movie_events in by_movie.items():
            for left, right in combinations(movie_events, 2):
                left_event: EventRow = left["event"]
                right_event: EventRow = right["event"]
                if left_event.profile_id == right_event.profile_id:
                    continue
                day_gap = abs((right["watched_date"] - left["watched_date"]).days)
                if day_gap > gap_days:
                    continue
                if not (left["is_rewatch"] or right["is_rewatch"]):
                    continue

                ordered = sorted(
                    [left, right],
                    key=lambda item: (
                        item["watched_date"],
                        item["event"].username.casefold(),
                    ),
                )
                start_date = ordered[0]["watched_date"]
                end_date = ordered[-1]["watched_date"]
                timing = "same_day" if day_gap == 0 else "within_gap"
                pattern = (
                    "rewatch_plus_rewatch"
                    if all(item["is_rewatch"] for item in ordered)
                    else "first_known_plus_rewatch"
                )
                identity = "|".join(
                    [
                        str(movie_id),
                        *(f"{item['event'].profile_id}:{item['watched_date'].isoformat()}"
                          for item in ordered),
                    ]
                )
                relationship = follow_graph.relationship(
                    ordered[0]["event"].profile_id,
                    ordered[-1]["event"].profile_id,
                    left_username=ordered[0]["event"].username,
                    right_username=ordered[-1]["event"].username,
                    left_date=ordered[0]["watched_date"],
                    right_date=ordered[-1]["watched_date"],
                )
                echoes.append(
                    {
                        # Stable UI identifier only; preserve the public 16-hex
                        # shape without SHA-1 over profile-associated metadata.
                        "echo_id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
                        "pattern": pattern,
                        "timing": timing,
                        "day_gap": day_gap,
                        "movie": self._movie_summary(
                            ordered[0]["event"].movie,
                            enrichment_by_movie.get(movie_id),
                        ),
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "participants": [
                            {
                                "username": item["event"].username,
                                "watched_date": item["watched_date"].isoformat(),
                                "rating": _round(item["rating"], 1),
                                "liked": item["liked"],
                                "is_rewatch": item["is_rewatch"],
                                "watch_kind": item["watch_kind"],
                                "classification_basis": item["classification_basis"],
                                "timing_role": (
                                    "same_day"
                                    if day_gap == 0
                                    else "leader"
                                    if item is ordered[0]
                                    else "follower"
                                ),
                            }
                            for item in ordered
                        ],
                        # Who follows whom, alongside the timing the echo
                        # already proves. Neither field asserts that the
                        # earlier watch prompted the later one.
                        "follow_relationship": relationship,
                        "follows_earlier_watcher": relationship["follows_earlier_watcher"],
                        "follow_backed": self._follow_backed([relationship]),
                    }
                )

        echoes.sort(
            key=lambda item: (
                -date.fromisoformat(item["end_date"]).toordinal(),
                -date.fromisoformat(item["start_date"]).toordinal(),
                item["day_gap"],
                item["movie"]["title"].casefold(),
                tuple(participant["username"].casefold() for participant in item["participants"]),
            )
        )
        total_echoes = len(echoes)
        returned_echoes = echoes[:limit]
        coverage = self._feature_coverage(
            profiles,
            "rewatch_echoes",
            events,
            states,
        )
        date_coverage_ratio = (
            min(
                coverage["dated_watch_events"]
                / max(coverage["total_watch_events"], 1),
                1.0,
            )
            if coverage["total_watch_events"]
            else None
        )
        if coverage["dated_watch_events"] < coverage["total_watch_events"]:
            coverage["warnings"] = list(
                dict.fromkeys(
                    [
                        *coverage["warnings"],
                        "First-known means earliest imported Diary event; undated watches cannot be ordered.",
                    ]
                )
            )

        return {
            "selected_profiles": [profile.username for profile in profiles],
            "gap_days": gap_days,
            "coverage": coverage,
            "summary": {
                "echoes": total_echoes,
                "returned_echoes": len(returned_echoes),
                "movies": len({item["movie"]["movie_id"] for item in echoes}),
                "same_day": sum(item["timing"] == "same_day" for item in echoes),
                "within_gap": sum(item["timing"] == "within_gap" for item in echoes),
                "first_known_plus_rewatch": sum(
                    item["pattern"] == "first_known_plus_rewatch" for item in echoes
                ),
                "rewatch_plus_rewatch": sum(
                    item["pattern"] == "rewatch_plus_rewatch" for item in echoes
                ),
                "date_coverage_ratio": _round(date_coverage_ratio, 3),
            },
            "follow_graph": self._follow_graph_summary(follow_graph, profiles, echoes),
            "echoes": returned_echoes,
        }

    def pair_dossier(self, requested: Sequence[str], *, gap_days: int) -> Dict[str, Any]:
        profiles = self._resolve_profiles(requested, minimum=2, maximum=2)
        states = self._state_rows(profiles, lightweight_enrichment=True)
        events = self._event_rows(profiles)
        states_by_movie: Dict[int, List[StateRow]] = defaultdict(list)
        events_by_movie: Dict[int, List[EventRow]] = defaultdict(list)
        for row in states:
            states_by_movie[row.movie_id].append(row)
        for row in events:
            events_by_movie[row.movie_id].append(row)

        shared = {
            movie_id: rows
            for movie_id, rows in states_by_movie.items()
            if len({row.profile_id for row in rows}) == 2
        }
        rated_shared = {
            movie_id: rows
            for movie_id, rows in shared.items()
            if len([row for row in rows if row.rating is not None]) == 2
        }
        ordered_profile_ids = [profile.id for profile in profiles]
        left_ratings: List[float] = []
        right_ratings: List[float] = []
        rating_gaps: List[float] = []
        for rows in rated_shared.values():
            by_profile = {row.profile_id: row for row in rows}
            left = by_profile[ordered_profile_ids[0]].rating
            right = by_profile[ordered_profile_ids[1]].rating
            if left is not None and right is not None:
                left_ratings.append(left)
                right_ratings.append(right)
                rating_gaps.append(abs(left - right))

        correlation = _pearson(left_ratings, right_ratings)
        average_gap = _average(rating_gaps)
        shared_component = min(len(shared) / 20, 1.0)
        correlation_component = (correlation + 1) / 2 if correlation is not None else 0.5
        gap_component = max(0.0, 1.0 - ((average_gap or 0) / 2.5))

        follow_graph = self._follow_graph(profiles)
        matched = self._matched_events(
            events,
            gap_days=gap_days,
            follow_graph=follow_graph,
        )
        timing_component = min(len(matched) / max(len(shared), 1), 1.0)
        alignment_score = 100 * (
            0.45 * correlation_component
            + 0.25 * shared_component
            + 0.20 * timing_component
            + 0.10 * gap_component
        )

        review_rows = (
            self.db.query(Review)
            .filter(
                Review.profile_id.in_(ordered_profile_ids),
                Review.movie_id.in_(list(shared) or [-1]),
                Review.removed_at.is_(None),
            )
            .order_by(Review.published_date.desc(), Review.id.desc())
            .all()
        )
        reviews: Dict[Tuple[int, int], Review] = {}
        for review in review_rows:
            if review.movie_id is not None:
                reviews.setdefault((review.profile_id, review.movie_id), review)

        comparisons = [
            self._comparison(
                rows[0].movie,
                rows,
                events_by_movie.get(movie_id, []),
                reviews,
            )
            for movie_id, rows in rated_shared.items()
        ]
        agreements = sorted(
            comparisons,
            key=lambda item: (
                item["rating_gap"] if item["rating_gap"] is not None else 99,
                -(_average(obs["rating"] for obs in item["observations"]) or 0),
                item["movie"]["title"],
            ),
        )[:24]
        disagreements = sorted(
            [item for item in comparisons if (item["rating_gap"] or 0) > 0],
            key=lambda item: (
                -(item["rating_gap"] or 0),
                item["movie"]["title"],
            ),
        )[:24]

        influence_paths: List[Dict[str, Any]] = []
        direction_counts: Dict[str, int] = defaultdict(int)
        for movie_id, movie_events in events_by_movie.items():
            # One observation per person per film, taken from their EARLIEST
            # viewing. This used to be a cross product over raw watch events,
            # and 4,948 (profile, film) pairs in the tracked library carry more
            # than one event, so a film someone had rewatched six times cast six
            # votes for who leads while the other person's single viewing cast
            # one. `directional_leader` was measuring rewatching, not sequence.
            # A rewatch also cannot make anyone earlier, so first viewings are
            # the only ones that answer the question being asked.
            earliest_by_profile = self._earliest_event_per_profile(movie_events)
            if len(earliest_by_profile) < 2:
                continue
            left = earliest_by_profile.get(ordered_profile_ids[0])
            right = earliest_by_profile.get(ordered_profile_ids[1])
            if left is None or right is None:
                continue
            delta = (right.watched_date - left.watched_date).days
            if delta == 0 or abs(delta) > gap_days:
                continue
            leader, follower = (left, right) if delta > 0 else (right, left)
            direction_counts[leader.username] += 1
            influence_paths.append(
                {
                    "leader": leader.username,
                    "follower": follower.username,
                    "movie": self._movie_summary(
                        leader.movie,
                        next(
                            (
                                row.enrichment
                                for row in states_by_movie.get(movie_id, [])
                                if row.enrichment is not None
                            ),
                            None,
                        ),
                    ),
                    "leader_date": leader.watched_date.isoformat(),
                    "follower_date": follower.watched_date.isoformat(),
                    "gap_days": abs(delta),
                    # `leader`/`follower` here are watch order, not the social
                    # graph. This field is the social question: was the later
                    # watcher already following the earlier one? None when that
                    # is unobservable.
                    "follows_earlier_watcher": follow_graph.follows(
                        follower.profile_id, leader.profile_id
                    ),
                }
            )
        # Newest first. Ordering by gap and then by *ascending* leader date
        # filled the panel with the pair's oldest one-day-apart films and never
        # reached recent activity, however active they had been lately; the
        # tight gap remains the tiebreaker within a day.
        influence_paths.sort(
            key=lambda item: (
                _negated_iso_date(item["leader_date"]),
                item["gap_days"],
                item["movie"]["title"],
            )
        )

        monthly: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"ratings_left": [], "ratings_right": [], "gaps": [], "overlap_count": 0}
        )
        for event in matched:
            month = event["start_date"][:7]
            observations = event["participants"]
            by_username = {item["username"]: item for item in observations}
            if all(profile.username in by_username for profile in profiles):
                left = by_username[profiles[0].username]["rating"]
                right = by_username[profiles[1].username]["rating"]
                monthly[month]["overlap_count"] += 1
                if left is not None and right is not None:
                    monthly[month]["ratings_left"].append(float(left))
                    monthly[month]["ratings_right"].append(float(right))
                    monthly[month]["gaps"].append(abs(float(left) - float(right)))
        monthly_alignment = [
            {
                "month": month,
                "overlap_count": values["overlap_count"],
                "correlation": _round(_pearson(values["ratings_left"], values["ratings_right"]), 2),
                "average_rating_gap": _round(_average(values["gaps"]), 2),
            }
            for month, values in sorted(monthly.items())
        ]

        directional_leader = None
        if direction_counts:
            ranked = sorted(direction_counts.items(), key=lambda item: (-item[1], item[0]))
            if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
                directional_leader = ranked[0][0]

        total_states = len(states)
        return {
            "selected_profiles": [profile.username for profile in profiles],
            "coverage": self._feature_coverage(
                profiles,
                "pair_dossier",
                events,
                states,
            ),
            "summary": {
                "shared_titles": len(shared),
                "rated_overlap": len(rated_shared),
                "same_day_events": sum(event["day_gap"] == 0 for event in matched),
                "within_gap_events": len(matched),
                "alignment_score": _round(alignment_score, 1),
                "rating_correlation": _round(correlation, 2),
                "average_rating_gap": _round(average_gap, 2),
                "directional_leader": directional_leader,
                "date_coverage_ratio": _round(
                    min(len(events) / max(sum(max(row.watch_count, 1) for row in states), 1), 1.0),
                    3,
                ) if total_states else None,
            },
            "follow_graph": {
                **self._follow_graph_summary(follow_graph, profiles, matched),
                # The pair's own social link, independent of any single event.
                "relationship": follow_graph.relationship(
                    ordered_profile_ids[0],
                    ordered_profile_ids[1],
                    left_username=profiles[0].username,
                    right_username=profiles[1].username,
                ),
            },
            "co_watches": matched[:100],
            "influence_paths": influence_paths[:100],
            "agreements": agreements,
            "disagreements": disagreements,
            "monthly_alignment": monthly_alignment,
        }

    def signal_calendar(
        self,
        requested: Sequence[str],
        *,
        gap_days: int,
        from_date: Optional[date],
        to_date: Optional[date],
    ) -> Dict[str, Any]:
        profiles = self._resolve_profiles(requested, minimum=2)
        events = self._event_rows(profiles)
        max_event_date = max((event.watched_date for event in events), default=date.today())
        range_to = to_date or max_event_date
        range_from = from_date or (range_to - timedelta(days=364))
        if range_from > range_to:
            raise InsightRequestError({"message": "from must be on or before to"})

        follow_graph = self._follow_graph(profiles)
        matches = self._matched_events(
            events,
            gap_days=gap_days,
            from_date=range_from,
            to_date=range_to,
            follow_graph=follow_graph,
        )
        calendar_events = []
        for event in matches:
            identity = "|".join(
                [
                    event["title"],
                    str(event["year"] or ""),
                    event["start_date"],
                    event["end_date"],
                    ",".join(event["profiles"]),
                ]
            )
            calendar_events.append(
                {
                    **event,
                    # This is a deterministic response identifier used as a UI key,
                    # not an authentication token. Keep its established 16-hex shape
                    # while avoiding SHA-1 over profile-associated event metadata.
                    "event_id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
                }
            )

        buckets: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"signal_count": 0, "pair_hits": 0, "profiles": set()}
        )
        monthly: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"signal_count": 0, "pair_hits": 0}
        )
        for event in calendar_events:
            day = event["start_date"]
            bucket = buckets[day]
            bucket["signal_count"] += 1
            bucket["pair_hits"] += event["pair_count"]
            bucket["profiles"].update(event["profiles"])
            monthly[day[:7]]["signal_count"] += 1
            monthly[day[:7]]["pair_hits"] += event["pair_count"]
        max_pair_hits = max((value["pair_hits"] for value in buckets.values()), default=0)
        bucket_payload = [
            {
                "date": day,
                "signal_count": value["signal_count"],
                "pair_hits": value["pair_hits"],
                "distinct_profiles": len(value["profiles"]),
                # The frontend renders five exact levels (0 through 4).
                "intensity": min(
                    4,
                    max(1, math.ceil((value["pair_hits"] / max_pair_hits) * 4)),
                ) if max_pair_hits and value["pair_hits"] else 0,
            }
            for day, value in sorted(buckets.items())
        ]
        monthly_payload = [
            {"month": month, **value} for month, value in sorted(monthly.items())
        ]
        return {
            "selected_profiles": [profile.username for profile in profiles],
            "gap_days": gap_days,
            "from": range_from.isoformat(),
            "to": range_to.isoformat(),
            "coverage": self._feature_coverage(profiles, "signal_calendar", events),
            "follow_graph": self._follow_graph_summary(
                follow_graph, profiles, calendar_events
            ),
            "buckets": bucket_payload,
            "events": calendar_events,
            "monthly_summary": monthly_payload,
        }

    @staticmethod
    def _trait_values(row: StateRow, dimension: str) -> List[str]:
        enrichment = row.enrichment
        if dimension == "decade":
            return [f"{(row.movie.release_year // 10) * 10}s"] if row.movie.release_year else []
        if dimension == "genre" and enrichment:
            return _as_string_list(enrichment.genres)
        if dimension == "language" and enrichment and enrichment.original_language:
            return [enrichment.original_language.upper()]
        if dimension == "country" and enrichment:
            return _as_string_list(enrichment.production_countries)
        if dimension == "keyword" and enrichment:
            return _as_string_list(enrichment.keywords)
        # TMDB stores an unfilled runtime as 0, not null — 55 films in the
        # tracked library carry it — and `is not None` read that as a known
        # length, filing them under "Under 90 min". The user was then told they
        # favour short films on the strength of films whose runtime nobody has
        # recorded. Everywhere else in the codebase treats 0 as unknown.
        if dimension == "runtime" and enrichment and enrichment.runtime_minutes:
            runtime = enrichment.runtime_minutes
            if runtime < 90:
                return ["Under 90 min"]
            if runtime <= 120:
                return ["90–120 min"]
            if runtime <= 150:
                return ["121–150 min"]
            return ["Over 150 min"]
        if dimension in {"director", "actor"} and enrichment and isinstance(enrichment.credits, dict):
            if dimension == "actor":
                return _as_string_list(enrichment.credits.get("cast", []))[:8]
            crew = enrichment.credits.get("crew", [])
            return _as_string_list(
                [member for member in crew if isinstance(member, dict) and member.get("job") == "Director"]
            )
        return []

    def _semantic_neighbors(
        self,
        profiles: Sequence[Profile],
        states: Sequence[StateRow],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Different films, watched by different people, that are the same thing.

        The panel's promise is "contextual matches, not exact-title co-watches",
        so a pair sharing a ``movie_id`` is excluded by construction: that is an
        ordinary co-watch and every other surface already reports it.

        Needs at least two profiles to be a match between anyone, and a date on
        both sides to claim they happened close together.
        """

        if len(profiles) < 2:
            return []

        best: Dict[Tuple[int, int], Dict[str, Any]] = {}
        for rank, (dimension, template) in enumerate(SEMANTIC_NEIGHBOR_DIMENSIONS):
            buckets: Dict[str, Tuple[str, List[StateRow]]] = {}
            for row in states:
                if row.latest_watched_date is None:
                    continue
                for label in self._trait_values(row, dimension):
                    key = label.casefold()
                    if dimension == "keyword" and key in SEMANTIC_NEIGHBOR_KEYWORD_STOPLIST:
                        continue
                    if key not in buckets:
                        buckets[key] = (label, [])
                    buckets[key][1].append(row)

            for label, rows in buckets.values():
                if len(rows) > SEMANTIC_NEIGHBOR_MAX_TRAIT_SIZE:
                    continue
                for index, left in enumerate(rows):
                    for right in rows[index + 1 :]:
                        if left.profile_id == right.profile_id:
                            continue
                        if left.movie_id == right.movie_id:
                            continue
                        gap = abs(
                            (left.latest_watched_date - right.latest_watched_date).days
                        )
                        if gap > SEMANTIC_NEIGHBOR_GAP_DAYS:
                            continue
                        pair = (min(left.movie_id, right.movie_id), max(left.movie_id, right.movie_id))
                        existing = best.get(pair)
                        # Strongest dimension wins; within one dimension the
                        # closest pair in time is the better illustration.
                        if existing is not None and (
                            existing["_rank"] < rank
                            or (existing["_rank"] == rank and existing["day_gap"] <= gap)
                        ):
                            continue
                        later, earlier = (
                            (left, right)
                            if left.latest_watched_date >= right.latest_watched_date
                            else (right, left)
                        )
                        best[pair] = {
                            "movie": self._movie_summary(later.movie, later.enrichment),
                            # "a Alex Garland film" is the sort of thing a reader
                            # notices instead of the insight.
                            "reason": template.format(
                                label=label,
                                article="an" if label[:1].lower() in "aeiou" else "a",
                            ),
                            # Ordered by who got there first, which is the only
                            # claim the dates support.
                            "watched_by": [earlier.username, later.username],
                            "day_gap": gap,
                            "_rank": rank,
                        }

        ordered = sorted(
            best.values(),
            key=lambda entry: (entry["_rank"], entry["day_gap"], entry["movie"]["title"]),
        )
        # One card per film. Two different pairs can share a displayed film --
        # two Park Chan-wook matches both surface "Decision to Leave" -- and the
        # panel renders posters, so that reads as the same entry twice. The
        # first survivor is already the strongest by the sort above.
        deduped: List[Dict[str, Any]] = []
        seen_titles: set = set()
        for entry in ordered:
            identity = entry["movie"].get("movie_id") or entry["movie"].get("title")
            if identity in seen_titles:
                continue
            seen_titles.add(identity)
            entry.pop("_rank", None)
            deduped.append(entry)
        return deduped[:limit]

    @staticmethod
    def _earliest_event_per_profile(events: Sequence[EventRow]) -> Dict[int, EventRow]:
        """One event per profile: the first time each of them saw this film.

        Watch history is not one row per person per film. 4,948 (profile, film)
        pairs in the tracked library carry more than one event -- rewatches, and
        several diary entries on a single date -- and pairing the raw rows made
        a film someone had rewatched six times cast six votes for who watched
        first, against one from the other person's single viewing.

        A rewatch cannot make anyone earlier, so the earliest event is the only
        one that speaks to sequence.
        """

        earliest: Dict[int, EventRow] = {}
        for event in events:
            current = earliest.get(event.profile_id)
            if current is None or event.watched_date < current.watched_date:
                earliest[event.profile_id] = event
        return earliest

    @staticmethod
    def _alignment_sort_key(trait: Dict[str, Any], profile_count: int) -> Tuple:
        """Order a dimension by how much the profiles actually agree.

        Ranking by group score alone surfaces traits one profile rated
        highly and the other never watched — maximum divergence, which the
        contrasts panel already covers. Alignment needs both sides present,
        both strong, and close together. A single five-star film also scores
        a perfect 100, so traits below the credible sample floor rank last.
        """
        # Engagement and credibility are both questions about ratings, because
        # the score is built from ratings alone. Measuring them against watched
        # rows made the floor inert for anyone who logs more than they rate: two
        # profiles who each rated ONE Wes Anderson film five stars both scored a
        # perfect 100 over a "sample" of three, and outranked a trait where both
        # had rated twenty-five films.
        engaged = [entry for entry in trait["per_profile"] if entry["rated_sample_size"] > 0]
        shared = len(engaged) == profile_count
        credible = shared and all(
            entry["rated_sample_size"] >= MIN_ALIGNMENT_SAMPLE for entry in engaged
        )
        scores = [entry["score"] for entry in engaged]
        weakest = min(scores) if scores else 0.0
        spread = (max(scores) - min(scores)) if len(scores) >= 2 else 0.0
        # The weaker side carries the pair, and disagreement is penalised, so
        # "both like this a lot" outranks "one adores it, one has never seen it".
        alignment = weakest - (spread / 2)
        return (
            not credible,
            not shared,
            -alignment,
            -trait["sample_size"],
            trait["label"],
        )

    def taste_dna(
        self,
        requested: Sequence[str],
        *,
        dimensions: Sequence[str],
        limit: int,
    ) -> Dict[str, Any]:
        profiles = self._resolve_profiles(requested, minimum=1)
        invalid = sorted(set(dimensions) - ALLOWED_TASTE_DIMENSIONS)
        if invalid:
            raise InsightRequestError(
                {"message": "Unsupported taste dimension", "unsupported_dimensions": invalid}
            )
        selected_dimensions = list(dict.fromkeys(dimensions)) or ["decade"]
        states = self._state_rows(profiles, analytical_enrichment=True)
        events = self._event_rows(profiles)
        by_movie: Dict[int, List[StateRow]] = defaultdict(list)
        for row in states:
            by_movie[row.movie_id].append(row)
        shared_rated = [
            rows
            for rows in by_movie.values()
            if len({row.profile_id for row in rows if row.rating is not None}) == len(profiles)
        ]

        trait_rows: Dict[str, Dict[str, List[StateRow]]] = {
            dimension: defaultdict(list) for dimension in selected_dimensions
        }
        labels: Dict[Tuple[str, str], str] = {}
        for row in states:
            for dimension in selected_dimensions:
                for label in self._trait_values(row, dimension):
                    key = label.casefold()
                    labels[(dimension, key)] = label
                    trait_rows[dimension][key].append(row)

        dimension_payloads: Dict[str, List[Dict[str, Any]]] = {}
        contrast_candidates: List[Tuple[float, Dict[str, Any]]] = []
        signature_candidates: List[Dict[str, Any]] = []
        for dimension, values in trait_rows.items():
            traits: List[Dict[str, Any]] = []
            for key, rows in values.items():
                per_profile = []
                present_profiles = set()
                all_ratings = []
                liked_count = 0
                top_movies: Dict[int, StateRow] = {}
                # Ratings per film per profile, so "shared" examples can require
                # that everybody actually rated the film. Keeping the single
                # best row per movie put films only one profile had seen into a
                # panel headed "Shared taste, real examples".
                rated_by: Dict[int, Dict[int, float]] = defaultdict(dict)
                for profile in profiles:
                    profile_rows = [row for row in rows if row.profile_id == profile.id]
                    ratings = [row.rating for row in profile_rows if row.rating is not None]
                    average_rating = _average(ratings)
                    present_profiles.update(row.profile_id for row in profile_rows)
                    all_ratings.extend(ratings)
                    liked_count += sum(row.liked for row in profile_rows)
                    for row in profile_rows:
                        current = top_movies.get(row.movie_id)
                        if current is None or (row.rating or 0) > (current.rating or 0):
                            top_movies[row.movie_id] = row
                        if row.rating is not None:
                            rated_by[row.movie_id][profile.id] = row.rating
                    per_profile.append(
                        {
                            "username": profile.username,
                            "score": _round((average_rating or 0) * 20, 1) or 0,
                            "sample_size": len(profile_rows),
                            # The score is an average of RATINGS, but sample_size
                            # counts every watched row. Someone who logged six
                            # horror films and rated none scored 0 out of a
                            # sample of six — indistinguishable from rating them
                            # all half a star, and enough to clear the
                            # credibility floor. Anything reasoning about the
                            # score has to weigh it against the ratings it came
                            # from, so carry that count too.
                            "rated_sample_size": len(ratings),
                            "average_rating": _round(average_rating, 2),
                        }
                    )
                average_rating = _average(all_ratings)
                watch_share = len(present_profiles) / len(profiles)
                score = ((average_rating or 0) / 5 * 70) + (watch_share * 30)
                # Only films every selected profile rated, ranked by the
                # weakest of those ratings: a film one person adored and another
                # merely tolerated is not the best example of shared taste, and
                # the maximum hid exactly that.
                shared_movie_ids = {
                    movie_id
                    for movie_id, by_profile in rated_by.items()
                    if len(by_profile) == len(profiles)
                }
                top_rows = sorted(
                    (
                        row
                        for movie_id, row in top_movies.items()
                        if movie_id in shared_movie_ids
                    ),
                    key=lambda row: (
                        -min(rated_by[row.movie_id].values()),
                        row.movie.title,
                    ),
                )[:4]
                trait = {
                    "id": f"{dimension}:{key}",
                    "label": labels[(dimension, key)],
                    "dimension": dimension,
                    "group_score": _round(score, 1) or 0,
                    "sample_size": len(rows),
                    "average_rating": _round(average_rating, 2),
                    "like_rate": _round(liked_count / len(rows), 3) if rows else None,
                    "watch_share": _round(watch_share, 3) or 0,
                    "per_profile": per_profile,
                    "top_movies": [
                        self._movie_summary(row.movie, row.enrichment)
                        for row in top_rows
                    ],
                }
                traits.append(trait)
                # A profile with nothing rated in this trait holds no opinion to
                # differ from. Counting its 0 as a position produced the widest
                # possible split — "Horror: alice 92%, bob 0%" when bob simply
                # never rated a horror film — and those artefacts crowded real
                # disagreements out of the panel.
                scores = [
                    entry["score"] for entry in per_profile if entry["rated_sample_size"] > 0
                ]
                contrast = max(scores) - min(scores) if len(scores) >= 2 else 0
                if contrast > 0:
                    contrast_candidates.append((contrast, {**trait, "group_score": _round(contrast, 1) or 0}))
                # "Shared" has to mean everyone rated it, not that everyone
                # watched it. Pooling ratings hid disagreement: one profile at
                # five stars and another at one averaged to a respectable three
                # and led a panel headed "where your tastes align".
                if len(profiles) >= 2 and all(
                    entry["rated_sample_size"] > 0 for entry in per_profile
                ):
                    signature_candidates.append(trait)
            traits.sort(key=lambda trait: self._alignment_sort_key(trait, len(profiles)))
            dimension_payloads[dimension] = traits[:limit]

        # Ranked by agreement, using the same definition the dimension lists
        # already use, rather than by a pooled average that a wide split can
        # still carry to the top.
        signature_candidates.sort(
            key=lambda trait: self._alignment_sort_key(trait, len(profiles))
        )
        contrast_candidates.sort(key=lambda item: (-item[0], -item[1]["sample_size"], item[1]["label"]))

        pair_correlations: List[float] = []
        profile_ids = [profile.id for profile in profiles]
        for left_id, right_id in combinations(profile_ids, 2):
            left: List[float] = []
            right: List[float] = []
            for rows in shared_rated:
                mapping = {row.profile_id: row.rating for row in rows}
                if left_id in mapping and right_id in mapping:
                    left.append(float(mapping[left_id]))
                    right.append(float(mapping[right_id]))
            correlation = _pearson(left, right)
            if correlation is not None:
                pair_correlations.append(correlation)
        similarity = _average([(value + 1) * 50 for value in pair_correlations])
        enriched = sum(row.enrichment is not None for row in states)
        metadata_ratio = enriched / len(states) if states else None
        tmdb_status = "unavailable"
        if metadata_ratio:
            tmdb_status = "connected" if metadata_ratio >= 0.8 else "partial"
        coverage = self._feature_coverage(
            profiles,
            "taste_dna",
            events,
            states,
        )
        if tmdb_status == "unavailable":
            # Never promote a blocked panel. Missing TMDB data can only make
            # coverage worse, and assigning unconditionally turned an existing
            # "blocked" into "partial" whenever any state row existed, letting a
            # panel with real blockers present itself as merely incomplete.
            # `readiness` guards the same way where it downgrades for TMDB.
            if coverage["status"] != "blocked":
                coverage["status"] = "partial" if states else "blocked"
            coverage["warnings"].append(
                "TMDB enrichment has not run yet; only Letterboxd-native dimensions such as decade are shown."
            )
        return {
            "selected_profiles": [profile.username for profile in profiles],
            "coverage": coverage,
            "summary": {
                "similarity_score": _round(similarity, 1),
                "shared_rated_titles": len(shared_rated),
                "metadata_coverage_ratio": _round(metadata_ratio, 3),
                "tmdb_status": tmdb_status,
            },
            "shared_signature": signature_candidates[:limit],
            "contrasts": [item[1] for item in contrast_candidates[:limit]],
            "dimensions": dimension_payloads,
            "semantic_neighbors": self._semantic_neighbors(profiles, states, limit),
        }

    @staticmethod
    def _season_for_date(watched_date: date) -> Tuple[int, str]:
        month = watched_date.month
        if month in SEASON_MONTHS["winter"]:
            # December belongs to the following winter, so Winter 2026 means
            # Dec 2025 through Feb 2026 rather than two disjoint date ranges.
            return watched_date.year + (1 if month == 12 else 0), "winter"
        if month in SEASON_MONTHS["spring"]:
            return watched_date.year, "spring"
        if month in SEASON_MONTHS["summer"]:
            return watched_date.year, "summer"
        return watched_date.year, "autumn"

    def _taste_period_summary(
        self,
        events: Sequence[EventRow],
        profiles: Sequence[Profile],
        state_lookup: Mapping[Tuple[int, int], StateRow],
        *,
        key: str,
        label: str,
        year: int,
        season: Optional[str],
        dimensions: Sequence[str],
        trait_limit: int,
    ) -> Dict[str, Any]:
        ratings = [event.rating for event in events if event.rating is not None]
        per_profile = []
        for profile in profiles:
            profile_events = [event for event in events if event.profile_id == profile.id]
            profile_ratings = [
                event.rating for event in profile_events if event.rating is not None
            ]
            per_profile.append(
                {
                    "username": profile.username,
                    "watch_events": len(profile_events),
                    "unique_films": len({event.movie_id for event in profile_events}),
                    "rated_events": len(profile_ratings),
                    "average_rating": _round(_average(profile_ratings), 2),
                    "rewatch_count": sum(event.rewatch for event in profile_events),
                    "liked_count": sum(event.liked for event in profile_events),
                }
            )

        trait_events: Dict[Tuple[str, str], List[EventRow]] = defaultdict(list)
        trait_labels: Dict[Tuple[str, str], str] = {}
        for event in events:
            state = state_lookup.get((event.profile_id, event.movie_id))
            if state is None:
                continue
            for dimension in dimensions:
                for value in self._trait_values(state, dimension):
                    trait_key = (dimension, value.casefold())
                    trait_labels[trait_key] = value
                    trait_events[trait_key].append(event)

        top_traits = []
        for trait_key, rows in trait_events.items():
            trait_ratings = [row.rating for row in rows if row.rating is not None]
            top_traits.append(
                {
                    "dimension": trait_key[0],
                    "label": trait_labels[trait_key],
                    "watch_events": len(rows),
                    "profile_count": len({row.profile_id for row in rows}),
                    "average_rating": _round(_average(trait_ratings), 2),
                }
            )
        top_traits.sort(
            key=lambda item: (
                -item["profile_count"],
                -item["watch_events"],
                -(item["average_rating"] or 0),
                item["dimension"],
                item["label"].casefold(),
            )
        )

        return {
            "key": key,
            "label": label,
            "year": year,
            "season": season,
            "watch_events": len(events),
            "unique_films": len({event.movie_id for event in events}),
            "rated_events": len(ratings),
            "average_rating": _round(_average(ratings), 2),
            "rewatch_count": sum(event.rewatch for event in events),
            "liked_count": sum(event.liked for event in events),
            "per_profile": per_profile,
            "top_traits": top_traits[:trait_limit],
        }

    def taste_timeline(
        self,
        requested: Sequence[str],
        *,
        dimensions: Sequence[str],
        from_year: Optional[int],
        to_year: Optional[int],
        trait_limit: int,
        year_limit: int,
    ) -> Dict[str, Any]:
        profiles = self._resolve_profiles(requested, minimum=1)
        invalid = sorted(set(dimensions) - ALLOWED_TASTE_DIMENSIONS)
        if invalid:
            raise InsightRequestError(
                {"message": "Unsupported taste dimension", "unsupported_dimensions": invalid}
            )
        if from_year is not None and to_year is not None and from_year > to_year:
            raise InsightRequestError({"message": "from_year must be on or before to_year"})

        selected_dimensions = list(dict.fromkeys(dimensions)) or ["decade"]
        states = self._state_rows(profiles, analytical_enrichment=True)
        all_events = self._event_rows(profiles)
        state_lookup = {(row.profile_id, row.movie_id): row for row in states}
        events = [
            event
            for event in all_events
            if (from_year is None or event.opinion_date.year >= from_year)
            and (to_year is None or event.opinion_date.year <= to_year)
        ]

        available_years = sorted({event.opinion_date.year for event in events})
        returned_years = available_years[-year_limit:]
        returned_year_set = set(returned_years)
        returned_events = [
            event for event in events if event.opinion_date.year in returned_year_set
        ]
        yearly_events: Dict[int, List[EventRow]] = defaultdict(list)
        seasonal_events: Dict[Tuple[int, str], List[EventRow]] = defaultdict(list)
        for event in returned_events:
            yearly_events[event.opinion_date.year].append(event)
            seasonal_events[self._season_for_date(event.opinion_date)].append(event)

        yearly = [
            self._taste_period_summary(
                yearly_events[year],
                profiles,
                state_lookup,
                key=str(year),
                label=str(year),
                year=year,
                season=None,
                dimensions=selected_dimensions,
                trait_limit=trait_limit,
            )
            for year in returned_years
        ]
        seasonal = [
            self._taste_period_summary(
                seasonal_events[(year, season)],
                profiles,
                state_lookup,
                key=f"{year}-{season}",
                label=f"{season.title()} {year}",
                year=year,
                season=season,
                dimensions=selected_dimensions,
                trait_limit=trait_limit,
            )
            for year, season in sorted(
                seasonal_events,
                key=lambda item: (item[0], SEASON_ORDER.index(item[1])),
            )
        ]

        coverage = self._feature_coverage(
            profiles,
            "taste_timeline",
            all_events,
            states,
        )
        total_known_watches = max(
            len(all_events),
            sum(max(row.watch_count, 1) for row in states),
        )
        undated_known_watches = max(total_known_watches - len(all_events), 0)
        rated_dated_events = sum(event.rating is not None for event in all_events)
        enriched_event_count = sum(
            bool(state_lookup.get((event.profile_id, event.movie_id)))
            and state_lookup[(event.profile_id, event.movie_id)].enrichment is not None
            for event in all_events
        )
        if undated_known_watches:
            coverage["warnings"] = list(
                dict.fromkeys(
                    [
                        *coverage["warnings"],
                        f"{undated_known_watches} known watches have no public Diary date and cannot be assigned to a year or season.",
                    ]
                )
            )
        if rated_dated_events < len(all_events):
            coverage["warnings"] = list(
                dict.fromkeys(
                    [
                        *coverage["warnings"],
                        "Average ratings use only dated events that carry an event-level rating.",
                    ]
                )
            )
        truncated_years = max(len(available_years) - len(returned_years), 0)
        if truncated_years:
            coverage["warnings"] = list(
                dict.fromkeys(
                    [
                        *coverage["warnings"],
                        f"{truncated_years} older year(s) were omitted by year_limit.",
                    ]
                )
            )

        date_coverage_ratio = (
            len(all_events) / total_known_watches if total_known_watches else None
        )
        rating_coverage_ratio = (
            rated_dated_events / len(all_events) if all_events else None
        )
        metadata_coverage_ratio = (
            enriched_event_count / len(all_events) if all_events else None
        )
        return {
            "selected_profiles": [profile.username for profile in profiles],
            "filters": {
                "dimensions": selected_dimensions,
                "from_year": from_year,
                "to_year": to_year,
                "trait_limit": trait_limit,
                "year_limit": year_limit,
            },
            "coverage": coverage,
            "summary": {
                "first_year": available_years[0] if available_years else None,
                "last_year": available_years[-1] if available_years else None,
                "years": len(available_years),
                "returned_years": len(returned_years),
                "truncated_years": truncated_years,
                "dated_watch_events": len(all_events),
                "total_known_watches": total_known_watches,
                "undated_known_watches": undated_known_watches,
                # Which date each point sits on. Log dates only exist in
                # official account exports, so a timeline built on watch dates
                # places backdated entries in the year of the viewing rather
                # than the year the opinion was formed.
                "date_basis": (
                    "logged"
                    if events and all(event.logged_date is not None for event in events)
                    else "watched"
                    if not any(event.logged_date is not None for event in events)
                    else "mixed"
                ),
                "logged_date_events": sum(
                    1 for event in events if event.logged_date is not None
                ),
                "date_coverage_ratio": _round(date_coverage_ratio, 3),
                "rated_dated_events": rated_dated_events,
                "rating_coverage_ratio": _round(rating_coverage_ratio, 3),
                "trait_metadata_coverage_ratio": _round(metadata_coverage_ratio, 3),
            },
            "yearly": yearly,
            "seasonal": seasonal,
        }

    def watch_provider_regions(self) -> Dict[str, Any]:
        """Describe every country represented in the cached TMDB provider data."""

        movies_by_region: Dict[str, set[int]] = defaultdict(set)
        for movie_id, raw_payload in self.db.query(
            MovieEnrichment.movie_id,
            MovieEnrichment.raw_payload,
        ).all():
            for region_code in _cached_provider_region_codes(raw_payload):
                movies_by_region[region_code].add(int(movie_id))

        for movie_id, region in (
            self.db.query(MovieWatchProvider.movie_id, MovieWatchProvider.region)
            .filter(MovieWatchProvider.provider_type.in_(SUPPORTED_PROVIDER_TYPES))
            .distinct()
            .all()
        ):
            region_code = str(region or "").upper()
            if len(region_code) == 2 and region_code.isalpha():
                movies_by_region[region_code].add(int(movie_id))

        return {
            "default_region": WORLDWIDE_REGION,
            "worldwide_region": WORLDWIDE_REGION,
            "regions": [
                {
                    "code": region_code,
                    "movie_count": len(movie_ids),
                }
                for region_code, movie_ids in sorted(movies_by_region.items())
            ],
        }

    @staticmethod
    def _public_list_summary(
        *,
        list_id: int,
        owner: str,
        name: str,
        movie_count: Optional[int],
        is_ranked: Optional[bool],
    ) -> Dict[str, Any]:
        return {
            "id": int(list_id),
            "owner": owner,
            "name": name,
            "movie_count": int(movie_count or 0),
            "is_ranked": bool(is_ranked),
        }

    def _available_public_lists(
        self,
        profiles: Sequence[Profile],
        *,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        if not profiles:
            return []
        rows = (
            self.db.query(
                MovieList.id,
                Profile.username,
                MovieList.name,
                MovieList.movie_count,
                MovieList.is_ranked,
            )
            .join(Profile, Profile.id == MovieList.profile_id)
            .filter(
                MovieList.profile_id.in_([profile.id for profile in profiles]),
                MovieList.is_public.is_(True),
                MovieList.removed_at.is_(None),
            )
            .order_by(
                Profile.username.asc(),
                MovieList.name.asc(),
                MovieList.id.asc(),
            )
            .limit(limit)
            .all()
        )
        payload = [
            self._public_list_summary(
                list_id=list_id,
                owner=owner,
                name=name,
                movie_count=movie_count,
                is_ranked=is_ranked,
            )
            for list_id, owner, name, movie_count, is_ranked in rows
        ]
        return sorted(
            payload,
            key=lambda item: (
                item["owner"].casefold(),
                item["name"].casefold(),
                item["id"],
            ),
        )

    def public_lists(
        self,
        requested: Sequence[str],
        *,
        limit: int,
    ) -> Dict[str, Any]:
        profiles = self._resolve_profiles(requested, minimum=1)
        lists = self._available_public_lists(profiles, limit=limit)
        return {
            "selected_profiles": [profile.username for profile in profiles],
            "summary": {
                "available_lists": len(lists),
                "total_movie_items": sum(item["movie_count"] for item in lists),
            },
            "lists": lists,
        }

    def watch_together(
        self,
        requested: Sequence[str],
        *,
        mode: str,
        region: str,
        max_runtime: Optional[int],
        genre: Optional[str],
        availability: Optional[str],
        limit: int,
        list_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        mode = str(mode or "").strip().casefold()
        if mode not in WATCH_TOGETHER_MODES:
            raise InsightRequestError(
                {
                    "message": "Unsupported Watch Together mode",
                    "supported_modes": sorted(WATCH_TOGETHER_MODES),
                }
            )
        region = str(region or "").strip().upper()
        if region != WORLDWIDE_REGION and (len(region) != 2 or not region.isalpha()):
            raise InsightRequestError(
                {"message": "Region must be ALL or a two-letter country code"}
            )
        availability = _normalize_availability_filter(availability)
        profiles = self._resolve_profiles(requested, minimum=2)
        selected_ids = {profile.id for profile in profiles}
        selected_usernames = {profile.id: profile.username for profile in profiles}
        available_lists = self._available_public_lists(profiles, limit=100)
        if mode == "list_mission" and list_id is None:
            raise InsightRequestError(
                {
                    "message": "list_id is required for list_mission",
                    "available_lists": available_lists,
                }
            )

        selected_list_record: Optional[Dict[str, Any]] = None
        selected_list = None
        if mode == "list_mission":
            selected_list_row = (
                self.db.query(
                    MovieList.id,
                    MovieList.profile_id,
                    Profile.username,
                    MovieList.name,
                    MovieList.movie_count,
                    MovieList.is_ranked,
                )
                .join(Profile, Profile.id == MovieList.profile_id)
                .filter(
                    MovieList.id == list_id,
                    MovieList.profile_id.in_(selected_ids),
                    MovieList.is_public.is_(True),
                    MovieList.removed_at.is_(None),
                )
                .one_or_none()
            )
            if selected_list_row is None:
                raise InsightRequestError(
                    {
                        "message": "The requested public list is not available for the selected profiles",
                        "list_id": list_id,
                        "available_lists": available_lists,
                    },
                    status_code=404,
                )
            (
                selected_list_id,
                selected_list_profile_id,
                selected_list_owner,
                selected_list_name,
                selected_list_movie_count,
                selected_list_is_ranked,
            ) = selected_list_row
            selected_list = self._public_list_summary(
                list_id=selected_list_id,
                owner=selected_list_owner,
                name=selected_list_name,
                movie_count=selected_list_movie_count,
                is_ranked=selected_list_is_ranked,
            )
            selected_list_record = {
                **selected_list,
                "profile_id": int(selected_list_profile_id),
            }
        # Candidate selection only needs to know whether enrichment exists.
        # Load the larger TMDB payload exactly once per distinct candidate
        # after the candidate set is known, not once per profile-film row.
        states = self._state_rows(profiles, lightweight_enrichment=True)
        watched_by_movie: Dict[int, List[StateRow]] = defaultdict(list)
        for row in states:
            watched_by_movie[row.movie_id].append(row)

        watchlist_rows = (
            self.db.query(WatchlistItem, Profile, Movie)
            .join(Profile, Profile.id == WatchlistItem.profile_id)
            .join(Movie, Movie.id == WatchlistItem.movie_id)
            .filter(
                WatchlistItem.profile_id.in_(selected_ids),
                WatchlistItem.removed_at.is_(None),
            )
            .all()
        )
        watchlist_by_movie: Dict[int, Dict[str, Any]] = {}
        for item, profile, movie in watchlist_rows:
            candidate = watchlist_by_movie.setdefault(
                movie.id,
                {
                    "movie": movie,
                    "enrichment": None,
                    "profile_ids": set(),
                    "list_item": None,
                    "blind_spot_source": None,
                },
            )
            candidate["profile_ids"].add(profile.id)

        candidate_ids = (
            set(watchlist_by_movie)
            if mode in {"watchlist_overlap", "unseen_pick"}
            else set()
        )
        outsider_rows: Dict[int, List[StateRow]] = defaultdict(list)
        if mode == "unseen_pick":
            all_rows_query = (
                self.db.query(ProfileFilm, Profile, Movie)
                .join(Profile, Profile.id == ProfileFilm.profile_id)
                .join(Movie, Movie.id == ProfileFilm.movie_id)
                .filter(ProfileFilm.removed_at.is_(None), Profile.is_active.is_(True))
            )
            if self.allowed_profile_ids is not None:
                all_rows_query = all_rows_query.filter(
                    Profile.id.in_(self.allowed_profile_ids)
                    if self.allowed_profile_ids
                    else false()
                )
            elif self.allowed_usernames is not None:
                all_rows_query = all_rows_query.filter(
                    func.lower(Profile.username).in_(self.allowed_usernames)
                    if self.allowed_usernames
                    else false()
                )
            all_rows = all_rows_query.all()
            movie_details: Dict[int, Movie] = {}
            for profile_film, profile, movie in all_rows:
                movie_details[movie.id] = movie
                if profile.id not in selected_ids:
                    outsider_rows[movie.id].append(
                        StateRow(
                            profile_id=profile.id,
                            username=profile.username,
                            movie_id=movie.id,
                            rating=_safe_float(profile_film.rating),
                            liked=bool(profile_film.is_liked),
                            tags=_as_string_list(profile_film.tags),
                            first_watched_date=profile_film.first_watched_date,
                            latest_watched_date=profile_film.latest_watched_date,
                            watch_count=int(profile_film.watch_count or 0),
                            rewatch_count=int(profile_film.rewatch_count or 0),
                            movie=movie,
                            enrichment=None,
                        )
                    )
            for movie_id, rows in outsider_rows.items():
                if movie_id not in watched_by_movie and rows:
                    candidate_ids.add(movie_id)
                    if movie_id not in watchlist_by_movie:
                        movie = movie_details[movie_id]
                        watchlist_by_movie[movie_id] = {
                            "movie": movie,
                            "enrichment": None,
                            "profile_ids": set(),
                            "list_item": None,
                            "blind_spot_source": None,
                        }

        if mode == "collective_blind_spots":
            for movie_id, watched_rows in watched_by_movie.items():
                distinct_rows = {
                    row.profile_id: row for row in watched_rows
                }
                if len(distinct_rows) != 1:
                    continue
                source = next(iter(distinct_rows.values()))
                if not source.liked and (source.rating is None or source.rating < 4.0):
                    continue
                candidate = watchlist_by_movie.setdefault(
                    movie_id,
                    {
                        "movie": source.movie,
                        "enrichment": source.enrichment,
                        "profile_ids": set(),
                        "list_item": None,
                        "blind_spot_source": None,
                    },
                )
                candidate["blind_spot_source"] = source
                if candidate.get("enrichment") is None:
                    candidate["enrichment"] = source.enrichment
                candidate_ids.add(movie_id)

        if mode == "list_mission" and selected_list_record is not None:
            list_rows = (
                self.db.query(MovieListItem, Movie)
                .join(Movie, Movie.id == MovieListItem.movie_id)
                .filter(
                    MovieListItem.movie_list_id == selected_list_record["id"],
                    MovieListItem.removed_at.is_(None),
                )
                .order_by(MovieListItem.position.asc(), MovieListItem.id.asc())
                .all()
            )
            for list_item, movie in list_rows:
                candidate = watchlist_by_movie.setdefault(
                    movie.id,
                    {
                        "movie": movie,
                        "enrichment": None,
                        "profile_ids": set(),
                        "list_item": None,
                        "blind_spot_source": None,
                    },
                )
                candidate["list_item"] = {
                    "list_id": selected_list_record["id"],
                    "owner": selected_list_record["owner"],
                    "name": selected_list_record["name"],
                    "position": int(list_item.position),
                    "notes": list_item.notes,
                }
                candidate_ids.add(movie.id)

        # Runtime/genre/provider filters must inspect every candidate. With the
        # default unfiltered view, rank first and hydrate only the returned
        # movies so thousands of large TMDB provider payloads are not decoded.
        eager_metadata = bool(max_runtime is not None or genre or availability)
        enrichments_by_movie: Dict[int, MovieEnrichment] = {}
        if candidate_ids and eager_metadata:
            enrichments_by_movie = {
                enrichment.movie_id: enrichment
                for enrichment in (
                    self.db.query(MovieEnrichment)
                    .filter(MovieEnrichment.movie_id.in_(candidate_ids))
                    .populate_existing()
                    .all()
                )
            }
            for movie_id in candidate_ids:
                watchlist_by_movie[movie_id]["enrichment"] = enrichments_by_movie.get(movie_id)
        elif not eager_metadata:
            for movie_id in candidate_ids:
                watchlist_by_movie[movie_id]["enrichment"] = None

        stored_providers_by_movie: Dict[int, List[MovieWatchProvider]] = defaultdict(list)
        if candidate_ids and availability:
            provider_query = self.db.query(MovieWatchProvider).filter(
                MovieWatchProvider.movie_id.in_(candidate_ids),
                MovieWatchProvider.provider_type.in_(SUPPORTED_PROVIDER_TYPES),
            )
            if region != WORLDWIDE_REGION:
                provider_query = provider_query.filter(
                    func.upper(MovieWatchProvider.region) == region
                )
            for provider in provider_query.order_by(
                MovieWatchProvider.display_priority.asc()
            ).all():
                stored_providers_by_movie[provider.movie_id].append(provider)

        providers_by_movie: Dict[int, List[ProviderAvailability]] = defaultdict(list)
        for movie_id in candidate_ids if availability else ():
            enrichment = watchlist_by_movie[movie_id]["enrichment"]
            cached_providers = _providers_from_cached_tmdb(
                movie_id,
                enrichment.raw_payload if enrichment else None,
                region=region,
            )
            providers_by_movie[movie_id] = _merge_provider_availability(
                movie_id,
                stored_providers_by_movie.get(movie_id, []),
                cached_providers,
            )

        recommendations: List[Dict[str, Any]] = []
        # Candidates dropped only because TMDB has never described them.
        unenriched_skipped = 0
        for movie_id in candidate_ids:
            candidate = watchlist_by_movie[movie_id]
            movie: Movie = candidate["movie"]
            enrichment: Optional[MovieEnrichment] = candidate["enrichment"]
            # `or None` so an unfilled TMDB runtime of 0 is unknown here exactly
            # as a null one is. Left as 0 it slipped through every max-runtime
            # filter — `0 > 90` is false — so asking for something short
            # returned films of unrecorded length, and the payload then
            # reported their runtime as zero minutes.
            runtime = (enrichment.runtime_minutes or None) if enrichment else None
            genres = _as_string_list(enrichment.genres) if enrichment else []
            providers = providers_by_movie.get(movie_id, [])
            # A film TMDB never enriched has no runtime and no genres, so both
            # filters drop it. That is the right call -- we cannot claim it is
            # under 90 minutes -- but silently, it reads as "no such film in
            # your watchlists" when the truth is "we do not know". Counted here
            # and reported in coverage below.
            if max_runtime is not None and runtime is None:
                unenriched_skipped += 1
                continue
            if max_runtime is not None and runtime > max_runtime:
                continue
            if genre and not genres:
                unenriched_skipped += 1
                continue
            if genre and genre.casefold() not in {value.casefold() for value in genres}:
                continue
            if availability:
                if not any(
                    _provider_matches_availability(provider, availability)
                    for provider in providers
                ):
                    continue

            watched_rows = watched_by_movie.get(movie_id, [])
            watched_ids = {row.profile_id for row in watched_rows}
            if mode == "unseen_pick" and watched_ids:
                # This mode is presented as “Unseen by all”, so a watchlist
                # entry must not leak an already-seen title into the results.
                continue
            unseen_ids = selected_ids - watched_ids
            if mode == "list_mission" and not unseen_ids:
                # A completed list item is not a remaining group mission.
                continue
            watchlist_ids = set(candidate["profile_ids"])
            outside = outsider_rows.get(movie_id, [])
            evidence_rows = [*watched_rows, *outside]
            evidence_ratings = [row.rating for row in evidence_rows if row.rating is not None]
            liked_ids = {row.profile_id for row in watched_rows if row.liked}
            blind_spot_source: Optional[StateRow] = candidate.get("blind_spot_source")
            list_context: Optional[Dict[str, Any]] = candidate.get("list_item")

            watchlist_component = len(watchlist_ids) / len(selected_ids)
            unseen_component = len(unseen_ids) / len(selected_ids)
            rating_component = (_average(evidence_ratings) or 2.5) / 5
            evidence_component = min(len(evidence_rows) / 5, 1.0)
            if mode == "collective_blind_spots" and blind_spot_source is not None:
                source_rating_component = (
                    blind_spot_source.rating / 5
                    if blind_spot_source.rating is not None
                    else 0.8
                )
                score = 100 * (
                    0.45 * source_rating_component
                    + 0.20 * float(blind_spot_source.liked)
                    + 0.25 * unseen_component
                    + 0.10 * watchlist_component
                )
            elif mode == "list_mission" and list_context is not None:
                # Position only means something on a list its owner ordered
                # deliberately. Letterboxd marks that explicitly, and on an
                # unranked list `position` is just the order rows happen to be
                # stored — so weighting it at 35% ranked recommendations by an
                # accident of storage. Unranked lists redistribute that weight
                # across the signals that do carry meaning.
                if (selected_list or {}).get("is_ranked"):
                    list_size = max(int((selected_list or {}).get("movie_count") or 0), 1)
                    rank_component = max(
                        0.0,
                        1.0 - ((int(list_context["position"]) - 1) / list_size),
                    )
                    score = 100 * (
                        0.35 * rank_component
                        + 0.30 * unseen_component
                        + 0.20 * watchlist_component
                        + 0.15 * rating_component
                    )
                else:
                    score = 100 * (
                        0.46 * unseen_component
                        + 0.31 * watchlist_component
                        + 0.23 * rating_component
                    )
            else:
                # Preserve the established scoring contract for the original
                # Watch Together modes.
                score = 100 * (
                    0.40 * watchlist_component
                    + 0.25 * unseen_component
                    + 0.25 * rating_component
                    + 0.10 * evidence_component
                )
            reasons = []
            if mode == "collective_blind_spots" and blind_spot_source is not None:
                # A film qualifies on a like OR a rating of 4.0+, so the word
                # "liked" cannot be assumed: a 4.5 that was never hearted was
                # still reported as "liked and rated 4.5 this", contradicting
                # the blind-spot source line rendered from the same payload a
                # few rows below — and reading as broken English besides.
                liked = bool(blind_spot_source.liked)
                rating = blind_spot_source.rating
                if liked and rating is not None:
                    source_signal = f"liked and rated this {rating:.1f}"
                elif liked:
                    source_signal = "liked this"
                elif rating is not None:
                    source_signal = f"rated this {rating:.1f}"
                else:
                    source_signal = "watched this"
                reasons.append(
                    f"{blind_spot_source.username} {source_signal}; everyone else selected has not seen it"
                )
            if mode == "list_mission" and list_context is not None:
                # "#3 on ..." asserts a ranking the owner never made when the
                # list is unordered.
                where = (
                    f"#{list_context['position']} on"
                    if (selected_list or {}).get("is_ranked")
                    else "On"
                )
                reasons.append(
                    f"{where} {list_context['owner']}'s {list_context['name']} list"
                )
            if len(watchlist_ids) == len(selected_ids):
                reasons.append("On every selected profile's watchlist")
            elif watchlist_ids:
                reasons.append(f"On {len(watchlist_ids)} selected watchlist(s)")
            if len(unseen_ids) == len(selected_ids):
                reasons.append("Unseen by everyone selected")
            elif unseen_ids:
                reasons.append(f"Still unseen by {len(unseen_ids)} selected profile(s)")
            average_rating = _average(evidence_ratings)
            if average_rating is not None:
                if outside and watched_rows:
                    rating_source = "selected and tracked-community evidence"
                elif outside:
                    rating_source = "tracked-community evidence"
                else:
                    rating_source = "selected-group evidence"
                reasons.append(f"Rated {average_rating:.1f} from {rating_source}")
            reason_provider = _provider_for_availability_reason(providers, availability)
            if reason_provider:
                reasons.append(_provider_availability_reason(reason_provider, region))

            certification = None
            if enrichment and isinstance(enrichment.raw_payload, dict):
                certification = enrichment.raw_payload.get("certification")
            recommendations.append(
                {
                    "movie": {
                        **self._movie_summary(movie, enrichment),
                        "runtime_minutes": runtime,
                        "genres": genres,
                        "certification": certification,
                        "providers": [
                            {
                                "id": provider.provider_id,
                                "name": provider.provider_name,
                                "logo_url": provider.logo_path,
                                "type": provider.provider_type,
                                "regions": list(provider.regions),
                            }
                            for provider in providers
                        ],
                    },
                    "on_watchlist_by": sorted(selected_usernames[value] for value in watchlist_ids),
                    "watched_by": sorted(selected_usernames[value] for value in watched_ids),
                    "unseen_by": sorted(selected_usernames[value] for value in unseen_ids),
                    "liked_by": sorted(selected_usernames[value] for value in liked_ids),
                    "blind_spot_source": (
                        {
                            "username": blind_spot_source.username,
                            "rating": _round(blind_spot_source.rating, 1),
                            "liked": blind_spot_source.liked,
                        }
                        if blind_spot_source is not None
                        else None
                    ),
                    "list_context": list_context,
                    "group_fit_score": _round(score, 1) or 0,
                    "reasons": reasons,
                }
            )
        recommendations.sort(
            key=lambda item: (
                -item["group_fit_score"],
                -len(item["on_watchlist_by"]),
                item["movie"]["title"],
            )
        )
        recommendations = recommendations[:limit]

        returned_movie_ids = {
            int(item["movie"]["movie_id"])
            for item in recommendations
            if item["movie"].get("movie_id") is not None
        }
        missing_enrichment_ids = returned_movie_ids - set(enrichments_by_movie)
        if missing_enrichment_ids:
            enrichments_by_movie.update(
                {
                    enrichment.movie_id: enrichment
                    for enrichment in (
                        self.db.query(MovieEnrichment)
                        .filter(MovieEnrichment.movie_id.in_(missing_enrichment_ids))
                        .populate_existing()
                        .all()
                    )
                }
            )

        returned_stored_providers: Dict[int, List[MovieWatchProvider]] = defaultdict(list)
        if returned_movie_ids:
            returned_provider_query = self.db.query(MovieWatchProvider).filter(
                MovieWatchProvider.movie_id.in_(returned_movie_ids),
                MovieWatchProvider.provider_type.in_(SUPPORTED_PROVIDER_TYPES),
            )
            if region != WORLDWIDE_REGION:
                returned_provider_query = returned_provider_query.filter(
                    func.upper(MovieWatchProvider.region) == region
                )
            for provider in returned_provider_query.order_by(
                MovieWatchProvider.display_priority.asc()
            ).all():
                returned_stored_providers[provider.movie_id].append(provider)

        for item in recommendations:
            movie_id = item["movie"].get("movie_id")
            if movie_id is None:
                continue
            movie_id = int(movie_id)
            movie = watchlist_by_movie[movie_id]["movie"]
            enrichment = enrichments_by_movie.get(movie_id)
            providers = _merge_provider_availability(
                movie_id,
                returned_stored_providers.get(movie_id, []),
                _providers_from_cached_tmdb(
                    movie_id,
                    enrichment.raw_payload if enrichment else None,
                    region=region,
                ),
            )
            providers_by_movie[movie_id] = providers
            certification = None
            if enrichment and isinstance(enrichment.raw_payload, dict):
                certification = enrichment.raw_payload.get("certification")
            item["movie"] = {
                **self._movie_summary(movie, enrichment),
                # Same guard as the candidate loop: TMDB writes an unfilled
                # runtime as 0, and this second pass rebuilds the movie payload
                # wholesale, so writing the raw column here put the zeros
                # straight back and handed them the top of a "Shortest runtime"
                # sort.
                "runtime_minutes": (enrichment.runtime_minutes or None) if enrichment else None,
                "genres": _as_string_list(enrichment.genres) if enrichment else [],
                "certification": certification,
                "providers": [
                    {
                        "id": provider.provider_id,
                        "name": provider.provider_name,
                        "logo_url": provider.logo_path,
                        "type": provider.provider_type,
                        "regions": list(provider.regions),
                    }
                    for provider in providers
                ],
            }
            reason_provider = _provider_for_availability_reason(providers, availability)
            if reason_provider:
                provider_reason = _provider_availability_reason(reason_provider, region)
                if provider_reason not in item["reasons"]:
                    item["reasons"].append(provider_reason)

        event_rows = self._event_rows(profiles)
        coverage_payload = self._coverage_payload(
            profiles,
            states=states,
            events=event_rows,
        )
        coverage = self._feature_coverage(
            profiles,
            "watch_together",
            event_rows,
            states,
            coverage_payload,
        )
        # Every mode except list_mission builds its candidate pool from the
        # selected profiles' watchlists, so a profile with no watchlist import
        # silently contributes nothing while coverage still reads green. Only
        # list_mission genuinely does not need one.
        required_surface_names = {
            "list_mission": {"ratings", "lists"},
        }.get(mode, {"ratings", "watchlist"})
        required_surfaces = [
            surface
            for profile_payload in coverage_payload["profiles"]
            for surface in profile_payload["surfaces"]
            if surface["surface"] in required_surface_names
            and not (
                mode == "list_mission"
                and surface["surface"] == "lists"
                and profile_payload["profile"]["username"]
                != (selected_list or {}).get("owner")
            )
        ]
        missing_surfaces = [
            surface for surface in required_surfaces if surface["status"] == "missing"
        ]
        partial_surfaces = [
            surface
            for surface in required_surfaces
            if surface["status"] in {"partial", "stale"}
        ]
        if missing_surfaces:
            coverage["status"] = "blocked"
        elif partial_surfaces:
            coverage["status"] = "partial"
        else:
            coverage["status"] = "ready"
        coverage["score"] = round(
            100
            * sum(self._surface_score(surface) for surface in required_surfaces)
            / max(len(required_surfaces), 1)
        )
        coverage["blockers"] = list(
            dict.fromkeys(
                f"{surface['surface']} is unavailable for one or more selected profiles"
                for surface in missing_surfaces
            )
        )
        coverage["warnings"] = list(
            dict.fromkeys(
                [
                    *(
                        warning
                        for warning in coverage["warnings"]
                        # The warning is about the watchlist import, which
                        # every watchlist-driven mode depends on -- stripping it
                        # everywhere but watchlist_overlap hid a real gap from
                        # the modes that share the same input.
                        if mode != "list_mission"
                        or not warning.startswith("Watchlist overlap requires")
                    ),
                    *(
                        f"{surface['surface']} coverage is partial"
                        for surface in partial_surfaces
                    ),
                ]
            )
        )
        # Only a claim about films that were actually checked. With no candidates
        # at all `providers_by_movie` is empty, `any({})` is false, and an empty
        # result set was being reported as missing streaming data — blaming the
        # TMDB cache for a query that simply matched nothing, and downgrading
        # coverage on the strength of it.
        # Say when a filter hid films rather than letting an empty-looking
        # result imply the watchlists held nothing matching.
        if unenriched_skipped:
            if coverage["status"] == "ready":
                coverage["status"] = "partial"
            coverage["warnings"].append(
                f"{unenriched_skipped} candidate"
                f"{'' if unenriched_skipped == 1 else 's'} could not be checked "
                "against the runtime and genre filters because TMDB metadata "
                "has not been imported for them."
            )
        if providers_by_movie and not any(providers_by_movie.values()):
            if coverage["status"] == "ready":
                coverage["status"] = "partial"
                coverage["score"] = min(coverage["score"], 75)
            availability_scope = "any country" if region == WORLDWIDE_REGION else region
            coverage["warnings"].append(
                f"Streaming availability for {availability_scope} is unavailable in the cached TMDB data."
            )
        if mode == "watchlist_overlap" and coverage["status"] == "blocked":
            coverage["blockers"] = list(
                dict.fromkeys(
                    [
                        *coverage["blockers"],
                        "Watchlist overlap is not treated as empty when a selected profile has no authoritative watchlist import.",
                    ]
                )
            )

        recommendation_regions = {
            provider_region
            for item in recommendations
            for provider in item["movie"]["providers"]
            for provider_region in provider["regions"]
        }
        return {
            "selected_profiles": [profile.username for profile in profiles],
            "mode": mode,
            "region": region,
            "region_scope": (
                "worldwide" if region == WORLDWIDE_REGION else "country"
            ),
            "selected_list": selected_list,
            "available_lists": available_lists,
            "coverage": coverage,
            "summary": {
                "candidates": len(recommendations),
                "on_every_watchlist": sum(
                    len(item["on_watchlist_by"]) == len(profiles) for item in recommendations
                ),
                "unseen_by_everyone": sum(
                    len(item["unseen_by"]) == len(profiles) for item in recommendations
                ),
                "available_in_region": sum(bool(item["movie"]["providers"]) for item in recommendations),
                "available_countries": len(recommendation_regions),
                "collective_blind_spots": sum(
                    item["blind_spot_source"] is not None for item in recommendations
                ),
                "remaining_list_items": sum(
                    item["list_context"] is not None for item in recommendations
                ),
            },
            "recommendations": recommendations,
        }
