# Database Schema

PostgreSQL schema for the current Spyboxd runtime.

The app is centered on imported full-profile datasets, not server-side scraping jobs.

## Compatibility Tables

### `profiles`

One canonical row per imported Letterboxd profile. Profile data is shared and
deduplicated globally; user visibility is represented separately rather than by
duplicating imports.

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
- `letterboxd_person_id` — Letterboxd's stable numeric member id; survives
  username renames, so an upload under an unknown username with a known person
  id renames the existing profile in place instead of duplicating it
- `member_badge` — Patron/Pro/Crew when observed
- `reported_watchlist_count` — profile-sidebar count, observable even when the
  watchlist itself is private

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

Authoritative diary imports store one row per occurrence. `logged_date`
preserves the official-export log date next to `watched_date`; public HTML
only exposes the watch date, so scraper syncs never overwrite a known log
date with their own unknown. Stable Letterboxd viewing IDs are preferred for `event_key`; deterministic occurrence-aware keys are the fallback. Repeat watches on the same title and date remain separate events. Superseded rows are retained during normal ingestion while insight queries use only active rows.

The normalization backfill also created non-authoritative `legacy_rating_snapshot` events from the one retained date on each legacy rating. `GET /api/spy-signals` therefore keeps ratings as its compatibility default. With `event_source=events`, it uses active WatchEvents only for profiles with a completed authoritative diary and falls back per profile to `ratings.watched_date` when no such diary exists.

### `watchlist_items`

Current per-profile watchlist membership with source position, optional added date, sync lineage, and removal timestamp.

### `movie_lists`

Imported list metadata: name, slug/source URL, description, ranked/public flags, published/updated dates, reported movie count, sync lineage, and removal timestamp.

### `movie_list_items`

Ordered canonical movie membership for each imported list. The `(movie_list_id, movie_id)` relationship is unique and preserves source position.

### `profile_favorite_movies`

The ordered favorite-film strip from a public profile page, linked to canonical movies and the authoritative profile sync.

### `profile_follow_edges`

One row per observed social edge on a tracked profile's following/followers
pages. `direction` distinguishes the two surfaces; each row is an observation
owned by the sync of the profile whose page produced it, so a mutual follow
between two tracked profiles legitimately appears as multiple rows and is
deduplicated at query time.

Counterparts are username-keyed (`counterpart_username_normalized` is the
casefolded identity inside the `(profile_id, direction, counterpart)` unique
constraint) because most followed accounts are never imported;
`counterpart_profile_id` is a nullable reference attached opportunistically
when a canonical profile exists. An unfollow observed by an authoritative
sync sets `removed_at`; a re-follow resurrects the row. The first social sync
for a profile is a baseline and emits no change events; later authoritative
diffs emit `follow` entity-type rows in `profile_data_changes`.

### `member_content_likes` and `member_comments`

Export-only member activity. Official account exports enumerate likes the
member placed on other members' reviews and lists (`likes/reviews.csv`,
`likes/lists.csv`: like date + boxd.it URL) and the member's own comments
(`comments.csv`: date, target URL, comment HTML). Rows are URL-keyed (comments
by a URL/date/text digest) with the usual lineage and soft-removal semantics;
scraper bundles never carry these files, so they always preserve prior state.

### `movie_enrichments` and `movie_watch_providers`

Optional TMDB cache. `movie_enrichments` stores details such as overview, runtime, release date, language, genres, keywords, credits, countries, and expiry. `movie_watch_providers` stores region/provider/type rows separately so regional availability can expire independently.

No Letterboxd import depends on these tables or on a TMDB credential.

### `app_users`, `user_tracked_profiles`, and `profile_access_requests`

`app_users` maps a verified Clerk user ID to the local access model and supports
local account disablement. New accounts also store a canonical, case-insensitively
unique `letterboxd_username`; `primary_profile_required` distinguishes mandatory
profile onboarding from grandfathered and administrative accounts.
`user_tracked_profiles` is the many-to-many access mapping between an app user
and a completed canonical profile. It does not own or duplicate the profile's
Letterboxd data.

`profile_access_requests` stores an exact Letterboxd username requested by one
user. A completed profile already in the database is attached immediately;
otherwise the request remains pending or approved until a residential full sync
successfully imports that username. Fulfillment then creates the access mapping.
Untracking removes only the mapping, while destructive profile maintenance
preserves approved request intent so a later re-import can restore access.

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
  ├─ profile_follow_edges (username-keyed counterpart, optional profile reference)
  ├─ ratings (compatibility)
  ├─ reviews (compatibility)
  └─ scraping_jobs (legacy)

app_users
  ├─ user_tracked_profiles ── profiles
  └─ profile_access_requests ── profiles (optional fulfilled reference)

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

- Admin dashboard reads use the cached global analytics snapshot. Ordinary-user
  dashboard reads are recomputed only over that user's tracked profiles so the
  global cache cannot leak hidden-profile aggregates.
- `profiles.avg_rating` and `profiles.total_reviews` are derived from imported `ratings` and `reviews`.
- `total_films` shown in the UI is computed from `ratings`, not stored directly on `profiles`.
- During normal authoritative ingestion, missing current state is soft-removed and missing diary occurrences are superseded where those tables support history. Reprocessing an identical source fingerprint can update its sync and event records; deleting a profile or explicitly clearing its imported data physically removes profile-owned history.
- Public HTML gaps such as tags, comments, or private account data are represented in coverage rather than fabricated.
- Migrations `20260728_0002` and `20260728_0003` add and backfill the normalized foundation without changing legacy cardinality at migration time.
- Migration `20260730_0008` adds the per-user access model and a case-insensitive
  unique profile-username index. It aborts before changing the schema if legacy
  usernames collide after case normalization.
- Migration `20260730_0009` adds each account's canonical Letterboxd username,
  case-insensitive uniqueness, and primary-profile onboarding state while
  grandfathering pre-existing accounts.
