"""Tests for refcast.models data shapes."""

from refcast.models import (
    Citation,
    CorpusDeleteResult,
    CorpusStatusResult,
    CorpusSummary,
    CorpusUploadResult,
    RecoveryEnum,
    ResearchConstraints,
    ResearchResult,
    StructuredError,
    redact_raw,
)


def test_recovery_enum_has_14_codes():
    expected = {
        "rate_limited",
        "quota_exceeded",
        "network_timeout",
        "auth_invalid",
        "corpus_not_found",
        "empty_corpus",
        "backend_unavailable",
        "schema_mismatch",
        "parse_error",
        "indexing_in_progress",
        "file_too_large",
        "unsupported_format",
        "partial_index",
        "unknown",
    }
    actual = {m.value for m in RecoveryEnum}
    assert actual == expected


def test_recovery_enum_str_value():
    assert RecoveryEnum.RATE_LIMITED.value == "rate_limited"
    assert str(RecoveryEnum.UNKNOWN.value) == "unknown"


def test_structured_error_shape():
    err: StructuredError = {
        "code": RecoveryEnum.RATE_LIMITED,
        "message": "Gemini 429",
        "recovery_hint": "retry after 30s",
        "recovery_action": "retry",
        "fallback_used": False,
        "partial_results": False,
        "retry_after_ms": 30000,
        "backend": "gemini_fs",
        "raw": {"status": 429},
    }
    assert err["code"] == RecoveryEnum.RATE_LIMITED
    assert err["recovery_action"] == "retry"


def test_redact_raw_removes_sensitive_keys():
    raw = {
        "status": 401,
        "authorization": "Bearer secret_token",
        "Cookie": "session=xyz",
        "data": {"x-goog-api-key": "AIza...", "ok": True},
    }
    redacted = redact_raw(raw)
    assert redacted["status"] == 401
    assert redacted["authorization"] == "[REDACTED]"
    assert redacted["Cookie"] == "[REDACTED]"
    assert redacted["data"]["x-goog-api-key"] == "[REDACTED]"
    assert redacted["data"]["ok"] is True


def test_redact_raw_leaves_originals_untouched():
    raw = {"authorization": "secret"}
    redact_raw(raw)
    assert raw["authorization"] == "secret"  # original unmodified


def test_citation_shape():
    c: Citation = {
        "text": "The claim",
        "source_url": "https://example.com",
        "author": None,
        "date": None,
        "confidence": 0.87,
        "backend_used": "gemini_fs",
        "raw": {"chunk_id": 5},
    }
    assert c["confidence"] == 0.87
    assert c["backend_used"] == "gemini_fs"


def test_citation_confidence_optional():
    c: Citation = {
        "text": "x",
        "source_url": "u",
        "author": None,
        "date": None,
        "confidence": None,
        "backend_used": "exa",
        "raw": {},
    }
    assert c["confidence"] is None


def test_research_constraints_all_optional():
    rc: ResearchConstraints = {}
    assert rc == {}


def test_research_result_full_shape():
    rr: ResearchResult = {
        "answer": "x",
        "citations": [],
        "backend_used": "gemini_fs",
        "latency_ms": 120,
        "cost_cents": 0.1,
        "fallback_scope": "none",
        "warnings": [],
        "error": None,
    }
    assert rr["fallback_scope"] == "none"


def test_corpus_upload_result():
    u: CorpusUploadResult = {
        "corpus_id": "cor_x",
        "operation_id": "op_y",
        "status": "indexing",
        "file_count": 3,
        "started_at": "2026-04-15T13:00:00Z",
    }
    assert u["status"] == "indexing"


def test_corpus_status_result():
    s: CorpusStatusResult = {
        "corpus_id": "cor_x",
        "indexed": True,
        "file_count": 3,
        "indexed_file_count": 3,
        "progress": 1.0,
        "warnings": [],
        "last_checked_at": "2026-04-15T13:01:00Z",
    }
    assert s["progress"] == 1.0


def test_corpus_summary():
    cs: CorpusSummary = {
        "corpus_id": "cor_x",
        "name": None,
        "file_count": 3,
        "indexed_file_count": 3,
        "total_bytes": 1024,
        "created_at": "2026-04-15T13:00:00Z",
        "backend": "gemini_fs",
    }
    assert cs["backend"] == "gemini_fs"


def test_corpus_delete_result():
    d: CorpusDeleteResult = {"corpus_id": "cor_x", "deleted": True, "files_removed": 3}
    assert d["deleted"] is True


def test_research_constraints_depth():
    rc: ResearchConstraints = {"depth": "deep"}
    assert rc["depth"] == "deep"
