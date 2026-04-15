"""Serial-fallback research router."""

from __future__ import annotations

from typing import Literal

FallbackScope = Literal["none", "same", "broader", "different"]


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
