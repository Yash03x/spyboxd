from types import SimpleNamespace

from database.models import Movie, MovieEnrichment, Profile
from services.content_traits import catalogue_labels, film_themes, microgenres
from services.insights import InsightsService


def test_categories_are_evidenced_conjunctions_with_no_duplicate_or_production_tags():
    keywords = [{'name': 'time travel'}, {'name': 'Time Travel'}, {'name': 'aftercreditsstinger'}, None]
    assert film_themes(keywords) == ['time travel']
    assert microgenres([{'name': 'Science Fiction'}, {'name': 'Science Fiction'}], film_themes(keywords)) == ['Science Fiction · time travel']
    assert microgenres(['Drama'], ['drama']) == []
    assert catalogue_labels('time travel') == []
    assert catalogue_labels([{}, False, {'name': 'x' * 101}]) == []


def test_group_categories_preserve_viewers_distinct_films_and_unrated_samples(monkeypatch):
    service = InsightsService(None)
    profiles = [Profile(id=1, username='alpha'), Profile(id=2, username='bravo')]
    one = Movie(id=1, title='One', release_year=2020)
    two = Movie(id=2, title='Two', release_year=2021)
    enrichment = MovieEnrichment(genres=[{'name': 'Science Fiction'}], keywords=[{'name': 'time travel'}, {'name': 'time travel'}])
    states = [SimpleNamespace(profile_id=pid, movie_id=movie.id, movie=movie, rating=rating, liked=False, enrichment=enrichment)
              for pid, movie, rating in [(1, one, 4.0), (2, one, None), (1, two, 2.0)]]
    monkeypatch.setattr(service, '_resolve_profiles', lambda *_a, **_k: profiles)
    monkeypatch.setattr(service, '_state_rows', lambda *_a, **_k: states)
    monkeypatch.setattr(service, '_event_rows', lambda *_a, **_k: [])
    monkeypatch.setattr(service, '_semantic_neighbors', lambda *_a, **_k: [])
    monkeypatch.setattr(service, '_feature_coverage', lambda *_a, **_k: {'status': 'ready', 'warnings': [], 'blockers': []})
    queried = []
    def states_for_content(*_args, **kwargs):
        queried.append(kwargs)
        return states
    monkeypatch.setattr(service, '_state_rows', states_for_content)
    monkeypatch.setattr(service, '_semantic_neighbors', lambda *_a: (_ for _ in ()).throw(AssertionError('Unrequested semantic neighbors must not run')))
    result = service.taste_dna(['alpha', 'bravo'], dimensions=['theme', 'microgenre'], limit=50, sort_by='watched', include_neighbors=False)
    assert queried == [{'analytical_enrichment': True, 'content_only': True}]
    trait = result['dimensions']['microgenre'][0]
    assert trait['label'] == 'Science Fiction · time travel'
    assert trait['sample_size'] == 3 and trait['unique_films'] == 2
    assert trait['average_rating'] == 3.0
    assert trait['per_profile'][1]['rated_sample_size'] == 0
    assert trait['top_movies'] == []  # Nobody pretends both people rated the film.
    assert [example['watched_by'] for example in trait['examples']] == [['alpha', 'bravo'], ['alpha']]
    assert result['trait_coverage']['microgenre'] == {'films': 2, 'total_films': 2}
