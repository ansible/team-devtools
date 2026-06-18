"""Anomaly detection engine for supply chain audit.

Processes cached data to detect 13 categories of supply chain anomalies
including commit integrity, CI integrity, dependency provenance, review
integrity, and known vulnerabilities.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

from cache_utils import (
    get_all_cached_checks,
    get_all_cached_commits,
    get_all_cached_deps,
    get_all_cached_pr_audits,
    get_all_cached_protection,
    get_all_cached_prs,
    get_all_cached_renovate,
    get_all_cached_vulns,
    read_manifest,
    write_findings,
)
from models import Finding, FindingCategory, RiskLevel

GITHUB_NOREPLY_EMAILS = {"noreply@github.com", "github@users.noreply.github.com"}
JACCARD_THRESHOLD = 0.95
MIN_COMMIT_MESSAGE_LENGTH = 20
REPLICATED_MESSAGE_LOOKBACK = 50
FALLBACK_COOLDOWN_DAYS = 3


def tokenize(text: str) -> set[str]:
    """Tokenize text into a set of lowercase words."""
    return set(text.lower().split())


def jaccard_similarity(a: str, b: str) -> float:
    """Compute Jaccard similarity between two strings."""
    tokens_a = tokenize(a)
    tokens_b = tokenize(b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def detect_unsigned_commits(commits: list[dict]) -> list[Finding]:
    """Detect commits without valid GPG/SSH signatures."""
    findings = []
    for commit in commits:
        verification = commit.get("verification", {})
        if not verification.get("verified", False):
            findings.append(
                Finding(
                    category=FindingCategory.UNSIGNED_COMMIT,
                    risk_level=RiskLevel.MEDIUM,
                    repo=commit["repo"],
                    summary=f"Unsigned commit by {commit.get('author_login', 'unknown')}",
                    details=(
                        f"Commit {commit['sha'][:8]} is not cryptographically signed. "
                        f"Reason: {verification.get('reason', 'unsigned')}. "
                        f"Author: {commit.get('author_login', 'unknown')} "
                        f"({commit.get('author_email', '')})"
                    ),
                    commit_sha=commit["sha"],
                    date=commit.get("date"),
                    evidence={
                        "author": commit.get("author_login"),
                        "reason": verification.get("reason"),
                    },
                ),
            )
    return findings


def detect_github_web_signed(commits: list[dict], prs: list[dict]) -> list[Finding]:
    """Detect commits signed by GitHub that are NOT squash/merge commits from PRs.

    Squash merges and regular merges via the GitHub merge button are expected
    to be signed by web-flow. Only flag commits signed by GitHub that cannot
    be attributed to a PR merge operation (i.e., direct web UI edits).
    """
    pr_merge_shas = {
        pr.get("merge_commit_sha")
        for pr in prs
        if pr.get("merged") and pr.get("merge_commit_sha")
    }

    findings = []
    for commit in commits:
        verification = commit.get("verification", {})
        if not verification.get("verified", False):
            continue

        committer_email = commit.get("committer_email", "")
        committer_login = commit.get("committer_login", "")

        is_github_signed = (
            committer_email in GITHUB_NOREPLY_EMAILS
            or committer_login == "web-flow"
            or "github" in committer_email.lower()
        )

        if not is_github_signed:
            continue

        # Squash/merge commits from PRs are expected to be GitHub-signed
        if commit["sha"] in pr_merge_shas:
            continue

        # Also skip if the commit is associated with a PR (it's the merge result)
        if commit.get("associated_prs"):
            continue

        findings.append(
            Finding(
                category=FindingCategory.GITHUB_WEB_SIGNED,
                risk_level=RiskLevel.MEDIUM,
                repo=commit["repo"],
                summary=f"GitHub-web-signed commit (not a PR merge) by {commit.get('author_login', 'unknown')}",
                details=(
                    f"Commit {commit['sha'][:8]} is signed by GitHub but is NOT the "
                    f"merge commit of any known PR. This suggests a direct web UI edit. "
                    f"Author: {commit.get('author_login', 'unknown')}, "
                    f"Committer: {committer_login} ({committer_email}). "
                    f"A compromised GitHub account can create verified commits via "
                    f"the web editor without needing the author's signing key."
                ),
                commit_sha=commit["sha"],
                date=commit.get("date"),
                evidence={
                    "author": commit.get("author_login"),
                    "committer": committer_login,
                    "committer_email": committer_email,
                    "is_pr_merge": False,
                },
            ),
        )
    return findings


def detect_orphan_commits(commits: list[dict], prs: list[dict]) -> list[Finding]:
    """Detect commits with no associated pull request."""
    pr_merge_shas = {
        pr.get("merge_commit_sha") for pr in prs if pr.get("merge_commit_sha")
    }

    findings = []
    for commit in commits:
        associated = commit.get("associated_prs", [])
        sha = commit["sha"]

        if not associated and sha not in pr_merge_shas:
            msg_first_line = commit.get("message", "").split("\n")[0][:80]
            findings.append(
                Finding(
                    category=FindingCategory.ORPHAN_COMMIT,
                    risk_level=RiskLevel.HIGH,
                    repo=commit["repo"],
                    summary=f"Commit without PR: {msg_first_line}",
                    details=(
                        f"Commit {sha[:8]} by {commit.get('author_login', 'unknown')} "
                        f"has no associated pull request. Direct pushes to protected branches "
                        f"bypass code review. Message: '{msg_first_line}'"
                    ),
                    commit_sha=sha,
                    date=commit.get("date"),
                    evidence={
                        "author": commit.get("author_login"),
                        "message_preview": msg_first_line,
                    },
                ),
            )
    return findings


def detect_bypassed_ci(
    _commits: list[dict],
    prs: list[dict],
    checks: dict[str, list[dict]],
    protection: dict[str, dict],
) -> list[Finding]:
    """Detect PRs merged with failing REQUIRED CI checks.

    Only flags failures of checks listed in the repo's branch protection
    required status checks. Non-required/advisory checks (SonarQube, Codecov
    when not required, etc.) are ignored.
    """
    merged_prs = {pr["number"]: pr for pr in prs if pr.get("merged", False)}

    findings = []
    for pr in merged_prs.values():
        merge_sha = pr.get("merge_commit_sha")
        if not merge_sha:
            continue

        repo = pr["repo"]
        repo_protection = protection.get(repo, {})
        required_checks = set(
            repo_protection.get("rules", {}).get("required_checks", []),
        )

        suites = checks.get(merge_sha, [])
        if not suites:
            continue

        failed_required = []
        failed_advisory = []
        for suite in suites:
            conclusion = suite.get("conclusion")
            # Only flag actual failures — "skipped" means a job's `if:` condition
            # was false (e.g., publish jobs that only run on tags). This is normal
            # workflow control, not a CI bypass.
            if conclusion not in ("failure", "action_required", "timed_out"):
                continue

            app_name = suite.get("app_name", "unknown")

            is_required = False
            if required_checks:
                for rc in required_checks:
                    if app_name.lower() in rc.lower() or rc.lower() in app_name.lower():
                        is_required = True
                        break

            if is_required:
                failed_required.append(f"{app_name}: {conclusion}")
            else:
                failed_advisory.append(f"{app_name}: {conclusion}")

        if failed_required:
            findings.append(
                Finding(
                    category=FindingCategory.BYPASSED_CI,
                    risk_level=RiskLevel.CRITICAL,
                    repo=repo,
                    summary=f"PR #{pr['number']} merged with REQUIRED check failing",
                    details=(
                        f"PR #{pr['number']} ('{pr.get('title', '')}') was merged despite "
                        f"required check failures: {'; '.join(failed_required)}. "
                        f"Advisory failures (non-blocking): {'; '.join(failed_advisory) or 'none'}. "
                        f"Author: {pr.get('author_login', 'unknown')}, "
                        f"Merged at: {pr.get('merged_at', 'unknown')}"
                    ),
                    commit_sha=merge_sha,
                    pr_number=pr["number"],
                    date=pr.get("merged_at"),
                    evidence={
                        "pr_title": pr.get("title"),
                        "author": pr.get("author_login"),
                        "failed_required": failed_required,
                        "failed_advisory": failed_advisory,
                        "required_checks_configured": list(required_checks),
                    },
                ),
            )
        # If no required checks configured, don't flag individual PRs — there's
        # no gate to bypass. The weak posture is reported separately in
        # detect_protection_changes as a repo-level finding.
    return findings


def detect_protection_changes(protection: dict[str, dict]) -> list[Finding]:
    """Detect branch protection rule modifications and weak posture."""
    findings = []
    for repo, data in protection.items():
        changes = data.get("changes", [])
        findings.extend(
            Finding(
                category=FindingCategory.PROTECTION_CHANGED,
                risk_level=RiskLevel.CRITICAL,
                repo=repo,
                summary=f"Branch protection rules modified by {change.get('actor_login', 'unknown')}",
                details=(
                    f"Branch protection rules for {repo} were modified at "
                    f"{change.get('timestamp', 'unknown')} by "
                    f"{change.get('actor_login', 'unknown')} "
                    f"(account type: {change.get('actor_type', 'unknown')}). "
                    f"Ref: {change.get('ref', 'unknown')}. "
                    f"Protection rule changes can weaken security gates "
                    f"(e.g., removing required reviews or checks before merging malicious code)."
                ),
                date=change.get("timestamp"),
                evidence={
                    "actor": change.get("actor_login"),
                    "actor_type": change.get("actor_type"),
                    "ref": change.get("ref"),
                    "timestamp": change.get("timestamp"),
                },
            )
            for change in changes
        )

        rules = data.get("rules", {})
        if rules.get("error") == "not_found":
            continue

        if rules.get("allow_force_pushes"):
            findings.append(
                Finding(
                    category=FindingCategory.PROTECTION_CHANGED,
                    risk_level=RiskLevel.HIGH,
                    repo=repo,
                    summary=f"Force pushes allowed on {repo} default branch",
                    details=(
                        f"Branch protection for {repo} allows force pushes to the "
                        f"default branch. This means history can be rewritten, "
                        f"which could mask malicious commits."
                    ),
                    evidence={"allow_force_pushes": True},
                ),
            )

        required_checks = rules.get("required_checks", [])
        if not required_checks:
            findings.append(
                Finding(
                    category=FindingCategory.PROTECTION_CHANGED,
                    risk_level=RiskLevel.MEDIUM,
                    repo=repo,
                    summary=f"No required status checks configured for {repo}",
                    details=(
                        f"Branch protection for {repo} does not require any status "
                        f"checks to pass before merging. PRs can be merged regardless "
                        f"of CI results. This weakens the supply chain integrity "
                        f"guarantee — there is no automated gate preventing merges "
                        f"with failing tests or security scans."
                    ),
                    evidence={"required_checks": [], "has_protection": True},
                ),
            )

    return findings


def detect_post_merge_pushes(commits: list[dict], prs: list[dict]) -> list[Finding]:
    """Detect commits pushed to branches after their PR was merged/closed."""
    pr_index: dict[tuple[str, int], dict] = {}
    for pr in prs:
        if pr.get("merged") or pr.get("state") == "closed":
            pr_index[(pr["repo"], pr["number"])] = pr

    findings = []
    for commit in commits:
        repo = commit["repo"]
        commit_date = commit.get("date", "")

        for pr_num in commit.get("associated_prs", []):
            matching_pr = pr_index.get((repo, pr_num))

            if not matching_pr:
                continue

            merged_at = matching_pr.get("merged_at")
            if not merged_at:
                continue

            if commit_date > merged_at and commit["sha"] != matching_pr.get(
                "merge_commit_sha",
            ):
                findings.append(
                    Finding(
                        category=FindingCategory.POST_MERGE_PUSH,
                        risk_level=RiskLevel.CRITICAL,
                        repo=repo,
                        summary=f"Post-merge commit on PR #{pr_num} branch",
                        details=(
                            f"Commit {commit['sha'][:8]} was pushed to branch "
                            f"'{matching_pr.get('head_ref', '')}' AFTER PR #{pr_num} was merged "
                            f"at {merged_at}. Commit date: {commit_date}. "
                            f"Author: {commit.get('author_login', 'unknown')}. "
                            f"This could indicate branch tampering."
                        ),
                        commit_sha=commit["sha"],
                        pr_number=pr_num,
                        date=commit_date,
                        evidence={
                            "branch": matching_pr.get("head_ref"),
                            "merged_at": merged_at,
                            "commit_date": commit_date,
                            "author": commit.get("author_login"),
                        },
                    ),
                )
    return findings


def detect_replicated_messages(commits: list[dict]) -> list[Finding]:
    """Detect commit messages that are near-duplicates of earlier commits."""
    findings = []

    commits_by_repo: dict[str, list[dict]] = {}
    for commit in commits:
        commits_by_repo.setdefault(commit["repo"], []).append(commit)

    for repo, repo_commits in commits_by_repo.items():
        sorted_commits = sorted(repo_commits, key=lambda c: c.get("date", ""))

        for i, commit in enumerate(sorted_commits):
            msg = commit.get("message", "")
            if len(msg) < MIN_COMMIT_MESSAGE_LENGTH:
                continue

            for j in range(max(0, i - REPLICATED_MESSAGE_LOOKBACK), i):
                earlier = sorted_commits[j]
                earlier_msg = earlier.get("message", "")
                if len(earlier_msg) < MIN_COMMIT_MESSAGE_LENGTH:
                    continue

                if commit["sha"] == earlier["sha"]:
                    continue

                similarity = jaccard_similarity(msg, earlier_msg)
                if similarity >= JACCARD_THRESHOLD:
                    if commit.get("author_login") != earlier.get("author_login"):
                        risk = RiskLevel.HIGH
                    else:
                        risk = RiskLevel.LOW

                    msg_preview = msg.split("\n")[0][:60]
                    findings.append(
                        Finding(
                            category=FindingCategory.REPLICATED_MESSAGE,
                            risk_level=risk,
                            repo=repo,
                            summary=f"Replicated commit message: '{msg_preview}'",
                            details=(
                                f"Commit {commit['sha'][:8]} has a message nearly identical "
                                f"(similarity: {similarity:.2f}) to earlier commit {earlier['sha'][:8]}. "
                                f"New author: {commit.get('author_login', 'unknown')}, "
                                f"Original author: {earlier.get('author_login', 'unknown')}."
                            ),
                            commit_sha=commit["sha"],
                            date=commit.get("date"),
                            evidence={
                                "similarity": round(similarity, 3),
                                "original_sha": earlier["sha"],
                                "original_author": earlier.get("author_login"),
                                "new_author": commit.get("author_login"),
                            },
                        ),
                    )
                    break

    return findings


def detect_suspicious_dep_timing(
    deps: list[dict], renovate_configs: dict[str, dict],
) -> list[Finding]:
    """Detect dependencies that violate the configured renovate cooldown period.

    Compares each dep's days_since_release against the repo's configured
    minimumReleaseAge. Violations are CRITICAL (policy breach). Deps with no
    configured cooldown fall back to a 3-day heuristic at LOW severity.
    """
    findings = []
    for dep in deps:
        days = dep.get("days_since_release")
        if days is None or days < 0:
            continue

        repo = dep["repo"]
        config = renovate_configs.get(repo, {})
        default_cooldown = config.get("default_cooldown_days")
        major_cooldown = config.get("major_cooldown_days")

        # Determine which cooldown applies
        old_ver = dep.get("old_version", "")
        new_ver = dep.get("new_version", "")

        is_major = False
        if old_ver and new_ver:
            old_major = old_ver.split(".")[0] if "." in old_ver else old_ver
            new_major = new_ver.split(".")[0] if "." in new_ver else new_ver
            is_major = old_major != new_major

        effective_cooldown = (
            major_cooldown if is_major and major_cooldown else default_cooldown
        )

        if effective_cooldown is not None and days < effective_cooldown:
            # Policy violation — adopted before configured cooldown
            findings.append(
                Finding(
                    category=FindingCategory.COOLDOWN_VIOLATED,
                    risk_level=RiskLevel.CRITICAL,
                    repo=repo,
                    summary=(
                        f"'{dep['package_name']}' adopted {days}d after release "
                        f"(cooldown: {effective_cooldown}d)"
                    ),
                    details=(
                        f"Package '{dep['package_name']}' {new_ver} was released on "
                        f"{dep.get('release_date')} and adopted {days} day(s) later. "
                        f"The repo's renovate config requires a {effective_cooldown}-day "
                        f"cooldown ({'major update rule' if is_major and major_cooldown else 'default'}). "
                        f"This dep bypassed the configured safety period. "
                        f"Source: {config.get('source', 'unknown')}"
                    ),
                    commit_sha=dep.get("commit_sha"),
                    date=dep.get("commit_date"),
                    evidence={
                        "package": dep["package_name"],
                        "version": new_ver,
                        "release_date": dep.get("release_date"),
                        "days_since_release": days,
                        "configured_cooldown": effective_cooldown,
                        "is_major": is_major,
                        "config_source": config.get("source"),
                    },
                ),
            )
        elif effective_cooldown is None and days < FALLBACK_COOLDOWN_DAYS:
            # No cooldown configured — fallback heuristic for very rapid adoption
            findings.append(
                Finding(
                    category=FindingCategory.SUSPICIOUS_DEP_TIMING,
                    risk_level=RiskLevel.LOW,
                    repo=repo,
                    summary=(
                        f"'{dep['package_name']}' adopted {days}d after release (no cooldown configured)"
                    ),
                    details=(
                        f"Package '{dep['package_name']}' {new_ver} was released on "
                        f"{dep.get('release_date')} and adopted {days} day(s) later. "
                        f"No renovate minimumReleaseAge is configured for this repo. "
                        f"Consider adding a cooldown policy."
                    ),
                    commit_sha=dep.get("commit_sha"),
                    date=dep.get("commit_date"),
                    evidence={
                        "package": dep["package_name"],
                        "version": new_ver,
                        "release_date": dep.get("release_date"),
                        "days_since_release": days,
                        "configured_cooldown": None,
                    },
                ),
            )

    return findings


def detect_yanked_versions(deps: list[dict]) -> list[Finding]:
    """Detect dependencies using yanked or deleted versions."""
    return [
        Finding(
            category=FindingCategory.YANKED_VERSION,
            risk_level=RiskLevel.CRITICAL,
            repo=dep["repo"],
            summary=f"Yanked version: {dep['package_name']} {dep.get('new_version')}",
            details=(
                f"Package '{dep['package_name']}' version {dep.get('new_version')} "
                f"has been yanked/deprecated from the registry. This version may have "
                f"been compromised or contained critical bugs. "
                f"File: {dep.get('file_path', 'unknown')}, "
                f"Change type: {dep.get('change_type', 'unknown')}"
            ),
            commit_sha=dep.get("commit_sha"),
            date=dep.get("commit_date"),
            evidence={
                "package": dep["package_name"],
                "version": dep.get("new_version"),
                "file": dep.get("file_path"),
                "ecosystem": dep.get("ecosystem"),
            },
        )
        for dep in deps
        if dep.get("yanked")
    ]


def detect_post_approval_commits(pr_audits: list[dict]) -> list[Finding]:
    """Detect commits pushed to a PR branch after the last approval.

    Attack scenario: PR gets approved, attacker pushes additional commit
    before merge. If 'require last push approval' is off, the PR merges
    with unapproved code.
    """
    findings = []
    for audit in pr_audits:
        approvals = audit.get("approvals", [])
        commits = audit.get("commits", [])
        repo = audit.get("repo", "")
        pr_num = audit.get("pr_number", 0)

        if not approvals or not commits:
            continue

        last_approval_time = max(a["submitted_at"] for a in approvals)
        last_approver = next(
            (a["user"] for a in approvals if a["submitted_at"] == last_approval_time),
            "unknown",
        )

        post_approval = []
        for c in commits:
            commit_date = c.get("date", "")
            if commit_date > last_approval_time:
                post_approval.append(c)

        if not post_approval:
            continue

        pr_author = audit.get("pr_author", "")
        approver_logins = {a["user"] for a in approvals}

        # Categorize post-approval commits by author relationship
        from_pr_author = [
            c for c in post_approval if c.get("author_login", "") == pr_author
        ]
        from_approver = [
            c
            for c in post_approval
            if c.get("author_login", "") in approver_logins
            and c.get("author_login", "") != pr_author
        ]
        from_unknown_third_party = [
            c
            for c in post_approval
            if c.get("author_login", "") != pr_author
            and c.get("author_login", "") not in approver_logins
            and c.get("author_login", "") != "unknown"
        ]

        if from_unknown_third_party:
            risk = RiskLevel.CRITICAL
            summary = (
                f"PR #{pr_num}: {len(from_unknown_third_party)} commit(s) from "
                f"unknown third party pushed after approval"
            )
        elif from_approver:
            risk = RiskLevel.MEDIUM
            summary = (
                f"PR #{pr_num}: {len(from_approver)} commit(s) from approver "
                f"pushed after their own approval (self-authored fixup)"
            )
        else:
            risk = RiskLevel.HIGH
            summary = (
                f"PR #{pr_num}: {len(from_pr_author)} commit(s) pushed by PR "
                f"author after approval by {last_approver}"
            )

        details_parts = [
            f"PR #{pr_num} ('{audit.get('pr_title', '')}') in {repo} was approved "
            f"by {last_approver} at {last_approval_time}. ",
            f"After approval, {len(post_approval)} commit(s) were pushed: ",
        ]
        for c in post_approval[:5]:
            author = c.get("author_login", "unknown")
            msg = c.get("message", "").split("\n")[0][:60]
            details_parts.append(
                f"  - {c['sha'][:8]} by {author}: '{msg}' ({c.get('date', '')[:16]})",
            )

        findings.append(
            Finding(
                category=FindingCategory.POST_APPROVAL_COMMIT,
                risk_level=risk,
                repo=repo,
                summary=summary,
                details=" ".join(details_parts),
                pr_number=pr_num,
                date=audit.get("merged_at"),
                evidence={
                    "pr_author": pr_author,
                    "last_approver": last_approver,
                    "last_approval_time": last_approval_time,
                    "post_approval_commits": [
                        {
                            "sha": c["sha"][:8],
                            "author": c.get("author_login"),
                            "date": c.get("date"),
                        }
                        for c in post_approval
                    ],
                    "from_pr_author": len(from_pr_author),
                    "from_approver": len(from_approver),
                    "from_unknown_third_party": len(from_unknown_third_party),
                },
            ),
        )

    return findings


def detect_known_vulnerabilities(vulns: dict[str, list[dict]]) -> list[Finding]:
    """Flag packages with known CVEs/advisories from OSV.dev."""
    findings = []
    for repo, pkg_vulns in vulns.items():
        for entry in pkg_vulns:
            pkg_name = entry["name"]
            version = entry["version"]
            ecosystem = entry["ecosystem"]

            for vuln in entry.get("vulns", []):
                vuln_id = vuln.get("id", "unknown")
                severity = vuln.get("severity", "unknown")
                summary = vuln.get("summary", "No description")
                aliases = vuln.get("aliases", [])

                if severity in ("critical", "high"):
                    risk = RiskLevel.CRITICAL
                elif severity == "medium":
                    risk = RiskLevel.HIGH
                else:
                    risk = RiskLevel.MEDIUM

                alias_str = f" (aliases: {', '.join(aliases)})" if aliases else ""
                findings.append(
                    Finding(
                        category=FindingCategory.KNOWN_VULNERABILITY,
                        risk_level=risk,
                        repo=repo,
                        summary=f"{pkg_name}@{version}: {vuln_id}{alias_str}",
                        details=(
                            f"{ecosystem} package '{pkg_name}' version {version} in {repo} "
                            f"has known vulnerability {vuln_id}: {summary}"
                        ),
                        evidence={
                            "package": pkg_name,
                            "version": version,
                            "ecosystem": ecosystem,
                            "vuln_id": vuln_id,
                            "severity": severity,
                            "aliases": aliases,
                        },
                    ),
                )

    return findings


# Known bot account patterns
BOT_ACCOUNTS = {
    "ansibuddy",
    "dependabot[bot]",
    "renovate[bot]",
    "github-actions[bot]",
    "pre-commit-ci[bot]",
    "codecov[bot]",
    "mergify[bot]",
}


def _is_bot_account(login: str) -> bool:
    """Check if a login is a known bot account."""
    return login in BOT_ACCOUNTS or login.endswith("[bot]")


def detect_bot_only_approval(pr_audits: list[dict], prs: list[dict]) -> list[Finding]:
    """Detect merged PRs where all approvals came from bots (no human review).

    A PR merged with only bot approvals means no human examined the code diff
    before it landed on main.
    """
    findings = []

    pr_files_info: dict[tuple[str, int], dict] = {}
    for pr in prs:
        if pr.get("merged"):
            pr_files_info[(pr.get("repo", ""), pr.get("number", 0))] = pr

    for audit in pr_audits:
        approvals = audit.get("approvals", [])
        repo = audit.get("repo", "")
        pr_num = audit.get("pr_number", 0)

        if not approvals:
            continue

        human_approvals = [a for a in approvals if not _is_bot_account(a["user"])]
        bot_approvals = [a for a in approvals if _is_bot_account(a["user"])]

        if human_approvals:
            continue

        # All approvals are from bots
        bot_names = list({a["user"] for a in bot_approvals})
        pr_author = audit.get("pr_author", "")
        pr_title = audit.get("pr_title", "")

        # Determine risk based on PR characteristics
        is_bot_pr = _is_bot_account(pr_author)
        is_dep_only = any(
            kw in pr_title.lower()
            for kw in ("chore(deps)", "bump ", "update dependency", "lock file")
        )

        if is_bot_pr and is_dep_only:
            risk = RiskLevel.LOW
            summary = (
                f"PR #{pr_num}: bot-to-bot approval for dependency update "
                f"(approved by {', '.join(bot_names)})"
            )
        elif is_bot_pr:
            risk = RiskLevel.MEDIUM
            summary = (
                f"PR #{pr_num}: bot PR approved only by bot(s) "
                f"({', '.join(bot_names)}), no human review"
            )
        else:
            risk = RiskLevel.HIGH
            summary = (
                f"PR #{pr_num}: human-authored PR approved only by bot(s) "
                f"({', '.join(bot_names)}), no human review"
            )

        findings.append(
            Finding(
                category=FindingCategory.BOT_ONLY_APPROVAL,
                risk_level=risk,
                repo=repo,
                summary=summary,
                details=(
                    f"PR #{pr_num} ('{pr_title}') in {repo} by {pr_author} was merged "
                    f"with approvals only from: {', '.join(bot_names)}. "
                    f"No human reviewer approved this change before merge."
                ),
                pr_number=pr_num,
                date=audit.get("merged_at"),
                evidence={
                    "pr_author": pr_author,
                    "pr_title": pr_title,
                    "bot_approvers": bot_names,
                    "is_bot_pr": is_bot_pr,
                    "is_dep_only": is_dep_only,
                    "commit_count": audit.get("commit_count", 0),
                },
            ),
        )

    return findings


def detect_self_approval(pr_audits: list[dict]) -> list[Finding]:
    """Detect PRs where the author approved their own PR with no independent review.

    GitHub allows self-approval when branch protection doesn't enforce
    'require approval from someone other than the last pusher'. This is
    a serious process violation — the author is reviewing their own code.
    """
    findings = []

    for audit in pr_audits:
        approvals = audit.get("approvals", [])
        pr_author = audit.get("pr_author", "")
        repo = audit.get("repo", "")
        pr_num = audit.get("pr_number", 0)

        if not approvals or not pr_author:
            continue

        # Skip bot PRs — they can't meaningfully self-approve
        if _is_bot_account(pr_author):
            continue

        approver_logins = [a["user"] for a in approvals]
        human_approvers = [a for a in approver_logins if not _is_bot_account(a)]

        # Self-approval: author is the only human approver
        if human_approvers == [pr_author]:
            findings.append(
                Finding(
                    category=FindingCategory.SELF_APPROVED,
                    risk_level=RiskLevel.CRITICAL,
                    repo=repo,
                    summary=f"PR #{pr_num}: self-approved by author {pr_author} (no independent review)",
                    details=(
                        f"PR #{pr_num} ('{audit.get('pr_title', '')}') in {repo} was authored "
                        f"and approved by the same person ({pr_author}). No independent human "
                        f"reviewed this change before merge."
                    ),
                    pr_number=pr_num,
                    date=audit.get("merged_at"),
                    evidence={
                        "pr_author": pr_author,
                        "approvers": approver_logins,
                        "human_approvers": human_approvers,
                    },
                ),
            )
        elif pr_author in human_approvers and len(human_approvers) > 1:
            # Author approved alongside others — informational only
            others = [a for a in human_approvers if a != pr_author]
            findings.append(
                Finding(
                    category=FindingCategory.SELF_APPROVED,
                    risk_level=RiskLevel.LOW,
                    repo=repo,
                    summary=(
                        f"PR #{pr_num}: author {pr_author} self-approved "
                        f"(also reviewed by {', '.join(others)})"
                    ),
                    details=(
                        f"PR #{pr_num} in {repo} was approved by its author {pr_author} "
                        f"in addition to independent reviewer(s): {', '.join(others)}. "
                        f"The independent review satisfies policy, but self-approval is unusual."
                    ),
                    pr_number=pr_num,
                    date=audit.get("merged_at"),
                    evidence={
                        "pr_author": pr_author,
                        "approvers": approver_logins,
                        "human_approvers": human_approvers,
                        "independent_reviewers": others,
                    },
                ),
            )

    return findings


def _print_cache_stats(
    commits: list[dict],
    prs: list[dict],
    checks: dict[str, list[dict]],
    deps: list[dict],
    protection: dict[str, dict],
    pr_audits: list[dict],
    renovate_configs: dict[str, dict],
    vulns: dict[str, list[dict]],
) -> None:
    """Print summary statistics for loaded cache data."""
    print(f"  Commits on main: {len(commits)}")
    print(f"  PRs: {len(prs)}")
    print(f"  PR branch commits: {sum(a.get('commit_count', 0) for a in pr_audits)}")
    print(f"  Check suites: {sum(len(v) for v in checks.values())}")
    print(f"  Dep changes: {len(deps)}")
    print(f"  Repos with protection data: {len(protection)}")
    print(
        f"  Repos with renovate config: "
        f"{sum(1 for c in renovate_configs.values() if c.get('source') != 'none')}",
    )
    print(
        f"  Repos with vulnerability data: {len(vulns)} "
        f"({sum(len(v) for v in vulns.values())} affected packages)",
    )


def _run_detection_pass(
    step: str,
    description: str,
    detector: Callable[[], list[Finding]],
    result_message: Callable[[list[Finding]], str],
) -> list[Finding]:
    """Run a single detection pass and print its progress."""
    print(f"  {step} {description}...")
    findings = detector()
    print(f"          {result_message(findings)}")
    return findings


def _run_detection_passes(
    commits: list[dict],
    prs: list[dict],
    checks: dict[str, list[dict]],
    deps: list[dict],
    protection: dict[str, dict],
    pr_audits: list[dict],
    renovate_configs: dict[str, dict],
    vulns: dict[str, list[dict]],
) -> list[Finding]:
    """Execute all detection passes and return combined findings."""
    print("\nRunning detection passes...")

    pass_specs: list[
        tuple[str, str, Callable[[], list[Finding]], Callable[[list[Finding]], str]]
    ] = [
        (
            "[1/12]",
            "Unsigned commits",
            lambda: detect_unsigned_commits(commits),
            lambda findings: f"Found {len(findings)} unsigned commits",
        ),
        (
            "[2/12]",
            "GitHub-web-signed commits (excluding PR merges)",
            lambda: detect_github_web_signed(commits, prs),
            lambda findings: (
                f"Found {len(findings)} GitHub-web-signed commits (non-merge)"
            ),
        ),
        (
            "[3/12]",
            "Orphan commits (no PR)",
            lambda: detect_orphan_commits(commits, prs),
            lambda findings: f"Found {len(findings)} orphan commits",
        ),
        (
            "[4/12]",
            "Bypassed CI (required checks only)",
            lambda: detect_bypassed_ci(commits, prs, checks, protection),
            lambda findings: f"Found {len(findings)} bypassed CI instances",
        ),
        (
            "[5/12]",
            "Post-merge pushes",
            lambda: detect_post_merge_pushes(commits, prs),
            lambda findings: f"Found {len(findings)} post-merge pushes",
        ),
        (
            "[6/12]",
            "Replicated commit messages",
            lambda: detect_replicated_messages(commits),
            lambda findings: f"Found {len(findings)} replicated messages",
        ),
        (
            "[7/12]",
            "Dependency cooldown policy check",
            lambda: detect_suspicious_dep_timing(deps, renovate_configs),
            lambda findings: (
                f"Found {sum(1 for f in findings if f.category == FindingCategory.COOLDOWN_VIOLATED)} "
                f"cooldown violations, "
                f"{len(findings) - sum(1 for f in findings if f.category == FindingCategory.COOLDOWN_VIOLATED)} "
                f"heuristic flags"
            ),
        ),
        (
            "[8/12]",
            "Yanked/deleted versions",
            lambda: detect_yanked_versions(deps),
            lambda findings: f"Found {len(findings)} yanked versions",
        ),
        (
            "[9/12]",
            "Branch protection changes",
            lambda: detect_protection_changes(protection),
            lambda findings: f"Found {len(findings)} protection findings",
        ),
        (
            "[10/12]",
            "Post-approval commits in PRs",
            lambda: detect_post_approval_commits(pr_audits),
            lambda findings: f"Found {len(findings)} PRs with post-approval commits",
        ),
        (
            "[11/13]",
            "Bot-only approvals (no human review)",
            lambda: detect_bot_only_approval(pr_audits, prs),
            lambda findings: f"Found {len(findings)} PRs with bot-only approval",
        ),
        (
            "[12/13]",
            "Self-approved PRs",
            lambda: detect_self_approval(pr_audits),
            lambda findings: f"Found {len(findings)} self-approved PRs",
        ),
        (
            "[13/13]",
            "Known vulnerabilities (OSV.dev)",
            lambda: detect_known_vulnerabilities(vulns),
            lambda findings: f"Found {len(findings)} known vulnerabilities",
        ),
    ]

    all_findings: list[Finding] = []
    for step, description, detector, result_message in pass_specs:
        all_findings.extend(
            _run_detection_pass(step, description, detector, result_message),
        )

    return all_findings


def _print_risk_summary(all_findings: list[Finding]) -> None:
    """Print finding counts grouped by risk level."""
    print(f"\nTotal findings: {len(all_findings)}")

    by_risk: dict[str, int] = {}
    for finding in all_findings:
        by_risk.setdefault(finding.risk_level.value, 0)
        by_risk[finding.risk_level.value] += 1
    for risk, count in sorted(by_risk.items()):
        print(f"  {risk}: {count}")


def run_analysis(cache_dir: Path) -> list[Finding]:
    """Run all detection passes and return combined findings."""
    print("Loading cached data...")
    commits = get_all_cached_commits(cache_dir)
    prs = get_all_cached_prs(cache_dir)
    checks = get_all_cached_checks(cache_dir)
    deps = get_all_cached_deps(cache_dir)
    protection = get_all_cached_protection(cache_dir)
    pr_audits = get_all_cached_pr_audits(cache_dir)
    renovate_configs = get_all_cached_renovate(cache_dir)
    vulns = get_all_cached_vulns(cache_dir)

    _print_cache_stats(
        commits, prs, checks, deps, protection, pr_audits, renovate_configs, vulns,
    )

    all_findings = _run_detection_passes(
        commits, prs, checks, deps, protection, pr_audits, renovate_configs, vulns,
    )
    _print_risk_summary(all_findings)

    return all_findings


def _build_findings_summary(findings: list[dict], manifest: dict) -> dict:
    """Build a compact summary of findings for the agent to reason about."""
    by_category: dict[str, list[dict]] = {}
    for f in findings:
        by_category.setdefault(f["category"], []).append(f)

    by_repo: dict[str, dict[str, int]] = {}
    for f in findings:
        repo = f["repo"]
        risk = f["risk_level"]
        by_repo.setdefault(repo, Counter())
        by_repo[repo][risk] += 1

    category_breakdown = []
    for cat, cat_findings in sorted(by_category.items(), key=lambda x: -len(x[1])):
        risk_counts = Counter(f["risk_level"] for f in cat_findings)
        repos_affected = sorted({f["repo"] for f in cat_findings})
        category_breakdown.append(
            {
                "category": cat,
                "total": len(cat_findings),
                "risk_counts": dict(risk_counts),
                "repos_affected": repos_affected,
                "top_findings": [
                    {
                        "repo": f["repo"],
                        "risk_level": f["risk_level"],
                        "summary": f["summary"],
                    }
                    for f in sorted(
                        cat_findings,
                        key=lambda x: [
                            "critical",
                            "high",
                            "medium",
                            "low",
                            "info",
                        ].index(x.get("risk_level", "info")),
                    )[:5]
                ],
            },
        )

    repo_breakdown = []
    for repo in sorted(by_repo.keys()):
        counts = by_repo[repo]
        repo_breakdown.append(
            {
                "repo": repo,
                "total": sum(counts.values()),
                "critical": counts.get("critical", 0),
                "high": counts.get("high", 0),
                "medium": counts.get("medium", 0),
                "low": counts.get("low", 0),
            },
        )
    repo_breakdown.sort(
        key=lambda x: (x["critical"], x["high"], x["total"]), reverse=True,
    )

    return {
        "audit_window": f"{manifest['start_date']} to {manifest['end_date']}",
        "repos_audited": manifest.get("repos", []),
        "total_findings": len(findings),
        "risk_totals": dict(Counter(f["risk_level"] for f in findings)),
        "category_breakdown": category_breakdown,
        "repo_breakdown": repo_breakdown,
    }


def main() -> None:
    """Entry point for anomaly analysis."""
    parser = argparse.ArgumentParser(description="Supply chain anomaly analyzer")
    parser.add_argument(
        "--cache-dir", required=True, help="Cache directory from collect.py",
    )
    args = parser.parse_args()

    cache_path = Path(args.cache_dir)

    manifest_found = False
    if (cache_path / "manifest.json").exists():
        cache_dir = cache_path
        manifest_found = True
    else:
        for subdir in sorted(cache_path.iterdir()):
            if subdir.is_dir() and (subdir / "manifest.json").exists():
                cache_dir = subdir
                manifest_found = True
                break

    if not manifest_found:
        print("ERROR: No manifest.json found. Run collect.py first.", file=sys.stderr)
        sys.exit(1)

    manifest = read_manifest(cache_dir)
    print(
        f"Analyzing audit data for: {manifest['start_date']} to {manifest['end_date']}",
    )
    print(f"Repos: {', '.join(manifest.get('repos', []))}")

    findings = run_analysis(cache_dir)
    serialized = [f.to_dict() for f in findings]
    write_findings(cache_dir, serialized)

    # Write a compact summary for agent consumption
    summary = _build_findings_summary(serialized, manifest)
    summary_path = cache_dir / "findings_summary.json"
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    print(f"\nFindings written to: {cache_dir / 'findings.json'}")
    print(f"Summary written to: {summary_path}")


if __name__ == "__main__":
    main()
