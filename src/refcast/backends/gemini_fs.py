"""Gemini File Search backend adapter."""

from __future__ import annotations

import contextlib
import datetime as _dt
import re
import time
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
    StructuredError,
)

MAX_FILE_BYTES = 100 * 1024 * 1024
ALLOWED_SUFFIXES = frozenset({".pdf", ".txt", ".html", ".docx"})

# Gemini 2.5 Flash pricing (April 2026): $0.30 / 1M input, $2.50 / 1M output
GEMINI_FLASH_INPUT_CENTS_PER_1K = 0.03
GEMINI_FLASH_OUTPUT_CENTS_PER_1K = 0.25

# Default retry-after for RATE_LIMITED when API doesn't supply one.
_DEFAULT_RATE_LIMIT_RETRY_MS = 30_000

# Prefix used by google-genai for File Search Store resource names.
_FS_STORE_PREFIX = "fileSearchStores/"


def _short_id(store_name: str) -> str:
    """Extract short id from a fileSearchStores/<id> resource name."""
    if store_name.startswith(_FS_STORE_PREFIX):
        return store_name[len(_FS_STORE_PREFIX) :]
    return store_name


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
        # Local cache mapping our corpus_id -> metadata needed to talk to the
        # File Search Stores API. The authoritative state lives server-side;
        # this cache just records the things the SDK doesn't readily expose
        # in list responses (original file paths, per-file operation names).
        # Shape:
        #   {
        #     "<corpus_id>": {
        #       "corpus_id": str,
        #       "store_name": "fileSearchStores/<id>",
        #       "operation_id": str,          # last upload op name (v0.1 contract)
        #       "operations": [Operation],    # per-file LRO handles (for poll)
        #       "files": [str],
        #       "file_count": int,
        #       "indexed_file_count": int,    # cached from last poll (tests)
        #       "indexed": bool,              # cached from last poll (tests)
        #       "total_bytes": int,
        #       "created_at": str,
        #       "started_at": str,
        #     }
        #   }
        self._states: dict[str, dict[str, Any]] = {}

    def _client(self) -> genai.Client:
        return genai.Client(api_key=self._api_key)

    async def upload_files(self, files: list[str]) -> CorpusUploadResult:
        if not files:
            raise BackendError(
                RecoveryEnum.UNSUPPORTED_FORMAT,
                "No files provided — pass at least one file path",
                backend=self.id,
                recovery_action="user_action",
            )

        for p in files:
            self._validate_path(p)

        total_bytes = sum(Path(f).stat().st_size for f in files)
        started = _dt.datetime.now(_dt.UTC).isoformat()

        # Create a fresh store, then upload each file. Both operations go
        # through the real File Search Stores API.
        store_name, operations = await self._start_upload_operation(files, started)
        corpus_id = _short_id(store_name)

        # operation_id contract: return the *last* upload op's name so callers
        # have a concrete LRO identifier. Per-file ops are kept in self._states
        # for poll_status. If no files were uploaded (degenerate case), fall
        # back to the store name itself.
        op_id = (operations[-1].name or store_name) if operations else store_name

        self._states[corpus_id] = {
            "corpus_id": corpus_id,
            "store_name": store_name,
            "operation_id": op_id,
            "operations": list(operations),
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
        operations: list[Any] = rec.get("operations", [])

        indexed_count = 0
        failed_count = 0
        warnings: list[StructuredError] = []

        if operations:
            client = self._client()
            refreshed: list[Any] = []
            for op in operations:
                try:
                    updated = await client.aio.operations.get(op)
                except Exception as e:
                    raise self._map_exception(e) from e
                refreshed.append(updated)
                if updated.done:
                    if updated.error:
                        failed_count += 1
                        warnings.append(
                            {
                                "code": RecoveryEnum.PARTIAL_INDEX,
                                "message": f"Upload operation failed: {updated.error}",
                                "recovery_hint": (
                                    "Some files failed to index; results from indexed subset."
                                ),
                                "recovery_action": "user_action",
                                "fallback_used": False,
                                "partial_results": True,
                                "retry_after_ms": None,
                                "backend": self.id,
                                "raw": {"operation_name": updated.name, "error": updated.error},
                            }
                        )
                    else:
                        indexed_count += 1
            rec["operations"] = refreshed

        all_done = bool(operations) and all(op.done for op in rec["operations"])
        indexed = all_done and failed_count == 0
        rec["indexed_file_count"] = indexed_count
        rec["indexed"] = indexed

        progress = (indexed_count / file_count) if file_count else 0.0
        return {
            "corpus_id": corpus_id,
            "indexed": indexed,
            "file_count": file_count,
            "indexed_file_count": indexed_count,
            "progress": progress,
            "warnings": warnings,
            "last_checked_at": _dt.datetime.now(_dt.UTC).isoformat(),
        }

    async def list_corpora(self) -> list[CorpusSummary]:
        out: list[CorpusSummary] = []
        try:
            client = self._client()
            pager = await client.aio.file_search_stores.list()
        except Exception as e:
            raise self._map_exception(e) from e

        async for store in pager:
            store_name = store.name or ""
            cid = _short_id(store_name)
            local = self._states.get(cid, {})

            # Prefer server-side counts when present; fall back to local cache.
            active = store.active_documents_count
            pending = store.pending_documents_count
            failed = store.failed_documents_count
            indexed_count = active if active is not None else local.get("indexed_file_count", 0)
            file_count_parts = [x for x in (active, pending, failed) if x is not None]
            file_count = sum(file_count_parts) if file_count_parts else local.get("file_count", 0)

            size_bytes = store.size_bytes
            total_bytes = size_bytes if size_bytes is not None else local.get("total_bytes", 0)

            created_at = (
                store.create_time.isoformat()
                if store.create_time is not None
                else local.get("created_at") or _dt.datetime.now(_dt.UTC).isoformat()
            )

            out.append(
                {
                    "corpus_id": cid,
                    "name": store.display_name,
                    "file_count": int(file_count),
                    "indexed_file_count": int(indexed_count),
                    "total_bytes": int(total_bytes),
                    "created_at": created_at,
                    "backend": "gemini_fs",
                }
            )
        return out

    async def delete_corpus(self, corpus_id: str) -> CorpusDeleteResult:
        rec = self._states.get(corpus_id)
        # If we don't have a local record we can still try to delete via the
        # conventional fileSearchStores/<id> name — this covers stores we
        # didn't create in this process.
        store_name = rec["store_name"] if rec is not None else f"{_FS_STORE_PREFIX}{corpus_id}"
        files_removed = rec["file_count"] if rec is not None else 0

        try:
            client = self._client()
            await client.aio.file_search_stores.delete(name=store_name)
        except Exception as e:
            # Re-map: 404 -> CORPUS_NOT_FOUND (user_action).
            mapped = self._map_exception(e)
            if mapped.code == RecoveryEnum.CORPUS_NOT_FOUND:
                # Clean local cache on NOT_FOUND so state stays consistent.
                self._states.pop(corpus_id, None)
            raise mapped from e

        self._states.pop(corpus_id, None)
        return {
            "corpus_id": corpus_id,
            "deleted": True,
            "files_removed": files_removed,
        }

    def _mark_complete(self, corpus_id: str) -> None:
        """Test-only helper — marks an in-memory corpus as indexed for unit tests."""
        rec = self._states.get(corpus_id)
        if rec is None:
            return
        rec["indexed_file_count"] = rec["file_count"]
        rec["indexed"] = True
        # Also flip any cached operation handles so a subsequent poll_status
        # (if exercised) would see them as done. Real tests that call this
        # helper don't touch the network.
        for op in rec.get("operations", []):
            try:
                op.done = True
                op.error = None
            except Exception:
                pass

    def _validate_path(self, path: str) -> None:
        raw = Path(path)
        if not raw.is_absolute():
            raise BackendError(
                RecoveryEnum.UNSUPPORTED_FORMAT,
                f"Path must be absolute: {path}",
                backend=self.id,
                recovery_action="user_action",
            )
        p = raw.resolve()
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

    async def _start_upload_operation(
        self, files: list[str], started: str
    ) -> tuple[str, list[Any]]:
        """Create a new File Search Store and kick off per-file uploads.

        Returns (store_name, list_of_UploadToFileSearchStoreOperation).
        """
        client = self._client()
        display_name = f"refcast-{started}"
        try:
            store = await client.aio.file_search_stores.create(
                config=genai_types.CreateFileSearchStoreConfig(display_name=display_name),
            )
        except Exception as e:
            raise self._map_exception(e) from e

        store_name = store.name
        if not store_name:
            raise BackendError(
                RecoveryEnum.BACKEND_UNAVAILABLE,
                "File search store creation returned no name",
                backend=self.id,
                recovery_action="fallback",
            )

        operations: list[Any] = []
        for file_path in files:
            try:
                op = await client.aio.file_search_stores.upload_to_file_search_store(
                    file_search_store_name=store_name,
                    file=file_path,
                )
            except Exception as e:
                # Clean up the orphaned store before propagating.
                with contextlib.suppress(Exception):
                    await client.aio.file_search_stores.delete(name=store_name)
                raise self._map_exception(e) from e
            operations.append(op)
        return store_name, operations

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
                            file_search_store_names=[f"{_FS_STORE_PREFIX}{corpus_id}"],
                        )
                    )
                ],
            )

        start = time.monotonic()
        try:
            client = self._client()
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
            if seg is None:
                continue
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

        # Priority 1: empty corpus — requires 'failed_precondition' AND ('empty' or 'no documents')
        if "failed_precondition" in lower and ("empty" in lower or "no documents" in lower):
            return BackendError(
                RecoveryEnum.EMPTY_CORPUS,
                text,
                backend=self.id,
                recovery_action="user_action",
                raw={"original": text},
            )
        # Priority 2: not found
        if "not_found" in lower or re.search(r"\b404\b", text):
            return BackendError(
                RecoveryEnum.CORPUS_NOT_FOUND,
                text,
                backend=self.id,
                recovery_action="user_action",
                raw={"original": text},
            )
        # Priority 3: rate limited / quota
        if re.search(r"\b429\b", text) or "resource_exhausted" in lower or "quota" in lower:
            return BackendError(
                RecoveryEnum.RATE_LIMITED,
                text,
                backend=self.id,
                recovery_action="retry",
                retry_after_ms=_DEFAULT_RATE_LIMIT_RETRY_MS,
                raw={"original": text},
            )
        # Priority 4: auth invalid
        if re.search(r"\b401\b", text) or "unauthenticated" in lower or "unauthorized" in lower:
            return BackendError(
                RecoveryEnum.AUTH_INVALID,
                text,
                backend=self.id,
                recovery_action="user_action",
                raw={"original": text},
            )
        # Priority 5: 5xx / network
        if (
            any(re.search(r"\b" + code + r"\b", text) for code in ("500", "502", "503", "504"))
            or "timeout" in lower
        ):
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
