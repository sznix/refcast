"""Tests for corpus.status MCP tool."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from refcast.backends.base import BackendError
from refcast.models import RecoveryEnum
from refcast.tools.corpus_status import register


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
async def test_corpus_status_success() -> None:
    g = MagicMock()
    g.poll_status = AsyncMock(
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
    mcp, captured = _mock_mcp()
    register(mcp, {"gemini_fs": g})
    fn = captured["corpus.status"]
    result = await fn("cor_abc")
    assert result["indexed"] is True
    assert result["progress"] == 1.0
    g.poll_status.assert_awaited_once_with("cor_abc")


@pytest.mark.asyncio
async def test_corpus_status_not_found() -> None:
    g = MagicMock()
    g.poll_status = AsyncMock(
        side_effect=BackendError(
            RecoveryEnum.CORPUS_NOT_FOUND,
            "Unknown corpus: cor_missing",
            backend="gemini_fs",
            recovery_action="user_action",
        )
    )
    mcp, captured = _mock_mcp()
    register(mcp, {"gemini_fs": g})
    fn = captured["corpus.status"]
    result = await fn("cor_missing")
    assert result["error"]["code"] == RecoveryEnum.CORPUS_NOT_FOUND.value
    assert result["error"]["recovery_action"] == "user_action"


@pytest.mark.asyncio
async def test_corpus_status_no_gemini_returns_error() -> None:
    mcp, captured = _mock_mcp()
    register(mcp, {})
    fn = captured["corpus.status"]
    result = await fn("cor_abc")
    assert "error" in result
    assert "not registered" in result["error"]["message"]
