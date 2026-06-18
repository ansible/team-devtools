"""Data models for supply chain audit."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class RiskLevel(enum.Enum):
    """Risk classification for findings.

    Attributes:
        CRITICAL: Critical severity risk.
        HIGH: High severity risk.
        MEDIUM: Medium severity risk.
        LOW: Low severity risk.
        INFO: Informational finding only.

    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingCategory(enum.Enum):
    """Categories of supply chain anomalies.

    Attributes:
        UNSIGNED_COMMIT: Commit lacks cryptographic signature.
        GITHUB_WEB_SIGNED: Signed only via GitHub web UI.
        ORPHAN_COMMIT: Commit not linked to any PR.
        BYPASSED_CI: Merged without passing CI checks.
        POST_MERGE_PUSH: Push directly after merge.
        REPLICATED_MESSAGE: Duplicated commit message detected.
        SUSPICIOUS_DEP_TIMING: Dependency updated suspiciously fast.
        YANKED_VERSION: Depends on a yanked release.
        PROTECTION_CHANGED: Branch protection was modified.
        POST_APPROVAL_COMMIT: Commit added after approval.
        BOT_ONLY_APPROVAL: PR approved only by bots.
        COOLDOWN_VIOLATED: Merged before cooldown elapsed.
        KNOWN_VULNERABILITY: Known CVE in dependency.
        SELF_APPROVED: Author approved their own PR.

    """

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
    """GPG/SSH signature verification details.

    Attributes:
        verified: Whether signature is valid.
        reason: Verification status reason.
        signature: Raw signature string.
        signer_login: GitHub login of signer.
        signer_email: Email of the signer.

    """

    verified: bool
    reason: str
    signature: str | None = None
    signer_login: str | None = None
    signer_email: str | None = None


@dataclass
class Commit:
    """A git commit with verification and PR linkage metadata.

    Attributes:
        sha: Full commit SHA hash.
        repo: Repository name (org/repo).
        author_login: GitHub login of author.
        author_email: Email of the author.
        committer_login: GitHub login of committer.
        committer_email: Email of the committer.
        message: Commit message text.
        date: ISO 8601 commit timestamp.
        verification: Signature verification details.
        associated_prs: Linked pull request numbers.
        url: GitHub web URL for commit.

    """

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
        """Construct from GitHub API commit response.

        Args:
            data: Raw GitHub API JSON dict.
            repo: Repository name.

        Returns:
            Parsed commit.

        """
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
        """Serialize to dict for JSON storage.

        Returns:
            JSON-serializable dict.

        """
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
        """Deserialize from dict.

        Args:
            data: Previously serialized dict.

        Returns:
            Reconstructed commit.

        """
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
    """A pull request with merge and review metadata.

    Attributes:
        number: PR number in the repository.
        repo: Repository name (org/repo).
        title: Pull request title.
        state: Current state (open/closed).
        merged: Whether the PR was merged.
        merged_at: ISO 8601 merge timestamp.
        merge_commit_sha: SHA of merge commit.
        author_login: GitHub login of PR author.
        base_ref: Target branch name.
        head_ref: Source branch name.
        url: GitHub web URL for PR.

    """

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
        """Construct from GitHub API PR response.

        Args:
            data: Raw GitHub API JSON dict.
            repo: Repository name.

        Returns:
            Parsed pull request.

        """
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
        """Serialize to dict for JSON storage.

        Returns:
            JSON-serializable dict.

        """
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
        """Deserialize from dict.

        Args:
            data: Previously serialized dict.

        Returns:
            Reconstructed pull request.

        """
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
    """CI check suite status for a commit.

    Attributes:
        commit_sha: SHA of the checked commit.
        repo: Repository name (org/repo).
        status: Suite execution status.
        conclusion: Final suite conclusion.
        app_name: GitHub App that ran checks.
        url: GitHub API URL for suite.

    """

    commit_sha: str
    repo: str
    status: str
    conclusion: str | None
    app_name: str
    url: str = ""

    @classmethod
    def from_api(cls, data: dict[str, Any], repo: str, commit_sha: str) -> CheckSuite:
        """Construct from GitHub API check-suite response.

        Args:
            data: Raw GitHub API JSON dict.
            repo: Repository name.
            commit_sha: SHA of the commit this suite belongs to.

        Returns:
            Parsed check suite.

        """
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
        """Serialize to dict for JSON storage.

        Returns:
            JSON-serializable dict.

        """
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
        """Deserialize from dict.

        Args:
            data: Previously serialized dict.

        Returns:
            Reconstructed check suite.

        """
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
    """A dependency change detected in a commit or comparison.

    Attributes:
        repo: Repository name (org/repo).
        file_path: Path to dependency file.
        package_name: Name of the package.
        old_version: Previous version string.
        new_version: Updated version string.
        change_type: Kind of change (added/removed/updated).
        commit_sha: SHA introducing the change.
        commit_date: ISO 8601 commit timestamp.
        ecosystem: Package ecosystem (pypi/npm).
        is_direct: Whether a direct dependency.
        release_date: Package release date.
        days_since_release: Days since upstream release.
        yanked: Whether version was yanked.

    """

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
        """Serialize to dict for JSON storage.

        Returns:
            JSON-serializable dict.

        """
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
        """Deserialize from dict.

        Args:
            data: Previously serialized dict.

        Returns:
            Reconstructed dependency change.

        """
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
    """An anomaly detected during analysis.

    Attributes:
        category: Type of anomaly found.
        risk_level: Severity classification.
        repo: Repository name (org/repo).
        summary: One-line finding summary.
        details: Extended description of finding.
        commit_sha: Related commit SHA if any.
        pr_number: Related PR number if any.
        date: ISO 8601 timestamp of event.
        evidence: Supporting data dictionary.

    """

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
        """Serialize to dict for JSON storage.

        Returns:
            JSON-serializable dict.

        """
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
        """Deserialize from dict.

        Args:
            data: Previously serialized dict.

        Returns:
            Reconstructed finding.

        """
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
    """Metadata about a cached audit run.

    Attributes:
        start_date: Audit window start date.
        end_date: Audit window end date.
        repos: List of audited repo slugs.
        cache_key: Unique key for cached data.
        collected_at: ISO 8601 collection timestamp.
        gh_version: GitHub CLI version used.
        total_commits: Number of commits analyzed.
        total_prs: Number of PRs analyzed.
        total_findings: Number of findings produced.

    """

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
        """Serialize to dict for JSON storage.

        Returns:
            JSON-serializable dict.

        """
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
        """Deserialize from dict.

        Args:
            data: Previously serialized dict.

        Returns:
            Reconstructed audit manifest.

        """
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
