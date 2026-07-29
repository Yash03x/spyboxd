"""
Database package initialization
"""
from .connection import (
    DATABASE_URL,
    SessionLocal,
    engine,
    get_database_url,
    get_db,
    init_db,
)
from .models import (
    Movie,
    MovieEnrichment,
    MovieList,
    MovieListItem,
    MovieWatchProvider,
    Profile,
    ProfileDataChange,
    ProfileFeedState,
    ProfileFavoriteMovie,
    ProfileFilm,
    ProfileSourceActivity,
    ProfileSync,
    Rating,
    Review,
    ScrapingJob,
    SyncDataset,
    SystemMetrics,
    WatchEvent,
    WatchlistItem,
)
from .repository import (
    ProfileRepository, 
    RatingRepository, 
    ReviewRepository, 
    AnalyticsRepository
)

__all__ = [
    'DATABASE_URL', 'engine', 'SessionLocal', 'get_db', 'get_database_url', 'init_db',
    'Profile', 'ProfileSync', 'ProfileFeedState', 'SyncDataset', 'Movie', 'ProfileFilm',
    'ProfileDataChange', 'ProfileSourceActivity',
    'WatchEvent', 'WatchlistItem', 'MovieList', 'MovieListItem',
    'ProfileFavoriteMovie', 'MovieEnrichment', 'MovieWatchProvider',
    'Rating', 'Review', 'ScrapingJob', 'SystemMetrics',
    'ProfileRepository', 'RatingRepository', 'ReviewRepository', 
    'AnalyticsRepository'
]
