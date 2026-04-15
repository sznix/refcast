"""Tests for corpus.list MCP tool."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from refcast.tools.corpus_list import register


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


@pytest.mark.asyncio
async def test_corpus_list_empty() -> None:
    g = MagicMock()
    g.list_corpora = AsyncMock(return_value=[])
    mcp, captured = _mock_mcp()
    register(mcp, {"gemini_fs": g})
    fn = captured["corpus.list"]
    result = await fn()
    assert result == {"corpora": []}


@pytest.mark.asyncio
async def test_corpus_list_populated() -> None:
    summaries = [
        {
            "corpus_id": "cor_a",
            "name": None,
            "file_count": 2,
            "indexed_file_count": 2,
            "total_bytes": 1024,
            "created_at": "2026-04-15T12:00:00Z",
            "backend": "gemini_fs",
        },
        {
            "corpus_id": "cor_b",
            "name": "second",
            "file_count": 1,
            "indexed_file_count": 0,
            "total_bytes": 512,
            "created_at": "2026-04-15T13:00:00Z",
            "backend": "gemini_fs",
        },
    ]
    g = MagicMock()
    g.list_corpora = AsyncMock(return_value=summaries)
    mcp, captured = _mock_mcp()
    register(mcp, {"gemini_fs": g})
    fn = captured["corpus.list"]
    result = await fn()
    assert result["corpora"] == summaries
    assert len(result["corpora"]) == 2


@pytest.mark.asyncio
async def test_corpus_list_no_gemini_returns_error() -> None:
    mcp, captured = _mock_mcp()
    register(mcp, {})
    fn = captured["corpus.list"]
    result = await fn()
    assert "error" in result
    assert "not registered" in result["error"]["message"]
