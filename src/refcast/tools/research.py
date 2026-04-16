"""MCP tool: research — broker query across backends with serial fallback."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refcast.backends.base import BackendError
from refcast.merge import merge_citations
from refcast.models import RecoveryEnum, ResearchConstraints, StructuredError
from refcast.perspectives import generate_perspectives
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

        depth = (typed_constraints or {}).get("depth", "quick")

        if depth == "deep" and _gemini_api_key:
            out = await _deep_research(
                query, corpus_id, typed_constraints, backends, _gemini_api_key
            )
        else:
            out = await _quick_research(
                query, corpus_id, typed_constraints, backends, _gemini_api_key
            )

        if partial_warning is not None:
            existing_warnings = out.get("warnings") or []
            pw_list: list[StructuredError] = list(existing_warnings)
            pw_list.append(partial_warning)
            out["warnings"] = pw_list

        return enforce_response_size(out)


async def _quick_research(
    query: str,
    corpus_id: str | None,
    typed_constraints: ResearchConstraints | None,
    backends: dict[str, BackendAdapter],
    gemini_api_key: str | None,
) -> dict[str, Any]:
    """Quick mode: single execute_research + optional synthesis."""
    result = await execute_research(query, corpus_id, typed_constraints, backends)
    out: dict[str, Any] = dict(result)

    if gemini_api_key and out.get("error") is None:
        synth_answer, synth_cost, synth_ms = await synthesize(
            query, out["citations"], gemini_api_key
        )
        if synth_answer is not None and synth_answer != "":
            out["answer"] = synth_answer
            out["cost_cents"] = round(out["cost_cents"] + synth_cost, 4)
            out["latency_ms"] += synth_ms
        elif synth_answer is None:
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
        # else: synth_answer == "" (0 citations) — keep raw answer, don't overwrite

    return out


async def _deep_research(
    query: str,
    corpus_id: str | None,
    typed_constraints: ResearchConstraints | None,
    backends: dict[str, BackendAdapter],
    gemini_api_key: str,
) -> dict[str, Any]:
    """Deep mode: multi-perspective fan-out + merge + synthesis."""
    # 1. Generate sub-queries from multiple perspectives
    sub_queries = await generate_perspectives(query, gemini_api_key)

    # 2. Run each sub-query through the router
    sub_results: list[dict[str, Any]] = []
    all_warnings: list[StructuredError] = []
    for sq in sub_queries:
        r = await execute_research(sq, corpus_id, typed_constraints, backends)
        sub_results.append(dict(r))
        all_warnings.extend(r.get("warnings") or [])

    # 3. Propagate error when ALL sub-queries failed (don't mask real failures)
    if sub_results and all(r.get("error") is not None for r in sub_results):
        return sub_results[0]  # propagate the first real error

    # 4. Merge citations (deduplicate by URL + text prefix)
    merged = merge_citations(sub_results)  # type: ignore[arg-type]

    # 5. Synthesize from merged set using ORIGINAL query
    if merged:
        synth_answer, synth_cost, synth_ms = await synthesize(query, merged, gemini_api_key)
    else:
        synth_answer, synth_cost, synth_ms = "No relevant sources found.", 0.0, 0

    # 6. Build final result
    total_cost = sum(r["cost_cents"] for r in sub_results) + synth_cost
    total_latency = sum(r["latency_ms"] for r in sub_results) + synth_ms
    backend_names = {r["backend_used"] for r in sub_results if r["backend_used"]}
    first_answer = sub_results[0]["answer"] if sub_results else ""

    return {
        "answer": synth_answer or first_answer,
        "citations": merged,
        "backend_used": ", ".join(sorted(backend_names)),
        "latency_ms": total_latency,
        "cost_cents": round(total_cost, 4),
        "fallback_scope": "none",
        "warnings": all_warnings,
        "error": None,
    }
