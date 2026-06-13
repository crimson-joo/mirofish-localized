#!/usr/bin/env bash
set -euo pipefail

repo="${1:-crimson-joo/mirofish-localized}"
expected_default="${EXPECTED_DEFAULT_BRANCH:-main}"
expected_integration="${EXPECTED_INTEGRATION_BRANCH:-develop}"
required_status_context="${REQUIRED_MAIN_STATUS_CONTEXT:-validate}"

fail=0
say() { printf '%s\n' "$*"; }

current_branch="$(git branch --show-current 2>/dev/null || true)"
say "repo=$repo"
say "current_branch=${current_branch:-unknown}"

if git rev-parse --verify "$expected_integration" >/dev/null 2>&1; then
  say "PASS local branch exists: $expected_integration"
else
  say "FAIL missing local branch: $expected_integration"
  fail=1
fi

if git rev-parse --verify "$expected_default" >/dev/null 2>&1; then
  say "PASS local branch exists: $expected_default"
else
  say "FAIL missing local branch: $expected_default"
  fail=1
fi

if command -v gh >/dev/null 2>&1 && gh auth status -h github.com >/dev/null 2>&1; then
  default_branch="$(gh repo view "$repo" --json defaultBranchRef --jq '.defaultBranchRef.name')"
  say "github_default_branch=$default_branch"
  if [ "$default_branch" = "$expected_default" ]; then
    say "PASS GitHub default branch is $expected_default"
  else
    say "FAIL GitHub default branch is $default_branch; expected $expected_default"
    fail=1
  fi

  for branch in "$expected_default" "$expected_integration"; do
    if gh api "repos/$repo/branches/$branch" >/dev/null 2>&1; then
      say "PASS remote branch exists: $branch"
    else
      say "FAIL missing remote branch: $branch"
      fail=1
    fi
  done

  if protection_json="$(gh api "repos/$repo/branches/$expected_default/protection" 2>/dev/null)"; then
    say "PASS $expected_default branch protection is enabled"

    if jq -e --arg context "$required_status_context" '
      .required_status_checks.strict == true
      and (.required_status_checks.contexts // [] | index($context))
    ' >/dev/null <<<"$protection_json"; then
      say "PASS $expected_default requires up-to-date status check: $required_status_context"
    else
      say "FAIL $expected_default missing strict required status check: $required_status_context"
      fail=1
    fi

    if jq -e '.required_pull_request_reviews != null' >/dev/null <<<"$protection_json"; then
      say "PASS $expected_default requires pull request before merge"
    else
      say "FAIL $expected_default does not require pull request before merge"
      fail=1
    fi

    if jq -e '
      (.enforce_admins.enabled == true)
      and (.required_conversation_resolution.enabled == true)
      and (.allow_force_pushes.enabled == false)
      and (.allow_deletions.enabled == false)
    ' >/dev/null <<<"$protection_json"; then
      say "PASS $expected_default blocks force-push/delete and enforces admin/conversation safeguards"
    else
      say "FAIL $expected_default branch protection safeguards are incomplete"
      fail=1
    fi
  else
    say "FAIL $expected_default branch protection is not enabled or cannot be read"
    fail=1
  fi
else
  say "SKIP GitHub default branch check: gh auth unavailable"
fi

if [ "$current_branch" = "$expected_default" ] && [ -n "$(git status --porcelain)" ]; then
  say "WARN dirty worktree on $expected_default. For feature work, move changes to feat/* based on $expected_integration."
fi

exit "$fail"
