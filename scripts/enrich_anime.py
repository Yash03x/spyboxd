#!/usr/bin/env python3
"""Resume a bounded public-metadata backfill for privately imported anime IDs."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from database.connection import engine, SessionLocal
from database.models import AnimeMetadataCache, PersonalAnimeImport
from services.anime_metadata import CACHE_DAYS, AniListClient, MetadataError, aware
from sqlalchemy import text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=2000)
    parser.add_argument('--force', action='store_true', help='Recheck cached metadata; never alter personal imports.')
    args = parser.parse_args()
    if not 1 <= args.limit <= 20000:
        parser.error('limit must be between 1 and 20000')
    with engine.connect() as lock:
        if not lock.execute(text('SELECT pg_try_advisory_lock(937552221)')).scalar():
            print('An anime metadata backfill is already running.')
            return 1
        try:
            with SessionLocal() as db:
                latest = {}
                for snapshot in db.query(PersonalAnimeImport).order_by(PersonalAnimeImport.id):
                    latest[snapshot.user_id] = snapshot
                ids = sorted({row['mal_id'] for snapshot in latest.values() for row in snapshot.payload['entries']})
                cached = {row.mal_id: row for row in db.query(AnimeMetadataCache).all()}
                now = datetime.now(timezone.utc)
                due = [mal_id for mal_id in ids if args.force or mal_id not in cached or (
                    (cached[mal_id].payload.get('source') != 'AniList' or not cached[mal_id].fetched_at or aware(cached[mal_id].fetched_at) < now - timedelta(days=CACHE_DAYS))
                    and (not cached[mal_id].last_error or aware(cached[mal_id].attempted_at) < now - timedelta(hours=6))
                )][:args.limit]
                print(json.dumps({'imported_title_ids': len(ids), 'due': len(due), 'cached': len(ids) - len(due)}), flush=True)
                client = AniListClient()
                failed, updated = 0, 0
                for offset in range(0, len(due), 40):
                    batch = due[offset:offset + 40]
                    try:
                        result = client.get_many(batch)
                    except MetadataError as exc:
                        print(f'Backfill paused: {exc} Existing metadata is unchanged.', flush=True)
                        return 1
                    for mal_id in batch:
                        row = cached.get(mal_id)
                        if row is None:
                            row = AnimeMetadataCache(mal_id=mal_id, payload={})
                            db.add(row)
                            cached[mal_id] = row
                        row.attempted_at = datetime.now(timezone.utc)
                        if mal_id in result:
                            row.payload = result[mal_id]
                            row.fetched_at = row.attempted_at
                            row.last_error = None
                            updated += 1
                        else:
                            row.last_error = 'AniList has no unique exact MAL ID match; existing metadata retained.'
                            failed += 1
                    db.commit()
                    print(json.dumps({'processed': min(offset + 40, len(due)), 'updated': updated, 'unmatched': failed, 'of': len(due)}), flush=True)
                print(json.dumps({'updated': updated, 'failed': failed, 'remaining': len(due) - updated - failed}), flush=True)
                return 1 if failed else 0
        finally:
            lock.execute(text('SELECT pg_advisory_unlock(937552221)'))


if __name__ == '__main__':
    raise SystemExit(main())
