"""Tests for refcast.router.classify_scope_shift — table from spec §3.5."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from refcast.backends.base import BackendError
from refcast.models import RecoveryEnum
from refcast.router import classify_scope_shift, execute_research, select_backends


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


# --- execute_research tests ---


def _ok_result(backend_id, citations_count=1):
    return {
        "answer": f"answer from {backend_id}",
        "citations": [
            {
                "text": f"cite{i}",
                "source_url": f"http://{backend_id}/{i}",
                "author": None,
                "date": None,
                "confidence": None,
                "backend_used": backend_id,
                "raw": {},
            }
            for i in range(citations_count)
        ],
        "backend_used": backend_id,
        "latency_ms": 100,
        "cost_cents": 0.1,
        "fallback_scope": "none",
        "warnings": [],
        "error": None,
    }


def _backend(id, caps, exec_result=None, exec_error=None):
    m = MagicMock()
    m.id = id
    m.capabilities = frozenset(caps)
    if exec_error:
        m.execute = AsyncMock(side_effect=exec_error)
    else:
        m.execute = AsyncMock(return_value=exec_result)
    return m


@pytest.mark.asyncio
async def test_execute_research_primary_succeeds_no_fallback():
    g = _backend(
        "gemini_fs", {"search", "upload", "cite"}, exec_result=_ok_result("gemini_fs")
    )
    e = _backend("exa", {"search", "cite"}, exec_result=_ok_result("exa"))
    result = await execute_research(
        query="q",
        corpus_id="cor_x",
        constraints=None,
        registered={"gemini_fs": g, "exa": e},
    )
    assert result["backend_used"] == "gemini_fs"
    assert result["fallback_scope"] == "none"
    assert result["warnings"] == []
    assert result["error"] is None
    g.execute.assert_called_once()
    e.execute.assert_not_called()


@pytest.mark.asyncio
async def test_execute_research_primary_fails_fallback_to_secondary():
    g_err = BackendError(
        RecoveryEnum.RATE_LIMITED,
        "429",
        backend="gemini_fs",
        recovery_action="fallback",
        retry_after_ms=30000,
    )
    g = _backend("gemini_fs", {"search", "upload", "cite"}, exec_error=g_err)
    e = _backend("exa", {"search", "cite"}, exec_result=_ok_result("exa"))
    result = await execute_research(
        query="q",
        corpus_id="cor_x",
        constraints={"preferred_backend": "gemini_fs"},
        registered={"gemini_fs": g, "exa": e},
    )
    assert result["backend_used"] == "exa"
    assert result["fallback_scope"] == "broader"  # gemini_fs -> exa with corpus_id
    assert len(result["warnings"]) == 1
    assert result["warnings"][0]["code"] == RecoveryEnum.RATE_LIMITED
    assert result["error"] is None


@pytest.mark.asyncio
async def test_execute_research_user_action_blocks_fallback():
    """recovery_action='user_action' must NOT trigger fallback."""
    g_err = BackendError(
        RecoveryEnum.AUTH_INVALID,
        "bad key",
        backend="gemini_fs",
        recovery_action="user_action",
    )
    g = _backend("gemini_fs", {"search", "upload", "cite"}, exec_error=g_err)
    e = _backend("exa", {"search", "cite"}, exec_result=_ok_result("exa"))
    result = await execute_research(
        query="q",
        corpus_id="cor_x",
        constraints={"preferred_backend": "gemini_fs"},
        registered={"gemini_fs": g, "exa": e},
    )
    assert result["error"] is not None
    assert result["error"]["code"] == RecoveryEnum.AUTH_INVALID
    e.execute.assert_not_called()


@pytest.mark.asyncio
async def test_execute_research_all_backends_fail():
    g_err = BackendError(RecoveryEnum.BACKEND_UNAVAILABLE, "5xx", backend="gemini_fs")
    e_err = BackendError(RecoveryEnum.BACKEND_UNAVAILABLE, "5xx", backend="exa")
    g = _backend("gemini_fs", {"search", "upload", "cite"}, exec_error=g_err)
    e = _backend("exa", {"search", "cite"}, exec_error=e_err)
    result = await execute_research(
        query="q",
        corpus_id="cor_x",
        constraints={"preferred_backend": "gemini_fs"},
        registered={"gemini_fs": g, "exa": e},
    )
    assert result["error"] is not None
    assert result["error"]["code"] == RecoveryEnum.BACKEND_UNAVAILABLE
    assert len(result["warnings"]) == 1  # first failure recorded as warning, last is the error


@pytest.mark.asyncio
async def test_execute_research_no_backends_returns_error():
    result = await execute_research(
        query="q", corpus_id=None, constraints=None, registered={}
    )
    assert result["error"] is not None
    assert result["error"]["code"] == RecoveryEnum.BACKEND_UNAVAILABLE
    assert result["error"]["recovery_action"] == "user_action"
