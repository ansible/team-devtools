#!/usr/bin/env python3
"""
Compare Guardian fetch JSON against a previous compact snapshot.

Produces reports/changes.json ("what changed since last check") and optionally
rotates the baseline via --write-previous.

Usage:
    python3 scripts/diff_snapshots.py \\
      --prs reports/open-prs.json \\
      --ci reports/ci-status.json \\
      --renovate reports/renovate-prs.json \\
      --previous reports/previous-snapshot.json \\
      --output reports/changes.json \\
      --write-previous reports/previous-snapshot.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def load_json_safe(path):
    if not path:
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        print(f"WARN: Could not parse {path}: {e}", file=sys.stderr)
        return None


def _repo_results(data):
    if not data:
        return []
    if "results" in data:
        return data["results"]
    if data.get("owner") and data.get("repo"):
        return [data]
    return []


def build_snapshot(prs_data, ci_data, renovate_data, codecov_data=None, sonar_data=None):
    """Normalize current fetch JSON into a compact comparable snapshot."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    workflows = {}
    for repo in _repo_results(ci_data):
        owner = repo.get("owner", "?")
        name = repo.get("repo", "?")
        slug = f"{owner}/{name}"
        for wf in repo.get("workflows", []):
            key = f"{slug}|{wf.get('name', '?')}"
            workflows[key] = {
                "repo": slug,
                "workflow": wf.get("name", "?"),
                "conclusion": wf.get("conclusion"),
                "is_flaky": bool(wf.get("is_flaky")),
                "url": wf.get("url", ""),
            }

    prs = {}
    for repo in _repo_results(prs_data):
        owner = repo.get("owner", "?")
        name = repo.get("repo", "?")
        slug = f"{owner}/{name}"
        for pr in repo.get("prs", []):
            number = pr.get("number")
            if number is None:
                continue
            key = f"{slug}#{number}"
            prs[key] = {
                "repo": slug,
                "number": number,
                "category": pr.get("category"),
                "title": pr.get("title", ""),
                "url": pr.get("url", ""),
                "age_days": pr.get("age_days"),
            }

    renovate = {}
    for repo in _repo_results(renovate_data):
        owner = repo.get("owner", "?")
        name = repo.get("repo", "?")
        slug = f"{owner}/{name}"
        for pr in repo.get("prs", []):
            number = pr.get("number")
            if number is None:
                continue
            key = f"{slug}#{number}"
            renovate[key] = {
                "repo": slug,
                "number": number,
                "is_overdue": bool(pr.get("is_overdue")),
                "update_type": pr.get("update_type"),
                "title": pr.get("title", ""),
                "url": pr.get("url", ""),
                "age_days": pr.get("age_days"),
            }

    def agg(data, *keys):
        if not data:
            return {k: 0 for k in keys}
        src = data.get("aggregate", data.get("summary", {}))
        return {k: src.get(k, 0) for k in keys}

    snapshot = {
        "generated_at": now,
        "workflows": workflows,
        "prs": prs,
        "renovate": renovate,
        "aggregates": {
            "ci": agg(ci_data, "failing", "flaky", "passing"),
            "prs": agg(prs_data, "total_prs", "ready_to_merge", "stale", "blocked", "needs_review"),
            "renovate": agg(renovate_data, "total_prs", "overdue", "security", "major", "minor"),
        },
    }

    if codecov_data:
        snapshot["aggregates"]["codecov"] = agg(
            codecov_data, "average_coverage", "repos_below_50", "repos_above_80"
        )
    if sonar_data:
        snapshot["aggregates"]["sonar"] = agg(
            sonar_data, "gate_error", "gate_ok", "total_vulnerabilities"
        )

    return snapshot


def _entity(item, extra=None):
    out = dict(item)
    if extra:
        out.update(extra)
    return out


def diff_snapshots(previous, current):
    """Compute structured deltas between two compact snapshots."""
    if not previous:
        return {
            "generated_at": (current or {}).get("generated_at"),
            "compared_to": None,
            "has_baseline": False,
            "ci": {"new_failures": [], "resolved_failures": [], "new_flaky": []},
            "prs": {
                "became_stale": [],
                "became_ready": [],
                "newly_opened": [],
                "closed_or_merged": [],
            },
            "renovate": {"newly_overdue": [], "no_longer_overdue": []},
            "summary": {
                "new_failures": 0,
                "resolved_failures": 0,
                "new_flaky": 0,
                "became_stale": 0,
                "became_ready": 0,
                "newly_opened": 0,
                "closed_or_merged": 0,
                "newly_overdue": 0,
                "no_longer_overdue": 0,
            },
            "aggregates": {
                "previous": None,
                "current": (current or {}).get("aggregates"),
            },
        }

    prev = previous
    curr = current or {}

    prev_wf = prev.get("workflows", {})
    curr_wf = curr.get("workflows", {})
    new_failures = []
    resolved_failures = []
    new_flaky = []

    for key, wf in curr_wf.items():
        was = prev_wf.get(key)
        is_fail = wf.get("conclusion") == "failure" and not wf.get("is_flaky")
        was_fail = (
            was is not None
            and was.get("conclusion") == "failure"
            and not was.get("is_flaky")
        )
        if is_fail and not was_fail:
            new_failures.append(_entity(wf))
        if wf.get("is_flaky") and not (was and was.get("is_flaky")):
            new_flaky.append(_entity(wf))

    for key, wf in prev_wf.items():
        was_fail = wf.get("conclusion") == "failure" and not wf.get("is_flaky")
        now = curr_wf.get(key)
        now_fail = (
            now is not None
            and now.get("conclusion") == "failure"
            and not now.get("is_flaky")
        )
        if was_fail and not now_fail:
            resolved_failures.append(_entity(wf, {
                "resolved_to": now.get("conclusion") if now else "gone",
            }))

    prev_prs = prev.get("prs", {})
    curr_prs = curr.get("prs", {})
    became_stale = []
    became_ready = []
    newly_opened = []
    closed_or_merged = []

    for key, pr in curr_prs.items():
        was = prev_prs.get(key)
        if was is None:
            newly_opened.append(_entity(pr))
            continue
        if pr.get("category") == "stale" and was.get("category") != "stale":
            became_stale.append(_entity(pr, {"previous_category": was.get("category")}))
        if pr.get("category") == "ready_to_merge" and was.get("category") != "ready_to_merge":
            became_ready.append(_entity(pr, {"previous_category": was.get("category")}))

    for key, pr in prev_prs.items():
        if key not in curr_prs:
            closed_or_merged.append(_entity(pr))

    prev_ren = prev.get("renovate", {})
    curr_ren = curr.get("renovate", {})
    newly_overdue = []
    no_longer_overdue = []

    for key, pr in curr_ren.items():
        was = prev_ren.get(key)
        if pr.get("is_overdue") and not (was and was.get("is_overdue")):
            newly_overdue.append(_entity(pr))

    for key, pr in prev_ren.items():
        now = curr_ren.get(key)
        if pr.get("is_overdue") and not (now and now.get("is_overdue")):
            no_longer_overdue.append(_entity(pr, {
                "reason": "resolved_or_closed" if now is None else "no_longer_overdue",
            }))

    summary = {
        "new_failures": len(new_failures),
        "resolved_failures": len(resolved_failures),
        "new_flaky": len(new_flaky),
        "became_stale": len(became_stale),
        "became_ready": len(became_ready),
        "newly_opened": len(newly_opened),
        "closed_or_merged": len(closed_or_merged),
        "newly_overdue": len(newly_overdue),
        "no_longer_overdue": len(no_longer_overdue),
    }

    return {
        "generated_at": curr.get("generated_at"),
        "compared_to": prev.get("generated_at"),
        "has_baseline": bool(previous),
        "ci": {
            "new_failures": new_failures,
            "resolved_failures": resolved_failures,
            "new_flaky": new_flaky,
        },
        "prs": {
            "became_stale": became_stale,
            "became_ready": became_ready,
            "newly_opened": newly_opened,
            "closed_or_merged": closed_or_merged,
        },
        "renovate": {
            "newly_overdue": newly_overdue,
            "no_longer_overdue": no_longer_overdue,
        },
        "summary": summary,
        "aggregates": {
            "previous": prev.get("aggregates"),
            "current": curr.get("aggregates"),
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Diff Guardian snapshots for since-last-check deltas"
    )
    parser.add_argument("--prs", help="Current open PRs JSON")
    parser.add_argument("--ci", help="Current CI status JSON")
    parser.add_argument("--renovate", help="Current renovate PRs JSON")
    parser.add_argument("--codecov", help="Current codecov JSON (optional)")
    parser.add_argument("--sonar", help="Current sonar JSON (optional)")
    parser.add_argument(
        "--previous",
        default="reports/previous-snapshot.json",
        help="Previous compact snapshot (default: reports/previous-snapshot.json)",
    )
    parser.add_argument(
        "--output", "-o",
        default="reports/changes.json",
        help="Write changes JSON (default: reports/changes.json)",
    )
    parser.add_argument(
        "--write-previous",
        help="Write the new compact snapshot to this path (rotate baseline)",
    )
    parser.add_argument(
        "--snapshot-out",
        help="Alias for --write-previous",
    )
    args = parser.parse_args()

    if not any([args.prs, args.ci, args.renovate]):
        parser.error("Provide at least one of --prs, --ci, --renovate")

    prs_data = load_json_safe(args.prs)
    ci_data = load_json_safe(args.ci)
    renovate_data = load_json_safe(args.renovate)
    codecov_data = load_json_safe(args.codecov)
    sonar_data = load_json_safe(args.sonar)

    if not any([prs_data, ci_data, renovate_data]):
        print("ERROR: No current data files loadable", file=sys.stderr)
        sys.exit(1)

    current = build_snapshot(
        prs_data, ci_data, renovate_data, codecov_data, sonar_data
    )
    previous = load_json_safe(args.previous)
    if previous is None and args.previous:
        print(
            f"INFO: No previous snapshot at {args.previous} — first-run baseline",
            file=sys.stderr,
        )

    changes = diff_snapshots(previous, current)

    out_path = args.output
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(changes, f, indent=2)
            f.write("\n")
        print(f"Changes written to {out_path}", file=sys.stderr)
    else:
        json.dump(changes, sys.stdout, indent=2)
        print(file=sys.stdout)

    snapshot_path = args.write_previous or args.snapshot_out
    if snapshot_path:
        os.makedirs(os.path.dirname(os.path.abspath(snapshot_path)) or ".", exist_ok=True)
        with open(snapshot_path, "w") as f:
            json.dump(current, f, indent=2)
            f.write("\n")
        print(f"Snapshot written to {snapshot_path}", file=sys.stderr)

    summary = changes["summary"]
    total = sum(summary.values())
    print(
        f"Delta summary: {total} change(s) "
        f"(new_failures={summary['new_failures']}, "
        f"resolved={summary['resolved_failures']}, "
        f"became_stale={summary['became_stale']}, "
        f"newly_overdue={summary['newly_overdue']})",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
