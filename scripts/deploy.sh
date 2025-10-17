#!/usr/bin/env bash
set -euo pipefail

# Deploy helper: commits and pushes changes, then prints the Pages URL.
# Defaults to committing only changes under docs/ to keep the site-focused.

usage() {
  cat <<EOF
Usage: $0 [--all] [--message "commit message"]

Options:
  --all                 Commit all changes (not just docs/)
  --message <msg>       Custom commit message. Default: chore(site): deploy

Examples:
  $0 --message "update homepage copy"
  $0 --all
EOF
}

main() {
  local commit_all=false
  local message="chore(site): deploy"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --all)
        commit_all=true; shift;;
      --message)
        message="$2"; shift 2;;
      -h|--help)
        usage; exit 0;;
      *)
        echo "Unknown argument: $1" >&2; usage; exit 1;;
    esac
  done

  command -v git >/dev/null 2>&1 || { echo "git is required." >&2; exit 1; }
  command -v gh >/dev/null 2>&1 || { echo "gh CLI is required for printing the Pages URL. Install gh or skip." >&2; }

  # Ensure repo
  if [ ! -d .git ]; then
    echo "This is not a git repository." >&2
    exit 1
  fi

  # Stage changes
  if [[ "$commit_all" == true ]]; then
    git add -A
  else
    git add docs/
  fi

  # If nothing to commit, exit gracefully
  if git diff --cached --quiet; then
    echo "No changes to deploy."
    exit 0
  fi

  # Commit and push
  git commit -m "$message"
  local branch
  branch=$(git rev-parse --abbrev-ref HEAD)
  git push origin "$branch"

  # Print Pages URL if available
  if command -v gh >/dev/null 2>&1; then
    local owner name
    owner=$(gh repo view --json owner --jq .owner.login || echo "")
    name=$(gh repo view --json name --jq .name || echo "")
    if [[ -n "$owner" && -n "$name" ]]; then
      local pages_url
      pages_url=$(gh api "/repos/$owner/$name/pages" -q .html_url 2>/dev/null || echo "")
      if [[ -n "$pages_url" ]]; then
        echo "Deployed. Pages URL: $pages_url"
      else
        echo "Deployed. Pages URL not available yet."
      fi
    fi
  fi
}

main "$@"


