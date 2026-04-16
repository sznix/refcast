"""Citation deduplication across multi-query research results."""

from __future__ import annotations

from refcast.models import Citation, ResearchResult


def merge_citations(results: list[ResearchResult]) -> list[Citation]:
    """Deduplicate by (source_url, text[:100]). Keeps higher confidence on collision."""
    seen: dict[tuple[str, str], Citation] = {}
    for result in results:
        for citation in result["citations"]:
            key = (citation["source_url"], citation["text"][:100])
            existing = seen.get(key)
            if existing is None or (citation["confidence"] or 0) > (existing["confidence"] or 0):
                seen[key] = citation
    return list(seen.values())
