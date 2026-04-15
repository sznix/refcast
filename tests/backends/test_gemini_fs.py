"""Tests for Gemini File Search adapter."""

import asyncio
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
    a = GeminiFSBackend(api_key="g_test")
    result = await a.upload_files([str(f)])
    assert result["status"] == "indexing"
    assert result["file_count"] == 1
    assert result["corpus_id"].startswith("cor_")
    assert result["operation_id"].startswith("operations/")


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
    a = GeminiFSBackend(api_key="g_test")
    up = await a.upload_files([str(f)])
    cid = up["corpus_id"]

    s1 = await a.poll_status(cid)
    assert s1["corpus_id"] == cid
    assert s1["indexed"] is False
    assert s1["file_count"] == 1
    assert s1["indexed_file_count"] == 0
    assert s1["progress"] == 0.0
    assert s1["warnings"] == []
    assert isinstance(s1["last_checked_at"], str)

    a._mark_complete(cid)
    s2 = await a.poll_status(cid)
    assert s2["indexed"] is True
    assert s2["indexed_file_count"] == 1
    assert s2["progress"] == 1.0


@pytest.mark.asyncio
async def test_poll_status_unknown_corpus_raises(tmp_path):
    a = GeminiFSBackend(api_key="g_test")
    with pytest.raises(BackendError) as exc:
        await a.poll_status("cor_unknown")
    assert exc.value.code == RecoveryEnum.CORPUS_NOT_FOUND


# --- list_corpora ---


@pytest.mark.asyncio
async def test_list_corpora_empty():
    a = GeminiFSBackend(api_key="g_test")
    assert await a.list_corpora() == []


@pytest.mark.asyncio
async def test_list_corpora_one(tmp_path):
    f = tmp_path / "x.pdf"
    f.write_bytes(b"x")
    a = GeminiFSBackend(api_key="g_test")
    up = await a.upload_files([str(f)])
    out = await a.list_corpora()
    assert len(out) == 1
    summary = out[0]
    assert summary["corpus_id"] == up["corpus_id"]
    assert summary["file_count"] == 1
    assert summary["indexed_file_count"] == 0
    assert summary["total_bytes"] == 1
    assert summary["backend"] == "gemini_fs"
    assert isinstance(summary["created_at"], str)


@pytest.mark.asyncio
async def test_list_corpora_two(tmp_path):
    a = GeminiFSBackend(api_key="g_test")
    f1 = tmp_path / "a.pdf"
    f1.write_bytes(b"aa")
    f2 = tmp_path / "b.txt"
    f2.write_bytes(b"bbb")
    await a.upload_files([str(f1)])
    await a.upload_files([str(f2)])
    assert len(await a.list_corpora()) == 2


# --- delete_corpus ---


@pytest.mark.asyncio
async def test_delete_corpus_success(tmp_path):
    a = GeminiFSBackend(api_key="g_test")
    f = tmp_path / "x.pdf"
    f.write_bytes(b"x")
    up = await a.upload_files([str(f)])
    cid = up["corpus_id"]
    result = await a.delete_corpus(cid)
    assert result["corpus_id"] == cid
    assert result["deleted"] is True
    assert result["files_removed"] == 1
    assert await a.list_corpora() == []


@pytest.mark.asyncio
async def test_delete_corpus_not_found_raises():
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
    with patch("refcast.backends.gemini_fs.genai.Client") as mock_cls:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=fake)
        mock_cls.return_value = client

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
    with patch("refcast.backends.gemini_fs.genai.Client") as mock_cls:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=fake)
        mock_cls.return_value = client

        a = GeminiFSBackend(api_key="g_test")
        with pytest.raises(BackendError) as exc:
            await a.execute(query="q", corpus_id="cor_x", constraints={"require_citation": True})
        assert exc.value.code == RecoveryEnum.PARSE_ERROR
        assert exc.value.recovery_action == "fallback"


@pytest.mark.asyncio
async def test_execute_require_citation_false_allows_zero():
    fake = _mk_response("plain answer", citations_count=0)
    with patch("refcast.backends.gemini_fs.genai.Client") as mock_cls:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=fake)
        mock_cls.return_value = client

        a = GeminiFSBackend(api_key="g_test")
        result = await a.execute(
            query="q", corpus_id="cor_x", constraints={"require_citation": False}
        )
        assert result["citations"] == []
        assert result["error"] is None


@pytest.mark.asyncio
async def test_execute_max_citations_truncates():
    fake = _mk_response("ans", citations_count=10)
    with patch("refcast.backends.gemini_fs.genai.Client") as mock_cls:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=fake)
        mock_cls.return_value = client

        a = GeminiFSBackend(api_key="g_test")
        result = await a.execute(query="q", corpus_id="cor_x", constraints={"max_citations": 3})
        assert len(result["citations"]) == 3


@pytest.mark.asyncio
async def test_execute_empty_corpus_maps_to_empty_corpus_code():
    """Gemini error mentioning 'empty' or 'FAILED_PRECONDITION' maps to EMPTY_CORPUS."""
    with patch("refcast.backends.gemini_fs.genai.Client") as mock_cls:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("FAILED_PRECONDITION: File search store is empty")
        )
        mock_cls.return_value = client

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
