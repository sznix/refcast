"""Reproducible Evidence Transcript — content-addressed, tamper-evident research provenance.

v0.3 primitive (design: 2026-04-17 research note + plan).

A `ResearchResult` can be accompanied by an `EvidencePack` that:
- Binds every citation's URL + text to a sha256 content ID (`source_cid`)
- Computes a sha256 over the canonical JSON of the whole pack (`transcript_cid`)
- Can be verified OFFLINE with no API key, no network, no refcast service

This is the substrate the v0.4 replay + v0.5 diff operators will build on.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import platform
import sys
from typing import Any

from refcast._version import __version__


def canonical_json(obj: Any) -> bytes:
    """Serialize `obj` to a byte sequence that is stable across runs/hosts/locales.

    Rules:
    - Keys sorted
    - ensure_ascii=True (non-ASCII → \\uXXXX, bytes identical regardless of locale)
    - No whitespace in separators (`,` and `:` only)
    """
    return json.dumps(
        obj,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")


def compute_source_cid(url: str, text: str) -> str:
    """sha256 over `url + "\\n" + text`.

    The newline separator prevents the ambiguity `sha256(url + text)` would create
    (different (url, text) pairs could collapse to the same byte stream).
    """
    payload = f"{url}\n{text}".encode()
    return hashlib.sha256(payload).hexdigest()


def compute_transcript_cid(pack: dict[str, Any]) -> str:
    """sha256 over canonical JSON of `pack`, EXCLUDING the `transcript_cid` field itself.

    Self-referential: the transcript_cid is computed, then set on the pack.
    When verifying, we strip transcript_cid, recompute, and compare.
    """
    without_cid = {k: v for k, v in pack.items() if k != "transcript_cid"}
    return hashlib.sha256(canonical_json(without_cid)).hexdigest()


def _env_fingerprint() -> dict[str, str]:
    """Lightweight identifier of what produced this transcript.

    Kept minimal — no PII, no hostnames, no paths. Just enough so a reviewer
    can tell which version of the tooling generated the pack.
    """
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return {
        "refcast_version": __version__,
        "python": py_ver,
        "platform": platform.system().lower(),
    }


def build_evidence_pack(
    result: dict[str, Any],
    query: str,
    backends: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a tamper-evident EvidencePack from a `ResearchResult`.

    `backends` is the list of backend descriptors that actually participated,
    e.g. ``[{"id": "exa", "version": "2.12.0", "params_hash": "..."}]``.
    """
    citations = result.get("citations") or []
    source_cids: list[str] = [
        compute_source_cid(c.get("source_url", "") or "", c.get("text", "") or "")
        for c in citations
    ]
    pack: dict[str, Any] = {
        "query": query,
        "backends_used": list(backends),
        "source_cids": source_cids,
        "citations_count": len(citations),
        "timestamp": _dt.datetime.now(_dt.UTC).isoformat(),
        "cost_cents": float(result.get("cost_cents", 0.0)),
        "latency_ms": int(result.get("latency_ms", 0)),
        "env_fingerprint": _env_fingerprint(),
    }
    pack["transcript_cid"] = compute_transcript_cid(pack)
    return pack


def verify_evidence_pack(pack: dict[str, Any]) -> tuple[bool, list[str]]:
    """Pure offline verification of an EvidencePack.

    Returns ``(valid, errors)`` where `errors` is a list of human-readable reasons
    for invalidity. ``valid=True`` iff `errors == []`.

    Checks (in order):
    1. `transcript_cid` field is present.
    2. `citations_count` matches `len(source_cids)`.
    3. Recomputed transcript_cid equals the stored one.

    This function never raises — all failure modes return `(False, [...])`.
    """
    errors: list[str] = []
    if not isinstance(pack, dict):
        return False, ["pack is not a dict"]
    if "transcript_cid" not in pack:
        errors.append("transcript_cid field is missing")
    required = ("query", "source_cids", "citations_count", "timestamp", "env_fingerprint")
    for field in required:
        if field not in pack:
            errors.append(f"required field '{field}' is missing")
    if errors:
        return False, errors

    source_cids = pack.get("source_cids") or []
    if pack.get("citations_count") != len(source_cids):
        errors.append(
            f"citations_count={pack.get('citations_count')} does not match "
            f"len(source_cids)={len(source_cids)}"
        )

    stored_cid = pack.get("transcript_cid")
    recomputed = compute_transcript_cid(pack)
    if stored_cid != recomputed:
        errors.append(f"transcript_cid mismatch — stored={stored_cid}, recomputed={recomputed}")

    return (len(errors) == 0), errors
