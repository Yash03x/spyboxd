"""What the credits summary is allowed to drop, and what it must not.

`movie_enrichments.credits_summary` exists to stop the panels loading a 22KB
TMDB document per film to read three fields out of it. That is only safe while
the summary answers every question the document answered, so these tests are
about equivalence rather than about the saving.

The bug this guards against is real and was caught by measurement rather than
by reading: the first version of the summary stored cast names in billing
order and dropped `order`, which silently billed a sixth actor on films whose
`order` values skip a number.
"""
from __future__ import annotations

from services.profile_stats import _actor_values, _crew_values, _director_genders, _director_values
from services.tmdb_enrichment import SUMMARY_CAST_LIMIT, summarize_credits


def _document() -> dict:
    """A credits payload shaped like TMDB's, including the parts nothing reads."""

    return {
        "cast": [
            {"name": "First Billed", "order": 0, "character": "A", "profile_path": "/a.jpg",
             "credit_id": "c1", "popularity": 31.2, "known_for_department": "Acting"},
            {"name": "Second Billed", "order": 1, "character": "B", "profile_path": "/b.jpg"},
            # TMDB genuinely skips order values; 2, 3 and 4 are absent here.
            {"name": "Sixth Billed", "order": 5, "character": "C"},
            {"name": "Ninth Billed", "order": 9, "character": "D"},
        ],
        "crew": [
            {"name": "The Director", "job": "Director", "gender": 1, "profile_path": "/d.jpg",
             "credit_id": "c9", "department": "Directing"},
            {"name": "The Editor", "job": "Editor", "gender": 2, "credit_id": "c8"},
            {"name": "A Gaffer", "job": "Gaffer", "gender": 0},
        ],
    }


def test_the_summary_answers_every_question_the_document_answered() -> None:
    document = _document()
    summary = summarize_credits(document)

    for reader, label in (
        (_director_values, "directors"),
        (lambda c: _crew_values(c, "Editor"), "editors"),
        (_actor_values, "top-billed cast"),
        (_director_genders, "director genders"),
    ):
        from_document = reader(document)
        from_summary = reader(summary)
        assert from_document == from_summary, f"{label} differ between document and summary"


def test_billing_order_is_carried_rather_than_inferred_from_position() -> None:
    """The defect that measurement caught.

    "The first five entries" and "order below five" are different sets when
    TMDB skips a number, and storing names alone left the reader no way to
    tell them apart -- so it billed an actor the full document excluded.
    """

    summary = summarize_credits(_document())

    assert [entry["order"] for entry in summary["cast"]] == [0, 1, 5]
    # Sixth Billed carries order 5, which is outside the top five, so it must
    # not appear even though it is the third entry in the list.
    assert [value.label for value in _actor_values(summary)] == ["First Billed", "Second Billed"]


def test_cast_beyond_the_summary_limit_is_dropped() -> None:
    summary = summarize_credits(_document())

    assert all(entry["order"] < SUMMARY_CAST_LIMIT for entry in summary["cast"])
    assert "Ninth Billed" not in {entry["name"] for entry in summary["cast"]}


def test_crew_is_kept_whole_rather_than_filtered_to_todays_job_titles() -> None:
    """A job whitelist would return nothing the first time a panel asked for a
    title nobody had listed. The per-person fields are what cost, not the rows.
    """

    summary = summarize_credits(_document())

    assert {member["job"] for member in summary["crew"]} == {"Director", "Editor", "Gaffer"}
    assert set(summary["crew"][0]) == {"name", "job", "gender"}


def test_a_missing_or_malformed_document_summarises_to_an_empty_one() -> None:
    for value in (None, {}, [], "not credits", {"cast": None, "crew": "no"}):
        assert summarize_credits(value) == {"crew": [], "cast": []}


def test_a_crew_or_cast_entry_without_a_name_is_dropped() -> None:
    summary = summarize_credits(
        {"crew": [{"job": "Director"}, {"name": "", "job": "Editor"}], "cast": [{"order": 0}]}
    )

    assert summary == {"crew": [], "cast": []}


def test_the_summary_is_substantially_smaller_than_the_document() -> None:
    """The whole reason it exists. Measured at 83% on the real library."""

    import json

    document = _document()
    assert len(json.dumps(summarize_credits(document))) < len(json.dumps(document))
