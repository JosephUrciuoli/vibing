#!/usr/bin/env bash
set -euo pipefail

# Automates:
# 1) Creating the GitHub repo (if missing)
# 2) Pushing local code to main
# 3) Enabling GitHub Pages from branch `main` and folder `/docs`
# 4) Granting Actions write permissions and PR approval
#
# Prereqs:
# - gh CLI installed and authenticated:   gh auth login
# - git installed
# - This script is run from the repo root

usage() {
  cat <<EOF
Usage: $0 [--repo <owner/name>] [--public|--private] [--force]

Options:
  --repo <owner/name>   Full repo path. Defaults to <gh-user>/<cwd-basename>
  --public              Create repo as public (default)
  --private             Create repo as private
  --force               Overwrite existing 'origin' remote to the target repo

Examples:
  $0 --repo yourname/vibing --public
  $0                      # uses gh user + current directory name
EOF
}

main() {
  local target_repo=""
  local visibility="public"
  local force_remote="false"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --repo)
        target_repo="$2"; shift 2;;
      --public)
        visibility="public"; shift;;
      --private)
        visibility="private"; shift;;
      --force)
        force_remote="true"; shift;;
      -h|--help)
        usage; exit 0;;
      *)
        echo "Unknown argument: $1" >&2; usage; exit 1;;
    esac
  done

  command -v gh >/dev/null 2>&1 || { echo "gh CLI is required. Install from https://cli.github.com/" >&2; exit 1; }
  command -v git >/dev/null 2>&1 || { echo "git is required." >&2; exit 1; }

  echo "Checking GitHub authentication..."
  if ! gh auth status >/dev/null 2>&1; then
    echo "You must run: gh auth login" >&2
    exit 1
  fi

  local gh_user
  gh_user=$(gh api user -q .login)

  local repo_name
  repo_name=$(basename "$(pwd)")

  if [[ -z "$target_repo" ]]; then
    target_repo="$gh_user/$repo_name"
  fi

  local owner
  owner=${target_repo%/*}
  local name
  name=${target_repo#*/}

  echo "Target repo: $owner/$name ($visibility)"

  # Ensure a git repo exists locally
  if [ ! -d .git ]; then
    echo "Initializing git repository..."
    git init -b main
  fi

  # Ensure initial commit exists
  if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
    echo "Creating initial commit..."
    git add -A
    git commit -m "chore: bootstrap vibing"
  fi

  # Create remote repo if missing
  echo "Ensuring remote repository exists..."
  if ! gh repo view "$owner/$name" >/dev/null 2>&1; then
    gh repo create "$owner/$name" --$visibility --source . --remote origin --push
  else
    echo "Remote repository already exists."
    # Ensure origin points to the target repo
    local expected_url="https://github.com/$owner/$name.git"
    if git remote get-url origin >/dev/null 2>&1; then
      current_url=$(git remote get-url origin)
      if [[ "$current_url" != *"$owner/$name"* ]]; then
        if [[ "$force_remote" == "true" ]]; then
          git remote remove origin || true
          git remote add origin "$expected_url"
        else
          echo "origin remote points to a different repo: $current_url" >&2
          echo "Use --force to overwrite it to $expected_url" >&2
          exit 1
        fi
      fi
    else
      git remote add origin "$expected_url"
    fi
    echo "Pushing to main..."
    git push -u origin main
  fi

  # Enable GitHub Pages from branch
  echo "Configuring GitHub Pages (branch: main, path: /docs)..."
  # Try create; if exists, then update
  set +e
  gh api \
    --method POST \
    -H "Accept: application/vnd.github+json" \
    "/repos/$owner/$name/pages" \
    -f "source[branch]=main" \
    -f "source[path]=/docs" >/dev/null 2>&1
  local create_rc=$?
  set -e
  if [[ $create_rc -ne 0 ]]; then
    gh api \
      --method PUT \
      -H "Accept: application/vnd.github+json" \
      "/repos/$owner/$name/pages" \
      -f "source[branch]=main" \
      -f "source[path]=/docs" >/dev/null
  fi

  # Set Actions workflow permissions
  echo "Setting Actions workflow permissions (write + PR approvals)..."
  gh api \
    --method PUT \
    -H "Accept: application/vnd.github+json" \
    "/repos/$owner/$name/actions/permissions" \
    -f default_workflow_permissions=write \
    -f can_approve_pull_request_reviews=true >/dev/null

  # Fetch Pages URL
  local pages_url
  pages_url=$(gh api "/repos/$owner/$name/pages" -q .html_url)
  echo "\nGitHub Pages is configured. It may take up to a minute to go live."
  echo "Site URL: $pages_url"
}

main "$@"


