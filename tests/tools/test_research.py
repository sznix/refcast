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
