"""MCP tool: corpus.upload — wraps GeminiFSBackend.upload_files."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refcast.backends.base import BackendError
from refcast.tools._utils import err_envelope, err_from_backend

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from refcast.backends.base import BackendAdapter


def register(mcp: FastMCP, backends: dict[str, BackendAdapter]) -> None:
    @mcp.tool(name="corpus.upload")
    async def corpus_upload(files: list[str]) -> dict[str, Any]:
        """Upload files to a new corpus.

        Returns immediately with operation_id; poll corpus.status for indexing progress.
        """
        gemini = backends.get("gemini_fs")
        if gemini is None:
            return err_envelope("gemini_fs backend not registered; corpus operations require it")
        try:
            result = await gemini.upload_files(files)  # type: ignore[attr-defined]
        except BackendError as e:
            return err_from_backend(e)
        return dict(result)
