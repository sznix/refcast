"""Tests for refcast.evidence — content-addressed, tamper-evident research transcripts.

v0.3 primitive: Reproducible Evidence Transcript. Every field is testable offline,
no network, no API keys required — that's the whole point.
"""

from __future__ import annotations

import hashlib
import json

from refcast.evidence import (
    build_evidence_pack,
    canonical_json,
    compute_source_cid,
    compute_transcript_cid,
    verify_evidence_pack,
)


def _cite(url: str, text: str, backend_id: str = "exa") -> dict:
    return {
        "text": text,
        "source_url": url,
        "author": None,
        "date": None,
        "confidence": 0.9,
        "backend_used": backend_id,
        "raw": {},
    }


def _result(citations: list[dict] | None = None, backend: str = "exa") -> dict:
    return {
        "answer": "answer text",
        "citations": citations or [],
        "backend_used": backend,
        "latency_ms": 100,
        "cost_cents": 0.7,
        "fallback_scope": "none",
        "warnings": [],
        "error": None,
    }


# --- canonical_json: deterministic, sorted, ASCII ---


def test_canonical_json_sorts_keys():
    a = canonical_json({"b": 1, "a": 2})
    b = canonical_json({"a": 2, "b": 1})
    assert a == b


def test_canonical_json_returns_bytes():
    out = canonical_json({"a": 1})
    assert isinstance(out, bytes)


def test_canonical_json_no_whitespace():
    out = canonical_json({"a": 1, "b": [1, 2]})
    assert b" " not in out


def test_canonical_json_ascii_safe():
    """Non-ASCII characters must be escaped to keep bytes identical on any locale."""
    out = canonical_json({"greeting": "hello \u4e16\u754c"})
    assert b"\\u4e16" in out


def test_canonical_json_nested_sorts():
    a = canonical_json({"outer": {"z": 1, "a": 2}})
    b = canonical_json({"outer": {"a": 2, "z": 1}})
    assert a == b


# --- compute_source_cid: binds URL + text ---


def test_source_cid_deterministic():
    cid1 = compute_source_cid("https://example.com", "hello world")
    cid2 = compute_source_cid("https://example.com", "hello world")
    assert cid1 == cid2
    # sha256 hex digest is 64 chars
    assert len(cid1) == 64
    assert all(c in "0123456789abcdef" for c in cid1)


def test_source_cid_changes_on_text_drift():
    cid1 = compute_source_cid("https://example.com", "hello world")
    cid2 = compute_source_cid("https://example.com", "hello world!")
    assert cid1 != cid2


def test_source_cid_changes_on_url_change():
    cid1 = compute_source_cid("https://a.com", "same text")
    cid2 = compute_source_cid("https://b.com", "same text")
    assert cid1 != cid2


def test_source_cid_empty_text():
    cid = compute_source_cid("https://example.com", "")
    assert len(cid) == 64


# --- compute_transcript_cid: self-referential ---


def test_transcript_cid_ignores_own_field():
    """Transcript CID must be computed WITHOUT the transcript_cid field itself,
    otherwise it would be a chicken-and-egg problem."""
    pack_without_cid = {
        "query": "test",
        "backends_used": [],
        "source_cids": [],
        "citations_count": 0,
        "timestamp": "2026-04-17T10:00:00",
        "cost_cents": 0.0,
        "latency_ms": 100,
        "env_fingerprint": {},
    }
    cid1 = compute_transcript_cid(pack_without_cid)
    # Same data + a transcript_cid field → same CID
    pack_with_cid = dict(pack_without_cid)
    pack_with_cid["transcript_cid"] = "anything_different"
    cid2 = compute_transcript_cid(pack_with_cid)
    assert cid1 == cid2


def test_transcript_cid_changes_on_any_field():
    base = {
        "query": "test",
        "backends_used": [],
        "source_cids": [],
        "citations_count": 0,
        "timestamp": "2026-04-17T10:00:00",
        "cost_cents": 0.0,
        "latency_ms": 100,
        "env_fingerprint": {},
    }
    cid_base = compute_transcript_cid(base)

    for field in ("query", "timestamp", "cost_cents", "latency_ms"):
        mutated = dict(base)
        if isinstance(mutated[field], (int, float)):
            mutated[field] = mutated[field] + 1
        else:
            mutated[field] = str(mutated[field]) + "!"
        assert compute_transcript_cid(mutated) != cid_base, f"field {field} not bound to CID"


# --- build_evidence_pack: full assembly ---


def test_build_evidence_pack_basic():
    citations = [_cite("https://a.com", "text a"), _cite("https://b.com", "text b")]
    result = _result(citations)
    pack = build_evidence_pack(
        result=result,
        query="q",
        backends=[{"id": "exa", "version": "2.12.0", "params_hash": "abc"}],
    )
    assert pack["query"] == "q"
    assert pack["citations_count"] == 2
    assert len(pack["source_cids"]) == 2
    assert all(len(cid) == 64 for cid in pack["source_cids"])
    assert pack["cost_cents"] == 0.7
    assert pack["latency_ms"] == 100
    assert pack["backends_used"] == [{"id": "exa", "version": "2.12.0", "params_hash": "abc"}]
    assert "transcript_cid" in pack
    assert len(pack["transcript_cid"]) == 64


def test_build_evidence_pack_source_cids_match_citations():
    citations = [_cite("https://a.com", "text a")]
    pack = build_evidence_pack(result=_result(citations), query="q", backends=[{"id": "exa"}])
    expected_cid = compute_source_cid("https://a.com", "text a")
    assert pack["source_cids"][0] == expected_cid


def test_build_evidence_pack_empty_citations():
    pack = build_evidence_pack(result=_result([]), query="empty", backends=[])
    assert pack["citations_count"] == 0
    assert pack["source_cids"] == []
    assert len(pack["transcript_cid"]) == 64  # still computable


def test_build_evidence_pack_env_fingerprint_has_version():
    from refcast._version import __version__

    pack = build_evidence_pack(result=_result([]), query="q", backends=[])
    assert pack["env_fingerprint"]["refcast_version"] == __version__


def test_build_evidence_pack_timestamp_is_iso8601():
    pack = build_evidence_pack(result=_result([]), query="q", backends=[])
    ts = pack["timestamp"]
    # Strict ISO 8601 parse
    from datetime import datetime

    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert parsed is not None


# --- verify_evidence_pack: tamper detection ---


def test_verify_valid_pack_returns_valid():
    pack = build_evidence_pack(
        result=_result([_cite("https://a.com", "text")]),
        query="q",
        backends=[{"id": "exa"}],
    )
    valid, errors = verify_evidence_pack(pack)
    assert valid is True
    assert errors == []


def test_verify_detects_tampered_query():
    pack = build_evidence_pack(result=_result([]), query="original", backends=[])
    pack["query"] = "tampered"
    valid, errors = verify_evidence_pack(pack)
    assert valid is False
    assert len(errors) >= 1
    assert any("transcript_cid" in e.lower() or "mismatch" in e.lower() for e in errors)


def test_verify_detects_tampered_source_cid():
    pack = build_evidence_pack(
        result=_result([_cite("https://a.com", "text")]),
        query="q",
        backends=[{"id": "exa"}],
    )
    # Corrupt one source_cid
    pack["source_cids"][0] = "0" * 64
    valid, errors = verify_evidence_pack(pack)
    assert valid is False


def test_verify_detects_mismatched_citations_count():
    pack = build_evidence_pack(
        result=_result([_cite("https://a.com", "text")]),
        query="q",
        backends=[],
    )
    pack["citations_count"] = 99  # lie about count
    valid, errors = verify_evidence_pack(pack)
    assert valid is False


def test_verify_missing_transcript_cid():
    pack = build_evidence_pack(result=_result([]), query="q", backends=[])
    del pack["transcript_cid"]  # type: ignore[misc]
    valid, errors = verify_evidence_pack(pack)
    assert valid is False
    assert any("transcript_cid" in e.lower() for e in errors)


def test_verify_empty_dict():
    valid, errors = verify_evidence_pack({})  # type: ignore[arg-type]
    assert valid is False
    assert len(errors) >= 1


# --- round-trip: build → serialize → deserialize → verify ---


def test_verify_round_trip_through_json():
    """Real-world flow: pack is serialized to JSON, stored/shared, re-loaded, verified."""
    original = build_evidence_pack(
        result=_result([_cite("https://a.com", "hello"), _cite("https://b.com", "world")]),
        query="q",
        backends=[{"id": "exa"}],
    )
    serialized = json.dumps(original)
    restored = json.loads(serialized)
    valid, errors = verify_evidence_pack(restored)
    assert valid is True, f"Round-trip verify failed: {errors}"


def test_verify_unicode_round_trip():
    """Non-ASCII citation text must survive canonicalization."""
    pack = build_evidence_pack(
        result=_result([_cite("https://example.com", "\u4e16\u754c hello")]),
        query="\u4e16\u754c",
        backends=[],
    )
    serialized = json.dumps(pack)
    restored = json.loads(serialized)
    valid, errors = verify_evidence_pack(restored)
    assert valid is True, f"Unicode round-trip failed: {errors}"


# --- cross-check: manual sha256 matches our CID helpers ---


def test_source_cid_matches_manual_sha256():
    url = "https://example.com"
    text = "hello"
    manual = hashlib.sha256(f"{url}\n{text}".encode()).hexdigest()
    assert compute_source_cid(url, text) == manual
