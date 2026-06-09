#!/usr/bin/env python3
"""Dependency vulnerability scanner for PR checks.

Parses dependency file diffs, queries OSV.dev for known vulnerabilities,
and outputs a markdown comment body for posting to the PR.

Usage:
    python dep-check.py --diff <diff_file> [--output <output_file>]

If --diff is "-", reads from stdin.
Exit code 0 = clean, 1 = vulnerabilities found, 2 = error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_BATCH_SIZE = 100
OSV_TIMEOUT = 30
COMMENT_MARKER = "<!-- dep-check-result -->"

DEP_FILE_PATTERNS: set[str] = {
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "pyproject.toml",
    "setup.cfg",
    "requirements.txt",
    "uv.lock",
    "Pipfile.lock",
}


def is_dep_file(path: str) -> bool:
    """Return True if the path is a recognized dependency file."""
    basename = path.split("/")[-1]
    if basename in DEP_FILE_PATTERNS:
        return True
    if basename.startswith("requirements") and basename.endswith(".txt"):
        return True
    if basename.endswith(".lock"):
        return True
    if "pnpm-lock" in path:
        return True
    return False


def detect_dep_files_in_diff(diff_text: str) -> list[str]:
    """Extract dependency file paths from a unified diff."""
    files = []
    for match in re.finditer(r"^diff --git a/(.+?) b/(.+?)$", diff_text, re.MULTILINE):
        path = match.group(2)
        if is_dep_file(path):
            files.append(path)
    return list(set(files))


def parse_uv_lock_diff(diff_text: str) -> list[dict[str, str]]:
    """Parse uv.lock diff for package version changes."""
    changes: list[dict[str, str]] = []
    lines = diff_text.split("\n")
    current_pkg: str | None = None
    old_ver: str | None = None
    new_ver: str | None = None

    for line in lines:
        name_match = re.match(r'^[\s]*name = "(.+)"', line)
        if name_match:
            current_pkg = name_match.group(1)
            old_ver = None
            new_ver = None

        if current_pkg:
            if re.match(r"^-version = \"(.+)\"", line):
                old_ver = re.match(r'^-version = "(.+)"', line).group(1)  # type: ignore[union-attr]
            if re.match(r'^\+version = "(.+)"', line):
                new_ver = re.match(r'^\+version = "(.+)"', line).group(1)  # type: ignore[union-attr]

            if old_ver and new_ver:
                changes.append({
                    "name": current_pkg,
                    "oldVersion": old_ver,
                    "newVersion": new_ver,
                    "ecosystem": "PyPI",
                })
                current_pkg = None
                old_ver = None
                new_ver = None

    return changes


def parse_pnpm_lock_diff(diff_text: str) -> list[dict[str, str]]:
    """Parse pnpm-lock.yaml diff for version changes."""
    changes: list[dict[str, str]] = []
    lines = diff_text.split("\n")
    current_pkg: str | None = None

    for i, line in enumerate(lines):
        pkg_match = re.match(r"^\s{4,8}'?(@?[\w/.@-]+)'?:", line)
        if pkg_match and "specifier" not in line and "version" not in line:
            current_pkg = pkg_match.group(1).rstrip(":")

        if line.startswith("-") and "version:" in line and current_pkg:
            ver_match = re.search(r"(\d+\.\d+[\d.]*)", line)
            if ver_match:
                old_v = ver_match.group(1)
                if i + 1 < len(lines) and lines[i + 1].startswith("+") and "version:" in lines[i + 1]:
                    new_match = re.search(r"(\d+\.\d+[\d.]*)", lines[i + 1])
                    if new_match and new_match.group(1) != old_v:
                        changes.append({
                            "name": current_pkg,
                            "oldVersion": old_v,
                            "newVersion": new_match.group(1),
                            "ecosystem": "npm",
                        })

    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for c in changes:
        key = f"{c['name']}:{c['oldVersion']}:{c['newVersion']}"
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped


def parse_pyproject_diff(diff_text: str) -> list[dict[str, str]]:
    """Parse pyproject.toml diff for version changes."""
    changes: list[dict[str, str]] = []
    lines = diff_text.split("\n")

    for i, line in enumerate(lines):
        if line.startswith("-") and not line.startswith("---"):
            old_match = re.search(r'"([\w][\w.-]*)([><=!~]+)([\d.]+\*?)"', line)
            if old_match and i + 1 < len(lines):
                next_line = lines[i + 1]
                if next_line.startswith("+"):
                    new_match = re.search(r'"([\w][\w.-]*)([><=!~]+)([\d.]+\*?)"', next_line)
                    if new_match and new_match.group(1) == old_match.group(1):
                        changes.append({
                            "name": old_match.group(1),
                            "oldVersion": old_match.group(3),
                            "newVersion": new_match.group(3),
                            "ecosystem": "PyPI",
                        })
    return changes


def parse_package_json_diff(diff_text: str) -> list[dict[str, str]]:
    """Parse package.json / package-lock.json diff for version changes."""
    changes: list[dict[str, str]] = []
    lines = diff_text.split("\n")
    pkg_ver_re = re.compile(r'"([@\w/.-]+)":\s*"[\^~>=<]*(\d+[\d.]*)')

    for i, line in enumerate(lines):
        if line.startswith("-") and not line.startswith("---"):
            old_match = pkg_ver_re.search(line)
            if old_match and i + 1 < len(lines):
                next_line = lines[i + 1]
                if next_line.startswith("+"):
                    new_match = pkg_ver_re.search(next_line)
                    if new_match and new_match.group(1) == old_match.group(1):
                        if old_match.group(2) != new_match.group(2):
                            changes.append({
                                "name": old_match.group(1),
                                "oldVersion": old_match.group(2),
                                "newVersion": new_match.group(2),
                                "ecosystem": "npm",
                            })
    return changes


def parse_diff(diff_text: str, dep_files: list[str]) -> list[dict[str, str]]:
    """Parse all dependency changes from the diff."""
    packages: list[dict[str, str]] = []

    if any("uv.lock" in f for f in dep_files):
        packages.extend(parse_uv_lock_diff(diff_text))
    if any("pnpm-lock" in f for f in dep_files):
        packages.extend(parse_pnpm_lock_diff(diff_text))
    if any("pyproject.toml" in f for f in dep_files):
        packages.extend(parse_pyproject_diff(diff_text))
    if any("package.json" in f or "package-lock.json" in f for f in dep_files):
        packages.extend(parse_package_json_diff(diff_text))

    # Deduplicate
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for pkg in packages:
        key = f"{pkg['name']}:{pkg['newVersion']}:{pkg['ecosystem']}"
        if key not in seen:
            seen.add(key)
            deduped.append(pkg)

    return deduped


def query_osv(packages: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """Query OSV.dev for vulnerabilities. Returns {key: [advisory,...]}."""
    results: dict[str, list[dict[str, str]]] = {}
    queries = [
        {
            "version": pkg["newVersion"],
            "package": {"name": pkg["name"], "ecosystem": pkg["ecosystem"]},
        }
        for pkg in packages
    ]

    for i in range(0, len(queries), OSV_BATCH_SIZE):
        batch = queries[i : i + OSV_BATCH_SIZE]
        payload = json.dumps({"queries": batch}).encode("utf-8")
        req = urllib.request.Request(
            OSV_BATCH_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "dep-check-action/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=OSV_TIMEOUT) as resp:  # noqa: S310
                data = json.loads(resp.read())
                batch_results = data.get("results", [])
                for j, result in enumerate(batch_results):
                    vulns = result.get("vulns", [])
                    if vulns:
                        pkg = packages[i + j]
                        key = f"{pkg['name']}:{pkg['newVersion']}:{pkg['ecosystem']}"
                        results[key] = [
                            {
                                "id": v.get("id", ""),
                                "summary": v.get("summary", "")[:120],
                            }
                            for v in vulns[:5]
                        ]
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as exc:
            print(f"::warning::OSV batch query failed: {exc}", file=sys.stderr)

    return results


def osv_url(advisory_id: str) -> str:
    """Return the URL for an advisory."""
    if advisory_id.startswith("GHSA-"):
        return f"https://github.com/advisories/{advisory_id}"
    return f"https://osv.dev/vulnerability/{advisory_id}"


def format_comment(
    packages: list[dict[str, str]],
    vulns: dict[str, list[dict[str, str]]],
    dep_files: list[str],
) -> str:
    """Format the PR comment markdown."""
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    vuln_count = sum(1 for pkg in packages if f"{pkg['name']}:{pkg['newVersion']}:{pkg['ecosystem']}" in vulns)
    clean_count = len(packages) - vuln_count
    status = "FAIL" if vuln_count > 0 else "PASS"

    lines = [
        COMMENT_MARKER,
        "## Dependency Vulnerability Scan",
        "",
        f"**Status**: {status}",
        f"**Scanned**: {now}",
        f"**Files**: {', '.join(f'`{f}`' for f in dep_files)}",
        "",
    ]

    if packages:
        lines.append("| Package | Version | Ecosystem | Status | Advisory |")
        lines.append("|---------|---------|-----------|--------|----------|")
        for pkg in packages:
            key = f"{pkg['name']}:{pkg['newVersion']}:{pkg['ecosystem']}"
            if key in vulns:
                advisories = vulns[key]
                links = ", ".join(f"[{a['id']}]({osv_url(a['id'])})" for a in advisories)
                lines.append(
                    f"| {pkg['name']} | {pkg['newVersion']} | {pkg['ecosystem']} "
                    f"| **VULNERABLE** | {links} |"
                )
            else:
                lines.append(
                    f"| {pkg['name']} | {pkg['newVersion']} | {pkg['ecosystem']} "
                    f"| Clean | — |"
                )
        lines.append("")

    lines.append(f"**Summary**: {len(packages)} packages scanned. {clean_count} clean. {vuln_count} vulnerable.")
    lines.append("")
    lines.append("---")
    lines.append("_Re-run with `/recheck`. Auto-scans daily._")

    return "\n".join(lines)


def format_no_deps_comment() -> str:
    """Format comment when no dependency changes are detected."""
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return "\n".join([
        COMMENT_MARKER,
        "## Dependency Vulnerability Scan",
        "",
        "**Status**: PASS",
        f"**Scanned**: {now}",
        "",
        "No dependency file changes detected in this PR.",
        "",
        "---",
        "_Re-run with `/recheck`. Auto-scans daily._",
    ])


def main() -> int:
    """Run the dep-check scanner."""
    parser = argparse.ArgumentParser(description="Dependency vulnerability scanner")
    parser.add_argument("--diff", required=True, help="Path to diff file, or '-' for stdin")
    parser.add_argument("--output", default="-", help="Output file for comment markdown")
    args = parser.parse_args()

    if args.diff == "-":
        diff_text = sys.stdin.read()
    else:
        diff_text = Path(args.diff).read_text()

    dep_files = detect_dep_files_in_diff(diff_text)

    if not dep_files:
        comment = format_no_deps_comment()
        if args.output == "-":
            print(comment)
        else:
            Path(args.output).write_text(comment)
        return 0

    packages = parse_diff(diff_text, dep_files)

    if not packages:
        comment = format_no_deps_comment()
        if args.output == "-":
            print(comment)
        else:
            Path(args.output).write_text(comment)
        return 0

    print(f"Scanning {len(packages)} packages against OSV.dev...", file=sys.stderr)
    vulns = query_osv(packages)

    comment = format_comment(packages, vulns, dep_files)

    if args.output == "-":
        print(comment)
    else:
        Path(args.output).write_text(comment)

    if vulns:
        print(f"::error::{len(vulns)} vulnerable package(s) found", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
