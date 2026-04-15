# refcast

> **Cast once. Cite anywhere.**

`refcast` is an open-source Python MCP server that brokers research queries across multiple backends (Gemini File Search, Exa, with NotebookLM Enterprise API in v0.2) and returns a **unified citation envelope** so your agent's prompts never break when one backend fails.

When Google rotates a cookie at 2am or Exa rate-limits, `refcast` falls over to the next backend automatically — same citation shape, same agent code, no rewrite.

## Hero demo

![refcast failover demo](docs/hero.gif)

*One `research()` call across two backends, byte-identical citation JSON. Swap backends with one config line.*

## Install

```bash
# Recommended
uv tool install refcast

# Or with pipx
pipx install refcast

# Or pip
pip install refcast
```

## Quickstart

```bash
# 1. Get API keys (free tier OK):
#    https://aistudio.google.com/apikey
#    https://dashboard.exa.ai/api-keys

# 2. Set them up
refcast init       # scaffolds .env.example
cp .env.example .env
# edit .env, fill in keys
refcast doctor     # verifies setup

# 3. Wire into your MCP client (e.g. Claude Code):
#    "mcpServers": {"refcast": {"command": "refcast-mcp"}}
```

## Tools

| Tool | Purpose |
|---|---|
| `corpus.upload(files)` | Upload PDFs/docs to a new corpus (returns immediately, async indexing) |
| `corpus.status(corpus_id)` | Poll indexing progress |
| `corpus.list()` | List all corpora |
| `corpus.delete(corpus_id)` | Remove a corpus |
| `research(query, corpus_id?, constraints?)` | Query across backends with serial fallback + unified citations |

## Architecture

```
┌─────────────────────────────────────────────┐
│ refcast MCP Server (stdio, fastmcp 3.x)     │
│  ┌─────────────┐   ┌────────────────┐       │
│  │ corpus.*    │   │ research       │       │
│  └──────┬──────┘   └───────┬────────┘       │
│         └──────────┬───────┘                │
│                    ▼                        │
│  ┌────────────────────────────────────┐     │
│  │ Router + Serial Fallback + 25KB    │     │
│  │ enforcement + structured errors    │     │
│  └─────┬────────────────────┬─────────┘     │
│        ▼                    ▼               │
│  Gemini File Search       Exa Search        │
└─────────────────────────────────────────────┘
```

- **Backend-agnostic Protocol**: every adapter implements 5 fields
- **Stripe-style structured errors** with `recovery_action: retry|fallback|user_action`
- **Deterministic `fallback_scope` classification**: `none|same|broader|different` (load-bearing for downstream agents)

## Roadmap

- **v0.1 (now)**: 5 tools, Gemini FS + Exa, serial fallback, normalized citations
- **v0.2**: NotebookLM Enterprise API backend, statistical drift detection (KL-divergence), idempotency for mutations
- **v0.3**: vCache-bounded semantic cache, plugin AuthStrategy

Full design spec: see `~/.claude/docs/specs/refcast/` (not in repo; maintainer's notes).

## Contributing

```bash
git clone https://github.com/sznix/refcast
cd refcast
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest -m "not integration"
```

## License

MIT. © 2026 sznix.
