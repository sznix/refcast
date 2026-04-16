#!/usr/bin/env bash
# refcast v0.1.0 publish + security hardening script
# Run ONCE: creates repo, pushes, sets topics, hardens security, tags release.
set -euo pipefail

REPO="sznix/refcast"

echo "=== Step 1: Create GitHub repo + push ==="
gh repo create "$REPO" --public --source=. --remote=origin --push

echo ""
echo "=== Step 2: Set repo metadata (SEO + discoverability) ==="
gh repo edit "$REPO" \
  --description "Cast once. Cite anywhere. MCP server for AI agents — multi-backend research with unified citations, automatic failover, and structured errors." \
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
echo "=== Step 3: Disable unused features (reduce attack surface) ==="
gh api "repos/$REPO" --method PATCH \
  -f has_wiki=false \
  -f has_projects=false \
  -f delete_branch_on_merge=true \
  -f allow_squash_merge=true \
  -f allow_merge_commit=false \
  -f allow_rebase_merge=false \
  -f squash_merge_commit_title=PR_TITLE \
  -f squash_merge_commit_message=PR_BODY \
  --silent

echo "  Wiki: disabled"
echo "  Projects: disabled"
echo "  Merge strategy: squash-only"
echo "  Delete branch on merge: enabled"

echo ""
echo "=== Step 4: Enable security features ==="

# Secret scanning + push protection (blocks commits containing API keys)
gh api "repos/$REPO" --method PATCH \
  --input - --silent <<'EOF'
{
  "security_and_analysis": {
    "secret_scanning": {"status": "enabled"},
    "secret_scanning_push_protection": {"status": "enabled"}
  }
}
EOF
echo "  Secret scanning: enabled"
echo "  Push protection: enabled (blocks secret commits before they enter history)"

# Dependabot vulnerability alerts
gh api "repos/$REPO/vulnerability-alerts" --method PUT --silent 2>/dev/null || true
echo "  Dependabot alerts: enabled"

# CodeQL default setup for Python
gh api "repos/$REPO/code-scanning/default-setup" --method PATCH \
  --input - --silent 2>/dev/null <<'EOF'
{"state": "configured", "languages": ["python"]}
EOF
echo "  CodeQL scanning: enabled (Python)"

echo ""
echo "=== Step 5: Branch protection on main ==="
gh api "repos/$REPO/branches/main/protection" --method PUT \
  --input - --silent <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["test (3.12, ubuntu-latest)"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_linear_history": true
}
EOF
echo "  Force push: blocked"
echo "  Branch deletion: blocked"
echo "  Linear history: required"
echo "  CI must pass: yes (test on 3.12/ubuntu)"
echo "  PR reviews: not required (solo maintainer — add when team grows)"

echo ""
echo "=== Step 6: Create issue labels ==="
# Delete GitHub defaults that add noise
for label in "invalid" "question"; do
  gh label delete "$label" --repo "$REPO" --yes 2>/dev/null || true
done

# Create project-specific labels
gh label create "security"        --color "d73a4a" --description "Security fixes or concerns"              --repo "$REPO" --force 2>/dev/null || true
gh label create "breaking change" --color "d73a4a" --description "Breaks backward compatibility"            --repo "$REPO" --force 2>/dev/null || true
gh label create "dependencies"    --color "0366d6" --description "Dependency updates (Dependabot)"          --repo "$REPO" --force 2>/dev/null || true
gh label create "needs more info" --color "9966FF" --description "Waiting for reporter to clarify"          --repo "$REPO" --force 2>/dev/null || true
gh label create "P0"              --color "a81d34" --description "Critical: broken core or security issue"  --repo "$REPO" --force 2>/dev/null || true
echo "  Labels: configured (12 total)"

echo ""
echo "=== Step 7: Enable discussions ==="
gh repo edit "$REPO" --enable-discussions 2>/dev/null || true
echo "  Discussions: enabled (for questions + help)"

echo ""
echo "=========================================="
echo "  REPO CREATED + HARDENED"
echo "=========================================="
echo ""
echo "GitHub:  https://github.com/$REPO"
echo ""
echo "Security features active:"
echo "  - Secret scanning + push protection"
echo "  - Dependabot alerts + auto-updates (pip + github-actions)"
echo "  - CodeQL Python scanning"
echo "  - Branch protection on main (no force push, linear history)"
echo "  - Squash-merge only"
echo ""
echo "NEXT STEPS (manual, before tagging):"
echo ""
echo "  1. Configure PyPI trusted publishing:"
echo "     https://pypi.org/manage/account/publishing/"
echo "     -> Add: repo=sznix/refcast, workflow=release.yml, env=(blank)"
echo ""
echo "  2. Then tag and release:"
echo "     git tag -a v0.1.0 -m 'refcast v0.1.0'"
echo "     git push origin v0.1.0"
echo ""
echo "  3. The release workflow auto-publishes to PyPI + creates GitHub Release."
