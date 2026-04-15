"""Tests for 25KB response-size enforcement."""

from __future__ import annotations

import json

from refcast.models import RecoveryEnum
from refcast.size_guard import RESPONSE_SIZE_LIMIT_BYTES, enforce_response_size


def _make_result(citation_count: int, citation_text_size: int = 500) -> dict:
    citations = []
    for i in range(citation_count):
        citations.append(
            {
                "text": "x" * citation_text_size,
                "source_url": f"https://example.com/{i}",
                "author": None,
                "date": None,
                "confidence": 0.9,
                "backend_used": "exa",
                "raw": {},
            }
        )
    return {
        "answer": "short answer",
        "citations": citations,
        "backend_used": "exa",
        "latency_ms": 100,
        "cost_cents": 0.7,
        "fallback_scope": "none",
        "warnings": [],
        "error": None,
    }


def test_under_limit_returns_unchanged() -> None:
    result = _make_result(citation_count=2, citation_text_size=100)
    out = enforce_response_size(result)
    assert out == result
    assert len(out["citations"]) == 2
    assert out["warnings"] == []


def test_over_limit_truncates_citations_source_order() -> None:
    # Build a result that exceeds 25KB. ~100 citations × 500 bytes ≈ >50KB.
    result = _make_result(citation_count=100, citation_text_size=500)
    size_before = len(json.dumps(result, default=str).encode("utf-8"))
    assert size_before > RESPONSE_SIZE_LIMIT_BYTES

    out = enforce_response_size(result)

    # Answer preserved
    assert out["answer"] == "short answer"
    # Some citations dropped
    assert len(out["citations"]) < 100
    # Remaining citations are the HEAD (source order preserved, tail dropped)
    for i, cit in enumerate(out["citations"]):
        assert cit["source_url"] == f"https://example.com/{i}"
    # Warning appended
    assert len(out["warnings"]) == 1
    warn = out["warnings"][0]
    assert warn["code"] == RecoveryEnum.UNKNOWN
    assert "truncated" in warn["message"].lower()
    assert warn["partial_results"] is True
    # Final size within limit
    assert len(json.dumps(out, default=str).encode("utf-8")) <= RESPONSE_SIZE_LIMIT_BYTES


def test_over_limit_preserves_existing_warnings() -> None:
    result = _make_result(citation_count=100, citation_text_size=500)
    existing_warning = {
        "code": RecoveryEnum.RATE_LIMITED,
        "message": "pre-existing",
        "recovery_hint": "wait",
        "recovery_action": "retry",
        "fallback_used": True,
        "partial_results": False,
        "retry_after_ms": 1000,
        "backend": "gemini_fs",
        "raw": {},
    }
    result["warnings"] = [existing_warning]

    out = enforce_response_size(result)

    # Existing warning retained plus truncation warning appended
    assert len(out["warnings"]) == 2
    assert out["warnings"][0]["message"] == "pre-existing"
    assert out["warnings"][1]["code"] == RecoveryEnum.UNKNOWN
