# Database Schema

PostgreSQL schema for the current Spyboxd runtime.

The app is centered on imported full-profile datasets, not server-side scraping jobs.

## Compatibility Tables

### `profiles`

One row per tracked Letterboxd profile.

Key columns:

- `username`
- `last_scraped_at`
- `scraping_status`
- `avg_rating`
- `total_reviews`
- `join_date`
- `bio`
- `location`
- `website`
- `profile_image_url`
- `enhanced_metrics`

Notes:

- `scraping_status` now reflects import state more than scrape state.
- Full HTML syncs populate richer profile metadata than partial imports.

### `ratings`

One row per film per profile.

Key columns:

- `profile_id`
- `movie_title`
- `movie_year`
- `letterboxd_id`
- `rating`
- `watched_date`
- `is_rewatch`
- `is_liked`
- `film_slug`
- `poster_url`

Constraint:

- unique on `(profile_id, movie_title, movie_year)`

### `reviews`

One row per written review.

Key columns:

- `profile_id`
- `movie_title`
- `movie_year`
- `letterboxd_id`
- `review_text`
- `rating`
- `published_date`
- `likes_count`
- `comments_count`

These tables are retained for existing routes and response contracts. New imports dual-write them and the normalized foundation below in the same transaction.

## Normalized Data Foundation

### `profile_syncs` and `sync_datasets`

`profile_syncs` records processing state for each unique `(profile, source fingerprint, importer version)` artifact. Reprocessing the same fingerprint reuses and updates that row; a distinct bundle fingerprint creates another history row. It stores source kind, status, timing, aggregate counts, coverage, and any failure that reaches ingestion.

`sync_datasets` records the state of each imported surface such as films, diary, reviews, watchlist, lists, and favorites. Each row captures source/imported counts and whether that surface was authoritative for the sync.

Together these tables answer both "how fresh is this profile?" and "which missing values are real versus unavailable?"

### `profile_feed_states`

One operational row per tracked profile for conservative Letterboxd RSS polling. It stores the rolling GUID window, content hash, optional HTTP validators, success/failure timestamps, exponential-backoff schedule, and a short worker lease. A feed row never makes RSS authoritative: disappearance from the finite feed cannot remove profile data, and a non-overlapping window is held for another full sync.

### `movies`

One canonical movie row shared by every profile. Stable Letterboxd numeric IDs are preferred, with slug and conservative title/year fallback matching. Source URLs and posters live here; optional `tmdb_id` and `imdb_id` are attached later without making TMDB part of ingestion.

### `profile_films`

One current-state row per `(profile_id, movie_id)` containing the profile's latest rating/like/review state, first and latest watch dates, watch and rewatch counts, and sync lineage. `removed_at` is used when an authoritative later snapshot no longer contains the film.

### `watch_events`

Authoritative diary imports store one row per occurrence. Stable Letterboxd viewing IDs are preferred for `event_key`; deterministic occurrence-aware keys are the fallback. Repeat watches on the same title and date remain separate events. Superseded rows are retained during normal ingestion while insight queries use only active rows.

The normalization backfill also created non-authoritative `legacy_rating_snapshot` events from the one retained date on each legacy rating. `GET /api/spy-signals` therefore keeps ratings as its compatibility default. With `event_source=events`, it uses active WatchEvents only for profiles with a completed authoritative diary and falls back per profile to `ratings.watched_date` when no such diary exists.

### `watchlist_items`

Current per-profile watchlist membership with source position, optional added date, sync lineage, and removal timestamp.

### `movie_lists`

Imported list metadata: name, slug/source URL, description, ranked/public flags, published/updated dates, reported movie count, sync lineage, and removal timestamp.

### `movie_list_items`

Ordered canonical movie membership for each imported list. The `(movie_list_id, movie_id)` relationship is unique and preserves source position.

### `profile_favorite_movies`

The ordered favorite-film strip from a public profile page, linked to canonical movies and the authoritative profile sync.

### `movie_enrichments` and `movie_watch_providers`

Optional TMDB cache. `movie_enrichments` stores details such as overview, runtime, release date, language, genres, keywords, credits, countries, and expiry. `movie_watch_providers` stores region/provider/type rows separately so regional availability can expire independently.

No Letterboxd import depends on these tables or on a TMDB credential.

## Other Tables

### `system_metrics`

Stores cached system-wide analytics snapshots.

Current use:

- `metrics.dashboard_snapshot` holds the cached dashboard payload served by `GET /api/dashboard/analytics`

Other numeric columns remain useful as coarse counters, but the JSON snapshot is the primary production cache.

### `scraping_jobs`

Legacy table kept for schema compatibility. The current runtime no longer writes new server-side scrape jobs.

## Relationships

```text
profiles
  ├─ profile_syncs ── sync_datasets
  ├─ profile_films ── movies
  ├─ watch_events ── movies
  ├─ watchlist_items ── movies
  ├─ movie_lists ── movie_list_items ── movies
  ├─ profile_favorite_movies ── movies
  ├─ ratings (compatibility)
  ├─ reviews (compatibility)
  └─ scraping_jobs (legacy)

movies
  ├─ movie_enrichments
  └─ movie_watch_providers
```

## Data Flow

```text
Residential machine
  └─ backend/scraper_html.py
       └─ schema-v2 CSV bundle + manifest
            ├─ ZIP upload to /upload/
            └─ scripts/import_local_archive.py
                 ├─ services/profile_loader.py
                 └─ services/ingestion.py
                      └─ one atomic dual-write sync
                           ├─ normalized foundation
                           ├─ ratings / reviews compatibility tables
                           └─ dashboard snapshot refresh
```

## Data Integrity Notes

- Read traffic should hit cached dashboard analytics, not recompute global correlations per request.
- `profiles.avg_rating` and `profiles.total_reviews` are derived from imported `ratings` and `reviews`.
- `total_films` shown in the UI is computed from `ratings`, not stored directly on `profiles`.
- During normal authoritative ingestion, missing current state is soft-removed and missing diary occurrences are superseded where those tables support history. Reprocessing an identical source fingerprint can update its sync and event records; deleting a profile or explicitly clearing its imported data physically removes profile-owned history.
- Public HTML gaps such as tags, comments, or private account data are represented in coverage rather than fabricated.
- Migrations `20260728_0002` and `20260728_0003` add and backfill the normalized foundation without changing legacy cardinality at migration time.
