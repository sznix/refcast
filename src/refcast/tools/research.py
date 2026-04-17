"""MCP tool: research — broker query across backends with serial fallback."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from refcast.backends.base import BackendError
from refcast.evidence import build_evidence_pack
from refcast.merge import merge_citations
from refcast.models import RecoveryEnum, ResearchConstraints, StructuredError
from refcast.perspectives import generate_perspectives
from refcast.router import execute_research, select_backends
from refcast.size_guard import enforce_response_size
from refcast.synthesizer import synthesize
from refcast.tools._utils import err_envelope, err_from_backend

# Known per-query minimum costs for pre-flight budget enforcement.
# Exa: fixed 0.7 cents/query (exa-py pricing).
# Gemini FS: variable by tokens; 0.05 is a conservative floor for a trivial query.
_BACKEND_MIN_COSTS: dict[str, float] = {"exa": 0.7, "gemini_fs": 0.05}

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
        unenforced_warnings: list[StructuredError] = []

        # Unenforced-constraint warnings. max_cost_cents IS enforced as of
        # Codex audit 2026-04-17 — pre-flight budget check + post-call overrun
        # warning happen below. date_after remains unenforced until v0.4.
        if constraints is not None and constraints.get("date_after") is not None:
            unenforced_warnings.append(
                {
                    "code": RecoveryEnum.UNKNOWN,
                    "message": "date_after is not enforced in v0.2. It will be ignored.",
                    "recovery_hint": "Remove date_after or wait for a future version.",
                    "recovery_action": "user_action",
                    "fallback_used": False,
                    "partial_results": False,
                    "retry_after_ms": None,
                    "backend": None,
                    "raw": {},
                }
            )

        # Pre-flight corpus-state check when a corpus_id is provided.
        # Skip preflight if user explicitly chose a non-corpus backend (e.g. Exa).
        primary_backend = (constraints or {}).get("preferred_backend")
        if corpus_id is not None and primary_backend != "exa":
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

        # BUG 4: Validate max_citations — clamp to sane range
        if constraints is not None:
            max_cit = constraints.get("max_citations", 10)
            if not isinstance(max_cit, int) or max_cit < 1:
                max_cit = 10
            constraints["max_citations"] = min(max_cit, 50)

        typed_constraints: ResearchConstraints | None = (
            constraints  # type: ignore[assignment]
            if constraints is not None
            else None
        )

        # Codex audit (2026-04-17): pre-flight budget enforcement for max_cost_cents.
        # Previously declared in schema but never enforced.
        max_cost_budget: float | None = None
        if constraints is not None and constraints.get("max_cost_cents") is not None:
            raw_budget = constraints["max_cost_cents"]
            if isinstance(raw_budget, int | float):
                max_cost_budget = float(raw_budget)
                candidates = select_backends(corpus_id, typed_constraints, backends)
                if candidates:
                    cheapest = min(_BACKEND_MIN_COSTS.get(b.id, 0.0) for b in candidates)
                    if cheapest > max_cost_budget:
                        return err_envelope(
                            (
                                f"max_cost_cents={max_cost_budget} is below known minimum "
                                f"{cheapest} for available backends "
                                f"({', '.join(sorted(b.id for b in candidates))})"
                            ),
                            code="quota_exceeded",
                            recovery_action="user_action",
                            backend=None,
                            raw={
                                "max_cost_cents": max_cost_budget,
                                "min_backend_cost": cheapest,
                                "candidates": sorted(b.id for b in candidates),
                            },
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
            # Codex audit (2026-04-17): user asked for deep but we silently
            # fell through to quick because Gemini key is missing. Surface it.
            if depth == "deep" and not _gemini_api_key:
                downgrade_warning: StructuredError = {
                    "code": RecoveryEnum.UNKNOWN,
                    "message": ("depth='deep' requires GEMINI_API_KEY; downgraded to quick mode."),
                    "recovery_hint": (
                        "Configure GEMINI_API_KEY to enable multi-perspective deep mode."
                    ),
                    "recovery_action": "user_action",
                    "fallback_used": False,
                    "partial_results": True,
                    "retry_after_ms": None,
                    "backend": None,
                    "raw": {"requested_depth": "deep", "effective_depth": "quick"},
                }
                downgrade_warnings: list[StructuredError] = list(out.get("warnings") or [])
                downgrade_warnings.append(downgrade_warning)
                out["warnings"] = downgrade_warnings

        if partial_warning is not None:
            existing_warnings = out.get("warnings") or []
            pw_list: list[StructuredError] = list(existing_warnings)
            pw_list.append(partial_warning)
            out["warnings"] = pw_list

        if unenforced_warnings:
            uw_list: list[StructuredError] = list(out.get("warnings") or [])
            uw_list.extend(unenforced_warnings)
            out["warnings"] = uw_list

        # Post-call budget overrun — variable-cost backends (Gemini) may exceed
        # what pre-flight minimums predicted. Surface it loudly, but don't fail
        # (the money is already spent).
        if max_cost_budget is not None and out.get("error") is None:
            actual_cost = float(out.get("cost_cents", 0.0))
            if actual_cost > max_cost_budget:
                overrun: StructuredError = {
                    "code": RecoveryEnum.UNKNOWN,
                    "message": (
                        f"Actual cost {actual_cost} cents exceeded "
                        f"max_cost_cents={max_cost_budget}. Request already executed; "
                        f"tighten budget or use a cheaper backend next time."
                    ),
                    "recovery_hint": (
                        "Set preferred_backend to the cheapest option, or raise max_cost_cents."
                    ),
                    "recovery_action": "user_action",
                    "fallback_used": False,
                    "partial_results": False,
                    "retry_after_ms": None,
                    "backend": out.get("backend_used"),
                    "raw": {
                        "actual_cost_cents": actual_cost,
                        "max_cost_cents": max_cost_budget,
                    },
                }
                overrun_list: list[StructuredError] = list(out.get("warnings") or [])
                overrun_list.append(overrun)
                out["warnings"] = overrun_list

        # v0.3 primitive: attach Reproducible Evidence Transcript AFTER size_guard
        # so source_cids match the actually-returned citations (size_guard may have
        # truncated citations for size reasons).
        out = enforce_response_size(out)
        if out.get("error") is None:
            backend_ids = [
                s.strip() for s in (out.get("backend_used") or "").split(",") if s.strip()
            ]
            out["evidence_pack"] = build_evidence_pack(
                result=out,
                query=query,
                backends=[{"id": bid} for bid in backend_ids],
            )
        return out


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

    # 3b. Convert partial sub-query errors into warnings so they surface
    for partial_r in sub_results:
        err = partial_r.get("error")
        if err is not None:
            all_warnings.append(err)

    # 4. Merge citations (deduplicate by URL + text prefix)
    merged = merge_citations(sub_results)  # type: ignore[arg-type]

    # 5. Synthesize from merged set using ORIGINAL query
    if merged:
        synth_answer, synth_cost, synth_ms = await synthesize(query, merged, gemini_api_key)
    else:
        synth_answer, synth_cost, synth_ms = "No relevant sources found.", 0.0, 0

    # 5b. Add synthesis failure warning in deep mode (mirrors quick mode behaviour)
    if synth_answer is None:
        all_warnings.append(
            {
                "code": RecoveryEnum.UNKNOWN,
                "message": "Deep-mode synthesis skipped — using raw answer from first sub-query.",
                "recovery_hint": "Retry later or check Gemini API key.",
                "recovery_action": "retry",
                "fallback_used": False,
                "partial_results": True,
                "retry_after_ms": None,
                "backend": None,
                "raw": {},
            }
        )

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
