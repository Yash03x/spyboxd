from copy import deepcopy
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from test_anime_export import db, xml_export  # noqa: F401 - shared synthetic fixture
from test_mal_client import _entry, FakeResponse, FakeSession
from api.routes.anime import router
from auth import ClerkUser, get_current_user
from database.connection import get_db
from database.models import AppUser, PersonalAnimeImport, PersonalAnimeSync
from services.anime_export import compare_snapshots, import_snapshot, latest_snapshot, AnimeImportError
from services.mal_client import MALClient, MALRequestError
from services.anime_metadata import aware
from services.personal_anime_sync import (SyncUnavailable, due_owners, normalize_entries,
                                         set_enabled, sync_owner, sync_status)


class Client:
    def __init__(self, rows=None, callback=None):
        self.rows = rows if rows is not None else [_entry()]
        self.callback = callback
    def fetch_private_list(self, username):
        assert username == 'anime_owner'
        if self.callback:
            self.callback()
        return self.rows


def seed(db):
    return import_snapshot(db, db.get(AppUser, 1), xml_export([{'series_animedb_id': '5114'}]), 'fixture.xml')[0]


def allow_retry(db):
    state = db.get(PersonalAnimeSync, 1)
    state.last_attempt_at = datetime.now(timezone.utc) - timedelta(hours=7)
    state.next_sync_at = state.last_attempt_at
    db.commit()


def test_compare_is_exact_private_and_never_joins_current_metadata(db):
    first, _ = import_snapshot(db, db.get(AppUser, 1), xml_export([{}, {'my_score': '0'}, {}]), 'old.xml')
    second, _ = import_snapshot(db, db.get(AppUser, 1), xml_export([{'my_score': '9'}, {'series_animedb_id': '3', 'series_title': 'Fixture Anime 3'}, {'series_animedb_id': '4', 'my_watched_episodes': '3', 'my_status': 'Watching'}]), 'new.xml')
    result = compare_snapshots(db, 1, first.id, second.id)
    assert result['counts'] == {'added': 1, 'removed': 1, 'changed': 1, 'unchanged': 1}
    assert result['episode_balance_delta'] == -9
    assert result['changes'][0]['fields'] == ['score']
    assert result['changes'][1]['before']['score'] is None
    assert compare_snapshots(db, 2, first.id, second.id) is None
    assert compare_snapshots(db, 1, first.id, 999) is None
    with pytest.raises(AnimeImportError):
        compare_snapshots(db, 1, second.id, first.id)


def test_sync_is_private_idempotent_and_real_reversions_are_new_snapshots(db):
    first = seed(db)
    result = sync_owner(db, 1, client=Client())
    assert result['created'] and result['last_success_at']
    current = latest_snapshot(db, 1)
    assert current.id != first.id and current.payload['source'] == 'MAL API'
    assert current.payload['entries'][0]['score'] == 10
    assert current.payload['entries'][0]['times_watched_raw'] is None
    assert latest_snapshot(db, 2) is None
    count = db.query(PersonalAnimeImport).count()
    allow_retry(db)
    assert not sync_owner(db, 1, client=Client())['created']
    assert db.query(PersonalAnimeImport).count() == count
    allow_retry(db)
    sync_owner(db, 1, client=Client([_entry(list_status={'score': 7})]))
    allow_retry(db)
    assert sync_owner(db, 1, client=Client())['created']
    assert db.query(PersonalAnimeImport).count() == count + 2
    assert latest_snapshot(db, 1).payload['entries'][0]['score'] == 10


@pytest.mark.parametrize('rows', [[], [{'node': {}}], [_entry(), _entry()], [_entry(list_status={'score': 11})], [_entry(list_status={'num_episodes_watched': -1})], [_entry(list_status={'status': 'fake'})]])
def test_empty_duplicate_or_invalid_responses_never_replace_a_good_snapshot(db, rows):
    first = seed(db)
    with pytest.raises(MALRequestError):
        sync_owner(db, 1, client=Client(rows))
    assert latest_snapshot(db, 1).id == first.id
    state = db.get(PersonalAnimeSync, 1)
    assert state.last_error and state.lease_token is None and state.last_success_at is None
    assert aware(state.next_sync_at) > datetime.now(timezone.utc)


def test_newer_upload_during_network_fetch_wins(db):
    seed(db)
    def upload():
        import_snapshot(db, db.get(AppUser, 1), xml_export([{'my_score': '9'}]), 'newer.xml')
    with pytest.raises(SyncUnavailable, match='newer import'):
        sync_owner(db, 1, client=Client(callback=upload))
    assert latest_snapshot(db, 1).filename == 'newer.xml'
    assert db.get(PersonalAnimeSync, 1).lease_token is None


def test_disabling_during_network_fetch_cancels_publication(db, monkeypatch):
    monkeypatch.setenv('MAL_CLIENT_ID', 'test')
    first = seed(db)
    set_enabled(db, db.get(AppUser, 1), True)
    with pytest.raises(SyncUnavailable, match='cancelled'):
        sync_owner(db, 1, client=Client(callback=lambda: set_enabled(db, db.get(AppUser, 1), False)), scheduled=True)
    assert latest_snapshot(db, 1).id == first.id
    assert not sync_status(db, 1)['enabled']


def test_schedule_is_opt_in_honours_backoff_and_excludes_disabled_accounts(db, monkeypatch):
    monkeypatch.setenv('MAL_CLIENT_ID', 'test')
    seed(db)
    assert sync_owner(db, 1, client=Client(), scheduled=True) == {'skipped': True}
    set_enabled(db, db.get(AppUser, 1), True)
    assert due_owners(db) == [1]
    sync_owner(db, 1, client=Client(), scheduled=True)
    assert due_owners(db) == []
    with pytest.raises(SyncUnavailable, match='ten minutes'):
        sync_owner(db, 1, client=Client())
    allow_retry(db)
    db.get(AppUser, 1).is_active = False
    db.commit()
    assert due_owners(db) == []


def test_missing_credentials_do_not_enable_or_mutate(db, monkeypatch):
    monkeypatch.delenv('MAL_CLIENT_ID', raising=False)
    first = seed(db)
    with pytest.raises(SyncUnavailable) as error:
        sync_owner(db, 1)
    assert error.value.status == 503
    with pytest.raises(SyncUnavailable):
        set_enabled(db, db.get(AppUser, 1), True)
    assert latest_snapshot(db, 1).id == first.id
    assert db.get(PersonalAnimeSync, 1) is None


def test_partial_dates_are_preserved_and_never_guessed():
    row = normalize_entries([_entry(list_status={'start_date': '2024-01', 'finish_date': '', 'score': 0})])[0]
    assert row['started_date'] is None and row['start_raw'] == '2024-01'
    assert row['start_precision'] == 'partial' and row['score'] is None


@pytest.mark.parametrize('source,expected', [('tv_special', 'TV Special'), ('cm', 'CM'), ('pv', 'PV'), ('ova', 'OVA'), ('unknown_new_type', 'Unknown')])
def test_api_formats_match_xml_vocabulary_without_guessing(source, expected):
    assert normalize_entries([_entry(node={'media_type': source})])[0]['media_type'] == expected


def test_api_only_unknown_fields_and_missing_date_encoding_are_not_changes(db):
    a = seed(db)
    b, _ = import_snapshot(db, db.get(AppUser, 1), xml_export([{'series_animedb_id': '5114', 'my_score': '9'}]), 'two.xml')
    left, right = deepcopy(a.payload), deepcopy(a.payload)
    left['entries'][0].update(start_raw='0000-00-00', start_precision='missing')
    right['entries'][0].update(start_raw='', start_precision='missing', priority='UNKNOWN', times_watched_raw=None)
    a.payload, b.payload = left, right
    db.commit()
    assert compare_snapshots(db, 1, a.id, b.id)['counts']['unchanged'] == 1


def test_private_list_client_fails_closed_on_partial_pagination_and_redirects():
    first = {'data': [_entry()], 'paging': {'next': 'https://api.myanimelist.net/v2/users/x/animelist?offset=500'}}
    session = FakeSession([FakeResponse(first), FakeResponse({'data': [_entry(node={'id': 2})], 'paging': {}})])
    assert len(MALClient(client_id='test', session=session, min_interval_seconds=0).fetch_private_list('x')) == 2
    assert all(call['allow_redirects'] is False and call['stream'] for call in session.calls)
    for payload in ({}, {'data': [], 'paging': {'next': 'https://evil.example/'}}, {'data': [], 'paging': []}):
        with pytest.raises(MALRequestError):
            MALClient(client_id='test', session=FakeSession([FakeResponse(payload)]), min_interval_seconds=0).fetch_private_list('x')
    with pytest.raises(MALRequestError):
        MALClient(client_id='test', session=FakeSession([FakeResponse({}, status_code=302)])).fetch_private_list('x')


def test_new_routes_require_owner_auth_and_never_allow_admin_cross_access(db, monkeypatch):
    monkeypatch.delenv('MAL_CLIENT_ID', raising=False)
    first = seed(db)
    second, _ = import_snapshot(db, db.get(AppUser, 1), xml_export([{'my_score': '9'}]), 'two.xml')
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        for method, path in [('get', '/api/anime/compare?before=1&after=2'), ('get', '/api/anime/sync'), ('post', '/api/anime/sync')]:
            assert getattr(client, method)(path).status_code == 401
        app.dependency_overrides[get_current_user] = lambda: ClerkUser('other', 'session', is_admin=True)
        assert client.get(f'/api/anime/compare?before={first.id}&after={second.id}').status_code == 404
        assert client.get('/api/anime/sync').json()['username'] is None
        app.dependency_overrides[get_current_user] = lambda: ClerkUser('owner', 'session')
        result = client.get(f'/api/anime/compare?before={first.id}&after={second.id}')
        assert result.status_code == 200 and result.headers['cache-control'] == 'private, no-store'
        assert client.patch('/api/anime/sync', json={'enabled': 'false'}).status_code == 422
        assert client.patch('/api/anime/sync', json={'enabled': True}).status_code == 503
        assert client.post('/api/anime/sync').status_code == 503
        db.get(AppUser, 1).is_active = False; db.commit()
        assert client.get('/api/anime/sync').status_code == 403
