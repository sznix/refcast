# Security

## Reporting vulnerabilities

If you find a security issue, **do not open a public GitHub issue.** Instead, use [GitHub's private vulnerability reporting](https://github.com/sznix/refcast/security/advisories/new) to submit it confidentially.

Include:
- Description of the vulnerability
- Steps to reproduce
- Impact assessment

I will respond within 72 hours and work with you on a fix before public disclosure.

## Data flow

Understanding what data goes where when you use refcast:

```
Your machine                   External services
┌─────────────┐
│  refcast    │
│  (local     │──── queries ──────────► Gemini API (Google)
│   process,  │──── queries ──────────► Exa API
│   stdio)    │──── uploaded docs ────► Gemini File Search (Google)
│             │
│  No data    │╌╌╌╌ nothing ╌╌╌╌╌╌╌╌► refcast servers (none exist)
│  leaves     │╌╌╌╌ nothing ╌╌╌╌╌╌╌╌► any telemetry service
│  except to  │╌╌╌╌ nothing ╌╌╌╌╌╌╌╌► any analytics
│  the APIs   │
└─────────────┘
```

- **refcast is a local stdio process.** It runs on YOUR machine, not a server.
- **No telemetry, no analytics, no phone-home.** Zero network calls beyond the two APIs you configured.
- **Your queries go to Google and/or Exa** — subject to their privacy policies, not ours.
- **Your uploaded documents go to Google Gemini File Search** — stored in your Google account, subject to [Google's AI terms](https://ai.google.dev/gemini-api/terms).

## API key safety

| Storage method | Security level | When to use |
|:---------------|:---------------|:------------|
| macOS Keychain (`refcast auth --store keyring`) | Encrypted by OS, requires user auth to access | Personal Mac |
| Environment variables (`GEMINI_API_KEY=...`) | Visible to all processes in the same shell session | CI, Docker, servers |
| `.env` file | Plaintext on disk (gitignored by default) | Local dev, convenience |

**Best practices:**
- Never commit `.env` files (`.gitignore` already covers this)
- Rotate keys if you suspect compromise
- Use the minimum-permission API key tier (free tier is sufficient for most use)
- On shared machines, prefer keychain over env vars or .env files

## What refcast does NOT do

- **Does not encrypt your data at rest.** Queries and responses are processed in memory and discarded. If you need audit logging or at-rest encryption, you must implement that separately.
- **Does not anonymize your queries.** Google and Exa see your raw query text. If your queries contain sensitive information, consider that before sending them to external APIs.
- **Does not validate citation truthfulness.** refcast normalizes citation FORMAT, not citation ACCURACY. A backend could return a citation that misquotes or hallucinates a source. Verify citations independently for high-stakes use.
- **Does not rate-limit your usage.** If you run an automated loop that fires 10,000 queries, you will exhaust your API quota and possibly incur charges. Use `constraints.max_cost_cents` (v0.2) for programmatic budget caps.

## ToS compliance

refcast uses only official, documented APIs:
- **Gemini File Search API** — [Google AI terms](https://ai.google.dev/gemini-api/terms)
- **Exa API** — [Exa terms](https://exa.ai/terms)

refcast does **not** include cookie-scraping, browser automation, or undocumented endpoint access. The companion tool `notebooklm-mcp-cli` (separate project, not maintained by us) does use browser automation — consult its documentation for ToS implications.

## Dependency security

All 102 runtime + dev dependencies use permissive licenses (MIT, Apache 2.0, BSD, ISC, MPL-2.0). Zero GPL/AGPL/proprietary dependencies. Full audit available via:

```bash
pip install pip-licenses && pip-licenses --format=table
```

## Supply chain

- Published to PyPI via [trusted publishing](https://docs.pypi.org/trusted-publishers/) (OIDC, no API token stored in GitHub secrets)
- CI runs on `ubuntu-latest` and `macos-latest` with pinned `astral-sh/setup-uv@v7`
- Dependencies are version-bounded in `pyproject.toml` (minor-version upper bounds)
