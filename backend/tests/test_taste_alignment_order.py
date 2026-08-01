"""The taste-alignment panel must rank agreement, not one profile's ratings."""
from __future__ import annotations

from backend.services.insights import InsightsService


def _trait(label: str, scores, samples, *, sample_size=None):
    """A trait payload shaped like taste_dna builds it."""
    per_profile = [
        {"username": f"p{index}", "score": score, "sample_size": sample,
         "average_rating": score / 20}
        for index, (score, sample) in enumerate(zip(scores, samples))
    ]
    return {
        "label": label,
        "per_profile": per_profile,
        "sample_size": sample_size if sample_size is not None else sum(samples),
    }


def _order(traits):
    return [
        trait["label"]
        for trait in sorted(
            traits, key=lambda t: InsightsService._alignment_sort_key(t, 2)
        )
    ]


def test_one_sided_perfect_score_loses_to_genuine_agreement():
    # The reported bug: a director one profile rated 5.0 and the other never
    # watched was topping a panel titled "Where your tastes align".
    traits = [
        _trait("Only One Watched", [100.0, 0.0], [3, 0]),
        _trait("Both Love It", [84.0, 80.0], [9, 7]),
    ]
    assert _order(traits) == ["Both Love It", "Only One Watched"]


def test_closer_agreement_outranks_a_wider_split():
    traits = [
        _trait("Split", [96.0, 60.0], [5, 5]),
        _trait("Aligned", [82.0, 80.0], [5, 5]),
    ]
    assert _order(traits) == ["Aligned", "Split"]


def test_single_film_traits_rank_below_credible_ones():
    # One five-star film scores a perfect 100 — coverage noise, not taste.
    traits = [
        _trait("One Film Each", [100.0, 100.0], [1, 1]),
        _trait("Well Sampled", [76.0, 74.0], [12, 11]),
    ]
    assert _order(traits) == ["Well Sampled", "One Film Each"]


def test_shared_traits_always_precede_unshared_ones():
    traits = [
        _trait("Unshared High", [100.0, 0.0], [8, 0]),
        _trait("Shared Low", [52.0, 50.0], [4, 4]),
    ]
    assert _order(traits) == ["Shared Low", "Unshared High"]


def test_stronger_mutual_affinity_wins_between_equally_aligned_traits():
    traits = [
        _trait("Warm", [62.0, 60.0], [6, 6]),
        _trait("Hot", [92.0, 90.0], [6, 6]),
    ]
    assert _order(traits) == ["Hot", "Warm"]


def test_opinion_date_prefers_the_log_date_over_a_backdated_watch():
    """A 2015 watch logged in 2024 belongs to 2024 on a taste timeline.

    Letterboxd lets members backdate diary entries to the day they actually
    saw a film, so the rating on a backdated entry was formed years after the
    watch date it carries.
    """
    from datetime import date as _date
    from backend.services.insights import EventRow

    backdated = EventRow(
        id=1, profile_id=1, username="viewer", movie_id=1,
        watched_date=_date(2015, 6, 1), logged_date=_date(2024, 3, 9),
        rating=4.5, liked=False, rewatch=False, tags=[],
        source_kind="diary_csv", movie=None,
    )
    assert backdated.opinion_date == _date(2024, 3, 9)

    # Public HTML carries no log date, so the watch date is the only axis.
    scraped_only = EventRow(
        id=2, profile_id=1, username="viewer", movie_id=2,
        watched_date=_date(2015, 6, 1), logged_date=None,
        rating=4.5, liked=False, rewatch=False, tags=[],
        source_kind="diary_csv", movie=None,
    )
    assert scraped_only.opinion_date == _date(2015, 6, 1)
