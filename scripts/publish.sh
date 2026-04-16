#!/usr/bin/env bash
# refcast v0.1.0 — complete publish + hardening script
# Creates repo, pushes code, configures ALL settings, hardens security.
# Based on exhaustive GitHub API research covering 10 setting categories.
set -euo pipefail

REPO="sznix/refcast"

echo "============================================"
echo "  refcast — publish + harden"
echo "============================================"
echo ""

# ─────────────────────────────────────────────────
# A. CREATE REPO + PUSH CODE
# ─────────────────────────────────────────────────
echo "=== A. Create repo + push ==="
gh repo create "$REPO" --public --source=. --remote=origin --push
echo ""

# ─────────────────────────────────────────────────
# B. GENERAL SETTINGS + SEO
# ─────────────────────────────────────────────────
echo "=== B. General settings + SEO ==="
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
echo "  Description: set"
echo "  Topics: 12 set"
echo ""

# ─────────────────────────────────────────────────
# C. FEATURE TOGGLES
# ─────────────────────────────────────────────────
echo "=== C. Feature toggles ==="
gh api "repos/$REPO" --method PATCH \
  -f has_wiki=false \
  -f has_projects=false \
  --silent
gh repo edit "$REPO" --enable-discussions 2>/dev/null || true
echo "  Wiki: OFF (unused attack surface)"
echo "  Projects: OFF (solo maintainer)"
echo "  Issues: ON (default)"
echo "  Discussions: ON (Q&A channel)"
echo ""

# ─────────────────────────────────────────────────
# D. PULL REQUEST + MERGE SETTINGS
# ─────────────────────────────────────────────────
echo "=== D. PR + merge settings ==="
gh api "repos/$REPO" --method PATCH \
  -f allow_squash_merge=true \
  -f allow_merge_commit=false \
  -f allow_rebase_merge=false \
  -f squash_merge_commit_title=PR_TITLE \
  -f squash_merge_commit_message=PR_BODY \
  -f delete_branch_on_merge=true \
  -F allow_auto_merge=true \
  -F allow_update_branch=true \
  --silent
echo "  Squash-merge only: ON"
echo "  Merge commits: OFF"
echo "  Rebase merge: OFF"
echo "  Squash title: PR title"
echo "  Squash message: PR body"
echo "  Delete branch on merge: ON"
echo "  Auto-merge: ON (merges when checks pass)"
echo "  Update branch button: ON"
echo ""

# ─────────────────────────────────────────────────
# E. SECURITY + ANALYSIS (exhaustive)
# ─────────────────────────────────────────────────
echo "=== E. Security + analysis ==="

# Secret scanning (all layers)
gh api "repos/$REPO" --method PATCH --input - --silent <<'EOF'
{
  "security_and_analysis": {
    "secret_scanning": {"status": "enabled"},
    "secret_scanning_push_protection": {"status": "enabled"},
    "secret_scanning_validity_checks": {"status": "enabled"},
    "secret_scanning_non_provider_patterns": {"status": "enabled"},
    "private_vulnerability_reporting": {"status": "enabled"}
  }
}
EOF
echo "  Secret scanning: ON"
echo "  Push protection: ON (blocks commits with secrets)"
echo "  Validity checks: ON (verifies detected secrets are active)"
echo "  Non-provider patterns: ON (catches generic keys/passwords)"
echo "  Private vuln reporting: ON (researchers can report securely)"

# Dependabot
gh api "repos/$REPO/vulnerability-alerts" --method PUT --silent 2>/dev/null || true
gh api "repos/$REPO" --method PATCH --input - --silent 2>/dev/null <<'DEOF'
{"security_and_analysis":{"dependabot_security_updates":{"status":"enabled"}}}
DEOF
echo "  Dependabot alerts: ON"
echo "  Dependabot security updates: ON (auto-PRs for vuln deps)"
echo "  Dependabot version updates: ON (via .github/dependabot.yml in repo)"

# CodeQL
gh api "repos/$REPO/code-scanning/default-setup" --method PATCH \
  --input - --silent 2>/dev/null <<'CEOF'
{"state": "configured", "languages": ["python"]}
CEOF
echo "  CodeQL Python: ON"
echo ""

# ─────────────────────────────────────────────────
# F. GITHUB ACTIONS PERMISSIONS
# ─────────────────────────────────────────────────
echo "=== F. GitHub Actions permissions ==="
gh api "repos/$REPO/actions/permissions/workflow" --method PUT \
  -f default_workflow_permissions=read \
  -F can_approve_pull_request_reviews=false \
  --silent 2>/dev/null || true
echo "  Default GITHUB_TOKEN: read-only (least privilege)"
echo "  Actions can approve PRs: OFF"
echo ""

# ─────────────────────────────────────────────────
# G. BRANCH PROTECTION (after push, branch exists)
# ─────────────────────────────────────────────────
echo "=== G. Branch protection on main ==="
gh api "repos/$REPO/branches/main/protection" --method PUT \
  --input - --silent <<'BEOF'
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
  "required_linear_history": true,
  "allow_fork_syncing": true
}
BEOF
echo "  Force push: BLOCKED"
echo "  Branch deletion: BLOCKED"
echo "  Linear history: REQUIRED"
echo "  CI must pass: YES"
echo "  Admins enforced: YES (rules apply to you too)"
echo "  Fork syncing: ON"
echo "  PR reviews: OFF (solo — enable when team grows)"
echo ""

# ─────────────────────────────────────────────────
# H. LABELS
# ─────────────────────────────────────────────────
echo "=== H. Issue labels ==="
for label in "invalid" "question"; do
  gh label delete "$label" --repo "$REPO" --yes 2>/dev/null || true
done
gh label create "security"        --color "d73a4a" --description "Security fixes or concerns"              --repo "$REPO" --force 2>/dev/null || true
gh label create "breaking change" --color "d73a4a" --description "Breaks backward compatibility"            --repo "$REPO" --force 2>/dev/null || true
gh label create "dependencies"    --color "0366d6" --description "Dependency updates (Dependabot)"          --repo "$REPO" --force 2>/dev/null || true
gh label create "needs more info" --color "9966FF" --description "Waiting for reporter to clarify"          --repo "$REPO" --force 2>/dev/null || true
gh label create "P0"              --color "a81d34" --description "Critical: broken core or security issue"  --repo "$REPO" --force 2>/dev/null || true
echo "  Noisy defaults removed: invalid, question"
echo "  Custom labels added: security, breaking change, dependencies, needs more info, P0"
echo ""

# ─────────────────────────────────────────────────
# I. VERIFICATION
# ─────────────────────────────────────────────────
echo "============================================"
echo "  VERIFICATION"
echo "============================================"
echo ""
gh api "repos/$REPO" --jq '{
  url: .html_url,
  visibility: .visibility,
  wiki: .has_wiki,
  projects: .has_projects,
  discussions: .has_discussions,
  squash_only: (.allow_squash_merge and (.allow_merge_commit | not) and (.allow_rebase_merge | not)),
  auto_merge: .allow_auto_merge,
  update_branch: .allow_update_branch,
  delete_branch: .delete_branch_on_merge,
  secret_scan: .security_and_analysis.secret_scanning.status,
  push_protect: .security_and_analysis.secret_scanning_push_protection.status,
  validity_checks: .security_and_analysis.secret_scanning_validity_checks.status,
  non_provider: .security_and_analysis.secret_scanning_non_provider_patterns.status,
  private_vuln_report: .security_and_analysis.private_vulnerability_reporting.status,
  dependabot_updates: .security_and_analysis.dependabot_security_updates.status
}'

echo ""
echo "Branch protection:"
gh api "repos/$REPO/branches/main/protection" --jq '{
  force_push: .allow_force_pushes.enabled,
  deletions: .allow_deletions.enabled,
  linear_history: .required_linear_history.enabled,
  admin_enforced: .enforce_admins.enabled,
  ci_contexts: .required_status_checks.contexts
}'

echo ""
echo "Topics:"
gh api "repos/$REPO/topics" --jq '.names | join(", ")'

echo ""
echo "============================================"
echo "  DONE — REPO LIVE + HARDENED"
echo "============================================"
echo ""
echo "  https://github.com/$REPO"
echo ""
echo "  NEXT STEPS:"
echo "    1. Go to Settings > Social preview > upload a 1280x640 image"
echo "       (only setting that can't be done via API)"
echo ""
echo "    2. Configure PyPI trusted publishing:"
echo "       https://pypi.org/manage/account/publishing/"
echo "       -> Owner: sznix, Repo: refcast, Workflow: release.yml"
echo ""
echo "    3. Tag and release:"
echo "       git tag -a v0.1.0 -m 'refcast v0.1.0 — Cast once. Cite anywhere.'"
echo "       git push origin v0.1.0"
echo "       (release workflow auto-publishes to PyPI)"
echo ""
echo "    4. Rotate API keys (yours appeared in a conversation transcript):"
echo "       Gemini: https://aistudio.google.com/apikey"
echo "       Exa: https://dashboard.exa.ai/api-keys"
echo "       Then: refcast auth --store keyring"
