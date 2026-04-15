"""Gemini File Search backend adapter."""

from __future__ import annotations

import datetime as _dt
import uuid
from pathlib import Path
from typing import Any

from refcast.backends.base import BackendError
from refcast.models import (
    CorpusStatusResult,
    CorpusSummary,
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
        # In-memory tracker until google-genai operations.get is wired up.
        # Each entry maps corpus_id -> mutable record carrying counts + metadata.
        self._states: dict[str, dict[str, Any]] = {}

    async def upload_files(self, files: list[str]) -> CorpusUploadResult:
        for p in files:
            self._validate_path(p)

        corpus_id = f"cor_{uuid.uuid4().hex[:12]}"
        op_id = await self._start_upload_operation(corpus_id, files)
        started = _dt.datetime.now(_dt.UTC).isoformat()

        total_bytes = sum(Path(f).stat().st_size for f in files)
        self._states[corpus_id] = {
            "corpus_id": corpus_id,
            "operation_id": op_id,
            "files": list(files),
            "file_count": len(files),
            "indexed_file_count": 0,
            "indexed": False,
            "total_bytes": total_bytes,
            "created_at": started,
            "started_at": started,
        }

        return {
            "corpus_id": corpus_id,
            "operation_id": op_id,
            "status": "indexing",
            "file_count": len(files),
            "started_at": started,
        }

    async def poll_status(self, corpus_id: str) -> CorpusStatusResult:
        rec = self._states.get(corpus_id)
        if rec is None:
            raise BackendError(
                RecoveryEnum.CORPUS_NOT_FOUND,
                f"Unknown corpus: {corpus_id}",
                backend=self.id,
                recovery_action="user_action",
            )
        file_count: int = rec["file_count"]
        indexed_count: int = rec["indexed_file_count"]
        progress = (indexed_count / file_count) if file_count else 0.0
        return {
            "corpus_id": corpus_id,
            "indexed": bool(rec["indexed"]),
            "file_count": file_count,
            "indexed_file_count": indexed_count,
            "progress": progress,
            "warnings": [],
            "last_checked_at": _dt.datetime.now(_dt.UTC).isoformat(),
        }

    async def list_corpora(self) -> list[CorpusSummary]:
        out: list[CorpusSummary] = []
        for cid, rec in self._states.items():
            out.append(
                {
                    "corpus_id": cid,
                    "name": rec.get("name"),
                    "file_count": rec["file_count"],
                    "indexed_file_count": rec["indexed_file_count"],
                    "total_bytes": rec["total_bytes"],
                    "created_at": rec["created_at"],
                    "backend": "gemini_fs",
                }
            )
        return out

    def _mark_complete(self, corpus_id: str) -> None:
        """Test/internal helper — simulate operation completion."""
        rec = self._states.get(corpus_id)
        if rec is None:
            return
        rec["indexed_file_count"] = rec["file_count"]
        rec["indexed"] = True

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
