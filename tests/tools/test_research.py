"""Tests for research MCP tool — happy path + serial fallback."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from refcast.backends.base import BackendError
from refcast.models import RecoveryEnum
from refcast.tools.research import register


def _mock_mcp() -> tuple[Any, dict[str, Any]]:
    mcp = MagicMock()
    captured: dict[str, Any] = {}

    def tool(name: str | None = None) -> Any:
        def deco(fn: Any) -> Any:
            captured[name or fn.__name__] = fn
            return fn

        return deco

    mcp.tool = tool
    return mcp, captured


def _mock_backend(backend_id: str, capabilities: frozenset[str]) -> Any:
    b = MagicMock()
    b.id = backend_id
    b.capabilities = capabilities
    return b


def _ok_result(backend_id: str, answer: str = "yes") -> dict[str, Any]:
    return {
        "answer": answer,
        "citations": [
            {
                "text": "snippet",
                "source_url": "https://example.com",
                "author": None,
                "date": None,
                "confidence": 0.9,
                "backend_used": backend_id,
                "raw": {},
            }
        ],
        "backend_used": backend_id,
        "latency_ms": 50,
        "cost_cents": 0.1,
        "fallback_scope": "none",
        "warnings": [],
        "error": None,
    }


@pytest.mark.asyncio
async def test_research_happy_path_gemini_wins() -> None:
    gemini = _mock_backend("gemini_fs", frozenset({"search", "upload", "cite"}))
    gemini.execute = AsyncMock(return_value=_ok_result("gemini_fs"))
    gemini.poll_status = AsyncMock(
        return_value={
            "corpus_id": "cor_abc",
            "indexed": True,
            "file_count": 3,
            "indexed_file_count": 3,
            "progress": 1.0,
            "warnings": [],
            "last_checked_at": "2026-04-15T13:00:00Z",
        }
    )
    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    exa.execute = AsyncMock(return_value=_ok_result("exa"))

    mcp, captured = _mock_mcp()
    register(mcp, {"gemini_fs": gemini, "exa": exa})
    fn = captured["research"]
    result = await fn("what is refcast?", "cor_abc", None)

    assert result["backend_used"] == "gemini_fs"
    assert result["fallback_scope"] == "none"
    assert result["error"] is None
    exa.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_research_fallback_gemini_fails_exa_wins() -> None:
    gemini = _mock_backend("gemini_fs", frozenset({"search", "upload", "cite"}))
    gemini.execute = AsyncMock(
        side_effect=BackendError(
            RecoveryEnum.BACKEND_UNAVAILABLE,
            "Gemini 503",
            backend="gemini_fs",
            recovery_action="fallback",
        )
    )
    gemini.poll_status = AsyncMock(
        return_value={
            "corpus_id": "cor_abc",
            "indexed": True,
            "file_count": 3,
            "indexed_file_count": 3,
            "progress": 1.0,
            "warnings": [],
            "last_checked_at": "2026-04-15T13:00:00Z",
        }
    )
    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    exa.execute = AsyncMock(return_value=_ok_result("exa"))

    mcp, captured = _mock_mcp()
    # With corpus_id, preferred_backend needed for exa fallback per router rules
    register(mcp, {"gemini_fs": gemini, "exa": exa})
    fn = captured["research"]
    result = await fn(
        "what is refcast?",
        "cor_abc",
        {"preferred_backend": "gemini_fs"},
    )

    assert result["backend_used"] == "exa"
    assert result["fallback_scope"] == "broader"
    assert len(result["warnings"]) >= 1
    # At least one warning should be from the gemini failure
    messages = [w.get("message", "") for w in result["warnings"]]
    assert any("Gemini 503" in m for m in messages)


@pytest.mark.asyncio
async def test_research_web_only_no_corpus() -> None:
    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    exa.execute = AsyncMock(return_value=_ok_result("exa"))

    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa})
    fn = captured["research"]
    result = await fn("current events", None, None)

    assert result["backend_used"] == "exa"
    assert result["fallback_scope"] == "none"


@pytest.mark.asyncio
async def test_research_applies_size_guard() -> None:
    """Result routed through enforce_response_size (integration smoke)."""
    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    # Build an oversized result — 100 citations × 500 bytes.
    oversize = _ok_result("exa", answer="a")
    oversize["citations"] = [
        {
            "text": "x" * 500,
            "source_url": f"https://example.com/{i}",
            "author": None,
            "date": None,
            "confidence": 0.9,
            "backend_used": "exa",
            "raw": {},
        }
        for i in range(100)
    ]
    exa.execute = AsyncMock(return_value=oversize)

    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa})
    fn = captured["research"]
    result = await fn("huge", None, None)

    assert result["answer"] == "a"
    assert len(result["citations"]) < 100
    # Truncation warning appended
    assert any(w.get("code") == RecoveryEnum.UNKNOWN for w in result["warnings"])


# --- Task 6: Synthesis in quick mode ---


@pytest.mark.asyncio
@patch("refcast.tools.research.synthesize")
@patch("refcast.tools.research.execute_research")
async def test_research_quick_synthesizes_answer(
    mock_execute: AsyncMock,
    mock_synth: AsyncMock,
) -> None:
    """Quick mode: synthesize replaces raw answer with [1][2] markers."""
    raw = _ok_result("exa", answer="raw answer")
    mock_execute.return_value = raw
    mock_synth.return_value = ("Synthesized [1] answer [2].", 0.05, 100)

    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa}, gemini_api_key="fake_key")
    fn = captured["research"]
    result = await fn("question", None, None)

    assert "[1]" in result["answer"]
    assert result["answer"] == "Synthesized [1] answer [2]."
    assert result["cost_cents"] == round(0.1 + 0.05, 4)
    assert result["latency_ms"] == 50 + 100
    mock_synth.assert_awaited_once()


@pytest.mark.asyncio
@patch("refcast.tools.research.synthesize")
@patch("refcast.tools.research.execute_research")
async def test_research_quick_synthesis_failure_uses_raw(
    mock_execute: AsyncMock,
    mock_synth: AsyncMock,
) -> None:
    """Quick mode: if synthesis fails, raw answer is kept + warning added."""
    raw = _ok_result("exa", answer="raw answer")
    mock_execute.return_value = raw
    mock_synth.return_value = (None, 0.0, 50)

    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa}, gemini_api_key="fake_key")
    fn = captured["research"]
    result = await fn("question", None, None)

    assert result["answer"] == "raw answer"
    messages = [w.get("message", "") for w in result["warnings"]]
    assert any("synthesis skipped" in m.lower() for m in messages)


@pytest.mark.asyncio
@patch("refcast.tools.research.execute_research")
async def test_research_no_api_key_skips_synthesis(
    mock_execute: AsyncMock,
) -> None:
    """No gemini_api_key: synthesis never runs, raw answer returned."""
    raw = _ok_result("exa", answer="raw answer")
    mock_execute.return_value = raw

    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa})  # no gemini_api_key
    fn = captured["research"]
    result = await fn("question", None, None)

    assert result["answer"] == "raw answer"


@pytest.mark.asyncio
@patch("refcast.tools.research.synthesize")
@patch("refcast.tools.research.execute_research")
async def test_research_quick_zero_citations_keeps_raw_answer(
    mock_execute: AsyncMock,
    mock_synth: AsyncMock,
) -> None:
    """Quick mode: when synthesis returns '' (0 citations), raw answer is preserved."""
    raw = _ok_result("exa", answer="Good answer")
    raw["citations"] = []
    mock_execute.return_value = raw
    mock_synth.return_value = ("", 0.0, 0)

    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa}, gemini_api_key="fake_key")
    fn = captured["research"]
    result = await fn("question", None, None)

    assert result["answer"] == "Good answer", (
        "synthesis returned '' for 0 citations — raw answer must not be overwritten"
    )
    assert result["cost_cents"] == 0.1  # synth cost NOT added (path not taken)
    assert result["latency_ms"] == 50  # synth latency NOT added


# --- Task 7: depth="deep" mode ---


def _ok_result_with_url(backend_id: str, answer: str, url: str) -> dict[str, Any]:
    return {
        "answer": answer,
        "citations": [
            {
                "text": f"snippet from {url}",
                "source_url": url,
                "author": None,
                "date": None,
                "confidence": 0.9,
                "backend_used": backend_id,
                "raw": {},
            }
        ],
        "backend_used": backend_id,
        "latency_ms": 50,
        "cost_cents": 0.1,
        "fallback_scope": "none",
        "warnings": [],
        "error": None,
    }


@pytest.mark.asyncio
@patch("refcast.tools.research.synthesize")
@patch("refcast.tools.research.execute_research")
@patch("refcast.tools.research.generate_perspectives")
async def test_research_deep_fires_multiple_queries(
    mock_perspectives: AsyncMock,
    mock_execute: AsyncMock,
    mock_synth: AsyncMock,
) -> None:
    """Deep mode: perspectives generate 3 sub-queries, each runs execute_research."""
    mock_perspectives.return_value = ["sq1", "sq2", "sq3"]
    mock_execute.side_effect = [
        _ok_result_with_url("exa", "a1", "https://a.com"),
        _ok_result_with_url("exa", "a2", "https://b.com"),
        _ok_result_with_url("exa", "a3", "https://c.com"),
    ]
    mock_synth.return_value = ("Deep [1] answer [2] [3].", 0.08, 200)

    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa}, gemini_api_key="fake_key")
    fn = captured["research"]
    result = await fn("original question", None, {"depth": "deep"})

    assert mock_execute.await_count == 3
    assert "[1]" in result["answer"]
    assert len(result["citations"]) == 3
    # Cost = 3 * 0.1 + 0.08 = 0.38
    assert result["cost_cents"] == round(3 * 0.1 + 0.08, 4)
    # Latency = 3 * 50 + 200 = 350
    assert result["latency_ms"] == 3 * 50 + 200
    # Synthesis called with ORIGINAL query, not sub-queries
    mock_synth.assert_awaited_once()
    synth_call_query = mock_synth.call_args[0][0]
    assert synth_call_query == "original question"


@pytest.mark.asyncio
@patch("refcast.tools.research.synthesize")
@patch("refcast.tools.research.execute_research")
@patch("refcast.tools.research.generate_perspectives")
async def test_research_deep_perspective_failure_degrades(
    mock_perspectives: AsyncMock,
    mock_execute: AsyncMock,
    mock_synth: AsyncMock,
) -> None:
    """Deep mode: perspective failure returns [original_query], so only 1 call."""
    mock_perspectives.return_value = ["original question"]
    mock_execute.return_value = _ok_result("exa", answer="raw")
    mock_synth.return_value = ("Synthesized.", 0.02, 50)

    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa}, gemini_api_key="fake_key")
    fn = captured["research"]
    result = await fn("original question", None, {"depth": "deep"})

    assert mock_execute.await_count == 1
    assert result["error"] is None


@pytest.mark.asyncio
@patch("refcast.tools.research.synthesize")
@patch("refcast.tools.research.execute_research")
async def test_research_deep_no_api_key_falls_back_to_quick(
    mock_execute: AsyncMock,
    mock_synth: AsyncMock,
) -> None:
    """No Gemini key with depth=deep: degrades to quick mode."""
    mock_execute.return_value = _ok_result("exa", answer="quick answer")

    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa})  # no gemini_api_key
    fn = captured["research"]
    result = await fn("question", None, {"depth": "deep"})

    # Should fall through to quick mode since no API key
    assert mock_execute.await_count == 1
    assert result["answer"] == "quick answer"
    mock_synth.assert_not_awaited()


@pytest.mark.asyncio
@patch("refcast.tools.research.synthesize")
@patch("refcast.tools.research.execute_research")
@patch("refcast.tools.research.generate_perspectives")
async def test_research_deep_merges_and_deduplicates(
    mock_perspectives: AsyncMock,
    mock_execute: AsyncMock,
    mock_synth: AsyncMock,
) -> None:
    """Deep mode: overlapping citations from 2 sub-results get deduplicated."""
    mock_perspectives.return_value = ["sq1", "sq2"]
    # Both sub-results have a citation from the same URL with same text prefix
    r1 = _ok_result_with_url("exa", "a1", "https://shared.com")
    r2 = _ok_result_with_url("exa", "a2", "https://shared.com")
    mock_execute.side_effect = [r1, r2]
    mock_synth.return_value = ("Merged [1].", 0.02, 50)

    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa}, gemini_api_key="fake_key")
    fn = captured["research"]
    result = await fn("question", None, {"depth": "deep"})

    # 2 sub-results had 1 citation each, but same URL + text[:100] => 1 merged
    assert len(result["citations"]) < 2


# --- BUG 2: Deep mode all-errors propagation ---


def _error_result(backend_id: str, error_code: str = "RATE_LIMITED") -> dict[str, Any]:
    return {
        "answer": "",
        "citations": [],
        "backend_used": backend_id,
        "latency_ms": 10,
        "cost_cents": 0.0,
        "fallback_scope": "none",
        "warnings": [],
        "error": {
            "code": error_code,
            "message": f"Simulated {error_code} error",
            "recovery_hint": "retry",
            "recovery_action": "retry",
            "fallback_used": False,
            "partial_results": False,
            "retry_after_ms": 30000,
            "backend": backend_id,
            "raw": {},
        },
    }


@pytest.mark.asyncio
@patch("refcast.tools.research.execute_research")
@patch("refcast.tools.research.generate_perspectives")
async def test_research_deep_all_sub_queries_errored_propagates_error(
    mock_perspectives: AsyncMock,
    mock_execute: AsyncMock,
) -> None:
    """Deep mode: when ALL sub-queries return errors, the error is propagated — not masked."""
    mock_perspectives.return_value = ["sq1", "sq2"]
    mock_execute.side_effect = [
        _error_result("exa", "RATE_LIMITED"),
        _error_result("exa", "RATE_LIMITED"),
    ]

    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa}, gemini_api_key="fake_key")
    fn = captured["research"]
    result = await fn("question", None, {"depth": "deep"})

    # Should propagate the real error, not silently return error=None
    assert result.get("error") is not None, (
        "Deep mode swallowed all sub-query errors — should have propagated the first error"
    )


# --- BUG 2 (round-2 audit): partial sub-query errors surfaced as warnings ---


@pytest.mark.asyncio
@patch("refcast.tools.research.synthesize")
@patch("refcast.tools.research.execute_research")
@patch("refcast.tools.research.generate_perspectives")
async def test_research_deep_partial_sub_query_error_becomes_warning(
    mock_perspectives: AsyncMock,
    mock_execute: AsyncMock,
    mock_synth: AsyncMock,
) -> None:
    """Deep mode: 1 success + 1 failure — failed sub-query error must appear in warnings."""
    mock_perspectives.return_value = ["sq1", "sq2"]
    mock_execute.side_effect = [
        _ok_result_with_url("exa", "good answer", "https://good.com"),
        _error_result("exa", "rate_limited"),
    ]
    mock_synth.return_value = ("Synthesized.", 0.02, 50)

    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa}, gemini_api_key="fake_key")
    fn = captured["research"]
    result = await fn("question", None, {"depth": "deep"})

    # Should succeed overall (one sub-query worked)
    assert result.get("error") is None
    # The failed sub-query error must appear as a warning
    warning_codes = [w.get("code") for w in result.get("warnings", [])]
    assert "rate_limited" in warning_codes, (
        f"Failed sub-query error not surfaced in warnings. Got: {warning_codes}"
    )


@pytest.mark.asyncio
@patch("refcast.tools.research.synthesize")
@patch("refcast.tools.research.execute_research")
@patch("refcast.tools.research.generate_perspectives")
async def test_research_deep_synthesis_failure_produces_warning(
    mock_perspectives: AsyncMock,
    mock_execute: AsyncMock,
    mock_synth: AsyncMock,
) -> None:
    """Deep mode: synthesis failure must append a warning (mirrors quick mode)."""
    mock_perspectives.return_value = ["sq1"]
    mock_execute.return_value = _ok_result_with_url("exa", "raw answer", "https://example.com")
    mock_synth.return_value = (None, 0.0, 50)

    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa}, gemini_api_key="fake_key")
    fn = captured["research"]
    result = await fn("question", None, {"depth": "deep"})

    assert result.get("error") is None
    messages = [w.get("message", "") for w in result.get("warnings", [])]
    assert any("deep-mode synthesis skipped" in m.lower() for m in messages), (
        f"Deep-mode synthesis failure not surfaced in warnings. Got: {messages}"
    )


# --- BUG 4 (audit): max_citations validation ---


@pytest.mark.asyncio
@patch("refcast.tools.research.execute_research")
async def test_research_negative_max_citations_uses_default(
    mock_execute: AsyncMock,
) -> None:
    """max_citations=-5 should be clamped to the sane default of 10."""
    raw = _ok_result("exa")
    mock_execute.return_value = raw

    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa})
    fn = captured["research"]
    result = await fn("question", None, {"max_citations": -5})

    assert result["error"] is None
    # The constraint passed to execute_research should have been clamped
    call_constraints = mock_execute.call_args[0][2]
    assert call_constraints["max_citations"] == 10


@pytest.mark.asyncio
@patch("refcast.tools.research.execute_research")
async def test_research_huge_max_citations_capped_at_50(
    mock_execute: AsyncMock,
) -> None:
    """max_citations=9999 should be capped at 50."""
    raw = _ok_result("exa")
    mock_execute.return_value = raw

    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa})
    fn = captured["research"]
    result = await fn("question", None, {"max_citations": 9999})

    assert result["error"] is None
    call_constraints = mock_execute.call_args[0][2]
    assert call_constraints["max_citations"] == 50


@pytest.mark.asyncio
@patch("refcast.tools.research.execute_research")
async def test_research_non_int_max_citations_uses_default(
    mock_execute: AsyncMock,
) -> None:
    """max_citations='abc' (non-int) should be replaced with sane default."""
    raw = _ok_result("exa")
    mock_execute.return_value = raw

    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa})
    fn = captured["research"]
    result = await fn("question", None, {"max_citations": "abc"})

    assert result["error"] is None
    call_constraints = mock_execute.call_args[0][2]
    assert call_constraints["max_citations"] == 10


# --- BUG 5 (audit): Unenforced constraints produce warnings ---


@pytest.mark.asyncio
@patch("refcast.tools.research.execute_research")
async def test_research_max_cost_cents_warns(
    mock_execute: AsyncMock,
) -> None:
    """Setting max_cost_cents should produce an 'unenforced' warning."""
    raw = _ok_result("exa")
    mock_execute.return_value = raw

    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa})
    fn = captured["research"]
    result = await fn("question", None, {"max_cost_cents": 1})

    messages = [w.get("message", "") for w in result.get("warnings", [])]
    assert any("max_cost_cents" in m and "not enforced" in m for m in messages)


@pytest.mark.asyncio
@patch("refcast.tools.research.execute_research")
async def test_research_date_after_warns(
    mock_execute: AsyncMock,
) -> None:
    """Setting date_after should produce an 'unenforced' warning."""
    raw = _ok_result("exa")
    mock_execute.return_value = raw

    exa = _mock_backend("exa", frozenset({"search", "cite"}))
    mcp, captured = _mock_mcp()
    register(mcp, {"exa": exa})
    fn = captured["research"]
    result = await fn("question", None, {"date_after": "2025-01-01"})

    messages = [w.get("message", "") for w in result.get("warnings", [])]
    assert any("date_after" in m and "not enforced" in m for m in messages)


# --- BUG 6 (audit): corpus preflight skipped when preferred_backend=exa ---


@pytest.mark.asyncio
@patch("refcast.tools.research.execute_research")
async def test_research_corpus_preflight_skipped_for_exa_preference(
    mock_execute: AsyncMock,
) -> None:
    """When preferred_backend='exa', corpus preflight should NOT run against Gemini."""
    raw = _ok_result("exa")
    mock_execute.return_value = raw

    gemini = _mock_backend("gemini_fs", frozenset({"search", "upload", "cite"}))
    gemini.poll_status = AsyncMock(side_effect=Exception("should not be called"))
    exa = _mock_backend("exa", frozenset({"search", "cite"}))

    mcp, captured = _mock_mcp()
    register(mcp, {"gemini_fs": gemini, "exa": exa})
    fn = captured["research"]
    result = await fn(
        "question",
        "cor_abc",
        {"preferred_backend": "exa"},
    )

    # Gemini's poll_status should NOT have been called
    gemini.poll_status.assert_not_awaited()
    assert result["error"] is None
