"""Backend adapter Protocol and shared exception type."""

from __future__ import annotations

from typing import Any, Protocol

from refcast.models import RecoveryEnum, ResearchConstraints, ResearchResult


class BackendAdapter(Protocol):
    id: str
    capabilities: frozenset[str]

    async def execute(
        self,
        query: str,
        corpus_id: str | None,
        constraints: ResearchConstraints | None,
    ) -> ResearchResult: ...


class BackendError(Exception):
    """Raised by adapters. Router converts to StructuredError."""

    def __init__(
        self,
        code: RecoveryEnum,
        message: str,
        *,
        backend: str,
        recovery_action: str = "fallback",
        retry_after_ms: int | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.backend = backend
        self.recovery_action = recovery_action
        self.retry_after_ms = retry_after_ms
        self.raw = raw or {}
