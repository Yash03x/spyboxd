"""Synthetic MAL exports only; no personal attachment belongs in git."""
from datetime import date
import gzip
from xml.sax.saxutils import escape

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.routes.anime import router
from auth import ClerkUser, get_current_user
from database.connection import get_db
from database.models import AppUser, PersonalAnimeImport, AnimeMetadataCache
from services.anime_export import (
    AnimeImportError, MAX_UPLOAD_BYTES, MAX_XML_BYTES, import_snapshot, parse_export,
    snapshot_response, summarize,
)


def xml_export(rows=None, **header):
    rows = rows if rows is not None else [{}]
    info = {"user_id": "123", "user_name": "anime_owner", "user_export_type": "1", "user_total_anime": str(len(rows)), **header}
    values = ["<myanimelist><myinfo>", *(f"<{k}>{escape(v)}</{k}>" for k, v in info.items()), "</myinfo>"]
    for i, changes in enumerate(rows, 1):
        row = {"series_animedb_id": str(i), "series_title": f"Fixture Anime {i}", "series_type": "TV", "series_episodes": "12", "my_watched_episodes": "12", "my_start_date": "2025-01-01", "my_finish_date": "2025-01-03", "my_score": "8", "my_status": "Completed", "my_times_watched": "0", "my_rewatching": "0", **changes}
        values += ["<anime>", *(f"<{k}>{escape(v)}</{k}>" for k, v in row.items()), "</anime>"]
    return ("".join(values) + "</myanimelist>").encode()


def test_plain_and_gzip_normalize_to_the_same_snapshot():
    raw = xml_export([{"series_title": 'A & B <not markup>', "my_score": "0", "series_episodes": "0", "my_start_date": "0000-00-00"}])
    plain = parse_export(raw)
    assert parse_export(gzip.compress(raw)) == plain
    row = plain['entries'][0]
    assert row['title'] == 'A & B <not markup>'
    assert row['score'] is None and row['episodes'] is None
    assert row['started_date'] is None and row['start_precision'] == 'missing'


@pytest.mark.parametrize('value,precision', [('2025', 'partial'), ('2025-04', 'partial'), ('2025-04-00', 'partial'), ('2025-00-00', 'partial'), ('2025-02-30', 'invalid'), ('2025-00-12', 'invalid')])
def test_partial_and_invalid_dates_are_preserved_not_guessed(value, precision):
    row = parse_export(xml_export([{'my_start_date': value}]))['entries'][0]
    assert row['start_raw'] == value and row['started_date'] is None
    assert row['start_precision'] == precision


@pytest.mark.parametrize('changes', [{'my_score': '-1'}, {'my_score': '11'}, {'my_score': '4.5'}, {'series_animedb_id': '0'}, {'my_status': 'Fake'}, {'my_watched_episodes': '-1'}, {'series_title': ''}, {'my_rewatching': '2'}])
def test_invalid_required_values_reject_the_entire_import(changes):
    with pytest.raises(AnimeImportError):
        parse_export(xml_export([{}, changes]))


@pytest.mark.parametrize('content', [b'not xml', b'<myanimelist>', b'', b'x' * (MAX_UPLOAD_BYTES + 1), gzip.compress(b'x' * (MAX_XML_BYTES + 1)), gzip.compress(xml_export())[:-4]])
def test_bad_or_unbounded_inputs_rejected(content):
    with pytest.raises(AnimeImportError):
        parse_export(content)


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16'])
def test_entities_and_document_types_rejected_at_parser_level(encoding):
    text = '<!DOCTYPE myanimelist [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + xml_export().decode().replace('Fixture Anime 1', '&x;')
    with pytest.raises(AnimeImportError, match='document types'):
        parse_export(text.encode(encoding))


def test_duplicates_header_mismatches_and_manga_are_rejected():
    for raw in [xml_export([{}, {'series_animedb_id': '1'}]), xml_export(user_total_anime='2'), xml_export(user_total_completed='9'), xml_export(user_export_type='2'), xml_export().replace(b'</myinfo>', b'<user_id>456</user_id></myinfo>')]:
        with pytest.raises(AnimeImportError):
            parse_export(raw)


def test_summary_preserves_grain_and_uses_honest_denominators():
    entries = parse_export(xml_export([
        {'my_score': '10'},
        {'my_score': '0', 'my_finish_date': '0000-00-00'},
        {'my_status': 'Watching', 'my_score': '6', 'my_watched_episodes': '3', 'my_finish_date': '0000-00-00'},
        {'my_status': 'Plan to Watch', 'my_score': '0', 'my_watched_episodes': '0', 'series_episodes': '0', 'my_start_date': '0000-00-00', 'my_finish_date': '0000-00-00'},
    ]))['entries']
    result = summarize(entries, today=date(2025, 12, 31))
    assert (result['total'], result['completed'], result['rated'], result['unrated']) == (4, 2, 2, 2)
    assert result['mean_score'] == result['median_score'] == 8
    assert result['episodes_watched'] == 27
    assert result['completion_percent'] == 50
    assert result['dated_completions'] == result['undated_completions'] == 1
    assert result['years'] == [{'period': '2025', 'started': 3, 'completed': 1}]
    assert result['median_elapsed_days'] == 2 and result['duration_sample'] == 1
    assert result['known_queue_remaining'] == 9
    assert sum(row['count'] for row in result['scores']) == result['rated']
    assert sum(row['count'] for row in result['statuses']) == result['total']


def test_future_dates_and_reversed_spans_do_not_make_fake_duration_stats():
    rows = parse_export(xml_export([
        {'my_start_date': '2025-01-05', 'my_finish_date': '2025-01-02'},
        {'my_finish_date': '2099-01-01'},
        {'my_start_date': '2025-01-03', 'my_finish_date': '2025-01-03', 'my_watched_episodes': '13'},
    ]))['entries']
    result = summarize(rows, today=date(2026, 1, 1))
    assert result['dated_completions'] == 2
    assert result['duration_sample'] == result['same_day_completions'] == 1
    assert result['median_elapsed_days'] == 0
    assert result['issues']['progress_exceeds_total'] == result['issues']['future_date'] == result['issues']['finish_before_start'] == 1
    assert rows[-1]['episodes_watched'] == 13  # never silently clamp source values


def test_empty_and_unscored_lists_do_not_invent_zero_ratings():
    for raw in [xml_export([]), xml_export([{'my_score': '0'}])]:
        summary = summarize(parse_export(raw)['entries'])
        assert summary['mean_score'] is None and summary['median_score'] is None


@pytest.fixture()
def db():
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    AppUser.__table__.create(engine)
    PersonalAnimeImport.__table__.create(engine)
    AnimeMetadataCache.__table__.create(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add_all([AppUser(id=1, clerk_user_id='owner', primary_profile_required=False), AppUser(id=2, clerk_user_id='other', primary_profile_required=False)])
        session.commit()
        yield session
    engine.dispose()


def test_imports_are_private_idempotent_and_preserve_history(db):
    owner = db.get(AppUser, 1)
    first, created = import_snapshot(db, owner, xml_export(), '../../anime.xml')
    assert created and first.filename == 'anime.xml'
    same, created = import_snapshot(db, owner, gzip.compress(xml_export()), 'anime.xml.gz')
    assert not created and same.id == first.id
    second, _ = import_snapshot(db, owner, xml_export([{'my_score': '9'}]), 'new.xml')
    assert snapshot_response(db, 1)['entries'][0]['score'] == 9
    assert snapshot_response(db, 1, snapshot_id=first.id)['entries'][0]['score'] == 8
    assert len(snapshot_response(db, 1)['history']) == 2
    assert snapshot_response(db, 2, snapshot_id=second.id) == {'snapshot': None}
    assert snapshot_response(db, 2) == {'snapshot': None}
    import_snapshot(db, owner, xml_export(), 'old.xml')
    assert snapshot_response(db, 1)['snapshot']['id'] == second.id  # old duplicate cannot replace latest
    with pytest.raises(AnimeImportError):
        import_snapshot(db, owner, xml_export(user_id='456'), 'wrong-account.xml')
    db.rollback()
    with pytest.raises(AnimeImportError):
        import_snapshot(db, owner, xml_export(user_total_anime='9'), 'truncated.xml')
    assert db.query(PersonalAnimeImport).count() == 2


def test_routes_enforce_auth_owner_scope_even_for_admin_and_disabled_users(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        assert client.get('/api/anime').status_code == 401
        assert client.post('/api/anime/import', files={'file': ('a.xml', xml_export())}).status_code == 401
        app.dependency_overrides[get_current_user] = lambda: ClerkUser('owner', 'session')
        result = client.post('/api/anime/import', files={'file': ('a.xml.gz', gzip.compress(xml_export()))})
        assert result.status_code == 200, result.text
        assert result.headers['cache-control'] == 'private, no-store'
        snapshot_id = result.json()['snapshot']['id']
        assert client.get('/api/anime').json()['summary']['total'] == 1
        app.dependency_overrides[get_current_user] = lambda: ClerkUser('other', 'session', is_admin=True)
        assert client.get('/api/anime').json() == {'snapshot': None}
        assert client.get(f'/api/anime?snapshot_id={snapshot_id}').status_code == 404
        db.get(AppUser, 2).is_active = False
        db.commit()
        assert client.get('/api/anime').status_code == 403
        assert client.post('/api/anime/import', files={'file': ('a.xml', xml_export())}).status_code == 403


def test_future_date_check_respects_the_viewers_calendar_day(monkeypatch):
    from datetime import datetime, timezone
    from fastapi import HTTPException
    from api.routes import anime
    instant = datetime(2026, 10, 2, 23, 30, tzinfo=timezone.utc)
    class Clock:
        @staticmethod
        def now(zone):
            return instant.astimezone(zone)
    monkeypatch.setattr(anime, 'datetime', Clock)
    assert anime._today('Europe/Berlin') == date(2026, 10, 3)
    assert anime._today('America/Los_Angeles') == date(2026, 10, 2)
    with pytest.raises(HTTPException) as error:
        anime._today('../../not-a-zone')
    assert error.value.status_code == 400
