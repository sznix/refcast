# Changelog

All notable changes to refcast will be documented here. Format follows [Keep a Changelog](https://keepachangelog.com).

## [0.1.0] — 2026-04-29

Initial release. **"Cast once. Cite anywhere."**

### Added
- 5 MCP tools: `corpus.upload`, `corpus.status`, `corpus.list`, `corpus.delete`, `research`
- 2 backends: Gemini File Search (corpus + web) and Exa (web only)
- Serial fallback router with deterministic `fallback_scope` classification (`none`/`same`/`broader`/`different`)
- Unified `Citation` envelope across backends with lossless `raw` passthrough
- Structured error protocol with 14-code `RecoveryEnum` and `recovery_action: retry|fallback|user_action`
- 25KB hard cap on MCP responses with source-order citation truncation
- CLI: `refcast init`, `refcast auth`, `refcast doctor`
- Secrets via `python-dotenv` + `keyring` chain
- Python 3.11+, fastmcp 3.x, MIT license
- Test suite: 127+ unit tests, integration tests gated behind real API keys
- CI: matrix on Python 3.11/3.12/3.13 × Ubuntu/macOS

### Excluded from v0.1 (planned for v0.2+)
- NotebookLM Enterprise API backend (v0.2)
- Statistical drift detection (v0.2)
- Idempotency keys for mutations (v0.2)
- vCache-bounded semantic cache (v0.3)
- Custom AuthStrategy plugins (v0.3)
