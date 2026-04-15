"""Tests for research MCP tool — happy path + serial fallback."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

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
