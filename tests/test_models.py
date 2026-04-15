"""Tests for refcast.models data shapes."""

from refcast.models import RecoveryEnum


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
