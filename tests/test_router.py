"""Tests for refcast.router.classify_scope_shift — table from spec §3.5."""

from unittest.mock import MagicMock

from refcast.router import classify_scope_shift, select_backends


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


# --- select_backends tests ---


def _mk(id, caps):
    m = MagicMock()
    m.id = id
    m.capabilities = frozenset(caps)
    return m


def test_select_backends_corpus_first():
    g = _mk("gemini_fs", {"search", "upload", "cite"})
    e = _mk("exa", {"search", "cite"})
    chosen = select_backends(
        corpus_id="cor_x", constraints=None, registered={"gemini_fs": g, "exa": e}
    )
    assert [b.id for b in chosen] == ["gemini_fs"]
    # Exa is filtered because it lacks "upload" -> cannot serve a corpus query


def test_select_backends_no_corpus_web_only():
    g = _mk("gemini_fs", {"search", "upload", "cite"})
    e = _mk("exa", {"search", "cite"})
    chosen = select_backends(
        corpus_id=None, constraints=None, registered={"gemini_fs": g, "exa": e}
    )
    assert [b.id for b in chosen] == ["exa"]


def test_select_backends_preferred_overrides_default():
    g = _mk("gemini_fs", {"search", "upload", "cite"})
    e = _mk("exa", {"search", "cite"})
    chosen = select_backends(
        corpus_id=None,
        constraints={"preferred_backend": "gemini_fs"},
        registered={"gemini_fs": g, "exa": e},
    )
    # gemini_fs first by preference, exa next as fallback
    assert [b.id for b in chosen] == ["gemini_fs", "exa"]


def test_select_backends_skips_unregistered():
    e = _mk("exa", {"search", "cite"})
    chosen = select_backends(corpus_id=None, constraints=None, registered={"exa": e})
    assert [b.id for b in chosen] == ["exa"]


def test_select_backends_empty_registered_returns_empty():
    chosen = select_backends(corpus_id=None, constraints=None, registered={})
    assert chosen == []


def test_select_backends_corpus_with_only_exa_returns_empty():
    """Exa cannot serve corpus queries - no upload capability."""
    e = _mk("exa", {"search", "cite"})
    chosen = select_backends(corpus_id="cor_x", constraints=None, registered={"exa": e})
    assert chosen == []
