"""Tests for refcast.models data shapes."""

from refcast.models import RecoveryEnum, StructuredError, redact_raw


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
