#!/usr/bin/env python3
"""Convert supply-chain audit cache into a single JSON for the Guardian dashboard.

Reads findings.json, findings_summary.json, and recommendations.json from
an audit cache directory and outputs a combined JSON object.

Usage:
    python3 scripts/convert_audit.py --cache-dir .supply-chain-audit/cache/<hash> \
        -o reports/security-audit.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

CATEGORY_LABELS = {
    "unsigned_commit": "Unsigned Commits",
    "github_web_signed": "GitHub-Web-Signed Commits",
    "orphan_commit": "Orphan Commits (No PR)",
    "bypassed_ci": "Bypassed CI",
    "post_merge_push": "Post-Merge Pushes",
    "replicated_message": "Replicated Commit Messages",
    "suspicious_dep_timing": "Suspicious Dependency Timing",
    "yanked_version": "Yanked/Deleted Versions",
    "protection_changed": "Branch Protection Changes",
    "post_approval_commit": "Post-Approval Commits",
    "bot_only_approval": "Bot-Only Approvals",
    "cooldown_violated": "Renovate Cooldown Violations",
    "known_vulnerability": "Known Vulnerabilities (OSV.dev)",
    "self_approved": "Self-Approved PRs",
}


def load_json(path: Path) -> dict | list | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"WARN: Could not load {path}: {e}", file=sys.stderr)
        return None


def _group_vuln_findings(findings: list[dict]) -> list[dict]:
    """Group vulnerability findings by (package, vuln_id) across repos.

    Non-vulnerability findings are passed through unchanged.
    Vulnerability findings are collapsed: one entry per unique
    (package, vuln_id) with a ``repos`` list showing which repos
    are affected.
    """
    grouped = []
    vuln_map: dict[tuple[str, str], dict] = {}

    for f in findings:
        category = f.get("category", "")
        if category != "known_vulnerability":
            grouped.append(f)
            continue

        evidence = f.get("evidence", {})
        pkg = evidence.get("package", "")
        vuln_id = evidence.get("vuln_id", "")
        if not pkg or not vuln_id:
            grouped.append(f)
            continue

        key = (pkg.lower(), vuln_id)

        if key not in vuln_map:
            entry = dict(f)
            entry["repos"] = [f.get("repo", "")]
            vuln_map[key] = entry
        else:
            repo = f.get("repo", "")
            if repo not in vuln_map[key]["repos"]:
                vuln_map[key]["repos"].append(repo)

    grouped.extend(vuln_map.values())
    return grouped


def convert(cache_dir: str) -> dict:
    base = Path(cache_dir)

    summary = load_json(base / "findings_summary.json")
    findings = load_json(base / "findings.json")
    recommendations = load_json(base / "recommendations.json")

    if not summary:
        print("ERROR: findings_summary.json is required", file=sys.stderr)
        sys.exit(1)

    raw_findings: list[dict] = findings if isinstance(findings, list) else []
    findings_grouped = _group_vuln_findings(raw_findings)

    vuln_count_raw = sum(
        1 for f in raw_findings
        if f.get("category", f.get("type", "")) in ("vulnerability", "known_vulnerability")
    )
    vuln_count_grouped = sum(
        1 for f in findings_grouped
        if f.get("category", f.get("type", "")) in ("vulnerability", "known_vulnerability")
    )
    if vuln_count_raw != vuln_count_grouped:
        print(
            f"  Dedup: {vuln_count_raw} vulnerability findings -> {vuln_count_grouped} unique",
            file=sys.stderr,
        )

    return {
        "audit_window": summary.get("audit_window", ""),
        "repos_audited": summary.get("repos_audited", []),
        "total_findings": summary.get("total_findings", 0),
        "total_findings_deduped": len(findings_grouped),
        "risk_totals": summary.get("risk_totals", {}),
        "category_breakdown": summary.get("category_breakdown", []),
        "repo_breakdown": summary.get("repo_breakdown", []),
        "findings": raw_findings,
        "findings_grouped": findings_grouped,
        "recommendations": recommendations or [],
        "category_labels": CATEGORY_LABELS,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert audit cache to Guardian dashboard JSON",
    )
    parser.add_argument(
        "--cache-dir",
        required=True,
        help="Path to audit cache directory containing findings*.json",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file (default: stdout)",
    )
    args = parser.parse_args()

    data = convert(args.cache_dir)

    output = json.dumps(data, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
