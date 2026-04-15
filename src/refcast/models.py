"""Data shapes for refcast — TypedDicts, enums, and error types."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, TypedDict


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


_REDACT_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "api_key",
        "x-goog-api-key",
        "bearer",
        "token",
        "password",
    }
)


def redact_raw(d: Any) -> Any:
    """Deep-copy `d` replacing any sensitive key's value with '[REDACTED]'."""
    if isinstance(d, dict):
        return {
            k: ("[REDACTED]" if k.lower() in _REDACT_KEYS else redact_raw(v)) for k, v in d.items()
        }
    if isinstance(d, list):
        return [redact_raw(v) for v in d]
    return d


class StructuredError(TypedDict):
    code: RecoveryEnum
    message: str
    recovery_hint: str
    recovery_action: Literal["retry", "fallback", "user_action"]
    fallback_used: bool
    partial_results: bool
    retry_after_ms: int | None
    backend: str | None
    raw: dict[str, Any]


class Citation(TypedDict):
    text: str
    source_url: str
    author: str | None
    date: str | None
    confidence: float | None
    backend_used: str
    raw: dict[str, Any]


class ResearchConstraints(TypedDict, total=False):
    max_cost_cents: int
    max_citations: int
    date_after: str
    require_citation: bool
    preferred_backend: Literal["gemini_fs", "exa"]


class ResearchResult(TypedDict):
    answer: str
    citations: list[Citation]
    backend_used: str
    latency_ms: int
    cost_cents: float
    fallback_scope: Literal["none", "same", "broader", "different"]
    warnings: list[StructuredError]
    error: StructuredError | None


class CorpusUploadResult(TypedDict):
    corpus_id: str
    operation_id: str
    status: Literal["indexing"]
    file_count: int
    started_at: str


class CorpusStatusResult(TypedDict):
    corpus_id: str
    indexed: bool
    file_count: int
    indexed_file_count: int
    progress: float
    warnings: list[StructuredError]
    last_checked_at: str


class CorpusSummary(TypedDict):
    corpus_id: str
    name: str | None
    file_count: int
    indexed_file_count: int
    total_bytes: int
    created_at: str
    backend: Literal["gemini_fs"]


class CorpusDeleteResult(TypedDict):
    corpus_id: str
    deleted: bool
    files_removed: int
