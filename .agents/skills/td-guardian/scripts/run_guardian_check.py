#!/usr/bin/env python3
"""
Guardian shift orchestrator — runs all fetch scripts and generates reports.

Modes:
    daily   - PRs + CI + Renovate checks, consolidated dashboard (run 2x/day)
    weekly  - Daily + SonarCloud quality gates (run Monday for security audit)
    handoff - Weekly + Jira handoff template (run at end of sprint)

Usage:
    python3 .agents/skills/td-guardian/scripts/run_guardian_check.py --mode daily
    python3 .agents/skills/td-guardian/scripts/run_guardian_check.py --mode weekly
    python3 .agents/skills/td-guardian/scripts/run_guardian_check.py --mode handoff
    python3 .agents/skills/td-guardian/scripts/run_guardian_check.py --mode daily --repos-file .agents/skills/td-guardian/config/repos.json
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone


SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(os.path.dirname(SCRIPTS_DIR), "reports")
DEFAULT_REPOS_FILE = os.path.join(os.path.dirname(SCRIPTS_DIR), "config", "repos.json")
DEFAULT_SONAR_CONFIG = os.path.join(os.path.dirname(SCRIPTS_DIR), "config", "sonar.json")
DEFAULT_CODECOV_CONFIG = os.path.join(os.path.dirname(SCRIPTS_DIR), "config", "codecov.json")


def run_script(script_name, args, output_file):
    """Run a fetch script and save its JSON output to a file."""
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    cmd = [sys.executable, script_path] + args

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Running: {script_name}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        print(f"ERROR: {script_name} timed out after 10 minutes", file=sys.stderr)
        return False
    except FileNotFoundError:
        print(f"ERROR: Script not found: {script_path}", file=sys.stderr)
        return False

    if result.returncode != 0:
        print(f"ERROR: {script_name} failed (exit {result.returncode})", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return False

    if result.stderr:
        print(result.stderr, file=sys.stderr)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"ERROR: {script_name} produced invalid JSON", file=sys.stderr)
        return False

    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    print(f"Saved: {output_file}", file=sys.stderr)
    return True


def generate_report(mode, args, output_file):
    """Run generate_report.py with the given mode and arguments."""
    script_path = os.path.join(SCRIPTS_DIR, "generate_report.py")
    cmd = [sys.executable, script_path, mode] + args + ["--output", output_file]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print(f"ERROR: Report generation timed out", file=sys.stderr)
        return False

    if result.returncode != 0:
        print(f"ERROR: Report generation failed for mode '{mode}'", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return False

    if result.stderr:
        print(result.stderr, file=sys.stderr)

    return True


def main():
    parser = argparse.ArgumentParser(description="Guardian shift orchestrator")
    parser.add_argument("--mode", choices=["daily", "weekly", "handoff"], default="daily",
                        help="Check mode (default: daily)")
    parser.add_argument("--repos-file", default=DEFAULT_REPOS_FILE,
                        help="Path to repos.json")
    parser.add_argument("--sonar-config", default=DEFAULT_SONAR_CONFIG,
                        help="Path to sonar.json")
    parser.add_argument("--codecov-config", default=DEFAULT_CODECOV_CONFIG,
                        help="Path to codecov.json")
    parser.add_argument("--reports-dir", default=REPORTS_DIR,
                        help="Directory for output files")
    parser.add_argument("--stale-days", type=int, default=14,
                        help="Days before a PR is considered stale (default: 14)")
    parser.add_argument("--ci-days", type=int, default=3,
                        help="Days of CI history to check (default: 3)")
    args = parser.parse_args()

    os.makedirs(args.reports_dir, exist_ok=True)

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    include_sonar = args.mode in ("weekly", "handoff")
    include_handoff = args.mode == "handoff"

    print(f"Guardian check: mode={args.mode}, date={date_str}", file=sys.stderr)
    print(f"Reports directory: {args.reports_dir}", file=sys.stderr)

    prs_file = os.path.join(args.reports_dir, f"open-prs-{date_str}.json")
    ci_file = os.path.join(args.reports_dir, f"ci-status-{date_str}.json")
    renovate_file = os.path.join(args.reports_dir, f"renovate-prs-{date_str}.json")
    sonar_file = os.path.join(args.reports_dir, f"sonar-gates-{date_str}.json")
    codecov_file = os.path.join(args.reports_dir, f"codecov-{date_str}.json")

    errors = 0
    issues_found = False

    if not run_script("fetch_open_prs.py",
                      ["--repos-file", args.repos_file, "--stale-days", str(args.stale_days)],
                      prs_file):
        errors += 1

    if not run_script("fetch_ci_status.py",
                      ["--repos-file", args.repos_file, "--days", str(args.ci_days)],
                      ci_file):
        errors += 1

    if not run_script("fetch_renovate_prs.py",
                      ["--repos-file", args.repos_file],
                      renovate_file):
        errors += 1

    if os.path.exists(args.codecov_config):
        if not run_script("fetch_codecov.py",
                          ["--codecov-config", args.codecov_config],
                          codecov_file):
            errors += 1
    else:
        print(f"WARN: Codecov config not found: {args.codecov_config}", file=sys.stderr)

    if include_sonar:
        if os.path.exists(args.sonar_config):
            if not run_script("fetch_sonar_gates.py",
                              ["--sonar-config", args.sonar_config],
                              sonar_file):
                errors += 1
        else:
            print(f"WARN: Sonar config not found: {args.sonar_config}", file=sys.stderr)

    previous_snapshot = os.path.join(args.reports_dir, "previous-snapshot.json")
    changes_file = os.path.join(args.reports_dir, "changes.json")

    print(f"\n{'='*60}", file=sys.stderr)
    print("Diffing against previous snapshot...", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    diff_args = [
        "--previous", previous_snapshot,
        "--output", changes_file,
        "--write-previous", previous_snapshot,
    ]
    if os.path.exists(prs_file):
        diff_args.extend(["--prs", prs_file])
    if os.path.exists(ci_file):
        diff_args.extend(["--ci", ci_file])
    if os.path.exists(renovate_file):
        diff_args.extend(["--renovate", renovate_file])
    if os.path.exists(codecov_file):
        diff_args.extend(["--codecov", codecov_file])
    if include_sonar and os.path.exists(sonar_file):
        diff_args.extend(["--sonar", sonar_file])

    # diff_snapshots writes files itself (not stdout JSON like fetch scripts)
    if any(os.path.exists(f) for f in [prs_file, ci_file, renovate_file]):
        diff_script = os.path.join(SCRIPTS_DIR, "diff_snapshots.py")
        diff_cmd = [sys.executable, diff_script] + diff_args
        try:
            diff_result = subprocess.run(diff_cmd, capture_output=True, text=True, timeout=60)
            if diff_result.stderr:
                print(diff_result.stderr, file=sys.stderr)
            if diff_result.returncode != 0:
                print("WARN: Snapshot diff failed", file=sys.stderr)
                errors += 1
        except subprocess.TimeoutExpired:
            print("WARN: Snapshot diff timed out", file=sys.stderr)
            errors += 1

    print(f"\n{'='*60}", file=sys.stderr)
    print("Generating reports...", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    if os.path.exists(prs_file):
        pr_report = os.path.join(args.reports_dir, f"pr-dashboard-{date_str}.md")
        generate_report("prs", [prs_file], pr_report)

    if os.path.exists(ci_file):
        ci_report = os.path.join(args.reports_dir, f"ci-dashboard-{date_str}.md")
        generate_report("ci", [ci_file], ci_report)

    if os.path.exists(renovate_file):
        dep_report = os.path.join(args.reports_dir, f"dependency-dashboard-{date_str}.md")
        generate_report("renovate", [renovate_file], dep_report)

    if os.path.exists(codecov_file):
        cov_report = os.path.join(args.reports_dir, f"codecov-dashboard-{date_str}.md")
        generate_report("codecov", [codecov_file], cov_report)

    if include_sonar and os.path.exists(sonar_file):
        sonar_report = os.path.join(args.reports_dir, f"sonar-dashboard-{date_str}.md")
        generate_report("sonar", [sonar_file], sonar_report)

    guardian_args = []
    if os.path.exists(prs_file):
        guardian_args.extend(["--prs", prs_file])
    if os.path.exists(ci_file):
        guardian_args.extend(["--ci", ci_file])
    if os.path.exists(renovate_file):
        guardian_args.extend(["--renovate", renovate_file])
    if os.path.exists(codecov_file):
        guardian_args.extend(["--codecov", codecov_file])
    if include_sonar and os.path.exists(sonar_file):
        guardian_args.extend(["--sonar", sonar_file])
    if os.path.exists(changes_file):
        guardian_args.extend(["--changes", changes_file])

    guardian_report = os.path.join(args.reports_dir, f"guardian-{args.mode}-{date_str}.md")
    generate_report("guardian", guardian_args, guardian_report)

    if include_handoff:
        handoff_report = os.path.join(args.reports_dir, f"handoff-{date_str}.md")
        generate_report("handoff", guardian_args, handoff_report)

    for json_file in [prs_file, ci_file, renovate_file, sonar_file, codecov_file]:
        if not os.path.exists(json_file):
            continue
        try:
            with open(json_file) as f:
                data = json.load(f)
            agg = data.get("aggregate", data.get("summary", {}))
            if agg.get("failing", 0) > 0 or agg.get("gate_error", 0) > 0:
                issues_found = True
            if agg.get("overdue", 0) > 0:
                issues_found = True
            if agg.get("stale", 0) > 0 or agg.get("blocked", 0) > 0:
                issues_found = True
        except (json.JSONDecodeError, KeyError):
            pass

    print(f"\n{'='*60}", file=sys.stderr)
    print("Guardian check complete!", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"Mode: {args.mode}", file=sys.stderr)
    print(f"Reports: {args.reports_dir}", file=sys.stderr)
    print(f"Main report: guardian-{args.mode}-{date_str}.md", file=sys.stderr)
    if include_handoff:
        print(f"Handoff: handoff-{date_str}.md", file=sys.stderr)
    if errors > 0:
        print(f"Errors: {errors} script(s) failed", file=sys.stderr)
    print("", file=sys.stderr)

    if errors > 0:
        sys.exit(2)
    elif issues_found:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
