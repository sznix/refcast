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
