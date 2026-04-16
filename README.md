<div align="center">

# refcast

**Cast once. Cite anywhere.**

One MCP tool that brokers research across multiple backends — when one fails, the next picks up seamlessly, returning citations in the same shape every time.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-128%20passing-brightgreen.svg)](#testing)
[![MCP](https://img.shields.io/badge/MCP-compatible-8B5CF6.svg)](https://modelcontextprotocol.io)
[![fastmcp](https://img.shields.io/badge/built%20with-fastmcp%203.x-FF6B35.svg)](https://gofastmcp.com)

</div>

---

## The problem

Every NotebookLM MCP breaks every 7-14 days when Google rotates cookies. Your agent crashes at 2am. You wake up, re-auth, retry. Repeat.

**refcast doesn't fight this. It routes around it.**

```
Your agent                refcast                     Backends
   |                         |                           |
   |  research("What is     |                           |
   |   quantum computing?") |                           |
   |----------------------->|  try Gemini File Search   |
   |                        |-------------------------->| 503 Service
   |                        |                           | Unavailable
   |                        |  fallback to Exa          |
   |                        |-------------------------->| 200 OK
   |                        |                           |
   |  { answer, citations,  |  normalize + return       |
   |    backend_used: "exa", |<--------------------------|
   |    fallback_scope:      |                           |
   |      "broader" }       |                           |
   |<-----------------------|                           |
```

Your agent's code never changes. Citations come back in the same shape. The `fallback_scope` field tells you what happened.

## Install

```bash
uv tool install refcast          # recommended
pipx install refcast             # alternative
pip install refcast              # also works
```

## Setup (2 minutes)

```bash
# 1. Get free API keys:
#    Gemini  → https://aistudio.google.com/apikey
#    Exa     → https://dashboard.exa.ai/api-keys

# 2. Store them securely
refcast auth --store keyring     # macOS Keychain / Windows Credential Locker

# 3. Verify
refcast doctor
# Gemini: configured
# Exa:    configured

# 4. Add to your MCP client
```

<details>
<summary><b>Claude Code</b></summary>

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "refcast": {
      "command": "refcast-mcp"
    }
  }
}
```

Restart Claude Code. Tools appear as `mcp__refcast__*`.

</details>

<details>
<summary><b>Cursor / Windsurf / Other MCP clients</b></summary>

Register the server with command `refcast-mcp` (stdio transport). Consult your client's MCP configuration docs.

</details>

## What you get

### 5 MCP tools

| Tool | What it does |
|:-----|:-------------|
| `corpus.upload(files)` | Upload PDFs/docs to Gemini File Search. Returns immediately; indexing runs async. |
| `corpus.status(corpus_id)` | Check indexing progress. Poll until `indexed: true`. |
| `corpus.list()` | List all your corpora with file counts and sizes. |
| `corpus.delete(corpus_id)` | Remove a corpus and all its files. |
| **`research(query)`** | **The main tool.** Routes query across backends, returns unified citations. |

### Unified citation envelope

Every backend returns the same shape. Swap engines without touching a single parser.

```json
{
  "answer": "Quantum computing uses qubits that can exist in superposition...",
  "citations": [
    {
      "text": "Unlike classical bits, qubits leverage quantum superposition",
      "source_url": "https://example.com/quantum-intro",
      "author": "Dr. Sarah Chen",
      "date": "2026-03-15",
      "confidence": 0.94,
      "backend_used": "exa",
      "raw": { }
    }
  ],
  "backend_used": "exa",
  "latency_ms": 1438,
  "cost_cents": 0.7,
  "fallback_scope": "none",
  "warnings": [],
  "error": null
}
```

### Structured errors (not string messages)

When things go wrong, your agent gets machine-actionable errors:

```json
{
  "code": "rate_limited",
  "message": "Gemini 429",
  "recovery_hint": "Wait then retry, or accept fallback result.",
  "recovery_action": "retry",
  "retry_after_ms": 30000,
  "fallback_used": true
}
```

14 error codes. Every code has a defined `recovery_action`: **retry**, **fallback**, or **user_action**. Your agent can branch on these programmatically.

<details>
<summary><b>Full error taxonomy (14 codes)</b></summary>

| Code | When | Recovery |
|:-----|:-----|:---------|
| `rate_limited` | Backend 429 | retry |
| `quota_exceeded` | Account limit reached | user_action |
| `network_timeout` | HTTP timeout | retry |
| `auth_invalid` | Bad API key | user_action |
| `corpus_not_found` | Unknown corpus_id | user_action |
| `empty_corpus` | Corpus has 0 indexed files | user_action |
| `backend_unavailable` | All backends down | user_action |
| `schema_mismatch` | Unexpected response shape | fallback |
| `parse_error` | No citations when required | fallback |
| `indexing_in_progress` | Corpus still indexing | retry |
| `file_too_large` | File exceeds 100MB | user_action |
| `unsupported_format` | Not PDF/TXT/HTML/DOCX | user_action |
| `partial_index` | Some files failed to index | (warning) |
| `unknown` | Uncategorized | fallback |

</details>

### Deterministic fallback classification

When refcast falls back to a different backend, `fallback_scope` tells your agent exactly what happened:

| Value | Meaning |
|:------|:--------|
| `none` | Primary backend answered. No fallback. |
| `same` | Fallback served same data scope. |
| `broader` | Fallback widened scope (corpus -> web). |
| `different` | Fallback served fundamentally different data. Treat with caution. |

This is a **load-bearing signal for downstream agents** — it's how your LLM decides whether to trust the answer or re-prompt.

## Architecture

```
                          refcast
  ┌────────────────────────────────────────────────────┐
  │                                                    │
  │  ┌──────────────┐  ┌───────────────────────────┐   │
  │  │ corpus.*     │  │ research                  │   │
  │  │ (4 tools)    │  │ (1 tool)                  │   │
  │  └──────┬───────┘  └────────────┬──────────────┘   │
  │         │                       │                  │
  │         └───────────┬───────────┘                  │
  │                     ▼                              │
  │  ┌──────────────────────────────────────────────┐  │
  │  │  Serial Fallback Router                      │  │
  │  │  ┌────────────────────────────────────────┐  │  │
  │  │  │ select_backends() → classify_scope()   │  │  │
  │  │  │ 25KB response cap · error taxonomy     │  │  │
  │  │  └────────────────────────────────────────┘  │  │
  │  └──────────┬──────────────────────┬────────────┘  │
  │             ▼                      ▼               │
  │  ┌──────────────────┐  ┌──────────────────┐        │
  │  │  Gemini File     │  │  Exa             │        │
  │  │  Search          │  │  Search          │        │
  │  │  (corpus + web)  │  │  (web)           │        │
  │  └──────────────────┘  └──────────────────┘        │
  │                                                    │
  │  BackendAdapter Protocol — implement to add more   │
  └────────────────────────────────────────────────────┘
```

**Built on primitives, not monoliths.** Every backend implements one Protocol with 3 methods. Adding a new research backend (Perplexity, SurfSense, your own RAG) is one Python file.

## How it compares

| Feature | refcast | jacob-bd notebooklm-mcp | Single-backend MCPs |
|:--------|:-------:|:-----------------------:|:-------------------:|
| Multi-backend routing | **Yes** | No | No |
| Auto-failover | **Yes** | No | No |
| Unified citation schema | **Yes** | Backend-specific | Backend-specific |
| Structured error protocol | **14 codes** | Generic errors | Varies |
| Fallback scope classification | **4-level** | N/A | N/A |
| Cookie-free (ToS-clean) | **Yes** | No (scraping) | Varies |
| Cost visibility per query | **Yes** | No | No |
| Works when Google changes things | **Yes** | Breaks ~biweekly | Varies |

> refcast and jacob-bd's tool are **complementary**, not competing. Use jacob-bd for your existing NotebookLM notebooks; use refcast for resilient, multi-backend research.

## Cost

| Usage | Monthly cost |
|:------|:-------------|
| Casual (5-10 queries/day) | **$0** (free tiers) |
| Regular (30 queries/day) | **~$1** |
| Heavy (150 queries/day) | **~$15** |

Both Gemini and Exa have generous free tiers. No credit card required to start.

## Roadmap

| Version | Status | What's new |
|:--------|:-------|:-----------|
| **v0.1** | **Shipped** | 5 tools, 2 backends, serial fallback, unified citations, structured errors |
| v0.2 | Planned | NotebookLM Enterprise API backend, statistical drift detection, idempotency |
| v0.3 | Future | Formally-bounded semantic cache, plugin auth strategies, cost governance |

## Development

```bash
git clone https://github.com/sznix/refcast
cd refcast
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Run tests
pytest -m "not integration"       # 128 unit tests
pytest -m integration             # requires real API keys

# Lint + types
ruff check . && ruff format --check .
mypy src/refcast/                 # strict mode
```

### Project structure

```
src/refcast/
  backends/         # BackendAdapter implementations (gemini_fs.py, exa.py)
  tools/            # MCP tool handlers (corpus_upload.py, research.py, ...)
  router.py         # Serial fallback orchestrator + scope classifier
  models.py         # TypedDicts, RecoveryEnum, Citation, ResearchResult
  config.py         # Credential loading (dotenv + keyring chain)
  size_guard.py     # 25KB response cap enforcement
  mcp.py            # FastMCP server entry point
  cli.py            # refcast init / auth / doctor
```

### Testing

128 unit tests with `respx` HTTP mocking + 5 gated integration tests against real APIs. CI runs on Python 3.11/3.12/3.13 across Ubuntu and macOS.

```bash
pytest -m "not integration" -q     # fast, no API keys needed
pytest -m integration -q           # real calls, needs GEMINI_API_KEY + EXA_API_KEY
```

## License

[MIT](LICENSE) &copy; 2026 sznix
