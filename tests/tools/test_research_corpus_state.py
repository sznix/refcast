"""Tests for research tool corpus-state coverage: EMPTY/INDEXING/PARTIAL_INDEX."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

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


def _ok_result(backend_id: str) -> dict[str, Any]:
    return {
        "answer": "ok",
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
async def test_research_empty_corpus_returns_error() -> None:
    gemini = _mock_backend("gemini_fs", frozenset({"search", "upload", "cite"}))
    gemini.poll_status = AsyncMock(
        return_value={
            "corpus_id": "cor_empty",
            "indexed": False,
            "file_count": 0,
            "indexed_file_count": 0,
            "progress": 0.0,
            "warnings": [],
            "last_checked_at": "2026-04-15T13:00:00Z",
        }
    )
    gemini.execute = AsyncMock(return_value=_ok_result("gemini_fs"))

    mcp, captured = _mock_mcp()
    register(mcp, {"gemini_fs": gemini})
    fn = captured["research"]
    result = await fn("anything", "cor_empty", None)

    assert "error" in result
    assert result["error"]["code"] == RecoveryEnum.EMPTY_CORPUS.value
    gemini.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_research_indexing_in_progress_returns_error() -> None:
    gemini = _mock_backend("gemini_fs", frozenset({"search", "upload", "cite"}))
    gemini.poll_status = AsyncMock(
        return_value={
            "corpus_id": "cor_idx",
            "indexed": False,
            "file_count": 5,
            "indexed_file_count": 0,
            "progress": 0.0,
            "warnings": [],
            "last_checked_at": "2026-04-15T13:00:00Z",
        }
    )
    gemini.execute = AsyncMock(return_value=_ok_result("gemini_fs"))

    mcp, captured = _mock_mcp()
    register(mcp, {"gemini_fs": gemini})
    fn = captured["research"]
    result = await fn("anything", "cor_idx", None)

    assert "error" in result
    assert result["error"]["code"] == RecoveryEnum.INDEXING_IN_PROGRESS.value
    assert result["error"]["recovery_action"] == "retry"
    gemini.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_research_partial_index_proceeds_with_warning() -> None:
    gemini = _mock_backend("gemini_fs", frozenset({"search", "upload", "cite"}))
    gemini.poll_status = AsyncMock(
        return_value={
            "corpus_id": "cor_part",
            "indexed": False,
            "file_count": 5,
            "indexed_file_count": 2,
            "progress": 0.4,
            "warnings": [],
            "last_checked_at": "2026-04-15T13:00:00Z",
        }
    )
    gemini.execute = AsyncMock(return_value=_ok_result("gemini_fs"))

    mcp, captured = _mock_mcp()
    register(mcp, {"gemini_fs": gemini})
    fn = captured["research"]
    result = await fn("anything", "cor_part", None)

    assert "error" not in result or result.get("error") is None
    assert result["backend_used"] == "gemini_fs"
    codes = [w.get("code") for w in result.get("warnings", [])]
    assert RecoveryEnum.PARTIAL_INDEX in codes
    gemini.execute.assert_awaited_once()
