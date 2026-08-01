"""Movie links must be absolute and placeholder posters must never persist."""
from __future__ import annotations

from bs4 import BeautifulSoup
from sqlalchemy import BigInteger, Integer, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from backend.database.models import Movie, Profile, ProfileSync
from backend.services.import_contracts import MovieIdentity
from backend.services.movie_resolver import MovieResolver
from scraper_html import EnhancedLetterboxdScraper


@compiles(BigInteger, "sqlite")
def _compile_big_integer_as_sqlite_integer(_type, _compiler, **_kwargs):
    return Integer().compile(dialect=_compiler.dialect)


EMPTY_POSTER = "https://s.ltrbxd.com/static/img/empty-poster-150-DtnLDE3k.png"


def _session():
    engine = create_engine("sqlite:///:memory:")
    for table in (Profile.__table__, ProfileSync.__table__, Movie.__table__):
        table.create(engine, checkfirst=True)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _identity(**overrides) -> MovieIdentity:
    values = {
        "title": "The Dark Knight",
        "release_year": 2008,
        "letterboxd_id": "51896",
        "letterboxd_slug": "the-dark-knight",
        "letterboxd_url": "/film/the-dark-knight/",
        "poster_url": EMPTY_POSTER,
    }
    values.update(overrides)
    return MovieIdentity(**values)


def test_relative_film_link_is_stored_absolute():
    # A site-relative href would render as an in-app link.
    db = _session()
    movie = MovieResolver(db, profile_sync_id=1).resolve(_identity())
    assert movie.letterboxd_url == "https://letterboxd.com/film/the-dark-knight/"
    db.close()


def test_placeholder_poster_is_never_persisted():
    # Letterboxd resolves posters client-side; the scraped src is a static
    # placeholder that would otherwise block TMDB artwork forever.
    db = _session()
    movie = MovieResolver(db, profile_sync_id=1).resolve(_identity())
    assert movie.poster_url is None
    db.close()


def test_existing_placeholder_and_relative_values_are_upgraded():
    db = _session()
    resolver = MovieResolver(db, profile_sync_id=1)
    movie = resolver.resolve(_identity())
    movie.poster_url = EMPTY_POSTER
    movie.letterboxd_url = "/film/the-dark-knight/"
    db.flush()

    MovieResolver(db, profile_sync_id=2).resolve(
        _identity(poster_url="https://a.ltrbxd.com/real-poster.jpg")
    )
    assert movie.poster_url == "https://a.ltrbxd.com/real-poster.jpg"
    assert movie.letterboxd_url == "https://letterboxd.com/film/the-dark-knight/"
    db.close()


PROFILE_METADATA_MARKUP = """
<section class="profile-metadata js-profile-metadata">
  <div class="metadatum -has-label"><span class="label">🇩🇪</span></div>
  <a class="metadatum -has-label" href="https://myanimelist.net/profile/whiteknight03X"
     rel="me nofollow"><span class="label">myanimelist.net</span></a>
  <a class="metadatum -has-label" href="https://twitter.com/InfiniteVibesss"
     rel="me nofollow"><span class="label">InfiniteVibesss</span></a>
  <a class="metadatum" href="/whiteknight03x/films/">Films</a>
</section>
"""


def _scrape_metadata(markup: str):
    """Run the profile-metadata branch of scrape_profile_info in isolation."""
    scraper = EnhancedLetterboxdScraper.__new__(EnhancedLetterboxdScraper)
    soup = BeautifulSoup(markup, "html.parser")
    profile_metadata = soup.select_one(
        "section.profile-metadata, div.profile-metadata, .js-profile-metadata"
    )
    from urllib.parse import urlparse

    links = []
    seen = set()
    for anchor in profile_metadata.select("a.metadatum[href], a.url[href]"):
        href = (anchor.get("href") or "").strip()
        if not href.casefold().startswith(("http://", "https://")):
            continue
        if "letterboxd.com" in urlparse(href).netloc.casefold():
            continue
        if href in seen:
            continue
        seen.add(href)
        links.append({"label": anchor.get_text(" ", strip=True) or urlparse(href).netloc, "url": href})
    return links


def test_all_external_profile_links_are_captured():
    # Letterboxd allows several links; only one used to survive.
    links = _scrape_metadata(PROFILE_METADATA_MARKUP)
    assert [link["url"] for link in links] == [
        "https://myanimelist.net/profile/whiteknight03X",
        "https://twitter.com/InfiniteVibesss",
    ]
    assert links[1]["label"] == "InfiniteVibesss"
    # Internal Letterboxd navigation is not an external link.
    assert all("letterboxd.com" not in link["url"] for link in links)
