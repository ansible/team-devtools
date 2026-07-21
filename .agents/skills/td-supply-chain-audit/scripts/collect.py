"""Data collection for supply chain audit via GitHub CLI.

Fetches commits, PRs, check suites, and dependency file diffs for all
target repos within a specified time window. Results are cached as JSON
for idempotent re-runs.
"""
# pylint: disable=too-many-lines

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

try:
    from audit_models import (  # pylint: disable=import-error
        CheckSuite,
        Commit,
        DepChange,
        PullRequest,
    )
    from cache_utils import (  # pylint: disable=import-error
        TARGET_REPOS,
        ensure_cache_structure,
        get_cache_dir,
        has_cached_data,
        normalize_repo,
        read_cache_file,
        repo_cache_name,
        write_cache_file,
        write_manifest,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from audit_models import (
        CheckSuite,
        Commit,
        DepChange,
        PullRequest,
    )
    from cache_utils import (
        TARGET_REPOS,
        ensure_cache_structure,
        get_cache_dir,
        has_cached_data,
        normalize_repo,
        read_cache_file,
        repo_cache_name,
        write_cache_file,
        write_manifest,
    )


RATE_LIMIT_SLEEP = 0.5
RATE_LIMIT_RETRY_SLEEP_SECONDS = 60
PER_PAGE = 100
GH_API_TIMEOUT_SECONDS = 120
GH_VERSION_TIMEOUT_SECONDS = 10
REGISTRY_REQUEST_TIMEOUT_SECONDS = 10
OSV_REQUEST_TIMEOUT_SECONDS = 30
OSV_BATCH_SIZE = 1000
OSV_BATCH_SLEEP_SECONDS = 1
SCORECARD_REQUEST_TIMEOUT_SECONDS = 20
SCORECARD_CLI_TIMEOUT_SECONDS = 300
SCORECARD_CLI_DOWNLOAD_TIMEOUT_SECONDS = 120
SCORECARD_CLI_BIN = "scorecard"
# Pinned release used when auto-bootstrapping the CLI (linux/mac).
SCORECARD_CLI_VERSION = "v5.5.0"
# Full Scorecard suite minus Vulnerabilities. That check walks OSV for the
# dependency graph and can hang for 15+ minutes on larger repos (e.g.
# ansible-builder). Dependency CVEs are already covered by the audit's
# separate OSV.dev inventory pass.
SCORECARD_CLI_CHECKS = (
    "Binary-Artifacts,"
    "Branch-Protection,"
    "CI-Tests,"
    "CII-Best-Practices,"
    "Code-Review,"
    "Contributors,"
    "Dangerous-Workflow,"
    "Dependency-Update-Tool,"
    "Fuzzing,"
    "License,"
    "Maintained,"
    "Packaging,"
    "Pinned-Dependencies,"
    "SAST,"
    "Security-Policy,"
    "Signed-Releases,"
    "Token-Permissions"
)
MAX_COMMIT_MSG_LEN = 120
GITHUB_EXT_PREFIX_LEN = 7
GITHUB_EXT_EXPECTED_PARTS = 2
CVSS_CRITICAL_THRESHOLD = 9.0
CVSS_HIGH_THRESHOLD = 7.0
CVSS_MEDIUM_THRESHOLD = 4.0
DATE_FORMAT = "%Y-%m-%d"
SCORECARD_WORKFLOW_NAMES = {
    "scorecard.yml",
    "scorecard.yaml",
    "ossf-scorecard.yml",
    "ossf-scorecard.yaml",
    "openssf-scorecard.yml",
    "openssf-scorecard.yaml",
}
SCORECARD_ACTION_RE = re.compile(
    r"uses:\s*['\"]?ossf/scorecard-action@",
    re.IGNORECASE,
)
SCORECARD_PUBLISH_RE = re.compile(
    r"publish_results\s*:\s*(true|false)",
    re.IGNORECASE,
)
SCORECARD_SCHEDULE_RE = re.compile(r"^\s*schedule\s*:", re.MULTILINE)
SCORECARD_BRANCH_PROTECTION_RE = re.compile(
    r"^\s*branch_protection_rule\s*:",
    re.MULTILINE,
)
SCORECARD_SARIF_UPLOAD_RE = re.compile(
    r"codeql-action/upload-sarif",
    re.IGNORECASE,
)

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


def _gh_api_on_failure(
    endpoint: str,
    result: subprocess.CompletedProcess[str],
    *,
    paginate: bool,
) -> list | dict | None:
    """Handle a non-zero ``gh api`` exit: retry rate limits, else return None."""
    stderr_lower = result.stderr.lower()
    # Auth / SAML / permission failures are not rate limits — fail fast.
    if "saml" in stderr_lower or "sso" in stderr_lower:
        print(
            f"  ACCESS DENIED (SAML/SSO): {endpoint} — authorize the org token via gh auth refresh / SSO grant",
            file=sys.stderr,
        )
    elif "rate limit" in stderr_lower or "secondary rate limit" in stderr_lower:
        print("  Rate limited, sleeping 60s...", file=sys.stderr)
        time.sleep(RATE_LIMIT_RETRY_SLEEP_SECONDS)
        return gh_api(endpoint, paginate=paginate)
    elif "404" in result.stderr or "Not Found" in result.stderr:
        pass
    elif "403" in result.stderr or "forbidden" in stderr_lower:
        # Generic 403 (e.g. private repo without access) — do not retry forever.
        print(f"  FORBIDDEN: {endpoint}: {result.stderr[:200]}", file=sys.stderr)
    else:
        print(f"  ERROR ({result.returncode}): {result.stderr[:200]}", file=sys.stderr)
    return None


def gh_api(endpoint: str, *, paginate: bool = False) -> list | dict | None:
    """Call GitHub API via gh CLI.

    Args:
        endpoint: API endpoint path.
        paginate: Whether to follow pagination.

    Returns:
        Parsed JSON, or ``None`` on error.

    """
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
        return _gh_api_on_failure(endpoint, result, paginate=paginate)

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def get_gh_version() -> str:
    """Get the installed gh CLI version string.

    Returns:
        Version string or ``"unknown"``.

    """
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
    """Fetch all commits for a repo in the time window.

    Args:
        repo: Repository name.
        start_date: Audit window start (YYYY-MM-DD).
        end_date: Audit window end (YYYY-MM-DD).

    Returns:
        Serialized commit dicts.

    """
    endpoint = f"repos/{repo}/commits?since={start_date}T00:00:00Z&until={end_date}T23:59:59Z&per_page={PER_PAGE}"
    data = gh_api(endpoint, paginate=True)
    if not data or not isinstance(data, list):
        return []

    commits = []
    for item in data:
        commit = Commit.from_api(item, repo)
        commits.append(commit.to_dict())

    return commits


def collect_prs_for_commits(repo: str, commits: list[dict]) -> list[dict]:
    """Fetch associated PRs for each commit and PR details.

    Args:
        repo: Repository name.
        commits: Commit dicts (mutated in place to add ``associated_prs``).

    Returns:
        Serialized PR dicts.

    """
    prs_seen: set[int] = set()
    prs: list[dict] = []

    for commit_data in commits:
        sha = commit_data["sha"]
        endpoint = f"repos/{repo}/commits/{sha}/pulls"
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
            pr_detail = gh_api(f"repos/{repo}/pulls/{pr_num}")
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

    Args:
        repo: Repository name.
        prs: Serialized PR dicts.

    Returns:
        PR audit data dicts.

    """
    pr_audit_data: list[dict] = []

    for pr in prs:
        if not pr.get("merged"):
            continue

        pr_num = pr["number"]

        # Get all commits on the PR branch
        commits_endpoint = f"repos/{repo}/pulls/{pr_num}/commits?per_page=100"
        pr_commits = gh_api(commits_endpoint)
        time.sleep(RATE_LIMIT_SLEEP)

        if not pr_commits or not isinstance(pr_commits, list):
            pr_commits = []

        # Get reviews (approvals)
        reviews_endpoint = f"repos/{repo}/pulls/{pr_num}/reviews"
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
    """Fetch check suites for each commit.

    Args:
        repo: Repository name.
        commits: Commit dicts.

    Returns:
        Check suites keyed by commit SHA.

    """
    checks_by_sha: dict[str, list[dict]] = {}

    for commit_data in commits:
        sha = commit_data["sha"]
        endpoint = f"repos/{repo}/commits/{sha}/check-suites"
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
    """Decode base64 GitHub contents API response to JSON.

    Args:
        data: GitHub contents API response dict.

    Returns:
        Parsed JSON content, or ``None`` on failure.

    """
    if not data.get("content"):
        return None
    try:
        content = base64.b64decode(data["content"]).decode("utf-8")
        return json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None


def _load_renovate_config_at_paths(config_paths: list[str]) -> dict | None:
    """Try loading renovate config from a list of GitHub contents API paths.

    Args:
        config_paths: GitHub contents API paths to try.

    Returns:
        Parsed renovate config, or ``None`` if not found.

    """
    for path in config_paths:
        data = gh_api(path)
        if data and isinstance(data, dict):
            raw = _decode_github_file_content(data)
            if raw:
                return raw
    return None


def _fetch_shared_renovate_config(extends: list) -> tuple[dict, str | None]:
    """Resolve shared renovate preset referenced in extends list.

    Args:
        extends: Renovate ``extends`` list entries.

    Returns:
        Tuple of (resolved config dict, source label or ``None``).

    """
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
    """Extract major-update cooldown days from renovate packageRules.

    Args:
        raw: Local renovate config.
        shared_config: Resolved shared preset config.

    Returns:
        Cooldown in days, or ``None`` if not configured.

    """
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

    Args:
        repo: Repository name.

    Returns:
        Dict with ``default_cooldown_days``, ``major_cooldown_days``,
        ``source``, and ``raw_config`` keys.

    """
    config: dict = {
        "source": "none",
        "default_cooldown_days": None,
        "major_cooldown_days": None,
    }

    config_paths = [
        f"repos/{repo}/contents/renovate.json",
        f"repos/{repo}/contents/.github/renovate.json",
        f"repos/{repo}/contents/renovate.json5",
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

    Args:
        age_str: Raw age value from renovate config.

    Returns:
        Age in days, or ``None`` if unparsable.

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
    repo: str,
    _start_date: str,
    end_date: str,
    commits: list[dict],
) -> list[dict]:
    """Identify dependency file changes by examining commits that touch dep files.

    Args:
        repo: Repository name.
        _start_date: Audit window start (unused, kept for API consistency).
        end_date: Audit window end (YYYY-MM-DD).
        commits: Commit dicts for this repo.

    Returns:
        Deduplicated and enriched dependency change dicts.

    """
    if not commits:
        return []

    first_sha = commits[-1]["sha"]
    last_sha = commits[0]["sha"]

    endpoint = f"repos/{repo}/compare/{first_sha}...{last_sha}"
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
    """Parse a unified diff patch to extract dependency additions/updates.

    Args:
        patch: Unified diff text.
        file_path: Path to the dependency file.
        repo: Repository name.
        ecosystem: Package ecosystem (``pypi`` or ``npm``).
        is_direct: Whether this is a direct (non-lock) dependency file.
        commit_sha: SHA of the commit introducing the change.
        commit_date: Date of the commit (YYYY-MM-DD).

    Returns:
        Serialized dependency change dicts.

    """
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
    patch: str,
    basename: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Parse npm ecosystem diff lines for package names and versions.

    Args:
        patch: Unified diff text.
        basename: Filename of the dependency file.

    Returns:
        Tuple of (added_deps, removed_deps) mappings.

    """
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

    These are TOML files with ``[[package]]`` sections containing name and
    version fields.

    Args:
        patch: Unified diff text.

    Returns:
        Tuple of (added_deps, removed_deps) mappings.

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
    """Parse Python ecosystem diff lines for package names and versions.

    Args:
        patch: Unified diff text.

    Returns:
        Tuple of (added_deps, removed_deps) mappings.

    """
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
    """Query PyPI or npm for release date of a dependency version.

    Args:
        dep: Dependency change dict (mutated in place).

    """
    if dep.get("new_version") is None:
        return

    pkg = dep["package_name"]
    version = dep["new_version"]
    ecosystem = dep["ecosystem"]

    try:
        if ecosystem == "pypi":
            url = f"https://pypi.org/pypi/{pkg}/{version}/json"
            req = urllib.request.Request(  # noqa: S310
                url,
                headers={"User-Agent": "supply-chain-audit/1.0"},
            )
            with urllib.request.urlopen(  # noqa: S310
                req,
                timeout=REGISTRY_REQUEST_TIMEOUT_SECONDS,
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
                url,
                headers={"User-Agent": "supply-chain-audit/1.0"},
            )
            with urllib.request.urlopen(  # noqa: S310
                req,
                timeout=REGISTRY_REQUEST_TIMEOUT_SECONDS,
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

    Args:
        repo: Repository name.

    Returns:
        List of ``{name, version, ecosystem}`` dicts.

    """
    packages: list[dict] = []

    # Check for Python lock files
    for lock_file in ["uv.lock", "poetry.lock", "pdm.lock"]:
        endpoint = f"repos/{repo}/contents/{lock_file}"
        data = gh_api(endpoint)
        if data and isinstance(data, dict) and data.get("content"):
            try:
                content = base64.b64decode(data["content"]).decode("utf-8")
                pkgs = _parse_toml_lock_inventory(content, lock_file)
                packages.extend({"name": p[0], "version": p[1], "ecosystem": "PyPI"} for p in pkgs)
            except (ValueError, UnicodeDecodeError):
                pass
            break
        time.sleep(RATE_LIMIT_SLEEP)

    npm_pkgs = _collect_npm_inventory(repo)
    packages.extend(npm_pkgs)

    return packages


def _collect_npm_inventory(repo: str) -> list[dict]:
    """Collect npm package inventory from lock files or package.json fallback."""
    tree_data = gh_api(f"repos/{repo}/git/trees/main")
    if tree_data and isinstance(tree_data, dict):
        for lock_file in ["pnpm-lock.yaml", "package-lock.json"]:
            for item in tree_data.get("tree", []):
                if item.get("path") != lock_file or not item.get("sha"):
                    continue
                blob_data = gh_api(f"repos/{repo}/git/blobs/{item['sha']}")
                if not blob_data or not isinstance(blob_data, dict):
                    continue
                try:
                    content = base64.b64decode(blob_data.get("content", "")).decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    continue
                parser = _parse_pnpm_lock_inventory if lock_file == "pnpm-lock.yaml" else _parse_package_lock_inventory
                return [{"name": p[0], "version": p[1], "ecosystem": "npm"} for p in parser(content)]
            time.sleep(RATE_LIMIT_SLEEP)

    endpoint = f"repos/{repo}/contents/package.json"
    data = gh_api(endpoint)
    if data and isinstance(data, dict) and data.get("content"):
        try:
            content = base64.b64decode(data["content"]).decode("utf-8")
            pkg_json = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return []
        packages = []
        for section in ("dependencies", "devDependencies"):
            for name, ver_spec in pkg_json.get(section, {}).items():
                ver = re.sub(r"^[~^>=<]*", "", ver_spec).strip()
                if ver and re.match(r"\d", ver):
                    packages.append({"name": name, "version": ver, "ecosystem": "npm"})
        return packages

    return []


def _parse_pnpm_lock_inventory(content: str) -> list[tuple[str, str]]:
    """Extract (name, version) pairs from a pnpm-lock.yaml file.

    Parses the packages section where entries look like:
      '@scope/name@1.2.3':
        resolution: ...

    """
    packages = []
    seen = set()
    in_packages = False
    pkg_pattern = re.compile(r"^\s{2}'?(@?[^@'\s]+(?:/@?[^@'\s]+)?)@(\d+[^(':\s]*)")

    for line in content.split("\n"):
        if line.strip() == "packages:":
            in_packages = True
            continue
        if not in_packages:
            continue
        m = pkg_pattern.match(line)
        if m:
            name, version = m.group(1), m.group(2)
            key = (name, version)
            if key not in seen:
                seen.add(key)
                packages.append((name, version))

    return packages


def _parse_package_lock_inventory(content: str) -> list[tuple[str, str]]:
    """Extract (name, version) pairs from a package-lock.json file."""
    packages = []
    try:
        data = json.loads(content)
        pkgs = data.get("packages", {})
        for path, info in pkgs.items():
            if not path:
                continue
            name = path.split("node_modules/")[-1] if "node_modules/" in path else path
            version = info.get("version", "")
            if name and version:
                packages.append((name, version))
    except (json.JSONDecodeError, ValueError):
        pass
    return packages


def _parse_toml_lock_inventory(content: str, _filename: str) -> list[tuple[str, str]]:
    """Extract (name, version) pairs from a TOML-based lock file.

    Args:
        content: Full text of the lock file.
        _filename: Filename (unused, kept for API consistency).

    Returns:
        List of (package_name, version) tuples.

    """
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

    Args:
        packages: List of ``{name, version, ecosystem}`` dicts.

    Returns:
        Entries with known vulnerabilities.

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
                req,
                timeout=OSV_REQUEST_TIMEOUT_SECONDS,
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
    """Extract severity from OSV vulnerability entry.

    Args:
        vuln: OSV vulnerability dict.

    Returns:
        Severity string (critical, high, medium, low, or unknown).

    """
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
    """Extract required status check names from legacy branch protection.

    Args:
        data: Legacy branch protection API response.

    Returns:
        Required check context names.

    """
    rsc = data.get("required_status_checks", {})
    if not rsc:
        return []
    checks = [check.get("context", "") for check in rsc.get("checks", [])]
    return checks or list(rsc.get("contexts", []))


def _legacy_branch_protection_result(data: dict) -> dict:
    """Build protection result dict from legacy branch protection API.

    Args:
        data: Legacy branch protection API response.

    Returns:
        Normalized protection result dict.

    """
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
    """Collect required status checks from active branch rulesets.

    Args:
        repo: Repository name.

    Returns:
        Required check context names.

    """
    required_checks: list[str] = []
    rulesets = gh_api(f"repos/{repo}/rulesets")
    if not rulesets or not isinstance(rulesets, list):
        return required_checks

    for rs in rulesets:
        if rs.get("enforcement") != "active" or rs.get("target") != "branch":
            continue
        rs_id = rs.get("id")
        if not rs_id:
            continue
        detail = gh_api(f"repos/{repo}/rulesets/{rs_id}")
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

    Args:
        repo: Repository name.

    Returns:
        Normalized protection result dict.

    """
    endpoint = f"repos/{repo}/branches/main/protection"
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
    """Fetch branch protection modification events from repo activity API.

    Args:
        repo: Repository name.
        start_date: Audit window start (YYYY-MM-DD).
        end_date: Audit window end (YYYY-MM-DD).

    Returns:
        Protection change event dicts.

    """
    endpoint = f"repos/{repo}/activity"
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


def _empty_scorecard_workflow() -> dict:
    """Return the default workflow metadata when no Scorecard workflow exists."""
    return {
        "present": False,
        "path": None,
        "publish_results": None,
        "has_schedule": False,
        "has_branch_protection_trigger": False,
        "uploads_sarif": False,
        "uses_scorecard_action": False,
    }


def _analyze_scorecard_workflow(content: str, path: str) -> dict:
    """Parse Scorecard workflow YAML text into normalized metadata.

    Args:
        content: Raw workflow file contents.
        path: Repository-relative workflow path.

    Returns:
        Workflow metadata dict.

    """
    publish_match = SCORECARD_PUBLISH_RE.search(content)
    publish_results = None
    if publish_match:
        publish_results = publish_match.group(1).lower() == "true"

    return {
        "present": True,
        "path": path,
        "publish_results": publish_results,
        "has_schedule": bool(SCORECARD_SCHEDULE_RE.search(content)),
        "has_branch_protection_trigger": bool(
            SCORECARD_BRANCH_PROTECTION_RE.search(content),
        ),
        "uploads_sarif": bool(SCORECARD_SARIF_UPLOAD_RE.search(content)),
        "uses_scorecard_action": bool(SCORECARD_ACTION_RE.search(content)),
    }


def _find_scorecard_workflow(repo: str) -> dict:
    """Locate and analyze a Scorecard GitHub Actions workflow in a repo.

    Args:
        repo: Repository name (``org/repo``).

    Returns:
        Workflow metadata dict.

    """
    workflows = gh_api(f"repos/{repo}/contents/.github/workflows")
    if not workflows or not isinstance(workflows, list):
        return _empty_scorecard_workflow()

    candidates = []
    for entry in workflows:
        name = (entry.get("name") or "").lower()
        path = entry.get("path") or ""
        if name in SCORECARD_WORKFLOW_NAMES or "scorecard" in name:
            candidates.append(path)

    if not candidates:
        return _empty_scorecard_workflow()

    # Prefer canonical scorecard.yml / scorecard.yaml names.
    candidates.sort(
        key=lambda p: (0 if Path(p).name.lower() in SCORECARD_WORKFLOW_NAMES else 1, p),
    )
    path = candidates[0]
    data = gh_api(f"repos/{repo}/contents/{path}")
    if not data or not isinstance(data, dict) or "content" not in data:
        result = _empty_scorecard_workflow()
        result["present"] = True
        result["path"] = path
        return result

    try:
        content = base64.b64decode(data["content"]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        result = _empty_scorecard_workflow()
        result["present"] = True
        result["path"] = path
        return result

    return _analyze_scorecard_workflow(content, path)


def _empty_scorecard_score(api_url: str) -> dict:
    """Return the default Scorecard score payload.

    Args:
        api_url: OpenSSF Scorecard API URL for the repo.

    Returns:
        Empty normalized score dict.

    """
    return {
        "available": False,
        "source": None,
        "score": None,
        "date": None,
        "scorecard_version": None,
        "commit": None,
        "checks": [],
        "api_url": api_url,
        "badge_url": f"{api_url}/badge",
        "error": None,
    }


def _normalize_scorecard_payload(data: dict, *, source: str, api_url: str) -> dict:
    """Normalize OpenSSF API or Scorecard CLI JSON into a common shape.

    Args:
        data: Raw Scorecard JSON document.
        source: ``api`` or ``cli``.
        api_url: Public OpenSSF API URL for the repository.

    Returns:
        Normalized score payload with ``available=True``.

    """
    checks = []
    for check in data.get("checks") or []:
        documentation = check.get("documentation") or {}
        doc_url = documentation.get("url", "")
        if not doc_url and isinstance(check.get("details"), list):
            # CLI JSON sometimes omits documentation; keep empty.
            doc_url = ""
        checks.append(
            {
                "name": check.get("name", ""),
                "score": check.get("score"),
                "reason": check.get("reason", ""),
                "documentation_url": doc_url,
            },
        )

    scorecard_meta = data.get("scorecard") or {}
    repo_meta = data.get("repo") or {}
    return {
        "available": True,
        "source": source,
        "score": data.get("score"),
        "date": data.get("date"),
        "scorecard_version": scorecard_meta.get("version"),
        "commit": repo_meta.get("commit"),
        "checks": checks,
        "api_url": api_url,
        "badge_url": f"{api_url}/badge",
        "error": None,
    }


def _fetch_openssf_scorecard(repo: str) -> dict:
    """Fetch published OpenSSF Scorecard results for a repository.

    Args:
        repo: Repository name (``org/repo``).

    Returns:
        Normalized score payload with availability flag.

    """
    api_url = f"https://api.securityscorecards.dev/projects/github.com/{repo}"
    result = _empty_scorecard_score(api_url)
    try:
        req = urllib.request.Request(  # noqa: S310
            api_url,
            headers={"User-Agent": "supply-chain-audit/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(  # noqa: S310
            req,
            timeout=SCORECARD_REQUEST_TIMEOUT_SECONDS,
        ) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        result["error"] = f"http_{exc.code}"
        return result
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        result["error"] = type(exc).__name__
        return result

    if not isinstance(data, dict) or data.get("score") is None:
        result["error"] = "api_payload_invalid"
        return result
    return _normalize_scorecard_payload(data, source="api", api_url=api_url)


def _resolve_github_token() -> str | None:
    """Resolve a GitHub token for Scorecard CLI rate limits.

    Returns:
        Token string, or ``None`` if unavailable.

    """
    for key in ("GITHUB_AUTH_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=GH_VERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    token = (result.stdout or "").strip()
    return token or None


def _scorecard_managed_bin_dir() -> Path:
    """Return the directory used for auto-downloaded Scorecard binaries."""
    return Path(".supply-chain-audit") / "bin"


def _scorecard_platform_triple() -> tuple[str, str] | None:
    """Map the current OS/arch to a Scorecard release asset triple.

    Returns:
        ``(goos, goarch)`` such as ``("darwin", "arm64")`` or
        ``("windows", "amd64")``, or ``None``.

    """
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        goos = "darwin"
    elif system == "linux":
        goos = "linux"
    elif system == "windows":
        goos = "windows"
    else:
        return None

    if machine in {"x86_64", "amd64"}:
        goarch = "amd64"
    elif machine in {"arm64", "aarch64"}:
        goarch = "arm64"
    else:
        return None
    return goos, goarch


def _scorecard_binary_name() -> str:
    """Return the Scorecard executable filename for the current OS."""
    if platform.system().lower() == "windows":
        return f"{SCORECARD_CLI_BIN}.exe"
    return SCORECARD_CLI_BIN


def _scorecard_release_asset_name(goos: str, goarch: str) -> str:
    """Build the Scorecard release tarball name for an OS/arch pair."""
    version = SCORECARD_CLI_VERSION.lstrip("v")
    return f"scorecard_{version}_{goos}_{goarch}.tar.gz"


def _scorecard_archive_member_names() -> tuple[str, ...]:
    """Filenames accepted inside a Scorecard release archive."""
    return (SCORECARD_CLI_BIN, f"{SCORECARD_CLI_BIN}.exe")


def _extract_scorecard_from_tar(tmp_path: Path, dest: Path) -> bool:
    """Extract the Scorecard binary from a release tarball.

    Args:
        tmp_path: Downloaded ``.tar.gz`` path.
        dest: Destination executable path.

    Returns:
        ``True`` on success.

    """
    with tarfile.open(tmp_path, "r:gz") as tar:
        member = None
        for entry in tar.getmembers():
            name = Path(entry.name).name
            if name in _scorecard_archive_member_names() and entry.isfile():
                member = entry
                break
        if member is None:
            print("  Scorecard CLI archive missing scorecard binary", file=sys.stderr)
            return False
        member.name = dest.name
        try:
            tar.extract(member, path=dest.parent, filter="data")
        except TypeError:
            # Python < 3.12 has no filter= argument.
            tar.extract(member, path=dest.parent)
    extracted = dest.parent / dest.name
    if extracted != dest:
        extracted.replace(dest)
    # Windows may not support POSIX mode bits; execution still works.
    with contextlib.suppress(OSError):
        dest.chmod(0o755)
    return True


def _download_scorecard_cli(dest: Path) -> str | None:
    """Download and extract the pinned Scorecard CLI into ``dest``.

    Args:
        dest: Destination path for the ``scorecard`` / ``scorecard.exe`` binary.

    Returns:
        Path string on success, or ``None`` on failure.

    """
    triple = _scorecard_platform_triple()
    if not triple:
        print(
            f"  Scorecard CLI auto-install unsupported on {platform.system()}/{platform.machine()}",
            file=sys.stderr,
        )
        return None

    goos, goarch = triple
    asset = _scorecard_release_asset_name(goos, goarch)
    url = f"https://github.com/ossf/scorecard/releases/download/{SCORECARD_CLI_VERSION}/{asset}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Bootstrapping Scorecard CLI {SCORECARD_CLI_VERSION} ({goos}/{goarch})...")

    try:
        req = urllib.request.Request(  # noqa: S310
            url,
            headers={"User-Agent": "supply-chain-audit/1.0"},
        )
        with (
            urllib.request.urlopen(  # noqa: S310
                req,
                timeout=SCORECARD_CLI_DOWNLOAD_TIMEOUT_SECONDS,
            ) as resp,
            tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp,
        ):
            shutil.copyfileobj(resp, tmp)
            tmp_path = Path(tmp.name)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"  Scorecard CLI download failed: {exc}", file=sys.stderr)
        return None

    try:
        if not _extract_scorecard_from_tar(tmp_path, dest):
            return None
    except (tarfile.TarError, OSError) as exc:
        print(f"  Scorecard CLI extract failed: {exc}", file=sys.stderr)
        return None
    finally:
        tmp_path.unlink(missing_ok=True)

    print(f"  Scorecard CLI ready: {dest}")
    return str(dest)


def _managed_scorecard_binary() -> Path:
    """Return the managed Scorecard binary path for this OS."""
    return _scorecard_managed_bin_dir() / _scorecard_binary_name()


def _is_usable_executable(path: Path) -> bool:
    """Return whether ``path`` looks like a usable Scorecard binary."""
    if not path.is_file():
        return False
    if platform.system().lower() == "windows":
        return True
    return os.access(path, os.X_OK)


def _ensure_scorecard_cli() -> str | None:
    """Locate the pinned managed Scorecard CLI, downloading it if needed.

    Prefers the audit-managed binary (pinned ``SCORECARD_CLI_VERSION``) over any
    ``scorecard`` on ``PATH`` so audits are reproducible and a poisoned PATH
    cannot override the pinned tool.

    Returns:
        Absolute path to the binary, or ``None`` if unavailable.

    """
    managed = _managed_scorecard_binary()
    if _is_usable_executable(managed):
        return str(managed.resolve())

    downloaded = _download_scorecard_cli(managed)
    if downloaded:
        return downloaded

    # Last resort: PATH (may differ from the pinned version).
    return shutil.which(SCORECARD_CLI_BIN) or shutil.which(f"{SCORECARD_CLI_BIN}.exe")


def _parse_scorecard_cli_stdout(stdout: str) -> dict | None:
    """Parse Scorecard CLI JSON from stdout, tolerating leading log lines.

    Args:
        stdout: Captured CLI standard output.

    Returns:
        Parsed JSON object, or ``None`` when no valid object is found.

    """
    text = stdout.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
        for raw_line in reversed(text.splitlines()):
            candidate = raw_line.strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                try:
                    payload = json.loads(candidate)
                    break
                except json.JSONDecodeError:
                    continue
    return payload if isinstance(payload, dict) else None


def _run_scorecard_cli(repo: str) -> dict:
    """Run the local Scorecard CLI against a repository.

    Args:
        repo: Repository name (``org/repo``).

    Returns:
        Normalized score payload (``available`` may be false on failure).

    """
    api_url = f"https://api.securityscorecards.dev/projects/github.com/{repo}"
    result = _empty_scorecard_score(api_url)
    cli = _ensure_scorecard_cli()
    if not cli:
        result["error"] = "scorecard_cli_not_installed"
        return result

    env = os.environ.copy()
    token = _resolve_github_token()
    if token:
        # Scorecard accepts any of these; set all common variants.
        env.setdefault("GITHUB_AUTH_TOKEN", token)
        env.setdefault("GH_TOKEN", token)
        env.setdefault("GITHUB_TOKEN", token)

    cmd = [
        cli,
        f"--repo=github.com/{repo}",
        "--format=json",
        "--show-details=false",
        f"--checks={SCORECARD_CLI_CHECKS}",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SCORECARD_CLI_TIMEOUT_SECONDS,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        result["error"] = "scorecard_cli_timeout"
        return result
    except OSError as exc:
        result["error"] = f"scorecard_cli_oserror:{type(exc).__name__}"
        return result

    stdout = proc.stdout or ""
    payload = _parse_scorecard_cli_stdout(stdout)
    if payload is None:
        kind = "empty_output" if not stdout.strip() else "bad_json"
        result["error"] = f"scorecard_cli_{kind}:exit_{proc.returncode}"
        return result

    normalized = _normalize_scorecard_payload(payload, source="cli", api_url=api_url)
    if proc.returncode != 0 and normalized.get("score") is None:
        result["error"] = f"scorecard_cli_exit_{proc.returncode}"
        return result
    # Record that CLI scores intentionally omit the OSV Vulnerabilities check.
    normalized["cli_checks_excluded"] = ["Vulnerabilities"]
    return normalized


def _print_scorecard_status(scorecard: dict) -> None:
    """Print a one-line Scorecard collection summary for a repo.

    Args:
        scorecard: Combined Scorecard audit payload.

    """
    workflow = scorecard.get("workflow") or {}
    score_data = scorecard.get("scorecard") or {}
    score_val = score_data.get("score")
    source = score_data.get("source") or "none"
    available = bool(score_data.get("available"))
    if available:
        score_msg = f"score={score_val} via {source}"
    else:
        err = score_data.get("error") or "unpublished"
        score_msg = f"score=unavailable ({err})"

    if workflow.get("present"):
        wf_path = workflow.get("path") or "scorecard.yml"
        print(f"  Scorecard workflow: {wf_path} ({score_msg})")
    else:
        print(f"  Scorecard workflow: missing ({score_msg})")


def collect_scorecard(repo: str, *, use_cli: bool = True) -> dict:
    """Collect Scorecard workflow presence and scores (API, then CLI fallback).

    Prefers the public OpenSSF Scorecard API. When no published score exists and
    ``use_cli`` is true, runs the local ``scorecard`` binary to evaluate the
    repo (requires CLI install + GitHub token for rate limits).

    Args:
        repo: Repository name (``org/repo``).
        use_cli: Whether to fall back to the Scorecard CLI.

    Returns:
        Combined Scorecard audit payload for caching.

    """
    workflow = _find_scorecard_workflow(repo)
    score = _fetch_openssf_scorecard(repo)
    # Prefer published API scores; only fall back to CLI when API has nothing.
    if not score.get("available") and use_cli:
        print("  OpenSSF API miss — running Scorecard CLI...")
        cli_score = _run_scorecard_cli(repo)
        if cli_score.get("available"):
            # Keep API error for diagnostics while using CLI results.
            cli_score["api_error"] = score.get("error")
            score = cli_score
        else:
            score["cli_error"] = cli_score.get("error")
            print(
                f"  Scorecard CLI unavailable for {repo}: {cli_score.get('error')}",
            )
    return {
        "repo": repo,
        "workflow": workflow,
        "scorecard": score,
        "collected_at": datetime.now(UTC).isoformat(),
    }


def _load_cached_repo_counts(cache_dir: Path, repo: str) -> tuple[int, int]:
    """Return commit and PR counts from cached repo data.

    Args:
        cache_dir: Root cache directory.
        repo: Repository name.

    Returns:
        Tuple of (commit_count, pr_count).

    """
    cache_name = f"{repo_cache_name(repo)}.json"
    commits = read_cache_file(cache_dir, "commits", cache_name) or []
    prs = read_cache_file(cache_dir, "prs", cache_name) or []
    return len(commits), len(prs)


def _report_osv_scan_results(inventory: list[dict], vuln_results: list[dict]) -> None:
    """Print OSV vulnerability scan summary.

    Args:
        inventory: Package inventory dicts.
        vuln_results: OSV scan result dicts.

    """
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
    """Scan package inventory for known vulnerabilities via OSV.dev.

    Args:
        repo: Repository name.

    Returns:
        Vulnerability scan results.

    """
    print("  Scanning package inventory against OSV.dev...")
    inventory = collect_package_inventory(repo)
    vuln_results = scan_osv_batch(inventory) if inventory else []
    _report_osv_scan_results(inventory, vuln_results)
    return vuln_results


def _collect_repo_artifacts(
    repo: str,
    start_date: str,
    end_date: str,
    *,
    use_scorecard_cli: bool = True,
) -> dict:
    """Collect all audit artifacts for a single repo.

    Args:
        repo: Repository name.
        start_date: Audit window start (YYYY-MM-DD).
        end_date: Audit window end (YYYY-MM-DD).
        use_scorecard_cli: Fall back to local Scorecard CLI when API has no score.

    Returns:
        Dict of collected artifact categories.

    """
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

    print("  Fetching OpenSSF Scorecard status...")
    scorecard = collect_scorecard(repo, use_cli=use_scorecard_cli)
    _print_scorecard_status(scorecard)

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
        "scorecard": scorecard,
    }


def _write_repo_cache_files(cache_dir: Path, repo: str, artifacts: dict) -> None:
    """Persist collected repo artifacts to the cache directory.

    Args:
        cache_dir: Root cache directory.
        repo: Repository name.
        artifacts: Collected artifact categories from ``_collect_repo_artifacts``.

    """
    cache_name = f"{repo_cache_name(repo)}.json"
    write_cache_file(cache_dir, "commits", cache_name, artifacts["commits"])
    write_cache_file(cache_dir, "prs", cache_name, artifacts["prs"])
    write_cache_file(cache_dir, "checks", cache_name, artifacts["checks"])
    write_cache_file(cache_dir, "deps", cache_name, artifacts["deps"])
    write_cache_file(cache_dir, "pr_audits", cache_name, artifacts["pr_audits"])
    write_cache_file(
        cache_dir,
        "renovate",
        cache_name,
        artifacts["renovate_config"],
    )
    write_cache_file(cache_dir, "vulns", cache_name, artifacts["vuln_results"])
    write_cache_file(
        cache_dir,
        "protection",
        cache_name,
        {
            "rules": artifacts["protection"],
            "changes": artifacts["protection_changes"],
        },
    )
    write_cache_file(cache_dir, "scorecard", cache_name, artifacts["scorecard"])


def _collect_and_cache_scorecard(
    repo: str,
    cache_dir: Path,
    *,
    use_scorecard_cli: bool = True,
) -> None:
    """Collect Scorecard data for a repo and write it to cache.

    Args:
        repo: Repository name.
        cache_dir: Root cache directory.
        use_scorecard_cli: Fall back to local Scorecard CLI when API has no score.

    """
    print("  Fetching OpenSSF Scorecard status...")
    scorecard = collect_scorecard(repo, use_cli=use_scorecard_cli)
    cache_name = f"{repo_cache_name(repo)}.json"
    write_cache_file(cache_dir, "scorecard", cache_name, scorecard)
    _print_scorecard_status(scorecard)


def collect_repo(
    repo: str,
    start_date: str,
    end_date: str,
    cache_dir: Path,
    *,
    force: bool = False,
    use_scorecard_cli: bool = True,
    refresh_scorecard: bool = False,
) -> tuple[int, int]:
    """Collect all data for a single repo.

    Args:
        repo: Repository name.
        start_date: Audit window start (YYYY-MM-DD).
        end_date: Audit window end (YYYY-MM-DD).
        cache_dir: Root cache directory.
        force: Re-collect even if cached data exists.
        use_scorecard_cli: Fall back to local Scorecard CLI when API has no score.
        refresh_scorecard: Re-collect Scorecard even when other artifacts are cached.

    Returns:
        Tuple of (commit_count, pr_count).

    """
    repo = normalize_repo(repo)
    print(f"\n{'=' * 60}")
    print(f"  Collecting: {repo}")
    print(f"{'=' * 60}")

    if not force and has_cached_data(cache_dir, repo, "commits"):
        print(f"  [cached] Skipping {repo} (already collected)")
        # Backfill/refresh Scorecard when missing, forced, or still unscored
        # so CLI auto-bootstrap fills gaps without a full re-collect.
        existing = read_cache_file(
            cache_dir,
            "scorecard",
            f"{repo_cache_name(repo)}.json",
        )
        score_meta = (existing.get("scorecard") or {}) if isinstance(existing, dict) else {}
        score_available = bool(score_meta.get("available"))
        cli_only = score_available and score_meta.get("source") == "cli"
        if refresh_scorecard or existing is None or not score_available:
            _collect_and_cache_scorecard(
                repo,
                cache_dir,
                use_scorecard_cli=use_scorecard_cli,
            )
        elif cli_only:
            # Re-check OpenSSF API only; keep the CLI snapshot if still unpublished.
            print("  Checking whether OpenSSF API score is now published...")
            api_only = collect_scorecard(repo, use_cli=False)
            if (api_only.get("scorecard") or {}).get("available"):
                write_cache_file(
                    cache_dir,
                    "scorecard",
                    f"{repo_cache_name(repo)}.json",
                    api_only,
                )
                _print_scorecard_status(api_only)
        return _load_cached_repo_counts(cache_dir, repo)

    artifacts = _collect_repo_artifacts(
        repo,
        start_date,
        end_date,
        use_scorecard_cli=use_scorecard_cli,
    )
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
        "--cache-dir",
        default=".supply-chain-audit/cache",
        help="Cache directory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-collection even if cached",
    )
    parser.add_argument(
        "--repos",
        nargs="*",
        help="Specific repos to collect (default: all)",
    )
    parser.add_argument(
        "--scorecard-cli",
        dest="scorecard_cli",
        action="store_true",
        default=True,
        help="Fall back to local Scorecard CLI when OpenSSF API has no score (default)",
    )
    parser.add_argument(
        "--skip-scorecard-cli",
        dest="scorecard_cli",
        action="store_false",
        help="Do not run the local Scorecard CLI; use OpenSSF API only",
    )
    parser.add_argument(
        "--refresh-scorecard",
        action="store_true",
        help="Re-fetch Scorecard (API/CLI) even when other repo data is cached",
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
    if args.scorecard_cli:
        # Lazy bootstrap: download only when a repo actually needs the CLI.
        managed = _managed_scorecard_binary()
        if _is_usable_executable(managed):
            print(f"Scorecard CLI: {managed.resolve()} (pinned {SCORECARD_CLI_VERSION})")
        else:
            print(
                f"Scorecard CLI: will auto-bootstrap {SCORECARD_CLI_VERSION} when OpenSSF API has no score",
            )
    else:
        print("Scorecard CLI: disabled (--skip-scorecard-cli)")

    repos = [normalize_repo(r) for r in (args.repos or TARGET_REPOS)]
    cache_dir = get_cache_dir(args.cache_dir, args.start, args.end)
    ensure_cache_structure(cache_dir)

    print("\nSupply Chain Audit - Data Collection")
    print(f"Time window: {args.start} to {args.end}")
    print(f"Repos: {len(repos)}")
    print(f"Cache: {cache_dir}")

    total_commits = 0
    total_prs = 0

    for repo in repos:
        c, p = collect_repo(
            repo,
            args.start,
            args.end,
            cache_dir,
            force=args.force,
            use_scorecard_cli=args.scorecard_cli,
            refresh_scorecard=args.refresh_scorecard,
        )
        total_commits += c
        total_prs += p

    write_manifest(
        cache_dir,
        args.start,
        args.end,
        repos,
        gh_version,
        total_commits,
        total_prs,
    )

    print(f"\n{'=' * 60}")
    print("  Collection complete!")
    print(f"  Total commits: {total_commits}")
    print(f"  Total PRs: {total_prs}")
    print(f"  Cache directory: {cache_dir}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
