"""Tests for Gemini File Search adapter."""

import asyncio

import pytest

from refcast.backends.base import BackendError
from refcast.backends.gemini_fs import GeminiFSBackend
from refcast.models import RecoveryEnum


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
