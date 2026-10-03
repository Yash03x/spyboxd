"""Cached public catalogue facts and explainable, account-private taste insights.

Only numeric public title IDs go to catalogue providers. Never send usernames, scores, list
statuses, dates or the XML. A provider failure never replaces the last good data.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math
import re
from statistics import mean
import time

import requests
from sqlalchemy.orm import Session

from database.models import AnimeMetadataCache

CACHE_DAYS = 7
MAX_BYTES = 2 * 1024 * 1024
JIKAN_BASE = "https://api.jikan.moe/v4/anime"


class MetadataError(ValueError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def bounded_number(value, low, high):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high:
        return value
    return None


def names(value):
    if not isinstance(value, list):
        return []
    return sorted({item['name'].strip()[:100] for item in value[:100] if isinstance(item, dict) and isinstance(item.get('name'), str) and item['name'].strip()})


def duration_minutes(value):
    """Parse provider-labelled average episode duration, never title runtime."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'(?:(\d+) hr(?:s)?\.?\s*)?(?:(\d+) min(?:s)?\.?)?(?: per ep\.?)?', value.strip())
    if not match or not any(match.groups()):
        return None
    return bounded_number(int(match[1] or 0) * 60 + int(match[2] or 0), 1, 1440)


def normalize_metadata(payload, mal_id):
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, dict) or type(data.get('mal_id')) is not int or data['mal_id'] != mal_id:
        raise MetadataError('Metadata response did not match the requested MAL ID.')
    score = bounded_number(data.get('score'), 1, 10)
    scored_by = bounded_number(data.get('scored_by'), 1, 1_000_000_000)
    return {
        'source': 'Jikan / MyAnimeList',
        'community_source': 'MyAnimeList',
        'release_status': {'Not yet aired': 'NOT_YET_RELEASED', 'Currently Airing': 'RELEASING', 'Finished Airing': 'FINISHED'}.get(data.get('status')),
        'genres': names(data.get('genres')),
        'themes': names(data.get('themes')),
        'studios': names(data.get('studios')),
        'community_score': score if scored_by else None,
        'scored_by': scored_by,
        'episode_minutes': duration_minutes(data.get('duration')),
        'duration_label': str(data.get('duration') or '')[:100],
        'episodes': bounded_number(data.get('episodes'), 1, 1_000_000),
        'airing_year': bounded_number(data.get('year'), 1900, 2200),
        'season': data.get('season') if data.get('season') in ('spring', 'summer', 'fall', 'winter') else None,
    }


def normalize_mal_metadata(data, mal_id):
    if not isinstance(data, dict) or type(data.get('id')) is not int or data['id'] != mal_id:
        raise MetadataError('MAL metadata did not match the requested title ID.')
    sample = bounded_number(data.get('num_scoring_users'), 1, 1_000_000_000)
    duration = bounded_number(data.get('average_episode_duration'), 1, 86400)
    season = data.get('start_season') if isinstance(data.get('start_season'), dict) else {}
    return {
        'source': 'MyAnimeList API', 'community_source': 'MyAnimeList',
        'release_status': {'not_yet_aired': 'NOT_YET_RELEASED', 'currently_airing': 'RELEASING', 'finished_airing': 'FINISHED'}.get(data.get('status')),
        'genres': names(data.get('genres')), 'themes': [], 'studios': names(data.get('studios')),
        'community_score': bounded_number(data.get('mean'), 1, 10) if sample else None,
        'scored_by': sample, 'episode_minutes': duration / 60 if duration else None,
        'duration_label': f'{duration / 60:g} min per ep' if duration else '',
        'episodes': bounded_number(data.get('num_episodes'), 1, 1_000_000),
        'airing_year': bounded_number(season.get('year'), 1900, 2200),
        'season': season.get('season') if season.get('season') in ('spring', 'summer', 'fall', 'winter') else None,
    }


class JikanClient:
    def __init__(self, session=None, interval=1.1):
        self.session = session or requests.Session()
        self.interval = max(1.1, interval)  # Below Jikan's 60 requests/minute ceiling.
        self.previous = 0.0

    def get(self, mal_id: int):
        if type(mal_id) is not int or mal_id <= 0:
            raise MetadataError('A positive MAL title ID is required.')
        delay = self.interval - (time.monotonic() - self.previous)
        if delay > 0:
            time.sleep(delay)
        self.previous = time.monotonic()
        try:
            with self.session.get(f'{JIKAN_BASE}/{mal_id}', timeout=(5, 25), allow_redirects=False, stream=True, headers={'Accept': 'application/json', 'User-Agent': 'Spyboxd/1.0 (public anime metadata cache)'}) as response:
                if response.status_code != 200:
                    raise MetadataError(f'Jikan returned HTTP {response.status_code}.', response.status_code)
                raw = bytearray()
                for chunk in response.iter_content(64 * 1024):
                    raw.extend(chunk)
                    if len(raw) > MAX_BYTES:
                        raise MetadataError('Metadata response exceeded the size limit.')
                import json
                return normalize_metadata(json.loads(raw), mal_id)
        except (requests.RequestException, ValueError) as exc:
            if isinstance(exc, MetadataError):
                raise
            raise MetadataError('Public anime metadata could not be read.') from exc


ANILIST_QUERY = '''query ($ids: [Int]) {
  Page(perPage: 50) {
    media(idMal_in: $ids, type: ANIME) {
      id idMal status genres duration episodes averageScore season seasonYear
      studios(isMain: true) { nodes { name } }
      stats { scoreDistribution { score amount } }
    }
  }
}'''


def normalize_anilist(data):
    if not isinstance(data, dict) or type(data.get('idMal')) is not int or data['idMal'] <= 0:
        raise MetadataError('AniList response has no valid MAL identity.')
    distribution = (data.get('stats') or {}).get('scoreDistribution') or []
    scored_by = sum(bounded_number(row.get('amount'), 0, 1_000_000_000) or 0 for row in distribution if isinstance(row, dict))
    average = bounded_number(data.get('averageScore'), 1, 100)
    duration = bounded_number(data.get('duration'), 1, 1440)
    return {
        'source': 'AniList', 'community_source': 'AniList',
        'release_status': data.get('status') if data.get('status') in ('FINISHED', 'RELEASING', 'NOT_YET_RELEASED', 'CANCELLED', 'HIATUS') else None,
        'genres': sorted({value[:100] for value in data.get('genres', []) if isinstance(value, str) and value}),
        'themes': [], 'studios': names((data.get('studios') or {}).get('nodes')),
        'community_score': average / 10 if average and scored_by else None,
        'scored_by': scored_by or None, 'episode_minutes': duration,
        'duration_label': f'{duration} min per ep' if duration else '',
        'episodes': bounded_number(data.get('episodes'), 1, 1_000_000),
        'airing_year': bounded_number(data.get('seasonYear'), 1900, 2200),
        'season': data.get('season', '').lower() if data.get('season') else None,
    }


class AniListClient:
    """Small ID-scoped catalogue batches, at most 20 requests per minute."""
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.previous = 0.0

    def get_many(self, ids):
        if not ids or len(ids) > 50 or any(type(value) is not int or value <= 0 for value in ids) or len(set(ids)) != len(ids):
            raise MetadataError('Choose 1–50 unique positive MAL title IDs.')
        delay = 3.1 - (time.monotonic() - self.previous)
        if delay > 0:
            time.sleep(delay)
        self.previous = time.monotonic()
        try:
            with self.session.post('https://graphql.anilist.co', json={'query': ANILIST_QUERY, 'variables': {'ids': ids}}, headers={'Accept': 'application/json', 'User-Agent': 'Spyboxd/1.0 (personal anime insights)'}, timeout=(5, 30), allow_redirects=False, stream=True) as response:
                if response.status_code != 200:
                    raise MetadataError(f'AniList returned HTTP {response.status_code}.', response.status_code)
                raw = bytearray()
                for chunk in response.iter_content(64 * 1024):
                    raw.extend(chunk)
                    if len(raw) > MAX_BYTES:
                        raise MetadataError('Metadata response exceeded the size limit.')
                import json
                payload = json.loads(raw)
                if not isinstance(payload, dict) or payload.get('errors'):
                    raise MetadataError('AniList returned an incomplete GraphQL result.')
                media = (payload.get('data') or {}).get('Page', {}).get('media')
                if not isinstance(media, list):
                    raise MetadataError('AniList returned an unexpected catalogue result.')
                result = {}
                ambiguous = set()
                for item in media:
                    normalized = normalize_anilist(item)
                    key = item['idMal']
                    if key not in ids:
                        raise MetadataError('AniList returned an unrequested MAL identity.')
                    if key in result or key in ambiguous:
                        # Provider sometimes maps a compilation and its parts to
                        # one MAL ID. Never pick one arbitrarily or multiply it.
                        result.pop(key, None)
                        ambiguous.add(key)
                    else:
                        result[key] = normalized
                return result
        except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
            if isinstance(exc, MetadataError):
                raise
            raise MetadataError('Public anime metadata could not be read.') from exc


def refresh_title(db: Session, mal_id: int, client: JikanClient, *, now=None):
    instant = now or datetime.now(timezone.utc)
    cached = db.get(AnimeMetadataCache, mal_id)
    if cached is None:
        cached = AnimeMetadataCache(mal_id=mal_id, payload={}, attempted_at=instant)
        db.add(cached)
    cached.attempted_at = instant
    try:
        payload = client.get(mal_id)
    except MetadataError as exc:
        cached.last_error = str(exc)
        db.commit()
        raise
    cached.payload = payload
    cached.fetched_at = instant
    cached.last_error = None
    db.commit()
    return cached


def add_metadata(db: Session, response: dict, *, now=None):
    """Called only after owner-scoped snapshot retrieval. No network on GET."""
    if not response.get('snapshot'):
        return response
    instant = now or datetime.now(timezone.utc)
    entries = response['entries']
    ids = [entry['mal_id'] for entry in entries]
    cached = {}
    for offset in range(0, len(ids), 500):
        cached.update({row.mal_id: row for row in db.query(AnimeMetadataCache).filter(AnimeMetadataCache.mal_id.in_(ids[offset:offset + 500])).all()})
    enriched = []
    missing, stale = 0, 0
    updated = []
    for entry in entries:
        row = cached.get(entry['mal_id'])
        metadata = None
        if row and row.fetched_at and row.payload:
            fetched = aware(row.fetched_at)
            outdated = fetched < instant - timedelta(days=CACHE_DAYS)
            metadata = {**row.payload, 'fetched_at': fetched.isoformat(), 'stale': outdated, 'refresh_failed': bool(row.last_error)}
            stale += int(outdated)
            updated.append(fetched)
        else:
            missing += 1
        enriched.append({**entry, 'metadata': metadata})
    result = {**response, 'entries': enriched}
    result['taste'] = build_taste(enriched)
    result['metadata_coverage'] = {
        'total': len(entries), 'enriched': len(entries) - missing, 'missing': missing, 'stale': stale,
        'oldest_fetched_at': min(updated).isoformat() if updated else None,
        'latest_fetched_at': max(updated).isoformat() if updated else None,
        'source': ', '.join(sorted({row['metadata']['source'] for row in enriched if row['metadata']})) or 'AniList', 'cache_days': CACHE_DAYS,
    }
    return result


def build_taste(entries: list[dict]):
    watched = [row for row in entries if row['status'] != 'plan_to_watch' and (row['episodes_watched'] > 0 or row['status'] == 'completed')]
    training = [row for row in watched if row.get('score') is not None and row.get('metadata')]
    baseline = mean([row['score'] for row in training]) if training else None
    buckets = {field: defaultdict(list) for field in ('genres', 'studios', 'themes')}
    for row in watched:
        for field, groups in buckets.items():
            for name in (row.get('metadata') or {}).get(field, []):
                groups[name].append(row)

    def group_rows(field):
        result = []
        for label, rows in buckets[field].items():
            ratings = [row['score'] for row in rows if row.get('score') is not None]
            result.append({'label': label, 'titles': len(rows), 'completed': sum(row['status'] == 'completed' for row in rows), 'rated': len(ratings), 'mean_score': round(mean(ratings), 2) if ratings else None})
        return sorted(result, key=lambda row: (-row['titles'], row['label']))

    comparisons = []
    minutes, runtime_titles, inconsistent = 0, 0, 0
    for row in entries:
        meta = row.get('metadata') or {}
        community = meta.get('community_score')
        if row.get('score') is not None and community is not None:
            comparisons.append({'mal_id': row['mal_id'], 'title': row['title'], 'score': row['score'], 'community_score': community, 'community_source': meta.get('community_source', meta.get('source')), 'scored_by': meta.get('scored_by'), 'delta': round(row['score'] - community, 2)})
        if row['episodes_watched'] > 0:
            # Keep source progress untouched; exclude impossible totals from estimates.
            if row.get('episodes') and row['episodes_watched'] > row['episodes']:
                inconsistent += 1
            elif meta.get('episode_minutes'):
                minutes += row['episodes_watched'] * meta['episode_minutes']
                runtime_titles += 1

    # Candidate scores cannot leak into the fit: only observed titles train it.
    # Per-trait deviations are shrunk toward the user's baseline by five titles.
    affinity = {}
    for field in ('genres', 'studios'):
        affinity[field] = {}
        for label, rows in buckets[field].items():
            scores = [row['score'] for row in rows if row.get('score') is not None]
            if len(scores) >= 3 and baseline is not None:
                affinity[field][label] = {'delta': (sum(scores) - len(scores) * baseline) / (len(scores) + 5), 'n': len(scores)}
    picks = []
    for row in entries:
        # A plan entry with recorded progress is not unseen; do not recommend it as such.
        if row['status'] != 'plan_to_watch' or row['episodes_watched'] != 0 or not row.get('metadata'):
            continue
        meta = row['metadata']
        if meta.get('release_status') in ('NOT_YET_RELEASED', 'CANCELLED'):
            continue
        traits = []
        for field in ('genres', 'studios'):
            for label in meta.get(field, []):
                evidence = affinity[field].get(label)
                if evidence:
                    traits.append({'label': label, 'kind': field, 'sample': evidence['n'], 'affinity': round(evidence['delta'], 3)})
        if len(training) < 10 or not traits:
            continue
        genre = [affinity['genres'][name]['delta'] for name in meta.get('genres', []) if name in affinity['genres']]
        studio = [affinity['studios'][name]['delta'] for name in meta.get('studios', []) if name in affinity['studios']]
        # Normalize by supported weights so unknown studio data is not a penalty.
        components = [(mean(genre), .75)] if genre else []
        if studio:
            components.append((mean(studio), .25))
        fit = sum(value * weight for value, weight in components) / sum(weight for _, weight in components)
        episodes = row.get('episodes') or meta.get('episodes')
        picks.append({'mal_id': row['mal_id'], 'title': row['title'], 'media_type': row['media_type'], 'fit': round(fit, 3), 'release_status': meta.get('release_status'), 'community_score': meta.get('community_score'), 'community_source': meta.get('community_source', meta.get('source')), 'episodes': episodes, 'estimated_minutes': episodes * meta['episode_minutes'] if episodes and meta.get('episode_minutes') else None, 'traits': sorted(traits, key=lambda value: (-value['affinity'], value['label']))[:4]})
    picks.sort(key=lambda row: (-row['fit'], -(row['community_score'] or 0), row['title'], row['mal_id']))
    return {
        'genres': group_rows('genres'), 'studios': group_rows('studios'), 'themes': group_rows('themes'),
        'watched_titles': len(watched), 'training_titles': len(training), 'training_mean': round(baseline, 2) if baseline is not None else None,
        'community_sample': len(comparisons), 'mean_community_delta': round(mean([row['delta'] for row in comparisons]), 2) if comparisons else None,
        'higher_than_community': sorted([row for row in comparisons if row['delta'] > 0], key=lambda row: (-row['delta'], row['mal_id']))[:10],
        'lower_than_community': sorted([row for row in comparisons if row['delta'] < 0], key=lambda row: (row['delta'], row['mal_id']))[:10],
        'estimated_watched_hours': round(minutes / 60, 1), 'runtime_titles': runtime_titles,
        'progress_titles': sum(row['episodes_watched'] > 0 for row in entries), 'inconsistent_progress_excluded': inconsistent,
        'recommendations': picks,
        'recommendation_method': 'Unstarted plan-to-watch titles, ranked by your shrunk genre (75%) and studio (25%) rating deviations. At least 10 scored watched titles and 3 scored examples per trait; five neutral pseudo-observations per trait. Unsupported weights are omitted. Community score only breaks ties. This is a content-based ranking heuristic, not a predicted rating or probability.',
    }
