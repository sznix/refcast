"""STORM-lite multi-perspective query generation."""

from __future__ import annotations

from google import genai

PERSPECTIVE_PROMPT = """\
Given this research question: "{query}"

STEP 1 (internal, do not print): Identify the MOST LIKELY domain and resolve
any ambiguous acronyms or terms using context clues.
Examples of ambiguous acronyms you must disambiguate from context:
- "MCP" in an AI / software / agents context → Model Context Protocol
  (NOT Minecraft Protocol, Master Control Program, or other meanings)
- "RAG" → Retrieval-Augmented Generation (NOT Red-Amber-Green, etc.)
- "LLM" → Large Language Model
- "AGI" → Artificial General Intelligence
- Prefer the domain implied by the question's surrounding vocabulary.
- If the question is clearly academic/scientific, prefer scientific meanings.
- If the question is about software/code/AI, prefer technical meanings.

STEP 2: Generate {n} sub-queries that STAY WITHIN that identified domain.
Each sub-query MUST include enough context that a web search cannot mistake
it for a different topic (e.g., "Model Context Protocol MCP" not just "MCP").

Angles to cover (one sub-query per angle):
- Technical or implementation details
- Limitations, criticisms, or failure modes
- Historical context or how this evolved
- Practical applications or real-world usage

Return ONLY the final sub-queries, one per line. No numbering, no explanation,
no Step-1 output."""


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
