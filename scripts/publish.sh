#!/usr/bin/env bash
# refcast v0.1.0 publish script
# Run this ONCE to create the GitHub repo, push, set topics, and release.
set -euo pipefail

REPO="sznix/refcast"

echo "=== Step 1: Create GitHub repo + push ==="
gh repo create "$REPO" --public --source=. --remote=origin --push

echo ""
echo "=== Step 2: Set repo metadata (SEO) ==="
gh repo edit "$REPO" \
  --description "Cast once. Cite anywhere. Open-source MCP server for AI agents — multi-backend research with unified citations, automatic failover, and structured errors." \
  --add-topic mcp \
  --add-topic model-context-protocol \
  --add-topic research \
  --add-topic citations \
  --add-topic gemini \
  --add-topic exa \
  --add-topic rag \
  --add-topic ai-agents \
  --add-topic claude-code \
  --add-topic python \
  --add-topic fastmcp \
  --add-topic llm-tools

echo ""
echo "=== Step 3: Tag v0.1.0 ==="
git tag -a v0.1.0 -m "refcast v0.1.0 — Cast once. Cite anywhere.

5 MCP tools, 2 backends (Gemini File Search + Exa), serial fallback,
unified citation envelope, 14-code structured error taxonomy.

128 unit tests, Python 3.11+, MIT license."

echo ""
echo "=== Step 4: Push tag (triggers PyPI release via GitHub Actions) ==="
git push origin v0.1.0

echo ""
echo "=== Done ==="
echo "GitHub:  https://github.com/$REPO"
echo "PyPI:    https://pypi.org/project/refcast/ (available after CI completes)"
echo "Install: pip install refcast"
echo ""
echo "IMPORTANT: Configure PyPI trusted publishing BEFORE the tag push takes effect:"
echo "  1. Go to https://pypi.org/manage/account/publishing/"
echo "  2. Add: owner=$REPO, workflow=release.yml, environment=(leave blank)"
echo "  3. Then the release workflow can publish automatically."
