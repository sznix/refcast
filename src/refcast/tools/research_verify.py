"""MCP tool: research.verify — pure-offline integrity verification of an EvidencePack.

Pure function. Zero network, zero API keys. Works on airgapped machines.
This is the consumer side of the v0.3 primitive.

**Scope**: integrity only — does NOT prove citation binding, provenance, or
authenticity. See `refcast.evidence` module docstring for the exact scope.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refcast.evidence import verify_evidence_pack

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.tool(name="research.verify")
    async def research_verify(evidence_pack: dict[str, Any]) -> dict[str, Any]:
        """Verify the **integrity** of an EvidencePack offline.

        Returns a structured verdict:

        ```
        {
          "integrity_valid":      bool,       # bytes unchanged since emission
          "binding_verified":     False,      # always False in v0.3 — see note
          "authenticity_verified": False,     # always False in v0.3 — no signer
          "errors":               list[str],  # empty iff integrity_valid
          "transcript_cid":       str | None, # pack's self-identifier, or None
          "scope_note":           str,        # human-readable scope disclaimer
        }
        ```

        **What `integrity_valid=True` proves**: the pack's bytes have not been
        mutated since emission.

        **What `integrity_valid=True` does NOT prove**:
        - That `citations` shown to the consumer correspond to this pack
          (`binding_verified` is always `False` in v0.3 — citation binding requires
          re-hashing each citation against `source_cids` out-of-band, which this
          tool does not do).
        - That refcast or any specific party produced the pack (`authenticity_verified`
          is always `False` in v0.3 — there is no signature, no signer identity).
        - That the answer or citations are factually correct.

        The caller provides the `evidence_pack` dict (typically saved from a prior
        ``research()`` call). No external calls are made — verification is a pure
        function of the pack's bytes. This means:

        - Works when APIs are down, quotas exhausted, or the user is offline.
        - Anyone can verify, not just the original caller.
        - Works on any machine that has refcast installed.
        """
        integrity_valid, errors = verify_evidence_pack(evidence_pack)
        return {
            "integrity_valid": integrity_valid,
            "binding_verified": False,
            "authenticity_verified": False,
            "errors": errors,
            "transcript_cid": evidence_pack.get("transcript_cid")
            if isinstance(evidence_pack, dict)
            else None,
            "scope_note": (
                "v0.3 integrity only. Does NOT prove citation binding "
                "(re-hash citations against source_cids out-of-band) "
                "or authenticity (no signer identity, no signature)."
            ),
        }
