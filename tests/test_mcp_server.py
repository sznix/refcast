"""Tests for MCP server entry point."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from refcast.config import MissingCredentialsError, RefcastConfig


async def _registered_tool_names(mcp_instance: Any) -> set[str]:
    tools = await mcp_instance.list_tools()
    return {t.name for t in tools}


@pytest.mark.asyncio
@patch("refcast.mcp.load_config")
@patch("refcast.mcp.GeminiFSBackend")
@patch("refcast.mcp.ExaBackend")
async def test_build_server_registers_five_tools(
    mock_exa: MagicMock,
    mock_gemini: MagicMock,
    mock_load: MagicMock,
) -> None:
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
    }
    assert expected.issubset(tool_names), f"Expected {expected} to be registered; got {tool_names}"


@pytest.mark.asyncio
@patch("refcast.mcp.load_config")
@patch("refcast.mcp.GeminiFSBackend")
async def test_build_server_partial_creds_gemini_only(
    mock_gemini: MagicMock,
    mock_load: MagicMock,
) -> None:
    mock_load.return_value = RefcastConfig(
        gemini_api_key="fake_gemini",
        exa_api_key=None,
    )
    mock_gemini.return_value = MagicMock(id="gemini_fs")

    from refcast.mcp import build_server

    mcp = build_server()
    tool_names = await _registered_tool_names(mcp)
    # All 5 tools still registered (they handle missing backends gracefully).
    assert "research" in tool_names
    assert "corpus.upload" in tool_names
    mock_gemini.assert_called_once_with(api_key="fake_gemini")


@pytest.mark.asyncio
@patch("refcast.mcp.load_config")
@patch("refcast.mcp.GeminiFSBackend")
@patch("refcast.mcp.ExaBackend")
async def test_register_backends_returns_tuple_with_gemini_key(
    mock_exa: MagicMock,
    mock_gemini: MagicMock,
    mock_load: MagicMock,
) -> None:
    mock_load.return_value = RefcastConfig(
        gemini_api_key="fake_gemini",
        exa_api_key="fake_exa",
    )
    mock_gemini.return_value = MagicMock(id="gemini_fs")
    mock_exa.return_value = MagicMock(id="exa")

    from refcast.mcp import _register_backends

    backends, gemini_key = _register_backends()
    assert "gemini_fs" in backends
    assert "exa" in backends
    assert gemini_key == "fake_gemini"


@pytest.mark.asyncio
@patch("refcast.mcp.load_config")
@patch("refcast.mcp.ExaBackend")
async def test_register_backends_no_gemini_key_returns_none(
    mock_exa: MagicMock,
    mock_load: MagicMock,
) -> None:
    mock_load.return_value = RefcastConfig(
        gemini_api_key=None,
        exa_api_key="fake_exa",
    )
    mock_exa.return_value = MagicMock(id="exa")

    from refcast.mcp import _register_backends

    backends, gemini_key = _register_backends()
    assert "exa" in backends
    assert gemini_key is None


@pytest.mark.asyncio
@patch("refcast.mcp.load_config")
@patch("refcast.mcp.GeminiFSBackend")
@patch("refcast.mcp.ExaBackend")
@patch("refcast.mcp.research")
async def test_build_server_passes_gemini_key_to_research(
    mock_research: MagicMock,
    mock_exa: MagicMock,
    mock_gemini: MagicMock,
    mock_load: MagicMock,
) -> None:
    mock_load.return_value = RefcastConfig(
        gemini_api_key="fake_gemini",
        exa_api_key="fake_exa",
    )
    mock_gemini.return_value = MagicMock(id="gemini_fs")
    mock_exa.return_value = MagicMock(id="exa")

    from refcast.mcp import build_server

    build_server()
    mock_research.register.assert_called_once()
    call_kwargs = mock_research.register.call_args
    assert call_kwargs[1].get("gemini_api_key") == "fake_gemini" or (
        len(call_kwargs[0]) >= 3 and call_kwargs[0][2] == "fake_gemini"
    )


@patch("refcast.mcp.load_config")
def test_main_missing_credentials_exits_1(
    mock_load: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_load.side_effect = MissingCredentialsError("No creds")

    from refcast.mcp import main

    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "No creds" in captured.err
