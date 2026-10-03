from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.models import AnimeMetadataCache
from services.anime_metadata import (
    AniListClient, MetadataError, add_metadata, build_taste, duration_minutes,
    normalize_anilist, normalize_metadata, normalize_mal_metadata, refresh_title,
)


def public_row(mal_id=1, **changes):
    return {'idMal': mal_id, 'genres': ['Drama', 'Drama'], 'duration': 24, 'episodes': 12,
            'averageScore': 85, 'seasonYear': 2025, 'season': 'SPRING',
            'studios': {'nodes': [{'name': 'Fixture Studio'}]},
            'stats': {'scoreDistribution': [{'score': 80, 'amount': 90}, {'score': 90, 'amount': 10}]}, **changes}


def entry(mal_id=1, **changes):
    return {'mal_id': mal_id, 'title': f'Fixture {mal_id}', 'status': 'completed', 'media_type': 'TV',
            'score': 8, 'episodes': 12, 'episodes_watched': 12, 'metadata': normalize_anilist(public_row(mal_id)), **changes}


def test_normalization_preserves_provider_scale_sample_and_identity():
    result = normalize_anilist(public_row())
    assert result['community_score'] == 8.5
    assert result['community_source'] == 'AniList'
    assert result['scored_by'] == 100
    assert result['genres'] == ['Drama']
    assert result['studios'] == ['Fixture Studio']
    assert result['episode_minutes'] == 24
    assert normalize_anilist(public_row(averageScore=0))['community_score'] is None
    assert normalize_anilist(public_row(stats={}))['community_score'] is None
    assert normalize_anilist(public_row(duration=None))['episode_minutes'] is None
    assert normalize_anilist(public_row(status='NOT_YET_RELEASED'))['release_status'] == 'NOT_YET_RELEASED'
    assert normalize_anilist(public_row(status='invalid'))['release_status'] is None
    for value in (0, -1, True, '1'):
        with pytest.raises(MetadataError):
            normalize_anilist(public_row(value))


@pytest.mark.parametrize('raw,expected', [('24 min per ep', 24), ('1 hr. 30 min.', 90), ('Unknown', None), ('0 min', None), ('24 min junk', None)])
def test_duration_is_bounded_and_never_guessed(raw, expected):
    assert duration_minutes(raw) == expected


def test_jikan_identity_must_match_and_score_needs_sample():
    with pytest.raises(MetadataError):
        normalize_metadata({'data': {'mal_id': 2}}, 1)
    result = normalize_metadata({'data': {'mal_id': 1, 'score': 8, 'scored_by': 0}}, 1)
    assert result['community_score'] is None


def test_official_mal_metadata_has_exact_identity_and_honest_units():
    data = {'id': 5, 'status': 'not_yet_aired', 'mean': 8.2, 'num_scoring_users': 50,
            'average_episode_duration': 1440, 'genres': [{'name': 'Drama'}], 'studios': [],
            'start_season': {'year': 2027, 'season': 'spring'}}
    result = normalize_mal_metadata(data, 5)
    assert result['community_source'] == 'MyAnimeList' and result['community_score'] == 8.2
    assert result['episode_minutes'] == 24
    assert result['release_status'] == 'NOT_YET_RELEASED'
    assert normalize_mal_metadata({**data, 'num_scoring_users': 0}, 5)['community_score'] is None
    with pytest.raises(MetadataError):
        normalize_mal_metadata(data, 6)


class Response:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass
    def iter_content(self, size):
        yield json.dumps(self.payload).encode()


class ClientSession:
    def __init__(self, response):
        self.response, self.call = response, None
    def post(self, url, **kwargs):
        self.call = (url, kwargs)
        return self.response


def test_batch_client_only_sends_scoped_public_ids_and_never_follows_redirects():
    session = ClientSession(Response({'data': {'Page': {'media': [public_row()]}}}))
    result = AniListClient(session).get_many([1, 2])
    assert set(result) == {1}  # missing ID remains missing, not title-matched
    url, options = session.call
    assert url == 'https://graphql.anilist.co'
    assert options['json']['variables'] == {'ids': [1, 2]}
    assert options['allow_redirects'] is False
    assert 'Authorization' not in options['headers']


@pytest.mark.parametrize('response', [
    Response({}, 429), Response({}, 302), Response({'errors': [{'message': 'failed'}]}),
    Response({'data': {'Page': {'media': [public_row(2)]}}}),
    Response({'data': {'Page': {'media': 'wrong'}}}),
])
def test_bad_partial_redirected_or_mismatched_batches_are_rejected(response):
    with pytest.raises(MetadataError):
        AniListClient(ClientSession(response)).get_many([1])


def test_batch_limits_and_oversized_response(monkeypatch):
    session = ClientSession(Response({'data': {'Page': {'media': [public_row()]}}}))
    client = AniListClient(session)
    for ids in ([], [1, 1], [True], list(range(1, 52))):
        with pytest.raises(MetadataError):
            client.get_many(ids)
    monkeypatch.setattr('services.anime_metadata.MAX_BYTES', 3)
    with pytest.raises(MetadataError, match='size limit'):
        client.get_many([1])


def test_ambiguous_provider_mapping_is_excluded_without_losing_other_titles():
    session = ClientSession(Response({'data': {'Page': {'media': [public_row(), public_row(), public_row(2)]}}}))
    assert set(AniListClient(session).get_many([1, 2])) == {2}


def test_traits_community_and_runtime_use_visible_denominators():
    rows = [entry(), entry(2, score=None), entry(3, status='plan_to_watch', episodes_watched=0),
            entry(4, episodes_watched=13), entry(5, metadata=None), entry(6, episodes_watched=0, status='dropped')]
    result = build_taste(rows)
    assert result['genres'][0] == {'label': 'Drama', 'titles': 3, 'completed': 3, 'rated': 2, 'mean_score': 8}
    assert result['watched_titles'] == 4
    assert result['runtime_titles'] == 2
    assert result['progress_titles'] == 4
    assert result['estimated_watched_hours'] == 9.6
    assert result['inconsistent_progress_excluded'] == 1
    assert result['community_sample'] == 4
    assert result['mean_community_delta'] == -.5


def test_next_watch_never_recommends_confirmed_unreleased_or_cancelled_titles():
    rows = [entry(i) for i in range(1, 11)]
    for i, status in enumerate(('NOT_YET_RELEASED', 'CANCELLED', 'RELEASING', None), 11):
        rows.append(entry(i, status='plan_to_watch', episodes_watched=0,
                          metadata=normalize_anilist(public_row(i, status=status))))
    picks = build_taste(rows)['recommendations']
    assert {row['mal_id'] for row in picks} == {13, 14}


def test_recommendations_exclude_seen_entries_and_candidate_scores_do_not_leak():
    training = [entry(index, score=6 if index <= 5 else 10) for index in range(1, 11)]
    for row in training[:5]:
        row['metadata']['genres'] = ['Action']
    for row in training:
        row['metadata']['studios'] = []
    candidates = [entry(11, status='plan_to_watch', score=1, episodes_watched=0),
                  entry(12, status='plan_to_watch', episodes_watched=1), entry(13, status='on_hold'),
                  entry(14, status='dropped'), entry(15, status='plan_to_watch', episodes_watched=0, metadata=None)]
    result = build_taste(training + candidates)
    assert result['training_titles'] == 12  # scored on-hold and dropped progress are observed
    assert [row['mal_id'] for row in result['recommendations']] == [11]
    first = result['recommendations'][0]
    candidates[0]['score'] = 10
    assert build_taste(training + candidates)['recommendations'][0] == first
    assert first['traits'][0]['sample'] == 7
    assert first['estimated_minutes'] == 288
    assert build_taste(training[:3] + candidates)['recommendations'] == []


def test_empty_and_unknown_metadata_do_not_invent_preferences():
    result = build_taste([entry(metadata=None)])
    assert result['training_mean'] is None and result['community_sample'] == 0
    assert not result['genres'] and not result['recommendations']
    assert result['runtime_titles'] == 0


def test_cached_metadata_cannot_modify_snapshot_and_failures_preserve_good_data():
    engine = create_engine('sqlite:///:memory:')
    AnimeMetadataCache.__table__.create(engine)
    now = datetime(2026, 10, 3, tzinfo=timezone.utc)
    with Session(engine) as db:
        db.add(AnimeMetadataCache(mal_id=1, payload=normalize_anilist(public_row()), fetched_at=now-timedelta(days=10), attempted_at=now))
        db.commit()
        response = {'snapshot': {'id': 1}, 'entries': [entry(metadata=None), entry(2, metadata=None)]}
        original = deepcopy(response)
        result = add_metadata(db, response, now=now)
        assert response == original
        assert result['metadata_coverage']['enriched'] == 1
        assert result['metadata_coverage']['missing'] == 1
        assert result['metadata_coverage']['stale'] == 1
        assert result['entries'][0]['metadata']['source'] == 'AniList'
        assert add_metadata(db, {'snapshot': None}) == {'snapshot': None}
        class Failed:
            def get(self, _):
                raise MetadataError('HTTP 504', 504)
        with pytest.raises(MetadataError):
            refresh_title(db, 1, Failed(), now=now)
        assert db.get(AnimeMetadataCache, 1).payload['community_score'] == 8.5
        assert db.get(AnimeMetadataCache, 1).last_error == 'HTTP 504'
    engine.dispose()
