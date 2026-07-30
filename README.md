# Spyboxd

Spyboxd is a shared Letterboxd analytics app built around one production-safe ingestion model:

- scrape a complete public-profile snapshot on a residential machine
- upload the generated dataset to the API
- poll Letterboxd's public RSS feed conservatively for later diary/review activity
- serve cached analytics from PostgreSQL

The backend does not perform server-side full-HTML scraping from the VPS. RSS
is a separate additions-only observation layer over the last full snapshot.

## Stack

- Backend: FastAPI + SQLAlchemy + PostgreSQL
- Frontend: Next.js App Router + React Query + Clerk
- Local sync runner: Python scripts calling the HTML scraper from a residential machine

## Features

Existing routes remain available:

- Dashboard for group-level activity and aggregate statistics
- Spy Signals for same-day and configurable day-gap co-watch detection
- My Profiles for tracking an existing imported account or requesting a new residential sync
- Analysis for a single profile's ratings and activity

Additive insight routes:

- Compare: Pair Dossier, Taste DNA, and Signal Calendar for selected profiles
- Watch Together: ranked unseen-by-all or shared-watchlist candidates with group-fit explanations and country-aware provider availability
- Data coverage: per-surface freshness, row counts, and honest missing-data warnings
- Optional TMDB enrichment: genres, runtimes, credits, keywords, artwork, and regional watch providers

The timing views use individual `watch_events`, so repeat diary entries are preserved. Sequence is presented as a follow pattern, not proof of influence.

`GET /api/spy-signals` keeps `event_source=ratings` as its compatibility default. The Spy Signals frontend opts into `event_source=events`, which uses authoritative active diary events and falls back per profile to the legacy stored date only when no authoritative diary has ever been imported.

## Current Architecture

```text
Residential machine
  └─ scripts/local_full_sync.py
       └─ backend/scraper_html.py
            └─ ZIP upload to /upload/

API / PostgreSQL
  ├─ services/profile_loader.py
  ├─ services/ingestion.py
  ├─ services/rss_incremental.py + rss_worker.py
  ├─ sync lineage + canonical movies + per-profile film state + watch events
  └─ dashboard snapshot cache in system_metrics.metrics

Frontend
  ├─ Clerk-authenticated private analytics workspace
  ├─ per-user tracked-profile visibility and exact-username requests
  └─ explicit public share pages at /u/<username>
```

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 20.9+
- PostgreSQL 15+

### Local development

```bash
git clone <repository-url>
cd letterboxd-reviewer

python3 -m venv .venv
source .venv/bin/activate
pip install --require-hashes -r requirements-dev.lock

cp .env.example .env
cp frontend/.env.example frontend/.env.local

createdb spyboxd
PYTHONPATH=backend alembic upgrade head

cd frontend
npm ci
cd ..
```

Run the app:

```bash
source .venv/bin/activate
cd backend
uvicorn main:app --reload --port 8000
```

```bash
cd frontend
npm run dev
```

## Residential Sync Workflow

The HTML scraper is fail-closed: a schema-v2 bundle is written only when every requested public surface finishes and its manifest counts match the CSVs. Empty public watchlists and lists require an explicit Letterboxd empty state; favorites require either a recognized favorites container (including Letterboxd's empty owner container) or an explicit empty state. When a retained sync directory is reused, only scraper-owned CSVs for newly unavailable surfaces are removed, so stale private data cannot enter the next bundle and unrelated files remain untouched.

Set an ingestion token on the API:

```bash
INGESTION_API_TOKEN=replace-with-a-long-random-secret
```

Single profile sync:

```bash
python scripts/local_full_sync.py <username> \
  --api-base-url http://localhost:8000 \
  --upload-token "$INGESTION_API_TOKEN"
```

Repeatable batch sync:

1. Copy `scripts/sync-profiles.example.json` to `sync-profiles.json`.
2. Fill in usernames and API URL.
3. Export `INGESTION_API_TOKEN`.
4. Run:

```bash
python scripts/batch_full_sync.py --config sync-profiles.json
```

For a local correction run that should write directly to the configured database, first scrape to a retained directory and then import its validated bundle:

```bash
python backend/scraper_html.py <username> --output data/scraped/<username>
python scripts/import_local_archive.py <username> data/scraped/<username>
```

The importer accepts either a directory or ZIP, requires the full schema-v2 manifest, checks username and dataset counts, rejects unsafe ZIP members, and commits one profile sync atomically.

## Incremental RSS Activity

After a profile has one completed full sync, the RSS worker checks only the
official `https://letterboxd.com/<username>/rss/` feed. It upserts observed
public diary entries and reviews by their stable feed/viewing ID. It never
deletes data, replaces the full snapshot, or treats the feed's rolling window
as complete history.

Run one due-profile cycle:

```bash
PYTHONPATH=backend python -m rss_worker --once
```

Run the long-lived worker:

```bash
PYTHONPATH=backend python -m rss_worker
```

The default per-profile interval is ten minutes. The worker checks the due queue
once a minute, sends feed requests sequentially with a three-second pause, and
uses exponential failure backoff capped at 24 hours. These settings are
configurable through the `SPYBOXD_RSS_*` environment variables.
RSS cannot prove deletions or observe watchlist, favorites, private activity,
profile metadata, or complete list membership, so periodic/manual residential
full syncs remain the reconciliation source.

Public HTML does not expose every account-only Letterboxd field. Tags, comments, and private data remain marked unavailable instead of being inferred. A user's official Letterboxd export can still be supported as a separate source without weakening the public-snapshot contract.

## Optional TMDB Enrichment

Letterboxd ingestion works without TMDB. After setting `TMDB_API_TOKEN` (preferred) or `TMDB_API_KEY`, enrich imported canonical movies separately:

```bash
python scripts/enrich_tmdb.py --region DE
```

The enrichment command caches details and provider results, retries transient failures, and supports bounded or dry runs. Streaming availability is region-specific and is displayed as unavailable when the cache has no matching provider data.

## Runtime Model

- `POST /upload/` is the write path for profile data.
- Profiles and imported movie data are stored once globally; `user_tracked_profiles`
  controls which profiles each signed-in user can select or analyze.
- `GET /api/dashboard/analytics` uses the cached global snapshot for admins and
  computes an access-scoped response for ordinary users. The global snapshot is
  refreshed after uploads, profile deletes, and data clears.
- Health checks and `GET /public/profile/{username}` are public. Profile lists,
  analytics, activity, access requests, and management screens require sign-in.
- A signed-in user can track a completed profile immediately by exact username.
  Missing or incomplete profiles become requests for the next residential sync;
  no global profile directory is exposed to ordinary users.
- Admin mutations require a strict boolean admin session claim or a Clerk user ID
  in the server-side `CLERK_ADMIN_USER_IDS` allowlist.
- Production releases fail closed unless the frontend live keys and backend JWKS
  configuration identify the same Clerk production instance.
- The one-time development-to-live Clerk cutover additionally requires the
  production GitHub environment variable `PRODUCTION_CLERK_BRIDGE_EDGE` set to
  `<active-40-char-sha>:<target-40-char-sha>`. Only an exact development-key
  source manifest can use it; no incompatible automatic rollback is retained,
  failed candidate health stops the services, and the variable must be removed
  after the successful bridge. Live-to-live mismatches are never bypassed.
- The local sync runner can authenticate with `X-Upload-Token`.

## Main Endpoints

### Public reads

- `GET /health`
- `GET /ready`
- `GET /health/rss`
- `GET /public/profile/{username}`

### Signed-in workspace

- `GET /api/me`
- `GET /profiles/`
- `POST /profiles/requests`
- `GET /profiles/requests`
- `DELETE /profiles/{username}/tracking`
- `GET /profiles/{username}/analysis`
- `GET /api/dashboard/analytics`
- `GET /api/spy-signals?event_source=ratings|events`
- `GET /api/data-coverage`
- `GET /api/pair-dossier`
- `GET /api/taste-dna`
- `GET /api/signal-calendar`
- `GET /api/watch-together`
- `GET /api/watch-provider-regions`

### Admin / ingestion

- `GET /admin/profile-requests`
- `PUT /admin/profile-requests/{request_id}`
- `POST /profiles/create`
- `PUT /profiles/{username}`
- `DELETE /profiles/{username}`
- `DELETE /profiles/{username}/data`
- `POST /upload/`

## Docker Compose

Local compose runs:

- `postgres`
- `api`
- `rss-poller`
- `frontend`

Start it with:

```bash
docker compose up --build
```

## Repo Layout

```text
backend/
  main.py
  auth.py
  rss_worker.py
  database/
  services/
  scraper_html.py

frontend/
  src/app/
  src/components/
  src/services/
  src/views/

scripts/
  local_full_sync.py
  batch_full_sync.py
  import_local_archive.py
  enrich_tmdb.py
  sync-profiles.example.json
```

See [`DATABASE.md`](DATABASE.md) for the normalized schema, compatibility tables, and data-integrity behavior.

## Notes

- `backend/scraper_html.py` remains because it powers the residential sync runner.
- The normalized data foundation is additive. Legacy `ratings`, `reviews`, and old API contracts remain available while new insights read canonical movies, profile-film state, and active watch events.
- Dashboard group metrics are precomputed into a cached snapshot for production reads.
- Legacy server-side scraping, Celery workers, Redis, SSE progress streams, and comparative scrape tooling have been removed from the active app path.
