#!/usr/bin/env python3
"""
  Fetch open PRs across Ansible Devtools repositories and categorize by review status.
  
  Categories:
    ready_to_merge     - approved, checks passing, no conflicts
    needs_review       - no reviews yet or review requested
    changes_requested  - reviewer requested changes
    draft              - PR is in draft state
    stale              - no activity in 14+ days
    blocked            - merge conflicts or failing checks (non-draft, reviewed)
  
  Usage:
      python3 scripts/fetch_open_prs.py ansible ansible-lint
      python3 scripts/fetch_open_prs.py --repos-file config/repos.json
      python3 scripts/fetch_open_prs.py --repos-file config/repos.json --stale-days 14
      python3 scripts/fetch_open_prs.py --repos-file config/repos.json --include-bots
"""
  
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone


STALE_THRESHOLD_DAYS = 14

BOT_AUTHORS = {
    "renovate[bot]",
    "dependabot[bot]",
    "pre-commit-ci[bot]",
    "konflux-internal-p02[bot]",
    "konflux[bot]",
    "github-actions[bot]",
    "codecov[bot]",
    "mergify[bot]",
}


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


def get_review_states(owner, repo, pr_number):
    """Get the review states for a PR."""
    reviews = gh_api(f"repos/{owner}/{repo}/pulls/{pr_number}/reviews")
    if not reviews or not isinstance(reviews, list):
        return []
    return [r.get("state", "") for r in reviews]


def get_check_state(owner, repo, sha):
    """Get combined commit status."""
    data = gh_api(f"repos/{owner}/{repo}/commits/{sha}/status")
    if not data:
        return "unknown"
    return data.get("state", "unknown")


def categorize(pr, review_states, check_state, now, stale_days):
    """Assign a category to a PR."""
    if pr.get("draft", False):
        return "draft"

    updated = pr.get("updated_at", "")
    if updated:
        try:
            updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            if (now - updated_dt).days >= stale_days:
                return "stale"
        except (ValueError, TypeError):
            pass

    if "CHANGES_REQUESTED" in review_states:
        return "changes_requested"

    has_approval = "APPROVED" in review_states
    checks_ok = check_state in ("success", "unknown")
    mergeable = pr.get("mergeable_state", "") != "dirty"

    if has_approval and checks_ok and mergeable:
        return "ready_to_merge"

    if has_approval and (not checks_ok or not mergeable):
        return "blocked"

    return "needs_review"


def fetch_repo_prs(owner, repo, stale_days, include_bots):
    """Fetch and categorize open PRs for one repo."""
    print(f"\nFetching {owner}/{repo}...", file=sys.stderr)

    prs_raw = gh_api(f"repos/{owner}/{repo}/pulls?state=open&per_page=100")
    if prs_raw is None:
        return {
            "owner": owner, "repo": repo,
            "error": "Failed to fetch PRs",
            "prs": [], "bot_prs": [],
            "summary": {"total": 0, "ready_to_merge": 0, "needs_review": 0,
                        "changes_requested": 0, "draft": 0, "stale": 0, "blocked": 0},
            "bot_summary": {"total": 0}
        }

    now = datetime.now(timezone.utc)
    human_prs = []
    bot_prs = []

    for pr in prs_raw:
        author = pr.get("user", {}).get("login", "")
        is_bot = author in BOT_AUTHORS

        pr_number = pr["number"]
        review_states = get_review_states(owner, repo, pr_number)

        head_sha = pr.get("head", {}).get("sha", "")
        check_state = get_check_state(owner, repo, head_sha) if head_sha else "unknown"

        category = categorize(pr, review_states, check_state, now, stale_days)

        created = pr.get("created_at", "")
        age_days = 0
        if created:
            try:
                age_days = (now - datetime.fromisoformat(created.replace("Z", "+00:00"))).days
            except (ValueError, TypeError):
                pass

        entry = {
            "number": pr_number,
            "title": pr["title"],
            "author": author,
            "url": pr.get("html_url", ""),
            "created_at": created,
            "updated_at": pr.get("updated_at", ""),
            "age_days": age_days,
            "labels": [l.get("name", "") for l in pr.get("labels", [])],
            "draft": pr.get("draft", False),
            "category": category,
        }

        if is_bot:
            bot_prs.append(entry)
        else:
            human_prs.append(entry)

    summary = {"total": len(human_prs), "ready_to_merge": 0, "needs_review": 0,
                "changes_requested": 0, "draft": 0, "stale": 0, "blocked": 0}
    for p in human_prs:
        if p["category"] in summary:
            summary[p["category"]] += 1

    result = {
        "owner": owner, "repo": repo,
        "fetched_at": now.isoformat(),
        "error": None,
        "prs": human_prs,
        "summary": summary,
        "bot_prs": bot_prs if include_bots else [],
        "bot_summary": {"total": len(bot_prs)},
    }
    return result


def load_repos(path):
    """Load repo list from config file."""
    with open(path) as f:
        return json.load(f).get("repos", [])


def main():
    parser = argparse.ArgumentParser(description="Fetch open PRs across repos")
    parser.add_argument("owner", nargs="?", help="GitHub org")
    parser.add_argument("repo", nargs="?", help="Repo name")
    parser.add_argument("--repos-file", help="Path to repos.json for batch mode")
    parser.add_argument("--stale-days", type=int, default=14,
                        help="Days inactive before marking stale (default: 14)")
    parser.add_argument("--include-bots", action="store_true",
                        help="Include bot PR details in output")
    args = parser.parse_args()

    if args.repos_file:
        repos = load_repos(args.repos_file)
        results = []
        for r in repos:
            result = fetch_repo_prs(r["owner"], r["repo"], args.stale_days, args.include_bots)
            results.append(result)

        output = {
            "mode": "batch",
            "total_repos": len(repos),
            "results": results,
            "aggregate": {
                "total_prs": sum(r["summary"]["total"] for r in results),
                "ready_to_merge": sum(r["summary"]["ready_to_merge"] for r in results),
                "needs_review": sum(r["summary"]["needs_review"] for r in results),
                "changes_requested": sum(r["summary"]["changes_requested"] for r in results),
                "draft": sum(r["summary"]["draft"] for r in results),
                "stale": sum(r["summary"]["stale"] for r in results),
                "blocked": sum(r["summary"]["blocked"] for r in results),
                "total_bot_prs": sum(r["bot_summary"]["total"] for r in results),
                "repos_with_errors": sum(1 for r in results if r["error"]),
            }
        }
    elif args.owner and args.repo:
        output = fetch_repo_prs(args.owner, args.repo, args.stale_days, args.include_bots)
    else:
        parser.error("Provide OWNER REPO or --repos-file")
        return

    json.dump(output, sys.stdout, indent=2)
    print(file=sys.stdout)


if __name__ == "__main__":
    main()