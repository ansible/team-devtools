"""Data models for supply chain audit."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class RiskLevel(enum.Enum):
    """Risk classification for findings."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingCategory(enum.Enum):
    """Categories of supply chain anomalies."""

    UNSIGNED_COMMIT = "unsigned_commit"
    GITHUB_WEB_SIGNED = "github_web_signed"
    ORPHAN_COMMIT = "orphan_commit"
    BYPASSED_CI = "bypassed_ci"
    POST_MERGE_PUSH = "post_merge_push"
    REPLICATED_MESSAGE = "replicated_message"
    SUSPICIOUS_DEP_TIMING = "suspicious_dep_timing"
    YANKED_VERSION = "yanked_version"
    PROTECTION_CHANGED = "protection_changed"
    POST_APPROVAL_COMMIT = "post_approval_commit"
    BOT_ONLY_APPROVAL = "bot_only_approval"
    COOLDOWN_VIOLATED = "cooldown_violated"
    KNOWN_VULNERABILITY = "known_vulnerability"
    SELF_APPROVED = "self_approved"


@dataclass
class CommitVerification:
    """GPG/SSH signature verification details."""

    verified: bool
    reason: str
    signature: str | None = None
    signer_login: str | None = None
    signer_email: str | None = None


@dataclass
class Commit:
    """A git commit with verification and PR linkage metadata."""

    sha: str
    repo: str
    author_login: str
    author_email: str
    committer_login: str
    committer_email: str
    message: str
    date: str
    verification: CommitVerification
    associated_prs: list[int] = field(default_factory=list)
    url: str = ""

    @classmethod
    def from_api(cls, data: dict[str, Any], repo: str) -> Commit:
        """Construct from GitHub API commit response."""
        commit_data = data.get("commit", {})
        author = data.get("author") or {}
        committer = data.get("committer") or {}
        verification = commit_data.get("verification", {})

        return cls(
            sha=data.get("sha", ""),
            repo=repo,
            author_login=author.get("login", "unknown"),
            author_email=commit_data.get("author", {}).get("email", ""),
            committer_login=committer.get("login", "unknown"),
            committer_email=commit_data.get("committer", {}).get("email", ""),
            message=commit_data.get("message", ""),
            date=commit_data.get("author", {}).get("date", ""),
            verification=CommitVerification(
                verified=verification.get("verified", False),
                reason=verification.get("reason", "unsigned"),
                signature=verification.get("signature"),
                signer_login=committer.get("login"),
                signer_email=commit_data.get("committer", {}).get("email", ""),
            ),
            url=data.get("html_url", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return {
            "sha": self.sha,
            "repo": self.repo,
            "author_login": self.author_login,
            "author_email": self.author_email,
            "committer_login": self.committer_login,
            "committer_email": self.committer_email,
            "message": self.message,
            "date": self.date,
            "verification": {
                "verified": self.verification.verified,
                "reason": self.verification.reason,
                "signature": self.verification.signature,
                "signer_login": self.verification.signer_login,
                "signer_email": self.verification.signer_email,
            },
            "associated_prs": self.associated_prs,
            "url": self.url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Commit:
        """Deserialize from dict."""
        v = data.get("verification", {})
        return cls(
            sha=data["sha"],
            repo=data["repo"],
            author_login=data.get("author_login", ""),
            author_email=data.get("author_email", ""),
            committer_login=data.get("committer_login", ""),
            committer_email=data.get("committer_email", ""),
            message=data.get("message", ""),
            date=data.get("date", ""),
            verification=CommitVerification(
                verified=v.get("verified", False),
                reason=v.get("reason", ""),
                signature=v.get("signature"),
                signer_login=v.get("signer_login"),
                signer_email=v.get("signer_email"),
            ),
            associated_prs=data.get("associated_prs", []),
            url=data.get("url", ""),
        )


@dataclass
class PullRequest:
    """A pull request with merge and review metadata."""

    number: int
    repo: str
    title: str
    state: str
    merged: bool
    merged_at: str | None
    merge_commit_sha: str | None
    author_login: str
    base_ref: str
    head_ref: str
    url: str = ""

    @classmethod
    def from_api(cls, data: dict[str, Any], repo: str) -> PullRequest:
        """Construct from GitHub API PR response."""
        user = data.get("user") or {}
        base = data.get("base") or {}
        head = data.get("head") or {}
        return cls(
            number=data.get("number", 0),
            repo=repo,
            title=data.get("title", ""),
            state=data.get("state", ""),
            merged=data.get("merged", False),
            merged_at=data.get("merged_at"),
            merge_commit_sha=data.get("merge_commit_sha"),
            author_login=user.get("login", "unknown"),
            base_ref=base.get("ref", ""),
            head_ref=head.get("ref", ""),
            url=data.get("html_url", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return {
            "number": self.number,
            "repo": self.repo,
            "title": self.title,
            "state": self.state,
            "merged": self.merged,
            "merged_at": self.merged_at,
            "merge_commit_sha": self.merge_commit_sha,
            "author_login": self.author_login,
            "base_ref": self.base_ref,
            "head_ref": self.head_ref,
            "url": self.url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PullRequest:
        """Deserialize from dict."""
        return cls(
            number=data["number"],
            repo=data["repo"],
            title=data.get("title", ""),
            state=data.get("state", ""),
            merged=data.get("merged", False),
            merged_at=data.get("merged_at"),
            merge_commit_sha=data.get("merge_commit_sha"),
            author_login=data.get("author_login", ""),
            base_ref=data.get("base_ref", ""),
            head_ref=data.get("head_ref", ""),
            url=data.get("url", ""),
        )


@dataclass
class CheckSuite:
    """CI check suite status for a commit."""

    commit_sha: str
    repo: str
    status: str
    conclusion: str | None
    app_name: str
    url: str = ""

    @classmethod
    def from_api(cls, data: dict[str, Any], repo: str, commit_sha: str) -> CheckSuite:
        """Construct from GitHub API check-suite response."""
        app = data.get("app") or {}
        return cls(
            commit_sha=commit_sha,
            repo=repo,
            status=data.get("status", ""),
            conclusion=data.get("conclusion"),
            app_name=app.get("name", "unknown"),
            url=data.get("url", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return {
            "commit_sha": self.commit_sha,
            "repo": self.repo,
            "status": self.status,
            "conclusion": self.conclusion,
            "app_name": self.app_name,
            "url": self.url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CheckSuite:
        """Deserialize from dict."""
        return cls(
            commit_sha=data["commit_sha"],
            repo=data["repo"],
            status=data.get("status", ""),
            conclusion=data.get("conclusion"),
            app_name=data.get("app_name", ""),
            url=data.get("url", ""),
        )


@dataclass
class DepChange:
    """A dependency change detected in a commit or comparison."""

    repo: str
    file_path: str
    package_name: str
    old_version: str | None
    new_version: str | None
    change_type: str  # "added", "removed", "updated"
    commit_sha: str
    commit_date: str
    ecosystem: str  # "pypi", "npm"
    is_direct: bool
    release_date: str | None = None
    days_since_release: int | None = None
    yanked: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return {
            "repo": self.repo,
            "file_path": self.file_path,
            "package_name": self.package_name,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "change_type": self.change_type,
            "commit_sha": self.commit_sha,
            "commit_date": self.commit_date,
            "ecosystem": self.ecosystem,
            "is_direct": self.is_direct,
            "release_date": self.release_date,
            "days_since_release": self.days_since_release,
            "yanked": self.yanked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DepChange:
        """Deserialize from dict."""
        return cls(
            repo=data["repo"],
            file_path=data.get("file_path", ""),
            package_name=data["package_name"],
            old_version=data.get("old_version"),
            new_version=data.get("new_version"),
            change_type=data.get("change_type", "updated"),
            commit_sha=data.get("commit_sha", ""),
            commit_date=data.get("commit_date", ""),
            ecosystem=data.get("ecosystem", "pypi"),
            is_direct=data.get("is_direct", True),
            release_date=data.get("release_date"),
            days_since_release=data.get("days_since_release"),
            yanked=data.get("yanked", False),
        )


@dataclass
class Finding:
    """An anomaly detected during analysis."""

    category: FindingCategory
    risk_level: RiskLevel
    repo: str
    summary: str
    details: str
    commit_sha: str | None = None
    pr_number: int | None = None
    date: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return {
            "category": self.category.value,
            "risk_level": self.risk_level.value,
            "repo": self.repo,
            "summary": self.summary,
            "details": self.details,
            "commit_sha": self.commit_sha,
            "pr_number": self.pr_number,
            "date": self.date,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        """Deserialize from dict."""
        return cls(
            category=FindingCategory(data["category"]),
            risk_level=RiskLevel(data["risk_level"]),
            repo=data["repo"],
            summary=data["summary"],
            details=data.get("details", ""),
            commit_sha=data.get("commit_sha"),
            pr_number=data.get("pr_number"),
            date=data.get("date"),
            evidence=data.get("evidence", {}),
        )


@dataclass
class AuditManifest:
    """Metadata about a cached audit run."""

    start_date: str
    end_date: str
    repos: list[str]
    cache_key: str
    collected_at: str
    gh_version: str
    total_commits: int = 0
    total_prs: int = 0
    total_findings: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "repos": self.repos,
            "cache_key": self.cache_key,
            "collected_at": self.collected_at,
            "gh_version": self.gh_version,
            "total_commits": self.total_commits,
            "total_prs": self.total_prs,
            "total_findings": self.total_findings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditManifest:
        """Deserialize from dict."""
        return cls(
            start_date=data["start_date"],
            end_date=data["end_date"],
            repos=data["repos"],
            cache_key=data["cache_key"],
            collected_at=data["collected_at"],
            gh_version=data.get("gh_version", ""),
            total_commits=data.get("total_commits", 0),
            total_prs=data.get("total_prs", 0),
            total_findings=data.get("total_findings", 0),
        )
