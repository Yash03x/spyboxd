"""Recommendation filters, equal-member scoring and honest source freshness."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from database.models import Base, Movie, MovieEnrichment, MovieWatchProvider, Profile, WatchlistItem
from services.insights import InsightsService, InsightRequestError, _availability_health, _group_pick_score


def member(profile_id, rating=None, watch_count=1):
    return SimpleNamespace(profile_id=profile_id, rating=rating, liked=False, watch_count=watch_count)


def total(parts):
    return sum(parts[key] for key in ('watchlist', 'unseen', 'ratings', 'evidence'))


def test_balanced_ratings_prefer_consensus_to_the_same_average_with_a_dissenter():
    consensus = _group_pick_score({1, 2}, {1, 2}, [member(1, 3), member(2, 3)])
    polarised = _group_pick_score({1, 2}, {1, 2}, [member(1, 5), member(2, 1)])
    assert total(consensus) > total(polarised)


def test_prolific_member_and_duplicate_watch_rows_cannot_gain_extra_votes():
    baseline = _group_pick_score({1, 2}, {1}, [member(1, 4)])
    prolific = _group_pick_score({1, 2}, {1}, [member(1, 4, 100)] * 20)
    assert baseline == prolific


def test_unknown_opinions_are_neutral_not_positive_rating_evidence():
    unknown = _group_pick_score({1, 2}, set(), [member(1), member(2)])
    assert unknown['ratings'] == 12.5
    assert unknown['evidence'] == 0
    assert unknown['rated_members'] == 0


def test_profile_order_cannot_change_the_score():
    assert _group_pick_score({1, 2}, {1}, [member(1, 4), member(2, 2)]) == _group_pick_score({2, 1}, {1}, [member(2, 2), member(1, 4)])


@pytest.mark.parametrize('days,status', [(1, 'fresh'), (15, 'stale')])
def test_availability_is_dated_per_actual_region_read(days, status):
    now = datetime.now(timezone.utc)
    enrichment = MovieEnrichment(raw_payload={'watch_providers': {'results': {'DE': {}}}, '_spyboxd': {'provider_payload_fetched_at': (now - timedelta(days=days)).isoformat()}}, fetched_at=now)
    health = _availability_health(enrichment, [], 'DE', now=now)
    assert health['status'] == status
    assert health['checked_at']
    assert _availability_health(enrichment, [], 'IN', now=now)['status'] == 'unknown'


def test_tmdb_match_without_provider_payload_does_not_mean_no_offers():
    enrichment = MovieEnrichment(raw_payload={}, fetched_at=datetime.now(timezone.utc))
    assert _availability_health(enrichment, [], 'DE') == {'status': 'unknown', 'checked_at': None}


def test_fresh_movie_details_cannot_date_legacy_provider_offers():
    enrichment = MovieEnrichment(raw_payload={'watch_providers': {'results': {'DE': {}}}}, fetched_at=datetime.now(timezone.utc))
    assert _availability_health(enrichment, [], 'DE')['status'] == 'unknown'


def test_one_dated_country_cannot_date_extra_legacy_offers_elsewhere():
    now = datetime.now(timezone.utc)
    offer = {'provider_id': 8, 'provider_name': 'Example'}
    enrichment = MovieEnrichment(raw_payload={'watch_providers': {'results': {
        'DE': {'flatrate': [offer]}, 'IN': {'flatrate': [offer]},
    }}})
    stored = [MovieWatchProvider(provider_id=8, provider_type='flatrate', region='DE', fetched_at=now)]
    assert _availability_health(enrichment, stored, 'DE', now=now)['status'] == 'fresh'
    assert _availability_health(enrichment, stored, 'ALL', now=now) == {'status': 'unknown', 'checked_at': None}


def test_expired_and_old_merged_provider_sources_are_not_hidden_by_a_fresh_read():
    now = datetime.now(timezone.utc)
    enrichment = MovieEnrichment(raw_payload={'watch_providers': {'results': {'DE': {}}}, '_spyboxd': {'provider_payload_fetched_at': now.isoformat()}}, fetched_at=now)
    old = MovieWatchProvider(fetched_at=now - timedelta(days=20))
    assert _availability_health(enrichment, [old], 'DE', now=now)['status'] == 'stale'
    enrichment.raw_payload['_spyboxd']['provider_payload_expires_at'] = (now - timedelta(hours=1)).isoformat()
    assert _availability_health(enrichment, [], 'DE', now=now)['status'] == 'stale'


@pytest.fixture()
def recommender(monkeypatch):
    engine = create_engine('sqlite:///:memory:')

    @event.listens_for(engine, 'connect')
    def sqlite_functions(connection, _record):
        connection.create_function('char_length', 1, lambda value: len(value) if value is not None else None)

    Base.metadata.create_all(engine, tables=[table.__table__ for table in (Profile, Movie, MovieEnrichment, MovieWatchProvider, WatchlistItem)])
    with Session(engine) as db:
        db.add_all([Profile(id=1, username='alpha', is_active=True, scraping_status='completed'), Profile(id=2, username='bravo', is_active=True, scraping_status='completed')])
        db.commit()
        service = InsightsService(db)
        states = []
        monkeypatch.setattr(service, '_state_rows', lambda *_a, **_k: states)
        monkeypatch.setattr(service, '_event_rows', lambda *_a, **_k: [])
        monkeypatch.setattr(service, '_available_public_lists', lambda *_a, **_k: [])
        monkeypatch.setattr(service, '_coverage_payload', lambda *_a, **_k: {'profiles': []})
        monkeypatch.setattr(service, '_feature_coverage', lambda *_a, **_k: {'status': 'ready', 'score': 100, 'warnings': [], 'blockers': []})

        def add(movie_id, title, runtime=None, genre='Drama', provider_type=None):
            movie = Movie(id=movie_id, canonical_key=f'letterboxd:film-{movie_id}', title=title, normalized_title=title.lower())
            db.add(movie)
            db.add(WatchlistItem(id=movie_id, profile_id=1, movie_id=movie_id))
            payload = {'watch_providers': {'results': {'DE': {provider_type: [{'provider_id': 8, 'provider_name': 'Example'}]} if provider_type else {}}}, '_spyboxd': {'provider_payload_fetched_at': datetime.now(timezone.utc).isoformat()}}
            db.add(MovieEnrichment(movie_id=movie_id, runtime_minutes=runtime, genres=[genre], raw_payload=payload, fetched_at=datetime.now(timezone.utc)))
            db.commit()
            return movie

        def query(**kwargs):
            options = dict(mode='watchlist_overlap', region='DE', max_runtime=None, genre=None, availability=None, limit=30)
            options.update(kwargs)
            return service.watch_together(['alpha', 'bravo'], **options)

        yield add, query, states
    engine.dispose()


def test_no_rewatches_filters_the_same_watchlist_pool(recommender):
    add, query, states = recommender
    add(10, 'Seen')
    add(20, 'Unseen')
    states.append(SimpleNamespace(**vars(member(1, 4)), movie_id=10))
    assert len(query()['recommendations']) == 2
    result = query(rewatch='unseen')
    assert [item['movie']['movie_id'] for item in result['recommendations']] == [20]
    assert result['summary']['candidates'] == 1


def test_filters_compose_and_unknown_runtime_does_not_count_as_short(recommender):
    add, query, _states = recommender
    add(1, 'Short drama', 90, provider_type='flatrate')
    add(2, 'Long drama', 150, provider_type='flatrate')
    add(3, 'Short comedy', 85, genre='Comedy', provider_type='flatrate')
    add(4, 'Unknown length', None, provider_type='flatrate')
    add(5, 'Rental', 80, provider_type='rent')
    result = query(max_runtime=90, genre='drama', availability='flatrate')
    assert [item['movie']['movie_id'] for item in result['recommendations']] == [1]
    assert any('could not be checked' in warning for warning in result['coverage']['warnings'])


def test_zero_runtime_is_unknown_and_rental_filter_is_distinct(recommender):
    add, query, _states = recommender
    add(1, 'Unknown', 0, provider_type='rent')
    add(2, 'Rental', 80, provider_type='rent')
    assert [item['movie']['movie_id'] for item in query(max_runtime=90, availability='rent')['recommendations']] == [2]


def test_same_title_ties_have_stable_canonical_ids_and_score_breakdown(recommender):
    add, query, _states = recommender
    add(20, 'The same title', 80)
    add(10, 'The same title', 80)
    result = query(limit=1)
    assert result['summary']['candidates'] == 2
    assert result['recommendations'][0]['movie']['movie_id'] == 10
    assert result['recommendations'][0]['group_fit_score'] == round(total(result['recommendations'][0]['score_breakdown']), 1)
    assert result['recommendations'][0]['movie']['availability_health']['status'] == 'fresh'


def test_invalid_rewatch_is_rejected_before_querying(recommender):
    _add, query, _states = recommender
    with pytest.raises(InsightRequestError, match='Rewatch preference'):
        query(rewatch='anything')


def test_group_trends_order_by_watch_volume_before_limiting(monkeypatch):
    service = InsightsService(None)
    profile = Profile(id=1, username='alpha')
    states = []
    for movie_id in range(1, 6):
        rare = movie_id == 5
        movie = Movie(id=movie_id, title=f'Film {movie_id}', release_year=2020)
        states.append(SimpleNamespace(
            profile_id=1, movie_id=movie_id, movie=movie, rating=5.0 if rare else None,
            liked=False, enrichment=MovieEnrichment(genres=['Western' if rare else 'Drama']),
        ))
    monkeypatch.setattr(service, '_resolve_profiles', lambda *_a, **_k: [profile])
    monkeypatch.setattr(service, '_state_rows', lambda *_a, **_k: states)
    monkeypatch.setattr(service, '_event_rows', lambda *_a, **_k: [])
    monkeypatch.setattr(service, '_semantic_neighbors', lambda *_a, **_k: [])
    monkeypatch.setattr(service, '_feature_coverage', lambda *_a, **_k: {'status': 'ready', 'warnings': [], 'blockers': []})

    alignment = service.taste_dna(['alpha'], dimensions=['genre'], limit=1)
    watched = service.taste_dna(['alpha'], dimensions=['genre'], limit=1, sort_by='watched')
    assert alignment['dimensions']['genre'][0]['label'] == 'Western'
    assert watched['dimensions']['genre'][0]['label'] == 'Drama'
    assert watched['dimensions']['genre'][0]['sample_size'] == 4
    assert watched['dimensions']['genre'][0]['average_rating'] is None


def test_invalid_taste_order_is_rejected_before_querying():
    with pytest.raises(InsightRequestError, match='Taste order'):
        InsightsService(None).taste_dna([], dimensions=['genre'], limit=12, sort_by='invalid')
