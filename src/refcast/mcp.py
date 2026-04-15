"""refcast MCP server entry point."""

from __future__ import annotations

import sys

from fastmcp import FastMCP

from refcast.backends.base import BackendAdapter, BackendError
from refcast.backends.exa import ExaBackend
from refcast.backends.gemini_fs import GeminiFSBackend
from refcast.config import MissingCredentialsError, load_config
from refcast.tools import (
    corpus_delete,
    corpus_list,
    corpus_status,
    corpus_upload,
    research,
)


def _register_backends() -> dict[str, BackendAdapter]:
    cfg = load_config(require_at_least_one=True)
    backends: dict[str, BackendAdapter] = {}

    if cfg.gemini_api_key:
        try:
            backends["gemini_fs"] = GeminiFSBackend(api_key=cfg.gemini_api_key)
        except BackendError as e:
            print(f"WARN: Gemini FS backend disabled: {e.message}", file=sys.stderr)

    if cfg.exa_api_key:
        try:
            backends["exa"] = ExaBackend(api_key=cfg.exa_api_key)
        except BackendError as e:
            print(f"WARN: Exa backend disabled: {e.message}", file=sys.stderr)

    return backends


def build_server() -> FastMCP:
    mcp: FastMCP = FastMCP("refcast")
    backends = _register_backends()

    corpus_upload.register(mcp, backends)
    corpus_status.register(mcp, backends)
    corpus_list.register(mcp, backends)
    corpus_delete.register(mcp, backends)
    research.register(mcp, backends)

    return mcp


def main() -> None:
    try:
        mcp = build_server()
    except MissingCredentialsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    mcp.run()


if __name__ == "__main__":
    main()
