from datetime import date
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.models import Profile
from services.insights import EventRow, InsightRequestError, InsightsService, StateRow
from services.research import build_research, evaluate_recommendations


@pytest.fixture()
def research(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    Profile.__table__.create(engine)
    with Session(engine) as db:
        db.add_all([Profile(id=i, username=name, is_active=True, scraping_status='completed') for i, name in ((1, 'alpha'), (2, 'bravo'), (3, 'charlie'))])
        db.commit()
        service = InsightsService(db)
        events, states = [], []
        monkeypatch.setattr(service, '_event_rows', lambda profiles: [e for e in events if e.profile_id in {p.id for p in profiles}])
        monkeypatch.setattr(service, '_state_rows', lambda profiles, **_: [s for s in states if s.profile_id in {p.id for p in profiles}])
        monkeypatch.setattr(service, '_feature_coverage', lambda *_: {'status': 'ready', 'blockers': [], 'warnings': []})

        def add(event_id, profile_id, day='2025-01-05', rating=4, movie_id=None, title='Film', logged=None, rewatch=False):
            movie_id = movie_id or event_id
            name = {1: 'alpha', 2: 'bravo', 3: 'charlie'}[profile_id]
            movie = SimpleNamespace(id=movie_id, title=title, release_year=2020, letterboxd_url=f'https://letterboxd.com/film/film-{movie_id}/')
            enrichment = SimpleNamespace(genres=['Drama'], original_language='en', production_countries=['DE'])
            events.append(EventRow(event_id, profile_id, name, movie_id, date.fromisoformat(day), date.fromisoformat(logged) if logged else None, rating, False, rewatch, [], 'diary', movie))
            if not any(s.profile_id == profile_id and s.movie_id == movie_id for s in states):
                states.append(StateRow(profile_id, name, movie_id, rating, False, [], None, None, 1, int(rewatch), movie, enrichment))
        yield service, add, events, states
    engine.dispose()


def run(service, **kwargs):
    return build_research(service, ['alpha', 'bravo'], start=date(2025, 1, 1), end=date(2025, 1, 10), **kwargs)


def test_equal_duration_comparison_and_event_denominators(research):
    service, add, *_ = research
    add(1, 1, day='2024-12-22', rating=2)
    add(2, 1, day='2025-01-01', movie_id=9, rating=4)
    add(3, 2, day='2025-01-10', movie_id=9, rating=None)
    add(4, 1, day='2025-01-10', movie_id=9, rating=5, rewatch=True)
    add(5, 1, day='2025-01-11')
    result = run(service)
    group = result['groups'][0]
    assert result['period']['previous_from'] == '2024-12-22'
    assert group['current']['watches'] == 3
    assert group['current']['films'] == 1
    assert group['current']['rated'] == 2
    assert group['current']['average_rating'] == 4.5
    assert group['current']['watches_per_member_30_days'] == 4.5
    assert group['previous']['watches'] == 1
    assert group['change']['watches_percent'] == 200
    assert sum(row['watches'] for row in group['per_profile']) == group['current']['watches']


def test_zero_baseline_is_not_infinite_growth_and_no_rating_is_not_zero(research):
    service, add, *_ = research
    add(1, 1, rating=None)
    group = run(service)['groups'][0]
    assert group['change']['watches_percent'] is None
    assert group['current']['average_rating'] is None


def test_overlapping_groups_have_unique_evidence_with_membership(research):
    service, add, *_ = research
    add(1, 1)
    add(2, 2)
    add(3, 3)
    result = run(service, comparison=['bravo', 'charlie'])
    assert [g['current']['watches'] for g in result['groups']] == [2, 2]
    assert result['evidence']['total'] == 3
    assert next(r for r in result['evidence']['rows'] if r['username'] == 'bravo')['groups'] == ['A', 'B']
    assert any('not independent' in warning for warning in result['coverage']['warnings'])


def test_filters_apply_to_summary_evidence_and_previous_period(research):
    service, add, *_ = research
    add(1, 1, title='MATCH', day='2024-12-30')
    add(2, 1, title='MATCH')
    add(3, 2, title='Other')
    result = run(service, search='match', trait='Drama')
    assert result['groups'][0]['current']['watches'] == result['evidence']['total'] == 1
    assert result['groups'][0]['previous']['watches'] == 1
    assert result['evidence']['rows'][0]['title'] == 'MATCH'
    assert run(service, trait='Comedy')['evidence']['total'] == 0


def test_log_date_mode_is_explicit_and_falls_back_to_watch_date(research):
    service, add, *_ = research
    add(1, 1, day='2024-01-01', logged='2025-01-03')
    add(2, 1, day='2025-01-04')
    assert run(service)['evidence']['total'] == 1
    assert run(service, basis='logged')['evidence']['total'] == 2


def test_pagination_is_stable_and_does_not_change_totals(research):
    service, add, *_ = research
    for i in range(1, 8):
        add(i, 1, title=f'Film {i}')
    first, second = run(service, limit=3), run(service, limit=3, offset=3)
    assert first['evidence']['total'] == second['evidence']['total'] == 7
    assert not ({r['event_id'] for r in first['evidence']['rows']} & {r['event_id'] for r in second['evidence']['rows']})
    assert first['groups'][0]['current']['watches'] == 7


def test_coverage_counts_missing_dates_per_film_not_by_subtracting_group_totals(research):
    service, add, events, states = research
    add(1, 1, movie_id=1)
    add(2, 1, movie_id=1, rewatch=True)
    add(3, 2, movie_id=2)
    events.pop()  # Bravo has a known film, but no recorded diary date.
    assert run(service)['coverage']['undated_known_watches'] == 1
    states[0] = replace(states[0], enrichment=None)
    result = run(service)
    assert result['evidence']['total'] == 2
    assert result['coverage']['events_without_trait'] == 2
    assert result['groups'][0]['traits'] == []


@pytest.mark.parametrize('options', [{'start': date(2025, 2, 1), 'end': date(2025, 1, 1)}, {'start': date(1800, 1, 1)}, {'end': date(2200, 1, 1)}, {'dimension': 'bad'}, {'sort': 'bad'}, {'basis': 'bad'}])
def test_invalid_research_inputs_are_rejected(research, options):
    service, *_ = research
    with pytest.raises(InsightRequestError):
        build_research(service, ['alpha'], **options)


def test_comparison_cannot_read_an_untracked_profile(research):
    service, *_ = research
    service.allowed_profile_ids = {1, 2}
    with pytest.raises(InsightRequestError) as error:
        run(service, comparison=['charlie'])
    assert error.value.status_code == 403


def test_holdout_diagnostic_requires_enough_common_evidence(research):
    service, add, *_ = research
    add(1, 1, movie_id=1)
    add(2, 2, movie_id=1)
    assert evaluate_recommendations(service, ['alpha', 'bravo'])['status'] == 'insufficient_data'


def test_held_out_ratings_do_not_rank_their_own_picks(research):
    service, add, events, states = research
    for i in range(1, 13):
        add(i, 1, movie_id=i, rating=5 if i % 2 else 1)
        add(100+i, 2, movie_id=i, rating=4)
    before = evaluate_recommendations(service, ['alpha', 'bravo'])
    before_ids = [r['movie_id'] for r in before['per_profile'][0]['examples']]
    from dataclasses import replace
    states[:] = [replace(row, rating=5) if row.profile_id == 1 else row for row in states]
    after = evaluate_recommendations(service, ['alpha', 'bravo'])
    assert [r['movie_id'] for r in after['per_profile'][0]['examples']] == before_ids
    assert after['per_profile'][0]['held_out_mean'] == 5
    assert after['members_evaluated'] == 2


def test_holdout_summary_weights_members_equally(research):
    service, add, *_ = research
    for i in range(1, 11):
        add(i, 1, movie_id=i, rating=5)
        add(100+i, 2, movie_id=i, rating=1)
    result = evaluate_recommendations(service, ['alpha', 'bravo', 'charlie'])
    assert result['equal_member_mean'] == 3
    assert result['worst_member_mean'] == 1
    assert result['members_selected'] == 3
    assert result['members_evaluated'] == 2
