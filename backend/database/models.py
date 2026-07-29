import math
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional, Dict, Any

Base = declarative_base()


def _json_type():
    """Use JSONB on PostgreSQL while keeping metadata portable for tests/tools."""
    return JSON().with_variant(JSONB(), "postgresql")


def _safe_float(value, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric):
        return default
    return numeric

class Profile(Base):
    __tablename__ = "profiles"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_scraped_at = Column(DateTime(timezone=True), nullable=True)
    scraping_status = Column(String(20), default="pending")
    
    # Profile metrics
    avg_rating = Column(Float, default=0.0)
    total_reviews = Column(Integer, default=0)
    join_date = Column(Date, nullable=True)
    
    # Additional metadata
    is_active = Column(Boolean, default=True)
    profile_image_url = Column(String(500), nullable=True)
    display_name = Column(String(200), nullable=True)
    bio = Column(Text, nullable=True)
    location = Column(String(100), nullable=True)
    website = Column(String(200), nullable=True)
    following_count = Column(Integer, nullable=True)
    followers_count = Column(Integer, nullable=True)
    reported_total_films = Column(Integer, nullable=True)
    reported_total_reviews = Column(Integer, nullable=True)
    reported_total_lists = Column(Integer, nullable=True)
    metadata_synced_at = Column(DateTime(timezone=True), nullable=True)
    last_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    
    # Enhanced metrics stored as JSON
    enhanced_metrics = Column(JSON, nullable=True)
    
    # Relationships
    ratings = relationship("Rating", back_populates="profile", cascade="all, delete-orphan")
    reviews = relationship("Review", back_populates="profile", cascade="all, delete-orphan")
    scraping_jobs = relationship("ScrapingJob", back_populates="profile", cascade="all, delete-orphan")
    lists = relationship("MovieList", back_populates="profile", cascade="all, delete-orphan")
    profile_syncs = relationship(
        "ProfileSync",
        back_populates="profile",
        cascade="all, delete-orphan",
        foreign_keys="ProfileSync.profile_id",
    )
    feed_state = relationship(
        "ProfileFeedState",
        back_populates="profile",
        cascade="all, delete-orphan",
        uselist=False,
    )
    last_profile_sync = relationship(
        "ProfileSync",
        foreign_keys=[last_profile_sync_id],
        post_update=True,
    )
    profile_films = relationship("ProfileFilm", back_populates="profile", cascade="all, delete-orphan")
    watch_events = relationship("WatchEvent", back_populates="profile", cascade="all, delete-orphan")
    watchlist_items = relationship("WatchlistItem", back_populates="profile", cascade="all, delete-orphan")
    favorite_movies = relationship(
        "ProfileFavoriteMovie",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    data_changes = relationship(
        "ProfileDataChange",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    source_activities = relationship(
        "ProfileSourceActivity",
        back_populates="profile",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("following_count IS NULL OR following_count >= 0", name="ck_profiles_following_nonnegative"),
        CheckConstraint("followers_count IS NULL OR followers_count >= 0", name="ck_profiles_followers_nonnegative"),
        CheckConstraint(
            "reported_total_films IS NULL OR reported_total_films >= 0",
            name="ck_profiles_reported_films_nonnegative",
        ),
        CheckConstraint(
            "reported_total_reviews IS NULL OR reported_total_reviews >= 0",
            name="ck_profiles_reported_reviews_nonnegative",
        ),
        CheckConstraint(
            "reported_total_lists IS NULL OR reported_total_lists >= 0",
            name="ck_profiles_reported_lists_nonnegative",
        ),
    )
    
    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            # total_movies removed - use calculated total_films instead
            "avg_rating": _safe_float(self.avg_rating, 0.0),
            "total_reviews": self.total_reviews,
            "join_date": self.join_date.isoformat() if self.join_date else None,
            "last_scraped_at": self.last_scraped_at.isoformat() if self.last_scraped_at else None,
            "scraping_status": self.scraping_status,
            "profile_image_url": self.profile_image_url,
            "display_name": self.display_name,
            "bio": self.bio,
            "location": self.location,
            "website": self.website,
            "following_count": self.following_count,
            "followers_count": self.followers_count,
            "reported_total_films": self.reported_total_films,
            "reported_total_reviews": self.reported_total_reviews,
            "reported_total_lists": self.reported_total_lists,
            "metadata_synced_at": self.metadata_synced_at.isoformat() if self.metadata_synced_at else None,
            "enhanced_metrics": self.enhanced_metrics or {}
        }


class ProfileSync(Base):
    __tablename__ = "profile_syncs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    source_kind = Column(String(50), nullable=False)
    source_fingerprint = Column(String(200), nullable=False)
    importer_version = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, server_default="running")
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    manifest = Column(_json_type(), nullable=False, server_default=sql_text("'{}'"))
    coverage = Column(_json_type(), nullable=False, server_default=sql_text("'{}'"))
    stats = Column(_json_type(), nullable=False, server_default=sql_text("'{}'"))
    error_message = Column(Text, nullable=True)

    profile = relationship("Profile", back_populates="profile_syncs", foreign_keys=[profile_id])
    datasets = relationship("SyncDataset", back_populates="profile_sync", cascade="all, delete-orphan")
    data_changes = relationship(
        "ProfileDataChange",
        back_populates="profile_sync",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "source_fingerprint",
            "importer_version",
            name="unique_profile_sync_fingerprint",
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'skipped')",
            name="ck_profile_syncs_status",
        ),
        Index("ix_profile_syncs_profile_started", "profile_id", "started_at"),
    )


class ProfileFeedState(Base):
    """Operational state for conservative, incremental Letterboxd RSS polling.

    RSS never replaces an authoritative profile snapshot.  This row only keeps
    conditional-request metadata, backoff state, and a short lease so a single
    due profile cannot be fetched concurrently by multiple poller processes.
    """

    __tablename__ = "profile_feed_states"

    profile_id = Column(
        Integer,
        ForeignKey("profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    feed_url = Column(String(500), nullable=False)
    etag = Column(String(500), nullable=True)
    last_modified = Column(String(200), nullable=True)
    content_sha256 = Column(String(64), nullable=True)
    activity_guids = Column(_json_type(), nullable=False, server_default=sql_text("'[]'"))
    last_polled_at = Column(DateTime(timezone=True), nullable=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    last_changed_at = Column(DateTime(timezone=True), nullable=True)
    next_poll_at = Column(DateTime(timezone=True), nullable=True)
    lease_until = Column(DateTime(timezone=True), nullable=True)
    consecutive_failures = Column(Integer, nullable=False, server_default="0")
    last_http_status = Column(Integer, nullable=True)
    last_error = Column(Text, nullable=True)
    requires_full_sync = Column(Boolean, nullable=False, server_default=sql_text("false"))
    reconciliation_reason = Column(Text, nullable=True)
    latest_item_guid = Column(String(200), nullable=True)
    latest_item_published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    profile = relationship("Profile", back_populates="feed_state")

    __table_args__ = (
        CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_profile_feed_states_failures_nonnegative",
        ),
        CheckConstraint(
            "last_http_status IS NULL OR (last_http_status >= 100 AND last_http_status <= 599)",
            name="ck_profile_feed_states_http_status",
        ),
        Index("ix_profile_feed_states_next_poll", "next_poll_at", "profile_id"),
        Index("ix_profile_feed_states_lease", "lease_until"),
    )


class SyncDataset(Base):
    __tablename__ = "sync_datasets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="CASCADE"),
        nullable=False,
    )
    dataset_name = Column(String(50), nullable=False)
    source_filename = Column(String(255), nullable=True)
    source_sha256 = Column(String(64), nullable=True)
    source_row_count = Column(Integer, nullable=False, server_default="0")
    imported_row_count = Column(Integer, nullable=False, server_default="0")
    is_authoritative = Column(Boolean, nullable=False, server_default=sql_text("false"))
    metadata_payload = Column("metadata", _json_type(), nullable=False, server_default=sql_text("'{}'"))

    profile_sync = relationship("ProfileSync", back_populates="datasets")

    __table_args__ = (
        UniqueConstraint("profile_sync_id", "dataset_name", name="unique_sync_dataset_name"),
        CheckConstraint("source_row_count >= 0", name="ck_sync_datasets_source_rows_nonnegative"),
        CheckConstraint("imported_row_count >= 0", name="ck_sync_datasets_imported_rows_nonnegative"),
    )


class ProfileDataChange(Base):
    """An immutable, semantic delta detected by a completed profile sync."""

    __tablename__ = "profile_data_changes"

    id = Column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="CASCADE"),
        nullable=False,
    )
    change_key = Column(String(600), nullable=False)
    change_type = Column(String(50), nullable=False)
    entity_type = Column(String(30), nullable=False)
    entity_key = Column(String(600), nullable=False)
    source_kind = Column(String(50), nullable=False)
    source_dataset = Column(String(50), nullable=True)
    movie_id = Column(BigInteger, ForeignKey("movies.id", ondelete="SET NULL"), nullable=True)
    movie_list_id = Column(Integer, ForeignKey("movie_lists.id", ondelete="SET NULL"), nullable=True)
    before_payload = Column("before", _json_type(), nullable=False, server_default=sql_text("'{}'"))
    after_payload = Column("after", _json_type(), nullable=False, server_default=sql_text("'{}'"))
    source_date = Column(Date, nullable=True)
    detected_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    profile = relationship("Profile", back_populates="data_changes")
    profile_sync = relationship("ProfileSync", back_populates="data_changes")
    movie = relationship("Movie", back_populates="data_changes")
    movie_list = relationship("MovieList", back_populates="data_changes")

    __table_args__ = (
        UniqueConstraint("profile_sync_id", "change_key", name="unique_profile_sync_change_key"),
        CheckConstraint(
            "entity_type IN ('film', 'watchlist', 'favorite', 'diary', 'review', 'list', 'list_item')",
            name="ck_profile_data_changes_entity_type",
        ),
        Index("ix_profile_data_changes_detected", "detected_at", "id"),
        Index("ix_profile_data_changes_profile_detected", "profile_id", "detected_at"),
    )


class ProfileSourceActivity(Base):
    """Dated source activity that is explicitly *not* a diary watch event.

    Letterboxd export ``Date`` values say when an account action occurred. They
    are useful provenance, but must never be treated as the date a film was
    watched. Only rows from ``diary.csv`` create :class:`WatchEvent` records.
    """

    __tablename__ = "profile_source_activities"

    id = Column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    movie_id = Column(BigInteger, ForeignKey("movies.id", ondelete="RESTRICT"), nullable=False)
    activity_key = Column(String(600), nullable=False)
    activity_type = Column(String(50), nullable=False)
    activity_date = Column(Date, nullable=False)
    date_semantics = Column(String(50), nullable=False)
    source_kind = Column(String(50), nullable=False)
    source_dataset = Column(String(50), nullable=False)
    source_row_number = Column(Integer, nullable=True)
    first_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    profile = relationship("Profile", back_populates="source_activities")
    movie = relationship("Movie", back_populates="source_activities")

    __table_args__ = (
        UniqueConstraint("profile_id", "activity_key", name="unique_profile_source_activity"),
        CheckConstraint(
            "activity_type IN ('watched_marked', 'rating_recorded', 'like_recorded', 'watchlist_added')",
            name="ck_profile_source_activities_type",
        ),
        CheckConstraint(
            "date_semantics IN ('account_activity', 'watchlist_added')",
            name="ck_profile_source_activities_date_semantics",
        ),
        CheckConstraint(
            "source_row_number IS NULL OR source_row_number > 0",
            name="ck_profile_source_activities_row_positive",
        ),
        Index("ix_profile_source_activities_profile_date", "profile_id", "activity_date"),
        Index("ix_profile_source_activities_movie_date", "movie_id", "activity_date"),
    )


class Movie(Base):
    __tablename__ = "movies"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    canonical_key = Column(String(500), nullable=False)
    letterboxd_id = Column(String(100), nullable=True)
    letterboxd_slug = Column(String(250), nullable=True)
    title = Column(String(300), nullable=False)
    normalized_title = Column(String(300), nullable=False)
    release_year = Column(Integer, nullable=True)
    letterboxd_url = Column(String(500), nullable=True)
    poster_url = Column(String(500), nullable=True)
    tmdb_id = Column(BigInteger, nullable=True)
    imdb_id = Column(String(32), nullable=True)
    tmdb_lookup_attempted_at = Column(DateTime(timezone=True), nullable=True)
    tmdb_lookup_expires_at = Column(DateTime(timezone=True), nullable=True)
    tmdb_lookup_key = Column(String(64), nullable=True)
    first_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    profile_films = relationship("ProfileFilm", back_populates="movie")
    watch_events = relationship("WatchEvent", back_populates="movie")
    watchlist_items = relationship("WatchlistItem", back_populates="movie")
    list_items = relationship("MovieListItem", back_populates="movie")
    profile_favorites = relationship("ProfileFavoriteMovie", back_populates="movie")
    data_changes = relationship("ProfileDataChange", back_populates="movie")
    source_activities = relationship("ProfileSourceActivity", back_populates="movie")
    enrichment = relationship(
        "MovieEnrichment",
        back_populates="movie",
        cascade="all, delete-orphan",
        uselist=False,
    )
    watch_providers = relationship(
        "MovieWatchProvider",
        back_populates="movie",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("canonical_key", name="unique_movie_canonical_key"),
        Index(
            "uq_movies_letterboxd_id",
            "letterboxd_id",
            unique=True,
            postgresql_where=sql_text("letterboxd_id IS NOT NULL"),
        ),
        Index(
            "uq_movies_tmdb_id",
            "tmdb_id",
            unique=True,
            postgresql_where=sql_text("tmdb_id IS NOT NULL"),
        ),
        Index(
            "uq_movies_imdb_id",
            "imdb_id",
            unique=True,
            postgresql_where=sql_text("imdb_id IS NOT NULL"),
        ),
        Index("ix_movies_normalized_title_year", "normalized_title", "release_year"),
        Index("ix_movies_letterboxd_slug", "letterboxd_slug"),
        Index("ix_movies_tmdb_lookup_expires_at", "tmdb_lookup_expires_at"),
    )

class Rating(Base):
    __tablename__ = "ratings"
    
    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False)
    movie_id = Column(BigInteger, ForeignKey("movies.id", ondelete="SET NULL"), nullable=True)
    first_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    removed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Movie details
    movie_title = Column(String(300), nullable=False)
    movie_year = Column(Integer, nullable=True)
    letterboxd_id = Column(String(100), nullable=True, index=True)
    
    # Rating details
    rating = Column(Float, nullable=True)  # 0.5 to 5.0 stars
    watched_date = Column(Date, nullable=True)
    is_rewatch = Column(Boolean, default=False)
    is_liked = Column(Boolean, default=False)  # User liked this film
    
    # Additional metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    tags = Column(JSON, nullable=True)  # Array of tags
    film_slug = Column(String(200), nullable=True)
    poster_url = Column(String(500), nullable=True)
    
    # Relationships
    profile = relationship("Profile", back_populates="ratings")
    movie = relationship("Movie", foreign_keys=[movie_id])
    profile_film = relationship("ProfileFilm", back_populates="legacy_rating", uselist=False)
    
    # Prevent duplicate ratings for same movie by same user
    __table_args__ = (
        UniqueConstraint('profile_id', 'movie_title', 'movie_year', name='unique_user_movie_rating'),
        Index("ix_ratings_movie_profile", "movie_id", "profile_id"),
    )


class ProfileFilm(Base):
    __tablename__ = "profile_films"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    movie_id = Column(BigInteger, ForeignKey("movies.id", ondelete="RESTRICT"), nullable=False)
    legacy_rating_id = Column(
        Integer,
        ForeignKey("ratings.id", ondelete="SET NULL"),
        nullable=True,
    )
    rating = Column(Float, nullable=True)
    is_liked = Column(Boolean, nullable=False, server_default=sql_text("false"))
    tags = Column(_json_type(), nullable=False, server_default=sql_text("'[]'"))
    first_watched_date = Column(Date, nullable=True)
    latest_watched_date = Column(Date, nullable=True)
    watch_count = Column(Integer, nullable=False, server_default="0")
    rewatch_count = Column(Integer, nullable=False, server_default="0")
    has_review = Column(Boolean, nullable=False, server_default=sql_text("false"))
    first_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    removed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    profile = relationship("Profile", back_populates="profile_films")
    movie = relationship("Movie", back_populates="profile_films")
    legacy_rating = relationship("Rating", back_populates="profile_film")
    watch_events = relationship("WatchEvent", back_populates="profile_film")

    __table_args__ = (
        UniqueConstraint("profile_id", "movie_id", name="unique_profile_film"),
        UniqueConstraint("legacy_rating_id", name="unique_profile_film_legacy_rating"),
        CheckConstraint("rating IS NULL OR (rating >= 0.5 AND rating <= 5.0)", name="ck_profile_films_rating"),
        CheckConstraint("watch_count >= 0", name="ck_profile_films_watch_count_nonnegative"),
        CheckConstraint("rewatch_count >= 0", name="ck_profile_films_rewatch_count_nonnegative"),
        CheckConstraint("rewatch_count <= watch_count", name="ck_profile_films_rewatch_le_watch"),
        Index("ix_profile_films_movie_profile", "movie_id", "profile_id"),
        Index("ix_profile_films_profile_removed", "profile_id", "removed_at"),
    )


class WatchEvent(Base):
    __tablename__ = "watch_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    movie_id = Column(BigInteger, ForeignKey("movies.id", ondelete="RESTRICT"), nullable=False)
    profile_film_id = Column(
        BigInteger,
        ForeignKey("profile_films.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_key = Column(String(600), nullable=False)
    watched_date = Column(Date, nullable=False)
    rating = Column(Float, nullable=True)
    is_rewatch = Column(Boolean, nullable=False, server_default=sql_text("false"))
    is_liked = Column(Boolean, nullable=False, server_default=sql_text("false"))
    has_review = Column(Boolean, nullable=False, server_default=sql_text("false"))
    tags = Column(_json_type(), nullable=False, server_default=sql_text("'[]'"))
    source_kind = Column(String(50), nullable=False)
    source_entry_id = Column(String(200), nullable=True)
    source_url = Column(String(500), nullable=True)
    source_row_number = Column(Integer, nullable=True)
    first_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    superseded_at = Column(DateTime(timezone=True), nullable=True)
    superseded_by_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    profile = relationship("Profile", back_populates="watch_events")
    movie = relationship("Movie", back_populates="watch_events")
    profile_film = relationship("ProfileFilm", back_populates="watch_events")

    __table_args__ = (
        UniqueConstraint("profile_id", "event_key", name="unique_profile_watch_event"),
        CheckConstraint("rating IS NULL OR (rating >= 0.5 AND rating <= 5.0)", name="ck_watch_events_rating"),
        CheckConstraint("source_row_number IS NULL OR source_row_number > 0", name="ck_watch_events_source_row_positive"),
        Index("ix_watch_events_profile_date", "profile_id", "watched_date"),
        Index(
            "ix_watch_events_movie_date_active",
            "movie_id",
            "watched_date",
            "profile_id",
            postgresql_where=sql_text("superseded_at IS NULL"),
        ),
    )

class Review(Base):
    __tablename__ = "reviews"
    
    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False)
    movie_id = Column(BigInteger, ForeignKey("movies.id", ondelete="SET NULL"), nullable=True)
    first_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_review_key = Column(String(600), nullable=True)
    source_url = Column(String(500), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    removed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Movie details
    movie_title = Column(String(300), nullable=False)
    movie_year = Column(Integer, nullable=True)
    letterboxd_id = Column(String(100), nullable=True, index=True)
    
    # Review content
    review_text = Column(Text, nullable=True)
    rating = Column(Float, nullable=True)
    contains_spoilers = Column(Boolean, default=False)
    tags = Column(_json_type(), nullable=False, server_default=sql_text("'[]'"))
    
    # Engagement metrics
    likes_count = Column(Integer, default=0)
    comments_count = Column(Integer, default=0)
    
    # Timestamps
    published_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    profile = relationship("Profile", back_populates="reviews")
    movie = relationship("Movie", foreign_keys=[movie_id])

    __table_args__ = (
        Index("ix_reviews_profile_movie", "profile_id", "movie_id"),
        Index(
            "uq_reviews_profile_source_key",
            "profile_id",
            "source_review_key",
            unique=True,
            postgresql_where=sql_text("source_review_key IS NOT NULL"),
        ),
    )

class MovieList(Base):
    __tablename__ = "movie_lists"
    
    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False)
    
    # List details
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    is_public = Column(Boolean, default=True)
    is_ranked = Column(Boolean, default=False)
    
    # List metadata
    movie_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Movies in the list (stored as JSON array)
    movies = Column(JSON, nullable=True)  # Array of movie objects
    tags = Column(_json_type(), nullable=False, server_default=sql_text("'[]'"))
    source_list_key = Column(String(600), nullable=True)
    letterboxd_url = Column(String(500), nullable=True)
    published_date = Column(Date, nullable=True)
    first_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    removed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    profile = relationship("Profile", back_populates="lists")
    items = relationship("MovieListItem", back_populates="movie_list", cascade="all, delete-orphan")
    data_changes = relationship("ProfileDataChange", back_populates="movie_list")

    __table_args__ = (
        Index("ix_movie_lists_profile_id", "profile_id"),
        Index(
            "uq_movie_lists_profile_source_key",
            "profile_id",
            "source_list_key",
            unique=True,
            postgresql_where=sql_text("source_list_key IS NOT NULL"),
        ),
    )


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    movie_id = Column(BigInteger, ForeignKey("movies.id", ondelete="RESTRICT"), nullable=False)
    added_date = Column(Date, nullable=True)
    added_date_source_kind = Column(String(50), nullable=True)
    position = Column(Integer, nullable=True)
    first_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    removed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    profile = relationship("Profile", back_populates="watchlist_items")
    movie = relationship("Movie", back_populates="watchlist_items")

    __table_args__ = (
        UniqueConstraint("profile_id", "movie_id", name="unique_profile_watchlist_movie"),
        CheckConstraint("position IS NULL OR position > 0", name="ck_watchlist_items_position_positive"),
        Index(
            "ix_watchlist_items_movie_active",
            "movie_id",
            "profile_id",
            postgresql_where=sql_text("removed_at IS NULL"),
        ),
        Index("ix_watchlist_items_profile_removed", "profile_id", "removed_at"),
    )


class MovieListItem(Base):
    __tablename__ = "movie_list_items"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    movie_list_id = Column(
        Integer,
        ForeignKey("movie_lists.id", ondelete="CASCADE"),
        nullable=False,
    )
    movie_id = Column(BigInteger, ForeignKey("movies.id", ondelete="RESTRICT"), nullable=False)
    position = Column(Integer, nullable=False)
    notes = Column(Text, nullable=True)
    first_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    removed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    movie_list = relationship("MovieList", back_populates="items")
    movie = relationship("Movie", back_populates="list_items")

    __table_args__ = (
        UniqueConstraint("movie_list_id", "movie_id", name="unique_movie_list_item"),
        CheckConstraint("position > 0", name="ck_movie_list_items_position_positive"),
        Index(
            "uq_movie_list_items_active_position",
            "movie_list_id",
            "position",
            unique=True,
            postgresql_where=sql_text("removed_at IS NULL"),
        ),
        Index("ix_movie_list_items_movie", "movie_id", "movie_list_id"),
    )


class ProfileFavoriteMovie(Base):
    __tablename__ = "profile_favorite_movies"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    movie_id = Column(BigInteger, ForeignKey("movies.id", ondelete="RESTRICT"), nullable=False)
    position = Column(Integer, nullable=False)
    first_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_seen_profile_sync_id = Column(
        BigInteger,
        ForeignKey("profile_syncs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    profile = relationship("Profile", back_populates="favorite_movies")
    movie = relationship("Movie", back_populates="profile_favorites")

    __table_args__ = (
        UniqueConstraint("profile_id", "position", name="unique_profile_favorite_position"),
        UniqueConstraint("profile_id", "movie_id", name="unique_profile_favorite_movie"),
        CheckConstraint("position BETWEEN 1 AND 4", name="ck_profile_favorite_position"),
        Index("ix_profile_favorite_movies_movie", "movie_id", "profile_id"),
    )


class MovieEnrichment(Base):
    __tablename__ = "movie_enrichments"

    movie_id = Column(
        BigInteger,
        ForeignKey("movies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    original_title = Column(String(300), nullable=True)
    overview = Column(Text, nullable=True)
    runtime_minutes = Column(Integer, nullable=True)
    original_language = Column(String(20), nullable=True)
    release_date = Column(Date, nullable=True)
    genres = Column(_json_type(), nullable=False, server_default=sql_text("'[]'"))
    keywords = Column(_json_type(), nullable=False, server_default=sql_text("'[]'"))
    credits = Column(_json_type(), nullable=False, server_default=sql_text("'{}'"))
    production_countries = Column(_json_type(), nullable=False, server_default=sql_text("'[]'"))
    poster_path = Column(String(500), nullable=True)
    backdrop_path = Column(String(500), nullable=True)
    raw_payload = Column(_json_type(), nullable=False, server_default=sql_text("'{}'"))
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    movie = relationship("Movie", back_populates="enrichment")

    __table_args__ = (
        CheckConstraint(
            "runtime_minutes IS NULL OR runtime_minutes >= 0",
            name="ck_movie_enrichments_runtime_nonnegative",
        ),
        Index("ix_movie_enrichments_expires_at", "expires_at"),
    )


class MovieWatchProvider(Base):
    __tablename__ = "movie_watch_providers"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    movie_id = Column(BigInteger, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False)
    region = Column(String(2), nullable=False)
    provider_id = Column(Integer, nullable=False)
    provider_name = Column(String(200), nullable=False)
    provider_type = Column(String(20), nullable=False)
    logo_path = Column(String(500), nullable=True)
    display_priority = Column(Integer, nullable=True)
    link = Column(String(1000), nullable=True)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    movie = relationship("Movie", back_populates="watch_providers")

    __table_args__ = (
        UniqueConstraint(
            "movie_id",
            "region",
            "provider_id",
            "provider_type",
            name="unique_movie_watch_provider",
        ),
        CheckConstraint("char_length(region) = 2", name="ck_movie_watch_providers_region"),
        CheckConstraint(
            "provider_type IN ('flatrate', 'rent', 'buy', 'free', 'ads')",
            name="ck_movie_watch_providers_type",
        ),
        CheckConstraint(
            "display_priority IS NULL OR display_priority >= 0",
            name="ck_movie_watch_providers_priority_nonnegative",
        ),
        Index("ix_movie_watch_providers_region_movie", "region", "movie_id"),
    )

class ScrapingJob(Base):
    __tablename__ = "scraping_jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False)
    
    # Job status
    status = Column(String(20), default="queued")  # queued, in_progress, completed, failed
    progress_message = Column(Text, nullable=True)
    progress_percentage = Column(Float, default=0.0)
    
    # Timestamps
    queued_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Error handling
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    
    # Job metadata
    job_type = Column(String(50), default="full_scrape")  # full_scrape, update_recent, etc.
    job_params = Column(JSON, nullable=True)
    
    # Relationships
    profile = relationship("Profile", back_populates="scraping_jobs")

class SystemMetrics(Base):
    __tablename__ = "system_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    
    # System stats
    total_profiles = Column(Integer, default=0)
    total_movies_tracked = Column(Integer, default=0)
    total_reviews = Column(Integer, default=0)
    
    # Performance metrics
    avg_scraping_time = Column(Float, default=0.0)  # in minutes
    active_scraping_jobs = Column(Integer, default=0)
    
    # Additional metrics as JSON
    metrics = Column(JSON, nullable=True)
