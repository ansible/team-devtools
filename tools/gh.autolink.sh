#!/usr/bin/env bash
# Configure autolink references for all GitHub repos listed in repos.lst.
# Each line is org/repo (see config/repos.lst). Blank lines and # comments are ignored.
# Idempotent: skips entries that already match, updates ones with a changed URL.
# Usage: ./gh.autolink.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOS_FILE="$SCRIPT_DIR/../config/repos.lst"

# Desired autolinks: "KEY_PREFIX|URL_TEMPLATE"
DESIRED=(
  "AAP-|https://redhat.atlassian.net/browse/AAP-<num>"
  "ACA-|https://redhat.atlassian.net/browse/ACA-<num>"
  "ANSTRAT-|https://redhat.atlassian.net/browse/ANSTRAT-<num>"
)

while IFS= read -r line || [[ -n "$line" ]]; do
  # strip comments and trim whitespace
  line="${line%%#*}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  [[ -z "$line" ]] && continue
  if [[ "$line" != */* ]]; then
    echo "gh.autolink.sh: expected org/repo, got: $line" >&2
    exit 1
  fi
  ORG="${line%%/*}"
  repo="${line#*/}"

  current=$(gh api "repos/$ORG/$repo/autolinks" 2>/dev/null || echo "[]")

  for entry in "${DESIRED[@]}"; do
    prefix="${entry%%|*}"
    url="${entry##*|}"

    existing=$(echo "$current" | python3 -c "
import json, sys
data = json.load(sys.stdin)
match = next((x for x in data if x['key_prefix'] == '$prefix'), None)
if match:
    print(match['id'], match['url_template'])
" 2>/dev/null || true)

    if [[ -z "$existing" ]]; then
      echo "[add] $ORG/$repo $prefix -> $url"
      gh api "repos/$ORG/$repo/autolinks" \
        --method POST \
        -f key_prefix="$prefix" \
        -f url_template="$url" \
        -F is_alphanumeric=false \
        --silent && echo "           done" || echo "           FAILED"
    else
      existing_id="${existing%% *}"
      existing_url="${existing#* }"
      if [[ "$existing_url" == "$url" ]]; then
        echo "[skip] $ORG/$repo $prefix already up to date"
      else
        echo "[update] $ORG/$repo $prefix from $existing_url to $url"
        gh api "repos/$ORG/$repo/autolinks/$existing_id" \
          --method DELETE \
          --silent && \
        gh api "repos/$ORG/$repo/autolinks" \
          --method POST \
          -f key_prefix="$prefix" \
          -f url_template="$url" \
          -F is_alphanumeric=false \
          --silent && echo "           done" || echo "           FAILED"
      fi
    fi
  done
done < "$REPOS_FILE"
