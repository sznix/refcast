"""Tests for refcast.router.classify_scope_shift — table from spec §3.5."""

from refcast.router import classify_scope_shift


def test_gemini_to_gemini_with_corpus_same():
    # Row 1: gemini_fs | gemini_fs | same corpus → same
    assert (
        classify_scope_shift(
            primary="gemini_fs",
            served="gemini_fs",
            primary_corpus_id="cor_x",
            served_corpus_id="cor_x",
        )
        == "same"
    )


def test_gemini_to_exa_with_corpus_broader():
    # Row 2: gemini_fs | exa | corpus_id present → broader
    assert (
        classify_scope_shift(
            primary="gemini_fs",
            served="exa",
            primary_corpus_id="cor_x",
            served_corpus_id=None,
        )
        == "broader"
    )


def test_gemini_to_exa_no_corpus_same():
    # Row 3: gemini_fs | exa | no corpus → same
    assert (
        classify_scope_shift(
            primary="gemini_fs",
            served="exa",
            primary_corpus_id=None,
            served_corpus_id=None,
        )
        == "same"
    )


def test_exa_to_gemini_with_corpus_different():
    # Row 4: exa | gemini_fs | corpus_id present → different
    assert (
        classify_scope_shift(
            primary="exa",
            served="gemini_fs",
            primary_corpus_id=None,
            served_corpus_id="cor_x",
        )
        == "different"
    )


def test_exa_to_exa_same():
    # Row 5: exa | exa | any → same
    assert (
        classify_scope_shift(
            primary="exa",
            served="exa",
            primary_corpus_id=None,
            served_corpus_id=None,
        )
        == "same"
    )


def test_same_backend_different_corpora_different():
    # Row 6: any | any | different corpora → different (the edge case)
    assert (
        classify_scope_shift(
            primary="gemini_fs",
            served="gemini_fs",
            primary_corpus_id="cor_A",
            served_corpus_id="cor_B",
        )
        == "different"
    )


def test_no_fallback_returns_none():
    # Row 7: no fallback triggered → none
    assert (
        classify_scope_shift(
            primary="gemini_fs",
            served="gemini_fs",
            primary_corpus_id="cor_x",
            served_corpus_id="cor_x",
            fell_back=False,
        )
        == "none"
    )
