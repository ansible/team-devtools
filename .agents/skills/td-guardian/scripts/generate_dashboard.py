#!/usr/bin/env python3
"""Generate a self-contained HTML dashboard from Guardian JSON data.

Produces a single index.html with embedded CSS — no external dependencies.
Designed to be deployed to GitHub Pages via Actions.

Usage:
    python3 scripts/generate_dashboard.py --prs reports/open-prs.json --output docs/index.html
    python3 scripts/generate_dashboard.py --prs FILE --ci FILE --renovate FILE --sonar FILE -o docs/index.html
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def load_json_safe(path):
    if not path:
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"WARN: Could not load {path}: {e}", file=sys.stderr)
        return None


def esc(text):
    """Escape HTML entities."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def status_class(status) -> str:
    if status in ("OK", "success", "passing", "PASS", "ready_to_merge"):
        return "ok"
    if status in ("ERROR", "failure", "failing", "FAIL", "blocked"):
        return "error"
    if status in ("WARN", "warning", "flaky", "stale", "changes_requested"):
        return "warn"
    if status in ("draft", "NONE", "needs_review"):
        return "neutral"
    return "unknown"


def status_label(status):
    mapping = {
        "OK": "Passing",
        "ERROR": "Failing",
        "WARN": "Warning",
        "NONE": "No Gate",
        "UNKNOWN": "Unknown",
        "success": "Pass",
        "failure": "Fail",
    }
    return mapping.get(status, status)


def card_html(title, status, detail) -> str:
    cls = status_class(status)
    return f"""<div class="card {cls}">
  <div class="card-title">{esc(title)}</div>
  <div class="card-status">{esc(status_label(status))}</div>
  <div class="card-detail">{esc(detail)}</div>
</div>"""


def section_html(section_id, title, count, content, collapsed=False) -> str:
    return f"""<details class="section" id="{section_id}" {"" if collapsed else "open"}>
  <summary><h2>{esc(title)} <span class="badge">{count}</span></h2></summary>
  {content}
</details>"""


def build_changes_section(changes_data) -> str:
    """Render a Since last check delta panel from changes.json."""
    if not changes_data:
        return ""

    if not changes_data.get("has_baseline", True):
        return (
            '<div class="action-items changes-section">'
            "<h3>Since Last Check</h3>"
            "<p>No previous snapshot yet — delta starts next run.</p>"
            "</div>"
        )

    summary = changes_data.get("summary", {})
    compared = changes_data.get("compared_to") or "previous run"
    total = sum(summary.values()) if summary else 0

    if total == 0:
        return (
            f'<div class="action-items ok changes-section">'
            f"<h3>Since Last Check</h3>"
            f"<p>No material changes since {esc(compared)}.</p>"
            f"</div>"
        )

    def _items(entries, tag, cls, fmt):
        rows = []
        for e in entries[:8]:
            rows.append(f'<li><span class="status {cls}">{tag}</span> {fmt(e)}</li>')
        return rows

    def _wf_link(e) -> str:
        slug = esc(e.get("repo", "?"))
        name = esc(e.get("workflow", "?"))
        url = e.get("url", "")
        link = f'<a href="{esc(url)}" target="_blank">{slug}</a>' if url else slug
        return f"{link} — {name}"

    def _pr_link(e):
        slug = esc(e.get("repo", "?"))
        num = e.get("number", "?")
        title = esc((e.get("title") or "")[:50])
        url = e.get("url", "")
        label = f"{slug}#{num}"
        link = f'<a href="{esc(url)}" target="_blank">{label}</a>' if url else label
        return f"{link} — {title}" if title else link

    rows = []
    ci = changes_data.get("ci", {})
    prs = changes_data.get("prs", {})
    ren = changes_data.get("renovate", {})

    rows += _items(ci.get("new_failures", []), "NEW FAIL", "error", _wf_link)
    rows += _items(ci.get("resolved_failures", []), "RESOLVED", "ok", _wf_link)
    rows += _items(ci.get("new_flaky", []), "NEW FLAKY", "warn", _wf_link)
    rows += _items(prs.get("became_stale", []), "STALE", "warn", _pr_link)
    rows += _items(prs.get("became_ready", []), "READY", "ok", _pr_link)
    rows += _items(prs.get("newly_opened", []), "NEW PR", "neutral", _pr_link)
    rows += _items(ren.get("newly_overdue", []), "OVERDUE", "error", _pr_link)
    rows += _items(ren.get("no_longer_overdue", []), "DEP OK", "ok", _pr_link)

    badges = f'<span class="badge">{total}</span> <span class="changes-meta">vs {esc(compared)}</span>'
    return f'<div class="action-items changes-section"><h3>Since Last Check {badges}</h3><ul>{"".join(rows)}</ul></div>'


def build_action_items(prs_data, ci_data, renovate_data, sonar_data) -> str:
    items = []

    if ci_data:
        for repo in ci_data.get("results", [ci_data]):
            slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
            for wf in repo.get("workflows", []):
                if wf.get("conclusion") == "failure" and not wf.get("is_flaky"):
                    url = wf.get("url", "")
                    link = f'<a href="{esc(url)}" target="_blank">{esc(slug)}</a>' if url else esc(slug)
                    items.append(("error", "CI FAILURE", f"{link} — {esc(wf['name'])}"))

    if prs_data:
        for repo in prs_data.get("results", [prs_data]):
            slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
            for pr in repo.get("prs", []):
                if pr.get("category") == "ready_to_merge":
                    url = pr.get("url", "")
                    link = (
                        f'<a href="{esc(url)}" target="_blank">{esc(slug)}#{pr["number"]}</a>'
                        if url
                        else f"{esc(slug)}#{pr['number']}"
                    )
                    items.append(("ok", "MERGE", f"{link} — {esc(pr.get('title', '')[:50])}"))

    if renovate_data:
        for repo in renovate_data.get("results", [renovate_data]):
            slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
            for pr in repo.get("prs", []):
                if pr.get("is_overdue") and pr.get("update_type") == "security":
                    url = pr.get("url", "")
                    link = (
                        f'<a href="{esc(url)}" target="_blank">{esc(slug)}#{pr["number"]}</a>'
                        if url
                        else f"{esc(slug)}#{pr['number']}"
                    )
                    items.append(("error", "SECURITY DEP", f"{link} — {esc(pr.get('title', '')[:50])}"))

    if sonar_data:
        for proj in sonar_data.get("results", [sonar_data]):
            if proj.get("gate_status") == "ERROR":
                slug = f"{proj.get('owner', '?')}/{proj.get('repo', '?')}"
                items.append(("warn", "SONAR GATE", f"{esc(slug)} — quality gate failing"))

    if not items:
        return '<div class="action-items ok"><h3>Priority Actions</h3><p>All systems healthy. No urgent action items.</p></div>'

    rows = ""
    for cls, tag, detail in items:
        rows += f'<li><span class="status {cls}">{tag}</span> {detail}</li>'

    return f'<div class="action-items"><h3>Priority Actions <span class="badge">{len(items)}</span></h3><ul>{rows}</ul></div>'


def build_health_cards(prs_data, ci_data, renovate_data, sonar_data, codecov_data=None, security_audit_data=None):
    cards = []

    if ci_data:
        agg = ci_data.get("aggregate", ci_data.get("summary", {}))
        failing = agg.get("failing", 0)
        flaky = agg.get("flaky", 0)
        status = "OK" if failing == 0 and flaky == 0 else ("WARN" if failing == 0 else "ERROR")
        cards.append(card_html("CI / Pipeline", status, f"{failing} failing, {flaky} flaky"))
    else:
        cards.append(card_html("CI / Pipeline", "UNKNOWN", "No data"))

    if prs_data:
        agg = prs_data.get("aggregate", prs_data.get("summary", {}))
        ready = agg.get("ready_to_merge", 0)
        stale = agg.get("stale", 0)
        blocked = agg.get("blocked", 0)
        total = agg.get("total_prs", 0)
        status = "OK" if blocked == 0 and stale == 0 else ("WARN" if blocked == 0 else "ERROR")
        cards.append(card_html("Open PRs", status, f"{total} total, {ready} ready, {stale} stale"))
    else:
        cards.append(card_html("Open PRs", "UNKNOWN", "No data"))

    if renovate_data:
        agg = renovate_data.get("aggregate", renovate_data.get("summary", {}))
        overdue = agg.get("overdue", 0)
        security = agg.get("security", 0)
        total = agg.get("total_prs", agg.get("total", 0))
        status = "ERROR" if security > 0 else ("WARN" if overdue > 0 else "OK")
        cards.append(card_html("Dependencies", status, f"{total} open, {overdue} overdue"))
    else:
        cards.append(card_html("Dependencies", "UNKNOWN", "No data"))

    if codecov_data:
        agg = codecov_data.get("aggregate", {})
        avg_cov = agg.get("average_coverage", 0)
        below_50 = agg.get("repos_below_50", 0)
        above_80 = agg.get("repos_above_80", 0)
        status = "OK" if below_50 == 0 else ("WARN" if avg_cov >= 50 else "ERROR")
        cards.append(card_html("Code Coverage", status, f"{avg_cov}% avg, {above_80} above 80%"))
    else:
        cards.append(card_html("Code Coverage", "UNKNOWN", "No data"))

    if sonar_data:
        agg = sonar_data.get("aggregate", {})
        gate_fail = agg.get("gate_error", 0)
        vulns = agg.get("total_vulnerabilities", 0)
        gate_ok = agg.get("gate_ok", 0)
        status = "ERROR" if gate_fail > 0 else "OK"
        cards.append(card_html("SonarCloud", status, f"{gate_ok} passing, {gate_fail} failing, {vulns} vulns"))
    else:
        cards.append(card_html("SonarCloud", "UNKNOWN", "No data"))

    cards_html = '<div class="cards">' + "\n".join(cards) + "</div>"

    if security_audit_data:
        risk = security_audit_data.get("risk_totals", {})
        crit = risk.get("critical", 0)
        high = risk.get("high", 0)
        med = risk.get("medium", 0)
        security_audit_data.get("total_findings", 0)
        window = security_audit_data.get("audit_window", "")

        badges = ""
        for level, count in [("critical", crit), ("high", high), ("medium", med)]:
            if count == 0:
                continue
            bcls = "error" if level in ("critical", "high") else "warn"
            badges += f'<span class="status {bcls}" style="margin-left:0.5rem;padding:0.15rem 0.5rem;font-size:0.8rem;">{count} {level}</span>'

        cards_html += (
            f'<a href="audit.html" target="_blank" style="text-decoration:none;display:block;'
            f"margin:-12px 0 24px;padding:10px 16px;border-radius:8px;"
            f"border:1px solid var(--border);"
            f'background:var(--card-bg);color:var(--text);">'
            f'<span style="font-weight:600;">Security Audit</span>'
            f"{badges}"
            f'<span style="color:var(--text-muted);margin-left:0.75rem;font-size:0.85rem;">{esc(window)}</span>'
            f'<span style="float:right;font-weight:600;color:var(--accent);">View Full Report &rarr;</span>'
            f"</a>"
        )

    return cards_html


def build_ci_section(ci_data):
    if not ci_data:
        return ""

    results = ci_data.get("results", [ci_data])
    failing = []
    flaky = []
    all_repos = []

    for repo in results:
        slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
        s = repo.get("summary", {})
        repo_status = "ok"
        if repo.get("error") or s.get("failing", 0) > 0:
            repo_status = "error"
        elif s.get("flaky", 0) > 0:
            repo_status = "warn"

        all_repos.append(
            f'<tr class="{repo_status}">'
            f"<td>{esc(slug)}</td>"
            f"<td>{s.get('total', 0)}</td>"
            f"<td>{s.get('passing', 0)}</td>"
            f"<td>{s.get('failing', 0)}</td>"
            f"<td>{s.get('flaky', 0)}</td>"
            f'<td><span class="status {repo_status}">{repo_status.upper()}</span></td>'
            f"</tr>",
        )

        for wf in repo.get("workflows", []):
            wf_entry = {"_repo": slug, **wf}
            if wf.get("conclusion") == "failure" and not wf.get("is_flaky"):
                failing.append(wf_entry)
            if wf.get("is_flaky"):
                flaky.append(wf_entry)

    content = ""

    if failing:
        rows = ""
        for wf in failing:
            jobs = ", ".join(j["name"] for j in wf.get("failing_jobs", []))
            url = wf.get("url", "")
            link = f'<a href="{esc(url)}" target="_blank">{esc(wf["name"])}</a>' if url else esc(wf["name"])
            rows += (
                f"<tr>"
                f"<td>{esc(wf['_repo'])}</td>"
                f"<td>{link}</td>"
                f"<td>{wf.get('age_hours', '?')}h</td>"
                f"<td>{esc(jobs or '-')}</td>"
                f"</tr>"
            )
        content += f"""<h3>Failing Workflows ({len(failing)})</h3>
<table><thead><tr><th>Repo</th><th>Workflow</th><th>Age</th><th>Failing Jobs</th></tr></thead>
<tbody>{rows}</tbody></table>"""

    if flaky:
        rows = ""
        for wf in flaky:
            url = wf.get("url", "")
            link = f'<a href="{esc(url)}" target="_blank">{esc(wf["name"])}</a>' if url else esc(wf["name"])
            rows += f"<tr><td>{esc(wf['_repo'])}</td><td>{link}</td><td>{esc(wf.get('conclusion', '?'))}</td></tr>"
        content += f"""<h3>Flaky Workflows ({len(flaky)})</h3>
<table><thead><tr><th>Repo</th><th>Workflow</th><th>Last Result</th></tr></thead>
<tbody>{rows}</tbody></table>"""

    rows = "\n".join(all_repos)
    content += f"""<h3>Per-Repo Status</h3>
<table><thead><tr><th>Repository</th><th>Total</th><th>Passing</th><th>Failing</th><th>Flaky</th><th>Status</th></tr></thead>
<tbody>{rows}</tbody></table>"""

    agg = ci_data.get("aggregate", ci_data.get("summary", {}))
    total = agg.get("total_workflows", agg.get("total", 0))
    return section_html("ci", "CI / Pipeline Health", total, content)


def build_pr_section(prs_data):
    if not prs_data:
        return ""

    results = prs_data.get("results", [prs_data])
    categories = [
        ("ready_to_merge", "Ready to Merge", "ok"),
        ("needs_review", "Needs Review", "neutral"),
        ("changes_requested", "Changes Requested", "warn"),
        ("blocked", "Blocked", "error"),
        ("stale", "Stale", "warn"),
        ("draft", "Draft", "neutral"),
    ]

    prs_by_cat = {k: [] for k, _, _ in categories}
    for repo in results:
        slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
        if repo.get("error"):
            continue
        for pr in repo.get("prs", []):
            pr["_repo"] = slug
            cat = pr.get("category", "needs_review")
            if cat in prs_by_cat:
                prs_by_cat[cat].append(pr)

    content = ""
    for cat_key, cat_title, cls in categories:
        prs = prs_by_cat[cat_key]
        if not prs:
            continue

        prs.sort(key=lambda p: p.get("age_days", 0), reverse=True)
        rows = ""
        for pr in prs:
            url = pr.get("url", "")
            link = f'<a href="{esc(url)}" target="_blank">#{pr["number"]}</a>' if url else f"#{pr['number']}"
            rows += (
                f"<tr>"
                f"<td>{esc(pr['_repo'])}</td>"
                f"<td>{link}</td>"
                f"<td>{esc(pr.get('title', '')[:60])}</td>"
                f"<td>{esc(pr.get('author', ''))}</td>"
                f"<td>{pr.get('age_days', 0)}d</td>"
                f"</tr>"
            )
        content += f"""<h3><span class="status {cls}">{cat_title}</span> ({len(prs)})</h3>
<table><thead><tr><th>Repo</th><th>PR</th><th>Title</th><th>Author</th><th>Age</th></tr></thead>
<tbody>{rows}</tbody></table>"""

    agg = prs_data.get("aggregate", prs_data.get("summary", {}))
    total = agg.get("total_prs", 0)
    return section_html("prs", "Open Pull Requests", total, content)


def build_renovate_section(renovate_data):
    if not renovate_data:
        return ""

    results = renovate_data.get("results", [renovate_data])
    priority_order = {"security": 0, "major": 1, "minor": 2}
    overdue = []
    pending = []

    for repo in results:
        slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
        if repo.get("error"):
            continue
        for pr in repo.get("prs", []):
            pr["_repo"] = slug
            if pr.get("is_overdue"):
                overdue.append(pr)
            else:
                pending.append(pr)

    content = ""

    if overdue:
        overdue.sort(key=lambda p: (priority_order.get(p.get("update_type", "minor"), 2), -p.get("age_days", 0)))
        rows = ""
        for pr in overdue:
            url = pr.get("url", "")
            link = f'<a href="{esc(url)}" target="_blank">#{pr["number"]}</a>' if url else f"#{pr['number']}"
            utype = pr.get("update_type", "?")
            cls = "error" if utype == "security" else "warn"
            rows += (
                f"<tr>"
                f"<td>{esc(pr['_repo'])}</td>"
                f"<td>{link}</td>"
                f"<td>{esc(pr.get('title', '')[:50])}</td>"
                f'<td><span class="status {cls}">{esc(utype)}</span></td>'
                f"<td>{pr.get('age_days', 0)}d</td>"
                f"<td>{pr.get('threshold_days', '?')}d</td>"
                f"</tr>"
            )
        content += f"""<h3>Overdue ({len(overdue)})</h3>
<table><thead><tr><th>Repo</th><th>PR</th><th>Title</th><th>Type</th><th>Age</th><th>Threshold</th></tr></thead>
<tbody>{rows}</tbody></table>"""

    if pending:
        pending.sort(key=lambda p: p.get("age_days", 0), reverse=True)
        rows = ""
        for pr in pending:
            url = pr.get("url", "")
            link = f'<a href="{esc(url)}" target="_blank">#{pr["number"]}</a>' if url else f"#{pr['number']}"
            rows += (
                f"<tr>"
                f"<td>{esc(pr['_repo'])}</td>"
                f"<td>{link}</td>"
                f"<td>{esc(pr.get('title', '')[:50])}</td>"
                f"<td>{esc(pr.get('update_type', '?'))}</td>"
                f"<td>{pr.get('age_days', 0)}d</td>"
                f"</tr>"
            )
        content += f"""<h3>Pending ({len(pending)})</h3>
<table><thead><tr><th>Repo</th><th>PR</th><th>Title</th><th>Type</th><th>Age</th></tr></thead>
<tbody>{rows}</tbody></table>"""

    agg = renovate_data.get("aggregate", renovate_data.get("summary", {}))
    total = agg.get("total_prs", agg.get("total", 0))
    return section_html("deps", "Dependency Updates", total, content, collapsed=True)


def build_sonar_section(sonar_data):
    if not sonar_data:
        return ""

    results = sonar_data.get("results", [sonar_data])

    rows = ""
    for proj in results:
        slug = f"{proj.get('owner', '?')}/{proj.get('repo', '?')}"
        m = proj.get("metrics", {})
        gate = proj.get("gate_status", "UNKNOWN")
        cls = status_class(gate)

        if proj.get("error"):
            rows += f'<tr class="error"><td>{esc(slug)}</td><td colspan="7">Error fetching data</td></tr>'
            continue

        coverage = m.get("coverage", "N/A")
        if isinstance(coverage, (int, float)):
            cov_cls = "ok" if coverage >= 80 else ("warn" if coverage >= 50 else "error")
            coverage_str = f'<span class="status {cov_cls}">{coverage}%</span>'
        else:
            coverage_str = "N/A"

        rows += (
            f'<tr class="{cls}">'
            f"<td>{esc(slug)}</td>"
            f'<td><span class="status {cls}">{esc(status_label(gate))}</span></td>'
            f"<td>{coverage_str}</td>"
            f"<td>{m.get('bugs', 'N/A')}</td>"
            f"<td>{m.get('vulnerabilities', 'N/A')}</td>"
            f"<td>{m.get('code_smells', 'N/A')}</td>"
            f"<td>{m.get('security_hotspots', 'N/A')}</td>"
            f"<td>{m.get('security_rating', 'N/A')}</td>"
            f"</tr>"
        )

    content = f"""<table>
<thead><tr><th>Repository</th><th>Gate</th><th>Coverage</th><th>Bugs</th><th>Vulns</th><th>Smells</th><th>Hotspots</th><th>Security</th></tr></thead>
<tbody>{rows}</tbody>
</table>"""

    failing = [r for r in results if r.get("gate_status") == "ERROR"]
    if failing:
        details = ""
        for proj in failing:
            slug = f"{proj.get('owner', '?')}/{proj.get('repo', '?')}"
            fail_conds = proj.get("failing_conditions", [])
            reasons = ", ".join(c["metric"] + "=" + str(c["value"]) for c in fail_conds[:3])
            details += f"<li><strong>{esc(slug)}</strong> — {esc(reasons)}</li>"
        content = f"<h3>Failing Gates ({len(failing)})</h3><ul>{details}</ul>" + content

    total = sonar_data.get("total_projects", len(results))
    return section_html("sonar", "SonarCloud Quality", total, content, collapsed=True)


CSS = """
:root {
  --bg: #f1f5f9;
  --surface: #ffffff;
  --surface-hover: #f8fafc;
  --border: #e2e8f0;
  --border-subtle: #edf2f7;
  --text: #1e293b;
  --text-muted: #64748b;
  --text-dim: #94a3b8;
  --accent: #3C50E0;
  --accent-hover: #3545C8;
  --accent-bg: rgba(60, 80, 224, 0.08);
  --accent-light: #2d3cc4;
  --ok: #10B981;
  --ok-bg: rgba(16, 185, 129, 0.08);
  --ok-text: #059669;
  --warn: #F59E0B;
  --warn-bg: rgba(245, 158, 11, 0.08);
  --warn-text: #D97706;
  --error: #EF4444;
  --error-bg: rgba(239, 68, 68, 0.08);
  --error-text: #DC2626;
  --neutral: #cbd5e1;
  --neutral-text: #64748b;
  --link: #3C50E0;
  --radius: 12px;
  --radius-sm: 8px;
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.03);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.06), 0 2px 4px rgba(0,0,0,0.04);
  --transition: 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.6;
  padding: 24px 32px; max-width: 1280px; margin: 0 auto;
  min-height: 100vh; -webkit-font-smoothing: antialiased;
}

::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-dim); }

header { margin-bottom: 24px; }
header h1 {
  font-size: 1.6rem; font-weight: 700; color: var(--text); letter-spacing: -0.02em;
}
header .subtitle { color: var(--text-muted); font-size: 0.85rem; margin-top: 4px; }
header .accent-line {
  height: 3px; width: 48px; margin-top: 12px; border-radius: 2px;
  background: var(--accent);
}

a { color: var(--link); text-decoration: none; transition: color var(--transition); }
a:hover { color: var(--accent-light); }

/* --- Health Cards --- */
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 20px; margin-bottom: 24px; }
.card {
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 20px 24px; border-left: 3px solid var(--neutral);
  box-shadow: var(--shadow-sm); transition: box-shadow var(--transition);
}
.card:hover { box-shadow: var(--shadow-md); }
.card.ok { border-left-color: var(--ok); }
.card.error { border-left-color: var(--error); }
.card.warn { border-left-color: var(--warn); }
.card-title {
  font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;
  letter-spacing: 0.08em; font-weight: 600;
}
.card-status { font-size: 1.5rem; font-weight: 700; margin: 6px 0; }
.card.ok .card-status { color: var(--ok-text); }
.card.error .card-status { color: var(--error-text); }
.card.warn .card-status { color: var(--warn-text); }
.card-detail { font-size: 0.8rem; color: var(--text-muted); }

/* --- Nav Bar --- */
.nav-bar {
  display: flex; align-items: center; gap: 4px; flex-wrap: wrap;
  position: sticky; top: 0; z-index: 100;
  padding: 8px 12px; margin-bottom: 20px;
  background: rgba(255, 255, 255, 0.92); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--border); border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
}
.nav-bar a {
  font-size: 0.78rem; font-weight: 500; padding: 6px 12px; border-radius: 6px;
  color: var(--text-muted); text-decoration: none; transition: all var(--transition);
}
.nav-bar a:hover { background: var(--accent-bg); color: var(--accent); }

/* --- Sections --- */
.section {
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  margin-bottom: 16px; scroll-margin-top: 3.5rem;
  box-shadow: var(--shadow-sm);
}
.section summary {
  cursor: pointer; padding: 16px 20px; list-style: none;
  transition: background var(--transition); border-radius: var(--radius);
}
.section summary::-webkit-details-marker { display: none; }
.section summary::before {
  content: ''; display: inline-block; width: 0; height: 0; margin-right: 10px;
  border-left: 5px solid var(--text-dim); border-top: 4px solid transparent; border-bottom: 4px solid transparent;
  transition: transform var(--transition); vertical-align: middle;
}
.section[open] summary::before { transform: rotate(90deg); }
.section summary:hover { background: var(--surface-hover); }
.section summary h2 { display: inline; font-size: 1rem; font-weight: 600; vertical-align: middle; }
.section > :not(summary) { padding: 0 20px 20px; }

.badge {
  background: var(--accent-bg); color: var(--accent); font-size: 0.7rem; font-weight: 600;
  padding: 2px 8px; border-radius: 9999px; vertical-align: middle;
}

h3 { font-size: 0.9rem; font-weight: 600; margin: 20px 0 8px; color: var(--text); }

/* --- Tables --- */
table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 0.82rem; margin-bottom: 16px; }
thead th {
  text-align: left; padding: 12px 16px; color: var(--text-muted); font-weight: 500;
  font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em;
  background: #f8fafc; border-bottom: 1px solid var(--border);
}
thead th:first-child { border-radius: var(--radius-sm) 0 0 0; }
thead th:last-child { border-radius: 0 var(--radius-sm) 0 0; }
td { padding: 14px 16px; border-bottom: 1px solid var(--border-subtle); }
tbody tr { transition: background var(--transition); }
tbody tr:hover { background: #f8fafc; }

/* --- Status Badges --- */
.status {
  display: inline-block; padding: 3px 10px; border-radius: 9999px;
  font-size: 0.72rem; font-weight: 500;
}
.status.ok { background: var(--ok-bg); color: var(--ok-text); }
.status.error { background: var(--error-bg); color: var(--error-text); }
.status.warn { background: var(--warn-bg); color: var(--warn-text); }
.status.neutral { background: #f1f5f9; color: var(--neutral-text); }

/* --- Action Items --- */
.action-items {
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 20px 24px; margin-bottom: 24px; border-left: 3px solid var(--accent);
  box-shadow: var(--shadow-sm);
}
.action-items h3 { margin: 0 0 12px; font-size: 1rem; font-weight: 600; }
.action-items.ok { border-left-color: var(--ok); }
.action-items.ok p { color: var(--ok-text); margin: 0; font-weight: 500; }
.action-items ul { list-style: none; padding: 0; margin: 0; }
.action-items li {
  padding: 8px 10px; border-radius: 6px;
  font-size: 0.82rem; transition: background var(--transition);
  border-bottom: 1px solid var(--border-subtle);
}
.action-items li:last-child { border-bottom: none; }
.action-items li:hover { background: var(--surface-hover); }
.action-items .status { margin-right: 8px; }
.changes-section .changes-meta {
  font-size: 0.8rem; font-weight: 400; color: var(--text-muted); margin-left: 6px;
}
.changes-section p { margin: 0; color: var(--text-muted); font-size: 0.9rem; }

ul { list-style: disc; padding-left: 1.5rem; margin-bottom: 1rem; }
li { margin-bottom: 4px; font-size: 0.85rem; }

/* --- Footer --- */
.footer {
  text-align: center; padding: 24px 0 16px; margin-top: 32px;
  border-top: 1px solid var(--border); color: var(--text-dim); font-size: 0.8rem;
}
.footer span { color: var(--accent); font-weight: 600; }

[data-theme="dark"] {
  --bg: #1A222C;
  --surface: #24303F;
  --surface-hover: #2E3A4A;
  --border: #2E3A47;
  --border-subtle: #333A48;
  --text: #DEE4EE;
  --text-muted: #8A99AF;
  --text-dim: #6B7B93;
  --accent-bg: rgba(60, 80, 224, 0.15);
  --accent-light: #80CAEE;
  --ok-bg: rgba(16, 185, 129, 0.12);
  --ok-text: #34D399;
  --warn-bg: rgba(245, 158, 11, 0.12);
  --warn-text: #FBBF24;
  --error-bg: rgba(239, 68, 68, 0.12);
  --error-text: #F87171;
  --neutral: #333A48;
  --neutral-text: #8A99AF;
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.2), 0 1px 2px rgba(0,0,0,0.15);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.25), 0 2px 4px rgba(0,0,0,0.15);
}
[data-theme="dark"] thead th { background: #2E3A47; }
[data-theme="dark"] tbody tr:hover { background: rgba(255,255,255,0.02); }
[data-theme="dark"] .status.neutral { background: rgba(51,58,72,0.5); }
[data-theme="dark"] .nav-bar { background: rgba(26,34,44,0.92); }

.theme-toggle {
  display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px;
  border-radius: var(--radius-sm); border: 1px solid var(--border); background: var(--surface);
  color: var(--text-muted); font-size: 0.78rem; font-weight: 500;
  cursor: pointer; transition: all var(--transition);
}
.theme-toggle:hover { background: var(--surface-hover); color: var(--text); }
.theme-toggle svg { width: 14px; height: 14px; }

@media (max-width: 768px) {
  body { padding: 16px; }
  .cards { grid-template-columns: repeat(2, 1fr); gap: 12px; }
  table { font-size: 0.72rem; }
  td, th { padding: 8px; }
  header h1 { font-size: 1.25rem; }
  .nav-bar a { font-size: 0.7rem; padding: 4px 8px; }
}
@media (max-width: 480px) {
  .cards { grid-template-columns: 1fr; }
}
"""


def build_repo_status_section(ci_data, prs_data, codecov_data):
    """Build a per-repo status overview grid matching the official DevTools status page.

    Shows CI status, coverage, and open PR count for each repo at a glance.
    """
    ci_by_repo = {}
    if ci_data:
        for repo in ci_data.get("results", []):
            slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
            ci_by_repo[slug] = repo

    pr_count_by_repo = {}
    if prs_data:
        for repo in prs_data.get("results", []):
            slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
            s = repo.get("summary", {})
            pr_count_by_repo[slug] = s.get("total", 0)

    cov_by_repo = {}
    if codecov_data:
        for repo in codecov_data.get("results", []):
            slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"
            cov_by_repo[slug] = repo

    all_slugs = sorted(set(list(ci_by_repo.keys()) + list(pr_count_by_repo.keys()) + list(cov_by_repo.keys())))

    if not all_slugs:
        return ""

    rows = ""
    for slug in all_slugs:
        ci_repo = ci_by_repo.get(slug, {})
        primary = ci_repo.get("primary_ci")
        ci_s = ci_repo.get("summary", {})

        ci_workflow = ci_repo.get("primary_ci", {}).get("workflow", "") if ci_repo.get("primary_ci") else ""
        ci_actions_url = (
            f"https://github.com/{slug}/actions/workflows/{ci_workflow}?query=event%3Aschedule"
            if ci_workflow
            else f"https://github.com/{slug}/actions"
        )

        if primary:
            ci_st = primary.get("status", "unknown")
            ci_cls = "ok" if ci_st == "success" else ("error" if ci_st == "failure" else "neutral")
            ci_label = primary.get("workflow", "CI")
            ci_cell = f'<a href="{esc(ci_actions_url)}" target="_blank"><span class="status {ci_cls}">{esc(ci_label)}</span></a>'
        elif ci_s:
            failing = ci_s.get("failing", 0)
            ci_cls = "ok" if failing == 0 else "error"
            ci_cell = f'<a href="{esc(ci_actions_url)}" target="_blank"><span class="status {ci_cls}">{"Pass" if failing == 0 else "Fail"}</span></a>'
        else:
            ci_cell = f'<a href="{esc(ci_actions_url)}" target="_blank"><span class="status neutral">N/A</span></a>'

        cov_repo = cov_by_repo.get(slug, {})
        coverage = cov_repo.get("coverage")
        codecov_url = f"https://codecov.io/github/{slug}"
        if coverage is not None:
            cov_cls = "ok" if coverage >= 80 else ("warn" if coverage >= 50 else "error")
            cov_cell = (
                f'<a href="{esc(codecov_url)}" target="_blank"><span class="status {cov_cls}">{coverage}%</span></a>'
            )
        else:
            cov_cell = '<span class="status neutral">N/A</span>'

        pr_count = pr_count_by_repo.get(slug, 0)
        pr_cls = "ok" if pr_count <= 3 else ("warn" if pr_count <= 8 else "error")
        prs_url = f"https://github.com/{slug}/pulls?q=sort%3Aupdated-desc+is%3Apr+is%3Aopen+-is%3Adraft"
        pr_cell = f'<a href="{esc(prs_url)}" target="_blank"><span class="status {pr_cls}">{pr_count} PRs</span></a>'

        owner_repo = slug.split("/", 1)
        repo_name = owner_repo[1] if len(owner_repo) > 1 else slug
        repo_url = f"https://github.com/{slug}"
        rows += (
            f"<tr>"
            f'<td><a href="{esc(repo_url)}" target="_blank">{esc(repo_name)}</a></td>'
            f"<td>{ci_cell}</td>"
            f"<td>{cov_cell}</td>"
            f"<td>{pr_cell}</td>"
            f"</tr>"
        )

    content = f"""<table>
<thead><tr><th>Repository</th><th>CI Status</th><th>Coverage</th><th>Open PRs</th></tr></thead>
<tbody>{rows}</tbody>
</table>"""

    return section_html("repo-status", "Repository Status", len(all_slugs), content)


def build_codecov_section(codecov_data):
    """Build the Code Coverage section from Codecov data."""
    if not codecov_data:
        return ""

    results = codecov_data.get("results", [])
    if not results:
        return ""

    results_sorted = sorted(results, key=lambda r: r.get("coverage") or 0)

    rows = ""
    for repo in results_sorted:
        slug = f"{repo.get('owner', '?')}/{repo.get('repo', '?')}"

        codecov_url = f"https://codecov.io/github/{slug}"
        repo_url = f"https://github.com/{slug}"

        if repo.get("error"):
            rows += f'<tr class="error"><td><a href="{esc(repo_url)}" target="_blank">{esc(slug)}</a></td><td colspan="4">Error fetching data</td></tr>'
            continue

        coverage = repo.get("coverage")
        if coverage is not None:
            cov_cls = "ok" if coverage >= 80 else ("warn" if coverage >= 50 else "error")
            coverage_str = (
                f'<a href="{esc(codecov_url)}" target="_blank"><span class="status {cov_cls}">{coverage}%</span></a>'
            )
        else:
            coverage_str = '<span class="status neutral">N/A</span>'

        lines = repo.get("lines", 0)
        hits = repo.get("hits", 0)
        misses = repo.get("misses", 0)

        rows += (
            f"<tr>"
            f'<td><a href="{esc(repo_url)}" target="_blank">{esc(slug)}</a></td>'
            f"<td>{coverage_str}</td>"
            f"<td>{lines:,}</td>"
            f"<td>{hits:,}</td>"
            f"<td>{misses:,}</td>"
            f"</tr>"
        )

    content = f"""<table>
<thead><tr><th>Repository</th><th>Coverage</th><th>Lines</th><th>Hits</th><th>Misses</th></tr></thead>
<tbody>{rows}</tbody>
</table>"""

    agg = codecov_data.get("aggregate", {})
    below_50 = agg.get("repos_below_50", 0)
    if below_50 > 0:
        low_cov = [r for r in results if not r.get("error") and r.get("coverage") is not None and r["coverage"] < 50]
        if low_cov:
            details = "".join(
                f"<li><strong>{esc(r.get('owner', '?'))}/{esc(r.get('repo', '?'))}</strong> — {r['coverage']}%</li>"
                for r in low_cov
            )
            content = f"<h3>Low Coverage ({below_50} repos below 50%)</h3><ul>{details}</ul>" + content

    total = codecov_data.get("total_repos", len(results))
    return section_html("codecov", "Code Coverage (Codecov)", total, content, collapsed=True)


def build_correlation_section(correlation_data):
    if not correlation_data:
        return ""

    summary = correlation_data.get("summary", {})
    clusters = correlation_data.get("clusters", [])
    isolated = correlation_data.get("isolated", [])

    if summary.get("total_failures", 0) == 0:
        return ""

    content = ""

    if clusters:
        for _i, cluster in enumerate(clusters):
            ctype = cluster.get("type", "unknown")
            cls = "error" if ctype == "dependency" else ("warn" if ctype == "temporal" else "neutral")
            type_label = {"temporal": "Time Cluster", "shared_job": "Shared Job", "dependency": "Dependency Link"}.get(
                ctype,
                ctype,
            )

            repos_html = ", ".join(esc(r) for r in cluster.get("repos", []))
            wf_rows = ""
            for wf in cluster.get("workflows", [])[:5]:
                url = wf.get("url", "")
                link = (
                    f'<a href="{esc(url)}" target="_blank">{esc(wf.get("workflow", ""))}</a>'
                    if url
                    else esc(wf.get("workflow", ""))
                )
                wf_rows += f"<tr><td>{esc(wf.get('repo', ''))}</td><td>{link}</td></tr>"

            dep_html = ""
            dep_pr = cluster.get("dependency_pr")
            if dep_pr:
                dep_url = dep_pr.get("url", "")
                dep_link = (
                    f'<a href="{esc(dep_url)}" target="_blank">#{dep_pr.get("number", "")}</a>'
                    if dep_url
                    else f"#{dep_pr.get('number', '')}"
                )
                dep_html = f'<p style="margin-top:0.5rem"><strong>Trigger:</strong> {dep_link} — {esc(dep_pr.get("title", "")[:60])}</p>'

            content += f"""<div style="margin-bottom:1rem; padding:0.75rem; border-left:3px solid var(--{cls}); background:var(--{cls}-bg); border-radius:4px;">
<p><span class="status {cls}">{type_label}</span> <strong>{esc(cluster.get("description", ""))}</strong></p>
<p style="color:var(--text-muted); font-size:0.85rem;">Likely cause: {esc(cluster.get("likely_cause", "Unknown"))}</p>
<p style="font-size:0.85rem;">Repos: {repos_html}</p>
{dep_html}
<details><summary style="font-size:0.8rem; color:var(--text-muted); cursor:pointer;">Affected workflows</summary>
<table><thead><tr><th>Repo</th><th>Workflow</th></tr></thead><tbody>{wf_rows}</tbody></table>
</details>
</div>"""

    if isolated:
        rows = ""
        for f in isolated:
            url = f.get("url", "")
            link = (
                f'<a href="{esc(url)}" target="_blank">{esc(f.get("workflow", ""))}</a>'
                if url
                else esc(f.get("workflow", ""))
            )
            jobs = ", ".join(f.get("failing_jobs", [])) or "-"
            flaky_tag = ' <span class="status warn">flaky</span>' if f.get("is_flaky") else ""
            rows += f"<tr><td>{esc(f.get('repo', ''))}</td><td>{link}{flaky_tag}</td><td>{esc(jobs)}</td></tr>"

        content += f"""<h3>Isolated Failures ({len(isolated)})</h3>
<table><thead><tr><th>Repo</th><th>Workflow</th><th>Failing Jobs</th></tr></thead>
<tbody>{rows}</tbody></table>"""

    total_failures = summary.get("total_failures", 0)
    cluster_count = len(clusters)
    content = (
        f'<p style="color:var(--text-muted); font-size:0.85rem; margin-bottom:1rem;">{cluster_count} correlated cluster(s) across {total_failures} total failure(s).</p>'
        + content
    )
    return section_html("correlation", "Failure Correlation", f"{cluster_count} clusters", content)


TOOLBAR_CSS = """
.toolbar {
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap;
  gap: 12px; margin-bottom: 20px; padding: 10px 16px;
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
}
.toolbar-left { display: flex; align-items: center; gap: 12px; }
.toolbar-right { display: flex; align-items: center; gap: 16px; font-size: 0.78rem; color: var(--text-muted); }
.btn {
  display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px;
  border-radius: var(--radius-sm); border: 1px solid var(--border); background: var(--surface);
  color: var(--text); font-size: 0.82rem; font-weight: 500;
  cursor: pointer; transition: all var(--transition);
}
.btn:hover { background: var(--surface-hover); border-color: var(--text-dim); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn-primary:hover { background: var(--accent-hover); border-color: var(--accent-hover); }
.btn-primary:disabled { background: var(--accent); }
.live-dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--ok); display: inline-block;
  animation: pulse 2s ease-in-out infinite;
}
.live-dot.fetching { background: var(--warn); }
.live-dot.error { background: var(--error); animation: none; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
#refresh-status { font-size: 0.78rem; color: var(--text-muted); }
#rate-limit { font-size: 0.72rem; color: var(--text-dim); }
"""

TOOLBAR_JS = """
const REPO = 'ansible/team-devtools';
const WORKFLOW = 'guardian-daily.yml';
const MAX_DAILY_TRIGGERS = 12;
const AUTO_REFRESH_MS = 30 * 60 * 1000;
const GH_TOKEN = '%GH_TOKEN%';

const REPOS = %REPOS_JSON%;

async function ghApi(endpoint) {
  const opts = {headers: {'Accept': 'application/vnd.github+json'}};
  if (GH_TOKEN) opts.headers['Authorization'] = 'Bearer ' + GH_TOKEN;
  const r = await fetch('https://api.github.com/' + endpoint, opts);
  if (!r.ok) return null;
  return r.json();
}

async function countTodayTriggers() {
  const today = new Date().toISOString().split('T')[0];
  const data = await ghApi(
    'repos/' + REPO + '/actions/workflows/' + WORKFLOW + '/runs?per_page=50&created=>' + today
  );
  if (!data || !data.workflow_runs) return 0;
  return data.workflow_runs.filter(r => r.event === 'workflow_dispatch').length;
}

async function updateRateLimit() {
  const count = await countTodayTriggers();
  const el = document.getElementById('rate-limit');
  if (el) el.textContent = count + '/' + MAX_DAILY_TRIGGERS + ' refreshes today';
  const btn = document.getElementById('refresh-btn');
  if (btn && count >= MAX_DAILY_TRIGGERS) {
    btn.disabled = true;
    btn.title = 'Daily limit reached';
  }
  return count;
}

async function triggerRefresh() {
  const btn = document.getElementById('refresh-btn');
  const status = document.getElementById('refresh-status');
  if (!GH_TOKEN) { status.textContent = 'No token configured'; return; }

  const count = await countTodayTriggers();
  if (count >= MAX_DAILY_TRIGGERS) { status.textContent = 'Daily limit reached (' + MAX_DAILY_TRIGGERS + ')'; return; }

  btn.disabled = true;
  status.textContent = 'Triggering full scan...';

  try {
    const r = await fetch('https://api.github.com/repos/' + REPO + '/actions/workflows/' + WORKFLOW + '/dispatches', {
      method: 'POST',
      headers: {'Authorization': 'Bearer ' + GH_TOKEN, 'Accept': 'application/vnd.github+json'},
      body: JSON.stringify({ref: 'main'})
    });
    if (r.status === 204) {
      status.textContent = 'Scan triggered — dashboard will update in ~3 min';
      setTimeout(() => location.reload(), 180000);
    } else {
      status.textContent = 'Failed (HTTP ' + r.status + ')';
    }
  } catch (e) {
    status.textContent = 'Error: ' + e.message;
  }
  setTimeout(() => { btn.disabled = false; updateRateLimit(); }, 5000);
}

async function fetchLiveStatus() {
  const dot = document.getElementById('live-dot');
  const liveClockEl = document.getElementById('live-time');
  if (dot) dot.className = 'live-dot fetching';

  let ciOk = 0, ciFail = 0;
  for (const repo of REPOS) {
    try {
      const data = await ghApi('repos/' + repo.owner + '/' + repo.repo + '/actions/runs?per_page=1&branch=' + (repo.default_branch || 'main'));
      if (data && data.workflow_runs && data.workflow_runs.length > 0) {
        const run = data.workflow_runs[0];
        if (run.conclusion === 'failure') ciFail++;
        else if (run.conclusion === 'success') ciOk++;
      }
    } catch(e) {}
  }

  const ciCard = document.querySelector('#live-ci-count');
  if (ciCard) ciCard.textContent = ciFail + ' failing, ' + ciOk + ' passing';

  if (dot) dot.className = 'live-dot';
  if (liveClockEl) liveClockEl.textContent = 'Live: ' + new Date().toLocaleTimeString();
}

document.addEventListener('DOMContentLoaded', () => {
  updateRateLimit();
  if (GH_TOKEN) fetchLiveStatus();
  setInterval(() => { if (GH_TOKEN) fetchLiveStatus(); }, AUTO_REFRESH_MS);
});
"""


def generate_dashboard(
    prs_data,
    ci_data,
    renovate_data,
    sonar_data,
    correlation_data=None,
    codecov_data=None,
    security_audit_data=None,
    changes_data=None,
    gh_token="",
) -> str:
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")

    repos_list = []
    if ci_data:
        for repo in ci_data.get("results", []):
            repos_list.append(
                {
                    "owner": repo.get("owner", ""),
                    "repo": repo.get("repo", ""),
                    "default_branch": repo.get("branch", "main"),
                },
            )

    js = TOOLBAR_JS.replace("%GH_TOKEN%", esc(gh_token)).replace(
        "%REPOS_JSON%",
        json.dumps(repos_list),
    )

    health_cards = build_health_cards(prs_data, ci_data, renovate_data, sonar_data, codecov_data, security_audit_data)
    changes_section = build_changes_section(changes_data)
    action_items = build_action_items(prs_data, ci_data, renovate_data, sonar_data)
    repo_status_section = build_repo_status_section(ci_data, prs_data, codecov_data)
    ci_section = build_ci_section(ci_data)
    correlation_section = build_correlation_section(correlation_data)
    pr_section = build_pr_section(prs_data)
    codecov_section = build_codecov_section(codecov_data)
    renovate_section = build_renovate_section(renovate_data)
    sonar_section = build_sonar_section(sonar_data)

    section_list = [
        ("repo-status", "Repos", repo_status_section),
        ("ci", "CI", ci_section),
        ("correlation", "Correlation", correlation_section),
        ("prs", "PRs", pr_section),
        ("codecov", "Coverage", codecov_section),
        ("deps", "Dependencies", renovate_section),
        ("sonar", "SonarCloud", sonar_section),
    ]

    nav_links = "".join(f'<a href="#{sid}">{label}</a>' for sid, label, html in section_list if html)
    nav_html = f'<nav class="nav-bar">{nav_links}</nav>' if nav_links else ""

    sections = "\n".join(html for _, _, html in section_list if html)

    toolbar_html = """<div class="toolbar">
  <div class="toolbar-left">
    <button class="btn btn-primary" id="refresh-btn" onclick="triggerRefresh()">Refresh Data</button>
    <span id="refresh-status"></span>
  </div>
  <div class="toolbar-right">
    <span><span class="live-dot" id="live-dot"></span> <span id="live-time">Live: --</span></span>
    <span id="live-ci-count"></span>
    <span id="rate-limit">--/12 refreshes today</span>
    <button class="theme-toggle" id="theme-toggle" onclick="toggleTheme()">
      <svg id="theme-icon-sun" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m8.66-13.66l-.71.71M4.05 19.95l-.71.71M21 12h-1M4 12H3m16.66 7.66l-.71-.71M4.05 4.05l-.71-.71M16 12a4 4 0 11-8 0 4 4 0 018 0z"/></svg>
      <svg id="theme-icon-moon" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" style="display:none"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"/></svg>
      <span id="theme-label">Dark</span>
    </button>
  </div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Guardian Dashboard — Ansible Devtools</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}
{TOOLBAR_CSS}</style>
<script>
(function(){{var t=localStorage.getItem('guardian-theme');if(t)document.documentElement.setAttribute('data-theme',t);}})();
</script>
</head>
<body>

<header>
  <h1>Guardian Dashboard</h1>
  <p class="subtitle">Ansible Devtools — Full scan: {esc(now_str)}</p>
  <div class="accent-line"></div>
</header>

{toolbar_html}

{nav_html}

{health_cards}

{changes_section}

{action_items}

{sections}

<footer class="footer">
  Powered by <span>td-guardian</span>
</footer>

<script>{js}</script>
<script>
function toggleTheme() {{
  var html = document.documentElement;
  var isDark = html.getAttribute('data-theme') === 'dark';
  if (isDark) {{
    html.removeAttribute('data-theme');
    localStorage.setItem('guardian-theme', '');
  }} else {{
    html.setAttribute('data-theme', 'dark');
    localStorage.setItem('guardian-theme', 'dark');
  }}
  updateThemeUI();
}}
function updateThemeUI() {{
  var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  var sun = document.getElementById('theme-icon-sun');
  var moon = document.getElementById('theme-icon-moon');
  var label = document.getElementById('theme-label');
  if (sun) sun.style.display = isDark ? 'none' : 'block';
  if (moon) moon.style.display = isDark ? 'block' : 'none';
  if (label) label.textContent = isDark ? 'Light' : 'Dark';
}}
document.addEventListener('DOMContentLoaded', updateThemeUI);
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Guardian HTML dashboard")
    parser.add_argument("--prs", help="PR data JSON file")
    parser.add_argument("--ci", help="CI status JSON file")
    parser.add_argument("--renovate", help="Renovate/dependency PR JSON file")
    parser.add_argument("--sonar", help="SonarCloud quality gate JSON file")
    parser.add_argument("--codecov", help="Codecov coverage JSON file")
    parser.add_argument("--correlation", help="Failure correlation JSON file")
    parser.add_argument(
        "--security-audit",
        dest="security_audit",
        help="Full security audit JSON file (from convert_audit.py)",
    )
    parser.add_argument("--changes", help="Since-last-check delta JSON (from diff_snapshots.py)")
    parser.add_argument(
        "--gh-token",
        help="Optional GitHub token for local dashboard refresh button only (never embed in Pages)",
    )
    parser.add_argument("--output", "-o", default="docs/index.html", help="Output HTML file (default: docs/index.html)")
    args = parser.parse_args()

    prs_data = load_json_safe(args.prs)
    ci_data = load_json_safe(args.ci)
    renovate_data = load_json_safe(args.renovate)
    sonar_data = load_json_safe(args.sonar)
    codecov_data = load_json_safe(args.codecov)
    correlation_data = load_json_safe(args.correlation)
    security_audit_data = load_json_safe(args.security_audit)
    changes_data = load_json_safe(args.changes)

    if not any([prs_data, ci_data, renovate_data, sonar_data, codecov_data, security_audit_data]):
        print("ERROR: No data files provided or loadable", file=sys.stderr)
        sys.exit(1)

    # Do not read GUARDIAN_GH_TOKEN — Pages must not embed PATs.
    gh_token = args.gh_token or ""
    html = generate_dashboard(
        prs_data,
        ci_data,
        renovate_data,
        sonar_data,
        correlation_data,
        codecov_data,
        security_audit_data,
        changes_data,
        gh_token,
    )

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        f.write(html)

    print(f"Dashboard written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
