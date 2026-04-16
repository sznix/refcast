"""MCP tool: research — broker query across backends with serial fallback."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refcast.backends.base import BackendError
from refcast.models import RecoveryEnum, ResearchConstraints, StructuredError
from refcast.router import execute_research
from refcast.size_guard import enforce_response_size
from refcast.synthesizer import synthesize
from refcast.tools._utils import err_from_backend

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from refcast.backends.base import BackendAdapter


_PARTIAL_INDEX_HINT = "Some files failed to index; results from indexed subset."


def _partial_index_warning(*, indexed: int, total: int, corpus_id: str | None) -> StructuredError:
    return {
        "code": RecoveryEnum.PARTIAL_INDEX,
        "message": (
            f"Corpus {corpus_id} partially indexed "
            f"({indexed}/{total} files); answering from indexed subset."
        ),
        "recovery_hint": _PARTIAL_INDEX_HINT,
        "recovery_action": "user_action",
        "fallback_used": False,
        "partial_results": True,
        "retry_after_ms": None,
        "backend": "gemini_fs",
        "raw": {"indexed_file_count": indexed, "file_count": total},
    }


def register(
    mcp: FastMCP,
    backends: dict[str, BackendAdapter],
    gemini_api_key: str | None = None,
) -> None:
    _gemini_api_key = gemini_api_key

    @mcp.tool(name="research")
    async def research(
        query: str,
        corpus_id: str | None = None,
        constraints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Query corpus or web with serial-fallback routing and unified citations."""
        partial_warning: StructuredError | None = None

        # Pre-flight corpus-state check when a corpus_id is provided.
        if corpus_id is not None:
            gemini = backends.get("gemini_fs")
            if gemini is not None:
                try:
                    status = await gemini.poll_status(corpus_id)  # type: ignore[attr-defined]
                except BackendError as e:
                    return err_from_backend(e)

                file_count = int(status.get("file_count", 0))
                indexed_count = int(status.get("indexed_file_count", 0))
                indexed = bool(status.get("indexed", False))

                # EMPTY_CORPUS: zero files ever uploaded.
                if file_count == 0:
                    return err_from_backend(
                        BackendError(
                            RecoveryEnum.EMPTY_CORPUS,
                            f"Corpus {corpus_id} is empty; upload files first.",
                            backend="gemini_fs",
                            recovery_action="user_action",
                        )
                    )
                # INDEXING_IN_PROGRESS: files queued but none indexed yet.
                if indexed_count == 0 and not indexed:
                    return err_from_backend(
                        BackendError(
                            RecoveryEnum.INDEXING_IN_PROGRESS,
                            (
                                f"Corpus {corpus_id} still indexing "
                                f"(0/{file_count}); retry after poll."
                            ),
                            backend="gemini_fs",
                            recovery_action="retry",
                        )
                    )
                # PARTIAL_INDEX: proceed but append a warning.
                if 0 < indexed_count < file_count:
                    partial_warning = _partial_index_warning(
                        indexed=indexed_count,
                        total=file_count,
                        corpus_id=corpus_id,
                    )

        typed_constraints: ResearchConstraints | None = (
            constraints  # type: ignore[assignment]
            if constraints is not None
            else None
        )
        result = await execute_research(query, corpus_id, typed_constraints, backends)
        out: dict[str, Any] = dict(result)

        # Synthesize answer (runs for both quick and deep modes)
        if _gemini_api_key and out.get("error") is None:
            synth_answer, synth_cost, synth_ms = await synthesize(
                query, out["citations"], _gemini_api_key
            )
            if synth_answer is not None:
                out["answer"] = synth_answer
                out["cost_cents"] = round(out["cost_cents"] + synth_cost, 4)
                out["latency_ms"] += synth_ms
            else:
                # Synthesis failed — keep raw answer, add warning
                out["latency_ms"] += synth_ms
                synth_warnings: list[StructuredError] = list(out.get("warnings") or [])
                synth_warnings.append(
                    {
                        "code": RecoveryEnum.UNKNOWN,
                        "message": "Answer synthesis skipped — using raw backend response.",
                        "recovery_hint": "Retry later or check Gemini API key.",
                        "recovery_action": "retry",
                        "fallback_used": False,
                        "partial_results": True,
                        "retry_after_ms": None,
                        "backend": None,
                        "raw": {},
                    }
                )
                out["warnings"] = synth_warnings

        if partial_warning is not None:
            existing_warnings = out.get("warnings") or []
            warnings: list[StructuredError] = list(existing_warnings)
            warnings.append(partial_warning)
            out["warnings"] = warnings

        return enforce_response_size(out)
