"""Serial-fallback research router."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from refcast.backends.base import BackendAdapter
    from refcast.models import ResearchConstraints

FallbackScope = Literal["none", "same", "broader", "different"]

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
        if corpus_id is not None and "upload" not in adapter.capabilities:
            continue
        out.append(adapter)
    return out
