"""MCP tool: research.verify — offline verification of an EvidencePack.

Pure function. Zero network, zero API keys. Works on airgapped machines.
This is the consumer side of the v0.3 primitive.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refcast.evidence import verify_evidence_pack

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.tool(name="research.verify")
    async def research_verify(evidence_pack: dict[str, Any]) -> dict[str, Any]:
        """Verify an EvidencePack offline.

        Returns ``{valid: bool, errors: list[str], transcript_cid: str | None}``.

        The caller provides the `evidence_pack` dict (typically saved from a prior
        ``research()`` call). No external calls are made — verification is a pure
        function of the pack's bytes. This means:
        - Works when APIs are down, quotas exhausted, or the user is offline.
        - Anyone can verify, not just the original caller.
        - Works on any machine that has refcast installed.
        """
        valid, errors = verify_evidence_pack(evidence_pack)
        return {
            "valid": valid,
            "errors": errors,
            "transcript_cid": evidence_pack.get("transcript_cid")
            if isinstance(evidence_pack, dict)
            else None,
        }
