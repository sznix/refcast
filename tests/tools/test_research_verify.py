"""Tests for the research.verify MCP tool — pure offline EvidencePack verification."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from refcast.evidence import build_evidence_pack
from refcast.tools.research_verify import register


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


def _valid_pack() -> dict[str, Any]:
    result = {
        "answer": "a",
        "citations": [
            {
                "text": "cite text",
                "source_url": "https://example.com",
                "author": None,
                "date": None,
                "confidence": 0.9,
                "backend_used": "exa",
                "raw": {},
            }
        ],
        "backend_used": "exa",
        "latency_ms": 100,
        "cost_cents": 0.7,
        "fallback_scope": "none",
        "warnings": [],
        "error": None,
    }
    return build_evidence_pack(result=result, query="q", backends=[{"id": "exa"}])


@pytest.mark.asyncio
async def test_verify_tool_valid_pack() -> None:
    mcp, captured = _mock_mcp()
    register(mcp)
    fn = captured["research.verify"]
    pack = _valid_pack()

    result = await fn(pack)

    assert result["valid"] is True
    assert result["errors"] == []
    assert result["transcript_cid"] == pack["transcript_cid"]


@pytest.mark.asyncio
async def test_verify_tool_tampered_pack() -> None:
    mcp, captured = _mock_mcp()
    register(mcp)
    fn = captured["research.verify"]
    pack = _valid_pack()
    pack["query"] = "TAMPERED"

    result = await fn(pack)

    assert result["valid"] is False
    assert len(result["errors"]) >= 1


@pytest.mark.asyncio
async def test_verify_tool_empty_dict() -> None:
    mcp, captured = _mock_mcp()
    register(mcp)
    fn = captured["research.verify"]

    result = await fn({})

    assert result["valid"] is False
    assert len(result["errors"]) >= 1
    assert result["transcript_cid"] is None


@pytest.mark.asyncio
async def test_verify_tool_round_trip_through_json() -> None:
    """Realistic: pack was serialized, shared, loaded, verified."""
    mcp, captured = _mock_mcp()
    register(mcp)
    fn = captured["research.verify"]

    pack = _valid_pack()
    restored = json.loads(json.dumps(pack))

    result = await fn(restored)
    assert result["valid"] is True
