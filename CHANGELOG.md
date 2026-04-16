# Changelog

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
