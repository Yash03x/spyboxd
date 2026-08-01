"""Export comment markup must reach clients as parsed plain text."""
from __future__ import annotations

from api.routes.member_archive import comment_plain_text


def test_comment_markup_is_reduced_to_text():
    assert comment_plain_text(
        'One interpretation on <a href="https://example.test">Reddit</a>.'
    ) == "One interpretation on Reddit."


def test_nested_tag_constructions_do_not_survive():
    # A single-pass regex strip leaves "<script>" behind here; a real
    # tokenizer does not.
    parsed = comment_plain_text('<scr<script>ipt>alert(1)</scr</script>ipt>')
    assert parsed is not None
    assert "<script" not in parsed.casefold()
    assert "<" not in parsed


def test_script_and_style_bodies_are_dropped():
    parsed = comment_plain_text("<script>alert(1)</script>Real text<style>b{}</style>")
    assert parsed == "Real text"


def test_entities_decode_and_whitespace_collapses():
    assert comment_plain_text("a &amp; b\n\n  c") == "a & b c"


def test_empty_and_missing_input():
    assert comment_plain_text(None) is None
    assert comment_plain_text("") is None
    assert comment_plain_text("<p></p>") is None
