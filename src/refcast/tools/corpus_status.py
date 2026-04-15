"""MCP tool: corpus.status — wraps GeminiFSBackend.poll_status."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refcast.backends.base import BackendError
from refcast.tools._utils import err_envelope, err_from_backend

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from refcast.backends.base import BackendAdapter


def register(mcp: FastMCP, backends: dict[str, BackendAdapter]) -> None:
    @mcp.tool(name="corpus.status")
    async def corpus_status(corpus_id: str) -> dict[str, Any]:
        """Return indexing progress for a corpus."""
        gemini = backends.get("gemini_fs")
        if gemini is None:
            return err_envelope(
                "gemini_fs backend not registered; corpus operations require it"
            )
        try:
            result = await gemini.poll_status(corpus_id)  # type: ignore[attr-defined]
        except BackendError as e:
            return err_from_backend(e)
        return dict(result)
