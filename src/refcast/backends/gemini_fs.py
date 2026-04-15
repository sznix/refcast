"""Gemini File Search backend adapter."""

from __future__ import annotations

import datetime as _dt
import time
import uuid
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types as genai_types

from refcast.backends.base import BackendError
from refcast.models import (
    Citation,
    CorpusDeleteResult,
    CorpusStatusResult,
    CorpusSummary,
    CorpusUploadResult,
    RecoveryEnum,
    ResearchConstraints,
    ResearchResult,
)

MAX_FILE_BYTES = 100 * 1024 * 1024
ALLOWED_SUFFIXES = frozenset({".pdf", ".txt", ".html", ".docx"})

# Gemini 2.5 Flash pricing (April 2026): $0.30 / 1M input, $2.50 / 1M output
GEMINI_FLASH_INPUT_CENTS_PER_1K = 0.03
GEMINI_FLASH_OUTPUT_CENTS_PER_1K = 0.25

# Default retry-after for RATE_LIMITED when API doesn't supply one.
_DEFAULT_RATE_LIMIT_RETRY_MS = 30_000


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

    async def delete_corpus(self, corpus_id: str) -> CorpusDeleteResult:
        rec = self._states.get(corpus_id)
        if rec is None:
            raise BackendError(
                RecoveryEnum.CORPUS_NOT_FOUND,
                f"Unknown corpus: {corpus_id}",
                backend=self.id,
                recovery_action="user_action",
            )
        files_removed: int = rec["file_count"]
        del self._states[corpus_id]
        return {
            "corpus_id": corpus_id,
            "deleted": True,
            "files_removed": files_removed,
        }

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
        c = constraints or {}
        max_citations = c.get("max_citations", 10)
        require_citation = c.get("require_citation", True)

        cfg: genai_types.GenerateContentConfig | None = None
        if corpus_id:
            cfg = genai_types.GenerateContentConfig(
                tools=[
                    genai_types.Tool(
                        file_search=genai_types.FileSearch(
                            file_search_store_names=[f"fileSearchStores/{corpus_id}"],
                        )
                    )
                ],
            )

        start = time.monotonic()
        try:
            client = genai.Client(api_key=self._api_key)
            response = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=query,
                config=cfg,
            )
        except Exception as e:
            raise self._map_exception(e) from e

        latency_ms = int((time.monotonic() - start) * 1000)

        candidates = response.candidates or []
        if not candidates:
            raise BackendError(
                RecoveryEnum.PARSE_ERROR,
                "Backend returned no candidates",
                backend=self.id,
                recovery_action="fallback",
                raw={},
            )
        candidate = candidates[0]
        content = candidate.content
        parts = (content.parts if content is not None else None) or []
        answer_parts: list[str] = []
        for part in parts:
            text = getattr(part, "text", None)
            if text:
                answer_parts.append(text)
        answer = "".join(answer_parts)

        citations: list[Citation] = (
            self._normalize_citations(
                candidate.grounding_metadata,
                corpus_id=corpus_id,
                limit=max_citations,
            )
            if candidate.grounding_metadata
            else []
        )

        if require_citation and not citations:
            raise BackendError(
                RecoveryEnum.PARSE_ERROR,
                "Backend returned 0 citations with require_citation=True",
                backend=self.id,
                recovery_action="fallback",
                raw={},
            )

        usage = response.usage_metadata
        prompt_tokens = (usage.prompt_token_count if usage is not None else None) or 0
        output_tokens = (usage.candidates_token_count if usage is not None else None) or 0
        cost_cents = round(
            (prompt_tokens / 1000) * GEMINI_FLASH_INPUT_CENTS_PER_1K
            + (output_tokens / 1000) * GEMINI_FLASH_OUTPUT_CENTS_PER_1K,
            4,
        )

        return {
            "answer": answer,
            "citations": citations,
            "backend_used": self.id,
            "latency_ms": latency_ms,
            "cost_cents": cost_cents,
            "fallback_scope": "none",
            "warnings": [],
            "error": None,
        }

    def _normalize_citations(
        self,
        grounding_metadata: Any,
        corpus_id: str | None,
        limit: int,
    ) -> list[Citation]:
        chunks = list(grounding_metadata.grounding_chunks or [])
        supports = list(grounding_metadata.grounding_supports or [])
        out: list[Citation] = []
        for support in supports[:limit]:
            indices = list(support.grounding_chunk_indices or [])
            if not indices:
                continue
            idx = indices[0]
            chunk = chunks[idx] if 0 <= idx < len(chunks) else None
            ctx = getattr(chunk, "retrieved_context", None) if chunk is not None else None
            uri = getattr(ctx, "uri", None) if ctx is not None else None
            title = getattr(ctx, "title", None) if ctx is not None else None
            source_url = uri or f"gemini://corpus/{corpus_id or 'unknown'}/chunk/{idx}"
            seg = support.segment
            out.append(
                {
                    "text": seg.text,
                    "source_url": source_url,
                    "author": None,
                    "date": None,
                    "confidence": None,
                    "backend_used": self.id,
                    "raw": {
                        "chunk_index": idx,
                        "title": title,
                        "segment_range": [seg.start_index, seg.end_index],
                    },
                }
            )
        return out

    def _map_exception(self, e: Exception) -> BackendError:
        text = str(e)
        lower = text.lower()

        # Priority 1: empty corpus (FAILED_PRECONDITION / 'empty')
        if "failed_precondition" in lower or "empty" in lower:
            return BackendError(
                RecoveryEnum.EMPTY_CORPUS,
                text,
                backend=self.id,
                recovery_action="user_action",
                raw={"original": text},
            )
        # Priority 2: not found
        if "not_found" in lower or "404" in text:
            return BackendError(
                RecoveryEnum.CORPUS_NOT_FOUND,
                text,
                backend=self.id,
                recovery_action="user_action",
                raw={"original": text},
            )
        # Priority 3: rate limited / quota
        if "429" in text or "resource_exhausted" in lower or "quota" in lower:
            return BackendError(
                RecoveryEnum.RATE_LIMITED,
                text,
                backend=self.id,
                recovery_action="retry",
                retry_after_ms=_DEFAULT_RATE_LIMIT_RETRY_MS,
                raw={"original": text},
            )
        # Priority 4: auth invalid
        if "401" in text or "unauthenticated" in lower or "unauthorized" in lower:
            return BackendError(
                RecoveryEnum.AUTH_INVALID,
                text,
                backend=self.id,
                recovery_action="user_action",
                raw={"original": text},
            )
        # Priority 5: 5xx / network
        if any(code in text for code in ("500", "502", "503", "504")) or "timeout" in lower:
            return BackendError(
                RecoveryEnum.BACKEND_UNAVAILABLE,
                text,
                backend=self.id,
                recovery_action="fallback",
                raw={"original": text},
            )
        return BackendError(
            RecoveryEnum.UNKNOWN,
            text,
            backend=self.id,
            recovery_action="fallback",
            raw={"original": text},
        )
