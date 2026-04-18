"""Reproducible Evidence Transcript — hash-identified, integrity-verifiable research envelope.

v0.3 primitive. Scope is deliberately narrow:

- **Integrity**: the envelope has not been mutated since emission. `verify_evidence_pack`
  returns `valid=True` iff the stored `transcript_cid` matches a fresh recomputation.
- **NOT authenticity**: there is no signer identity, no signature, no PKI. Anyone can
  produce a well-formed pack with any `query` / `source_cids` / `answer`. The verifier
  does not prove provenance.
- **NOT citation-binding**: `source_cid = sha256(url + "\\n" + text)` is computed at
  build time, but the underlying `(url, text)` pairs are NOT retained in the envelope.
  A consumer who receives `citations[]` + `evidence_pack` and wants to verify they
  correspond MUST re-hash each citation against `source_cids` out-of-band —
  `verify_evidence_pack` does not perform that step.
- **NOT content-addressed** in the Git/IPFS sense: there is no retrieval store keyed
  on the CID. The hash is an identity for integrity-checking, not an addressing
  scheme into a content-addressable store.

Uses SHA-256 over a canonical JSON encoding (`sort_keys=True, ensure_ascii=True,
separators=(",",":")`). **Not RFC 8785 JCS-compliant** — JCS number normalization
and UTF-8 escaping are deliberately not implemented. Cross-language verifiers must
replicate the exact Python encoding or they will diverge on edge cases (IEEE 754
numbers, surrogate pairs).

Prior art: RFC 8785 JCS · Haber-Stornetta hash-linked timestamping · C2PA 2.2 ·
IETF SCITT · W3C VC 2.0 · AGA MCP Server v2.1.0. This module composes well-known
primitives; nothing in it is novel cryptography. The refcast contribution is the
first-party-bundled MCP pairing (research tool + pure-offline integrity verifier),
not the primitives themselves.
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
    """Build an integrity-verifiable EvidencePack from a `ResearchResult`.

    `backends` is the list of backend descriptors that actually participated,
    e.g. ``[{"id": "exa", "version": "2.12.0", "params_hash": "..."}]``.

    The resulting pack is hash-identified (the `transcript_cid` is a self-contained
    identifier) but NOT signed and NOT bound to a signer identity. The (url, text)
    pairs from citations are hashed into `source_cids` but not retained in the pack;
    binding from citations shown to the consumer back to the envelope requires
    out-of-band re-hashing. See module docstring for the full scope disclaimer.
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
    """Pure offline **integrity** verification of an EvidencePack.

    Returns ``(integrity_valid, errors)``. ``integrity_valid=True`` iff the pack's
    recomputed `transcript_cid` matches the stored one AND required fields are
    present AND `citations_count` agrees with `len(source_cids)`.

    **What a `True` result proves**: the pack's bytes have not been mutated since
    emission.

    **What a `True` result does NOT prove**:
    - Citations shown to the consumer correspond to the pack (citation binding
      requires re-hashing each citation against `source_cids` out-of-band).
    - The pack was produced by refcast or any specific party (no signature, no PKI).
    - The answer or citations are factually correct.

    Checks (in order):
    1. `transcript_cid` field is present.
    2. Required scalar fields are present.
    3. `citations_count` matches `len(source_cids)`.
    4. Recomputed transcript_cid equals the stored one.

    This function is pure: no network, no credentials, no server state. It never
    raises — all failure modes return `(False, [...])`.
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
