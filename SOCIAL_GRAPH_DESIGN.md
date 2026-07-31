# Social Graph Feature Spec — Letterboxd Following/Followers for Tracked Profiles

Repo: `/Users/yash/code/letterboxd-reviewer` (Spyboxd). Status: design only, no code changes made. All conventions below were verified against the current codebase (`backend/database/models.py`, `backend/services/ingestion.py`, `backend/services/profile_changes.py`, `backend/scraper_html.py`, `backend/services/profile_loader.py`, `backend/services/profile_access.py`, `alembic/versions/*`, `backend/tests/test_additive_migrations.py`).

---

## 1. Schema

### 1.1 One table, direction column (recommended)

Create a single table `profile_follow_edges` rather than separate `profile_following` / `profile_followers` tables.

Rationale:
- Both surfaces have an identical shape: "tracked profile X has a social relationship with Letterboxd user Y, observed on one of X's people pages." Two tables would duplicate the counterpart-identity columns, the lineage columns, the soft-removal machinery, the ingestion upsert, and the change-event plumbing.
- The house already uses discriminator columns for same-shaped variants (`movie_watch_providers.provider_type` with a CHECK constraint; `profile_source_activities.activity_type` / `date_semantics`).
- Mutual-follow and suggestion queries want both directions in one scan; a `direction` predicate on an indexed column is cheaper and simpler than a UNION across two tables.

Semantics: each row is an **observation from the scanned profile's own pages**, not a canonical graph edge. `direction = 'following'` means "profile follows counterpart" (from `/{username}/following/`); `direction = 'follower'` means "counterpart follows profile" (from `/{username}/followers/`). When two tracked profiles follow each other, the same underlying relationship legitimately appears as up to four rows (A-following-B, B-follower-A, B-following-A, A-follower-B). This is intentional: each row's lifecycle (authoritative removal, lineage) is owned by the sync of the profile whose page produced it, exactly like every other per-profile dataset in this codebase. Deduplication happens at query time.

### 1.2 Counterpart representation: username-keyed with an opportunistic nullable FK (recommended)

Most followed/follower accounts will never be imported profiles. Do **not** create stub `profiles` rows for them:
- `profiles` rows are heavyweight canonical datasets with `scraping_status`, sync history, catalog visibility, and access-request fulfillment semantics (`fulfill_pending_requests` keys off `profiles.username`). Thousands of stub rows would pollute the admin library and complicate every `scraping_status == 'completed'` filter.
- The house precedent is exactly this problem already solved: `profile_access_requests` stores `requested_username` + `normalized_username` with a **nullable** `fulfilled_profile_id` FK that is attached when a canonical profile exists.

So: store `counterpart_username` (display case) + `counterpart_username_normalized` (casefolded, the identity key), plus a nullable `counterpart_profile_id` FK (`ondelete="SET NULL"`) resolved opportunistically — at ingestion time via `lower(profiles.username)` match, and backfilled when a new profile later completes (hook alongside `fulfill_pending_requests` in the upload/import completion path). Also snapshot lightweight recognition fields (`counterpart_display_name`, `counterpart_avatar_url`), mirroring what `list_profile_catalog` calls "recognition fields".

### 1.3 Model (house style)

```python
class ProfileFollowEdge(Base):
    """One observed social edge from a tracked profile's following/followers pages."""

    __tablename__ = "profile_follow_edges"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    direction = Column(String(10), nullable=False)  # 'following' | 'follower'
    counterpart_username = Column(String(50), nullable=False)
    counterpart_username_normalized = Column(String(50), nullable=False)
    counterpart_display_name = Column(String(200), nullable=True)
    counterpart_avatar_url = Column(String(500), nullable=True)
    counterpart_profile_url = Column(String(500), nullable=True)
    counterpart_profile_id = Column(
        Integer, ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )
    position = Column(Integer, nullable=True)  # source page order (approx. recency); semantics not guaranteed
    first_seen_profile_sync_id = Column(
        BigInteger, ForeignKey("profile_syncs.id", ondelete="SET NULL"), nullable=True
    )
    last_seen_profile_sync_id = Column(
        BigInteger, ForeignKey("profile_syncs.id", ondelete="SET NULL"), nullable=True
    )
    removed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    profile = relationship("Profile", back_populates="follow_edges", foreign_keys=[profile_id])
    counterpart_profile = relationship("Profile", foreign_keys=[counterpart_profile_id])

    __table_args__ = (
        UniqueConstraint(
            "profile_id", "direction", "counterpart_username_normalized",
            name="unique_profile_follow_edge",
        ),
        CheckConstraint("direction IN ('following', 'follower')", name="ck_profile_follow_edges_direction"),
        CheckConstraint("position IS NULL OR position > 0", name="ck_profile_follow_edges_position_positive"),
        CheckConstraint(
            "counterpart_username_normalized = lower(counterpart_username_normalized)",
            name="ck_profile_follow_edges_normalized_lower",
        ),
        Index("ix_profile_follow_edges_profile_removed", "profile_id", "removed_at"),
        Index(  # reverse lookups: "who among tracked profiles follows user X"
            "ix_profile_follow_edges_counterpart_active",
            "counterpart_username_normalized", "direction", "profile_id",
            postgresql_where=sql_text("removed_at IS NULL"),
        ),
        Index("ix_profile_follow_edges_counterpart_profile", "counterpart_profile_id"),
    )
```

Also add `follow_edges` to `Profile.__mapper__` relationships (`cascade="all, delete-orphan"`, `foreign_keys="ProfileFollowEdge.profile_id"`).

Key semantics:
- **Uniqueness** is global (not partial on active rows), matching `unique_profile_watchlist_movie`: an unfollow soft-removes the row (`removed_at = now`), a re-follow resurrects it (`removed_at = None`, `last_seen_profile_sync_id = sync.id`), and the change feed correctly emits a fresh added event because `capture_profile_state` filters `removed_at IS NULL`.
- **Lineage** matches house style exactly: `first_seen_profile_sync_id` set once at insert, `last_seen_profile_sync_id` updated every sync that observes the row, both `BigInteger` FK to `profile_syncs.id` with `ondelete="SET NULL"`.
- **Unfollow semantics**: when the corresponding dataset is authoritative in a sync (its CSV was present in the bundle), any existing active edge for that `(profile_id, direction)` not present in the snapshot gets `removed_at = now` — identical to `_upsert_watchlist`. When the dataset is unavailable (private/forbidden/capped), prior state is preserved untouched, per the "prior imported state was preserved" convention.
- `profiles.following_count` / `followers_count` already exist (with non-negative CHECKs) and continue to be the header-reported totals; edges are the enumerated membership.

---

## 2. Scraper (`backend/scraper_html.py`)

### 2.1 New methods: `scrape_following()` / `scrape_followers()`

Both share one implementation (`_scrape_people(dataset: str)`) parameterized by dataset name and start URL (`self.urls['following']` / `self.urls['followers']` — both URLs already exist in `self.urls`). Storage target: the existing `self.social_data['following']` / `self.social_data['followers']` lists.

Per-page loop, following every house validation convention:

1. `response = self.fetch_with_retry(page_url, allow_private_forbidden=True)`.
2. If `self._is_private_forbidden_response(response)`: clear the partial list, `self._mark_unavailable(dataset, 'forbidden/private')`, print the "preserving prior imported state" warning, and return `[]` — mirroring `scrape_watchlist`. (A fully private profile 403s on people pages; the profile header itself may still have rendered counts.)
3. `response = self._require_response(response, dataset, page_url)`.
4. Parse person rows. Letterboxd renders people pages as a person table; use a grouped selector with fallbacks in the house style, e.g. `main.select('table.person-table td.table-person, .person-summary, li.listitem .person-summary')` — **selectors must be verified against live HTML during implementation**, same as the LazyPoster work was.
5. Empty state: if page 1 yields no person rows, accept only when `self._declares_empty(soup, dataset)`; otherwise `raise ScrapeValidationError(f"{dataset} page {page_num} returned HTML but no recognized person rows")`. Extend the `_declares_empty` phrases dict:
   - `'following': ("isn't following anyone", "is not following anyone", "not following any members", "isn\u2019t following anyone")`
   - `'followers': ("no followers", "doesn't have any followers", "has no followers", "doesn\u2019t have any followers")`
   (Exact phrases to be confirmed against live pages; the mechanism is the point.)
6. Per row, extract: username (from the `/username/` href), display name (`a.name` text), avatar URL (`img src`/`data-src`). A recognized row lacking username or URL raises `ScrapeValidationError` (mirrors "Recognized film poster lacked title or URL"). Deduplicate by casefolded username across pages; assign `position` as running source order.
7. `page_url = self._next_page_url(soup, page_url)`; `time.sleep(1)` between pages ("Be respectful" convention).
8. On completion: `self._finish_dataset(dataset)`.

### 2.2 Page-count expectations from the profile header

`scrape_profile_info()` already extracts `following_count` and `followers_count` from the header stat links. Use them two ways:

- **Pre-flight estimate and cap**: people pages hold 25 entries per page, so expected pages = `ceil(count / 25)`. If `count > SPYBOXD_MAX_FOLLOW_EDGES_PER_SURFACE` (env, default e.g. 5,000 ≈ 200 pages), do not partially scrape: `self._mark_unavailable(dataset, f"count {count} exceeds configured cap")`. Fail-closed-or-skip beats silently partial data — this repo never records an unproven-complete dataset.
- **Post-scrape validation**: after pagination completes, compare `len(entries)` with the header count, mirroring the list-membership check ("reported N films but only M were captured"). Because follower counts can drift between the header fetch and the last page, allow a small tolerance (recommend: exact match OR within `max(2, 1%)`; outside tolerance, raise `ScrapeValidationError`). Document the tolerance in the manifest metadata for the dataset.

### 2.3 CSV contract

Two new scraper-owned files in the bundle:

`following.csv` — one row per account the profile follows, in source order:

| Column | Notes |
|---|---|
| `Position` | 1-based source order across pages |
| `Username` | Letterboxd username as displayed in URL |
| `Display_Name` | may be empty |
| `Avatar_URL` | may be empty |
| `Profile_URL` | absolute `https://letterboxd.com/{username}/` |

`followers.csv` — identical columns, one row per follower.

Writers `_save_following()` / `_save_followers()` follow the existing pattern: gated on `dataset in self.completed_datasets`, written via `self._write_csv`. Add both datasets to `_remove_stale_unavailable_files`'s `dataset_files` map (`'following': ('following.csv',)`, `'followers': ('followers.csv',)`) so a previously-public surface that went private has its stale CSV removed.

Manifest: add `'following', 'followers'` to `self.requested_datasets` in `scrape_all()`, and to the `counts` dict in `save_all_data()`. Bump `schema_version` to **3** (see §3.1 for why).

Call order in `scrape_all()`: after `scrape_profile_info()` (so header counts exist) — recommend immediately after profile info, before the heavy film surfaces, since people pages are cheap and fail fast.

---

## 3. Loader / contracts / ingestion

### 3.1 `backend/services/profile_loader.py`

- `LoadedProfileData` gains `following: pd.DataFrame` and `followers: pd.DataFrame`; `load_profile_data` reads `following.csv` / `followers.csv` via `read_source` when present (they land in `source_files` with sha256 + row_count automatically).
- `validate_import_bundle`: **do not** add the new datasets to `FULL_SCRAPE_REQUIRED_DATASETS` unconditionally — that would retroactively invalidate every existing schema-v2 bundle ("Full scrape manifest did not request datasets"). Instead gate on manifest version: for `schema_version >= 3`, require `following`/`followers` to be requested and accounted (completed or unavailable), extend the observed-counts check (`"following": len(loaded.following)` etc.), and extend the `dataset_files` map (`"following": "following.csv"`, `"followers": "followers.csv"`). v2 bundles remain valid without them. Neither dataset joins the `mandatory` set (they can legitimately be unavailable for private profiles).
- Official Letterboxd account exports do **not** include a social graph, so `letterboxd_export` bundles simply never carry these files; nothing to do there.

### 3.2 `backend/services/ingestion.py`

New `_upsert_follow_edges(...)` modeled directly on `_upsert_watchlist`:

```python
def _upsert_follow_edges(*, analyzer_profile, profile_id, sync, direction, frame, authoritative, db) -> int:
    existing = {edge.counterpart_username_normalized: edge
                for edge in db.query(ProfileFollowEdge).filter(
                    ProfileFollowEdge.profile_id == profile_id,
                    ProfileFollowEdge.direction == direction).all()}
    seen = set()
    for source_position, row in enumerate(frame_records(frame), start=1):
        username = clean_text(first_value(row, ("Username",)), max_length=50)
        if not username:
            continue
        normalized = username.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        edge = existing.get(normalized)
        if edge is None:
            edge = ProfileFollowEdge(profile_id=profile_id, direction=direction,
                                     counterpart_username_normalized=normalized,
                                     first_seen_profile_sync_id=sync.id)
            db.add(edge)
        edge.counterpart_username = username
        edge.counterpart_display_name = clean_text(first_value(row, ("Display_Name", "Display Name")), max_length=200)
        edge.counterpart_avatar_url = clean_text(first_value(row, ("Avatar_URL", "Avatar URL")), max_length=500)
        edge.counterpart_profile_url = normalize_letterboxd_url(first_value(row, ("Profile_URL", "Profile URL")))
        edge.position = parse_integer(first_value(row, ("Position",)), minimum=1) or source_position
        edge.counterpart_profile_id = counterpart_ids.get(normalized)  # bulk lower(username) lookup
        edge.last_seen_profile_sync_id = sync.id
        edge.removed_at = None
    if authoritative:
        now = _utcnow()
        for normalized, edge in existing.items():
            if normalized not in seen and edge.removed_at is None:
                edge.removed_at = now
    db.flush()
    return len(seen)
```

Wiring inside `unified_data_loader`:
- `following_authoritative = _source_present(analyzer_profile, "following.csv")`; likewise `followers_authoritative` — same rule as every other surface: file present in bundle ⇒ authoritative snapshot; file absent (including `_mark_unavailable`, whose CSVs are deleted) ⇒ non-authoritative, prior state preserved.
- Add `"following"` / `"followers"` to the `authoritative` dict, `imported_counts`, `_dataset_file_names` mapping (`"following": ["following.csv"]`, `"followers": ["followers.csv"]`), and the dataset-name tuple in `_upsert_sync_datasets` — this produces the required **`sync_datasets` rows** with `source_filename`, `source_sha256`, `source_row_count`, `imported_row_count`, `is_authoritative`, and `unavailable_reason` in `metadata_payload`, for free.
- `_build_coverage`: add `following_available` / `followers_available` flags and limitation strings ("Social graph unavailable (forbidden/private); prior imported state was preserved." / "Following/follower data was not included in this sync.").
- Counterpart backfill hook: after a sync completes for a *new* profile (the same code path that calls `fulfill_pending_requests`), run one UPDATE attaching `counterpart_profile_id` on active edges whose `counterpart_username_normalized = lower(new_profile.username)`.

### 3.3 Change events (`backend/services/profile_changes.py`)

- `capture_profile_state` gains two surfaces, keyed by counterpart:
  - `"following"`: `{f"user:{normalized}": {"username", "display_name", "profile_url", "counterpart_profile_id"}}` over active `direction='following'` edges.
  - `"followers"`: same over `direction='follower'` edges.
- `record_profile_changes` gains two `membership_changes` calls gated on `authoritative.get("following")` / `authoritative.get("followers")`:
  - `follow_added` / `follow_removed` (entity_type `'follow'`, dataset `'following'`) — the profile followed/unfollowed someone.
  - `follower_gained` / `follower_lost` (entity_type `'follow'`, dataset `'followers'`).
- `movie_id` / `movie_list_id` stay NULL; the payloads carry the counterpart identity. `change_key = f"{change_type}|{entity_key}"` stays well under 600 chars.
- **Constraint change required**: `ck_profile_data_changes_entity_type` currently enumerates `('film','watchlist','favorite','diary','review','list','list_item')`. The migration must drop and recreate it with `'follow'` appended (safe: new list is a superset, existing rows all satisfy it).
- The existing baseline rule applies untouched: a first import (`has_baseline == False`) records no events, so onboarding a profile with 3,000 followers does not flood the feed. `GET /api/recent-changes` (`backend/api/routes/activity.py`) serves the new change types with zero route changes.

---

## 4. Migration

### 4.1 Alembic revision (additive, house pattern)

`alembic/versions/20260731_0010_add_profile_follow_edges.py`:
- `revision = "20260731_0010"`, `down_revision = "20260730_0009"`.
- `op.create_table("profile_follow_edges", ...)` using `sa.BigInteger(), sa.Identity()` PK (matching `20260729_0004`), all columns/FKs/CHECKs/unique constraint from §1.3, then `op.create_index` for the three indexes (the partial one via `postgresql_where=sa.text("removed_at IS NULL")`).
- Widen the change-feed constraint in the same revision (or defer to the phase-3 revision if phase 1 ships standalone — either is acceptable; one revision is simpler):
  ```python
  op.drop_constraint("ck_profile_data_changes_entity_type", "profile_data_changes", type_="check")
  op.create_check_constraint(
      "ck_profile_data_changes_entity_type", "profile_data_changes",
      "entity_type IN ('film','watchlist','favorite','diary','review','list','list_item','follow')",
  )
  ```
- `downgrade()` reverses: restore the original CHECK, drop indexes, drop table.
- The table is empty at migration time; existing profile snapshots become the baseline on their next v3 sync — same statement the `20260729_0004` docstring makes.
- Also add `"profile_follow_edges"` to `TABLE_COPY_ORDER` in `backend/database/migrate.py` (after `"profile_favorite_movies"`, before `"profile_source_activities"` — anywhere after `profiles`/`profile_syncs` works) so SQLite-import tooling and truncation ordering stay correct.

### 4.2 Tests mirroring `backend/tests/test_additive_migrations.py`

- Bump `HEAD_REVISION = "20260731_0010"`; extend `test_revision_chain_has_one_expected_head` with the new link (`down_revision == "20260730_0009"`).
- `test_model_metadata_exposes_the_foundation_contract`: add `"profile_follow_edges"` to `expected_tables`; add expected columns (`profile_id`, `direction`, `counterpart_username_normalized`, `counterpart_profile_id`, `first_seen_profile_sync_id`, `last_seen_profile_sync_id`, `removed_at`); add `{"profile_follow_edges": {"unique_profile_follow_edge"}}` to the unique-constraint contract; assert the widened entity-type CHECK in `Base.metadata` includes `'follow'`; optionally assert the migration source contains the recreated constraint string (matches the source-grep style used for `0008`/`0009`).
- `AdditiveMigrationPostgresTests` (isolated loopback schema, `SPYBOXD_TEST_DATABASE_URL`-gated): upgrade chain now ends at the new head; add assertions that (a) legacy application reads snapshotted at `LEGACY_REVISION` are unchanged, (b) inserting a duplicate `(profile_id, direction, counterpart_username_normalized)` raises, (c) a `profile_data_changes` row with `entity_type='follow'` inserts cleanly post-migration and fails pre-migration.
- Ingestion behavior tests live beside `test_profile_changes.py` / `test_import_contracts.py`: authoritative removal sets `removed_at`; unavailable dataset preserves prior edges; re-follow resurrects and re-emits `follow_added`; first import emits nothing.

---

## 5. API

New module `backend/api/routes/follow_graph.py`, `router = APIRouter(prefix="/api", tags=["follow graph"])`, registered in `backend/main.py` next to the existing three routers. All scoping reuses `backend/services/profile_access.py` primitives — no new auth logic.

### 5.1 Per-profile graph

```
GET /api/profiles/{username}/follow-graph
    ?direction=following|followers|both (default both)
    &include_removed=false
    &limit=100&offset=0
```
- Access: `require_profile_access(db, user, username)` — admins see any profile, ordinary users only tracked ones (403 with the standard "Track this profile" detail otherwise).
- Response per edge: `counterpart_username`, `counterpart_display_name`, `counterpart_avatar_url`, `counterpart_profile_url`, `position`, `is_imported_profile` (counterpart_profile_id attached and that profile `is_active` + `completed`), `removed_at`, plus `following_count`/`followers_count` header totals and per-dataset coverage (from the latest sync's `sync_datasets` rows) so the UI can say "followers unavailable: private".

### 5.2 Mutual follows across tracked profiles

```
GET /api/follow-graph/mutuals?profiles=a&profiles=b...
```
- Access: `authorize_profile_usernames(db, user, profiles)` — omitted selection expands to the caller's completed tracked set; explicit untracked names 403; admin may name any profiles (admin with no selection uses `accessible_profiles`).
- For each ordered pair (A, B) in the selection: `a_follows_b` is true iff an active edge `(A, 'following', lower(B))` exists, with fallback corroboration from `(B, 'follower', lower(A))` when A's following surface is unavailable; symmetric for `b_follows_a`; `mutual = both`. Response is a pair matrix plus per-profile "follows N / followed by M of this group" rollups. This slots naturally beside `pair_dossier` in the insights family.

### 5.3 "Who to track next" suggestions

```
GET /api/follow-graph/suggestions?limit=20&min_overlap=2
```
- Scope: ordinary users — aggregated only over their own tracked profiles (per-user tracking cap of 25 keeps this tiny); admins in global scope — over all active profiles.
- Core ranking query (uses `ix_profile_follow_edges_counterpart_active`):

```sql
SELECT counterpart_username_normalized,
       max(counterpart_username)        AS username,
       count(DISTINCT profile_id)       AS followed_by_count,
       bool_or(counterpart_profile_id IS NOT NULL) AS already_imported
FROM profile_follow_edges
WHERE direction = 'following' AND removed_at IS NULL
  AND profile_id = ANY(:scoped_profile_ids)
GROUP BY counterpart_username_normalized
HAVING count(DISTINCT profile_id) >= :min_overlap
ORDER BY followed_by_count DESC, username ASC
LIMIT :limit
```
- Exclude counterparts already in the caller's tracked set; annotate each suggestion with `followed_by` (the tracked usernames producing the overlap), `follows_back_count` (active `direction='follower'` edges naming this counterpart — a reciprocity tiebreaker), `already_imported` (one-click `track_profile_by_id`) versus not-imported (routes to the existing `track_or_request_profile` request flow). Ordinary users see only usernames drawn from profiles they already track — no cross-user data leakage, consistent with the "global cache cannot leak hidden-profile aggregates" integrity note in `DATABASE.md`.
- Add coverage to `backend/tests/test_route_access_matrix.py` for all three endpoints (admin / tracked / untracked / anonymous).

---

## 6. Frontend touchpoints (later phase)

All pages already consume scope via `frontend/src/hooks/useAdminScope.tsx` (tracked vs global admin view) and `frontend/src/hooks/useScopedProfiles.ts`; the new endpoints are scoped server-side, so the frontend only chooses which usernames to ask about.

- **Profiles** (`frontend/src/app/(app)/profiles/page.tsx`): per-profile following/followers counts already exist on `Profile.to_dict()`; add a follow-graph drawer (per-profile endpoint) and a "Who to track next" panel backed by `/api/follow-graph/suggestions`, with the existing track/request affordances (`profileApi` in `frontend/src/services/api.ts` gains three functions).
- **Compare** (`frontend/src/app/(app)/compare/page.tsx`): mutual/one-way follow badge for the selected pair/group from `/api/follow-graph/mutuals`; natural companion to the pair dossier.
- **Spy Signals** (`frontend/src/app/(app)/spy-signals/page.tsx`): follow/unfollow/follower-gained/lost events arrive automatically through the existing `/api/recent-changes` feed once change types exist; the feed renderer needs cases for the four new `change_type` values (counterpart avatar + username instead of a poster).

---

## 7. Risks and constraints

- **Page volume**: people pages hold 25 entries. A profile following 2,000 accounts is 80 pages; both surfaces for a 10k-follower account is ~800 requests. With the mandatory 1s inter-page sleep that is ~13+ minutes added to a full sync for one popular profile. Mitigations: the header-count pre-flight cap (§2.2, `_mark_unavailable` on exceed rather than partial capture), scraping people pages only (a) on first import and (b) on a configurable cadence (e.g. every Nth full sync or a `--skip-social` flag on `scripts/local_full_sync.py` / `scripts/batch_full_sync.py`), since a v3 bundle without the CSVs is simply non-authoritative for those surfaces and preserves prior edges.
- **Rate limiting / politeness**: `fetch_with_retry` already handles 429 with long exponential backoff; keep the 1s sleep, and consider raising it to 2s for people pages since they contribute no film data urgency. All scraping remains on the residential machine — the server runtime never scrapes (unchanged architecture).
- **Count drift**: follower counts move while paginating; the tolerance rule in §2.2 prevents both false failures and silently-partial data. Record observed-vs-header counts in the dataset `metadata_payload`.
- **Privacy / ethics**: this is public-page data, but a *diffed social graph over time* (who unfollowed whom, when) is materially more sensitive than film lists — it is exactly the "spy" surface. Constraints: never scrape past a 403 (`_is_private_forbidden_response` handling is mandatory, not best-effort); store only recognition fields for counterparts (username/display/avatar), never enumerate or crawl counterpart profiles themselves; unfollow events are visible only to users who track the observed profile (enforced by existing `recent-changes` scoping); suggestions never reveal which *other app users* track anyone. Letterboxd ToS discourages scraping — the existing residential, throttled, fail-closed posture applies; the social surfaces roughly double request volume, which strengthens the cadence-throttling mitigation above.
- **Why RSS cannot help**: `profile_feed_states` polls `letterboxd.com/{user}/rss/`, which contains only diary/review/list activity items — Letterboxd publishes no feed of follow/unfollow events and no per-user social-graph feed at all. Follow churn is therefore invisible to the conservative RSS poller by construction; the only observation channel is re-paginating the HTML people pages, which is why this feature rides the full-sync bundle path and why edge freshness is bounded by full-sync cadence, not the RSS window. (Consistent with the repo's rule that RSS is never authoritative and can never remove data.)

---

## 8. Phased implementation plan

| Phase | Scope | Effort |
|---|---|---|
| 1 | Schema + migration + model + migration tests + docs | ~0.5–1 day |
| 2 | Scraper surfaces + CSV + manifest v3 + loader/validation (incl. live-HTML selector verification) | ~1.5–2 days |
| 3 | Ingestion (`_upsert_follow_edges`, sync_datasets, coverage) + change events + counterpart backfill + tests | ~1.5–2 days |
| 4 | API endpoints + access-matrix tests | ~1–1.5 days |
| 5 | Frontend (Profiles drawer + suggestions panel, Compare badge, Spy Signals renderers) | ~2–3 days |

Phases 1–3 are independently shippable and inert (empty table; old bundles unaffected; v3 bundles only appear once the residential scraper updates). Phase 4 requires 3; phase 5 requires 4.

### Phase 1 file-by-file change list

1. `backend/database/models.py` — add `ProfileFollowEdge` model (§1.3) and the `follow_edges` relationship on `Profile` (with explicit `foreign_keys` since the table has two FKs to `profiles`).
2. `alembic/versions/20260731_0010_add_profile_follow_edges.py` — new revision (§4.1): create table + indexes, widen `ck_profile_data_changes_entity_type` to include `'follow'`, full `downgrade()`.
3. `backend/database/migrate.py` — add `"profile_follow_edges"` to `TABLE_COPY_ORDER`.
4. `backend/tests/test_additive_migrations.py` — `HEAD_REVISION = "20260731_0010"`; extend revision-chain assertions, `expected_tables`, `expected_columns`, `expected_unique_constraints`; Postgres-schema assertions for the new table and widened CHECK (§4.2).
5. `DATABASE.md` — new "### `profile_follow_edges`" subsection under the Normalized Data Foundation, an entry in the Relationships tree (`profiles ├─ profile_follow_edges`), and a Data Integrity note that edges are per-profile observations with soft removal and that the first social sync is a baseline emitting no change events.

Later-phase file map (for reference): phase 2 → `backend/scraper_html.py`, `backend/services/profile_loader.py`; phase 3 → `backend/services/ingestion.py`, `backend/services/profile_changes.py`, upload-completion hook (same module that calls `fulfill_pending_requests`), `backend/tests/test_profile_changes.py` + a new `backend/tests/test_follow_edges_ingestion.py`; phase 4 → `backend/api/routes/follow_graph.py`, `backend/main.py`, `backend/tests/test_route_access_matrix.py`; phase 5 → `frontend/src/services/api.ts`, `frontend/src/app/(app)/{profiles,compare,spy-signals}/page.tsx`.