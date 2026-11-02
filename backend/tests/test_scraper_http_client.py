"""The full-loader must preserve the HTTP transport's coherent header profile."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import scraper_html


@pytest.mark.parametrize('use_curl', [True, False])
def test_scraper_preserves_transport_managed_headers(monkeypatch, tmp_path, use_curl):
    managed = {
        'User-Agent': 'transport-selected-user-agent',
        'Sec-Ch-Ua': 'transport-selected-client-hints',
        'Sec-Ch-Ua-Platform': 'transport-selected-platform',
        'Accept': 'transport-selected-accept',
        'Accept-Encoding': 'transport-selected-encoding',
    }
    session = Mock(headers=dict(managed))
    factory = Mock(return_value=session)
    if use_curl:
        monkeypatch.setattr(scraper_html, 'curl_requests', SimpleNamespace(Session=factory))
    else:
        monkeypatch.setattr(scraper_html, 'curl_requests', None)
        monkeypatch.setattr(scraper_html.cloudscraper, 'create_scraper', factory)

    scraper = scraper_html.EnhancedLetterboxdScraper('viewer', str(tmp_path))

    assert scraper.session is session
    assert {name: session.headers[name] for name in managed} == managed
    assert session.headers['Accept-Language'] == 'en-US,en;q=0.9'
    assert set(session.headers) == set(managed) | {'Accept-Language'}
    if use_curl:
        factory.assert_called_once_with(impersonate='chrome')
    else:
        factory.assert_called_once_with(
            browser={'browser': 'chrome', 'platform': 'darwin', 'mobile': False}
        )


def test_scraper_does_not_install_a_frozen_browser_profile(monkeypatch, tmp_path):
    session = Mock(headers={})
    monkeypatch.setattr(scraper_html, 'curl_requests', SimpleNamespace(
        Session=Mock(return_value=session),
    ))

    scraper_html.EnhancedLetterboxdScraper('viewer', str(tmp_path))

    assert session.headers == {'Accept-Language': 'en-US,en;q=0.9'}
