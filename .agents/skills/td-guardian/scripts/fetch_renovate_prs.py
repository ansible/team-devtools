"""
Fetch Renovate and dependency bot PRs across Ansible Devtools repositories.

Tracks open dependency update PRs and applies cooldown policy thresholds:
- Security updates: overdue after 3 days
- Minor/patch updates: overdue after 7 days
- Major version bumps: overdue after 14 days

Usage:
    python3 scripts/fetch_renovate_prs.py ansible ansible-lint
    python3 scripts/fetch_renovate_prs.py --repos-file config/repos.json
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone


BOT_AUTHORS = {
    "renovate[bot]",
    "dependabot[bot]",
    "konflux-internal-p02[bot]",
    "konflux[bot]",
    "pre-commit-ci[bot]",
}

SECURITY_PATTERNS = re.compile(
    r"(CVE-|security|vulnerability|GHSA-)", re.IGNORECASE
)
MAJOR_PATTERNS = re.compile(
    r"(major update|update .+ to v?\d+\.0|bump .+ from \d+\.\d+ to \d+\.)",
    re.IGNORECASE,
)


def gh_api(endpoint):
    """Call gh api and return parsed JSON. Returns None on failure."""
    cmd = ["gh", "api", endpoint]
    print(f"  gh api {endpoint[:80]}...", file=sys.stderr)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        print("ERROR: gh CLI not found", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT: {endpoint}", file=sys.stderr)
        return None

    if result.returncode != 0:
        stderr_msg = result.stderr.strip()
        print(f"  WARN: {endpoint} -> {stderr_msg[:100]}", file=sys.stderr)
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def classify_update(title, labels):
    """Classify a dependency PR as security, major, or minor."""
    combined = title + " " + " ".join(labels)
    if SECURITY_PATTERNS.search(combined):
        return "security"
    if MAJOR_PATTERNS.search(title):
        return "major"
    return "minor"


def cooldown_threshold(update_type):
    """Return the overdue threshold in days for each update type."""
    if update_type == "security":
        return 3
    if update_type == "major":
        return 14
    return 7


def fetch_repo_renovate(owner, repo):
    """Fetch dependency bot PRs for a single repo."""
    print(f"\nFetching dependency PRs for {owner}/{repo}...", file=sys.stderr)

    prs_raw = gh_api(f"repos/{owner}/{repo}/pulls?state=open&per_page=100")
    if prs_raw is None:
        return {
            "owner": owner, "repo": repo,
            "error": "Failed to fetch PRs",
            "prs": [],
            "summary": {"total": 0, "overdue": 0, "security": 0,
                        "major": 0, "minor": 0, "oldest_days": 0,
                        "all_checks_passing": True},
        }

    now = datetime.now(timezone.utc)
    dep_prs = []

    for pr in prs_raw:
        author = pr.get("user", {}).get("login", "")
        if author not in BOT_AUTHORS:
            continue

        title = pr["title"]
        labels = [l.get("name", "") for l in pr.get("labels", [])]
        update_type = classify_update(title, labels)
        threshold = cooldown_threshold(update_type)

        created = pr.get("created_at", "")
        age_days = 0
        if created:
            try:
                age_days = (now - datetime.fromisoformat(created.replace("Z", "+00:00"))).days
            except (ValueError, TypeError):
                pass

        is_overdue = age_days > threshold

        head_sha = pr.get("head", {}).get("sha", "")
        check_state = "unknown"
        if head_sha:
            data = gh_api(f"repos/{owner}/{repo}/commits/{head_sha}/status")
            if data:
                check_state = data.get("state", "unknown")

        dep_prs.append({
            "number": pr["number"],
            "title": title,
            "author": author,
            "url": pr.get("html_url", ""),
            "created_at": created,
            "age_days": age_days,
            "labels": labels,
            "update_type": update_type,
            "threshold_days": threshold,
            "is_overdue": is_overdue,
            "check_state": check_state,
            "mergeable_state": pr.get("mergeable_state", ""),
        })

    overdue_count = sum(1 for p in dep_prs if p["is_overdue"])
    security_count = sum(1 for p in dep_prs if p["update_type"] == "security")
    major_count = sum(1 for p in dep_prs if p["update_type"] == "major")
    minor_count = sum(1 for p in dep_prs if p["update_type"] == "minor")
    oldest = max((p["age_days"] for p in dep_prs), default=0)
    all_passing = all(p["check_state"] == "success" for p in dep_prs) if dep_prs else True

    return {
        "owner": owner, "repo": repo,
        "fetched_at": now.isoformat(),
        "error": None,
        "prs": dep_prs,
        "summary": {
            "total": len(dep_prs),
            "overdue": overdue_count,
            "security": security_count,
            "major": major_count,
            "minor": minor_count,
            "oldest_days": oldest,
            "all_checks_passing": all_passing,
        },
    }


def load_repos(path):
    """Load repo list from config file."""
    with open(path) as f:
        return json.load(f).get("repos", [])


def main():
    parser = argparse.ArgumentParser(description="Fetch Renovate/dependency bot PRs")
    parser.add_argument("owner", nargs="?", help="GitHub org")
    parser.add_argument("repo", nargs="?", help="Repo name")
    parser.add_argument("--repos-file", help="Path to repos.json for batch mode")
    args = parser.parse_args()

    if args.repos_file:
        repos = load_repos(args.repos_file)
        results = []
        for r in repos:
            result = fetch_repo_renovate(r["owner"], r["repo"])
            results.append(result)

        output = {
            "mode": "batch",
            "total_repos": len(repos),
            "results": results,
            "aggregate": {
                "total_prs": sum(r["summary"]["total"] for r in results),
                "overdue": sum(r["summary"]["overdue"] for r in results),
                "security": sum(r["summary"]["security"] for r in results),
                "major": sum(r["summary"]["major"] for r in results),
                "minor": sum(r["summary"]["minor"] for r in results),
                "oldest_days": max((r["summary"]["oldest_days"] for r in results), default=0),
                "repos_with_errors": sum(1 for r in results if r["error"]),
            },
        }
    elif args.owner and args.repo:
        output = fetch_repo_renovate(args.owner, args.repo)
    else:
        parser.error("Provide OWNER REPO or --repos-file")
        return

    json.dump(output, sys.stdout, indent=2)
    print(file=sys.stdout)


if __name__ == "__main__":
    main()