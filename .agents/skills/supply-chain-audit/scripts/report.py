"""HTML dashboard report generator for supply chain audit.

Reads cached audit data and findings, produces a standalone HTML file
with embedded CSS, JS, and SVG visualizations.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from cache_utils import (
    get_all_cached_checks,
    get_all_cached_commits,
    get_all_cached_deps,
    get_all_cached_pr_audits,
    get_all_cached_prs,
    get_all_cached_protection,
    get_all_cached_renovate,
    read_findings,
    read_manifest,
    read_package_focus,
)

TEMPLATE_PATH = Path(__file__).parent / "html_templates" / "dashboard.html"

RISK_COLORS = {
    "critical": "#f85149",
    "high": "#db6d28",
    "medium": "#d29922",
    "low": "#3fb950",
    "info": "#8b949e",
}

CATEGORY_LABELS = {
    "unsigned_commit": "Unsigned Commits",
    "github_web_signed": "GitHub-Web-Signed Commits (non-merge)",
    "orphan_commit": "Orphan Commits (No PR)",
    "bypassed_ci": "Bypassed CI",
    "post_merge_push": "Post-Merge Pushes",
    "replicated_message": "Replicated Commit Messages",
    "suspicious_dep_timing": "Suspicious Dependency Timing",
    "yanked_version": "Yanked/Deleted Versions",
    "protection_changed": "Branch Protection Modified",
    "post_approval_commit": "Post-Approval Commits in PR",
    "bot_only_approval": "Bot-Only Approval (No Human Review)",
    "cooldown_violated": "Renovate Cooldown Violated",
    "known_vulnerability": "Known Vulnerabilities (OSV.dev)",
    "self_approved": "Self-Approved PRs",
}


def load_template() -> str:
    """Load the HTML template."""
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return f.read()


def esc(text: str | None) -> str:
    """HTML-escape a string."""
    if text is None:
        return ""
    return html.escape(str(text))


import re as _re

_ADVISORY_PATTERN = _re.compile(r"(GHSA-[\w-]+|PYSEC-[\d-]+|CVE-[\d-]+)")


def _linkify_advisory_ids(text: str) -> str:
    """Turn advisory IDs (GHSA-*, PYSEC-*, CVE-*) into clickable links."""
    def _make_link(m: _re.Match) -> str:
        vuln_id = m.group(1)
        if vuln_id.startswith("GHSA-"):
            url = f"https://github.com/advisories/{vuln_id}"
        else:
            url = f"https://osv.dev/vulnerability/{vuln_id}"
        return f'<a href="{url}" target="_blank">{vuln_id}</a>'

    return _ADVISORY_PATTERN.sub(_make_link, text)


def generate_verdict(findings: list[dict], total_commits: int, total_prs: int) -> str:
    """Generate the top-level verdict banner."""
    if not findings:
        return (
            '<div class="verdict verdict-clean">'
            f'No supply chain anomalies detected. All {total_commits} commits across '
            f'{total_prs} pull requests passed verification checks.'
            '</div>'
        )

    critical = sum(1 for f in findings if f.get("risk_level") == "critical")
    high = sum(1 for f in findings if f.get("risk_level") == "high")

    if critical or high:
        return (
            '<div class="verdict verdict-issues">'
            f'{critical + high} high/critical findings require investigation. '
            f'{len(findings)} total anomalies detected across {total_commits} commits.'
            '</div>'
        )

    return (
        '<div class="verdict verdict-clean">'
        f'{len(findings)} low-severity observations noted. No critical supply chain '
        f'threats detected across {total_commits} commits and {total_prs} pull requests.'
        '</div>'
    )


def generate_repo_summary_rows(
    commits: list[dict],
    prs: list[dict],
    deps: list[dict],
    findings: list[dict],
    protection: dict,
    repos: list[str],
) -> str:
    """Generate per-repo summary table rows."""
    commits_by_repo: dict[str, list[dict]] = {r: [] for r in repos}
    for c in commits:
        repo = c.get("repo", "")
        if repo in commits_by_repo:
            commits_by_repo[repo].append(c)

    prs_by_repo: dict[str, int] = {r: 0 for r in repos}
    for p in prs:
        repo = p.get("repo", "")
        if repo in prs_by_repo and p.get("merged"):
            prs_by_repo[repo] += 1

    deps_by_repo: dict[str, int] = {r: 0 for r in repos}
    for d in deps:
        repo = d.get("repo", "")
        if repo in deps_by_repo:
            deps_by_repo[repo] += 1

    findings_by_repo: dict[str, int] = {r: 0 for r in repos}
    for f in findings:
        repo = f.get("repo", "")
        if repo in findings_by_repo:
            findings_by_repo[repo] += 1

    rows = []
    for repo in sorted(repos):
        repo_commits = commits_by_repo[repo]
        num_commits = len(repo_commits)
        num_prs = prs_by_repo[repo]
        num_deps = deps_by_repo[repo]
        num_findings = findings_by_repo[repo]

        signed_github = 0
        signed_personal = 0
        unsigned = 0
        for c in repo_commits:
            v = c.get("verification", {})
            if v.get("verified"):
                committer = c.get("committer_login", "")
                if committer == "web-flow" or "github" in c.get("committer_email", "").lower():
                    signed_github += 1
                else:
                    signed_personal += 1
            else:
                unsigned += 1

        repo_prot = protection.get(repo, {}).get("rules", {})
        required_checks = repo_prot.get("required_checks", [])
        prot_source = repo_prot.get("source", "none")
        if required_checks:
            checks_str = f'{len(required_checks)} ({prot_source})'
        else:
            checks_str = '<span class="badge badge-medium">none</span>'

        findings_str = str(num_findings) if num_findings == 0 else (
            f'<span class="badge badge-high">{num_findings}</span>'
        )

        row = (
            f'<tr>'
            f'<td><a href="https://github.com/ansible/{repo}" target="_blank">{esc(repo)}</a></td>'
            f'<td>{num_commits}</td>'
            f'<td>{num_prs}</td>'
            f'<td>{signed_github}</td>'
            f'<td>{signed_personal}</td>'
            f'<td>{unsigned}</td>'
            f'<td>{num_deps}</td>'
            f'<td>{checks_str}</td>'
            f'<td>{findings_str}</td>'
            f'</tr>'
        )
        rows.append(row)

    return "\n".join(rows)


def generate_findings_summary(findings: list[dict]) -> str:
    """Generate findings summary with risk breakdown."""
    if not findings:
        return (
            '<div class="verdict verdict-clean" style="margin: 1rem 0;">'
            'All checks passed. No anomalies detected in any category.'
            '</div>'
        )

    risk_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        risk = f.get("risk_level", "info")
        risk_counts[risk] = risk_counts.get(risk, 0) + 1

    cards = []
    for risk in ["critical", "high", "medium", "low", "info"]:
        count = risk_counts[risk]
        if count > 0:
            cards.append(
                f'<div class="summary-card risk-{risk}">'
                f'<span class="number">{count}</span>'
                f'<span class="label">{risk.title()}</span>'
                f'</div>'
            )

    return f'<div class="summary-grid">{"".join(cards)}</div>'


def generate_repo_cards(findings: list[dict], repos: list[str]) -> str:
    """Generate repo status cards with traffic lights."""
    repo_findings: dict[str, list[dict]] = {r: [] for r in repos}
    for f in findings:
        repo = f.get("repo", "")
        if repo in repo_findings:
            repo_findings[repo].append(f)

    cards = []
    for repo in sorted(repos):
        rf = repo_findings.get(repo, [])
        has_critical = any(f["risk_level"] in ("critical", "high") for f in rf)
        has_medium = any(f["risk_level"] == "medium" for f in rf)

        if has_critical:
            light_class = "light-red"
        elif has_medium:
            light_class = "light-yellow"
        else:
            light_class = "light-green"

        count = len(rf)
        count_str = f'{count} issues' if count else "clean"
        cards.append(
            f'<div class="repo-card">'
            f'<div class="light {light_class}"></div>'
            f'<span class="repo-name">{esc(repo)}</span>'
            f'<span class="repo-count">{count_str}</span>'
            f'</div>'
        )
    return "\n".join(cards)


def generate_timeline_svg(commits: list[dict], findings: list[dict], start_date: str, end_date: str) -> str:
    """Generate an SVG timeline visualization."""
    width = 900
    height = 200
    margin_left = 60
    margin_right = 30
    margin_top = 30
    margin_bottom = 40
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    total_days = (end_dt - start_dt).days or 1

    finding_shas = {}
    for f in findings:
        sha = f.get("commit_sha", "")
        if sha:
            existing = finding_shas.get(sha, "info")
            risk = f.get("risk_level", "info")
            priority = ["critical", "high", "medium", "low", "info"]
            if priority.index(risk) < priority.index(existing):
                finding_shas[sha] = risk

    repos = sorted(set(c.get("repo", "") for c in commits))
    if not repos:
        return '<p class="no-data">No commits to visualize</p>'

    repo_y = {repo: margin_top + (i * plot_height // max(len(repos) - 1, 1))
              for i, repo in enumerate(repos)}

    svg_parts = [
        f'<svg class="timeline-svg" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">',
        f'<rect width="{width}" height="{height}" fill="transparent"/>',
    ]

    for repo, y in repo_y.items():
        short_name = repo[:14]
        svg_parts.append(
            f'<text x="{margin_left - 5}" y="{y + 4}" '
            f'font-size="9" fill="#8b949e" text-anchor="end" font-family="sans-serif">'
            f'{esc(short_name)}</text>'
        )
        svg_parts.append(
            f'<line x1="{margin_left}" y1="{y}" x2="{width - margin_right}" y2="{y}" '
            f'stroke="#30363d" stroke-width="0.5"/>'
        )

    num_ticks = min(total_days, 10)
    for i in range(num_ticks + 1):
        x = margin_left + (i * plot_width // num_ticks)
        day_offset = i * total_days // num_ticks
        tick_date = start_dt + timedelta(days=day_offset)
        label = tick_date.strftime("%m/%d")
        svg_parts.append(
            f'<line x1="{x}" y1="{margin_top}" x2="{x}" y2="{height - margin_bottom}" '
            f'stroke="#30363d" stroke-width="0.5" stroke-dasharray="2,4"/>'
        )
        svg_parts.append(
            f'<text x="{x}" y="{height - margin_bottom + 15}" '
            f'font-size="9" fill="#8b949e" text-anchor="middle" font-family="sans-serif">'
            f'{label}</text>'
        )

    for commit in commits:
        date_str = commit.get("date", "")[:10]
        repo = commit.get("repo", "")
        sha = commit.get("sha", "")

        if not date_str or repo not in repo_y:
            continue

        try:
            commit_dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        days_offset = (commit_dt - start_dt).days
        x = margin_left + (days_offset * plot_width // total_days)
        y = repo_y[repo]

        risk = finding_shas.get(sha, "")
        if risk:
            color = RISK_COLORS.get(risk, "#3fb950")
            radius = 5 if risk in ("critical", "high") else 4
        else:
            color = "#3fb950"
            radius = 3

        svg_parts.append(
            f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{color}" opacity="0.8">'
            f'<title>{esc(repo)} {esc(sha[:8])} {esc(date_str)}</title>'
            f'</circle>'
        )

    svg_parts.append('</svg>')
    return "\n".join(svg_parts)


def generate_commit_integrity_section(commits: list[dict], findings: list[dict]) -> str:
    """Generate commit integrity table, only if there are flagged commits."""
    commit_findings = [f for f in findings if f.get("commit_sha")]
    if not commit_findings:
        return ""

    finding_by_sha: dict[str, list[dict]] = {}
    for f in commit_findings:
        sha = f.get("commit_sha", "")
        if sha:
            finding_by_sha.setdefault(sha, []).append(f)

    rows = []
    for commit in commits:
        sha = commit["sha"]
        if sha not in finding_by_sha:
            continue

        cf = finding_by_sha[sha]
        risk = "info"
        for f in cf:
            r = f.get("risk_level", "info")
            priority = ["critical", "high", "medium", "low", "info"]
            if priority.index(r) < priority.index(risk):
                risk = r

        verified = commit.get("verification", {}).get("verified", False)
        signed_icon = "&#10003;" if verified else "&#10007;"
        signed_class = "low" if verified else "critical"

        signer = commit.get("committer_login", "")
        prs = commit.get("associated_prs", [])
        repo_name = commit.get("repo", "")
        pr_str = ", ".join(
            f'<a href="https://github.com/ansible/{repo_name}/pull/{p}" '
            f'target="_blank">#{p}</a>'
            for p in prs
        ) if prs else "\u2014"

        flags = []
        for f in cf:
            cat = f.get("category", "")
            label = CATEGORY_LABELS.get(cat, cat).split("(")[0].strip()
            flags.append(f'<span class="badge badge-{f.get("risk_level", "info")}">{esc(label)}</span>')

        row = (
            f'<tr data-risk="{risk}">'
            f'<td>{esc(commit["repo"])}</td>'
            f'<td><code>{esc(sha[:8])}</code></td>'
            f'<td>{esc(commit.get("author_login", ""))}</td>'
            f'<td>{esc(commit.get("date", "")[:10])}</td>'
            f'<td><span class="badge badge-{signed_class}">{signed_icon}</span></td>'
            f'<td>{esc(signer)}</td>'
            f'<td>{pr_str}</td>'
            f'<td>{" ".join(flags)}</td>'
            f'</tr>'
        )
        rows.append(row)

    if not rows:
        return ""

    return (
        '<h2>Flagged Commits</h2>'
        '<p>Commits with one or more anomaly detections. Click column headers to sort.</p>'
        '<div class="controls">'
        '<input type="text" id="commitFilter" placeholder="Filter by repo, author, SHA..." '
        'onkeyup="filterTable(\'commitTable\', this.value)">'
        '</div>'
        '<div style="overflow-x: auto;">'
        '<table id="commitTable">'
        '<thead><tr>'
        '<th onclick="sortTable(\'commitTable\', 0)">Repo <span class="sort-arrow">\u25be</span></th>'
        '<th onclick="sortTable(\'commitTable\', 1)">SHA <span class="sort-arrow">\u25be</span></th>'
        '<th onclick="sortTable(\'commitTable\', 2)">Author <span class="sort-arrow">\u25be</span></th>'
        '<th onclick="sortTable(\'commitTable\', 3)">Date <span class="sort-arrow">\u25be</span></th>'
        '<th onclick="sortTable(\'commitTable\', 4)">Signed <span class="sort-arrow">\u25be</span></th>'
        '<th onclick="sortTable(\'commitTable\', 5)">Signer <span class="sort-arrow">\u25be</span></th>'
        '<th onclick="sortTable(\'commitTable\', 6)">PR# <span class="sort-arrow">\u25be</span></th>'
        '<th onclick="sortTable(\'commitTable\', 7)">Flags <span class="sort-arrow">\u25be</span></th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table></div>'
    )


def generate_dep_section(deps: list[dict], prs: list[dict]) -> str:
    """Generate the dependency changes section."""
    if not deps:
        return '<p class="no-data">No dependency changes detected in the audit window.</p>'

    # Build a map of merge_commit_sha -> PR number for linking
    sha_to_pr: dict[str, tuple[str, int]] = {}
    for pr in prs:
        sha = pr.get("merge_commit_sha", "")
        if sha and pr.get("merged"):
            sha_to_pr[sha] = (pr.get("repo", ""), pr.get("number", 0))

    rows = []
    for dep in deps:
        flags = []
        days = dep.get("days_since_release")
        if days is not None and days < 7:
            flags.append('<span class="badge badge-high">rapid adoption</span>')
        if dep.get("yanked"):
            flags.append('<span class="badge badge-critical">yanked</span>')

        days_str = str(days) if days is not None else "\u2014"
        commit_date = esc(dep.get("commit_date") or "\u2014")

        # Find associated PR
        commit_sha = dep.get("commit_sha", "")
        pr_info = sha_to_pr.get(commit_sha)
        if pr_info:
            repo_name, pr_num = pr_info
            pr_cell = (
                f'<a href="https://github.com/ansible/{repo_name}/pull/{pr_num}" '
                f'target="_blank">#{pr_num}</a>'
            )
        else:
            pr_cell = "\u2014"

        row = (
            f'<tr>'
            f'<td>{esc(dep.get("repo", ""))}</td>'
            f'<td><code>{esc(dep.get("package_name", ""))}</code></td>'
            f'<td>{esc(dep.get("change_type", ""))}</td>'
            f'<td>{esc(dep.get("old_version") or "\u2014")}</td>'
            f'<td>{esc(dep.get("new_version") or "\u2014")}</td>'
            f'<td>{esc(dep.get("release_date") or "\u2014")}</td>'
            f'<td>{commit_date}</td>'
            f'<td>{days_str}</td>'
            f'<td>{pr_cell}</td>'
            f'<td>{" ".join(flags) if flags else "\u2014"}</td>'
            f'</tr>'
        )
        rows.append(row)

    return (
        '<div class="controls">'
        '<input type="text" id="depFilter" placeholder="Filter by package, repo..." '
        'onkeyup="filterTable(\'depTable\', this.value)">'
        '</div>'
        '<div style="overflow-x: auto;">'
        '<table id="depTable"><thead><tr>'
        '<th onclick="sortTable(\'depTable\', 0)">Repo <span class="sort-arrow">\u25be</span></th>'
        '<th onclick="sortTable(\'depTable\', 1)">Package <span class="sort-arrow">\u25be</span></th>'
        '<th onclick="sortTable(\'depTable\', 2)">Change <span class="sort-arrow">\u25be</span></th>'
        '<th onclick="sortTable(\'depTable\', 3)">Old Version <span class="sort-arrow">\u25be</span></th>'
        '<th onclick="sortTable(\'depTable\', 4)">New Version <span class="sort-arrow">\u25be</span></th>'
        '<th onclick="sortTable(\'depTable\', 5)">Released <span class="sort-arrow">\u25be</span></th>'
        '<th onclick="sortTable(\'depTable\', 6)">Adopted <span class="sort-arrow">\u25be</span></th>'
        '<th onclick="sortTable(\'depTable\', 7)">Days <span class="sort-arrow">\u25be</span></th>'
        '<th onclick="sortTable(\'depTable\', 8)">PR <span class="sort-arrow">\u25be</span></th>'
        '<th onclick="sortTable(\'depTable\', 9)">Flags <span class="sort-arrow">\u25be</span></th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table></div>'
    )


def generate_renovate_config_table(renovate_configs: dict[str, dict], repos: list[str]) -> str:
    """Generate a table showing each repo's configured renovate cooldown."""
    rows = []
    for repo in sorted(repos):
        config = renovate_configs.get(repo, {})
        source = config.get("source", "none")
        default_cd = config.get("default_cooldown_days")
        major_cd = config.get("major_cooldown_days")

        if source == "none":
            source_display = '<span class="badge badge-high">none</span>'
            default_str = "\u2014"
            major_str = "\u2014"
        else:
            if "shared:" in source:
                source_display = "shared preset"
            else:
                source_display = "local"
            default_str = f"{default_cd} days" if default_cd else "\u2014"
            major_str = f"{major_cd} days" if major_cd else "(inherits default)"

        rows.append(
            f"<tr>"
            f"<td>{esc(repo)}</td>"
            f"<td>{default_str}</td>"
            f"<td>{major_str}</td>"
            f"<td>{source_display}</td>"
            f"</tr>"
        )

    return (
        '<h2>Renovate Cooldown Policy</h2>'
        '<p>Configured <code>minimumReleaseAge</code> per repository. '
        'Dependencies adopted before the cooldown expires are flagged as critical violations.</p>'
        '<div style="overflow-x: auto;">'
        '<table><thead><tr>'
        '<th>Repository</th>'
        '<th>Default Cooldown</th>'
        '<th>Major Update Cooldown</th>'
        '<th>Config Source</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table></div>'
    )


def generate_findings_details(findings: list[dict]) -> str:
    """Generate collapsible findings detail sections."""
    if not findings:
        return ""

    by_category: dict[str, list[dict]] = {}
    for f in findings:
        cat = f.get("category", "unknown")
        by_category.setdefault(cat, []).append(f)

    sections = []
    risk_priority = ["critical", "high", "medium", "low", "info"]
    for cat, cat_findings in sorted(by_category.items(), key=lambda x: -len(x[1])):
        label = CATEGORY_LABELS.get(cat, cat)
        count = len(cat_findings)

        # Sort findings within category: highest risk first
        cat_findings.sort(key=lambda f: risk_priority.index(f.get("risk_level", "info")))

        max_risk = cat_findings[0].get("risk_level", "info") if cat_findings else "info"

        items_html = []
        for f in cat_findings[:50]:
            pr_num = f.get("pr_number")
            repo = f.get("repo", "")
            pr_link = ""
            if pr_num:
                pr_link = (
                    f' <a href="https://github.com/ansible/{repo}/pull/{pr_num}" '
                    f'target="_blank">PR #{pr_num}</a>'
                )
            summary_html = _linkify_advisory_ids(esc(f.get("summary", "")))
            details_html = _linkify_advisory_ids(esc(f.get("details", "")[:300]))
            items_html.append(
                f'<div style="padding: 0.5rem 0; border-bottom: 1px solid var(--border);">'
                f'<span class="badge badge-{f.get("risk_level", "info")}">{f.get("risk_level", "")}</span> '
                f'<strong>{esc(repo)}</strong>{pr_link} \u2014 {summary_html}'
                f'<div style="color: var(--text-muted); font-size: 0.8rem; margin-top: 0.3rem;">'
                f'{details_html}</div>'
                f'</div>'
            )
        if count > 50:
            items_html.append(f'<div class="no-data">... and {count - 50} more</div>')

        section = (
            f'<div class="collapsible">'
            f'<div class="collapsible-header">'
            f'<span class="arrow">\u25b6</span>'
            f'<span class="badge badge-{max_risk}">{count}</span>'
            f'{esc(label)}'
            f'</div>'
            f'<div class="collapsible-body">'
            f'{"".join(items_html)}'
            f'</div>'
            f'</div>'
        )
        sections.append(section)

    return (
        '<h2>Anomaly Details</h2>'
        '<p>Expand each category to see individual findings.</p>'
        + "\n".join(sections)
    )


def render_recommendations_html(recommendations: list[dict[str, str]]) -> str:
    """Render agent-authored recommendations into HTML.

    Each recommendation is a dict with keys: title, detail, priority (optional).
    The agent writes these based on its analysis of findings.
    """
    if not recommendations:
        return ""

    items = []
    for i, rec in enumerate(recommendations[:10], 1):
        title = esc(rec.get("title", ""))
        detail = rec.get("detail", "")
        items.append(
            f'<div style="padding: 0.75rem 0; border-bottom: 1px solid var(--border);">'
            f'<strong>{i}. {title}</strong>'
            f'<div style="color: var(--text-muted); font-size: 0.85rem; margin-top: 0.3rem;">'
            f'{detail}</div>'
            f'</div>'
        )

    return (
        '<h2>Security Recommendations</h2>'
        '<p>Prioritized actions based on this audit\'s findings, ordered by impact.</p>'
        + "".join(items)
    )


def generate_package_focus_section(package_data: dict | None) -> str:
    """Generate the Phase 2 package focus section if data exists."""
    if not package_data:
        return ""

    pkg = package_data.get("package_name", "unknown")
    date = package_data.get("compromise_date", "unknown")
    affected = package_data.get("affected_entries", [])
    total_using = package_data.get("total_repos_using", 0)
    exposed = package_data.get("potentially_exposed_count", 0)

    rows = []
    for entry in affected:
        risk = entry.get("risk_assessment", "low")
        rows.append(
            f'<tr>'
            f'<td>{esc(entry.get("repo", ""))}</td>'
            f'<td><code>{esc(entry.get("version", ""))}</code></td>'
            f'<td>{esc(entry.get("change_type", ""))}</td>'
            f'<td>{esc(entry.get("commit_date", ""))}</td>'
            f'<td>{esc(entry.get("version_release_date", ""))}</td>'
            f'<td>{"Yes" if entry.get("is_pinned") else "No (range)"}</td>'
            f'<td><span class="badge badge-{risk}">{risk}</span></td>'
            f'</tr>'
        )

    table_html = ""
    if rows:
        table_html = (
            '<table><thead><tr>'
            '<th>Repo</th><th>Version</th><th>Change</th>'
            '<th>Adopted</th><th>Released</th><th>Pinned?</th><th>Risk</th>'
            '</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody>'
            '</table>'
        )
    else:
        table_html = '<div class="no-data">No affected entries found in the audit window</div>'

    return (
        f'<h2>Package Focus: {esc(pkg)}</h2>'
        f'<div class="package-focus">'
        f'<h3>Impact Analysis: {esc(pkg)} (compromise date: {esc(date)})</h3>'
        f'<div class="summary-grid">'
        f'<div class="summary-card"><span class="number">{total_using}</span>'
        f'<span class="label">Repos Using Package</span></div>'
        f'<div class="summary-card risk-critical"><span class="number">{exposed}</span>'
        f'<span class="label">Potentially Exposed</span></div>'
        f'<div class="summary-card"><span class="number">{len(affected)}</span>'
        f'<span class="label">Affected Entries</span></div>'
        f'</div>'
        f'{table_html}'
        f'</div>'
    )


def generate_report(cache_dir: Path, output_path: Path) -> None:
    """Generate the complete HTML report."""
    print("Loading data...")
    manifest = read_manifest(cache_dir)
    if not manifest:
        print("ERROR: No manifest found", file=sys.stderr)
        sys.exit(1)

    commits = get_all_cached_commits(cache_dir)
    prs = get_all_cached_prs(cache_dir)
    checks = get_all_cached_checks(cache_dir)
    deps = get_all_cached_deps(cache_dir)
    protection = get_all_cached_protection(cache_dir)
    pr_audits = get_all_cached_pr_audits(cache_dir)
    renovate_configs = get_all_cached_renovate(cache_dir)
    findings = read_findings(cache_dir)
    package_data = read_package_focus(cache_dir)

    start_date = manifest["start_date"]
    end_date = manifest["end_date"]
    repos = manifest.get("repos", [])
    gh_version = manifest.get("gh_version", "unknown")

    total_check_suites = sum(len(v) for v in checks.values())
    total_prs = len([p for p in prs if p.get("merged")])
    total_pr_branch_commits = sum(a.get("commit_count", 0) for a in pr_audits)

    print("Generating components...")
    template = load_template()

    verdict_section = generate_verdict(findings, len(commits), total_prs)
    repo_summary_rows = generate_repo_summary_rows(commits, prs, deps, findings, protection, repos)
    findings_summary = generate_findings_summary(findings)
    repo_cards = generate_repo_cards(findings, repos)
    timeline_svg = generate_timeline_svg(commits, findings, start_date, end_date)
    commit_integrity = generate_commit_integrity_section(commits, findings)
    dep_section = generate_dep_section(deps, prs)
    renovate_section = generate_renovate_config_table(renovate_configs, repos)
    findings_details = generate_findings_details(findings)

    recommendations_path = cache_dir / "recommendations.json"
    if recommendations_path.exists():
        with open(recommendations_path, encoding="utf-8") as fh:
            recs = json.load(fh)
        recommendations_section = render_recommendations_html(recs)
    else:
        recommendations_section = (
            '<h2>Security Recommendations</h2>'
            '<p><em>Recommendations will be generated by the agent after analysis. '
            'Re-run report.py after writing recommendations.json.</em></p>'
        )

    package_focus_section = generate_package_focus_section(package_data)

    print("Rendering HTML...")
    output = template
    replacements = {
        "{{start_date}}": start_date,
        "{{end_date}}": end_date,
        "{{generated_at}}": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "{{repo_count}}": str(len(repos)),
        "{{gh_version}}": esc(gh_version),
        "{{total_commits}}": str(len(commits)),
        "{{total_prs}}": str(total_prs),
        "{{total_pr_branch_commits}}": str(total_pr_branch_commits),
        "{{total_check_suites}}": str(total_check_suites),
        "{{total_dep_changes}}": str(len(deps)),
        "{{total_findings}}": str(len(findings)),
        "{{verdict_section}}": verdict_section,
        "{{repo_summary_rows}}": repo_summary_rows,
        "{{findings_summary_section}}": findings_summary,
        "{{repo_cards}}": repo_cards,
        "{{timeline_svg}}": timeline_svg,
        "{{commit_integrity_section}}": commit_integrity,
        "{{dep_section}}": dep_section,
        "{{renovate_section}}": renovate_section,
        "{{findings_details_section}}": findings_details,
        "{{recommendations_section}}": recommendations_section,
        "{{package_focus_section}}": package_focus_section,
    }

    for placeholder, value in replacements.items():
        output = output.replace(placeholder, value)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"\nReport generated: {output_path}")
    print(f"  Size: {output_path.stat().st_size / 1024:.1f} KB")
    print(f"  Findings: {len(findings)} total")
    print(f"  Commits: {len(commits)}")
    print(f"  PRs: {total_prs}")
    print(f"  Check suites: {total_check_suites}")
    print(f"  Dep changes: {len(deps)}")


def main() -> None:
    """Entry point for report generation."""
    parser = argparse.ArgumentParser(description="Supply chain audit HTML report generator")
    parser.add_argument("--cache-dir", required=True, help="Cache directory with audit data")
    parser.add_argument("--output", default=".supply-chain-audit/report.html",
                        help="Output HTML file path")
    args = parser.parse_args()

    cache_path = Path(args.cache_dir)

    cache_dir = cache_path
    if not (cache_path / "manifest.json").exists():
        for subdir in sorted(cache_path.iterdir()):
            if subdir.is_dir() and (subdir / "manifest.json").exists():
                cache_dir = subdir
                break
        else:
            print("ERROR: No manifest.json found. Run collect.py first.", file=sys.stderr)
            sys.exit(1)

    generate_report(cache_dir, Path(args.output))


if __name__ == "__main__":
    main()
