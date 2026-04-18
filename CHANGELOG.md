# Changelog

## [0.3.0] — 2026-04-17

**Reproducible Evidence Transcript.** Every `research()` call now attaches a hash-identified, integrity-verifiable envelope, with a pure-offline `research.verify` tool you can hand to any reviewer.

### Scope

This release adds an **integrity-only** primitive — it proves the envelope has not been mutated since emission. It does NOT prove citations are correct, does NOT bind citations to the envelope (the consumer must re-hash citations against `source_cids` out-of-band), and does NOT constitute authenticity (there is no signature, no signer identity). See `SECURITY.md` and the verifier docstring for the exact scope.

### Added

- **`EvidencePack`** attached to every successful `research()` result: query + backends used + per-citation `source_cid = sha256(url + "\n" + text)` + `transcript_cid = sha256(canonical JSON of the pack minus transcript_cid itself)` + cost + latency + env fingerprint (refcast version, Python version, platform).
- **`research.verify`** — a new MCP tool, a pure function of the input pack: no network, no credentials, no server state. Returns a structured verdict `{integrity_valid, binding_verified: false, authenticity_verified: false, errors, transcript_cid}` that is explicit about the scope (integrity only; citation binding and authenticity are out of scope in v0.3).
- **`refcast verify <file>`** — CLI wrapper: exit 0 on integrity-valid, exit 1 otherwise, identical semantics to the MCP tool. Works offline.
- **Canonical JSON encoding** — `sort_keys=True`, `ensure_ascii=True`, compact separators. Deterministic across Python runtimes on the same machine; **not RFC 8785 JCS-compliant** (JCS number normalization and UTF-8 escaping are deliberately not implemented). Cross-language verifiers must replicate the exact Python encoding.
- **Regression guards**: test asserting absence of signing-related imports in the evidence path, test asserting both `research` and `research.verify` are registered as independently-callable MCP tools. These prevent silent drift from integrity-only to authenticity-claiming, and prevent silent deletion of the verifier tool.

### Changed

- `research.verify` return shape: `{valid, errors, transcript_cid}` → `{integrity_valid, binding_verified: false, authenticity_verified: false, errors, transcript_cid}`. Downstream consumers treating the old `valid=True` as "citations proven correct" will now see an explicit `binding_verified: false` field that names the gap.
- README rewritten: lead with integrity disclaimer (not a truthfulness claim), enumerate all six registered MCP tools (four corpus-management + two research), list prior art (AGA MCP Server, PapersFlow MCP, citecheck).
- `evidence.py` module docstring: "content-addressed, tamper-evident" → "hash-identified, integrity-verifiable" (accurate — there is no CID retrieval store; only a self-verifying digest).

### Prior art

Not a novel cryptographic primitive. The construction composes well-known components: RFC 8785 JCS (approximated, not compliant) · SHA-256 · Haber-Stornetta hash-linked timestamping. Adjacent shipped systems: **AGA MCP Server v2.1.0** (Attested Intelligence — Ed25519 + proper JCS + Merkle, governance-proxy shape), **PapersFlow MCP** (hosted verify), **citecheck** (arXiv 2603.17339 — online bibliographic verification), C2PA 2.2, IETF SCITT, W3C VC 2.0. refcast is positioned as a first-party-bundled research producer + integrity verifier in one MCP package; priority claim, not a moat.

### Notes

- The underlying `(url, text)` pairs are not retained in the envelope; only their `source_cid`s are. If a downstream consumer needs to verify that the citations they see correspond to the pack they received, they must re-hash each citation and compare — `research.verify` does not perform that step.
- SHA-256 integrity holds through ~2035 per NIST IR 8547. Algorithm-agility is not yet implemented.

## [0.2.0] — 2026-04-15

**Answers with teeth.** Research results now come back with inline `[1]` `[2]` citation markers and a new `depth` parameter for multi-perspective deep research.

### Added
- **Answer synthesis** — every `research()` call now passes raw citations through Gemini to produce a coherent answer with inline `[1]` `[2]` markers pointing to specific sources. Works in both quick and deep modes.
- **`depth="deep"` mode** — generates multiple sub-queries from different perspectives (technical, critical, historical, practical), runs each through the backend pipeline, merges and deduplicates citations, then synthesizes a single comprehensive answer from the combined evidence.
- **Multi-perspective query generation** — STORM-lite approach that fans out a single question into 4 angle-specific sub-queries for broader coverage.
- **Citation deduplication** — `merge_citations()` deduplicates by `(source_url, text[:100])`, keeping the highest-confidence entry on collision.

### Changed
- `research()` tool accepts an optional `depth` parameter in `constraints`: `"quick"` (default, backward-compatible) or `"deep"`.
- `_register_backends()` now returns a `tuple[dict, str | None]` to thread the Gemini API key through to synthesis.
- When synthesis fails, the raw backend answer is preserved and a structured warning is appended (no crashes, no data loss).
- When `gemini_api_key` is not configured, synthesis and deep mode are silently skipped — Exa-only users see no behavior change.

## [0.1.0] — 2026-04-29

First release. **Cast once. Cite anywhere.**

### What's in the box
- **5 MCP tools** for corpus management and research: `corpus.upload`, `corpus.status`, `corpus.list`, `corpus.delete`, and `research`
- **2 research backends**: Gemini File Search (for your own documents) and Exa (for the web)
- **Automatic fallback** — if one backend is down, refcast tries the next one. A `fallback_scope` field tells you what happened (`none`, `same`, `broader`, or `different`)
- **One citation shape for everything** — no matter which backend answered, citations come back in the same format with a `raw` field if you need the original data
- **Errors that tell you what to do** — 14 error codes, each with a `recovery_action` (retry / fallback / user_action) so your agent doesn't have to guess
- **25KB response cap** — large responses get citation-trimmed automatically instead of crashing your context window
- **CLI tools**: `refcast init` (scaffold config), `refcast auth` (store API keys), `refcast doctor` (check everything works)
- **Three ways to store credentials**: OS keychain, environment variables, or `.env` file
- **128 unit tests** + integration tests against real APIs (gated behind env vars)
- **CI on 3 Python versions** (3.11, 3.12, 3.13) across Ubuntu and macOS

### Not yet (coming in future releases)
- NotebookLM Enterprise API as a third backend (v0.3)
- Drift detection to catch when a backend silently changes behavior (v0.3)
- Semantic caching for expensive queries (v0.4)
- Plugin system for custom auth strategies (v0.4)
