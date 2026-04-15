"""Exa backend adapter — web search with relevance-scored citations."""

from __future__ import annotations

from refcast.backends.base import BackendError
from refcast.models import RecoveryEnum, ResearchConstraints, ResearchResult


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
        corpus_id: str | None,
        constraints: ResearchConstraints | None,
    ) -> ResearchResult:
        raise NotImplementedError
