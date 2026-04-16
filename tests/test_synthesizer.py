"""Tests for refcast.synthesizer — answer synthesis with inline [N] citation markers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from refcast.models import Citation


def _mk_citation(text: str, url: str, confidence: float | None = 0.9) -> Citation:
    return {
        "text": text,
        "source_url": url,
        "author": None,
        "date": None,
        "confidence": confidence,
        "backend_used": "gemini_fs",
        "raw": {},
    }


def _mk_synth_response(answer_text: str, input_tokens: int = 50, output_tokens: int = 20):
    """Build a fake google-genai response for synthesis."""
    response = MagicMock()
    response.text = answer_text
    response.usage_metadata = MagicMock(
        prompt_token_count=input_tokens,
        candidates_token_count=output_tokens,
    )
    return response


@pytest.mark.asyncio
async def test_synthesize_returns_answer_with_markers():
    citations = [
        _mk_citation("Attention is all you need.", "https://arxiv.org/abs/1706.03762"),
        _mk_citation("BERT uses bidirectional encoding.", "https://arxiv.org/abs/1810.04805"),
    ]
    fake_answer = "Transformers use attention [1]. BERT extends this [2]."
    fake_response = _mk_synth_response(fake_answer)

    with patch("refcast.synthesizer.genai.Client") as mock_cls:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=fake_response)
        mock_cls.return_value = client

        from refcast.synthesizer import synthesize

        answer, cost, ms = await synthesize(
            query="How do transformers work?",
            citations=citations,
            api_key="test-key",
        )

    assert answer == fake_answer
    assert "[1]" in answer
    assert "[2]" in answer
    assert cost >= 0.0
    assert ms >= 0


@pytest.mark.asyncio
async def test_synthesize_empty_citations_returns_empty():
    from refcast.synthesizer import synthesize

    answer, cost, ms = await synthesize(
        query="anything",
        citations=[],
        api_key="test-key",
    )

    assert answer == ""
    assert cost == 0.0
    assert ms == 0


@pytest.mark.asyncio
async def test_synthesize_fallback_on_api_failure():
    citations = [_mk_citation("Some text.", "https://example.com")]

    with patch("refcast.synthesizer.genai.Client") as mock_cls:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(side_effect=Exception("API unavailable"))
        mock_cls.return_value = client

        from refcast.synthesizer import synthesize

        answer, cost, ms = await synthesize(
            query="test query",
            citations=citations,
            api_key="test-key",
        )

    assert answer is None
    assert cost == 0.0
    assert ms >= 0


@pytest.mark.asyncio
async def test_synthesize_prompt_contains_sources():
    citations = [
        _mk_citation("First source text here.", "https://source1.com"),
        _mk_citation("Second source text here.", "https://source2.com"),
    ]
    fake_response = _mk_synth_response("Answer with [1] and [2].")

    captured_prompt: list[str] = []

    async def capture_generate(model, contents, config=None):
        captured_prompt.append(contents)
        return fake_response

    with patch("refcast.synthesizer.genai.Client") as mock_cls:
        client = MagicMock()
        client.aio.models.generate_content = capture_generate
        mock_cls.return_value = client

        from refcast.synthesizer import synthesize

        await synthesize(
            query="What do the sources say?",
            citations=citations,
            api_key="test-key",
        )

    assert len(captured_prompt) == 1
    prompt = captured_prompt[0]
    assert "[1]" in prompt
    assert "[2]" in prompt
    assert "https://source1.com" in prompt
    assert "https://source2.com" in prompt
