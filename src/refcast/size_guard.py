"""25KB response-size enforcement per spec §5.2."""

from __future__ import annotations

import json
from typing import Any

from refcast.models import RecoveryEnum, StructuredError

RESPONSE_SIZE_LIMIT_BYTES = 25 * 1024


def _serialized_size(payload: Any) -> int:
    return len(json.dumps(payload, default=str).encode("utf-8"))


def enforce_response_size(result: dict[str, Any]) -> dict[str, Any]:
    """Truncate citations source-order until payload <= 25KB. Answer preserved."""
    if _serialized_size(result) <= RESPONSE_SIZE_LIMIT_BYTES:
        return result

    out = dict(result)
    citations = list(out.get("citations", []))
    warnings = list(out.get("warnings", []))
    original_count = len(citations)

    while (
        citations
        and _serialized_size({**out, "citations": citations, "warnings": warnings})
        > RESPONSE_SIZE_LIMIT_BYTES
    ):
        citations.pop()

    if len(citations) < original_count:
        truncation_warning: StructuredError = {
            "code": RecoveryEnum.UNKNOWN,
            "message": "Response truncated at 25KB (citations dropped from tail).",
            "recovery_hint": "Narrow the query or request fewer citations.",
            "recovery_action": "user_action",
            "fallback_used": False,
            "partial_results": True,
            "retry_after_ms": None,
            "backend": out.get("backend_used"),
            "raw": {},
        }
        warnings.append(truncation_warning)

    out["citations"] = citations
    out["warnings"] = warnings

    # Last resort: if answer alone exceeds the limit (no/few citations to drop),
    # truncate the answer text itself so the response always fits within 25KB.
    while _serialized_size(out) > RESPONSE_SIZE_LIMIT_BYTES and len(out.get("answer", "")) > 100:
        out["answer"] = out["answer"][: len(out["answer"]) // 2] + "... [truncated]"

    return out
