"""Tests for corpus.delete MCP tool."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from refcast.backends.base import BackendError
from refcast.models import RecoveryEnum
from refcast.tools.corpus_delete import register


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
async def test_corpus_delete_success() -> None:
    g = MagicMock()
    g.delete_corpus = AsyncMock(
        return_value={
            "corpus_id": "cor_abc",
            "deleted": True,
            "files_removed": 2,
        }
    )
    mcp, captured = _mock_mcp()
    register(mcp, {"gemini_fs": g})
    fn = captured["corpus.delete"]
    result = await fn("cor_abc")
    assert result["deleted"] is True
    assert result["files_removed"] == 2
    g.delete_corpus.assert_awaited_once_with("cor_abc")


@pytest.mark.asyncio
async def test_corpus_delete_not_found() -> None:
    g = MagicMock()
    g.delete_corpus = AsyncMock(
        side_effect=BackendError(
            RecoveryEnum.CORPUS_NOT_FOUND,
            "Unknown corpus: cor_missing",
            backend="gemini_fs",
            recovery_action="user_action",
        )
    )
    mcp, captured = _mock_mcp()
    register(mcp, {"gemini_fs": g})
    fn = captured["corpus.delete"]
    result = await fn("cor_missing")
    assert result["error"]["code"] == RecoveryEnum.CORPUS_NOT_FOUND.value


@pytest.mark.asyncio
async def test_corpus_delete_no_gemini_returns_error() -> None:
    mcp, captured = _mock_mcp()
    register(mcp, {})
    fn = captured["corpus.delete"]
    result = await fn("cor_abc")
    assert "error" in result
    assert "not registered" in result["error"]["message"]
