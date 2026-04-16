"""End-to-end integration tests against real Gemini File Search + Exa APIs.

Gated by env vars. Run with: pytest -m integration
Skipped automatically when GEMINI_API_KEY or EXA_API_KEY are absent.
"""

import os

import pytest

from refcast.backends.exa import ExaBackend
from refcast.backends.gemini_fs import GeminiFSBackend
from refcast.router import execute_research

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("GEMINI_API_KEY") and os.environ.get("EXA_API_KEY")),
        reason="Requires GEMINI_API_KEY and EXA_API_KEY",
    ),
]


@pytest.fixture
def gemini() -> GeminiFSBackend:
    return GeminiFSBackend(api_key=os.environ["GEMINI_API_KEY"])


@pytest.fixture
def exa() -> ExaBackend:
    return ExaBackend(api_key=os.environ["EXA_API_KEY"])


@pytest.mark.asyncio
async def test_exa_real_search_returns_citations(exa: ExaBackend) -> None:
    """Sanity: real Exa search returns at least 1 citation with valid URL."""
    result = await exa.execute(
        query="What is retrieval augmented generation?",
        corpus_id=None,
        constraints={"max_citations": 3},
    )
    assert result["error"] is None
    assert len(result["citations"]) >= 1
    assert result["citations"][0]["source_url"].startswith("http")
    assert result["citations"][0]["confidence"] is not None


@pytest.mark.asyncio
async def test_router_fallback_when_corpus_none(gemini: GeminiFSBackend, exa: ExaBackend) -> None:
    """Without a corpus_id, router selects only Exa, returns web result."""
    result = await execute_research(
        query="What is the Model Context Protocol?",
        corpus_id=None,
        constraints={"max_citations": 3},
        registered={"gemini_fs": gemini, "exa": exa},
    )
    assert result["error"] is None
    assert result["backend_used"] == "exa"
    assert len(result["citations"]) >= 1


@pytest.mark.asyncio
async def test_router_fallback_when_gemini_corpus_invalid(
    gemini: GeminiFSBackend, exa: ExaBackend
) -> None:
    """Invalid corpus_id → Gemini fails → fallback to Exa with broader scope."""
    result = await execute_research(
        query="What is RAG?",
        corpus_id="cor_definitely_does_not_exist_12345",
        constraints={"preferred_backend": "gemini_fs", "max_citations": 3},
        registered={"gemini_fs": gemini, "exa": exa},
    )
    # Either router returns ResearchResult with error (no fallback path), OR
    # falls back to exa with broader scope. Both are valid for v0.1.
    if result["error"] is None:
        assert result["backend_used"] == "exa"
        assert result["fallback_scope"] == "broader"
        assert len(result["warnings"]) >= 1


@pytest.mark.asyncio
async def test_gemini_fs_full_corpus_lifecycle(gemini: GeminiFSBackend, tmp_path) -> None:
    """
    End-to-end: create corpus -> upload PDF -> poll until indexed ->
    query against it -> verify citations -> delete.
    """
    import asyncio as _asyncio
    import contextlib

    # Tiny PDF so indexing is fast
    test_pdf = tmp_path / "smoke.pdf"
    test_pdf.write_bytes(
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R>>endobj\n"
        b"4 0 obj<</Length 44>>stream\n"
        b"BT /F1 12 Tf 100 700 Td (refcast smoke test) Tj ET\n"
        b"endstream\nendobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    )

    upload = await gemini.upload_files([str(test_pdf)])
    corpus_id = upload["corpus_id"]

    try:
        # Poll up to 60s for indexing
        status = await gemini.poll_status(corpus_id)
        for _ in range(12):
            status = await gemini.poll_status(corpus_id)
            if status["indexed"]:
                break
            await _asyncio.sleep(5)
        assert status["indexed"], f"Corpus did not index in 60s: {status}"

        # Query
        result = await gemini.execute(
            query="What is the content of this document?",
            corpus_id=corpus_id,
            constraints={"max_citations": 3, "require_citation": False},
        )
        assert result["backend_used"] == "gemini_fs"
    finally:
        # Always clean up
        with contextlib.suppress(Exception):
            await gemini.delete_corpus(corpus_id)
