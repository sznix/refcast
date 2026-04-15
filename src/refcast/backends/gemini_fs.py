"""Gemini File Search backend adapter."""

from __future__ import annotations

from refcast.backends.base import BackendError
from refcast.models import RecoveryEnum, ResearchConstraints, ResearchResult


class GeminiFSBackend:
    id = "gemini_fs"
    capabilities = frozenset({"search", "upload", "cite"})

    def __init__(self, api_key: str | None) -> None:
        if not api_key:
            raise BackendError(
                RecoveryEnum.AUTH_INVALID,
                "GEMINI_API_KEY not set",
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
