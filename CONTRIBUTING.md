# Contributing to refcast

Thanks for your interest! Here's how to get involved.

## Setup

```bash
git clone https://github.com/sznix/refcast
cd refcast
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Before you submit a PR

1. **Open an issue first** for anything beyond a typo fix. This prevents wasted work if the change doesn't fit the project direction.
2. **Write tests.** Every new feature or bugfix needs a test. Run `pytest -m "not integration"` to verify.
3. **Lint and type-check.** `ruff check . && ruff format . && mypy src/refcast/` should all pass clean.
4. **Keep PRs small.** One feature or fix per PR. Easier to review, easier to revert if something goes wrong.

## Code style

- Python 3.11+, type hints everywhere, `mypy --strict`
- `ruff` for formatting and linting (config in `pyproject.toml`)
- Conventional commit messages: `feat(scope):`, `fix(scope):`, `test(scope):`, `docs:`, `ci:`
- No `Co-Authored-By` trailers in commits

## Adding a new backend

This is the most common contribution. A new backend is one Python file:

1. Create `src/refcast/backends/your_backend.py`
2. Implement the `BackendAdapter` Protocol (see `backends/base.py` — 3 methods: `execute`, and that's it for v0.1)
3. Add tests in `tests/backends/test_your_backend.py`
4. Register it in `src/refcast/mcp.py`

Look at `backends/exa.py` as a template — it's the simplest existing adapter.

## What we're NOT looking for right now

- Cookie-scraping backends (ToS concerns — see SECURITY.md)
- Semantic caching (deferred to v0.3 with formal error bounds)
- LLM-as-judge features (research showed reliability issues — see design spec)

## Questions?

Open a [discussion](https://github.com/sznix/refcast/discussions) or file an issue.
