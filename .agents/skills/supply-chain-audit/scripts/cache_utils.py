"""Cache management for supply chain audit data.

Provides idempotent read/write with deterministic cache keys so that
repeat runs with the same time frame produce identical output.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TARGET_REPOS = [
    "ansible-builder",
    "ansible-compat",
    "ansible-creator",
    "ansible-dev-environment",
    "ansible-lint",
    "ansible-navigator",
    "ansible-sign",
    "molecule",
    "pytest-ansible",
    "tox-ansible",
    "ansible-dev-tools",
    "vscode-ansible",
]

GITHUB_ORG = "ansible"


def compute_cache_key(start_date: str, end_date: str, repos: list[str] | None = None) -> str:
    """Deterministic cache key from time frame and repo list."""
    if repos is None:
        repos = TARGET_REPOS
    payload = f"{start_date}|{end_date}|{','.join(sorted(repos))}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def get_cache_dir(base_dir: str, start_date: str, end_date: str) -> Path:
    """Return the cache directory path for a given audit window."""
    key = compute_cache_key(start_date, end_date)
    return Path(base_dir) / key


def ensure_cache_structure(cache_dir: Path) -> None:
    """Create the cache directory tree if it doesn't exist."""
    subdirs = ["commits", "prs", "checks", "deps"]
    for sub in subdirs:
        (cache_dir / sub).mkdir(parents=True, exist_ok=True)


def read_cache_file(cache_dir: Path, subdir: str, filename: str) -> Any | None:
    """Read a JSON file from cache. Returns None if not found."""
    path = cache_dir / subdir / filename
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_cache_file(cache_dir: Path, subdir: str, filename: str, data: Any) -> Path:
    """Write data as JSON to cache. Returns the file path."""
    (cache_dir / subdir).mkdir(parents=True, exist_ok=True)
    path = cache_dir / subdir / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def has_cached_data(cache_dir: Path, repo: str, subdir: str) -> bool:
    """Check if cached data exists for a repo in a given subdirectory."""
    path = cache_dir / subdir / f"{repo}.json"
    return path.exists()


def read_manifest(cache_dir: Path) -> dict[str, Any] | None:
    """Read the audit manifest from cache."""
    manifest_path = cache_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)


def write_manifest(
    cache_dir: Path,
    start_date: str,
    end_date: str,
    repos: list[str],
    gh_version: str,
    total_commits: int = 0,
    total_prs: int = 0,
) -> None:
    """Write the audit manifest to cache."""
    key = compute_cache_key(start_date, end_date, repos)
    manifest = {
        "start_date": start_date,
        "end_date": end_date,
        "repos": repos,
        "cache_key": key,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "gh_version": gh_version,
        "total_commits": total_commits,
        "total_prs": total_prs,
    }
    manifest_path = cache_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def read_findings(cache_dir: Path) -> list[dict[str, Any]]:
    """Read findings from cache."""
    path = cache_dir / "findings.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_findings(cache_dir: Path, findings: list[dict[str, Any]]) -> None:
    """Write findings to cache."""
    path = cache_dir / "findings.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, ensure_ascii=False)


def read_package_focus(cache_dir: Path) -> dict[str, Any] | None:
    """Read package focus results from cache."""
    path = cache_dir / "package_focus.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_package_focus(cache_dir: Path, data: dict[str, Any]) -> None:
    """Write package focus results to cache."""
    path = cache_dir / "package_focus.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def is_cache_complete(cache_dir: Path, repos: list[str] | None = None) -> bool:
    """Check if all repos have been fully collected."""
    if repos is None:
        repos = TARGET_REPOS
    manifest = read_manifest(cache_dir)
    if manifest is None:
        return False
    for repo in repos:
        if not has_cached_data(cache_dir, repo, "commits"):
            return False
    return True


def get_all_cached_commits(cache_dir: Path) -> list[dict[str, Any]]:
    """Load all cached commits across all repos."""
    all_commits = []
    commits_dir = cache_dir / "commits"
    if not commits_dir.exists():
        return []
    for f in sorted(commits_dir.iterdir()):
        if f.suffix == ".json":
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, list):
                    all_commits.extend(data)
    return all_commits


def get_all_cached_prs(cache_dir: Path) -> list[dict[str, Any]]:
    """Load all cached PRs across all repos."""
    all_prs = []
    prs_dir = cache_dir / "prs"
    if not prs_dir.exists():
        return []
    for f in sorted(prs_dir.iterdir()):
        if f.suffix == ".json":
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, list):
                    all_prs.extend(data)
    return all_prs


def get_all_cached_checks(cache_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Load all cached check suites, keyed by commit SHA."""
    checks_by_sha: dict[str, list[dict[str, Any]]] = {}
    checks_dir = cache_dir / "checks"
    if not checks_dir.exists():
        return {}
    for f in sorted(checks_dir.iterdir()):
        if f.suffix == ".json":
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    for sha, suites in data.items():
                        checks_by_sha.setdefault(sha, []).extend(suites)
    return checks_by_sha


def get_all_cached_deps(cache_dir: Path) -> list[dict[str, Any]]:
    """Load all cached dependency changes."""
    all_deps = []
    deps_dir = cache_dir / "deps"
    if not deps_dir.exists():
        return []
    for f in sorted(deps_dir.iterdir()):
        if f.suffix == ".json":
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, list):
                    all_deps.extend(data)
    return all_deps


def get_all_cached_protection(cache_dir: Path) -> dict[str, dict[str, Any]]:
    """Load all cached branch protection data, keyed by repo name."""
    protection: dict[str, dict[str, Any]] = {}
    prot_dir = cache_dir / "protection"
    if not prot_dir.exists():
        return {}
    for f in sorted(prot_dir.iterdir()):
        if f.suffix == ".json":
            repo_name = f.stem
            with open(f, encoding="utf-8") as fh:
                protection[repo_name] = json.load(fh)
    return protection


def get_all_cached_vulns(cache_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Load all cached vulnerability scan results, keyed by repo name."""
    vulns: dict[str, list[dict[str, Any]]] = {}
    vulns_dir = cache_dir / "vulns"
    if not vulns_dir.exists():
        return {}
    for f in sorted(vulns_dir.iterdir()):
        if f.suffix == ".json":
            repo_name = f.stem
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, list) and data:
                    vulns[repo_name] = data
    return vulns


def get_all_cached_renovate(cache_dir: Path) -> dict[str, dict[str, Any]]:
    """Load all cached renovate configs, keyed by repo name."""
    configs: dict[str, dict[str, Any]] = {}
    reno_dir = cache_dir / "renovate"
    if not reno_dir.exists():
        return {}
    for f in sorted(reno_dir.iterdir()):
        if f.suffix == ".json":
            repo_name = f.stem
            with open(f, encoding="utf-8") as fh:
                configs[repo_name] = json.load(fh)
    return configs


def get_all_cached_pr_audits(cache_dir: Path) -> list[dict[str, Any]]:
    """Load all cached PR audit data (commits + reviews per PR)."""
    all_audits = []
    audits_dir = cache_dir / "pr_audits"
    if not audits_dir.exists():
        return []
    for f in sorted(audits_dir.iterdir()):
        if f.suffix == ".json":
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, list):
                    all_audits.extend(data)
    return all_audits
