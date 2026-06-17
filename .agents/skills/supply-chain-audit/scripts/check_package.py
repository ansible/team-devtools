"""Phase 2: Package/CVE focused supply chain analysis.

Given a suspect package and compromise date, determines which repos in the
ADT ecosystem pulled in the affected version and when. Cross-references
cached dependency change data to build an impact timeline.
"""
# ruff: noqa: BLE001

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from cache_utils import (
    get_all_cached_deps,
    read_manifest,
    write_package_focus,
)


def get_pypi_release_dates(package_name: str) -> dict[str, str]:
    """Fetch all release dates for a package from PyPI."""
    try:
        url = f"https://pypi.org/pypi/{package_name}/json"
        req = urllib.request.Request(  # noqa: S310
            url, headers={"User-Agent": "supply-chain-audit/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            data = json.loads(resp.read())

        releases = data.get("releases", {})
        version_dates: dict[str, str] = {}
        for version, files in releases.items():
            if files:
                upload_time = files[0].get("upload_time_iso_8601", "")
                if upload_time:
                    version_dates[version] = upload_time[:10]
    except Exception:
        return {}
    else:
        return version_dates


def get_npm_release_dates(package_name: str) -> dict[str, str]:
    """Fetch all release dates for a package from npm."""
    try:
        url = f"https://registry.npmjs.org/{package_name}"
        req = urllib.request.Request(  # noqa: S310
            url, headers={"User-Agent": "supply-chain-audit/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            data = json.loads(resp.read())

        time_data = data.get("time", {})
        version_dates: dict[str, str] = {}
        for version, timestamp in time_data.items():
            if version not in ("created", "modified"):
                version_dates[version] = timestamp[:10]
    except Exception:
        return {}
    else:
        return version_dates


def analyze_package_impact(
    package_name: str,
    compromise_date: str,
    deps: list[dict],
    release_dates: dict[str, str],
) -> dict:
    """Analyze how a compromised package affected the ecosystem."""
    affected_repos: list[dict] = []
    safe_repos: list[dict] = []

    repos_with_package: dict[str, list[dict]] = {}
    for dep in deps:
        if dep.get("package_name", "").lower() == package_name.lower():
            repos_with_package.setdefault(dep["repo"], []).append(dep)

    for repo, repo_deps in repos_with_package.items():
        for dep in sorted(repo_deps, key=lambda d: d.get("commit_date", "")):
            version = dep.get("new_version")
            commit_date = dep.get("commit_date", "")[:10]
            change_type = dep.get("change_type", "unknown")

            version_release = release_dates.get(version, "unknown")

            is_after_compromise = commit_date >= compromise_date
            version_released_after = (
                version_release != "unknown" and version_release >= compromise_date
            )

            is_pinned = _is_version_pinned(dep)

            entry = {
                "repo": repo,
                "version": version,
                "change_type": change_type,
                "commit_date": commit_date,
                "commit_sha": dep.get("commit_sha", ""),
                "file_path": dep.get("file_path", ""),
                "version_release_date": version_release,
                "is_pinned": is_pinned,
                "adopted_after_compromise": is_after_compromise,
                "version_released_after_compromise": version_released_after,
                "risk_assessment": _assess_risk(
                    adopted_after=is_after_compromise,
                    released_after=version_released_after,
                    is_pinned=is_pinned,
                    change_type=change_type,
                ),
            }

            if is_after_compromise or version_released_after:
                affected_repos.append(entry)
            else:
                safe_repos.append(entry)

    potentially_exposed = [
        r for r in affected_repos if r["risk_assessment"] in ("critical", "high")
    ]

    return {
        "package_name": package_name,
        "compromise_date": compromise_date,
        "total_repos_using": len(repos_with_package),
        "affected_entries": affected_repos,
        "safe_entries": safe_repos,
        "potentially_exposed_count": len(potentially_exposed),
        "release_dates_checked": len(release_dates),
        "timeline": _build_timeline(affected_repos, safe_repos, compromise_date),
    }


def _is_version_pinned(dep: dict) -> bool:
    """Heuristic: is this a pinned (exact) version vs a range?"""
    version = dep.get("new_version", "")
    if not version:
        return False
    return not any(c in version for c in ("*", "^", "~", ">", "<", "!"))


def _assess_risk(
    *,
    adopted_after: bool,
    released_after: bool,
    is_pinned: bool,
    change_type: str,
) -> str:
    """Classify the risk level for a specific dep entry."""
    if adopted_after and released_after:
        return "critical"
    if adopted_after and not is_pinned:
        return "high"
    if released_after and change_type == "added":
        return "high"
    if adopted_after:
        return "medium"
    return "low"


def _build_timeline(
    affected: list[dict],
    safe: list[dict],
    compromise_date: str,
) -> list[dict]:
    """Build a chronological timeline of events."""
    events: list[dict] = []

    events.append(
        {
            "date": compromise_date,
            "event": "compromise",
            "description": "Suspected compromise date",
            "repo": None,
        }
    )

    events.extend(
        {
            "date": entry["commit_date"],
            "event": "dep_change",
            "description": (
                f"{entry['repo']}: {entry['change_type']} "
                f"v{entry['version']} ({entry['file_path']})"
            ),
            "repo": entry["repo"],
            "risk": entry.get("risk_assessment", "unknown"),
        }
        for entry in affected + safe
    )

    events.sort(key=lambda e: e.get("date", ""))
    return events


def main() -> None:
    """Entry point for package focus analysis."""
    parser = argparse.ArgumentParser(
        description="Package/CVE focused supply chain analysis"
    )
    parser.add_argument(
        "--cache-dir", required=True, help="Cache directory from collect.py"
    )
    parser.add_argument("--package", required=True, help="Package name to investigate")
    parser.add_argument(
        "--compromise-date",
        required=True,
        help="Suspected compromise date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--ecosystem",
        default="pypi",
        choices=["pypi", "npm"],
        help="Package ecosystem (default: pypi)",
    )
    args = parser.parse_args()

    try:
        datetime.strptime(args.compromise_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        print("ERROR: compromise-date must be YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)

    cache_path = Path(args.cache_dir)

    cache_dir = cache_path
    if not (cache_path / "manifest.json").exists():
        for subdir in sorted(cache_path.iterdir()):
            if subdir.is_dir() and (subdir / "manifest.json").exists():
                cache_dir = subdir
                break
        else:
            print(
                "ERROR: No manifest.json found. Run collect.py first.", file=sys.stderr
            )
            sys.exit(1)

    manifest = read_manifest(cache_dir)
    print("Package Focus Analysis")
    print(f"  Package: {args.package}")
    print(f"  Compromise date: {args.compromise_date}")
    print(f"  Audit window: {manifest['start_date']} to {manifest['end_date']}")
    print(f"  Ecosystem: {args.ecosystem}")

    print(f"\nFetching release dates for '{args.package}'...")
    if args.ecosystem == "pypi":
        release_dates = get_pypi_release_dates(args.package)
    else:
        release_dates = get_npm_release_dates(args.package)
    print(f"  Found {len(release_dates)} versions")

    print("\nLoading cached dependency data...")
    deps = get_all_cached_deps(cache_dir)
    print(f"  Total dep changes in cache: {len(deps)}")

    print("\nAnalyzing impact...")
    results = analyze_package_impact(
        args.package, args.compromise_date, deps, release_dates
    )

    write_package_focus(cache_dir, results)

    print(f"\n{'=' * 60}")
    print("  Results Summary")
    print(f"{'=' * 60}")
    print(f"  Repos using '{args.package}': {results['total_repos_using']}")
    print(f"  Potentially exposed: {results['potentially_exposed_count']}")
    print(f"  Affected entries: {len(results['affected_entries'])}")
    print(f"  Safe entries: {len(results['safe_entries'])}")

    if results["affected_entries"]:
        print("\n  Affected repos:")
        for entry in results["affected_entries"]:
            risk = entry["risk_assessment"].upper()
            print(
                f"    [{risk}] {entry['repo']}: v{entry['version']} "
                f"({entry['change_type']} on {entry['commit_date']})"
            )

    print(f"\n  Results written to: {cache_dir / 'package_focus.json'}")


if __name__ == "__main__":
    main()
