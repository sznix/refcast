# Changelog

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
- NotebookLM Enterprise API as a third backend (v0.2)
- Drift detection to catch when a backend silently changes behavior (v0.2)
- Semantic caching for expensive queries (v0.3)
- Plugin system for custom auth strategies (v0.3)
