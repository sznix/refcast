"""Scope-regression guards for the v0.3 integrity primitive.

These tests DELIBERATELY enforce what refcast v0.3 does NOT do. If a future
commit adds a signature field, a crypto-signing import, or a PKI-backed verifier,
these tests fail — preventing silent drift from the integrity-only scope into an
authenticity claim the code cannot actually defend.

A separate guard enforces that `research.verify` remains registered as an
independently-callable MCP tool alongside `research` (protecting against silent
removal that would pass the rest of the suite).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from refcast.config import RefcastConfig

# Files in the evidence + verifier path. If any of these imports a signing
# primitive, we will lie to users about the scope of the verifier.
EVIDENCE_PATH_FILES = [
    Path(__file__).resolve().parent.parent / "src" / "refcast" / "evidence.py",
    Path(__file__).resolve().parent.parent / "src" / "refcast" / "tools" / "research_verify.py",
]

# Module names that would imply authenticity-level crypto (signatures, PKI).
# sha256/hmac-less hashing via `hashlib` is fine; signing modules are not.
SIGNING_MODULES = {
    "cryptography",              # asymmetric crypto suite
    "cryptography.hazmat",
    "Crypto",                    # pycryptodome
    "nacl",                      # PyNaCl (Ed25519/Curve25519)
    "pysodium",
    "ecdsa",
    "rsa",                       # standalone RSA library (not the RFC, the package)
    "gnupg",
    "pgpy",
    "ed25519",
    "cose",                      # COSE signatures
    "jose",                      # JOSE / JWS / JWT
    "python_jose",
    "jwcrypto",
    "pycryptodome",
    "pycryptodomex",
    "keyring",                   # keyring access would imply credential binding
}


def _top_module(name: str) -> str:
    return name.split(".")[0]


def _imports_in(path: Path) -> set[str]:
    """Return the set of top-level module names imported by `path`."""
    src = path.read_text()
    tree = ast.parse(src, filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(_top_module(alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(_top_module(node.module))
    return modules


def test_no_signing_imports_in_evidence_path() -> None:
    """R3.1 regression guard: v0.3 is integrity-only. If a dev adds a signing
    import to evidence.py or research_verify.py, this test fails so the scope
    disclaimer in the claim and docstrings does not silently become a lie.
    """
    offenders: dict[str, set[str]] = {}
    for path in EVIDENCE_PATH_FILES:
        assert path.exists(), f"evidence-path file missing: {path}"
        imports = _imports_in(path)
        bad = imports & SIGNING_MODULES
        if bad:
            offenders[str(path)] = bad
    assert not offenders, (
        "v0.3 is integrity-only — verifier must not import signing/PKI modules.\n"
        "If you are intentionally moving to authenticity, update the claim, "
        "the docstrings, the CHANGELOG, and the verifier output schema FIRST.\n"
        f"Offending files: {offenders}"
    )


def test_no_network_imports_in_verifier() -> None:
    """R3.1-adj regression guard: the verifier is pure offline. No network imports.

    Only the `evidence.py` and `research_verify.py` files are checked — the
    `research` producer tool is allowed network I/O; the verifier is not.
    """
    network_modules = {"httpx", "requests", "urllib3", "aiohttp", "httpcore"}
    offenders: dict[str, set[str]] = {}
    for path in EVIDENCE_PATH_FILES:
        imports = _imports_in(path)
        bad = imports & network_modules
        if bad:
            offenders[str(path)] = bad
    assert not offenders, (
        "Verifier must be pure offline. Found network imports: " + str(offenders)
    )


async def _registered_tool_names(mcp_instance: Any) -> set[str]:
    tools = await mcp_instance.list_tools()
    return {t.name for t in tools}


@pytest.mark.asyncio
@patch("refcast.mcp.load_config")
@patch("refcast.mcp.GeminiFSBackend")
@patch("refcast.mcp.ExaBackend")
async def test_build_server_registers_research_verify(
    mock_exa: MagicMock,
    mock_gemini: MagicMock,
    mock_load: MagicMock,
) -> None:
    """R3.2 regression guard: `research.verify` must be registered alongside
    `research`. The prior `test_build_server_registers_five_tools` uses
    `.issubset(...)` and deliberately excludes `research.verify` — a dev could
    delete the registration line and this test would still pass. This test
    directly asserts presence.
    """
    mock_load.return_value = RefcastConfig(
        gemini_api_key="fake_gemini",
        exa_api_key="fake_exa",
    )
    mock_gemini.return_value = MagicMock(id="gemini_fs")
    mock_exa.return_value = MagicMock(id="exa")

    from refcast.mcp import build_server

    mcp = build_server()
    tool_names = await _registered_tool_names(mcp)

    assert "research" in tool_names, (
        "Expected `research` to be registered; got: " + str(sorted(tool_names))
    )
    assert "research.verify" in tool_names, (
        "Expected `research.verify` to be registered alongside `research`; "
        "got: " + str(sorted(tool_names))
    )


@pytest.mark.asyncio
@patch("refcast.mcp.load_config")
@patch("refcast.mcp.GeminiFSBackend")
@patch("refcast.mcp.ExaBackend")
async def test_build_server_registers_six_tools_total(
    mock_exa: MagicMock,
    mock_gemini: MagicMock,
    mock_load: MagicMock,
) -> None:
    """Exactly six tools should be registered: four corpus-management tools
    plus `research` and `research.verify`. This pins the tool-count claim in
    the v0.3 CHANGELOG / README.
    """
    mock_load.return_value = RefcastConfig(
        gemini_api_key="fake_gemini",
        exa_api_key="fake_exa",
    )
    mock_gemini.return_value = MagicMock(id="gemini_fs")
    mock_exa.return_value = MagicMock(id="exa")

    from refcast.mcp import build_server

    mcp = build_server()
    tool_names = await _registered_tool_names(mcp)

    expected = {
        "corpus.upload",
        "corpus.status",
        "corpus.list",
        "corpus.delete",
        "research",
        "research.verify",
    }
    assert expected == tool_names, (
        f"Expected exactly {expected}; got {tool_names}. "
        "If a new tool was added, update this test AND the CHANGELOG AND the README."
    )
