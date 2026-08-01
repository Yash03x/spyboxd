from __future__ import annotations

from typing import Dict, Optional, Tuple

from sqlalchemy.orm import Session

from database.models import Movie
from services.import_contracts import MovieIdentity, normalize_letterboxd_url


def _usable_poster_url(value: Optional[str]) -> Optional[str]:
    """Reject Letterboxd's lazy-load placeholder.

    Poster images are resolved client-side, so a scraped ``img src`` is the
    static empty-poster asset until their JS runs. Persisting it would mask
    the real poster (TMDB enrichment supplies those).
    """
    absolute = normalize_letterboxd_url(value)
    if not absolute or "empty-poster" in absolute:
        return None
    return absolute


class MovieResolver:
    """Resolve a source movie to one canonical row without committing the session."""

    def __init__(self, db: Session, profile_sync_id: int):
        self.db = db
        self.profile_sync_id = profile_sync_id
        self._by_key: Dict[str, Movie] = {}
        self._by_title_year: Dict[Tuple[str, Optional[int]], Movie] = {}

    def resolve(self, identity: MovieIdentity) -> Movie:
        cached = self._by_key.get(identity.canonical_key)
        if cached is not None:
            self._merge_metadata(cached, identity)
            return cached

        movie = self._find_stable_identity(identity)
        if movie is None:
            movie = self._find_compatible_title_year(identity)
        if movie is None:
            movie = Movie(
                canonical_key=identity.canonical_key,
                letterboxd_id=identity.letterboxd_id,
                letterboxd_slug=identity.letterboxd_slug,
                title=identity.title,
                normalized_title=identity.normalized_title,
                release_year=identity.release_year,
                letterboxd_url=normalize_letterboxd_url(identity.letterboxd_url),
                poster_url=_usable_poster_url(identity.poster_url),
                first_seen_profile_sync_id=self.profile_sync_id,
                last_seen_profile_sync_id=self.profile_sync_id,
            )
            self.db.add(movie)
            self.db.flush()
        else:
            self._merge_metadata(movie, identity)

        self._cache(movie, identity)
        return movie

    def _find_stable_identity(self, identity: MovieIdentity) -> Optional[Movie]:
        if identity.letterboxd_id:
            movie = (
                self.db.query(Movie)
                .filter(Movie.letterboxd_id == identity.letterboxd_id)
                .first()
            )
            if movie is not None:
                return movie
        if identity.letterboxd_slug:
            movie = (
                self.db.query(Movie)
                .filter(Movie.letterboxd_slug == identity.letterboxd_slug)
                .first()
            )
            if movie is not None:
                return movie
        return self.db.query(Movie).filter(Movie.canonical_key == identity.canonical_key).first()

    def _find_compatible_title_year(self, identity: MovieIdentity) -> Optional[Movie]:
        key = (identity.normalized_title, identity.release_year)
        if key in self._by_title_year:
            candidate = self._by_title_year[key]
        else:
            candidates = (
                self.db.query(Movie)
                .filter(
                    Movie.normalized_title == identity.normalized_title,
                    Movie.release_year == identity.release_year,
                )
                .limit(2)
                .all()
            )
            if len(candidates) != 1:
                return None
            candidate = candidates[0]

        if (
            identity.letterboxd_id
            and candidate.letterboxd_id
            and candidate.letterboxd_id != identity.letterboxd_id
        ):
            return None
        if (
            identity.letterboxd_slug
            and candidate.letterboxd_slug
            and candidate.letterboxd_slug != identity.letterboxd_slug
        ):
            return None
        return candidate

    def _merge_metadata(self, movie: Movie, identity: MovieIdentity) -> None:
        if identity.letterboxd_id and not movie.letterboxd_id:
            movie.letterboxd_id = identity.letterboxd_id
        if identity.letterboxd_slug and not movie.letterboxd_slug:
            movie.letterboxd_slug = identity.letterboxd_slug
        # Every source funnels through the resolver, so normalising here keeps
        # relative hrefs (data-item-link is site-relative) from reaching the
        # database and rendering as in-app links.
        identity_url = normalize_letterboxd_url(identity.letterboxd_url)
        if identity_url and (not movie.letterboxd_url or movie.letterboxd_url.startswith("/")):
            movie.letterboxd_url = identity_url
        identity_poster = _usable_poster_url(identity.poster_url)
        if identity_poster and (
            not movie.poster_url
            or movie.poster_url.startswith("/")
            or "empty-poster" in movie.poster_url
        ):
            movie.poster_url = identity_poster
        if not movie.title and identity.title:
            movie.title = identity.title
            movie.normalized_title = identity.normalized_title
        if movie.release_year is None and identity.release_year is not None:
            movie.release_year = identity.release_year

        # Promote a title-only fallback key after a stable Letterboxd identifier arrives,
        # but only when the desired key is not already owned by another movie.
        if movie.canonical_key != identity.canonical_key and (
            identity.letterboxd_id or identity.letterboxd_slug
        ):
            conflict = (
                self.db.query(Movie.id)
                .filter(
                    Movie.canonical_key == identity.canonical_key,
                    Movie.id != movie.id,
                )
                .first()
            )
            if conflict is None:
                movie.canonical_key = identity.canonical_key

        movie.last_seen_profile_sync_id = self.profile_sync_id
        self.db.flush()
        self._cache(movie, identity)

    def _cache(self, movie: Movie, identity: MovieIdentity) -> None:
        self._by_key[identity.canonical_key] = movie
        self._by_key[movie.canonical_key] = movie
        self._by_title_year[(movie.normalized_title, movie.release_year)] = movie
