#!/usr/bin/env python3
"""
Correlate CI failures across Ansible Devtools repositories.

Analyzes CI failure data to detect common root causes:
- Temporal clusters: multiple repos failing within the same time window
- Shared job failures: same job name failing across repos
- Dependency links: recent dependency PR merged before failures began
- Isolated failures: single repo issues with no correlation

Usage:
    python3 scripts/correlate_failures.py --ci reports/ci-status.json
    python3 scripts/correlate_failures.py --ci reports/ci-status.json --renovate reports/renovate-prs.json
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


TEMPORAL_WINDOW_HOURS = 2
MIN_CLUSTER_SIZE = 2

PACKAGE_PATTERN = re.compile(
    r"(?:update|bump|upgrade)\s+(.+?)\s+(?:from|to)\s+v?[\d.]",
    re.IGNORECASE,
)


def load_json_safe(path):
    if not path:
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"WARN: Could not load {path}: {e}", file=sys.stderr)
        return None


def parse_timestamp(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def extract_package_name(title):
    match = PACKAGE_PATTERN.search(title)
    if match:
        return match.group(1).strip()
    parts = title.lower().split()
    for i, word in enumerate(parts):
        if word in ("update", "bump", "upgrade") and i + 1 < len(parts):
            return parts[i + 1].strip(":`'\"")
    return None


def collect_failures(ci_data):
    """Extract all failing workflows from CI data."""
    results = ci_data.get("results", [ci_data])
    failures = []

    for repo in results:
        slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
        if repo.get("error"):
            continue
        for wf in repo.get("workflows", []):
            if wf.get("conclusion") != "failure":
                continue
            failures.append({
                "repo": slug,
                "owner": repo.get("owner", ""),
                "repo_name": repo.get("repo", ""),
                "workflow": wf.get("name", ""),
                "run_id": wf.get("run_id", 0),
                "url": wf.get("url", ""),
                "updated_at": wf.get("updated_at", ""),
                "age_hours": wf.get("age_hours", 0),
                "head_sha": wf.get("head_sha", ""),
                "is_flaky": wf.get("is_flaky", False),
                "failing_jobs": [j.get("name", "") for j in wf.get("failing_jobs", [])],
            })

    return failures


def collect_recent_dep_prs(renovate_data, hours=48):
    """Extract recently created dependency PRs."""
    if not renovate_data:
        return []

    results = renovate_data.get("results", [renovate_data])
    recent = []
    now = datetime.now(timezone.utc)

    for repo in results:
        slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
        if repo.get("error"):
            continue
        for pr in repo.get("prs", []):
            created = parse_timestamp(pr.get("created_at"))
            if not created:
                continue
            if (now - created).total_seconds() / 3600 > hours:
                continue
            package = extract_package_name(pr.get("title", ""))
            recent.append({
                "repo": slug,
                "number": pr.get("number", 0),
                "title": pr.get("title", ""),
                "url": pr.get("url", ""),
                "created_at": pr.get("created_at", ""),
                "age_days": pr.get("age_days", 0),
                "update_type": pr.get("update_type", "minor"),
                "check_state": pr.get("check_state", "unknown"),
                "package": package,
            })

    return recent


def find_temporal_clusters(failures):
    """Group failures that occurred within the same time window."""
    timed = []
    for f in failures:
        ts = parse_timestamp(f["updated_at"])
        if ts:
            timed.append((ts, f))

    if len(timed) < MIN_CLUSTER_SIZE:
        return []

    timed.sort(key=lambda x: x[0])
    clusters = []
    used = set()

    for i, (ts_i, f_i) in enumerate(timed):
        if i in used:
            continue
        group = [f_i]
        group_repos = {f_i["repo"]}
        for j in range(i + 1, len(timed)):
            if j in used:
                continue
            ts_j, f_j = timed[j]
            if (ts_j - ts_i).total_seconds() / 3600 <= TEMPORAL_WINDOW_HOURS:
                if f_j["repo"] not in group_repos:
                    group.append(f_j)
                    group_repos.add(f_j["repo"])
                    used.add(j)

        if len(group_repos) >= MIN_CLUSTER_SIZE:
            used.add(i)
            window_start = ts_i.astimezone(IST).strftime("%H:%M IST")
            window_end = (ts_i + timedelta(hours=TEMPORAL_WINDOW_HOURS)).astimezone(IST).strftime("%H:%M IST")
            clusters.append({
                "type": "temporal",
                "description": f"{len(group_repos)} repos failed between {window_start} and {window_end}",
                "likely_cause": "Infrastructure or runner outage — multiple repos failed in the same time window",
                "repos": sorted(group_repos),
                "workflows": [
                    {"repo": f["repo"], "workflow": f["workflow"], "url": f["url"]}
                    for f in group
                ],
                "window_hours": TEMPORAL_WINDOW_HOURS,
            })

    return clusters


def find_shared_job_clusters(failures):
    """Group failures where the same job name fails across repos."""
    job_to_repos = defaultdict(list)

    for f in failures:
        for job in f["failing_jobs"]:
            job_normalized = job.strip().lower()
            job_to_repos[job_normalized].append(f)

    clusters = []
    for job_name, group in job_to_repos.items():
        repos = set(f["repo"] for f in group)
        if len(repos) < MIN_CLUSTER_SIZE:
            continue
        clusters.append({
            "type": "shared_job",
            "description": f"Job '{job_name}' failing in {len(repos)} repos",
            "likely_cause": f"Shared tooling or config issue — the '{job_name}' job is failing across multiple repos",
            "job_name": job_name,
            "repos": sorted(repos),
            "workflows": [
                {"repo": f["repo"], "workflow": f["workflow"], "url": f["url"]}
                for f in group
            ],
        })

    return clusters


def find_dependency_links(failures, dep_prs):
    """Link CI failures to recent dependency PRs."""
    if not dep_prs:
        return []

    failing_with_test_jobs = []
    for f in failures:
        test_jobs = [j for j in f["failing_jobs"] if "test" in j.lower() or "check" in j.lower()]
        if test_jobs:
            failing_with_test_jobs.append(f)

    clusters = []
    for pr in dep_prs:
        if pr["check_state"] == "failure":
            linked_repos = set()
            linked_workflows = []

            for f in failing_with_test_jobs:
                if f["repo"] != pr["repo"]:
                    linked_repos.add(f["repo"])
                    linked_workflows.append({
                        "repo": f["repo"],
                        "workflow": f["workflow"],
                        "url": f["url"],
                    })

            if linked_repos:
                pkg = pr.get("package") or pr.get("title", "")[:40]
                clusters.append({
                    "type": "dependency",
                    "description": f"Dependency update '{pkg}' in {pr['repo']} has failing checks — {len(linked_repos)} other repos also failing tests",
                    "likely_cause": f"Breaking dependency update: {pkg}",
                    "dependency_pr": {
                        "repo": pr["repo"],
                        "number": pr["number"],
                        "title": pr["title"],
                        "url": pr["url"],
                        "package": pr.get("package"),
                        "update_type": pr["update_type"],
                    },
                    "repos": sorted(linked_repos),
                    "workflows": linked_workflows,
                })

    return clusters


def find_isolated(failures, clustered_repos):
    """Failures not part of any cluster."""
    isolated = []
    for f in failures:
        if f["repo"] not in clustered_repos:
            isolated.append({
                "repo": f["repo"],
                "workflow": f["workflow"],
                "url": f["url"],
                "failing_jobs": f["failing_jobs"],
                "is_flaky": f["is_flaky"],
                "age_hours": f["age_hours"],
            })
    return isolated


def correlate(ci_data, renovate_data):
    """Run all correlation analyses and return results."""
    failures = collect_failures(ci_data)
    dep_prs = collect_recent_dep_prs(renovate_data)

    if not failures:
        return {
            "clusters": [],
            "isolated": [],
            "summary": {
                "total_failures": 0,
                "total_clusters": 0,
                "clustered_repos": 0,
                "isolated_repos": 0,
                "has_correlations": False,
            },
        }

    temporal = find_temporal_clusters(failures)
    shared_jobs = find_shared_job_clusters(failures)
    dep_links = find_dependency_links(failures, dep_prs)

    all_clusters = temporal + shared_jobs + dep_links
    clustered_repos = set()
    for c in all_clusters:
        clustered_repos.update(c["repos"])

    isolated = find_isolated(failures, clustered_repos)
    isolated_repos = set(f["repo"] for f in isolated)

    return {
        "clusters": all_clusters,
        "isolated": isolated,
        "summary": {
            "total_failures": len(failures),
            "total_clusters": len(all_clusters),
            "clustered_repos": len(clustered_repos),
            "isolated_repos": len(isolated_repos),
            "has_correlations": len(all_clusters) > 0,
            "by_type": {
                "temporal": len(temporal),
                "shared_job": len(shared_jobs),
                "dependency": len(dep_links),
            },
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Correlate CI failures across repos")
    parser.add_argument("--ci", required=True, help="CI status JSON file")
    parser.add_argument("--renovate", help="Renovate PR JSON file (optional)")
    parser.add_argument("--output", "-o", help="Write output to file (default: stdout)")
    args = parser.parse_args()

    ci_data = load_json_safe(args.ci)
    if not ci_data:
        print("ERROR: Could not load CI data", file=sys.stderr)
        sys.exit(1)

    renovate_data = load_json_safe(args.renovate)

    result = correlate(ci_data, renovate_data)
    result["fetched_at"] = datetime.now(timezone.utc).isoformat()

    output = json.dumps(result, indent=2)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
            f.write("\n")
        print(f"Correlation report written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
