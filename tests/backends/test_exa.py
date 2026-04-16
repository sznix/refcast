"""Tests for Exa backend adapter."""

from unittest.mock import MagicMock, patch

import pytest

from refcast.backends.base import BackendError
from refcast.backends.exa import ExaBackend
from refcast.models import RecoveryEnum

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_exa_response(num_results: int = 3) -> MagicMock:
    results = []
    for i in range(num_results):
        r = MagicMock()
        r.url = f"https://example.com/{i}"
        r.title = f"Article {i}"
        r.text = f"Content for article {i}"
        r.score = 0.95 - (i * 0.05)
        r.published_date = "2026-01-15"
        r.author = f"Author {i}"
        results.append(r)
    response = MagicMock()
    response.results = results
    return response


# ---------------------------------------------------------------------------
# Task 4.1 — skeleton + auth
# ---------------------------------------------------------------------------


def test_adapter_id_and_capabilities():
    a = ExaBackend(api_key="exa_test")
    assert a.id == "exa"
    assert "search" in a.capabilities
    assert "cite" in a.capabilities
    # Exa does NOT support upload (web-only)
    assert "upload" not in a.capabilities


def test_missing_api_key_raises_auth_invalid():
    with pytest.raises(BackendError) as exc:
        ExaBackend(api_key=None)
    assert exc.value.code == RecoveryEnum.AUTH_INVALID
    assert exc.value.recovery_action == "user_action"


# ---------------------------------------------------------------------------
# Task 4.2 — execute via search_and_contents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_returns_research_result_with_citations():
    fake = _mk_exa_response(num_results=3)
    with patch("refcast.backends.exa.Exa") as mock_cls:
        client = MagicMock()
        client.search_and_contents = MagicMock(return_value=fake)
        mock_cls.return_value = client

        a = ExaBackend(api_key="exa_test")
        result = await a.execute(query="fusion energy", corpus_id=None, constraints=None)

    assert result["backend_used"] == "exa"
    assert result["fallback_scope"] == "none"
    assert len(result["citations"]) == 3
    assert result["citations"][0]["confidence"] == pytest.approx(0.95)
    assert result["citations"][0]["source_url"] == "https://example.com/0"
    assert result["citations"][0]["author"] == "Author 0"
    assert result["citations"][0]["date"] == "2026-01-15"
    assert result["citations"][0]["backend_used"] == "exa"
    assert isinstance(result["cost_cents"], float)
    assert result["latency_ms"] >= 0
    assert result["error"] is None


@pytest.mark.asyncio
async def test_execute_respects_max_citations_constraint():
    fake = _mk_exa_response(num_results=10)
    with patch("refcast.backends.exa.Exa") as mock_cls:
        client = MagicMock()
        client.search_and_contents = MagicMock(return_value=fake)
        mock_cls.return_value = client

        a = ExaBackend(api_key="exa_test")
        result = await a.execute(
            query="q",
            corpus_id=None,
            constraints={"max_citations": 5},
        )
    assert len(result["citations"]) == 5


@pytest.mark.asyncio
async def test_execute_require_citation_zero_raises_parse_error():
    fake = _mk_exa_response(num_results=0)
    with patch("refcast.backends.exa.Exa") as mock_cls:
        client = MagicMock()
        client.search_and_contents = MagicMock(return_value=fake)
        mock_cls.return_value = client

        a = ExaBackend(api_key="exa_test")
        with pytest.raises(BackendError) as exc:
            await a.execute(
                query="q",
                corpus_id=None,
                constraints={"require_citation": True},
            )
        assert exc.value.code == RecoveryEnum.PARSE_ERROR


@pytest.mark.asyncio
async def test_execute_require_citation_false_allows_zero():
    fake = _mk_exa_response(num_results=0)
    with patch("refcast.backends.exa.Exa") as mock_cls:
        client = MagicMock()
        client.search_and_contents = MagicMock(return_value=fake)
        mock_cls.return_value = client

        a = ExaBackend(api_key="exa_test")
        result = await a.execute(
            query="q",
            corpus_id=None,
            constraints={"require_citation": False},
        )
    assert result["citations"] == []
    assert result["error"] is None


@pytest.mark.asyncio
async def test_execute_corpus_id_ignored():
    """Exa has no corpus concept — corpus_id is silently ignored."""
    fake = _mk_exa_response(num_results=1)
    with patch("refcast.backends.exa.Exa") as mock_cls:
        client = MagicMock()
        client.search_and_contents = MagicMock(return_value=fake)
        mock_cls.return_value = client

        a = ExaBackend(api_key="exa_test")
        result = await a.execute(query="q", corpus_id="some_corpus", constraints=None)
    # Should still return valid result — corpus_id is a no-op
    assert result["backend_used"] == "exa"
    assert len(result["citations"]) == 1


@pytest.mark.asyncio
async def test_execute_passes_num_results_to_sdk():
    """execute should pass max_citations as num_results to search_and_contents."""
    fake = _mk_exa_response(num_results=5)
    with patch("refcast.backends.exa.Exa") as mock_cls:
        client = MagicMock()
        client.search_and_contents = MagicMock(return_value=fake)
        mock_cls.return_value = client

        a = ExaBackend(api_key="exa_test")
        await a.execute(query="q", corpus_id=None, constraints={"max_citations": 5})

    call_kwargs = client.search_and_contents.call_args
    assert call_kwargs.kwargs.get("num_results") == 5 or call_kwargs.args[1] == 5


# ---------------------------------------------------------------------------
# Task 4.3 — citation normalizer
# ---------------------------------------------------------------------------


def test_normalize_citations_shape_and_score():
    fake = _mk_exa_response(num_results=3)
    a = ExaBackend(api_key="exa_test")
    cites = a._normalize_citations(fake.results, limit=10)
    assert len(cites) == 3
    c0 = cites[0]
    assert c0["text"] == "Content for article 0"
    assert c0["source_url"] == "https://example.com/0"
    assert c0["author"] == "Author 0"
    assert c0["date"] == "2026-01-15"
    assert c0["confidence"] == pytest.approx(0.95)
    assert c0["backend_used"] == "exa"
    assert "title" in c0["raw"]
    assert c0["raw"]["title"] == "Article 0"


def test_normalize_citations_limit_applied():
    fake = _mk_exa_response(num_results=6)
    a = ExaBackend(api_key="exa_test")
    cites = a._normalize_citations(fake.results, limit=4)
    assert len(cites) == 4


def test_normalize_citations_none_author_survives():
    """result.author may be None for some Exa results — must not crash."""
    r = MagicMock()
    r.url = "https://example.com/0"
    r.title = "Title"
    r.text = "Body"
    r.score = 0.8
    r.published_date = None
    r.author = None
    a = ExaBackend(api_key="exa_test")
    cites = a._normalize_citations([r], limit=10)
    assert len(cites) == 1
    assert cites[0]["author"] is None
    assert cites[0]["date"] is None


def test_normalize_citations_none_text_survives():
    """result.text may be None when highlights_only=True — fall back to empty string."""
    r = MagicMock()
    r.url = "https://example.com/0"
    r.title = "Title"
    r.text = None
    r.score = 0.7
    r.published_date = "2026-02-01"
    r.author = "Alice"
    a = ExaBackend(api_key="exa_test")
    cites = a._normalize_citations([r], limit=10)
    assert cites[0]["text"] == ""


# ---------------------------------------------------------------------------
# Task 4.4 — exception mapping
# ---------------------------------------------------------------------------


def test_map_exception_rate_limited_429():
    a = ExaBackend(api_key="exa_test")
    err = a._map_exception(Exception("HTTP 429 RATE_LIMITED too many requests"))
    assert err.code == RecoveryEnum.RATE_LIMITED
    assert err.recovery_action == "retry"
    assert err.retry_after_ms == 30000


def test_map_exception_rate_limited_phrase():
    a = ExaBackend(api_key="exa_test")
    err = a._map_exception(Exception("rate limit exceeded"))
    assert err.code == RecoveryEnum.RATE_LIMITED
    assert err.recovery_action == "retry"


def test_map_exception_auth_invalid_401():
    a = ExaBackend(api_key="exa_test")
    err = a._map_exception(Exception("HTTP 401 Unauthorized"))
    assert err.code == RecoveryEnum.AUTH_INVALID
    assert err.recovery_action == "user_action"


def test_map_exception_auth_invalid_api_key():
    a = ExaBackend(api_key="exa_test")
    err = a._map_exception(Exception("invalid api key provided"))
    assert err.code == RecoveryEnum.AUTH_INVALID
    assert err.recovery_action == "user_action"


def test_map_exception_5xx_backend_unavailable():
    a = ExaBackend(api_key="exa_test")
    err = a._map_exception(Exception("HTTP 503 server error"))
    assert err.code == RecoveryEnum.BACKEND_UNAVAILABLE
    assert err.recovery_action == "fallback"


def test_map_exception_network_timeout():
    a = ExaBackend(api_key="exa_test")
    err = a._map_exception(Exception("connection timeout while reading"))
    assert err.code == RecoveryEnum.BACKEND_UNAVAILABLE
    assert err.recovery_action == "fallback"


def test_map_exception_default_unknown():
    a = ExaBackend(api_key="exa_test")
    err = a._map_exception(Exception("something totally unexpected"))
    assert err.code == RecoveryEnum.UNKNOWN
    assert err.recovery_action == "fallback"


@pytest.mark.asyncio
async def test_execute_maps_sdk_exception_to_backend_error():
    """SDK exceptions raised during search_and_contents are mapped via _map_exception."""
    with patch("refcast.backends.exa.Exa") as mock_cls:
        client = MagicMock()
        client.search_and_contents = MagicMock(side_effect=Exception("HTTP 429 rate_limited"))
        mock_cls.return_value = client

        a = ExaBackend(api_key="exa_test")
        with pytest.raises(BackendError) as exc:
            await a.execute(query="q", corpus_id=None, constraints=None)
        assert exc.value.code == RecoveryEnum.RATE_LIMITED


# --- BUG 6 (exa): Status code word-boundary matching ---


def test_map_exception_no_false_positive_500_in_id():
    """'File id 50021 not found' — '500' is a substring, should NOT match as 500 server error."""
    a = ExaBackend(api_key="exa_test")
    err = a._map_exception(Exception("File id 50021 not found"))
    # "50021" contains "500" but is not a standalone status code
    # Does not match timeout/server error/connection → UNKNOWN
    assert err.code == RecoveryEnum.UNKNOWN


def test_map_exception_no_false_positive_429_in_corpus_id():
    """Error with '42907' in corpus name should NOT trigger RATE_LIMITED."""
    a = ExaBackend(api_key="exa_test")
    err = a._map_exception(Exception("Corpus 42907abc access failed"))
    # "42907abc" contains "429" as substring — must not trigger RATE_LIMITED
    assert err.code == RecoveryEnum.UNKNOWN
