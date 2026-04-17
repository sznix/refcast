"""Serial-fallback research router."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast

from refcast.backends.base import BackendError
from refcast.models import RecoveryEnum, ResearchResult, StructuredError, redact_raw

if TYPE_CHECKING:
    from refcast.backends.base import BackendAdapter
    from refcast.models import ResearchConstraints

FallbackScope = Literal["none", "same", "broader", "different"]
RecoveryAction = Literal["retry", "fallback", "user_action"]

_DEFAULT_ORDER_WITH_CORPUS = ["gemini_fs", "exa"]
_DEFAULT_ORDER_WEB_ONLY = ["exa"]


def classify_scope_shift(
    primary: str,
    served: str,
    primary_corpus_id: str | None,
    served_corpus_id: str | None,
    fell_back: bool = True,
) -> FallbackScope:
    """Deterministic classifier per spec §3.5 truth table (7 rows).

    Signature tracks BOTH corpus IDs so row 6 (same backend, different
    corpora) can be distinguished from row 1 (same backend, same corpus).
    """
    if not fell_back:
        return "none"
    # Row 6: same backend, different corpora
    if (
        primary == served
        and primary_corpus_id is not None
        and served_corpus_id is not None
        and primary_corpus_id != served_corpus_id
    ):
        return "different"
    if primary == served:
        return "same"
    if primary == "gemini_fs" and served == "exa":
        return "broader" if primary_corpus_id else "same"
    if primary == "exa" and served == "gemini_fs":
        return "different"
    return "different"


def select_backends(
    corpus_id: str | None,
    constraints: ResearchConstraints | None,
    registered: dict[str, BackendAdapter],
) -> list[BackendAdapter]:
    """Pick backend adapters in fallback order.

    Rules:
    - preferred_backend wins, others follow in default order
    - corpus_id requires the "upload" capability (filters out web-only backends)
    - returns [] if no eligible backends
    """
    c = constraints or {}
    preferred = c.get("preferred_backend")

    # Ignore invalid preferences — an unregistered backend name must not bypass
    # the upload-capability filter that protects corpus-based queries.
    if preferred and preferred not in registered:
        preferred = None

    if preferred:
        order = [preferred] + [b for b in _DEFAULT_ORDER_WITH_CORPUS if b != preferred]
    elif corpus_id is not None:
        order = list(_DEFAULT_ORDER_WITH_CORPUS)
    else:
        order = list(_DEFAULT_ORDER_WEB_ONLY)

    out: list[BackendAdapter] = []
    for backend_id in order:
        adapter = registered.get(backend_id)
        if adapter is None:
            continue
        # Filter non-upload backends when corpus_id is set, UNLESS a preferred
        # backend is explicitly chosen — preference opts into scope-broadening
        # fallback (Exa becomes a valid fallback even though it cannot serve
        # the corpus; the fallback_scope classifier flags this as "broader").
        if corpus_id is not None and not preferred and "upload" not in adapter.capabilities:
            continue
        out.append(adapter)
    return out


_RECOVERY_HINTS: dict[RecoveryEnum, str] = {
    RecoveryEnum.RATE_LIMITED: "Wait then retry, or accept fallback result.",
    RecoveryEnum.QUOTA_EXCEEDED: "Check API quota at provider dashboard.",
    RecoveryEnum.NETWORK_TIMEOUT: "Retry with longer timeout.",
    RecoveryEnum.AUTH_INVALID: "Check API key. Run: refcast auth",
    RecoveryEnum.CORPUS_NOT_FOUND: "Verify corpus_id with corpus.list",
    RecoveryEnum.EMPTY_CORPUS: "Upload files to the corpus first.",
    RecoveryEnum.BACKEND_UNAVAILABLE: "Backend temporarily unavailable; retry later.",
    RecoveryEnum.SCHEMA_MISMATCH: "Backend returned unexpected schema; report bug.",
    RecoveryEnum.PARSE_ERROR: "Backend response unparseable; trying fallback.",
    RecoveryEnum.INDEXING_IN_PROGRESS: "Poll corpus.status until indexed=true.",
    RecoveryEnum.FILE_TOO_LARGE: "Split file under 100MB before upload.",
    RecoveryEnum.UNSUPPORTED_FORMAT: "Use PDF, TXT, HTML, or DOCX.",
    RecoveryEnum.PARTIAL_INDEX: "Some files failed to index; results from indexed subset.",
    RecoveryEnum.UNKNOWN: "Unexpected error; check raw field for details.",
}


def _hint_for(code: RecoveryEnum) -> str:
    return _RECOVERY_HINTS.get(code, "Unknown error.")


def _scope_shift_warning(
    scope: FallbackScope,
    primary_backend: str,
    served_backend: str,
    corpus_id: str | None,
) -> StructuredError:
    """Surface scope-broadening or scope-different fallbacks loudly in warnings[].

    Rationale (Codex audit, 2026-04-17): `fallback_scope` is a field on the
    result, but agents that don't inspect it silently accept web results for a
    corpus query. This warning forces the scope shift into the warnings list
    that every agent processes.
    """
    if scope == "broader":
        msg = (
            f"Query answered from a broader source ({served_backend}) because "
            f"primary ({primary_backend}) failed. Original corpus_id={corpus_id} "
            f"was NOT queried."
        )
    else:
        msg = (
            f"Query answered from a fundamentally different source "
            f"({served_backend} instead of {primary_backend}). Treat with caution."
        )
    return StructuredError(
        code=RecoveryEnum.UNKNOWN,
        message=msg,
        recovery_hint=(
            "Inspect result.fallback_scope. If strict corpus matching is "
            "required, handle this case in your agent."
        ),
        recovery_action="user_action",
        fallback_used=True,
        partial_results=True,
        retry_after_ms=None,
        backend=served_backend,
        raw={
            "scope": scope,
            "primary": primary_backend,
            "served": served_backend,
            "corpus_id": corpus_id,
        },
    )


def _be_to_struct(e: BackendError, fallback_used: bool) -> StructuredError:
    action = cast(RecoveryAction, e.recovery_action)
    return StructuredError(
        code=e.code,
        message=e.message,
        recovery_hint=_hint_for(e.code),
        recovery_action=action,
        fallback_used=fallback_used,
        partial_results=False,
        retry_after_ms=e.retry_after_ms,
        backend=e.backend,
        raw=redact_raw(e.raw),
    )


def _failed_result(
    code: RecoveryEnum,
    message: str,
    recovery_action: RecoveryAction,
    *,
    warnings: list[StructuredError],
    retry_after_ms: int | None = None,
    backend: str | None = None,
    raw: dict[str, Any] | None = None,
) -> ResearchResult:
    error = StructuredError(
        code=code,
        message=message,
        recovery_hint=_hint_for(code),
        recovery_action=recovery_action,
        fallback_used=False,
        partial_results=False,
        retry_after_ms=retry_after_ms,
        backend=backend,
        raw=redact_raw(raw or {}),
    )
    return ResearchResult(
        answer="",
        citations=[],
        backend_used=backend or "",
        latency_ms=0,
        cost_cents=0.0,
        fallback_scope="none",
        warnings=warnings,
        error=error,
    )


async def execute_research(
    query: str,
    corpus_id: str | None,
    constraints: ResearchConstraints | None,
    registered: dict[str, BackendAdapter],
) -> ResearchResult:
    """Serial fallback orchestrator.

    Iterates backends from `select_backends` order; on BackendError with
    recovery_action='fallback' and more candidates remaining, records a warning
    and tries the next. Otherwise returns the failed result.
    """
    backends = select_backends(corpus_id, constraints, registered)
    if not backends:
        return _failed_result(
            RecoveryEnum.BACKEND_UNAVAILABLE,
            "No backends configured for this query",
            "user_action",
            warnings=[],
        )

    primary = backends[0]
    warnings: list[StructuredError] = []

    for idx, backend in enumerate(backends):
        is_last = idx == len(backends) - 1
        try:
            result = await backend.execute(query, corpus_id, constraints)
        except BackendError as e:
            action = cast(RecoveryAction, e.recovery_action)
            if action != "fallback" or is_last:
                return _failed_result(
                    e.code,
                    e.message,
                    action,
                    warnings=warnings,
                    retry_after_ms=e.retry_after_ms,
                    backend=e.backend,
                    raw=e.raw,
                )
            warnings.append(_be_to_struct(e, fallback_used=True))
            continue
        except Exception as e:
            # Wrap unexpected errors so they surface as StructuredError
            wrapped = BackendError(
                RecoveryEnum.UNKNOWN,
                f"Unexpected error in {backend.id}: {e}",
                backend=backend.id,
                recovery_action="fallback",
                raw={"type": type(e).__name__, "message": str(e)},
            )
            if is_last:
                return _failed_result(
                    wrapped.code,
                    wrapped.message,
                    cast(RecoveryAction, wrapped.recovery_action),
                    warnings=warnings,
                    backend=wrapped.backend,
                    raw=wrapped.raw,
                )
            warnings.append(_be_to_struct(wrapped, fallback_used=True))
            continue

        # Success path
        scope = classify_scope_shift(
            primary=primary.id,
            served=backend.id,
            primary_corpus_id=corpus_id,
            served_corpus_id=corpus_id if "upload" in backend.capabilities else None,
            fell_back=(idx > 0),
        )
        result["fallback_scope"] = scope
        existing = result.get("warnings") or []
        combined: list[StructuredError] = warnings + list(existing)
        # Loudly surface scope shifts — agents shouldn't have to check
        # fallback_scope silently to learn they got a different-source answer.
        if scope in ("broader", "different"):
            combined.append(
                _scope_shift_warning(
                    scope=scope,
                    primary_backend=primary.id,
                    served_backend=backend.id,
                    corpus_id=corpus_id,
                )
            )
        result["warnings"] = combined
        return result

    # Defensive: unreachable in practice
    return _failed_result(
        RecoveryEnum.BACKEND_UNAVAILABLE,
        "All backends exhausted",
        "user_action",
        warnings=warnings,
    )
