from requests.adapters import HTTPAdapter
from urllib3.exceptions import ProtocolError, MaxRetryError
import pytest

from backend.rss_worker import create_session


def test_rss_reconnects_once_without_retrying_http_blocks_or_writes():
    with create_session('Spyboxd test') as session:
        adapter = session.get_adapter('https://letterboxd.com/example/rss/')
        assert isinstance(adapter, HTTPAdapter)
        retry = adapter.max_retries
        assert retry.total == 1
        assert retry.allowed_methods == frozenset({'GET'})
        assert not retry.respect_retry_after_header
        for status in (403, 429, 500, 503):
            assert not retry.is_retry('GET', status, has_retry_after=True)
        remaining = retry.increment(method='GET', error=ProtocolError('idle connection reset'))
        assert remaining.total == 0
        with pytest.raises(MaxRetryError):
            remaining.increment(method='GET', error=ProtocolError('still unavailable'))
        assert session.headers['User-Agent'] == 'Spyboxd test'
