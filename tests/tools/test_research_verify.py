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

    assert result["integrity_valid"] is True
    assert result["binding_verified"] is False  # v0.3: always False
    assert result["authenticity_verified"] is False  # v0.3: always False
    assert result["errors"] == []
    assert result["transcript_cid"] == pack["transcript_cid"]
    assert "scope_note" in result


@pytest.mark.asyncio
async def test_verify_tool_tampered_pack() -> None:
    mcp, captured = _mock_mcp()
    register(mcp)
    fn = captured["research.verify"]
    pack = _valid_pack()
    pack["query"] = "TAMPERED"

    result = await fn(pack)

    assert result["integrity_valid"] is False
    assert len(result["errors"]) >= 1


@pytest.mark.asyncio
async def test_verify_tool_empty_dict() -> None:
    mcp, captured = _mock_mcp()
    register(mcp)
    fn = captured["research.verify"]

    result = await fn({})

    assert result["integrity_valid"] is False
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
    assert result["integrity_valid"] is True


@pytest.mark.asyncio
async def test_verify_tool_schema_always_has_scope_fields() -> None:
    """R5.5 regression guard: the tool output must always expose the three scope
    fields (integrity_valid, binding_verified, authenticity_verified) so downstream
    consumers cannot mistake integrity for truthfulness or authenticity.
    """
    mcp, captured = _mock_mcp()
    register(mcp)
    fn = captured["research.verify"]

    # Valid pack
    result = await fn(_valid_pack())
    for key in ("integrity_valid", "binding_verified", "authenticity_verified", "errors",
                "transcript_cid", "scope_note"):
        assert key in result, f"result missing required field: {key}"
    # binding_verified and authenticity_verified are always False in v0.3
    assert result["binding_verified"] is False
    assert result["authenticity_verified"] is False

    # Empty dict (malformed pack) must also carry the scope fields
    result = await fn({})
    for key in ("integrity_valid", "binding_verified", "authenticity_verified", "errors",
                "transcript_cid", "scope_note"):
        assert key in result
    assert result["binding_verified"] is False
    assert result["authenticity_verified"] is False
