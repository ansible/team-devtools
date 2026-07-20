"""
Fetch code coverage data from Codecov for Ansible Devtools repositories.

Retrieves latest coverage percentages, trends, and commit details from the
Codecov API. Works without authentication for public repositories.

Usage:
    python3 scripts/fetch_codecov.py --repos-file config/repos.json
    python3 scripts/fetch_codecov.py --codecov-config config/codecov.json
    python3 scripts/fetch_codecov.py ansible ansible-lint
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

BASE_URL = "https://api.codecov.io/api/v2"


def codecov_api(endpoint, token=None):
    """Call Codecov API and return parsed JSON. Returns None on failure."""
    url = f"{BASE_URL}/{endpoint}"
    print(f"  GET {url[:90]}...", file=sys.stderr)

    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  WARN: HTTP {e.code} for {url}", file=sys.stderr)
        return None
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  WARN: {e} for {url}", file=sys.stderr)
        return None
    except json.JSONDecodeError:
        return None


def fetch_repo_coverage(owner, repo, token=None):
    """Fetch coverage data for a single repo from Codecov."""
    print(f"\nFetching Codecov for {owner}/{repo}...", file=sys.stderr)

    data = codecov_api(f"github/{owner}/repos/{repo}/", token)

    if data is None:
        return {
            "owner": owner, "repo": repo,
            "error": "Failed to fetch from Codecov API",
            "coverage": None,
            "trend": None,
        }

    totals = data.get("totals", {}) or {}
    coverage = totals.get("coverage")
    if coverage is not None:
        coverage = round(float(coverage), 2)

    latest_commit = data.get("commit", {}) or {}
    commit_totals = latest_commit.get("totals", {}) or {}

    lines = totals.get("lines", 0)
    hits = totals.get("hits", 0)
    misses = totals.get("misses", 0)
    branches = totals.get("branches", 0)

    return {
        "owner": owner,
        "repo": repo,
        "error": None,
        "coverage": coverage,
        "lines": lines,
        "hits": hits,
        "misses": misses,
        "branches": branches,
        "language": data.get("language", "unknown"),
        "activated": data.get("activated", False),
        "active": data.get("active", False),
        "updatestamp": data.get("updatestamp", ""),
        "branch": data.get("branch", "main"),
    }


def load_repos_from_config(path):
    """Load repo list from repos.json config."""
    with open(path) as f:
        data = json.load(f)
    return [(r["owner"], r["repo"]) for r in data.get("repos", [])]


def load_codecov_config(path):
    """Load repo list from codecov.json config."""
    with open(path) as f:
        data = json.load(f)
    return [(r["owner"], r["repo"]) for r in data.get("repos", [])]


def main():
    parser = argparse.ArgumentParser(description="Fetch Codecov coverage data")
    parser.add_argument("owner", nargs="?", help="GitHub org")
    parser.add_argument("repo", nargs="?", help="Repo name")
    parser.add_argument("--repos-file", help="Path to repos.json for batch mode")
    parser.add_argument("--codecov-config", help="Path to codecov.json for batch mode")
    args = parser.parse_args()

    token = os.environ.get("CODECOV_TOKEN")

    if args.codecov_config:
        repos = load_codecov_config(args.codecov_config)
    elif args.repos_file:
        repos = load_repos_from_config(args.repos_file)
    elif args.owner and args.repo:
        repos = [(args.owner, args.repo)]
    else:
        parser.error("Provide OWNER REPO, --repos-file, or --codecov-config")
        return

    if len(repos) == 1 and not (args.repos_file or args.codecov_config):
        output = fetch_repo_coverage(repos[0][0], repos[0][1], token)
    else:
        results = []
        for owner, repo in repos:
            result = fetch_repo_coverage(owner, repo, token)
            results.append(result)

        active = [r for r in results if not r["error"] and r.get("coverage") is not None]
        coverages = [r["coverage"] for r in active]

        output = {
            "mode": "batch",
            "total_repos": len(repos),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "results": results,
            "aggregate": {
                "repos_with_coverage": len(active),
                "repos_without_coverage": len(repos) - len(active),
                "repos_with_errors": sum(1 for r in results if r["error"]),
                "average_coverage": round(sum(coverages) / len(coverages), 2) if coverages else 0,
                "min_coverage": min(coverages) if coverages else 0,
                "max_coverage": max(coverages) if coverages else 0,
                "repos_above_80": sum(1 for c in coverages if c >= 80),
                "repos_below_50": sum(1 for c in coverages if c < 50),
            },
        }

    json.dump(output, sys.stdout, indent=2)
    print(file=sys.stdout)


if __name__ == "__main__":
    main()
