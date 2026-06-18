"""Data collection for supply chain audit via GitHub CLI.

Fetches commits, PRs, check suites, and dependency file diffs for all
target repos within a specified time window. Results are cached as JSON
for idempotent re-runs.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cache_utils import (
    GITHUB_ORG,
    TARGET_REPOS,
    ensure_cache_structure,
    get_cache_dir,
    has_cached_data,
    read_cache_file,
    write_cache_file,
    write_manifest,
)
from models import CheckSuite, Commit, DepChange, PullRequest

if TYPE_CHECKING:
    from pathlib import Path


RATE_LIMIT_SLEEP = 0.5
RATE_LIMIT_RETRY_SLEEP_SECONDS = 60
PER_PAGE = 100
GH_API_TIMEOUT_SECONDS = 120
GH_VERSION_TIMEOUT_SECONDS = 10
REGISTRY_REQUEST_TIMEOUT_SECONDS = 10
OSV_REQUEST_TIMEOUT_SECONDS = 30
OSV_BATCH_SIZE = 100
OSV_BATCH_SLEEP_SECONDS = 1
MAX_COMMIT_MSG_LEN = 120
GITHUB_EXT_PREFIX_LEN = 7
GITHUB_EXT_EXPECTED_PARTS = 2
CVSS_CRITICAL_THRESHOLD = 9.0
CVSS_HIGH_THRESHOLD = 7.0
CVSS_MEDIUM_THRESHOLD = 4.0
DATE_FORMAT = "%Y-%m-%d"

DEP_FILES_PYTHON = {
    "pyproject.toml",
    "setup.cfg",
    "setup.py",
    "requirements.txt",
    "constraints.txt",
    "Pipfile",
    "Pipfile.lock",
    "poetry.lock",
    "uv.lock",
    "pdm.lock",
}

DEP_FILES_NODE = {
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
}

DEP_FILE_PATTERNS = re.compile(
    r"(requirements.*\.txt|constraints\.txt|pyproject\.toml|setup\.cfg|setup\.py|"
    r"Pipfile(\.lock)?|poetry\.lock|uv\.lock|pdm\.lock|"
    r"package\.json|package-lock\.json|yarn\.lock|pnpm-lock\.yaml)",
)


def gh_api(endpoint: str, *, paginate: bool = False) -> list | dict | None:
    """Call GitHub API via gh CLI. Returns parsed JSON or None on error."""
    cmd = ["gh", "api", endpoint, "--header", "Accept: application/vnd.github+json"]
    if paginate:
        cmd.append("--paginate")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=GH_API_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT: {endpoint}", file=sys.stderr)
        return None

    if result.returncode != 0:
        if "rate limit" in result.stderr.lower() or "403" in result.stderr:
            print("  Rate limited, sleeping 60s...", file=sys.stderr)
            time.sleep(RATE_LIMIT_RETRY_SLEEP_SECONDS)
            return gh_api(endpoint, paginate=paginate)
        if "404" in result.stderr or "Not Found" in result.stderr:
            return None
        print(f"  ERROR ({result.returncode}): {result.stderr[:200]}", file=sys.stderr)
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def get_gh_version() -> str:
    """Get the installed gh CLI version string."""
    try:
        result = subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            text=True,
            timeout=GH_VERSION_TIMEOUT_SECONDS,
            check=False,
        )
        return result.stdout.strip().split("\n")[0]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "unknown"


def collect_commits(repo: str, start_date: str, end_date: str) -> list[dict]:
    """Fetch all commits for a repo in the time window."""
    endpoint = (
        f"repos/{GITHUB_ORG}/{repo}/commits"
        f"?since={start_date}T00:00:00Z&until={end_date}T23:59:59Z&per_page={PER_PAGE}"
    )
    data = gh_api(endpoint, paginate=True)
    if not data or not isinstance(data, list):
        return []

    commits = []
    for item in data:
        commit = Commit.from_api(item, repo)
        commits.append(commit.to_dict())

    return commits


def collect_prs_for_commits(repo: str, commits: list[dict]) -> list[dict]:
    """Fetch associated PRs for each commit and PR details."""
    prs_seen: set[int] = set()
    prs: list[dict] = []

    for commit_data in commits:
        sha = commit_data["sha"]
        endpoint = f"repos/{GITHUB_ORG}/{repo}/commits/{sha}/pulls"
        pr_list = gh_api(endpoint)
        time.sleep(RATE_LIMIT_SLEEP)

        if not pr_list or not isinstance(pr_list, list):
            continue

        for pr_data in pr_list:
            pr_num = pr_data.get("number", 0)
            if pr_num in prs_seen:
                commit_data.setdefault("associated_prs", [])
                if pr_num not in commit_data["associated_prs"]:
                    commit_data["associated_prs"].append(pr_num)
                continue

            prs_seen.add(pr_num)
            pr_detail = gh_api(f"repos/{GITHUB_ORG}/{repo}/pulls/{pr_num}")
            time.sleep(RATE_LIMIT_SLEEP)

            if pr_detail and isinstance(pr_detail, dict):
                pr = PullRequest.from_api(pr_detail, repo)
                prs.append(pr.to_dict())

            commit_data.setdefault("associated_prs", [])
            if pr_num not in commit_data["associated_prs"]:
                commit_data["associated_prs"].append(pr_num)

    return prs


def collect_pr_commits_and_reviews(repo: str, prs: list[dict]) -> list[dict]:
    """Fetch all commits and review timeline for each merged PR.

    For each merged PR, collects:
    - All individual commits on the PR branch
    - All reviews (approvals) with their timestamps
    - Detects commits pushed after the last approval
    """
    pr_audit_data: list[dict] = []

    for pr in prs:
        if not pr.get("merged"):
            continue

        pr_num = pr["number"]

        # Get all commits on the PR branch
        commits_endpoint = (
            f"repos/{GITHUB_ORG}/{repo}/pulls/{pr_num}/commits?per_page=100"
        )
        pr_commits = gh_api(commits_endpoint)
        time.sleep(RATE_LIMIT_SLEEP)

        if not pr_commits or not isinstance(pr_commits, list):
            pr_commits = []

        # Get reviews (approvals)
        reviews_endpoint = f"repos/{GITHUB_ORG}/{repo}/pulls/{pr_num}/reviews"
        reviews = gh_api(reviews_endpoint)
        time.sleep(RATE_LIMIT_SLEEP)

        if not reviews or not isinstance(reviews, list):
            reviews = []

        approvals = [
            {
                "user": r.get("user", {}).get("login", "unknown"),
                "submitted_at": r.get("submitted_at", ""),
                "state": r.get("state", ""),
            }
            for r in reviews
            if r.get("state") == "APPROVED"
        ]

        commit_entries = []
        for c in pr_commits:
            commit_data = c.get("commit", {})
            author = c.get("author") or {}
            committer = c.get("committer") or {}
            commit_entries.append(
                {
                    "sha": c.get("sha", ""),
                    "author_login": author.get("login", "unknown"),
                    "committer_login": committer.get("login", "unknown"),
                    "date": commit_data.get("author", {}).get("date", ""),
                    "message": commit_data.get("message", "")[:MAX_COMMIT_MSG_LEN],
                },
            )

        pr_audit_data.append(
            {
                "repo": repo,
                "pr_number": pr_num,
                "pr_title": pr.get("title", ""),
                "pr_author": pr.get("author_login", ""),
                "merged_at": pr.get("merged_at", ""),
                "commits": commit_entries,
                "approvals": approvals,
                "commit_count": len(commit_entries),
            },
        )

    return pr_audit_data


def collect_check_suites(repo: str, commits: list[dict]) -> dict[str, list[dict]]:
    """Fetch check suites for each commit."""
    checks_by_sha: dict[str, list[dict]] = {}

    for commit_data in commits:
        sha = commit_data["sha"]
        endpoint = f"repos/{GITHUB_ORG}/{repo}/commits/{sha}/check-suites"
        data = gh_api(endpoint)
        time.sleep(RATE_LIMIT_SLEEP)

        suites = []
        if data and isinstance(data, dict):
            for suite in data.get("check_suites", []):
                cs = CheckSuite.from_api(suite, repo, sha)
                suites.append(cs.to_dict())

        checks_by_sha[sha] = suites

    return checks_by_sha


def _decode_github_file_content(data: dict) -> dict | None:
    """Decode base64 GitHub contents API response to JSON."""
    if not data.get("content"):
        return None
    try:
        content = base64.b64decode(data["content"]).decode("utf-8")
        return json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None


def _load_renovate_config_at_paths(config_paths: list[str]) -> dict | None:
    """Try loading renovate config from a list of GitHub contents API paths."""
    for path in config_paths:
        data = gh_api(path)
        if data and isinstance(data, dict):
            raw = _decode_github_file_content(data)
            if raw:
                return raw
    return None


def _fetch_shared_renovate_config(extends: list) -> tuple[dict, str | None]:
    """Resolve shared renovate preset referenced in extends list."""
    for ext in extends:
        if not ext.startswith("github>"):
            continue
        # Renovate github> preset uses org/repo//path/to/file.json
        parts = ext[GITHUB_EXT_PREFIX_LEN:].split("//", 1)
        if len(parts) != GITHUB_EXT_EXPECTED_PARTS:
            continue
        ext_repo, ext_path = parts[0], parts[1]
        ext_data = gh_api(f"repos/{ext_repo}/contents/{ext_path}")
        if ext_data and isinstance(ext_data, dict):
            shared = _decode_github_file_content(ext_data)
            if shared:
                time.sleep(RATE_LIMIT_SLEEP)
                return shared, f"shared:{ext}"
        time.sleep(RATE_LIMIT_SLEEP)
    return {}, None


def _resolve_major_cooldown(raw: dict, shared_config: dict) -> int | None:
    """Extract major-update cooldown days from renovate packageRules."""
    for rules_source in (raw, shared_config):
        for rule in rules_source.get("packageRules", []):
            update_types = rule.get("matchUpdateTypes", [])
            if "major" in update_types:
                major_age = rule.get("minimumReleaseAge") or rule.get("stabilityDays")
                if major_age:
                    return _parse_release_age(major_age)
    return None


def collect_renovate_config(repo: str) -> dict:
    """Fetch and resolve the renovate config for a repo, including shared presets.

    Returns a dict with:
      - default_cooldown_days: default minimumReleaseAge in days
      - major_cooldown_days: minimumReleaseAge for major updates (if different)
      - source: where the config comes from (local, shared preset, or none)
      - raw_config: the merged effective config values
    """
    config: dict = {
        "source": "none",
        "default_cooldown_days": None,
        "major_cooldown_days": None,
    }

    config_paths = [
        f"repos/{GITHUB_ORG}/{repo}/contents/renovate.json",
        f"repos/{GITHUB_ORG}/{repo}/contents/.github/renovate.json",
        f"repos/{GITHUB_ORG}/{repo}/contents/renovate.json5",
    ]

    raw = _load_renovate_config_at_paths(config_paths)
    if not raw:
        return config

    config["source"] = "local"
    extends = raw.get("extends", [])
    shared_config, shared_source = _fetch_shared_renovate_config(extends)
    if shared_source:
        config["source"] = shared_source

    effective_cooldown = (
        raw.get("minimumReleaseAge")
        or raw.get("stabilityDays")
        or shared_config.get("minimumReleaseAge")
        or shared_config.get("stabilityDays")
    )
    config["default_cooldown_days"] = _parse_release_age(effective_cooldown)
    config["major_cooldown_days"] = _resolve_major_cooldown(raw, shared_config)
    config["raw_config"] = {
        "minimumReleaseAge": effective_cooldown,
        "extends": extends,
    }

    return config


def _parse_release_age(age_str: str | int | None) -> int | None:
    """Parse renovate minimumReleaseAge string to days.

    Supports: '2 days', '7 days', '1 day', '24 hours', integer (days).
    """
    if age_str is None:
        return None
    if isinstance(age_str, int):
        return age_str

    age_str = age_str.strip().lower()
    match = re.match(r"(\d+)\s*(day|days|hour|hours|week|weeks)", age_str)
    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2)
    if "hour" in unit:
        return max(1, value // 24)
    if "week" in unit:
        return value * 7
    return value


def collect_dep_changes(
    repo: str, _start_date: str, end_date: str, commits: list[dict],
) -> list[dict]:
    """Identify dependency file changes by examining commits that touch dep files."""
    if not commits:
        return []

    first_sha = commits[-1]["sha"]
    last_sha = commits[0]["sha"]

    endpoint = f"repos/{GITHUB_ORG}/{repo}/compare/{first_sha}...{last_sha}"
    data = gh_api(endpoint)

    if not data or not isinstance(data, dict):
        return []

    dep_changes: list[dict] = []
    files = data.get("files", [])

    for file_info in files:
        filename = file_info.get("filename", "")
        basename = filename.split("/")[-1] if "/" in filename else filename

        if not DEP_FILE_PATTERNS.search(basename):
            continue

        patch = file_info.get("patch", "")
        ecosystem = "npm" if basename in DEP_FILES_NODE else "pypi"
        is_direct = basename not in {
            "poetry.lock",
            "uv.lock",
            "pdm.lock",
            "Pipfile.lock",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
        }

        # Use the latest commit date as the adoption date (when dep landed on main)
        latest_commit_date = commits[0].get("date", end_date)[:10]
        changes = parse_dep_patch(
            patch,
            filename,
            repo,
            ecosystem,
            is_direct=is_direct,
            commit_sha=last_sha,
            commit_date=latest_commit_date,
        )
        dep_changes.extend(changes)

    # Deduplicate: prefer direct dep files (package.json) over lock files
    seen: dict[tuple[str, str, str], dict] = {}
    for dep in dep_changes:
        key = (
            dep["repo"],
            dep["package_name"],
            dep.get("new_version") or dep.get("old_version", ""),
        )
        existing = seen.get(key)
        if existing:
            if dep.get("is_direct") and not existing.get("is_direct"):
                seen[key] = dep
        else:
            seen[key] = dep

    deduped = list(seen.values())
    for dep in deduped:
        enrich_dep_release_info(dep)
        time.sleep(RATE_LIMIT_SLEEP)

    return deduped


def parse_dep_patch(
    patch: str,
    file_path: str,
    repo: str,
    ecosystem: str,
    *,
    is_direct: bool,
    commit_sha: str,
    commit_date: str,
) -> list[dict]:
    """Parse a unified diff patch to extract dependency additions/updates."""
    changes: list[dict] = []
    basename = file_path.rsplit("/", maxsplit=1)[-1] if "/" in file_path else file_path

    if basename in ("package-lock.json", "package.json", "yarn.lock", "pnpm-lock.yaml"):
        added_deps, removed_deps = _parse_npm_patch(patch, basename)
    elif basename in ("uv.lock", "poetry.lock", "pdm.lock"):
        added_deps, removed_deps = _parse_toml_lock_patch(patch)
    else:
        added_deps, removed_deps = _parse_python_patch(patch)

    for pkg, new_ver in added_deps.items():
        old_ver = removed_deps.pop(pkg, None)
        change_type = "updated" if old_ver else "added"
        dep = DepChange(
            repo=repo,
            file_path=file_path,
            package_name=pkg,
            old_version=old_ver,
            new_version=new_ver,
            change_type=change_type,
            commit_sha=commit_sha,
            commit_date=commit_date,
            ecosystem=ecosystem,
            is_direct=is_direct,
        )
        changes.append(dep.to_dict())

    for pkg, old_ver in removed_deps.items():
        dep = DepChange(
            repo=repo,
            file_path=file_path,
            package_name=pkg,
            old_version=old_ver,
            new_version=None,
            change_type="removed",
            commit_sha=commit_sha,
            commit_date=commit_date,
            ecosystem=ecosystem,
            is_direct=is_direct,
        )
        changes.append(dep.to_dict())

    return changes


def _parse_npm_patch(
    patch: str, basename: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Parse npm ecosystem diff lines for package names and versions."""
    added_deps: dict[str, str] = {}
    removed_deps: dict[str, str] = {}

    # package.json / package-lock.json dependency declarations:
    #   "@devcontainers/cli": "^0.87.0"
    #   "some-pkg": "~2.1.0"
    dep_decl = re.compile(r'"((?:@[\w.-]+/)?[\w][\w./-]*)"\s*:\s*"[~^]?(\d+[\d.]*\w*)"')

    # package-lock.json node_modules path (extracts name from path key):
    #   "node_modules/@devcontainers/cli": {
    node_path = re.compile(r'"node_modules/((?:@[\w.-]+/)?[\w][\w./-]*)"\s*:')

    # package-lock.json "version" field (used to pair with preceding path key)
    version_field = re.compile(r'"version"\s*:\s*"(\d+[\d.]*\w*)"')

    current_pkg: str | None = None

    for line in patch.split("\n"):
        is_add = line.startswith("+") and not line.startswith("+++")
        is_remove = line.startswith("-") and not line.startswith("---")

        if not is_add and not is_remove:
            # Context line — track package path for version pairing
            m = node_path.search(line)
            if m:
                current_pkg = m.group(1)
            continue

        # Direct dependency declaration (package.json style)
        m = dep_decl.search(line)
        if m:
            pkg = m.group(1)
            ver = m.group(2)
            # Skip metadata keys
            if pkg in ("version", "resolved", "integrity", "name"):
                pass
            elif is_add:
                added_deps[pkg] = ver
            else:
                removed_deps[pkg] = ver
            continue

        # node_modules path key
        m = node_path.search(line)
        if m:
            current_pkg = m.group(1)
            continue

        # version field — pair with current_pkg if in lock file
        if current_pkg and basename == "package-lock.json":
            m = version_field.search(line)
            if m:
                ver = m.group(1)
                if is_add:
                    added_deps[current_pkg] = ver
                else:
                    removed_deps[current_pkg] = ver

    return added_deps, removed_deps


def _parse_toml_lock_patch(patch: str) -> tuple[dict[str, str], dict[str, str]]:
    """Parse uv.lock / poetry.lock / pdm.lock diffs.

    These are TOML files with [[package]] sections containing name and version fields:
        [[package]]
        name = "idna"
        version = "3.16"
    """
    added_deps: dict[str, str] = {}
    removed_deps: dict[str, str] = {}

    name_pattern = re.compile(r'^[+-]\s*name\s*=\s*"([\w][\w.-]*)"')
    version_pattern = re.compile(r'^[+-]\s*version\s*=\s*"(\d+[\d.]*\w*)"')

    current_add_name: str | None = None
    current_remove_name: str | None = None

    for line in patch.split("\n"):
        # Track package names from added/removed lines
        m = name_pattern.match(line)
        if m:
            if line.startswith("+"):
                current_add_name = m.group(1)
            else:
                current_remove_name = m.group(1)
            continue

        # Match version lines and pair with the most recent name
        m = version_pattern.match(line)
        if m:
            ver = m.group(1)
            if line.startswith("+") and current_add_name:
                added_deps[current_add_name] = ver
                current_add_name = None
            elif line.startswith("-") and current_remove_name:
                removed_deps[current_remove_name] = ver
                current_remove_name = None
            continue

        # Reset on section boundaries
        if line.strip() in ("", "+[[package]]", "-[[package]]", " [[package]]"):
            current_add_name = None
            current_remove_name = None

    return added_deps, removed_deps


def _parse_python_patch(patch: str) -> tuple[dict[str, str], dict[str, str]]:
    """Parse Python ecosystem diff lines for package names and versions."""
    added_deps: dict[str, str] = {}
    removed_deps: dict[str, str] = {}

    # Matches: package>=1.0.0, package==1.0.0, package~=1.0, "package[extra]>=1.0"
    version_pattern = re.compile(
        r'["\']?([\w][\w.-]*(?:\[[^\]]*\])?)["\']?\s*'
        r"(?:[><=!~^]+\s*)?(\d+\.\d+[\w.*]*)",
    )

    for line in patch.split("\n"):
        match = version_pattern.search(line)
        if not match:
            continue

        pkg_name = match.group(1).strip("\"' ")
        version = match.group(2)

        # Skip common non-package keys
        if pkg_name in ("version", "python", "requires"):
            continue

        if line.startswith("+") and not line.startswith("+++"):
            added_deps[pkg_name] = version
        elif line.startswith("-") and not line.startswith("---"):
            removed_deps[pkg_name] = version

    return added_deps, removed_deps


def enrich_dep_release_info(dep: dict) -> None:
    """Query PyPI or npm for release date of a dependency version."""
    if dep.get("new_version") is None:
        return

    pkg = dep["package_name"]
    version = dep["new_version"]
    ecosystem = dep["ecosystem"]

    try:
        if ecosystem == "pypi":
            url = f"https://pypi.org/pypi/{pkg}/{version}/json"
            req = urllib.request.Request(  # noqa: S310
                url, headers={"User-Agent": "supply-chain-audit/1.0"},
            )
            with urllib.request.urlopen(  # noqa: S310
                req, timeout=REGISTRY_REQUEST_TIMEOUT_SECONDS,
            ) as resp:
                data = json.loads(resp.read())
                urls = data.get("urls", [])
                if urls:
                    upload_time = urls[0].get("upload_time_iso_8601", "")
                    dep["release_date"] = upload_time[:10] if upload_time else None
                info = data.get("info", {})
                if info.get("yanked"):
                    dep["yanked"] = True
        elif ecosystem == "npm":
            url = f"https://registry.npmjs.org/{pkg}"
            req = urllib.request.Request(  # noqa: S310
                url, headers={"User-Agent": "supply-chain-audit/1.0"},
            )
            with urllib.request.urlopen(  # noqa: S310
                req, timeout=REGISTRY_REQUEST_TIMEOUT_SECONDS,
            ) as resp:
                data = json.loads(resp.read())
                time_map = data.get("time", {})
                publish_time = time_map.get(version, "")
                dep["release_date"] = publish_time[:10] if publish_time else None
                versions = data.get("versions", {})
                ver_data = versions.get(version, {})
                if ver_data.get("deprecated"):
                    dep["yanked"] = True
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError):
        dep["release_date"] = None

    if dep.get("release_date") and dep.get("commit_date"):
        try:
            release_dt = datetime.fromisoformat(dep["release_date"])
            commit_dt = datetime.fromisoformat(dep["commit_date"][:10])
            dep["days_since_release"] = (commit_dt - release_dt).days
        except (ValueError, TypeError):
            pass


def collect_package_inventory(repo: str) -> list[dict]:
    """Extract current package inventory from lock files on the default branch.

    Reads lock files (uv.lock, poetry.lock, package-lock.json) to get a
    full list of installed packages and their pinned versions.
    """
    packages: list[dict] = []

    # Check for Python lock files
    for lock_file in ["uv.lock", "poetry.lock", "pdm.lock"]:
        endpoint = f"repos/{GITHUB_ORG}/{repo}/contents/{lock_file}"
        data = gh_api(endpoint)
        if data and isinstance(data, dict) and data.get("content"):
            try:
                content = base64.b64decode(data["content"]).decode("utf-8")
                pkgs = _parse_toml_lock_inventory(content, lock_file)
                packages.extend(
                    {"name": p[0], "version": p[1], "ecosystem": "PyPI"} for p in pkgs
                )
            except (ValueError, UnicodeDecodeError):
                pass
            break
        time.sleep(RATE_LIMIT_SLEEP)

    # Check for npm lock file (too large for contents API, use a different approach)
    # For package.json we can get direct deps
    endpoint = f"repos/{GITHUB_ORG}/{repo}/contents/package.json"
    data = gh_api(endpoint)
    if data and isinstance(data, dict) and data.get("content"):
        try:
            content = base64.b64decode(data["content"]).decode("utf-8")
            pkg_json = json.loads(content)
            for section in ("dependencies", "devDependencies"):
                for name, ver_spec in pkg_json.get(section, {}).items():
                    # Strip version prefixes (^, ~, >=)
                    ver = re.sub(r"^[~^>=<]*", "", ver_spec).strip()
                    if ver and re.match(r"\d", ver):
                        packages.append(
                            {"name": name, "version": ver, "ecosystem": "npm"},
                        )
        except (json.JSONDecodeError, ValueError):
            pass

    return packages


def _parse_toml_lock_inventory(content: str, _filename: str) -> list[tuple[str, str]]:
    """Extract (name, version) pairs from a TOML-based lock file."""
    packages = []
    name_pattern = re.compile(r'^name\s*=\s*"([\w][\w.-]*)"', re.MULTILINE)
    version_pattern = re.compile(r'^version\s*=\s*"(\d+[\d.]*\w*)"', re.MULTILINE)

    # Split by [[package]] sections
    sections = re.split(r"^\[\[package\]\]", content, flags=re.MULTILINE)
    for section in sections[1:]:  # Skip preamble
        name_m = name_pattern.search(section)
        ver_m = version_pattern.search(section)
        if name_m and ver_m:
            packages.append((name_m.group(1), ver_m.group(1)))

    return packages


def scan_osv_batch(packages: list[dict]) -> list[dict]:
    """Query OSV.dev batch endpoint for known vulnerabilities.

    Sends up to 100 packages per request.
    Returns list of {package, version, ecosystem, vulns: [...]} entries.
    """
    results = []

    for i in range(0, len(packages), OSV_BATCH_SIZE):
        batch = packages[i : i + OSV_BATCH_SIZE]
        queries = [
            {
                "version": pkg["version"],
                "package": {"name": pkg["name"], "ecosystem": pkg["ecosystem"]},
            }
            for pkg in batch
        ]

        payload = json.dumps({"queries": queries}).encode("utf-8")
        req = urllib.request.Request(
            "https://api.osv.dev/v1/querybatch",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "supply-chain-audit/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(  # noqa: S310
                req, timeout=OSV_REQUEST_TIMEOUT_SECONDS,
            ) as resp:
                data = json.loads(resp.read())
                batch_results = data.get("results", [])
                for j, result in enumerate(batch_results):
                    vulns = result.get("vulns", [])
                    if vulns:
                        pkg = batch[j]
                        results.append(
                            {
                                "name": pkg["name"],
                                "version": pkg["version"],
                                "ecosystem": pkg["ecosystem"],
                                "vulns": [
                                    {
                                        "id": v.get("id", ""),
                                        "summary": v.get("summary", "")[:120],
                                        "severity": _extract_osv_severity(v),
                                        "aliases": v.get("aliases", [])[:3],
                                    }
                                    for v in vulns
                                ],
                            },
                        )
        except (
            urllib.error.URLError,
            json.JSONDecodeError,
            TimeoutError,
            OSError,
        ) as exc:
            print(f"    OSV batch query failed: {exc}")

        time.sleep(OSV_BATCH_SLEEP_SECONDS)

    return results


def _extract_osv_severity(vuln: dict) -> str:
    """Extract severity from OSV vulnerability entry."""
    severity_list = vuln.get("severity", [])
    for s in severity_list:
        if s.get("type") == "CVSS_V3":
            score_str = s.get("score", "")
            # Parse CVSS score from vector string
            if "/" in score_str:
                # It's a vector string, not a score
                pass
            else:
                try:
                    score = float(score_str)
                except (ValueError, TypeError):
                    pass
                else:
                    if score >= CVSS_CRITICAL_THRESHOLD:
                        return "critical"
                    if score >= CVSS_HIGH_THRESHOLD:
                        return "high"
                    if score >= CVSS_MEDIUM_THRESHOLD:
                        return "medium"
                    return "low"
    # Check database_specific severity
    db_specific = vuln.get("database_specific", {})
    gh_severity = db_specific.get("severity")
    if gh_severity:
        return gh_severity.lower()
    return "unknown"


def _parse_legacy_protection_checks(data: dict) -> list[str]:
    """Extract required status check names from legacy branch protection."""
    rsc = data.get("required_status_checks", {})
    if not rsc:
        return []
    checks = [check.get("context", "") for check in rsc.get("checks", [])]
    return checks or list(rsc.get("contexts", []))


def _legacy_branch_protection_result(data: dict) -> dict:
    """Build protection result dict from legacy branch protection API."""
    return {
        "required_checks": _parse_legacy_protection_checks(data),
        "source": "branch_protection",
        "enforce_admins": bool(data.get("enforce_admins", {}).get("enabled", False)),
        "required_reviews": bool(data.get("required_pull_request_reviews")),
        "required_signatures": bool(
            data.get("required_signatures", {}).get("enabled", False),
        ),
        "allow_force_pushes": bool(
            data.get("allow_force_pushes", {}).get("enabled", False),
        ),
        "allow_deletions": bool(data.get("allow_deletions", {}).get("enabled", False)),
    }


def _collect_ruleset_required_checks(repo: str) -> list[str]:
    """Collect required status checks from active branch rulesets."""
    required_checks: list[str] = []
    rulesets = gh_api(f"repos/{GITHUB_ORG}/{repo}/rulesets")
    if not rulesets or not isinstance(rulesets, list):
        return required_checks

    for rs in rulesets:
        if rs.get("enforcement") != "active" or rs.get("target") != "branch":
            continue
        rs_id = rs.get("id")
        if not rs_id:
            continue
        detail = gh_api(f"repos/{GITHUB_ORG}/{repo}/rulesets/{rs_id}")
        time.sleep(RATE_LIMIT_SLEEP)
        if not detail or not isinstance(detail, dict):
            continue
        for rule in detail.get("rules", []):
            if rule.get("type") != "required_status_checks":
                continue
            params = rule.get("parameters", {}) or {}
            for check in params.get("required_status_checks", []):
                ctx = check.get("context", "")
                if ctx and ctx not in required_checks:
                    required_checks.append(ctx)
    return required_checks


def collect_branch_protection(repo: str) -> dict:
    """Fetch branch protection rules for the default branch.

    Checks both legacy branch protection API and the newer rulesets API,
    since repos may use either or both.
    """
    endpoint = f"repos/{GITHUB_ORG}/{repo}/branches/main/protection"
    data = gh_api(endpoint)
    if data and isinstance(data, dict) and "message" not in data:
        return _legacy_branch_protection_result(data)

    required_checks = _collect_ruleset_required_checks(repo)
    if not required_checks:
        return {"required_checks": [], "source": "none", "error": "not_found"}

    return {
        "required_checks": required_checks,
        "source": "rulesets",
        "enforce_admins": False,
        "required_reviews": True,
        "required_signatures": False,
        "allow_force_pushes": False,
        "allow_deletions": False,
    }


def collect_protection_changes(repo: str, start_date: str, end_date: str) -> list[dict]:
    """Fetch branch protection modification events from repo activity API."""
    endpoint = f"repos/{GITHUB_ORG}/{repo}/activity"
    data = gh_api(endpoint, paginate=True)
    if not data or not isinstance(data, list):
        return []

    changes = []
    for event in data:
        activity_type = event.get("activity_type", "")
        timestamp = event.get("timestamp", "")[:10]

        if activity_type != "branch_protection_rule":
            continue
        if timestamp < start_date or timestamp > end_date:
            continue

        actor = event.get("actor") or {}
        changes.append(
            {
                "repo": repo,
                "timestamp": event.get("timestamp", ""),
                "actor_login": actor.get("login", "unknown"),
                "actor_type": actor.get("type", "unknown"),
                "ref": event.get("ref", ""),
            },
        )

    return changes


def _load_cached_repo_counts(cache_dir: Path, repo: str) -> tuple[int, int]:
    """Return commit and PR counts from cached repo data."""
    commits = read_cache_file(cache_dir, "commits", f"{repo}.json") or []
    prs = read_cache_file(cache_dir, "prs", f"{repo}.json") or []
    return len(commits), len(prs)


def _report_osv_scan_results(inventory: list[dict], vuln_results: list[dict]) -> None:
    """Print OSV vulnerability scan summary."""
    if not inventory:
        print("  No lock files found, skipping OSV scan")
        return
    print(f"  Found {len(inventory)} packages, querying OSV...")
    if vuln_results:
        total_vulns = sum(len(v["vulns"]) for v in vuln_results)
        print(
            f"  \u26a0\ufe0f  {len(vuln_results)} packages with {total_vulns} known vulnerabilities",
        )
    else:
        print("  \u2705 No known vulnerabilities found")


def _scan_osv_for_repo(repo: str) -> list[dict]:
    """Scan package inventory for known vulnerabilities via OSV.dev."""
    print("  Scanning package inventory against OSV.dev...")
    inventory = collect_package_inventory(repo)
    vuln_results = scan_osv_batch(inventory) if inventory else []
    _report_osv_scan_results(inventory, vuln_results)
    return vuln_results


def _collect_repo_artifacts(repo: str, start_date: str, end_date: str) -> dict:
    """Collect all audit artifacts for a single repo."""
    print(f"  Fetching commits ({start_date} to {end_date})...")
    commits = collect_commits(repo, start_date, end_date)
    print(f"  Found {len(commits)} commits")

    print("  Fetching associated PRs...")
    prs = collect_prs_for_commits(repo, commits)
    print(f"  Found {len(prs)} PRs")

    print("  Fetching check suites...")
    checks = collect_check_suites(repo, commits)
    print(f"  Collected checks for {len(checks)} commits")

    print("  Analyzing dependency changes...")
    deps = collect_dep_changes(repo, start_date, end_date, commits)
    print(f"  Found {len(deps)} dependency changes")

    vuln_results = _scan_osv_for_repo(repo)

    print("  Fetching renovate config...")
    renovate_config = collect_renovate_config(repo)
    cooldown = renovate_config.get("default_cooldown_days")
    major_cd = renovate_config.get("major_cooldown_days")
    print(
        f"  Cooldown: {cooldown} days (major: {major_cd} days), source: {renovate_config['source']}",
    )

    print("  Fetching PR commit histories and reviews...")
    pr_audits = collect_pr_commits_and_reviews(repo, prs)
    total_pr_commits = sum(a["commit_count"] for a in pr_audits)
    print(
        f"  Collected {total_pr_commits} PR branch commits across {len(pr_audits)} PRs",
    )

    print("  Fetching branch protection rules...")
    protection = collect_branch_protection(repo)
    required = protection.get("required_checks", [])
    print(f"  Required checks: {required or '(none configured)'}")

    print("  Checking for protection rule changes...")
    protection_changes = collect_protection_changes(repo, start_date, end_date)
    print(f"  Protection changes in window: {len(protection_changes)}")

    return {
        "commits": commits,
        "prs": prs,
        "checks": checks,
        "deps": deps,
        "pr_audits": pr_audits,
        "renovate_config": renovate_config,
        "vuln_results": vuln_results,
        "protection": protection,
        "protection_changes": protection_changes,
    }


def _write_repo_cache_files(cache_dir: Path, repo: str, artifacts: dict) -> None:
    """Persist collected repo artifacts to the cache directory."""
    write_cache_file(cache_dir, "commits", f"{repo}.json", artifacts["commits"])
    write_cache_file(cache_dir, "prs", f"{repo}.json", artifacts["prs"])
    write_cache_file(cache_dir, "checks", f"{repo}.json", artifacts["checks"])
    write_cache_file(cache_dir, "deps", f"{repo}.json", artifacts["deps"])
    write_cache_file(cache_dir, "pr_audits", f"{repo}.json", artifacts["pr_audits"])
    write_cache_file(
        cache_dir, "renovate", f"{repo}.json", artifacts["renovate_config"],
    )
    write_cache_file(cache_dir, "vulns", f"{repo}.json", artifacts["vuln_results"])
    write_cache_file(
        cache_dir,
        "protection",
        f"{repo}.json",
        {
            "rules": artifacts["protection"],
            "changes": artifacts["protection_changes"],
        },
    )


def collect_repo(
    repo: str,
    start_date: str,
    end_date: str,
    cache_dir: Path,
    *,
    force: bool = False,
) -> tuple[int, int]:
    """Collect all data for a single repo. Returns (commit_count, pr_count)."""
    print(f"\n{'=' * 60}")
    print(f"  Collecting: {GITHUB_ORG}/{repo}")
    print(f"{'=' * 60}")

    if not force and has_cached_data(cache_dir, repo, "commits"):
        print(f"  [cached] Skipping {repo} (already collected)")
        return _load_cached_repo_counts(cache_dir, repo)

    artifacts = _collect_repo_artifacts(repo, start_date, end_date)
    _write_repo_cache_files(cache_dir, repo, artifacts)

    commits = artifacts["commits"]
    prs = artifacts["prs"]
    deps = artifacts["deps"]
    print(
        f"  [done] {repo}: {len(commits)} commits, {len(prs)} PRs, {len(deps)} dep changes",
    )
    return len(commits), len(prs)


def main() -> None:
    """Entry point for data collection."""
    parser = argparse.ArgumentParser(description="Supply chain audit data collector")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--cache-dir", default=".supply-chain-audit/cache", help="Cache directory",
    )
    parser.add_argument(
        "--force", action="store_true", help="Force re-collection even if cached",
    )
    parser.add_argument(
        "--repos", nargs="*", help="Specific repos to collect (default: all)",
    )
    args = parser.parse_args()

    try:
        datetime.strptime(args.start, DATE_FORMAT).replace(tzinfo=UTC)
        datetime.strptime(args.end, DATE_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        print("ERROR: Dates must be in YYYY-MM-DD format", file=sys.stderr)
        sys.exit(1)

    gh_version = get_gh_version()
    if "unknown" in gh_version:
        print(
            "ERROR: gh CLI not found. Install it and run 'gh auth login'",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"Using: {gh_version}")

    repos = args.repos or TARGET_REPOS
    cache_dir = get_cache_dir(args.cache_dir, args.start, args.end)
    ensure_cache_structure(cache_dir)

    print("\nSupply Chain Audit - Data Collection")
    print(f"Time window: {args.start} to {args.end}")
    print(f"Repos: {len(repos)}")
    print(f"Cache: {cache_dir}")

    total_commits = 0
    total_prs = 0

    for repo in repos:
        c, p = collect_repo(repo, args.start, args.end, cache_dir, force=args.force)
        total_commits += c
        total_prs += p

    write_manifest(
        cache_dir, args.start, args.end, repos, gh_version, total_commits, total_prs,
    )

    print(f"\n{'=' * 60}")
    print("  Collection complete!")
    print(f"  Total commits: {total_commits}")
    print(f"  Total PRs: {total_prs}")
    print(f"  Cache directory: {cache_dir}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
