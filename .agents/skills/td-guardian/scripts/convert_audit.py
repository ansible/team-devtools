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


def convert(cache_dir: str) -> dict:
    base = Path(cache_dir)

    summary = load_json(base / "findings_summary.json")
    findings = load_json(base / "findings.json")
    recommendations = load_json(base / "recommendations.json")

    if not summary:
        print("ERROR: findings_summary.json is required", file=sys.stderr)
        sys.exit(1)

    result = {
        "audit_window": summary.get("audit_window", ""),
        "repos_audited": summary.get("repos_audited", []),
        "total_findings": summary.get("total_findings", 0),
        "risk_totals": summary.get("risk_totals", {}),
        "category_breakdown": summary.get("category_breakdown", []),
        "repo_breakdown": summary.get("repo_breakdown", []),
        "findings": findings or [],
        "recommendations": recommendations or [],
        "category_labels": CATEGORY_LABELS,
    }

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert audit cache to Guardian dashboard JSON"
    )
    parser.add_argument(
        "--cache-dir",
        required=True,
        help="Path to audit cache directory containing findings*.json",
    )
    parser.add_argument(
        "--output", "-o",
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
