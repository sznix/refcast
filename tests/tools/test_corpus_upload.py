"""Tests for corpus.upload MCP tool."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from refcast.backends.base import BackendError
from refcast.models import RecoveryEnum
from refcast.tools.corpus_upload import register


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
async def test_corpus_upload_success(tmp_path: Any) -> None:
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-test")
    g = MagicMock()
    g.upload_files = AsyncMock(
        return_value={
            "corpus_id": "cor_abc",
            "operation_id": "op_xyz",
            "status": "indexing",
            "file_count": 1,
            "started_at": "2026-04-15T13:00:00Z",
        }
    )
    mcp, captured = _mock_mcp()
    register(mcp, {"gemini_fs": g})
    fn = captured["corpus.upload"]
    result = await fn([str(f)])
    assert result["corpus_id"] == "cor_abc"
    assert result["status"] == "indexing"
    g.upload_files.assert_awaited_once_with([str(f)])


@pytest.mark.asyncio
async def test_corpus_upload_no_gemini_returns_error() -> None:
    mcp, captured = _mock_mcp()
    register(mcp, {})
    fn = captured["corpus.upload"]
    result = await fn(["/tmp/x.pdf"])
    assert "error" in result
    assert "not registered" in result["error"]["message"]
    assert result["error"]["code"] == RecoveryEnum.BACKEND_UNAVAILABLE.value


@pytest.mark.asyncio
async def test_corpus_upload_backend_error_mapped() -> None:
    g = MagicMock()
    g.upload_files = AsyncMock(
        side_effect=BackendError(
            RecoveryEnum.UNSUPPORTED_FORMAT,
            "File not found: /tmp/x.pdf",
            backend="gemini_fs",
            recovery_action="user_action",
        )
    )
    mcp, captured = _mock_mcp()
    register(mcp, {"gemini_fs": g})
    fn = captured["corpus.upload"]
    result = await fn(["/tmp/x.pdf"])
    assert result["error"]["code"] == RecoveryEnum.UNSUPPORTED_FORMAT.value
    assert result["error"]["recovery_action"] == "user_action"
    assert result["error"]["backend"] == "gemini_fs"
