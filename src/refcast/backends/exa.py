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
                type="neural",  # "neural" returns relevance scores; "auto" returns null
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
        """Map Exa SDK Result objects to Citation TypedDicts.

        Handles missing optional fields gracefully:
        - ``author`` may be None for many web pages.
        - ``published_date`` may be None.
        - ``text`` may be None when the SDK is called without text retrieval.
        """
        out: list[Citation] = []
        for result in results[:limit]:
            text: str = getattr(result, "text", None) or ""
            url: str = getattr(result, "url", "") or ""
            title: str | None = getattr(result, "title", None)
            score: float | None = getattr(result, "score", None)
            published_date: str | None = getattr(result, "published_date", None)
            author: str | None = getattr(result, "author", None)

            out.append(
                {
                    "text": text,
                    "source_url": url,
                    "author": author,
                    "date": published_date,
                    "confidence": float(score) if score is not None else None,
                    "backend_used": self.id,
                    "raw": {
                        "title": title,
                    },
                }
            )
        return out

    def _map_exception(self, e: Exception) -> BackendError:
        """Map SDK / HTTP exceptions to BackendError with appropriate RecoveryEnum."""
        text = str(e)
        lower = text.lower()

        # Priority 1: rate limited — 429, "rate limit", or "rate_limited"
        if "429" in text or "rate limit" in lower or "rate_limited" in lower:
            return BackendError(
                RecoveryEnum.RATE_LIMITED,
                text,
                backend=self.id,
                recovery_action="retry",
                retry_after_ms=_DEFAULT_RATE_LIMIT_RETRY_MS,
                raw={"original": text},
            )

        # Priority 2: auth invalid — 401, "unauthorized", "invalid api key"
        if "401" in text or "unauthorized" in lower or "invalid api key" in lower:
            return BackendError(
                RecoveryEnum.AUTH_INVALID,
                text,
                backend=self.id,
                recovery_action="user_action",
                raw={"original": text},
            )

        # Priority 3: server errors and network/timeout issues
        if (
            any(code in text for code in ("500", "502", "503", "504"))
            or "server error" in lower
            or "timeout" in lower
            or "connection" in lower
        ):
            return BackendError(
                RecoveryEnum.BACKEND_UNAVAILABLE,
                text,
                backend=self.id,
                recovery_action="fallback",
                raw={"original": text},
            )

        # Default fallback
        return BackendError(
            RecoveryEnum.UNKNOWN,
            text,
            backend=self.id,
            recovery_action="fallback",
            raw={"original": text},
        )
