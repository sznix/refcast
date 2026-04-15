"""MCP tool: corpus.list — wraps GeminiFSBackend.list_corpora."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refcast.backends.base import BackendError
from refcast.tools._utils import err_envelope, err_from_backend

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from refcast.backends.base import BackendAdapter


def register(mcp: FastMCP, backends: dict[str, BackendAdapter]) -> None:
    @mcp.tool(name="corpus.list")
    async def corpus_list() -> dict[str, Any]:
        """List all corpora known to the Gemini FS backend."""
        gemini = backends.get("gemini_fs")
        if gemini is None:
            return err_envelope("gemini_fs backend not registered; corpus operations require it")
        try:
            corpora = await gemini.list_corpora()  # type: ignore[attr-defined]
        except BackendError as e:
            return err_from_backend(e)
        return {"corpora": list(corpora)}
