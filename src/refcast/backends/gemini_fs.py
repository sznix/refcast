"""Gemini File Search backend adapter."""

from __future__ import annotations

import datetime as _dt
import uuid
from pathlib import Path

from refcast.backends.base import BackendError
from refcast.models import (
    CorpusUploadResult,
    RecoveryEnum,
    ResearchConstraints,
    ResearchResult,
)

MAX_FILE_BYTES = 100 * 1024 * 1024
ALLOWED_SUFFIXES = frozenset({".pdf", ".txt", ".html", ".docx"})


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

    async def upload_files(self, files: list[str]) -> CorpusUploadResult:
        for p in files:
            self._validate_path(p)

        corpus_id = f"cor_{uuid.uuid4().hex[:12]}"
        op_id = await self._start_upload_operation(corpus_id, files)

        return {
            "corpus_id": corpus_id,
            "operation_id": op_id,
            "status": "indexing",
            "file_count": len(files),
            "started_at": _dt.datetime.now(_dt.UTC).isoformat(),
        }

    def _validate_path(self, path: str) -> None:
        p = Path(path)
        if not p.is_absolute():
            raise BackendError(
                RecoveryEnum.UNSUPPORTED_FORMAT,
                f"Path must be absolute: {path}",
                backend=self.id,
                recovery_action="user_action",
            )
        if not p.exists():
            raise BackendError(
                RecoveryEnum.UNSUPPORTED_FORMAT,
                f"File not found: {path}",
                backend=self.id,
                recovery_action="user_action",
            )
        if p.suffix.lower() not in ALLOWED_SUFFIXES:
            raise BackendError(
                RecoveryEnum.UNSUPPORTED_FORMAT,
                f"Unsupported format: {p.suffix}",
                backend=self.id,
                recovery_action="user_action",
            )
        if p.stat().st_size > MAX_FILE_BYTES:
            raise BackendError(
                RecoveryEnum.FILE_TOO_LARGE,
                f"File exceeds 100MB: {path}",
                backend=self.id,
                recovery_action="user_action",
            )

    async def _start_upload_operation(self, corpus_id: str, files: list[str]) -> str:
        """Stub for google-genai upload. Real impl uses client.files.upload(...)."""
        return f"operations/{uuid.uuid4().hex[:12]}"

    async def execute(
        self,
        query: str,
        corpus_id: str | None,
        constraints: ResearchConstraints | None,
    ) -> ResearchResult:
        raise NotImplementedError
