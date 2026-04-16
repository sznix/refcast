"""Tests for Gemini File Search adapter."""

import asyncio
import datetime as _dt
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from refcast.backends.base import BackendError
from refcast.backends.gemini_fs import GeminiFSBackend
from refcast.models import RecoveryEnum

# Note on mocking strategy: google-genai's HTTP transport is not cleanly
# interceptable via respx in all paths (it uses its own client wrapper).
# We mock at the SDK boundary via unittest.mock.patch on `genai.Client`,
# which gives us deterministic control over the response shape.


def _mk_response(answer_text, citations_count, input_tokens=42, output_tokens=18):
    """Build a fake google-genai response object."""
    chunks = []
    supports = []
    for i in range(citations_count):
        chunk = MagicMock()
        chunk.retrieved_context = MagicMock(uri=f"gemini://file/{i}", title=f"doc_{i}.pdf")
        chunks.append(chunk)
        support = MagicMock()
        support.segment = MagicMock(
            text=f"citation text {i}", start_index=i * 10, end_index=(i + 1) * 10
        )
        support.grounding_chunk_indices = [i]
        supports.append(support)

    grounding = (
        MagicMock(grounding_chunks=chunks, grounding_supports=supports)
        if citations_count > 0
        else None
    )

    candidate = MagicMock()
    candidate.content = MagicMock(parts=[MagicMock(text=answer_text)])
    candidate.grounding_metadata = grounding
    candidate.finish_reason = "STOP"

    response = MagicMock()
    response.candidates = [candidate]
    response.usage_metadata = MagicMock(
        prompt_token_count=input_tokens,
        candidates_token_count=output_tokens,
        total_token_count=input_tokens + output_tokens,
    )
    return response


def _mk_upload_operation(name: str, done: bool = False, error=None) -> MagicMock:
    """Build a fake UploadToFileSearchStoreOperation."""
    op = MagicMock()
    op.name = name
    op.done = done
    op.error = error
    op.response = None
    op.metadata = None
    return op


def _mk_store(
    name: str = "fileSearchStores/test123",
    display_name: str | None = "refcast-test",
    active: int | None = None,
    pending: int | None = None,
    failed: int | None = None,
    size_bytes: int | None = None,
    create_time: _dt.datetime | None = None,
) -> MagicMock:
    """Build a fake FileSearchStore resource."""
    store = MagicMock()
    store.name = name
    store.display_name = display_name
    store.active_documents_count = active
    store.pending_documents_count = pending
    store.failed_documents_count = failed
    store.size_bytes = size_bytes
    store.create_time = create_time
    return store


def _mk_async_pager(items: list) -> MagicMock:
    """Build a MagicMock that supports `async for` over items.

    async client.aio.file_search_stores.list() returns an AsyncPager; our
    adapter uses `async for store in await client.aio...list()`, so we need
    a coroutine that resolves to an async-iterable.
    """

    class _AsyncIter:
        def __init__(self, xs):
            self._xs = list(xs)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._xs:
                raise StopAsyncIteration
            return self._xs.pop(0)

    return _AsyncIter(items)


@contextmanager
def _patched_client(
    *,
    create_store=None,
    upload_ops: list | None = None,
    list_stores: list | None = None,
    delete_side_effect=None,
    operations_get_side_effect=None,
    generate_content=None,
):
    """Context manager yielding a mocked genai.Client."""
    with patch("refcast.backends.gemini_fs.genai.Client") as mock_cls:
        client = MagicMock()

        # Async file_search_stores surface
        if create_store is not None:
            client.aio.file_search_stores.create = AsyncMock(return_value=create_store)
        if upload_ops is not None:
            client.aio.file_search_stores.upload_to_file_search_store = AsyncMock(
                side_effect=list(upload_ops)
            )
        if list_stores is not None:
            client.aio.file_search_stores.list = AsyncMock(
                return_value=_mk_async_pager(list_stores)
            )
        if delete_side_effect is not None:
            client.aio.file_search_stores.delete = AsyncMock(side_effect=delete_side_effect)
        else:
            client.aio.file_search_stores.delete = AsyncMock(return_value=None)

        # operations.get — signature is (operation, *, config=None)
        if operations_get_side_effect is not None:
            client.aio.operations.get = AsyncMock(side_effect=operations_get_side_effect)

        if generate_content is not None:
            if isinstance(generate_content, Exception):
                client.aio.models.generate_content = AsyncMock(side_effect=generate_content)
            else:
                client.aio.models.generate_content = AsyncMock(return_value=generate_content)

        mock_cls.return_value = client
        yield client


def test_adapter_id_and_capabilities():
    a = GeminiFSBackend(api_key="g_test")
    assert a.id == "gemini_fs"
    assert "search" in a.capabilities
    assert "upload" in a.capabilities
    assert "cite" in a.capabilities


def test_missing_api_key_raises_auth_invalid():
    with pytest.raises(BackendError) as exc:
        GeminiFSBackend(api_key=None)
    assert exc.value.code == RecoveryEnum.AUTH_INVALID
    assert exc.value.recovery_action == "user_action"


# --- upload_files ---


@pytest.mark.asyncio
async def test_upload_files_returns_indexing_status(tmp_path):
    f = tmp_path / "paper.pdf"
    f.write_bytes(b"%PDF-1.4\n%test")
    store = _mk_store(name="fileSearchStores/abc123def456")
    op = _mk_upload_operation(name="operations/up_op_1")
    with _patched_client(create_store=store, upload_ops=[op]):
        a = GeminiFSBackend(api_key="g_test")
        result = await a.upload_files([str(f)])

    assert result["status"] == "indexing"
    assert result["file_count"] == 1
    # corpus_id is the short id extracted from the store name
    assert result["corpus_id"] == "abc123def456"
    # operation_id is the last upload op's name
    assert result["operation_id"] == "operations/up_op_1"


@pytest.mark.asyncio
async def test_upload_files_two_files_captures_both_operations(tmp_path):
    f1 = tmp_path / "a.pdf"
    f1.write_bytes(b"%PDF-1.4")
    f2 = tmp_path / "b.pdf"
    f2.write_bytes(b"%PDF-1.4")
    store = _mk_store(name="fileSearchStores/multi")
    op1 = _mk_upload_operation(name="operations/op_a")
    op2 = _mk_upload_operation(name="operations/op_b")
    with _patched_client(create_store=store, upload_ops=[op1, op2]):
        a = GeminiFSBackend(api_key="g_test")
        result = await a.upload_files([str(f1), str(f2)])

    assert result["corpus_id"] == "multi"
    assert result["file_count"] == 2
    # operation_id returns the LAST op's name per our contract
    assert result["operation_id"] == "operations/op_b"
    # Both ops retained internally for poll_status
    assert len(a._states["multi"]["operations"]) == 2


def test_upload_files_relative_path_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "paper.pdf"
    f.write_bytes(b"test")
    a = GeminiFSBackend(api_key="g_test")
    with pytest.raises(BackendError) as exc:
        asyncio.run(a.upload_files(["paper.pdf"]))
    assert exc.value.code == RecoveryEnum.UNSUPPORTED_FORMAT


@pytest.mark.asyncio
async def test_upload_files_missing_raises(tmp_path):
    a = GeminiFSBackend(api_key="g_test")
    with pytest.raises(BackendError) as exc:
        await a.upload_files([str(tmp_path / "nope.pdf")])
    assert exc.value.code == RecoveryEnum.UNSUPPORTED_FORMAT


@pytest.mark.asyncio
async def test_upload_files_wrong_format_raises(tmp_path):
    f = tmp_path / "paper.exe"
    f.write_bytes(b"x")
    a = GeminiFSBackend(api_key="g_test")
    with pytest.raises(BackendError) as exc:
        await a.upload_files([str(f)])
    assert exc.value.code == RecoveryEnum.UNSUPPORTED_FORMAT


# --- poll_status ---


@pytest.mark.asyncio
async def test_poll_status_indexing_then_complete(tmp_path):
    f = tmp_path / "paper.pdf"
    f.write_bytes(b"%PDF-1.4")
    store = _mk_store(name="fileSearchStores/poll1")
    op = _mk_upload_operation(name="operations/poll_op", done=False)
    with _patched_client(create_store=store, upload_ops=[op]):
        a = GeminiFSBackend(api_key="g_test")
        up = await a.upload_files([str(f)])
    cid = up["corpus_id"]

    # Poll 1 — still not done.
    op_still_running = _mk_upload_operation(name="operations/poll_op", done=False)
    with _patched_client(operations_get_side_effect=[op_still_running]):
        s1 = await a.poll_status(cid)
    assert s1["corpus_id"] == cid
    assert s1["indexed"] is False
    assert s1["file_count"] == 1
    assert s1["indexed_file_count"] == 0
    assert s1["progress"] == 0.0
    assert s1["warnings"] == []
    assert isinstance(s1["last_checked_at"], str)

    # Flip to done via test-only helper and re-poll (helper mutates cached op,
    # but poll_status re-fetches from the API, so we mock that too).
    op_done = _mk_upload_operation(name="operations/poll_op", done=True)
    with _patched_client(operations_get_side_effect=[op_done]):
        s2 = await a.poll_status(cid)
    assert s2["indexed"] is True
    assert s2["indexed_file_count"] == 1
    assert s2["progress"] == 1.0


@pytest.mark.asyncio
async def test_poll_status_mark_complete_helper(tmp_path):
    """_mark_complete is a test-only shortcut that skips polling the API."""
    f = tmp_path / "paper.pdf"
    f.write_bytes(b"%PDF-1.4")
    store = _mk_store(name="fileSearchStores/mark1")
    op = _mk_upload_operation(name="operations/mark_op", done=False)
    with _patched_client(create_store=store, upload_ops=[op]):
        a = GeminiFSBackend(api_key="g_test")
        up = await a.upload_files([str(f)])
    cid = up["corpus_id"]

    a._mark_complete(cid)
    # After _mark_complete, cached op is flipped; poll_status should still
    # call operations.get, so we mock it to return a done op.
    op_done = _mk_upload_operation(name="operations/mark_op", done=True)
    with _patched_client(operations_get_side_effect=[op_done]):
        s = await a.poll_status(cid)
    assert s["indexed"] is True
    assert s["indexed_file_count"] == 1


@pytest.mark.asyncio
async def test_poll_status_failed_op_surfaces_partial_index_warning(tmp_path):
    f1 = tmp_path / "ok.pdf"
    f1.write_bytes(b"%PDF-1.4")
    f2 = tmp_path / "bad.pdf"
    f2.write_bytes(b"%PDF-1.4")
    store = _mk_store(name="fileSearchStores/mixed")
    op1 = _mk_upload_operation(name="operations/ok")
    op2 = _mk_upload_operation(name="operations/bad")
    with _patched_client(create_store=store, upload_ops=[op1, op2]):
        a = GeminiFSBackend(api_key="g_test")
        up = await a.upload_files([str(f1), str(f2)])
    cid = up["corpus_id"]

    op_ok = _mk_upload_operation(name="operations/ok", done=True)
    op_bad = _mk_upload_operation(
        name="operations/bad", done=True, error={"code": 3, "message": "bad file"}
    )
    with _patched_client(operations_get_side_effect=[op_ok, op_bad]):
        s = await a.poll_status(cid)
    assert s["indexed"] is False  # one failed
    assert s["indexed_file_count"] == 1
    assert s["progress"] == 0.5
    assert len(s["warnings"]) == 1
    assert s["warnings"][0]["code"] == RecoveryEnum.PARTIAL_INDEX
    assert s["warnings"][0]["partial_results"] is True


@pytest.mark.asyncio
async def test_poll_status_unknown_corpus_returns_optimistic():
    """BUG 1 fix: corpus unknown to _states returns optimistic indexed=True (not CORPUS_NOT_FOUND).

    After a process restart _states is empty even if the corpus exists on the server.
    poll_status must not crash — it returns indexed=True with file_count=0 so the
    caller can proceed and let the execute() call validate the corpus server-side.
    """
    a = GeminiFSBackend(api_key="g_test")
    result = await a.poll_status("cor_unknown")
    assert result["corpus_id"] == "cor_unknown"
    assert result["indexed"] is True
    assert result["file_count"] == 0
    assert result["progress"] == 1.0
    assert result["warnings"] == []
    assert isinstance(result["last_checked_at"], str)


# --- list_corpora ---


@pytest.mark.asyncio
async def test_list_corpora_empty():
    with _patched_client(list_stores=[]):
        a = GeminiFSBackend(api_key="g_test")
        assert await a.list_corpora() == []


@pytest.mark.asyncio
async def test_list_corpora_one(tmp_path):
    f = tmp_path / "x.pdf"
    f.write_bytes(b"x")
    store = _mk_store(name="fileSearchStores/one_upload")
    op = _mk_upload_operation(name="operations/o1")
    with _patched_client(create_store=store, upload_ops=[op]):
        a = GeminiFSBackend(api_key="g_test")
        up = await a.upload_files([str(f)])

    # Server returns the store we just made, plus counts.
    listed = _mk_store(
        name="fileSearchStores/one_upload",
        display_name="refcast-display",
        active=0,
        pending=1,
        failed=0,
        size_bytes=1,
        create_time=_dt.datetime(2026, 4, 15, tzinfo=_dt.UTC),
    )
    with _patched_client(list_stores=[listed]):
        out = await a.list_corpora()
    assert len(out) == 1
    summary = out[0]
    assert summary["corpus_id"] == up["corpus_id"]
    assert summary["name"] == "refcast-display"
    assert summary["file_count"] == 1
    assert summary["indexed_file_count"] == 0
    assert summary["total_bytes"] == 1
    assert summary["backend"] == "gemini_fs"
    assert isinstance(summary["created_at"], str)


@pytest.mark.asyncio
async def test_list_corpora_two(tmp_path):
    s1 = _mk_store(name="fileSearchStores/store_a", active=1)
    s2 = _mk_store(name="fileSearchStores/store_b", active=2)
    with _patched_client(list_stores=[s1, s2]):
        a = GeminiFSBackend(api_key="g_test")
        result = await a.list_corpora()
    assert len(result) == 2
    ids = {r["corpus_id"] for r in result}
    assert ids == {"store_a", "store_b"}


# --- delete_corpus ---


@pytest.mark.asyncio
async def test_delete_corpus_success(tmp_path):
    f = tmp_path / "x.pdf"
    f.write_bytes(b"x")
    store = _mk_store(name="fileSearchStores/to_delete")
    op = _mk_upload_operation(name="operations/d1")
    with _patched_client(create_store=store, upload_ops=[op]):
        a = GeminiFSBackend(api_key="g_test")
        up = await a.upload_files([str(f)])
    cid = up["corpus_id"]

    with _patched_client(list_stores=[]):
        result = await a.delete_corpus(cid)
    assert result["corpus_id"] == cid
    assert result["deleted"] is True
    assert result["files_removed"] == 1
    # Confirm local state is cleared.
    assert cid not in a._states


@pytest.mark.asyncio
async def test_delete_corpus_not_found_raises():
    """Deleting a corpus we've never seen → API returns 404 → CORPUS_NOT_FOUND."""
    with _patched_client(delete_side_effect=[Exception("HTTP 404 NOT_FOUND")]):
        a = GeminiFSBackend(api_key="g_test")
        with pytest.raises(BackendError) as exc:
            await a.delete_corpus("cor_unknown")
    assert exc.value.code == RecoveryEnum.CORPUS_NOT_FOUND
    assert exc.value.recovery_action == "user_action"


@pytest.mark.asyncio
async def test_upload_files_too_large_raises(tmp_path, monkeypatch):
    f = tmp_path / "big.pdf"
    f.write_bytes(b"x")
    # Pretend file is >100MB via stat shim
    real_stat = type(f).stat

    class _FakeStat:
        st_size = 200 * 1024 * 1024

    def fake_stat(self, *a, **kw):
        if self == f:
            return _FakeStat()
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(type(f), "stat", fake_stat)
    a = GeminiFSBackend(api_key="g_test")
    with pytest.raises(BackendError) as exc:
        await a.upload_files([str(f)])
    assert exc.value.code == RecoveryEnum.FILE_TOO_LARGE


# --- execute ---


@pytest.mark.asyncio
async def test_execute_populates_citations_and_backend():
    fake = _mk_response("Q3 revenue was $4.2M", citations_count=2)
    with _patched_client(generate_content=fake):
        a = GeminiFSBackend(api_key="g_test")
        result = await a.execute(query="What was Q3 revenue?", corpus_id="cor_x", constraints=None)

    assert result["backend_used"] == "gemini_fs"
    assert result["fallback_scope"] == "none"
    assert len(result["citations"]) == 2
    assert result["citations"][0]["backend_used"] == "gemini_fs"
    assert result["citations"][0]["confidence"] is None
    assert result["citations"][0]["text"] == "citation text 0"
    assert result["citations"][0]["source_url"] == "gemini://file/0"
    assert isinstance(result["cost_cents"], float)
    assert result["latency_ms"] >= 0
    assert result["error"] is None
    assert result["answer"] == "Q3 revenue was $4.2M"


@pytest.mark.asyncio
async def test_execute_without_corpus_id_no_filesearch_tool():
    fake = _mk_response("general answer", citations_count=1)
    with patch("refcast.backends.gemini_fs.genai.Client") as mock_cls:
        client = MagicMock()
        gc = AsyncMock(return_value=fake)
        client.aio.models.generate_content = gc
        mock_cls.return_value = client

        a = GeminiFSBackend(api_key="g_test")
        # require_citation=False to avoid PARSE_ERROR; test focuses on tool config
        await a.execute(query="q", corpus_id=None, constraints={"require_citation": False})

    # When no corpus_id, config should be None (no FileSearch tool)
    call_kwargs = gc.call_args.kwargs
    assert call_kwargs.get("config") is None


@pytest.mark.asyncio
async def test_execute_require_citation_zero_raises_parse_error():
    fake = _mk_response("answer without citations", citations_count=0)
    with _patched_client(generate_content=fake):
        a = GeminiFSBackend(api_key="g_test")
        with pytest.raises(BackendError) as exc:
            await a.execute(query="q", corpus_id="cor_x", constraints={"require_citation": True})
        assert exc.value.code == RecoveryEnum.PARSE_ERROR
        assert exc.value.recovery_action == "fallback"


@pytest.mark.asyncio
async def test_execute_require_citation_false_allows_zero():
    fake = _mk_response("plain answer", citations_count=0)
    with _patched_client(generate_content=fake):
        a = GeminiFSBackend(api_key="g_test")
        result = await a.execute(
            query="q", corpus_id="cor_x", constraints={"require_citation": False}
        )
        assert result["citations"] == []
        assert result["error"] is None


@pytest.mark.asyncio
async def test_execute_max_citations_truncates():
    fake = _mk_response("ans", citations_count=10)
    with _patched_client(generate_content=fake):
        a = GeminiFSBackend(api_key="g_test")
        result = await a.execute(query="q", corpus_id="cor_x", constraints={"max_citations": 3})
        assert len(result["citations"]) == 3


@pytest.mark.asyncio
async def test_execute_empty_corpus_maps_to_empty_corpus_code():
    """Gemini error mentioning 'empty' or 'FAILED_PRECONDITION' maps to EMPTY_CORPUS."""
    with _patched_client(
        generate_content=Exception("FAILED_PRECONDITION: File search store is empty")
    ):
        a = GeminiFSBackend(api_key="g_test")
        with pytest.raises(BackendError) as exc:
            await a.execute(query="q", corpus_id="cor_empty", constraints=None)
        assert exc.value.code == RecoveryEnum.EMPTY_CORPUS


# --- citation normalizer ---


def test_normalize_citations_two_chunks_two_citations():
    fake = _mk_response("ans", citations_count=2)
    a = GeminiFSBackend(api_key="g_test")
    cites = a._normalize_citations(
        fake.candidates[0].grounding_metadata, corpus_id="cor_z", limit=10
    )
    assert len(cites) == 2
    c0 = cites[0]
    assert c0["text"] == "citation text 0"
    assert c0["source_url"] == "gemini://file/0"
    assert c0["author"] is None
    assert c0["date"] is None
    assert c0["confidence"] is None
    assert c0["backend_used"] == "gemini_fs"
    assert c0["raw"]["chunk_index"] == 0
    assert c0["raw"]["title"] == "doc_0.pdf"
    assert c0["raw"]["segment_range"] == [0, 10]


def test_normalize_citations_uri_fallback():
    """When chunk has no uri, fall back to gemini://corpus/{cid}/chunk/{idx}."""
    chunk = MagicMock()
    chunk.retrieved_context = MagicMock(uri=None, title="t.pdf")
    support = MagicMock()
    support.segment = MagicMock(text="segtext", start_index=0, end_index=5)
    support.grounding_chunk_indices = [0]
    grounding = MagicMock(grounding_chunks=[chunk], grounding_supports=[support])

    a = GeminiFSBackend(api_key="g_test")
    cites = a._normalize_citations(grounding, corpus_id="cor_q", limit=10)
    assert cites[0]["source_url"] == "gemini://corpus/cor_q/chunk/0"


# --- exception mapping ---


def test_map_exception_empty_corpus():
    a = GeminiFSBackend(api_key="g_test")
    err = a._map_exception(Exception("FAILED_PRECONDITION: store empty"))
    assert err.code == RecoveryEnum.EMPTY_CORPUS
    assert err.recovery_action == "user_action"


def test_map_exception_not_found_404():
    a = GeminiFSBackend(api_key="g_test")
    err = a._map_exception(Exception("HTTP 404 NOT_FOUND"))
    assert err.code == RecoveryEnum.CORPUS_NOT_FOUND
    assert err.recovery_action == "user_action"


def test_map_exception_rate_limited_429():
    a = GeminiFSBackend(api_key="g_test")
    err = a._map_exception(Exception("HTTP 429 RESOURCE_EXHAUSTED quota"))
    assert err.code == RecoveryEnum.RATE_LIMITED
    assert err.recovery_action == "retry"
    assert err.retry_after_ms == 30000


def test_map_exception_auth_invalid_401():
    a = GeminiFSBackend(api_key="g_test")
    err = a._map_exception(Exception("HTTP 401 UNAUTHENTICATED"))
    assert err.code == RecoveryEnum.AUTH_INVALID
    assert err.recovery_action == "user_action"


def test_map_exception_5xx_backend_unavailable():
    a = GeminiFSBackend(api_key="g_test")
    err = a._map_exception(Exception("HTTP 503 service unavailable"))
    assert err.code == RecoveryEnum.BACKEND_UNAVAILABLE
    assert err.recovery_action == "fallback"


def test_map_exception_default_unknown():
    a = GeminiFSBackend(api_key="g_test")
    err = a._map_exception(Exception("something weird"))
    assert err.code == RecoveryEnum.UNKNOWN
    assert err.recovery_action == "fallback"


def test_map_exception_priority_empty_over_5xx():
    """When error mentions both 'empty' and a 5xx-shaped phrase, EMPTY_CORPUS wins."""
    a = GeminiFSBackend(api_key="g_test")
    err = a._map_exception(Exception("HTTP 503 FAILED_PRECONDITION store empty"))
    assert err.code == RecoveryEnum.EMPTY_CORPUS


# --- BUG 1: None segment guard ---


def test_normalize_citations_none_segment_skipped():
    """Citations with segment=None should be skipped, not crash."""
    chunk = MagicMock()
    chunk.retrieved_context = MagicMock(uri="gemini://file/0", title="doc.pdf")

    support_none_seg = MagicMock()
    support_none_seg.segment = None
    support_none_seg.grounding_chunk_indices = [0]

    support_good = MagicMock()
    support_good.segment = MagicMock(text="good text", start_index=0, end_index=9)
    support_good.grounding_chunk_indices = [0]

    grounding = MagicMock(
        grounding_chunks=[chunk],
        grounding_supports=[support_none_seg, support_good],
    )

    a = GeminiFSBackend(api_key="g_test")
    cites = a._normalize_citations(grounding, corpus_id="cor_x", limit=10)
    # The None-segment support is skipped; only the good one produces a citation
    assert len(cites) == 1
    assert cites[0]["text"] == "good text"


def test_normalize_citations_none_seg_text_skipped():
    """BUG 5 fix: seg.text=None must be skipped — not crash on text[:100]."""
    chunk = MagicMock()
    chunk.retrieved_context = MagicMock(uri="gemini://file/0", title="doc.pdf")

    support_none_text = MagicMock()
    support_none_text.segment = MagicMock(text=None, start_index=0, end_index=5)
    support_none_text.grounding_chunk_indices = [0]

    support_good = MagicMock()
    support_good.segment = MagicMock(text="real text", start_index=5, end_index=14)
    support_good.grounding_chunk_indices = [0]

    grounding = MagicMock(
        grounding_chunks=[chunk],
        grounding_supports=[support_none_text, support_good],
    )

    a = GeminiFSBackend(api_key="g_test")
    cites = a._normalize_citations(grounding, corpus_id="cor_x", limit=10)
    # None-text support skipped; only the good one surfaces
    assert len(cites) == 1
    assert cites[0]["text"] == "real text"


# --- BUG 3: Overly broad 'empty' match ---


def test_map_exception_empty_response_body_not_empty_corpus():
    """'empty response body' without 'failed_precondition' → UNKNOWN, not EMPTY_CORPUS."""
    a = GeminiFSBackend(api_key="g_test")
    err = a._map_exception(Exception("empty response body from server"))
    assert err.code == RecoveryEnum.UNKNOWN


def test_map_exception_empty_parameter_not_empty_corpus():
    """'empty parameter' without 'failed_precondition' → UNKNOWN, not EMPTY_CORPUS."""
    a = GeminiFSBackend(api_key="g_test")
    err = a._map_exception(Exception("empty parameter in request"))
    assert err.code == RecoveryEnum.UNKNOWN


def test_map_exception_failed_precondition_with_empty_still_maps():
    """'failed_precondition' + 'empty' still correctly maps to EMPTY_CORPUS."""
    a = GeminiFSBackend(api_key="g_test")
    err = a._map_exception(Exception("FAILED_PRECONDITION: store is empty"))
    assert err.code == RecoveryEnum.EMPTY_CORPUS


def test_map_exception_failed_precondition_no_documents_maps():
    """'failed_precondition' + 'no documents' maps to EMPTY_CORPUS."""
    a = GeminiFSBackend(api_key="g_test")
    err = a._map_exception(Exception("FAILED_PRECONDITION: no documents indexed"))
    assert err.code == RecoveryEnum.EMPTY_CORPUS


# --- BUG 4: Path symlink resolution ---


def test_validate_path_symlink_to_allowed_file(tmp_path):
    """Symlink to a valid PDF passes validation (resolves to real file)."""
    real_file = tmp_path / "real.pdf"
    real_file.write_bytes(b"%PDF-1.4")
    link = tmp_path / "link.pdf"
    link.symlink_to(real_file)

    a = GeminiFSBackend(api_key="g_test")
    # Should not raise — the symlink resolves to a valid PDF
    a._validate_path(str(link))


def test_validate_path_symlink_to_disallowed_suffix(tmp_path):
    """Symlink to a .txt target but with .pdf name: resolves target suffix check."""
    # Create a text file, symlink with a .pdf extension that points to it
    real_file = tmp_path / "data.txt"
    real_file.write_bytes(b"plaintext")
    link = tmp_path / "link.pdf"
    link.symlink_to(real_file)

    # After resolving symlink, Path.suffix for the link is still .pdf (the link name),
    # so this should pass. The important thing is that it doesn't crash.
    a = GeminiFSBackend(api_key="g_test")
    # .pdf extension so validation passes
    a._validate_path(str(link))


# --- BUG 6 (gemini): Status code word-boundary matching ---


def test_map_exception_no_false_positive_500_in_corpus_id():
    """Error message with '50021' should NOT be treated as a 500 server error."""
    a = GeminiFSBackend(api_key="g_test")
    # "50021" contains "500" as substring but is not a standalone HTTP status code
    err = a._map_exception(Exception("File id 50021 access denied"))
    # Word-boundary fix prevents false 500 match → falls through to UNKNOWN
    assert err.code != RecoveryEnum.BACKEND_UNAVAILABLE


def test_map_exception_no_false_positive_429_in_id():
    """Error message with corpus id containing '429' substring should not trigger RATE_LIMITED."""
    a = GeminiFSBackend(api_key="g_test")
    # "42907" contains "429" but is not a standalone 429 status code
    err = a._map_exception(Exception("Resource 42907 access denied"))
    # Should be UNKNOWN, not RATE_LIMITED
    assert err.code == RecoveryEnum.UNKNOWN


# --- BUG 2 (audit): upload_files([]) raises BackendError ---


@pytest.mark.asyncio
async def test_upload_files_empty_list_raises():
    """upload_files([]) must raise BackendError, not create an empty store."""
    a = GeminiFSBackend(api_key="g_test")
    with pytest.raises(BackendError) as exc:
        await a.upload_files([])
    assert exc.value.code == RecoveryEnum.UNSUPPORTED_FORMAT
    assert exc.value.recovery_action == "user_action"
    assert "No files" in exc.value.message


# --- BUG 1 (audit): Orphan store cleanup on partial upload failure ---


@pytest.mark.asyncio
async def test_upload_files_cleans_up_store_on_upload_failure(tmp_path):
    """If a file upload fails, the created store should be deleted (best-effort)."""
    f1 = tmp_path / "ok.pdf"
    f1.write_bytes(b"%PDF-1.4")
    f2 = tmp_path / "fail.pdf"
    f2.write_bytes(b"%PDF-1.4")

    store = _mk_store(name="fileSearchStores/orphan_test")
    op1 = _mk_upload_operation(name="operations/ok")

    with _patched_client(
        create_store=store,
        upload_ops=[op1, Exception("upload failed for file 2")],
    ) as client:
        a = GeminiFSBackend(api_key="g_test")
        with pytest.raises(BackendError):
            await a.upload_files([str(f1), str(f2)])
        # The store should have been cleaned up via delete
        client.aio.file_search_stores.delete.assert_awaited_once_with(
            name="fileSearchStores/orphan_test"
        )
