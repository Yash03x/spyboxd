#!/usr/bin/env python3
"""
Enhanced Letterboxd Profile Scraper

A comprehensive scraper for Letterboxd user profiles that extracts:
- Complete film data (ratings, reviews, watchlist, diary)
- Profile information and statistics
- Social connections and activity
- Custom lists and detailed metadata
- Advanced analytics and viewing patterns
"""

import cloudscraper
try:
    from curl_cffi import requests as curl_requests
except ImportError:  # Kept for a clear local error before dependencies are installed.
    curl_requests = None
import csv
import json
import argparse
import time
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Union
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import re
from dataclasses import dataclass, asdict


class ScrapeValidationError(RuntimeError):
    """Raised when a full scrape cannot prove a dataset was fetched completely."""


@dataclass
class ProfileInfo:
    """Profile information structure"""
    username: str
    display_name: str = ""
    bio: str = ""
    location: str = ""
    website: str = ""
    join_date: Optional[str] = None
    avatar_url: str = ""
    total_films: int = 0
    total_reviews: int = 0
    total_lists: int = 0
    following_count: int = 0
    followers_count: int = 0
    favorite_films: List[Dict] = None

    def __post_init__(self):
        if self.favorite_films is None:
            self.favorite_films = []


@dataclass
class FilmEntry:
    """Enhanced film entry structure"""
    title: str
    year: Optional[int] = None
    rating: Optional[float] = None
    watch_date: Optional[str] = None
    review_text: str = ""
    is_rewatch: bool = False
    is_liked: bool = False
    tags: List[str] = None
    viewing_context: str = ""  # theater, home, etc.
    film_id: str = ""
    slug: str = ""
    poster_url: str = ""
    has_review: bool = False
    review_likes: int = 0
    lists_containing: List[str] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.lists_containing is None:
            self.lists_containing = []


class EnhancedLetterboxdScraper:
    def __init__(self, username: str, output_dir: Optional[str] = None, debug: bool = False):
        self.username = username
        self.output_dir = output_dir or f"{username}_data"
        self.debug = debug
        
        # Create output directory structure
        os.makedirs(self.output_dir, exist_ok=True)
        
        # URL structure for different sections
        self.urls = {
            'profile': f"https://letterboxd.com/{username}/",
            'films': f"https://letterboxd.com/{username}/films/",
            'diary': f"https://letterboxd.com/{username}/diary/",
            'reviews': f"https://letterboxd.com/{username}/reviews/",
            'watchlist': f"https://letterboxd.com/{username}/watchlist/",
            'lists': f"https://letterboxd.com/{username}/lists/",
            'following': f"https://letterboxd.com/{username}/following/",
            'followers': f"https://letterboxd.com/{username}/followers/",
            'stats': f"https://letterboxd.com/{username}/films/stats/",
        }
        
        # Letterboxd currently challenges ordinary requests/cloudscraper on paginated
        # profile pages. curl_cffi's browser impersonation is required for a complete sync.
        if curl_requests is not None:
            self.session = curl_requests.Session(impersonate='chrome')
            self._curl_impersonation = True
        else:
            self.session = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'darwin', 'mobile': False}
            )
            self._curl_impersonation = False
        self.session.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Sec-Ch-Ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"macOS"',
            'Referer': 'https://letterboxd.com/',
            'Cache-Control': 'max-age=0',
        })
        
        # Data storage
        self.profile_info = ProfileInfo(username=username)
        self.films_data = []
        self.diary_entries = []
        self.reviews_data = []
        self.watchlist_data = []
        self.lists_data = []
        self.list_items_data = []
        self.social_data = {
            'following': [],
            'followers': [],
            'activity': []
        }
        self.movies_seen = set()  # To track duplicates
        self.completed_datasets = set()
        self.requested_datasets = set()
        self.unavailable_datasets = {}
    
    def fetch_with_retry(
        self,
        url: str,
        max_retries: int = 5,
        *,
        allow_private_forbidden: bool = False,
    ):
        """Fetch URL with exponential backoff retry logic."""
        for attempt in range(max_retries):
            try:
                request_kwargs = {'timeout': 30}
                if self._curl_impersonation:
                    request_kwargs['impersonate'] = 'chrome'
                response = self.session.get(url, **request_kwargs)

                if allow_private_forbidden and self._is_private_forbidden_response(response):
                    return response
                
                # Handle rate limiting specifically
                if response.status_code == 429:
                    wait_time = (2 ** attempt) * 10  # Much longer wait for rate limiting
                    print(f"Rate limited (429) on attempt {attempt + 1} for {url}. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                    
                response.raise_for_status()
                return response
                
            except Exception as e:
                wait_time = (2 ** attempt) + 1  # Exponential backoff
                print(f"Attempt {attempt + 1} failed for {url}: {e}")
                
                if attempt < max_retries - 1:
                    print(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    print(f"Failed to fetch {url} after {max_retries} attempts")
                    return None

    @staticmethod
    def _next_page_url(soup: BeautifulSoup, current_url: str) -> Optional[str]:
        next_link = soup.select_one('a[rel="next"], a.next, .paginate-next a, a.next-page')
        href = next_link.get('href') if next_link else None
        return urljoin(current_url, href) if href else None

    @staticmethod
    def _lazy_posters(soup: BeautifulSoup) -> List:
        posters = soup.select(
            'div.react-component[data-component-class="LazyPoster"][data-item-name], '
            'div.react-component[data-item-name][data-item-link]'
        )
        seen = set()
        unique = []
        for poster in posters:
            marker = id(poster)
            if marker not in seen:
                unique.append(poster)
                seen.add(marker)
        return unique

    @staticmethod
    def _poster_identity(poster) -> Dict:
        item_name = poster.get('data-item-name', '').strip()
        year_match = re.search(r'\((\d{4})\)\s*$', item_name)
        year = int(year_match.group(1)) if year_match else None
        title = item_name[:year_match.start()].strip() if year_match else item_name
        href = poster.get('data-item-link', '')
        slug = poster.get('data-item-slug', '')
        film_id = poster.get('data-film-id', '')
        raw_identifier = poster.get('data-postered-identifier', '')
        if raw_identifier:
            try:
                identifier = json.loads(raw_identifier)
            except (TypeError, ValueError, json.JSONDecodeError):
                identifier = {}
            uid_match = re.search(r'film:(\d+)', str(identifier.get('uid') or ''))
            film_id = film_id or (uid_match.group(1) if uid_match else '') or str(identifier.get('lid') or '')
        if not slug:
            slug_match = re.search(r'/film/([^/]+)/?', href)
            slug = slug_match.group(1) if slug_match else ''
        image = poster.find('img')
        if image is None and poster.find_parent() is not None:
            image = poster.find_parent().find('img')
        poster_url = poster.get('data-poster-url', '')
        if image:
            poster_url = poster_url or image.get('src', '') or image.get('data-src', '')
            title = title or image.get('alt', '').strip()
        poster_url = urljoin('https://letterboxd.com/', poster_url) if poster_url else ''
        return {
            'title': title,
            'year': year,
            'film_id': film_id,
            'slug': slug,
            'film_url': href,
            'poster_url': poster_url,
        }

    @staticmethod
    def _declares_empty(soup: BeautifulSoup, dataset: str) -> bool:
        text = ' '.join(' '.join(soup.stripped_strings).casefold().split())
        phrases = {
            'films': ('no films', 'no films yet', 'hasn\u2019t watched any films', "hasn't watched any films"),
            'diary': ('no diary entries', 'hasn\u2019t logged any films', "hasn't logged any films"),
            'reviews': ('no reviews', 'hasn\u2019t reviewed any films', "hasn't reviewed any films"),
            'watchlist': (
                'watchlist is empty',
                'no films in this watchlist',
                'empty watchlist',
                'wants to see 0 films',
                'no films yet',
            ),
            'lists': ('no lists', 'hasn\u2019t made any lists', "hasn't made any lists"),
            'favorites': (
                'no favorite films',
                'no favourite films',
                'hasn\u2019t selected any favorite films',
                "hasn't selected any favorite films",
                'hasn\u2019t selected any favourite films',
                "hasn't selected any favourite films",
            ),
        }
        return any(phrase in text for phrase in phrases.get(dataset, ()))

    def _require_response(self, response, dataset: str, url: str):
        if response is None:
            raise ScrapeValidationError(f"Could not fetch required {dataset} page: {url}")
        return response

    def _finish_dataset(self, dataset: str) -> None:
        if dataset in self.unavailable_datasets:
            raise ScrapeValidationError(
                f"Dataset {dataset} cannot be both completed and unavailable"
            )
        self.completed_datasets.add(dataset)

    def _mark_unavailable(self, dataset: str, reason: str) -> None:
        if dataset in self.completed_datasets:
            raise ScrapeValidationError(
                f"Dataset {dataset} cannot be both completed and unavailable"
            )
        self.unavailable_datasets[dataset] = reason

    @staticmethod
    def _is_private_forbidden_response(response) -> bool:
        if response is None or getattr(response, 'status_code', None) != 403:
            return False
        body = str(getattr(response, 'text', '') or '').casefold()
        return (
            'letterboxd - forbidden' in body
            and ('correct clearance' in body or 'attempting to access is classified' in body)
        )

    def _extract_rating(self, container) -> Optional[float]:
        if container is None:
            return None
        marker = container.select_one('span.rating, svg.glyph.-rating, .inline-rating svg')
        if marker is None:
            return None
        stars_text = marker.get('aria-label', '') or marker.get_text()
        return self.convert_stars_to_rating(stars_text)

    @staticmethod
    def _extract_rewatch(rewatch_cell) -> bool:
        if rewatch_cell is None:
            return False
        cell_classes = set(rewatch_cell.get('class', []))
        return 'icon-status-on' in cell_classes or 'icon-status-off' not in cell_classes

    @staticmethod
    def _extract_display_name(soup: BeautifulSoup) -> str:
        label = soup.select_one(
            'h1.person-display-name .displayname .label, '
            '.profile-header-person .displayname .label, '
            'h1.person-display-name .displayname'
        )
        if label is not None:
            return label.get_text(' ', strip=True)
        heading = soup.select_one('.profile-header-person h1, h1.title-1, main h1')
        return heading.get_text(' ', strip=True) if heading is not None else ''
    
    def scrape_profile_info(self) -> ProfileInfo:
        """Scrape basic profile information and statistics."""
        print(f"🔍 Scraping profile info for {self.username}...")
        
        response = self._require_response(
            self.fetch_with_retry(self.urls['profile']),
            'profile',
            self.urls['profile'],
        )
            
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract profile information
        try:
            # Display name
            display_name = self._extract_display_name(soup)
            if display_name:
                self.profile_info.display_name = display_name
            
            # Bio
            bio_element = soup.select_one('.profile-text, .profile-summary .bio, .profile-bio')
            if bio_element:
                self.profile_info.bio = bio_element.get_text().strip()
            
            # Location and website
            profile_metadata = soup.find('section', class_='profile-metadata')
            if profile_metadata:
                location = profile_metadata.find('span', class_='location')
                if location:
                    self.profile_info.location = location.get_text().strip()
                
                website = profile_metadata.find('a', class_='url')
                if website:
                    self.profile_info.website = website.get('href', '')
            
            # Avatar URL
            avatar = soup.select_one('.profile-avatar img, img.avatar, .avatar img')
            if avatar:
                self.profile_info.avatar_url = avatar.get('src', '') or avatar.get('data-src', '')
            
            # Statistics from profile page
            stats = soup.select(
                f'a[href="/{self.username}/films/"], '
                f'a[href="/{self.username}/following/"], '
                f'a[href="/{self.username}/followers/"]'
            )
            for stat in stats:
                stat_text = stat.get_text().strip()
                href = stat.get('href', '')
                numbers = re.findall(r'[\d,]+', stat_text)
                if href == f'/{self.username}/films/' and 'film' in stat_text.casefold() and numbers:
                    self.profile_info.total_films = int(numbers[0].replace(',', ''))
                elif href == f'/{self.username}/following/' and numbers:
                    self.profile_info.following_count = int(numbers[0].replace(',', ''))
                elif href == f'/{self.username}/followers/' and numbers:
                    self.profile_info.followers_count = int(numbers[0].replace(',', ''))
            
            # Favorite films (top 4)
            favorite_root = soup.select_one('#favourites, #favorites, .profile-favorites, .profile-favourites')
            if favorite_root is not None:
                for poster in self._lazy_posters(favorite_root)[:4]:
                    identity = self._poster_identity(poster)
                    if not identity['title'] or not identity['film_url']:
                        raise ScrapeValidationError(
                            "Recognized favorite-film poster lacked title or URL"
                        )
                    self.profile_info.favorite_films.append({
                        'title': identity['title'],
                        'year': identity['year'],
                        'film_id': identity['film_id'],
                        'slug': identity['slug'],
                        'url': identity['film_url'],
                        'poster': identity['poster_url'],
                    })
            elif not self._declares_empty(soup, 'favorites'):
                raise ScrapeValidationError(
                    "Profile page returned no recognized favorites container or explicit empty state"
                )
            
        except Exception as exc:
            raise ScrapeValidationError(f"Could not parse required profile data: {exc}") from exc
        
        self._finish_dataset('profile')
        self._finish_dataset('favorites')
        return self.profile_info
    
    def scrape_all_films(self) -> List[Dict]:
        """Scrape all films from the user's films page."""
        print(f"🎬 Scraping all films for {self.username}...")

        films = []
        page_url = self.urls['films']
        page_num = 1

        while True:
            response = self._require_response(self.fetch_with_retry(page_url), 'films', page_url)
            soup = BeautifulSoup(response.content, 'html.parser')
            posters = self._lazy_posters(soup)
            if not posters:
                if page_num == 1 and self._declares_empty(soup, 'films'):
                    break
                raise ScrapeValidationError(
                    f"Films page {page_num} returned HTML but no recognized film posters"
                )

            for poster in posters:
                try:
                    identity = self._poster_identity(poster)
                    if not identity['title'] or not identity['film_url']:
                        raise ScrapeValidationError("Recognized film poster lacked title or URL")
                    container = poster.find_parent('li') or poster.parent
                    rating = None
                    is_liked = False
                    has_review = False
                    viewing_data = container.select_one('.poster-viewingdata') if container else None
                    if viewing_data:
                        rating = self._extract_rating(viewing_data)
                        is_liked = viewing_data.select_one('.like, .icon-liked') is not None
                        has_review = viewing_data.select_one('a.review-micro, .icon-review') is not None

                    films.append({
                        'title': identity['title'],
                        'year': identity['year'],
                        'rating': rating,
                        'film_id': identity['film_id'],
                        'slug': identity['slug'],
                        'poster_url': identity['poster_url'],
                        'film_url': identity['film_url'],
                        'is_liked': is_liked,
                        'has_review': has_review,
                        'movie_id': identity['film_id'],
                    })
                except Exception as exc:
                    raise ScrapeValidationError(
                        f"Could not parse film record on page {page_num}: {exc}"
                    ) from exc

            next_page_url = self._next_page_url(soup, page_url)
            if not next_page_url:
                break
            page_num += 1
            page_url = next_page_url
            time.sleep(1)  # Be respectful

        if not films and not self._declares_empty(soup, 'films'):
            raise ScrapeValidationError("Full film history resolved to zero without an explicit empty state")
        self.films_data = films
        self._finish_dataset('films')
        print(f"✓ Found {len(films)} films")
        return films

    def scrape_diary_entries(self) -> List[Dict]:
        """Scrape complete diary entries with watch dates."""
        print(f"📅 Scraping diary entries for {self.username}...")

        diary_entries = []
        page_url = self.urls['diary']
        page_num = 1
        current_month = None
        current_year = None

        while True:
            response = self._require_response(self.fetch_with_retry(page_url), 'diary', page_url)
            soup = BeautifulSoup(response.content, 'html.parser')

            diary_table = soup.select_one('table.diary-table, main table')
            if not diary_table:
                if page_num == 1 and self._declares_empty(soup, 'diary'):
                    break
                raise ScrapeValidationError("Diary page returned no recognized diary table")
            diary_rows = [
                row for row in diary_table.select('tbody tr')
                if row.select_one('div.react-component[data-item-name][data-item-link]')
            ]
            if not diary_rows:
                if page_num == 1 and self._declares_empty(soup, 'diary'):
                    break
                raise ScrapeValidationError(
                    f"Diary page {page_num} returned a table but no recognized diary rows"
                )

            for row in diary_rows:
                try:
                    month_cell = row.select_one('td.col-monthdate, td.td-calendar')
                    day_cell = row.select_one('td.col-daydate, td.td-day')
                    month_link = month_cell.select_one('a.month') if month_cell else None
                    year_link = month_cell.select_one('a.year') if month_cell else None
                    day_link = day_cell.select_one('a.daydate, a') if day_cell else None
                    if month_link and year_link:
                        current_month = month_link.get_text().strip()
                        current_year = year_link.get_text().strip()

                    watch_date = ''
                    time_element = row.select_one('time[datetime]')
                    if time_element:
                        watch_date = time_element.get('datetime', '')
                    elif current_month and current_year and day_link:
                        day_text = day_link.get_text().strip()
                        if day_text:
                            watch_date = f"{current_month} {current_year} {day_text}"

                    poster = row.select_one('div.react-component[data-item-name][data-item-link]')
                    identity = self._poster_identity(poster)
                    rating_cell = row.select_one('td.col-rating, .td-rating')
                    rating = None
                    if rating_cell:
                        rating = self._extract_rating(rating_cell)

                    rewatch_cell = row.select_one('td.col-rewatch, .td-rewatch')
                    is_rewatch = self._extract_rewatch(rewatch_cell)
                    is_liked = row.select_one('td.col-like .icon-liked, .td-like .icon-liked, .icon-liked') is not None
                    has_review = row.select_one('td.col-review a, .td-review a, a.icon-review') is not None
                    source_entry_id = (
                        row.get('data-viewing-id', '')
                        or row.get('data-entry-id', '')
                        or row.get('id', '')
                    )

                    diary_entries.append({
                        'title': identity['title'],
                        'year': identity['year'],
                        'watch_date': watch_date,
                        'rating': rating,
                        'is_rewatch': is_rewatch,
                        'is_liked': is_liked,
                        'has_review': has_review,
                        'film_url': identity['film_url'],
                        'film_id': identity['film_id'],
                        'slug': identity['slug'],
                        'source_entry_id': source_entry_id,
                    })
                except Exception as exc:
                    raise ScrapeValidationError(
                        f"Could not parse diary record on page {page_num}: {exc}"
                    ) from exc

            next_page_url = self._next_page_url(soup, page_url)
            if not next_page_url:
                break
            page_num += 1
            page_url = next_page_url
            time.sleep(1)  # Be respectful

        if not diary_entries and not self._declares_empty(soup, 'diary'):
            raise ScrapeValidationError("Diary resolved to zero without an explicit empty state")
        self.diary_entries = diary_entries
        self._finish_dataset('diary')
        print(f"✓ Found {len(diary_entries)} diary entries")
        return diary_entries
    
    def scrape_reviews(self) -> List[Dict]:
        """Scrape all reviews with full text content."""
        print(f"📝 Scraping reviews for {self.username}...")

        reviews = []
        page_url = self.urls['reviews']
        page_num = 1

        while True:
            response = self._require_response(self.fetch_with_retry(page_url), 'reviews', page_url)
            soup = BeautifulSoup(response.content, 'html.parser')

            main = soup.select_one('main') or soup
            posters = self._lazy_posters(main)
            if not posters:
                if page_num == 1 and self._declares_empty(soup, 'reviews'):
                    break
                raise ScrapeValidationError(
                    f"Reviews page {page_num} returned HTML but no recognized review posters"
                )

            parsed_on_page = 0
            for poster in posters:
                try:
                    review_elem = (
                        poster.find_parent('article')
                        or poster.find_parent('li', class_=re.compile(r'film-detail|production-viewing'))
                        or poster.find_parent(class_=re.compile(r'film-detail|production-viewing'))
                    )
                    if review_elem is None:
                        continue
                    identity = self._poster_identity(poster)
                    rating = self._extract_rating(review_elem)

                    # Letterboxd renders a spoiler-reveal control before the hidden
                    # review body. A grouped selector containing ``.body-text``
                    # therefore returns the warning in document order, even when
                    # ``.js-review-body`` appears first in the selector string.
                    review_text_elem = review_elem.select_one('.js-review-body')
                    if review_text_elem is None:
                        for fallback_selector in ('.review-text', '.body-text'):
                            for candidate in review_elem.select(fallback_selector):
                                candidate_classes = set(candidate.get('class', []))
                                inside_spoiler_control = (
                                    'js-spoiler-container' in candidate_classes
                                    or candidate.find_parent(class_='js-spoiler-container') is not None
                                    or candidate.select_one('[data-js-trigger="spoiler.reveal"]') is not None
                                )
                                if not inside_spoiler_control:
                                    review_text_elem = candidate
                                    break
                            if review_text_elem is not None:
                                break
                    review_text = ""
                    if review_text_elem:
                        for script in review_text_elem(["script", "style"]):
                            script.decompose()
                        review_text = review_text_elem.get_text().strip()
                    contains_spoilers = review_elem.select_one(
                        '.js-spoiler-container, [data-js-trigger="spoiler.reveal"]'
                    ) is not None

                    date_elem = review_elem.select_one('time.timestamp, time[datetime]')
                    review_date = date_elem.get('datetime', '') if date_elem else ""
                    if not review_date:
                        date_elem = review_elem.select_one('span.date')
                        review_date = date_elem.get_text().strip() if date_elem else ""

                    likes_elem = review_elem.select_one('.like-link-target, [data-count].like-link-target')
                    review_likes = 0
                    if likes_elem:
                        likes_count = likes_elem.get('data-count', '0')
                        review_likes = int(likes_count) if likes_count.isdigit() else 0

                    reviews.append({
                        'title': identity['title'],
                        'year': identity['year'],
                        'rating': rating,
                        'review_text': review_text,
                        'review_date': review_date,
                        'review_likes': review_likes,
                        'contains_spoilers': contains_spoilers,
                        'film_url': identity['film_url'],
                        'film_id': identity['film_id'],
                        'slug': identity['slug'],
                    })
                    parsed_on_page += 1
                except Exception as exc:
                    raise ScrapeValidationError(
                        f"Could not parse review record on page {page_num}: {exc}"
                    ) from exc

            if parsed_on_page == 0:
                raise ScrapeValidationError(
                    f"Reviews page {page_num} contained posters but no recognized review records"
                )
            next_page_url = self._next_page_url(soup, page_url)
            if not next_page_url:
                break
            page_num += 1
            page_url = next_page_url
            time.sleep(1)  # Be respectful

        if not reviews and not self._declares_empty(soup, 'reviews'):
            raise ScrapeValidationError("Reviews resolved to zero without an explicit empty state")
        self.reviews_data = reviews
        self._finish_dataset('reviews')
        print(f"✓ Found {len(reviews)} reviews")
        return reviews
    
    def scrape_watchlist(self) -> List[Dict]:
        """Scrape complete watchlist."""
        print(f"📋 Scraping watchlist for {self.username}...")

        watchlist = []
        page_url = self.urls['watchlist']
        page_num = 1

        while True:
            response = self.fetch_with_retry(page_url, allow_private_forbidden=True)
            if self._is_private_forbidden_response(response):
                self.watchlist_data = []
                self._mark_unavailable('watchlist', 'forbidden/private')
                print("⚠ Watchlist is private or forbidden; preserving prior imported state")
                return []
            response = self._require_response(response, 'watchlist', page_url)
            soup = BeautifulSoup(response.content, 'html.parser')

            main = soup.select_one('main') or soup
            posters = self._lazy_posters(main)
            if not posters:
                if page_num == 1 and self._declares_empty(soup, 'watchlist'):
                    break
                raise ScrapeValidationError(
                    f"Watchlist page {page_num} returned HTML but no recognized film posters"
                )

            for poster in posters:
                try:
                    identity = self._poster_identity(poster)
                    if not identity['title'] or not identity['film_url']:
                        raise ScrapeValidationError("Recognized watchlist poster lacked title or URL")
                    watchlist.append(identity)
                except Exception as exc:
                    raise ScrapeValidationError(
                        f"Could not parse watchlist record on page {page_num}: {exc}"
                    ) from exc

            next_page_url = self._next_page_url(soup, page_url)
            if not next_page_url:
                break
            page_num += 1
            page_url = next_page_url
            time.sleep(1)  # Be respectful

        if not watchlist and not self._declares_empty(soup, 'watchlist'):
            raise ScrapeValidationError("Watchlist resolved to zero without an explicit empty state")
        self.watchlist_data = watchlist
        self._finish_dataset('watchlist')
        print(f"✓ Found {len(watchlist)} watchlist items")
        return watchlist
    
    def scrape_custom_lists(self) -> List[Dict]:
        """Scrape user's custom lists."""
        print(f"📝 Scraping custom lists for {self.username}...")

        lists = []
        page_url = self.urls['lists']
        page_num = 1
        seen_urls = set()
        while True:
            response = self.fetch_with_retry(page_url, allow_private_forbidden=True)
            if self._is_private_forbidden_response(response):
                self.lists_data = []
                self.list_items_data = []
                self._mark_unavailable('lists', 'forbidden/private')
                self._mark_unavailable('list_items', 'forbidden/private')
                print("⚠ Lists are private or forbidden; preserving prior imported state")
                return []
            response = self._require_response(response, 'lists', page_url)
            soup = BeautifulSoup(response.content, 'html.parser')
            main = soup.select_one('main') or soup
            list_elements = main.select('article.list-summary, section.list-set, li.list-item')
            if not list_elements:
                if page_num == 1 and self._declares_empty(soup, 'lists'):
                    break
                raise ScrapeValidationError(
                    f"Lists page {page_num} returned HTML but no recognized list summaries"
                )

            parsed_on_page = 0
            for list_elem in list_elements:
                try:
                    list_link = list_elem.select_one('h2.name a, h2.title a')
                    if list_link is None:
                        list_link = list_elem.select_one(
                            f'a[href^="/{self.username}/list/"]'
                        )
                    if not list_link:
                        continue
                    list_title = list_link.get_text(' ', strip=True)
                    list_url = list_link.get('href', '')
                    if not list_title or not list_url or list_url in seen_urls:
                        continue
                    seen_urls.add(list_url)
                    desc_elem = list_elem.select_one('.body-text, .description')
                    description = desc_elem.get_text(' ', strip=True) if desc_elem else ""
                    count_elem = list_elem.select_one('.list-count, .value')
                    count_match = re.search(r'([\d,]+)', count_elem.get_text() if count_elem else '')
                    film_count = int(count_match.group(1).replace(',', '')) if count_match else 0
                    lists.append({
                        'title': list_title,
                        'description': description,
                        'film_count': film_count,
                        'url': list_url,
                    })
                    parsed_on_page += 1
                except Exception as exc:
                    raise ScrapeValidationError(
                        f"Could not parse list record on page {page_num}: {exc}"
                    ) from exc

            if parsed_on_page == 0:
                raise ScrapeValidationError(
                    f"Lists page {page_num} contained summaries but no usable list records"
                )
            next_page_url = self._next_page_url(soup, page_url)
            if not next_page_url:
                break
            page_num += 1
            page_url = next_page_url
            time.sleep(1)

        if not lists and not self._declares_empty(soup, 'lists'):
            raise ScrapeValidationError("Custom lists resolved to zero without an explicit empty state")
        self.lists_data = lists
        self.list_items_data = self._scrape_list_memberships(lists)
        self._finish_dataset('lists')
        if 'list_items' not in self.unavailable_datasets:
            self._finish_dataset('list_items')
        print(f"✓ Found {len(lists)} custom lists")
        return lists

    def _scrape_list_memberships(self, lists: List[Dict]) -> List[Dict]:
        """Fetch every public list page and retain ordered canonical film identity."""
        all_items = []
        for list_data in lists:
            list_url = urljoin('https://letterboxd.com/', list_data.get('url', ''))
            expected_count = int(list_data.get('film_count') or 0)
            page_url = list_url
            page_num = 1
            position = 0
            seen_movie_keys = set()

            while page_url:
                response = self.fetch_with_retry(page_url, allow_private_forbidden=True)
                if self._is_private_forbidden_response(response):
                    self._mark_unavailable(
                        'list_items',
                        f"forbidden/private list: {list_data.get('title', '')}",
                    )
                    return []
                response = self._require_response(
                    response, f"list {list_data.get('title', '')}", page_url
                )
                soup = BeautifulSoup(response.content, 'html.parser')
                main = soup.select_one('main') or soup
                posters = main.select(
                    'ul.poster-list div.react-component[data-component-class="LazyPoster"], '
                    'ul.posterlist div.react-component[data-component-class="LazyPoster"]'
                )
                if not posters:
                    if page_num == 1 and expected_count == 0:
                        break
                    raise ScrapeValidationError(
                        f"List {list_data.get('title', '')!r} page {page_num} "
                        "returned no recognized list films"
                    )

                for poster in posters:
                    identity = self._poster_identity(poster)
                    movie_key = identity['film_id'] or identity['slug'] or identity['film_url']
                    if not identity['title'] or not movie_key or movie_key in seen_movie_keys:
                        continue
                    seen_movie_keys.add(movie_key)
                    position += 1
                    all_items.append({
                        'list_name': list_data.get('title', ''),
                        'list_url': list_data.get('url', ''),
                        'position': position,
                        **identity,
                        'notes': '',
                    })

                page_url = self._next_page_url(soup, page_url)
                page_num += 1
                if page_url:
                    time.sleep(1)

            if expected_count and position != expected_count:
                raise ScrapeValidationError(
                    f"List {list_data.get('title', '')!r} reported {expected_count} films "
                    f"but only {position} were captured"
                )
        return all_items
    
    def _write_csv(self, file_path: str, data: List[Dict], fieldnames: List[str]):
        """Helper function to write data to a CSV file."""
        full_path = os.path.join(self.output_dir, file_path)
        with open(full_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)

    def _save_profile_info(self):
        """Saves the main profile information."""
        if 'profile' not in self.completed_datasets:
            return
        fieldnames = [
            'Username', 'Display_Name', 'Bio', 'Location', 'Website', 'Join_Date',
            'Avatar_URL', 'Total_Films', 'Total_Reviews', 'Total_Lists',
            'Following_Count', 'Followers_Count'
        ]
        data = [{
            'Username': self.profile_info.username,
            'Display_Name': self.profile_info.display_name,
            'Bio': self.profile_info.bio,
            'Location': self.profile_info.location,
            'Website': self.profile_info.website,
            'Join_Date': self.profile_info.join_date,
            'Avatar_URL': self.profile_info.avatar_url,
            'Total_Films': self.profile_info.total_films,
            'Total_Reviews': self.profile_info.total_reviews,
            'Total_Lists': self.profile_info.total_lists,
            'Following_Count': self.profile_info.following_count,
            'Followers_Count': self.profile_info.followers_count
        }]
        self._write_csv("profile.csv", data, fieldnames)

    def _save_diary_entries(self):
        """Saves diary entries."""
        if 'diary' not in self.completed_datasets:
            return
        fieldnames = [
            'Name', 'Year', 'Watched Date', 'Rating', 'Is_Rewatch', 'Is_Liked',
            'Has_Review', 'Film_ID', 'Slug', 'Diary_Entry_ID', 'Film_URL'
        ]
        data = [{
            'Name': entry['title'], 'Year': entry['year'], 'Watched Date': entry['watch_date'],
            'Rating': entry['rating'], 'Is_Rewatch': 'Yes' if entry['is_rewatch'] else 'No',
            'Is_Liked': 'Yes' if entry['is_liked'] else 'No', 'Has_Review': 'Yes' if entry['has_review'] else 'No',
            'Film_ID': entry.get('film_id', ''), 'Slug': entry.get('slug', ''),
            'Diary_Entry_ID': entry.get('source_entry_id', ''),
            'Film_URL': entry['film_url']
        } for entry in self.diary_entries]
        self._write_csv("diary.csv", data, fieldnames)

    def _save_reviews(self):
        """Saves reviews."""
        if 'reviews' not in self.completed_datasets:
            return
        fieldnames = [
            'Name', 'Year', 'Rating', 'Review', 'Review_Date', 'Review_Likes',
            'Contains_Spoilers', 'Film_ID', 'Slug', 'Film_URL'
        ]
        data = [{
            'Name': review['title'], 'Year': review['year'], 'Rating': review['rating'],
            'Review': review['review_text'], 'Review_Date': review['review_date'],
            'Review_Likes': review['review_likes'],
            'Contains_Spoilers': 'Yes' if review.get('contains_spoilers', False) else 'No',
            'Film_ID': review.get('film_id', ''),
            'Slug': review.get('slug', ''), 'Film_URL': review['film_url']
        } for review in self.reviews_data]
        self._write_csv("reviews.csv", data, fieldnames)

    def _save_watchlist(self):
        """Saves the watchlist."""
        if 'watchlist' not in self.completed_datasets:
            return
        fieldnames = ['Name', 'Year', 'Film_ID', 'Slug', 'Film_URL', 'Poster_URL']
        data = [{
            'Name': item['title'], 'Year': item['year'], 'Film_ID': item.get('film_id', ''),
            'Slug': item.get('slug', ''), 'Film_URL': item['film_url'],
            'Poster_URL': item['poster_url']
        } for item in self.watchlist_data]
        self._write_csv("watchlist.csv", data, fieldnames)

    def _save_custom_lists(self):
        """Saves custom lists."""
        if 'lists' not in self.completed_datasets:
            return
        fieldnames = ['Title', 'Description', 'Film_Count', 'URL']
        data = [{
            'Title': li['title'], 'Description': li['description'],
            'Film_Count': li['film_count'], 'URL': li['url']
        } for li in self.lists_data]
        self._write_csv("lists.csv", data, fieldnames)

    def _save_list_items(self):
        """Save normalized ordered memberships for all custom lists."""
        if 'list_items' not in self.completed_datasets:
            return
        fieldnames = [
            'List_Name', 'List_URL', 'Position', 'Name', 'Year', 'Film_ID',
            'Slug', 'Film_URL', 'Poster_URL', 'Notes'
        ]
        data = [{
            'List_Name': item.get('list_name', ''),
            'List_URL': item.get('list_url', ''),
            'Position': item.get('position', ''),
            'Name': item.get('title', ''),
            'Year': item.get('year', ''),
            'Film_ID': item.get('film_id', ''),
            'Slug': item.get('slug', ''),
            'Film_URL': item.get('film_url', ''),
            'Poster_URL': item.get('poster_url', ''),
            'Notes': item.get('notes', ''),
        } for item in self.list_items_data]
        self._write_csv("list_items.csv", data, fieldnames)

    def _save_favorites(self):
        if 'favorites' not in self.completed_datasets:
            return
        fieldnames = ['Position', 'Name', 'Year', 'Film_ID', 'Slug', 'Film_URL', 'Poster_URL']
        data = [{
            'Position': position,
            'Name': item.get('title', ''),
            'Year': item.get('year', ''),
            'Film_ID': item.get('film_id', ''),
            'Slug': item.get('slug', ''),
            'Film_URL': item.get('url', ''),
            'Poster_URL': item.get('poster', ''),
        } for position, item in enumerate(self.profile_info.favorite_films, start=1)]
        self._write_csv("favorites.csv", data, fieldnames)

    def _remove_stale_unavailable_files(self) -> None:
        """Remove only managed CSVs contradicted by the new manifest state."""
        dataset_files = {
            'watchlist': ('watchlist.csv',),
            'lists': ('lists.csv',),
            'list_items': ('list_items.csv',),
            'favorites': ('favorites.csv',),
        }
        output_root = Path(self.output_dir)
        for dataset_name in self.unavailable_datasets:
            for filename in dataset_files.get(dataset_name, ()):
                artifact = output_root / filename
                if artifact.is_file() or artifact.is_symlink():
                    artifact.unlink()
        if 'list_items' in self.unavailable_datasets:
            legacy_lists_dir = output_root / 'lists'
            if legacy_lists_dir.is_dir() and not legacy_lists_dir.is_symlink():
                for artifact in legacy_lists_dir.iterdir():
                    if artifact.name.casefold().endswith('.csv') and (
                        artifact.is_file() or artifact.is_symlink()
                    ):
                        artifact.unlink()

    def _save_enriched_ratings(self) -> int:
        """Enriches and saves the ratings file, returning the count of rated films."""
        if 'films' not in self.completed_datasets:
            return 0
        diary_lookup = {f"{e['title']}_{e['year'] or 'no_year'}": e for e in self.diary_entries if e['title']}
        review_lookup = {f"{r['title']}_{r['year'] or 'no_year'}": r for r in self.reviews_data if r['title']}
        
        all_ratings = []
        for film in self.films_data:
            if not film['title']:
                continue

            key = f"{film['title']}_{film['year'] or 'no_year'}"
            rating_entry = {'Name': film['title'], 'Year': film['year'] or '', 'Rating': film['rating'] or ''}

            diary_entry = diary_lookup.get(key)
            if diary_entry and diary_entry['rating'] and not rating_entry['Rating']:
                rating_entry['Rating'] = diary_entry['rating']

            review_entry = review_lookup.get(key)
            if review_entry and review_entry['rating'] and not rating_entry['Rating']:
                rating_entry['Rating'] = review_entry['rating']

            if rating_entry['Rating'] and str(rating_entry['Rating']).strip():
                all_ratings.append(rating_entry)
        
        self._write_csv("ratings.csv", all_ratings, ['Name', 'Year', 'Rating'])
        return len(all_ratings)

    def _build_like_rows(self) -> List[Dict]:
        """Build one stable-identity row per liked film from complete source surfaces."""
        all_likes = []
        seen_likes = set()

        def add_like(item: Dict, watched_date: str = '') -> None:
            like_key = (
                item.get('film_id')
                or item.get('slug')
                or f"{item.get('title', '')}_{item.get('year') or 'no_year'}"
            )
            if not item.get('title') or like_key in seen_likes:
                return
            all_likes.append({
                'Name': item.get('title', ''),
                'Year': item.get('year') or '',
                'Date': watched_date,
                'Is_Liked': 'Yes',
                'Film_ID': item.get('film_id', ''),
                'Slug': item.get('slug', ''),
                'Film_URL': item.get('film_url', ''),
                'Poster_URL': item.get('poster_url', ''),
            })
            seen_likes.add(like_key)

        for film in self.films_data:
            if film.get('is_liked', False):
                add_like(film)

        for entry in self.diary_entries:
            if entry.get('is_liked', False):
                add_like(entry, entry.get('watch_date', ''))

        return all_likes

    def _save_likes(self) -> int:
        """Saves liked films and returns the authoritative unique-film count."""
        if 'likes' not in self.completed_datasets:
            return 0
        all_likes = self._build_like_rows()
        self._write_csv(
            "likes.csv",
            all_likes,
            ['Name', 'Year', 'Date', 'Is_Liked', 'Film_ID', 'Slug', 'Film_URL', 'Poster_URL'],
        )
        return len(all_likes)

    def _save_comprehensive_films(self):
        """Saves the comprehensive film data."""
        if 'films' not in self.completed_datasets:
            return
        fieldnames = [
            'Title', 'Year', 'Rating', 'Film_ID', 'Slug', 'Poster_URL',
            'Film_URL', 'Has_Review', 'Is_Liked', 'Movie_ID'
        ]
        data = [{
            'Title': film.get('title', ''), 'Year': film.get('year', ''), 'Rating': film.get('rating', ''),
            'Film_ID': film.get('film_id', ''), 'Slug': film.get('slug', ''),
            'Poster_URL': film.get('poster_url', ''), 'Film_URL': film.get('film_url', ''),
            'Has_Review': 'Yes' if film.get('has_review') else 'No',
            'Is_Liked': 'Yes' if film.get('is_liked') else 'No',
            'Movie_ID': film.get('movie_id', '')
        } for film in self.films_data]
        self._write_csv("films_comprehensive.csv", data, fieldnames)

    def save_all_data(self):
        """Save all scraped data to CSV files in an organized structure."""
        print(f"💾 Saving all data to {self.output_dir}...")
        
        self._save_profile_info()
        self._save_diary_entries()
        self._save_reviews()
        self._save_watchlist()
        self._save_custom_lists()
        self._save_list_items()
        self._save_favorites()
        rated_films_count = self._save_enriched_ratings()
        liked_films_count = self._save_likes()
        self._save_comprehensive_films()

        # A retained output directory may contain a CSV from an earlier public
        # sync even when that surface is private/unavailable now. Remove only
        # scraper-owned files for unavailable surfaces after all current data
        # files are written; unrelated files are untouched.
        self._remove_stale_unavailable_files()

        counts = {
            'films': len(self.films_data),
            'diary': len(self.diary_entries),
            'likes': liked_films_count,
            'reviews': len(self.reviews_data),
            'watchlist': len(self.watchlist_data),
            'lists': len(self.lists_data),
            'list_items': len(self.list_items_data),
            'favorites': len(self.profile_info.favorite_films),
        }
        for dataset_name in self.unavailable_datasets:
            counts.pop(dataset_name, None)

        manifest = {
            'schema_version': 2,
            'username': self.username,
            'source_kind': 'full_html_upload',
            'requested_datasets': sorted(self.requested_datasets),
            'completed_datasets': sorted(self.completed_datasets),
            'unavailable_datasets': dict(sorted(self.unavailable_datasets.items())),
            'counts': counts,
            'completed_at': datetime.now().astimezone().isoformat(),
        }
        with open(os.path.join(self.output_dir, 'manifest.json'), 'w', encoding='utf-8') as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
        
        print(f"✅ All data saved to {self.output_dir}/")
        print(f"   - Profile info, Diary, Reviews, Watchlist, Lists, Ratings, Likes, and Comprehensive films.")
        print(f"📊 Data Summary:")
        print(f"   - Total films discovered: {len(self.films_data)}")
        print(f"   - Films with ratings: {rated_films_count}")
        print(f"   - Diary entries: {len(self.diary_entries)}")
        print(f"   - Reviews: {len(self.reviews_data)}")
        print(f"   - List memberships: {len(self.list_items_data)}")
    
    def scrape_all(self):
        """Main method to scrape all available data."""
        print(f"🎬 Starting comprehensive scrape for {self.username}")
        print("=" * 50)
        
        self.requested_datasets = {
            'profile', 'favorites', 'films', 'diary', 'likes', 'reviews',
            'watchlist', 'lists', 'list_items'
        }

        # Scrape all sections
        self.scrape_profile_info()
        self.scrape_all_films()  # Add this line to scrape films
        self.scrape_diary_entries()
        self.scrape_reviews()
        self.scrape_watchlist()
        self.scrape_custom_lists()

        # These source-of-truth counts are only known after their complete surfaces
        # have passed pagination and parse validation.
        self.profile_info.total_films = len(self.films_data)
        self.profile_info.total_reviews = len(self.reviews_data)
        self.profile_info.total_lists = len(self.lists_data)
        self._finish_dataset('likes')

        accounted_datasets = self.completed_datasets | set(self.unavailable_datasets)
        missing_datasets = self.requested_datasets - accounted_datasets
        if missing_datasets:
            raise ScrapeValidationError(
                f"Full scrape incomplete; missing datasets: {', '.join(sorted(missing_datasets))}"
            )
        
        # Save all data
        self.save_all_data()
        
        print("=" * 50)
        print(f"🎉 Comprehensive scrape completed for {self.username}!")
        return {
            'profile': asdict(self.profile_info),
            'diary_entries': self.diary_entries,
            'reviews': self.reviews_data,
            'watchlist': self.watchlist_data,
            'lists': self.lists_data,
            'list_items': self.list_items_data,
        }
        
    def convert_stars_to_rating(self, stars_text: str) -> Optional[float]:
        """Convert star rating text to decimal value."""
        if not stars_text:
            return None
            
        # Count full stars and half stars
        full_stars = stars_text.count('★')
        half_stars = stars_text.count('½')
        
        rating = full_stars + (half_stars * 0.5)
        return rating if rating > 0 else None
    


def validate_username(username: str) -> bool:
    """Validate that the username is reasonable."""
    if not username:
        return False
    
    # Basic validation - letterboxd usernames are alphanumeric with some special chars
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', username):
        return False
        
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Enhanced Letterboxd Profile Scraper - Extract comprehensive profile data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python letterboxd_scraper.py username
  python letterboxd_scraper.py username -o username_data
  python letterboxd_scraper.py username --debug
  
Features:
  - Complete profile information and statistics
  - All rated films with enhanced metadata
  - Full diary entries with watch dates
  - Complete reviews with text content
  - Watchlist data
  - Custom lists information
  - Organized CSV export structure
        """
    )
    
    parser.add_argument('username', 
                       help='Letterboxd username (e.g., "username" for https://letterboxd.com/username/)')
    parser.add_argument('-o', '--output', 
                       default=None,
                       help='Output directory name (default: username_data)')
    parser.add_argument('--debug', 
                       action='store_true',
                       help='Enable debug output to see HTML structure')
    parser.add_argument('--profile-only', 
                       action='store_true',
                       help='Scrape only basic profile info (faster)')
    parser.add_argument('--no-reviews', 
                       action='store_true',
                       help='Skip scraping reviews (faster)')
    
    args = parser.parse_args()
    
    # Validate username
    if not validate_username(args.username):
        print("Error: Please provide a valid Letterboxd username")
        print("Username should contain only letters, numbers, underscores, and hyphens")
        print("Example: python letterboxd_scraper.py username")
        sys.exit(1)
    
    # Create and run enhanced scraper
    scraper = EnhancedLetterboxdScraper(args.username, args.output, args.debug)
    
    try:
        if args.profile_only:
            print("🎬 Running profile-only scrape...")
            scraper.scrape_profile_info()
            scraper.save_all_data()
        else:
            print("🎬 Running comprehensive scrape...")
            scraper.scrape_all()
            
    except KeyboardInterrupt:
        print("\nScraping interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
