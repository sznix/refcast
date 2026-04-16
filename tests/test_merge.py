"""Tests for refcast.merge — citation deduplication across multi-query research results."""

from refcast.models import Citation, ResearchResult


def _mk_citation(
    text: str,
    url: str,
    confidence: float | None = 0.8,
) -> Citation:
    return {
        "text": text,
        "source_url": url,
        "author": None,
        "date": None,
        "confidence": confidence,
        "backend_used": "gemini_fs",
        "raw": {},
    }


def _mk_result(citations: list[Citation]) -> ResearchResult:
    return {
        "answer": "test answer",
        "citations": citations,
        "backend_used": "gemini_fs",
        "latency_ms": 100,
        "cost_cents": 0.01,
        "fallback_scope": "none",
        "warnings": [],
        "error": None,
    }


def test_merge_deduplicates_same_url_same_text():
    from refcast.merge import merge_citations

    c1 = _mk_citation("Identical text passage.", "https://example.com/page")
    c2 = _mk_citation("Identical text passage.", "https://example.com/page")

    results = [_mk_result([c1]), _mk_result([c2])]
    merged = merge_citations(results)

    assert len(merged) == 1
    assert merged[0]["source_url"] == "https://example.com/page"


def test_merge_keeps_different_passages_same_url():
    from refcast.merge import merge_citations

    c1 = _mk_citation("First passage about topic A.", "https://example.com/page")
    c2 = _mk_citation("Second passage about topic B.", "https://example.com/page")

    results = [_mk_result([c1, c2])]
    merged = merge_citations(results)

    assert len(merged) == 2


def test_merge_keeps_higher_confidence():
    from refcast.merge import merge_citations

    c_low = _mk_citation("Same text passage here.", "https://example.com", confidence=0.5)
    c_high = _mk_citation("Same text passage here.", "https://example.com", confidence=0.9)

    results = [_mk_result([c_low]), _mk_result([c_high])]
    merged = merge_citations(results)

    assert len(merged) == 1
    assert merged[0]["confidence"] == 0.9


def test_merge_handles_none_confidence():
    from refcast.merge import merge_citations

    c_none = _mk_citation("Same passage.", "https://example.com", confidence=None)
    c_real = _mk_citation("Same passage.", "https://example.com", confidence=0.7)

    results = [_mk_result([c_none]), _mk_result([c_real])]
    merged = merge_citations(results)

    assert len(merged) == 1
    assert merged[0]["confidence"] == 0.7


def test_merge_empty_results():
    from refcast.merge import merge_citations

    merged = merge_citations([])
    assert merged == []


def test_merge_preserves_order():
    from refcast.merge import merge_citations

    c1 = _mk_citation("First unique passage.", "https://first.com")
    c2 = _mk_citation("Second unique passage.", "https://second.com")
    c3 = _mk_citation("Third unique passage.", "https://third.com")

    results = [_mk_result([c1, c2, c3])]
    merged = merge_citations(results)

    assert len(merged) == 3
    urls = [c["source_url"] for c in merged]
    assert urls == ["https://first.com", "https://second.com", "https://third.com"]
