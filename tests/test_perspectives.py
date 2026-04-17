"""Tests for refcast.perspectives — STORM-lite multi-perspective query generation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mk_perspectives_response(text: str) -> MagicMock:
    """Build a fake google-genai response for perspectives."""
    response = MagicMock()
    response.text = text
    return response


@pytest.mark.asyncio
async def test_generate_perspectives_returns_list():
    fake_text = (
        "How does transformer attention work technically?\n"
        "What are the limitations of transformers at scale?\n"
        "How did transformers evolve from RNNs historically?\n"
        "Where are transformers used in production today?"
    )
    fake_response = _mk_perspectives_response(fake_text)

    with patch("refcast.perspectives.genai.Client") as mock_cls:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=fake_response)
        mock_cls.return_value = client

        from refcast.perspectives import generate_perspectives

        results = await generate_perspectives(
            query="How do transformers work?",
            api_key="test-key",
            num_perspectives=4,
        )

    assert isinstance(results, list)
    assert len(results) == 4
    assert all(isinstance(s, str) for s in results)
    assert all(len(s) > 0 for s in results)


@pytest.mark.asyncio
async def test_generate_perspectives_fallback_on_failure():
    original_query = "How do transformers work?"

    with patch("refcast.perspectives.genai.Client") as mock_cls:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(side_effect=Exception("API unavailable"))
        mock_cls.return_value = client

        from refcast.perspectives import generate_perspectives

        results = await generate_perspectives(
            query=original_query,
            api_key="test-key",
        )

    assert results == [original_query]


def test_perspective_prompt_contains_domain_disambiguation():
    """Codex audit (2026-04-17): prompt must instruct the model to disambiguate
    acronyms (e.g. 'MCP' → 'Model Context Protocol', not 'Minecraft Protocol')
    BEFORE generating sub-queries. Previously the prompt was context-free, which
    produced Minecraft-themed sub-queries for a Model-Context-Protocol question.

    This is a prompt-quality assertion, not a model-behaviour test.
    """
    from refcast.perspectives import PERSPECTIVE_PROMPT

    lowered = PERSPECTIVE_PROMPT.lower()
    # Must instruct disambiguation
    assert "disambiguat" in lowered or "domain" in lowered, (
        "PERSPECTIVE_PROMPT must include domain/acronym disambiguation instruction"
    )
    # Must steer the model to stay WITHIN the identified domain
    assert "within" in lowered or "stay" in lowered or "same domain" in lowered


@pytest.mark.asyncio
async def test_generate_perspectives_passes_query_into_prompt():
    """The formatted prompt must include the actual query text."""
    from refcast.perspectives import PERSPECTIVE_PROMPT

    formatted = PERSPECTIVE_PROMPT.format(query="What is MCP?", n=4)
    assert "What is MCP?" in formatted


@pytest.mark.asyncio
async def test_generate_perspectives_filters_empty_lines():
    fake_text = (
        "First sub-query about technical details\n"
        "\n"
        "  \n"
        "Second sub-query about limitations\n"
        "\n"
        "Third sub-query about history\n"
    )
    fake_response = _mk_perspectives_response(fake_text)

    with patch("refcast.perspectives.genai.Client") as mock_cls:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=fake_response)
        mock_cls.return_value = client

        from refcast.perspectives import generate_perspectives

        results = await generate_perspectives(
            query="test query",
            api_key="test-key",
        )

    assert len(results) == 3
    assert all(len(s) > 0 for s in results)
    assert all(s == s.strip() for s in results)
