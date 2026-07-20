"""Cache management for supply chain audit data.

Provides idempotent read/write with deterministic cache keys so that
repeat runs with the same time frame produce identical output.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

TARGET_REPOS = [
    "ansible/ansible-builder",
    "ansible/ansible-compat",
    "ansible/ansible-creator",
    "ansible/ansible-dev-environment",
    "ansible/ansible-lint",
    "ansible/ansible-navigator",
    "ansible/ansible-sign",
    "ansible/molecule",
    "ansible/pytest-ansible",
    "ansible/tox-ansible",
    "ansible/ansible-dev-tools",
    "ansible/vscode-ansible",
    "ansible/actions",
    "ansible/ansible-content-actions",
    "ansible/mkdocs-ansible",
    "ansible-automation-platform/ansible-devtools-container",
    "ansible-automation-platform/ansible-devspaces-container",
    "redhat-developer/abbenay",
]

# Default org when a bare repo name is passed (e.g. via --repos).
GITHUB_ORG = "ansible"


def normalize_repo(repo: str) -> str:
    """Return a canonical ``org/repo`` slug.

    Bare names (no slash) are assumed to live under ``GITHUB_ORG``.
    """
    if "/" in repo:
        return repo
    return f"{GITHUB_ORG}/{repo}"


def repo_cache_name(repo: str) -> str:
    """Filename-safe cache key for an ``org/repo`` slug (``org__repo``)."""
    return normalize_repo(repo).replace("/", "__")


def repo_from_cache_name(name: str) -> str:
    """Inverse of :func:`repo_cache_name` (stem without ``.json``)."""
    return name.replace("__", "/", 1)


def repo_github_url(repo: str, *, path: str = "") -> str:
    """Build a GitHub URL for a repo, optionally with a path suffix."""
    slug = normalize_repo(repo)
    base = f"https://github.com/{slug}"
    if path:
        return f"{base}/{path.lstrip('/')}"
    return base


def compute_cache_key(
    start_date: str,
    end_date: str,
    repos: list[str] | None = None,
) -> str:
    """Deterministic cache key from time frame and repo list.

    Args:
        start_date: Start of audit window (YYYY-MM-DD).
        end_date: End of audit window (YYYY-MM-DD).
        repos: Repository names (defaults to ``TARGET_REPOS``).

    Returns:
        Hex digest cache key.

    """
    if repos is None:
        repos = TARGET_REPOS
    payload = f"{start_date}|{end_date}|{','.join(sorted(repos))}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def get_cache_dir(base_dir: str, start_date: str, end_date: str) -> Path:
    """Return the cache directory path for a given audit window.

    Args:
        base_dir: Base cache directory.
        start_date: Audit window start (YYYY-MM-DD).
        end_date: Audit window end (YYYY-MM-DD).

    Returns:
        Resolved cache directory path.

    """
    key = compute_cache_key(start_date, end_date)
    return Path(base_dir) / key


def ensure_cache_structure(cache_dir: Path) -> None:
    """Create the cache directory tree if it doesn't exist.

    Args:
        cache_dir: Root cache directory.

    """
    subdirs = ["commits", "prs", "checks", "deps"]
    for sub in subdirs:
        (cache_dir / sub).mkdir(parents=True, exist_ok=True)


def read_cache_file(
    cache_dir: Path,
    subdir: str,
    filename: str,
) -> dict[str, object] | list[object] | None:
    """Read a JSON file from cache.

    Args:
        cache_dir: Root cache directory.
        subdir: Subdirectory name (e.g. ``commits``).
        filename: JSON filename.

    Returns:
        Parsed JSON data, or ``None`` if not found.

    """
    path = cache_dir / subdir / filename
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def write_cache_file(
    cache_dir: Path,
    subdir: str,
    filename: str,
    data: dict[str, object] | list[object],
) -> Path:
    """Write data as JSON to cache.

    Args:
        cache_dir: Root cache directory.
        subdir: Subdirectory name (e.g. ``commits``).
        filename: JSON filename.
        data: Data to serialize.

    Returns:
        Path to the written file.

    """
    (cache_dir / subdir).mkdir(parents=True, exist_ok=True)
    path = cache_dir / subdir / filename
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def has_cached_data(cache_dir: Path, repo: str, subdir: str) -> bool:
    """Check if cached data exists for a repo in a given subdirectory.

    Args:
        cache_dir: Root cache directory.
        repo: Repository name.
        subdir: Subdirectory to check.

    Returns:
        ``True`` if the cache file exists.

    """
    path = cache_dir / subdir / f"{repo_cache_name(repo)}.json"
    return path.exists()


def read_manifest(cache_dir: Path) -> dict[str, object] | None:
    """Read the audit manifest from cache.

    Args:
        cache_dir: Root cache directory.

    Returns:
        Manifest dict, or ``None`` if not found.

    """
    manifest_path = cache_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    with manifest_path.open(encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def write_manifest(
    cache_dir: Path,
    start_date: str,
    end_date: str,
    repos: list[str],
    gh_version: str,
    total_commits: int = 0,
    total_prs: int = 0,
) -> None:
    """Write the audit manifest to cache.

    Args:
        cache_dir: Root cache directory.
        start_date: Audit window start (YYYY-MM-DD).
        end_date: Audit window end (YYYY-MM-DD).
        repos: Repository names.
        gh_version: Installed gh CLI version string.
        total_commits: Total commits collected.
        total_prs: Total PRs collected.

    """
    key = compute_cache_key(start_date, end_date, repos)
    manifest = {
        "start_date": start_date,
        "end_date": end_date,
        "repos": repos,
        "cache_key": key,
        "collected_at": datetime.now(UTC).isoformat(),
        "gh_version": gh_version,
        "total_commits": total_commits,
        "total_prs": total_prs,
    }
    manifest_path = cache_dir / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def read_findings(cache_dir: Path) -> list[dict[str, object]]:
    """Read findings from cache.

    Args:
        cache_dir: Root cache directory.

    Returns:
        List of finding dicts.

    """
    path = cache_dir / "findings.json"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def write_findings(cache_dir: Path, findings: list[dict[str, object]]) -> None:
    """Write findings to cache.

    Args:
        cache_dir: Root cache directory.
        findings: Serialized finding dicts.

    """
    path = cache_dir / "findings.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, ensure_ascii=False)


def read_package_focus(cache_dir: Path) -> dict[str, object] | None:
    """Read package focus results from cache.

    Args:
        cache_dir: Root cache directory.

    Returns:
        Package focus dict, or ``None`` if not found.

    """
    path = cache_dir / "package_focus.json"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def write_package_focus(cache_dir: Path, data: dict[str, object]) -> None:
    """Write package focus results to cache.

    Args:
        cache_dir: Root cache directory.
        data: Package focus analysis results.

    """
    path = cache_dir / "package_focus.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def is_cache_complete(cache_dir: Path, repos: list[str] | None = None) -> bool:
    """Check if all repos have been fully collected.

    Args:
        cache_dir: Root cache directory.
        repos: Repository names (defaults to ``TARGET_REPOS``).

    Returns:
        ``True`` if all repos have cached commit data.

    """
    if repos is None:
        repos = TARGET_REPOS
    manifest = read_manifest(cache_dir)
    if manifest is None:
        return False
    return all(has_cached_data(cache_dir, repo, "commits") for repo in repos)


def get_all_cached_commits(cache_dir: Path) -> list[dict[str, object]]:
    """Load all cached commits across all repos.

    Args:
        cache_dir: Root cache directory.

    Returns:
        Combined list of commit dicts.

    """
    all_commits: list[dict[str, object]] = []
    commits_dir = cache_dir / "commits"
    if not commits_dir.exists():
        return []
    for f in sorted(commits_dir.iterdir()):
        if f.suffix == ".json":
            with f.open(encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, list):
                    all_commits.extend(data)
    return all_commits


def get_all_cached_prs(cache_dir: Path) -> list[dict[str, object]]:
    """Load all cached PRs across all repos.

    Args:
        cache_dir: Root cache directory.

    Returns:
        Combined list of PR dicts.

    """
    all_prs: list[dict[str, object]] = []
    prs_dir = cache_dir / "prs"
    if not prs_dir.exists():
        return []
    for f in sorted(prs_dir.iterdir()):
        if f.suffix == ".json":
            with f.open(encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, list):
                    all_prs.extend(data)
    return all_prs


def get_all_cached_checks(cache_dir: Path) -> dict[str, list[dict[str, object]]]:
    """Load all cached check suites, keyed by commit SHA.

    Args:
        cache_dir: Root cache directory.

    Returns:
        Check suites grouped by commit SHA.

    """
    checks_by_sha: dict[str, list[dict[str, object]]] = {}
    checks_dir = cache_dir / "checks"
    if not checks_dir.exists():
        return {}
    for f in sorted(checks_dir.iterdir()):
        if f.suffix == ".json":
            with f.open(encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    for sha, suites in data.items():
                        checks_by_sha.setdefault(sha, []).extend(suites)
    return checks_by_sha


def get_all_cached_deps(cache_dir: Path) -> list[dict[str, object]]:
    """Load all cached dependency changes.

    Args:
        cache_dir: Root cache directory.

    Returns:
        Combined list of dependency change dicts.

    """
    all_deps: list[dict[str, object]] = []
    deps_dir = cache_dir / "deps"
    if not deps_dir.exists():
        return []
    for f in sorted(deps_dir.iterdir()):
        if f.suffix == ".json":
            with f.open(encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, list):
                    all_deps.extend(data)
    return all_deps


def get_all_cached_protection(cache_dir: Path) -> dict[str, dict[str, object]]:
    """Load all cached branch protection data, keyed by repo name.

    Args:
        cache_dir: Root cache directory.

    Returns:
        Protection data grouped by repository.

    """
    protection: dict[str, dict[str, object]] = {}
    prot_dir = cache_dir / "protection"
    if not prot_dir.exists():
        return {}
    for f in sorted(prot_dir.iterdir()):
        if f.suffix == ".json":
            repo_name = repo_from_cache_name(f.stem)
            with f.open(encoding="utf-8") as fh:
                protection[repo_name] = json.load(fh)
    return protection


def get_all_cached_vulns(cache_dir: Path) -> dict[str, list[dict[str, object]]]:
    """Load all cached vulnerability scan results, keyed by repo name.

    Args:
        cache_dir: Root cache directory.

    Returns:
        Vulnerability results grouped by repository.

    """
    vulns: dict[str, list[dict[str, object]]] = {}
    vulns_dir = cache_dir / "vulns"
    if not vulns_dir.exists():
        return {}
    for f in sorted(vulns_dir.iterdir()):
        if f.suffix == ".json":
            repo_name = repo_from_cache_name(f.stem)
            with f.open(encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, list) and data:
                    vulns[repo_name] = data
    return vulns


def get_all_cached_renovate(cache_dir: Path) -> dict[str, dict[str, object]]:
    """Load all cached renovate configs, keyed by repo name.

    Args:
        cache_dir: Root cache directory.

    Returns:
        Renovate configs grouped by repository.

    """
    configs: dict[str, dict[str, object]] = {}
    reno_dir = cache_dir / "renovate"
    if not reno_dir.exists():
        return {}
    for f in sorted(reno_dir.iterdir()):
        if f.suffix == ".json":
            repo_name = repo_from_cache_name(f.stem)
            with f.open(encoding="utf-8") as fh:
                configs[repo_name] = json.load(fh)
    return configs


def get_all_cached_pr_audits(cache_dir: Path) -> list[dict[str, object]]:
    """Load all cached PR audit data (commits + reviews per PR).

    Args:
        cache_dir: Root cache directory.

    Returns:
        Combined list of PR audit dicts.

    """
    all_audits: list[dict[str, object]] = []
    audits_dir = cache_dir / "pr_audits"
    if not audits_dir.exists():
        return []
    for f in sorted(audits_dir.iterdir()):
        if f.suffix == ".json":
            with f.open(encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, list):
                    all_audits.extend(data)
    return all_audits
