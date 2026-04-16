"""STORM-lite multi-perspective query generation."""

from __future__ import annotations

from google import genai

PERSPECTIVE_PROMPT = """\
Given this research question: "{query}"
Generate {n} different sub-queries, each from a different angle:
- Technical or implementation details
- Limitations, criticisms, or failure modes
- Historical context or how this evolved
- Practical applications or real-world usage
Return ONLY the sub-queries, one per line. No numbering, no explanation."""


async def generate_perspectives(
    query: str,
    api_key: str,
    num_perspectives: int = 4,
    model: str = "gemini-2.5-flash",
) -> list[str]:
    """Generate angle-specific sub-queries. Returns [query] on any failure."""
    try:
        client = genai.Client(api_key=api_key)
        response = await client.aio.models.generate_content(
            model=model,
            contents=PERSPECTIVE_PROMPT.format(query=query, n=num_perspectives),
        )
        lines = [line.strip() for line in (response.text or "").split("\n") if line.strip()]
        return lines if lines else [query]
    except Exception:
        return [query]
