"""Generate markdown reports from Guardian JSON data.

Reads JSON output from fetch scripts and produces formatted markdown dashboards.

Usage:
    python3 scripts/generate_report.py prs reports/open-prs.json
    python3 scripts/generate_report.py ci reports/ci-status.json
    python3 scripts/generate_report.py renovate reports/renovate-prs.json
    python3 scripts/generate_report.py sonar reports/sonar-gates.json
    python3 scripts/generate_report.py guardian --prs FILE --ci FILE --renovate FILE --sonar FILE
    python3 scripts/generate_report.py handoff --prs FILE --ci FILE --renovate FILE --sonar FILE
    python3 scripts/generate_report.py prs reports/open-prs.json --output reports/pr-dashboard.md
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def load_json(path):
    """Load JSON from a file path."""
    with open(path) as f:
        return json.load(f)


def load_json_safe(path):
    """Load JSON, returning None if file doesn't exist or is invalid."""
    if not path:
        return None
    try:
        return load_json(path)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"WARN: Could not load {path}: {e}", file=sys.stderr)
        return None


def truncate(text, length=60):
    """Truncate text with ellipsis."""
    if len(text) > length:
        return text[: length - 3] + "..."
    return text


def health_icon(status) -> str:
    """Return a text indicator for health status."""
    if status in ("OK", "success", "passing", True):
        return "PASS"
    if status in ("ERROR", "failure", "failing", False):
        return "FAIL"
    if status in ("WARN", "warning", "flaky"):
        return "WARN"
    if status == "NONE":
        return "N/A"
    return "?"


# ---------------------------------------------------------------------------
# PR Report (existing)
# ---------------------------------------------------------------------------


def generate_pr_report(data):
    """Generate the Open PR dashboard."""
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    lines = []

    lines.append("# Guardian: Open PR Dashboard")
    lines.append("")
    lines.append(f"**Generated:** {now_str}")
    lines.append("")

    if data.get("mode") == "batch":
        agg = data["aggregate"]
        lines.append("## Summary")
        lines.append("")
        lines.append("| Metric | Count |")
        lines.append("|---|---|")
        lines.append(f"| Total open PRs | **{agg['total_prs']}** across {data['total_repos']} repos |")
        lines.append(f"| Ready to merge | {agg['ready_to_merge']} |")
        lines.append(f"| Needs review | {agg['needs_review']} |")
        lines.append(f"| Changes requested | {agg['changes_requested']} |")
        lines.append(f"| Draft | {agg['draft']} |")
        lines.append(f"| Stale (14+ days inactive) | {agg['stale']} |")
        lines.append(f"| Blocked | {agg['blocked']} |")
        lines.append(f"| Bot PRs (excluded) | {agg['total_bot_prs']} |")
        if agg["repos_with_errors"] > 0:
            lines.append(f"| Repos with errors | {agg['repos_with_errors']} |")
        lines.append("")
        results = data["results"]
    else:
        results = [data]

    categories = [
        ("ready_to_merge", "Ready to Merge"),
        ("changes_requested", "Changes Requested"),
        ("needs_review", "Needs Review"),
        ("blocked", "Blocked"),
        ("stale", "Stale"),
        ("draft", "Draft"),
    ]

    prs_by_cat = {k: [] for k, _ in categories}
    for repo in results:
        slug = f"{repo['owner']}/{repo['repo']}"
        if repo.get("error"):
            continue
        for pr in repo.get("prs", []):
            pr["_repo"] = slug
            cat = pr.get("category", "needs_review")
            if cat in prs_by_cat:
                prs_by_cat[cat].append(pr)

    for cat_key, cat_title in categories:
        prs = prs_by_cat[cat_key]
        if not prs:
            continue

        lines.append(f"## {cat_title} ({len(prs)})")
        lines.append("")
        lines.append("| Repo | PR | Title | Author | Age |")
        lines.append("|---|---|---|---|---|")

        prs.sort(key=lambda p: p.get("age_days", 0), reverse=True)
        for pr in prs:
            lines.append(
                f"| {pr['_repo']} "
                f"| [#{pr['number']}]({pr['url']}) "
                f"| {truncate(pr['title'])} "
                f"| {pr['author']} "
                f"| {pr['age_days']}d |",
            )
        lines.append("")

    lines.append("## Per-Repo Overview")
    lines.append("")
    lines.append("| Repository | Total | Ready | Review | Changes | Draft | Stale | Blocked | Bots |")
    lines.append("|---|---|---|---|---|---|---|---|---|")

    for repo in results:
        slug = f"{repo['owner']}/{repo['repo']}"
        s = repo.get("summary", {})
        bots = repo.get("bot_summary", {}).get("total", 0)
        if repo.get("error"):
            lines.append(f"| {slug} | ERROR | - | - | - | - | - | - | - |")
        else:
            lines.append(
                f"| {slug} "
                f"| {s.get('total', 0)} "
                f"| {s.get('ready_to_merge', 0)} "
                f"| {s.get('needs_review', 0)} "
                f"| {s.get('changes_requested', 0)} "
                f"| {s.get('draft', 0)} "
                f"| {s.get('stale', 0)} "
                f"| {s.get('blocked', 0)} "
                f"| {bots} |",
            )
    lines.append("")

    action_items = []
    for pr in prs_by_cat.get("ready_to_merge", []):
        action_items.append(
            f"- **MERGE** [{pr['_repo']}#{pr['number']}]({pr['url']}) - {truncate(pr['title'], 80)}",
        )
    for pr in prs_by_cat.get("stale", []):
        action_items.append(
            f"- **STALE** [{pr['_repo']}#{pr['number']}]({pr['url']}) - {pr['age_days']} days inactive",
        )
    for pr in prs_by_cat.get("blocked", []):
        action_items.append(
            f"- **BLOCKED** [{pr['_repo']}#{pr['number']}]({pr['url']}) - check conflicts/CI",
        )

    if action_items:
        lines.append("## Action Items")
        lines.append("")
        lines.extend(action_items)
        lines.append("")

    lines.append("---")
    lines.append("*Generated by td-guardian*")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CI Status Report
# ---------------------------------------------------------------------------


def generate_ci_report(data):
    """Generate the CI/Pipeline Health dashboard."""
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    lines = []

    lines.append("# Guardian: CI/Pipeline Health Dashboard")
    lines.append("")
    lines.append(f"**Generated:** {now_str}")
    lines.append("")

    if data.get("mode") == "batch":
        agg = data["aggregate"]
        lines.append("## Summary")
        lines.append("")
        lines.append("| Metric | Count |")
        lines.append("|---|---|")
        lines.append(f"| Total workflows | **{agg['total_workflows']}** across {data['total_repos']} repos |")
        lines.append(f"| Passing | {agg['passing']} |")
        lines.append(f"| Failing | {agg['failing']} |")
        lines.append(f"| Flaky | {agg['flaky']} |")
        lines.append(f"| Repos all green | {agg['repos_all_green']} / {data['total_repos']} |")
        if agg["repos_with_errors"] > 0:
            lines.append(f"| Repos with errors | {agg['repos_with_errors']} |")
        lines.append("")
        results = data["results"]
    else:
        results = [data]

    failing_workflows = []
    flaky_workflows = []
    for repo in results:
        slug = f"{repo['owner']}/{repo['repo']}"
        if repo.get("error"):
            continue
        for wf in repo.get("workflows", []):
            wf["_repo"] = slug
            if wf.get("conclusion") == "failure" and not wf.get("is_flaky"):
                failing_workflows.append(wf)
            if wf.get("is_flaky"):
                flaky_workflows.append(wf)

    if failing_workflows:
        lines.append(f"## Failing Workflows ({len(failing_workflows)})")
        lines.append("")
        lines.append("| Repo | Workflow | Age | Failing Jobs |")
        lines.append("|---|---|---|---|")
        for wf in failing_workflows:
            jobs = ", ".join(j["name"] for j in wf.get("failing_jobs", []))
            if not jobs:
                jobs = "-"
            lines.append(
                f"| {wf['_repo']} "
                f"| [{wf['name']}]({wf.get('url', '')}) "
                f"| {wf.get('age_hours', '?')}h "
                f"| {truncate(jobs, 50)} |",
            )
        lines.append("")

    if flaky_workflows:
        lines.append(f"## Flaky Workflows ({len(flaky_workflows)})")
        lines.append("")
        lines.append("| Repo | Workflow | Last Result |")
        lines.append("|---|---|---|")
        for wf in flaky_workflows:
            lines.append(
                f"| {wf['_repo']} | [{wf['name']}]({wf.get('url', '')}) | {wf.get('conclusion', '?')} |",
            )
        lines.append("")

    lines.append("## Per-Repo Status")
    lines.append("")
    lines.append("| Repository | Total | Passing | Failing | Flaky | Status |")
    lines.append("|---|---|---|---|---|---|")

    for repo in results:
        slug = f"{repo['owner']}/{repo['repo']}"
        s = repo.get("summary", {})
        if repo.get("error"):
            lines.append(f"| {slug} | ERROR | - | - | - | ERROR |")
        else:
            status = "PASS"
            if s.get("failing", 0) > 0:
                status = "FAIL"
            elif s.get("flaky", 0) > 0:
                status = "WARN"
            lines.append(
                f"| {slug} "
                f"| {s.get('total', 0)} "
                f"| {s.get('passing', 0)} "
                f"| {s.get('failing', 0)} "
                f"| {s.get('flaky', 0)} "
                f"| {status} |",
            )
    lines.append("")

    action_items = []
    for wf in failing_workflows:
        action_items.append(
            f"- **FIX CI** [{wf['_repo']}]({wf.get('url', '')}) - {wf['name']} failing",
        )
    for wf in flaky_workflows:
        action_items.append(
            f"- **INVESTIGATE** [{wf['_repo']}]({wf.get('url', '')}) - {wf['name']} flaky",
        )

    if action_items:
        lines.append("## Action Items")
        lines.append("")
        lines.extend(action_items)
        lines.append("")

    lines.append("---")
    lines.append("*Generated by td-guardian*")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Renovate / Dependency Report
# ---------------------------------------------------------------------------


def generate_renovate_report(data):
    """Generate the Dependency Update dashboard."""
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    lines = []

    lines.append("# Guardian: Dependency Update Dashboard")
    lines.append("")
    lines.append(f"**Generated:** {now_str}")
    lines.append("")

    if data.get("mode") == "batch":
        agg = data["aggregate"]
        lines.append("## Summary")
        lines.append("")
        lines.append("| Metric | Count |")
        lines.append("|---|---|")
        lines.append(f"| Total dependency PRs | **{agg['total_prs']}** across {data['total_repos']} repos |")
        lines.append(f"| Overdue | {agg['overdue']} |")
        lines.append(f"| Security updates | {agg['security']} |")
        lines.append(f"| Major bumps | {agg['major']} |")
        lines.append(f"| Minor/patch | {agg['minor']} |")
        lines.append(f"| Oldest PR | {agg['oldest_days']} days |")
        if agg["repos_with_errors"] > 0:
            lines.append(f"| Repos with errors | {agg['repos_with_errors']} |")
        lines.append("")
        results = data["results"]
    else:
        results = [data]

    priority_order = {"security": 0, "major": 1, "minor": 2}
    overdue_prs = []
    all_dep_prs = []
    for repo in results:
        slug = f"{repo['owner']}/{repo['repo']}"
        if repo.get("error"):
            continue
        for pr in repo.get("prs", []):
            pr["_repo"] = slug
            all_dep_prs.append(pr)
            if pr.get("is_overdue"):
                overdue_prs.append(pr)

    if overdue_prs:
        overdue_prs.sort(key=lambda p: (priority_order.get(p.get("update_type", "minor"), 2), -p.get("age_days", 0)))
        lines.append(f"## Overdue Updates ({len(overdue_prs)})")
        lines.append("")
        lines.append("| Repo | PR | Title | Type | Age | Threshold | Checks |")
        lines.append("|---|---|---|---|---|---|---|")
        for pr in overdue_prs:
            lines.append(
                f"| {pr['_repo']} "
                f"| [#{pr['number']}]({pr.get('url', '')}) "
                f"| {truncate(pr['title'], 45)} "
                f"| {pr.get('update_type', '?')} "
                f"| {pr.get('age_days', '?')}d "
                f"| {pr.get('threshold_days', '?')}d "
                f"| {pr.get('check_state', '?')} |",
            )
        lines.append("")

    if all_dep_prs:
        not_overdue = [p for p in all_dep_prs if not p.get("is_overdue")]
        if not_overdue:
            lines.append(f"## Pending Updates ({len(not_overdue)})")
            lines.append("")
            lines.append("| Repo | PR | Title | Type | Age | Checks |")
            lines.append("|---|---|---|---|---|---|")
            not_overdue.sort(key=lambda p: p.get("age_days", 0), reverse=True)
            for pr in not_overdue:
                lines.append(
                    f"| {pr['_repo']} "
                    f"| [#{pr['number']}]({pr.get('url', '')}) "
                    f"| {truncate(pr['title'], 45)} "
                    f"| {pr.get('update_type', '?')} "
                    f"| {pr.get('age_days', '?')}d "
                    f"| {pr.get('check_state', '?')} |",
                )
            lines.append("")

    lines.append("## Per-Repo Overview")
    lines.append("")
    lines.append("| Repository | Total | Overdue | Security | Major | Minor | Oldest |")
    lines.append("|---|---|---|---|---|---|---|")
    for repo in results:
        slug = f"{repo['owner']}/{repo['repo']}"
        s = repo.get("summary", {})
        if repo.get("error"):
            lines.append(f"| {slug} | ERROR | - | - | - | - | - |")
        else:
            lines.append(
                f"| {slug} "
                f"| {s.get('total', 0)} "
                f"| {s.get('overdue', 0)} "
                f"| {s.get('security', 0)} "
                f"| {s.get('major', 0)} "
                f"| {s.get('minor', 0)} "
                f"| {s.get('oldest_days', 0)}d |",
            )
    lines.append("")

    action_items = []
    for pr in overdue_prs:
        if pr.get("update_type") == "security":
            action_items.append(
                f"- **SECURITY** [{pr['_repo']}#{pr['number']}]({pr.get('url', '')}) - "
                f"{truncate(pr['title'], 60)} ({pr.get('age_days', '?')}d, threshold {pr.get('threshold_days', '?')}d)",
            )
    for pr in overdue_prs:
        if pr.get("update_type") != "security":
            action_items.append(
                f"- **OVERDUE** [{pr['_repo']}#{pr['number']}]({pr.get('url', '')}) - "
                f"{pr.get('update_type', '?')} update, {pr.get('age_days', '?')}d old",
            )

    if action_items:
        lines.append("## Action Items")
        lines.append("")
        lines.extend(action_items)
        lines.append("")

    lines.append("---")
    lines.append("*Generated by td-guardian*")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SonarCloud Quality Report
# ---------------------------------------------------------------------------


def generate_sonar_report(data):
    """Generate the SonarCloud Quality Gate dashboard."""
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    lines = []

    lines.append("# Guardian: SonarCloud Quality Dashboard")
    lines.append("")
    lines.append(f"**Generated:** {now_str}")
    lines.append("")

    if data.get("mode") == "batch":
        agg = data["aggregate"]
        lines.append("## Summary")
        lines.append("")
        lines.append("| Metric | Count |")
        lines.append("|---|---|")
        lines.append(f"| Total projects | **{data['total_projects']}** |")
        lines.append(f"| Quality gate passing | {agg['gate_ok']} |")
        lines.append(f"| Quality gate failing | {agg['gate_error']} |")
        if agg.get("gate_warn", 0) > 0:
            lines.append(f"| Quality gate warning | {agg['gate_warn']} |")
        if agg.get("gate_unknown", 0) > 0:
            lines.append(f"| Unknown/not found | {agg['gate_unknown']} |")
        lines.append(f"| Total bugs | {agg['total_bugs']} |")
        lines.append(f"| Total vulnerabilities | {agg['total_vulnerabilities']} |")
        lines.append(f"| Total code smells | {agg['total_code_smells']} |")
        lines.append(f"| Security hotspots | {agg['total_security_hotspots']} |")
        if agg["projects_with_errors"] > 0:
            lines.append(f"| Projects with errors | {agg['projects_with_errors']} |")
        lines.append("")
        results = data["results"]
    else:
        results = [data]

    failing = [r for r in results if r.get("gate_status") == "ERROR"]
    if failing:
        lines.append(f"## Failing Quality Gates ({len(failing)})")
        lines.append("")
        for proj in failing:
            slug = f"{proj['owner']}/{proj['repo']}"
            lines.append(f"### {slug}")
            lines.append("")
            m = proj.get("metrics", {})
            lines.append(f"- Coverage: {m.get('coverage', 'N/A')}%")
            lines.append(f"- Bugs: {m.get('bugs', 'N/A')}")
            lines.append(f"- Vulnerabilities: {m.get('vulnerabilities', 'N/A')}")
            lines.append(f"- Code Smells: {m.get('code_smells', 'N/A')}")
            lines.append(f"- Security Hotspots: {m.get('security_hotspots', 'N/A')}")
            lines.append("")
            fail_conds = proj.get("failing_conditions", [])
            if fail_conds:
                lines.append("**Failing conditions:**")
                lines.append("")
                for c in fail_conds:
                    lines.append(f"- {c['metric']}: {c['value']} (threshold: {c['comparator']} {c['threshold']})")
                lines.append("")

    lines.append("## All Projects")
    lines.append("")
    lines.append("| Repository | Gate | Coverage | Bugs | Vulns | Smells | Hotspots | Reliability | Security |")
    lines.append("|---|---|---|---|---|---|---|---|---|")

    for proj in results:
        slug = f"{proj['owner']}/{proj['repo']}"
        m = proj.get("metrics", {})
        if proj.get("error"):
            lines.append(f"| {slug} | ERROR | - | - | - | - | - | - | - |")
        else:
            gate = health_icon(proj.get("gate_status", "UNKNOWN"))
            lines.append(
                f"| {slug} "
                f"| {gate} "
                f"| {m.get('coverage', 'N/A')}% "
                f"| {m.get('bugs', 'N/A')} "
                f"| {m.get('vulnerabilities', 'N/A')} "
                f"| {m.get('code_smells', 'N/A')} "
                f"| {m.get('security_hotspots', 'N/A')} "
                f"| {m.get('reliability_rating', 'N/A')} "
                f"| {m.get('security_rating', 'N/A')} |",
            )
    lines.append("")

    action_items = []
    for proj in failing:
        slug = f"{proj['owner']}/{proj['repo']}"
        fail_conds = proj.get("failing_conditions", [])
        reasons = ", ".join(c["metric"] for c in fail_conds[:3])
        action_items.append(f"- **GATE FAILING** {slug} - {reasons}")

    vuln_projects = [r for r in results if not r.get("error") and r.get("metrics", {}).get("vulnerabilities", 0) > 0]
    for proj in vuln_projects:
        slug = f"{proj['owner']}/{proj['repo']}"
        v = proj["metrics"]["vulnerabilities"]
        action_items.append(f"- **VULNERABILITIES** {slug} - {v} open")

    if action_items:
        lines.append("## Action Items")
        lines.append("")
        lines.extend(action_items)
        lines.append("")

    lines.append("---")
    lines.append("*Generated by td-guardian*")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Codecov Coverage Report
# ---------------------------------------------------------------------------


def generate_codecov_report(data):
    """Generate the Code Coverage dashboard from Codecov data."""
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    lines = []

    lines.append("# Guardian: Code Coverage Dashboard (Codecov)")
    lines.append("")
    lines.append(f"**Generated:** {now_str}")
    lines.append("")

    if data.get("mode") == "batch":
        agg = data["aggregate"]
        lines.append("## Summary")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        lines.append(f"| Repos with coverage | **{agg['repos_with_coverage']}** / {data['total_repos']} |")
        lines.append(f"| Average coverage | {agg['average_coverage']}% |")
        lines.append(f"| Min coverage | {agg['min_coverage']}% |")
        lines.append(f"| Max coverage | {agg['max_coverage']}% |")
        lines.append(f"| Repos above 80% | {agg['repos_above_80']} |")
        lines.append(f"| Repos below 50% | {agg['repos_below_50']} |")
        if agg["repos_with_errors"] > 0:
            lines.append(f"| Repos with errors | {agg['repos_with_errors']} |")
        lines.append("")
        results = data["results"]
    else:
        results = [data]

    low_coverage = [r for r in results if not r.get("error") and r.get("coverage") is not None and r["coverage"] < 50]
    if low_coverage:
        low_coverage.sort(key=lambda r: r.get("coverage", 0))
        lines.append(f"## Low Coverage ({len(low_coverage)} repos below 50%)")
        lines.append("")
        for r in low_coverage:
            slug = f"{r['owner']}/{r['repo']}"
            lines.append(f"- **{slug}** — {r['coverage']}%")
        lines.append("")

    lines.append("## All Repositories")
    lines.append("")
    lines.append("| Repository | Coverage | Lines | Hits | Misses |")
    lines.append("|---|---|---|---|---|")

    sorted_results = sorted(results, key=lambda r: r.get("coverage") or 0)
    for repo in sorted_results:
        slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
        if repo.get("error"):
            lines.append(f"| {slug} | ERROR | - | - | - |")
        else:
            cov = repo.get("coverage")
            cov_str = f"{cov}%" if cov is not None else "N/A"
            lines.append(
                f"| {slug} "
                f"| {cov_str} "
                f"| {repo.get('lines', 0):,} "
                f"| {repo.get('hits', 0):,} "
                f"| {repo.get('misses', 0):,} |",
            )
    lines.append("")

    action_items = []
    for r in low_coverage:
        slug = f"{r['owner']}/{r['repo']}"
        action_items.append(f"- **LOW COVERAGE** {slug} — {r['coverage']}% (target: 50%+)")

    if action_items:
        lines.append("## Action Items")
        lines.append("")
        lines.extend(action_items)
        lines.append("")

    lines.append("---")
    lines.append("*Generated by td-guardian*")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Consolidated Guardian Dashboard
# ---------------------------------------------------------------------------


def format_changes_section(changes_data):
    """Markdown section for since-last-check deltas."""
    lines = []
    lines.append("## Since Last Check")
    lines.append("")

    if not changes_data:
        lines.append("_No changes data available._")
        lines.append("")
        return lines

    if not changes_data.get("has_baseline", True):
        lines.append("No previous snapshot yet — delta starts next run.")
        lines.append("")
        return lines

    compared = changes_data.get("compared_to") or "previous run"
    summary = changes_data.get("summary", {})
    total = sum(summary.values()) if summary else 0
    lines.append(f"**Compared to:** {compared}")
    lines.append("")

    if total == 0:
        lines.append("No material changes since the previous snapshot.")
        lines.append("")
        return lines

    def _bullets(entries, label, fmt) -> None:
        if not entries:
            return
        lines.append(f"### {label} ({len(entries)})")
        lines.append("")
        for e in entries[:15]:
            lines.append(f"- {fmt(e)}")
        lines.append("")

    def _wf(e) -> str:
        slug = e.get("repo", "?")
        name = e.get("workflow", "?")
        url = e.get("url", "")
        if url:
            return f"**[{slug}]({url})** — {name}"
        return f"**{slug}** — {name}"

    def _pr(e) -> str:
        slug = e.get("repo", "?")
        num = e.get("number", "?")
        title = truncate(e.get("title", ""), 50)
        url = e.get("url", "")
        label = f"{slug}#{num}"
        if url:
            return f"**[{label}]({url})** — {title}"
        return f"**{label}** — {title}"

    ci = changes_data.get("ci", {})
    prs = changes_data.get("prs", {})
    ren = changes_data.get("renovate", {})

    _bullets(ci.get("new_failures", []), "New CI failures", _wf)
    _bullets(ci.get("resolved_failures", []), "Resolved CI failures", _wf)
    _bullets(ci.get("new_flaky", []), "Newly flaky workflows", _wf)
    _bullets(prs.get("became_stale", []), "PRs that became stale", _pr)
    _bullets(prs.get("became_ready", []), "PRs that became ready", _pr)
    _bullets(prs.get("newly_opened", []), "Newly opened PRs", _pr)
    _bullets(prs.get("closed_or_merged", []), "Closed or merged PRs", _pr)
    _bullets(ren.get("newly_overdue", []), "Newly overdue dependencies", _pr)
    _bullets(ren.get("no_longer_overdue", []), "Dependencies no longer overdue", _pr)

    return lines


def generate_guardian_report(prs_data, ci_data, renovate_data, sonar_data, codecov_data=None, changes_data=None):
    """Generate a consolidated Guardian shift dashboard."""
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    lines = []

    lines.append("# Guardian: Daily Shift Dashboard")
    lines.append("")
    lines.append(f"**Generated:** {now_str}")
    lines.append("")

    lines.extend(format_changes_section(changes_data))

    lines.append("## Health Overview")
    lines.append("")
    lines.append("| Area | Status | Key Metric |")
    lines.append("|---|---|---|")

    if ci_data:
        agg = ci_data.get("aggregate", ci_data.get("summary", {}))
        failing = agg.get("failing", 0)
        flaky = agg.get("flaky", 0)
        ci_status = "PASS" if failing == 0 and flaky == 0 else ("WARN" if failing == 0 else "FAIL")
        lines.append(f"| CI/Pipeline | {ci_status} | {failing} failing, {flaky} flaky |")
    else:
        lines.append("| CI/Pipeline | N/A | No data |")

    if prs_data:
        agg = prs_data.get("aggregate", prs_data.get("summary", {}))
        ready = agg.get("ready_to_merge", 0)
        stale = agg.get("stale", 0)
        blocked = agg.get("blocked", 0)
        pr_status = "PASS" if blocked == 0 and stale == 0 else ("WARN" if blocked == 0 else "FAIL")
        lines.append(f"| Open PRs | {pr_status} | {ready} ready, {stale} stale, {blocked} blocked |")
    else:
        lines.append("| Open PRs | N/A | No data |")

    if renovate_data:
        agg = renovate_data.get("aggregate", renovate_data.get("summary", {}))
        overdue = agg.get("overdue", 0)
        security = agg.get("security", 0)
        dep_status = "FAIL" if security > 0 else ("WARN" if overdue > 0 else "PASS")
        lines.append(f"| Dependencies | {dep_status} | {overdue} overdue, {security} security |")
    else:
        lines.append("| Dependencies | N/A | No data |")

    if codecov_data:
        agg = codecov_data.get("aggregate", {})
        avg_cov = agg.get("average_coverage", 0)
        below_50 = agg.get("repos_below_50", 0)
        cov_status = "PASS" if below_50 == 0 else ("WARN" if avg_cov >= 50 else "FAIL")
        lines.append(f"| Code Coverage | {cov_status} | {avg_cov}% avg, {below_50} repos below 50% |")
    else:
        lines.append("| Code Coverage | N/A | No data |")

    if sonar_data:
        agg = sonar_data.get("aggregate", {})
        gate_fail = agg.get("gate_error", 0)
        vulns = agg.get("total_vulnerabilities", 0)
        sonar_status = "FAIL" if gate_fail > 0 or vulns > 0 else "PASS"
        lines.append(f"| SonarCloud | {sonar_status} | {gate_fail} gates failing, {vulns} vulnerabilities |")
    else:
        lines.append("| SonarCloud | N/A | No data |")

    lines.append("")

    action_items = []

    if ci_data:
        results = ci_data.get("results", [ci_data])
        for repo in results:
            slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
            for wf in repo.get("workflows", []):
                if wf.get("conclusion") == "failure" and not wf.get("is_flaky"):
                    action_items.append(
                        f"- **CI FAILURE** [{slug}]({wf.get('url', '')}) - {wf['name']}",
                    )

    if prs_data:
        results = prs_data.get("results", [prs_data])
        for repo in results:
            for pr in repo.get("prs", []):
                slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
                if pr.get("category") == "ready_to_merge":
                    action_items.append(
                        f"- **MERGE** [{slug}#{pr['number']}]({pr.get('url', '')}) - {truncate(pr['title'], 50)}",
                    )

    if renovate_data:
        results = renovate_data.get("results", [renovate_data])
        for repo in results:
            for pr in repo.get("prs", []):
                if pr.get("is_overdue") and pr.get("update_type") == "security":
                    slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
                    action_items.append(
                        f"- **SECURITY DEP** [{slug}#{pr['number']}]({pr.get('url', '')}) - "
                        f"{truncate(pr['title'], 50)}",
                    )

    if sonar_data:
        results = sonar_data.get("results", [sonar_data])
        for proj in results:
            if proj.get("gate_status") == "ERROR":
                slug = f"{proj.get('owner', '?')}/{proj.get('repo', '?')}"
                action_items.append(f"- **SONAR GATE** {slug} - quality gate failing")

    if action_items:
        lines.append("## Priority Action Items")
        lines.append("")
        lines.extend(action_items)
        lines.append("")
    else:
        lines.append("## Priority Action Items")
        lines.append("")
        lines.append("No urgent action items. All systems healthy.")
        lines.append("")

    if prs_data:
        agg = prs_data.get("aggregate", prs_data.get("summary", {}))
        lines.append("## PR Summary")
        lines.append("")
        lines.append(f"- **{agg.get('total_prs', 0)}** total open PRs")
        lines.append(f"- {agg.get('ready_to_merge', 0)} ready to merge")
        lines.append(f"- {agg.get('needs_review', 0)} needs review")
        lines.append(f"- {agg.get('changes_requested', 0)} changes requested")
        lines.append(f"- {agg.get('stale', 0)} stale (14+ days)")
        lines.append("")

    if ci_data:
        agg = ci_data.get("aggregate", ci_data.get("summary", {}))
        lines.append("## CI Summary")
        lines.append("")
        lines.append(f"- **{agg.get('total_workflows', agg.get('total', 0))}** workflows tracked")
        lines.append(f"- {agg.get('passing', 0)} passing")
        lines.append(f"- {agg.get('failing', 0)} failing")
        lines.append(f"- {agg.get('flaky', 0)} flaky")
        lines.append("")

    if renovate_data:
        agg = renovate_data.get("aggregate", renovate_data.get("summary", {}))
        lines.append("## Dependency Summary")
        lines.append("")
        lines.append(f"- **{agg.get('total_prs', agg.get('total', 0))}** dependency PRs open")
        lines.append(f"- {agg.get('overdue', 0)} overdue")
        lines.append(f"- {agg.get('security', 0)} security updates")
        lines.append(f"- {agg.get('major', 0)} major bumps")
        lines.append("")

    if codecov_data:
        agg = codecov_data.get("aggregate", {})
        lines.append("## Code Coverage Summary (Codecov)")
        lines.append("")
        lines.append(f"- **{agg.get('repos_with_coverage', 0)}** repos with coverage data")
        lines.append(f"- {agg.get('average_coverage', 0)}% average coverage")
        lines.append(f"- {agg.get('repos_above_80', 0)} repos above 80%")
        lines.append(f"- {agg.get('repos_below_50', 0)} repos below 50%")
        lines.append("")

    if sonar_data:
        agg = sonar_data.get("aggregate", {})
        lines.append("## SonarCloud Summary")
        lines.append("")
        lines.append(f"- **{sonar_data.get('total_projects', 0)}** projects tracked")
        lines.append(f"- {agg.get('gate_ok', 0)} gates passing")
        lines.append(f"- {agg.get('gate_error', 0)} gates failing")
        lines.append(f"- {agg.get('total_bugs', 0)} total bugs")
        lines.append(f"- {agg.get('total_vulnerabilities', 0)} vulnerabilities")
        lines.append("")

    lines.append("---")
    lines.append("*Generated by td-guardian*")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Handoff Report
# ---------------------------------------------------------------------------


def generate_handoff_report(prs_data, ci_data, renovate_data, sonar_data, codecov_data=None):
    """Generate a Jira handoff template for the next Guardian."""
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    lines = []

    lines.append("# Guardian Handoff Report")
    lines.append("")
    lines.append(f"**Generated:** {now_str}")
    lines.append("")

    lines.append("## Current State Summary")
    lines.append("")

    if ci_data:
        agg = ci_data.get("aggregate", ci_data.get("summary", {}))
        lines.append(f"- CI: {agg.get('failing', 0)} failing, {agg.get('flaky', 0)} flaky workflows")
    if prs_data:
        agg = prs_data.get("aggregate", prs_data.get("summary", {}))
        lines.append(
            f"- PRs: {agg.get('total_prs', 0)} open ({agg.get('ready_to_merge', 0)} ready, {agg.get('stale', 0)} stale)",
        )
    if renovate_data:
        agg = renovate_data.get("aggregate", renovate_data.get("summary", {}))
        lines.append(
            f"- Dependencies: {agg.get('total_prs', agg.get('total', 0))} open ({agg.get('overdue', 0)} overdue)",
        )
    if codecov_data:
        agg = codecov_data.get("aggregate", {})
        lines.append(
            f"- Coverage: {agg.get('average_coverage', 0)}% avg ({agg.get('repos_below_50', 0)} repos below 50%)",
        )
    if sonar_data:
        agg = sonar_data.get("aggregate", {})
        lines.append(
            f"- SonarCloud: {agg.get('gate_error', 0)} failing gates, {agg.get('total_vulnerabilities', 0)} vulnerabilities",
        )
    lines.append("")

    lines.append("## Ongoing Issues")
    lines.append("")
    lines.append("<!-- List active issues being tracked this sprint -->")
    lines.append("")
    lines.append("- [ ] _[Add ongoing issues here]_")
    lines.append("")

    lines.append("## CI Failures Requiring Attention")
    lines.append("")
    if ci_data:
        results = ci_data.get("results", [ci_data])
        has_failures = False
        for repo in results:
            slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
            for wf in repo.get("workflows", []):
                if wf.get("conclusion") == "failure":
                    has_failures = True
                    jobs = ", ".join(j["name"] for j in wf.get("failing_jobs", []))
                    lines.append(f"- **{slug}** - {wf['name']}: {jobs or 'see logs'}")
        if not has_failures:
            lines.append("No CI failures at time of handoff.")
    else:
        lines.append("CI data not available.")
    lines.append("")

    lines.append("## PRs Ready to Merge")
    lines.append("")
    if prs_data:
        results = prs_data.get("results", [prs_data])
        ready = []
        for repo in results:
            slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
            for pr in repo.get("prs", []):
                if pr.get("category") == "ready_to_merge":
                    ready.append(f"- [{slug}#{pr['number']}]({pr.get('url', '')}) - {truncate(pr['title'], 60)}")
        if ready:
            lines.extend(ready)
        else:
            lines.append("No PRs ready to merge.")
    else:
        lines.append("PR data not available.")
    lines.append("")

    lines.append("## Stale PRs (14+ days inactive)")
    lines.append("")
    if prs_data:
        results = prs_data.get("results", [prs_data])
        stale = []
        for repo in results:
            slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
            for pr in repo.get("prs", []):
                if pr.get("category") == "stale":
                    stale.append(
                        f"- [{slug}#{pr['number']}]({pr.get('url', '')}) - {truncate(pr['title'], 60)} ({pr.get('age_days', '?')}d)",
                    )
        if stale:
            lines.extend(stale)
        else:
            lines.append("No stale PRs.")
    else:
        lines.append("PR data not available.")
    lines.append("")

    lines.append("## Overdue Dependency Updates")
    lines.append("")
    if renovate_data:
        results = renovate_data.get("results", [renovate_data])
        overdue = []
        for repo in results:
            slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
            for pr in repo.get("prs", []):
                if pr.get("is_overdue"):
                    overdue.append(
                        f"- [{slug}#{pr['number']}]({pr.get('url', '')}) - "
                        f"{pr.get('update_type', '?')}: {truncate(pr['title'], 50)} ({pr.get('age_days', '?')}d)",
                    )
        if overdue:
            lines.extend(overdue)
        else:
            lines.append("No overdue dependency updates.")
    else:
        lines.append("Dependency data not available.")
    lines.append("")

    lines.append("## Escalated Tickets")
    lines.append("")
    lines.append("<!-- List Jira tickets created during this shift that need follow-up -->")
    lines.append("")
    lines.append("- [ ] _[Add escalated tickets here]_")
    lines.append("")

    lines.append("## Tech Debt / Improvements Attempted")
    lines.append("")
    lines.append("<!-- Note any incremental improvements started or completed -->")
    lines.append("")
    lines.append("- [ ] _[Add tech debt items here]_")
    lines.append("")

    lines.append("## Notes for Next Guardian")
    lines.append("")
    lines.append("<!-- Any context, gotchas, or heads-up for the incoming Guardian -->")
    lines.append("")
    lines.append("- [ ] _[Add notes here]_")
    lines.append("")

    lines.append("---")
    lines.append("*Generated by td-guardian*")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mode dispatch
# ---------------------------------------------------------------------------

SINGLE_INPUT_MODES = {
    "prs": generate_pr_report,
    "ci": generate_ci_report,
    "renovate": generate_renovate_report,
    "sonar": generate_sonar_report,
    "codecov": generate_codecov_report,
}

MULTI_INPUT_MODES = {"guardian", "handoff"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Guardian reports")
    parser.add_argument(
        "mode",
        choices=sorted(list(SINGLE_INPUT_MODES.keys()) + list(MULTI_INPUT_MODES)),
        help="Report type",
    )
    parser.add_argument("input_file", nargs="?", help="JSON data file (for single-input modes)")
    parser.add_argument("--output", "-o", help="Write report to file (default: stdout)")
    parser.add_argument("--prs", help="PR data JSON (for guardian/handoff mode)")
    parser.add_argument("--ci", help="CI data JSON (for guardian/handoff mode)")
    parser.add_argument("--renovate", help="Renovate data JSON (for guardian/handoff mode)")
    parser.add_argument("--sonar", help="SonarCloud data JSON (for guardian/handoff mode)")
    parser.add_argument("--codecov", help="Codecov data JSON (for guardian/handoff mode)")
    parser.add_argument("--changes", help="Since-last-check delta JSON (from diff_snapshots.py)")
    args = parser.parse_args()

    if args.mode in SINGLE_INPUT_MODES:
        if not args.input_file:
            parser.error(f"Mode '{args.mode}' requires an input_file argument")
        data = load_json(args.input_file)
        report = SINGLE_INPUT_MODES[args.mode](data)

    elif args.mode in MULTI_INPUT_MODES:
        prs_data = load_json_safe(args.prs)
        ci_data = load_json_safe(args.ci)
        renovate_data = load_json_safe(args.renovate)
        sonar_data = load_json_safe(args.sonar)
        codecov_data = load_json_safe(args.codecov)
        changes_data = load_json_safe(args.changes)

        if args.mode == "guardian":
            report = generate_guardian_report(
                prs_data,
                ci_data,
                renovate_data,
                sonar_data,
                codecov_data,
                changes_data,
            )
        else:
            report = generate_handoff_report(prs_data, ci_data, renovate_data, sonar_data, codecov_data)
    else:
        parser.error(f"Unknown mode: {args.mode}")
        return

    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(report)


if __name__ == "__main__":
    main()
