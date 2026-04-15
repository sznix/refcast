"""Exa backend adapter — web search with relevance-scored citations."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from exa_py import Exa

from refcast.backends.base import BackendError
from refcast.models import Citation, RecoveryEnum, ResearchConstraints, ResearchResult

# Exa search-with-contents pricing (April 2026): ~$7 / 1K queries = 0.7 cents per query.
EXA_COST_CENTS_PER_QUERY = 0.7

# Default retry-after when API does not supply one.
_DEFAULT_RATE_LIMIT_RETRY_MS = 30_000


class ExaBackend:
    """Backend adapter for Exa web search.

    Exa searches the entire public web — there is no concept of a corpus.
    ``corpus_id`` is always ignored. Relevance scores from the SDK are
    surfaced as ``Citation.confidence`` (unlike Gemini which sets it to None).
    """

    id = "exa"
    capabilities = frozenset({"search", "cite"})

    def __init__(self, api_key: str | None) -> None:
        if not api_key:
            raise BackendError(
                RecoveryEnum.AUTH_INVALID,
                "EXA_API_KEY not set",
                backend=self.id,
                recovery_action="user_action",
            )
        self._api_key = api_key

    async def execute(
        self,
        query: str,
        corpus_id: str | None,  # noqa: ARG002  — Exa has no corpus concept
        constraints: ResearchConstraints | None,
    ) -> ResearchResult:
        c: ResearchConstraints = constraints or {}
        max_citations: int = c.get("max_citations", 10)
        require_citation: bool = c.get("require_citation", True)

        start = time.monotonic()
        try:
            client = Exa(api_key=self._api_key)
            response = await asyncio.to_thread(
                client.search_and_contents,
                query,
                num_results=max_citations,
            )
        except Exception as e:
            raise self._map_exception(e) from e

        latency_ms = int((time.monotonic() - start) * 1000)

        citations = self._normalize_citations(response.results, limit=max_citations)

        if require_citation and not citations:
            raise BackendError(
                RecoveryEnum.PARSE_ERROR,
                "Exa returned 0 results with require_citation=True",
                backend=self.id,
                recovery_action="fallback",
                raw={},
            )

        answer = f"{citations[0]['text'][:500]}..." if citations else ""

        return {
            "answer": answer,
            "citations": citations,
            "backend_used": self.id,
            "latency_ms": latency_ms,
            "cost_cents": EXA_COST_CENTS_PER_QUERY,
            "fallback_scope": "none",
            "warnings": [],
            "error": None,
        }

    def _normalize_citations(self, results: list[Any], limit: int) -> list[Citation]:
        raise NotImplementedError

    def _map_exception(self, e: Exception) -> BackendError:
        raise NotImplementedError
