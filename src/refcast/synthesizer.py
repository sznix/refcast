"""Answer synthesis with inline [N] citation markers."""

from __future__ import annotations

import time

from google import genai
from google.genai import types as genai_types

from refcast.models import Citation

SYNTHESIS_MODEL = "gemini-2.5-flash"
INPUT_CENTS_PER_1K = 0.03
OUTPUT_CENTS_PER_1K = 0.25

SYSTEM_PROMPT = """\
You are a research assistant. Answer using ONLY the provided sources.
Rules:
1. Cite each claim with [1], [2] matching the source number below.
2. If sources disagree, present both positions with their citations.
3. If sources don't cover the question, say "Insufficient evidence from available sources."
4. Lead with a direct answer, then supporting details.
5. Keep it concise — 2-4 paragraphs."""


def _build_sources_block(citations: list[Citation]) -> str:
    lines = []
    for i, c in enumerate(citations, 1):
        url = c["source_url"]
        text = c["text"][:500]
        lines.append(f"[{i}] {url} — {text}")
    return "\n".join(lines)


async def synthesize(
    query: str,
    citations: list[Citation],
    api_key: str,
    model: str = SYNTHESIS_MODEL,
) -> tuple[str | None, float, int]:
    """Returns (answer_text | None, cost_cents, duration_ms). None = synthesis failed."""
    if not citations:
        return "", 0.0, 0
    sources = _build_sources_block(citations)
    user_prompt = f"SOURCES:\n{sources}\n\nQUESTION: {query}"
    start = time.monotonic()
    try:
        client = genai.Client(api_key=api_key)
        response = await client.aio.models.generate_content(
            model=model,
            contents=user_prompt,
            config=genai_types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
        )
        answer = response.text or ""
        usage = response.usage_metadata
        if usage is not None:
            in_tokens = usage.prompt_token_count or 0
            out_tokens = usage.candidates_token_count or 0
            cost = round(
                (in_tokens / 1000) * INPUT_CENTS_PER_1K + (out_tokens / 1000) * OUTPUT_CENTS_PER_1K,
                4,
            )
        else:
            cost = 0.0
        ms = int((time.monotonic() - start) * 1000)
        return answer, cost, ms
    except Exception:
        ms = int((time.monotonic() - start) * 1000)
        return None, 0.0, ms
