"""MCP tool: corpus.delete — wraps GeminiFSBackend.delete_corpus."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refcast.backends.base import BackendError
from refcast.tools._utils import err_envelope, err_from_backend

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from refcast.backends.base import BackendAdapter


def register(mcp: FastMCP, backends: dict[str, BackendAdapter]) -> None:
    @mcp.tool(name="corpus.delete")
    async def corpus_delete(corpus_id: str) -> dict[str, Any]:
        """Delete a corpus and release its storage."""
        gemini = backends.get("gemini_fs")
        if gemini is None:
            return err_envelope("gemini_fs backend not registered; corpus operations require it")
        try:
            result = await gemini.delete_corpus(corpus_id)  # type: ignore[attr-defined]
        except BackendError as e:
            return err_from_backend(e)
        return dict(result)
