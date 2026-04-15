"""Data shapes for refcast — TypedDicts, enums, and error types."""

from __future__ import annotations

from enum import StrEnum


class RecoveryEnum(StrEnum):
    RATE_LIMITED = "rate_limited"
    QUOTA_EXCEEDED = "quota_exceeded"
    NETWORK_TIMEOUT = "network_timeout"
    AUTH_INVALID = "auth_invalid"
    CORPUS_NOT_FOUND = "corpus_not_found"
    EMPTY_CORPUS = "empty_corpus"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    SCHEMA_MISMATCH = "schema_mismatch"
    PARSE_ERROR = "parse_error"
    INDEXING_IN_PROGRESS = "indexing_in_progress"
    FILE_TOO_LARGE = "file_too_large"
    UNSUPPORTED_FORMAT = "unsupported_format"
    PARTIAL_INDEX = "partial_index"
    UNKNOWN = "unknown"
