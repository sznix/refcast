"""Shared helpers for MCP tool wrappers."""

from __future__ import annotations

from typing import Any

from refcast.backends.base import BackendError


def err_envelope(
    message: str,
    code: str = "backend_unavailable",
    recovery_action: str = "user_action",
    *,
    retry_after_ms: int | None = None,
    backend: str | None = None,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a consistent error envelope for MCP tool responses."""
    envelope: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "recovery_action": recovery_action,
        }
    }
    if retry_after_ms is not None:
        envelope["error"]["retry_after_ms"] = retry_after_ms
    if backend is not None:
        envelope["error"]["backend"] = backend
    if raw is not None:
        envelope["error"]["raw"] = raw
    return envelope


def err_from_backend(e: BackendError) -> dict[str, Any]:
    """Convert a BackendError into the MCP tool error envelope."""
    return err_envelope(
        e.message,
        code=e.code.value,
        recovery_action=e.recovery_action,
        retry_after_ms=e.retry_after_ms,
        backend=e.backend,
        raw=e.raw,
    )
