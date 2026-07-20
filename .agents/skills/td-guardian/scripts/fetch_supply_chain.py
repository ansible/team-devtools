#!/usr/bin/env python3
"""Fetch supply-chain audit data for the Guardian dashboard.

Collects three categories of findings from the GitHub API and OSV.dev:
  1. Post-approval commits — code pushed after PR was approved
  2. Bot-only approvals — PRs merged without human review
  3. Known vulnerabilities — packages with CVEs (via OSV.dev)

Output: JSON suitable for --supply-chain flag in generate_dashboard.py

Usage:
    python3 scripts/fetch_supply_chain.py --repos-file config/repos.json > reports/supply-chain.json
    python3 scripts/fetch_supply_chain.py --repos-file config/repos.json --days 30
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

GH_TOKEN = os.environ.get("GH_TOKEN", "")
BOT_ACCOUNTS = {
    "ansibuddy",
    "dependabot[bot]",
    "renovate[bot]",
    "github-actions[bot]",
    "pre-commit-ci[bot]",
    "codecov[bot]",
    "mergify[bot]",
}

OSV_API = "https://api.osv.dev/v1/query"
LOCK_FILES = {
    "requirements.txt",
    "constraints.txt",
    "uv.lock",
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
}
DEP_FILES = {"pyproject.toml", "setup.cfg", "package.json"}


def _is_bot(login: str) -> bool:
    return login in BOT_ACCOUNTS or login.endswith("[bot]")


def gh_api(endpoint: str, per_page: int = 100) -> Any:
    """Call GitHub REST API with pagination support."""
    results = []
    url = f"https://api.github.com/{endpoint}"
    separator = "&" if "?" in url else "?"
    url += f"{separator}per_page={per_page}"

    while url:
        req = Request(url)
        req.add_header("Accept", "application/vnd.github+json")
        if GH_TOKEN:
            req.add_header("Authorization", f"Bearer {GH_TOKEN}")

        try:
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                if isinstance(data, list):
                    results.extend(data)
                else:
                    return data

                link = resp.headers.get("Link", "")
                url = ""
                for part in link.split(","):
                    if 'rel="next"' in part:
                        url = part.split("<")[1].split(">")[0]
                        break
        except (HTTPError, URLError) as e:
            print(f"  WARN: GitHub API error for {endpoint}: {e}", file=sys.stderr)
            return results if results else []

    return results


def gh_graphql(query: str, variables: dict | None = None) -> dict:
    """Call GitHub GraphQL API."""
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = Request("https://api.github.com/graphql", data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    if GH_TOKEN:
        req.add_header("Authorization", f"Bearer {GH_TOKEN}")

    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except (HTTPError, URLError) as e:
        print(f"  WARN: GraphQL error: {e}", file=sys.stderr)
        return {}


def fetch_merged_prs(owner: str, repo: str, since: str) -> list[dict]:
    """Fetch recently merged PRs."""
    query = f"repo:{owner}/{repo} is:pr is:merged merged:>={since}"
    encoded_query = quote(query, safe="")
    data = gh_api(f"search/issues?q={encoded_query}&sort=updated&order=desc")
    if isinstance(data, dict):
        return data.get("items", [])
    return []


def fetch_pr_reviews(owner: str, repo: str, pr_number: int) -> list[dict]:
    """Fetch reviews for a PR."""
    return gh_api(f"repos/{owner}/{repo}/pulls/{pr_number}/reviews")


def fetch_pr_commits(owner: str, repo: str, pr_number: int) -> list[dict]:
    """Fetch commits in a PR."""
    return gh_api(f"repos/{owner}/{repo}/pulls/{pr_number}/commits")


def detect_post_approval_commits(
    owner: str, repo: str, pr: dict, reviews: list[dict], commits: list[dict]
) -> dict | None:
    """Check if commits were pushed after the last approval."""
    approvals = [
        r for r in reviews
        if r.get("state") == "APPROVED" and r.get("submitted_at")
    ]
    if not approvals:
        return None

    last_approval_time = max(a["submitted_at"] for a in approvals)
    last_approver = next(
        (a["user"]["login"] for a in approvals if a["submitted_at"] == last_approval_time),
        "unknown",
    )

    post_approval = []
    for c in commits:
        commit_date = c.get("commit", {}).get("committer", {}).get("date", "")
        if commit_date > last_approval_time:
            post_approval.append(c)

    if not post_approval:
        return None

    pr_author = pr.get("user", {}).get("login", "unknown")
    approver_logins = {a["user"]["login"] for a in approvals}

    from_third_party = [
        c for c in post_approval
        if c.get("author", {}).get("login", "") != pr_author
        and c.get("author", {}).get("login", "") not in approver_logins
    ]

    if from_third_party:
        risk = "critical"
    elif all(c.get("author", {}).get("login", "") == pr_author for c in post_approval):
        risk = "high"
    else:
        risk = "medium"

    return {
        "category": "post_approval_commit",
        "risk": risk,
        "repo": f"{owner}/{repo}",
        "pr_number": pr["number"],
        "pr_title": pr.get("title", ""),
        "pr_url": pr.get("html_url", pr.get("pull_request", {}).get("html_url", "")),
        "pr_author": pr_author,
        "last_approver": last_approver,
        "last_approval_time": last_approval_time,
        "post_approval_count": len(post_approval),
        "commits": [
            {
                "sha": c["sha"][:8],
                "author": c.get("author", {}).get("login", "unknown"),
                "message": c.get("commit", {}).get("message", "").split("\n")[0][:80],
                "date": c.get("commit", {}).get("committer", {}).get("date", ""),
            }
            for c in post_approval[:5]
        ],
    }


def detect_bot_only_approval(
    owner: str, repo: str, pr: dict, reviews: list[dict]
) -> dict | None:
    """Check if a PR was merged with only bot approvals."""
    approvals = [
        r for r in reviews if r.get("state") == "APPROVED"
    ]
    if not approvals:
        return None

    human_approvals = [
        a for a in approvals if not _is_bot(a.get("user", {}).get("login", ""))
    ]
    bot_approvals = [
        a for a in approvals if _is_bot(a.get("user", {}).get("login", ""))
    ]

    if human_approvals:
        return None

    if not bot_approvals:
        return None

    pr_author = pr.get("user", {}).get("login", "unknown")
    pr_title = pr.get("title", "")
    bot_names = list({a["user"]["login"] for a in bot_approvals})

    is_bot_pr = _is_bot(pr_author)
    is_dep_only = any(
        kw in pr_title.lower()
        for kw in ("chore(deps)", "bump ", "update dependency", "lock file")
    )

    if is_bot_pr and is_dep_only:
        risk = "low"
    elif is_bot_pr:
        risk = "medium"
    else:
        risk = "high"

    return {
        "category": "bot_only_approval",
        "risk": risk,
        "repo": f"{owner}/{repo}",
        "pr_number": pr["number"],
        "pr_title": pr_title,
        "pr_url": pr.get("html_url", pr.get("pull_request", {}).get("html_url", "")),
        "pr_author": pr_author,
        "bot_approvers": bot_names,
        "is_bot_pr": is_bot_pr,
        "is_dep_only": is_dep_only,
        "merged_at": pr.get("pull_request", {}).get("merged_at", ""),
    }


def fetch_dependency_versions(owner: str, repo: str) -> list[dict]:
    """Extract package versions from lock/dep files on default branch."""
    packages = []

    tree = gh_api(f"repos/{owner}/{repo}/git/trees/HEAD?recursive=1")
    if isinstance(tree, dict):
        for item in tree.get("tree", []):
            path = item.get("path", "")
            filename = path.split("/")[-1] if "/" in path else path
            if filename not in LOCK_FILES and filename not in DEP_FILES:
                continue
            if filename == "pyproject.toml":
                packages.extend(_parse_pyproject(owner, repo, path))
            elif filename == "package.json":
                packages.extend(_parse_package_json(owner, repo, path))

    return packages


def _parse_pyproject(owner: str, repo: str, path: str) -> list[dict]:
    """Parse dependencies from pyproject.toml (simple regex approach)."""
    import re

    try:
        content_data = gh_api(f"repos/{owner}/{repo}/contents/{path}")
        if isinstance(content_data, dict) and content_data.get("encoding") == "base64":
            import base64
            content = base64.b64decode(content_data["content"]).decode()
        else:
            return []
    except Exception:
        return []

    packages = []
    dep_pattern = re.compile(r'"([a-zA-Z0-9_-]+)\s*([><=!~]+\s*[\d.]+(?:\.\*)?)"')
    for match in dep_pattern.finditer(content):
        name = match.group(1)
        version_spec = match.group(2).strip()
        version = re.search(r"[\d.]+", version_spec)
        if version:
            packages.append({
                "name": name,
                "version": version.group(),
                "ecosystem": "PyPI",
            })

    return packages


def _parse_package_json(owner: str, repo: str, path: str) -> list[dict]:
    """Parse dependencies from package.json."""
    try:
        content_data = gh_api(f"repos/{owner}/{repo}/contents/{path}")
        if isinstance(content_data, dict) and content_data.get("encoding") == "base64":
            import base64
            content = base64.b64decode(content_data["content"]).decode()
            pkg = json.loads(content)
        else:
            return []
    except Exception:
        return []

    packages = []
    for section in ("dependencies", "devDependencies"):
        for name, version_spec in pkg.get(section, {}).items():
            version = version_spec.lstrip("^~>=<! ")
            if version and version[0].isdigit():
                packages.append({
                    "name": name,
                    "version": version,
                    "ecosystem": "npm",
                })

    return packages


def query_osv(package: str, version: str, ecosystem: str) -> list[dict]:
    """Query OSV.dev for known vulnerabilities."""
    payload = json.dumps({
        "version": version,
        "package": {"name": package, "ecosystem": ecosystem},
    }).encode()

    req = Request(OSV_API, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return data.get("vulns", [])
    except (HTTPError, URLError):
        return []


def detect_vulnerabilities(owner: str, repo: str, packages: list[dict]) -> list[dict]:
    """Scan packages against OSV.dev for known CVEs."""
    findings = []

    for pkg in packages:
        vulns = query_osv(pkg["name"], pkg["version"], pkg["ecosystem"])
        if not vulns:
            continue

        for vuln in vulns:
            vuln_id = vuln.get("id", "unknown")
            aliases = vuln.get("aliases", [])
            severity_data = vuln.get("database_specific", {}).get("severity", "")
            if not severity_data:
                severities = vuln.get("severity", [])
                if severities:
                    severity_data = severities[0].get("score", "unknown")

            summary_text = vuln.get("summary", "No description available")

            cve_ids = [a for a in aliases if a.startswith("CVE-")]
            risk = "critical" if any(
                s in str(severity_data).upper() for s in ("CRITICAL", "HIGH")
            ) else "medium"

            findings.append({
                "category": "vulnerability",
                "risk": risk,
                "repo": f"{owner}/{repo}",
                "package": pkg["name"],
                "version": pkg["version"],
                "ecosystem": pkg["ecosystem"],
                "vuln_id": vuln_id,
                "cve_ids": cve_ids,
                "summary": summary_text[:200],
                "aliases": aliases,
            })

    return findings


def process_repo(owner: str, repo: str, since: str, scan_vulns: bool = True) -> dict:
    """Process a single repo for all three finding categories."""
    print(f"  Scanning {owner}/{repo}...", file=sys.stderr)

    post_approval_findings = []
    bot_only_findings = []
    vuln_findings = []

    # Fetch merged PRs
    merged_prs = fetch_merged_prs(owner, repo, since)
    print(f"    {len(merged_prs)} merged PRs since {since}", file=sys.stderr)

    for pr in merged_prs:
        pr_number = pr["number"]
        time.sleep(0.5)  # rate limit

        reviews = fetch_pr_reviews(owner, repo, pr_number)
        commits = fetch_pr_commits(owner, repo, pr_number)

        # Post-approval check
        finding = detect_post_approval_commits(owner, repo, pr, reviews, commits)
        if finding:
            post_approval_findings.append(finding)

        # Bot-only approval check
        finding = detect_bot_only_approval(owner, repo, pr, reviews)
        if finding:
            bot_only_findings.append(finding)

    # Vulnerability scan
    if scan_vulns:
        print(f"    Scanning dependencies for vulnerabilities...", file=sys.stderr)
        packages = fetch_dependency_versions(owner, repo)
        if packages:
            vuln_findings = detect_vulnerabilities(owner, repo, packages[:50])
            print(f"    {len(packages)} packages, {len(vuln_findings)} vulnerabilities found", file=sys.stderr)

    return {
        "owner": owner,
        "repo": repo,
        "post_approval": post_approval_findings,
        "bot_only": bot_only_findings,
        "vulnerabilities": vuln_findings,
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch supply-chain audit data")
    parser.add_argument("--repos-file", required=True, help="Path to repos.json config")
    parser.add_argument("--days", type=int, default=7,
                        help="Look back N days for merged PRs (default: 7)")
    parser.add_argument("--skip-vulns", action="store_true",
                        help="Skip vulnerability scanning (faster)")
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    args = parser.parse_args()

    with open(args.repos_file) as f:
        config = json.load(f)

    repos = config.get("repos", [])
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")

    print(f"Supply-chain audit: {len(repos)} repos, since {since}", file=sys.stderr)

    results = []
    total_post_approval = 0
    total_bot_only = 0
    total_vulns = 0

    for repo_conf in repos:
        owner = repo_conf["owner"]
        repo = repo_conf["repo"]
        result = process_repo(owner, repo, since, scan_vulns=not args.skip_vulns)
        results.append(result)
        total_post_approval += len(result["post_approval"])
        total_bot_only += len(result["bot_only"])
        total_vulns += len(result["vulnerabilities"])

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since": since,
        "days": args.days,
        "aggregate": {
            "total_post_approval": total_post_approval,
            "total_bot_only": total_bot_only,
            "total_vulnerabilities": total_vulns,
            "repos_scanned": len(repos),
            "critical_findings": sum(
                1 for r in results
                for f in r["post_approval"] + r["bot_only"] + r["vulnerabilities"]
                if f.get("risk") == "critical"
            ),
        },
        "results": results,
    }

    out_json = json.dumps(output, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(out_json)
        print(f"Output written to {args.output}", file=sys.stderr)
    else:
        print(out_json)

    print(
        f"\nSummary: {total_post_approval} post-approval commits, "
        f"{total_bot_only} bot-only approvals, {total_vulns} vulnerabilities",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
