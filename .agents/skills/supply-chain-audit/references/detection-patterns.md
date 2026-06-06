# Detection Patterns Reference

Detailed documentation of each anomaly category detected by the supply chain
audit analysis engine.

## 1. Unsigned Commits

**Category:** `unsigned_commit`
**Default Risk:** Medium

### What it detects

Commits that lack a cryptographic signature (GPG or SSH). In a well-configured
repository with branch protection rules requiring signed commits, unsigned
commits should not exist on protected branches.

### Why it matters

An unsigned commit cannot be cryptographically attributed to a specific
developer. An attacker who gains push access (e.g., via a stolen token) can
create commits impersonating any author without needing their signing key.

### False positive scenarios

- Repositories that don't enforce commit signing (common in open-source)
- Bot accounts that legitimately don't sign (e.g., dependabot, renovate)
- Historical commits before signing was enforced

### Investigation steps

1. Check if the repo has branch protection requiring signatures
2. Verify the commit author is a known contributor
3. Check if the commit was part of a properly-reviewed PR
4. Inspect the commit content for suspicious changes

---

## 2. GitHub-Web-Signed Commits

**Category:** `github_web_signed`
**Default Risk:** Low

### What it detects

Commits that are signed by GitHub's web-flow key rather than the author's
personal GPG/SSH key. This happens when:

- Files are edited via the GitHub web UI
- PRs are merged via the merge button (merge commits)
- GitHub Actions create commits

### Why it matters

A compromised GitHub account can create web-signed commits that appear
legitimate because GitHub signs them. The signature proves the commit went
through GitHub, but NOT that the account owner authorized it. This was
observed in real supply chain attacks where attackers:

- Gained access to a maintainer's GitHub session
- Made edits via the web UI
- The commits appeared "verified" because GitHub signed them

### Distinguishing legitimate from suspicious

**Likely legitimate:**
- Merge commits from the merge button
- Bot accounts (dependabot, github-actions)
- Typo fixes in documentation

**Suspicious indicators:**
- Code changes (not just docs/config)
- Changes to dependency files
- Author account with unusual activity patterns
- Commits outside the author's normal working hours

### Investigation steps

1. Check the commit content — is it a merge commit or actual code?
2. Verify the author's account history and activity patterns
3. Check if the commit modifies security-sensitive files
4. Look for corresponding PR with proper review

---

## 3. Orphan Commits (No Associated PR)

**Category:** `orphan_commit`
**Default Risk:** High

### What it detects

Commits on the default branch that have no associated pull request. This
indicates a direct push bypassing code review.

### Why it matters

Pull requests provide:
- Code review by peers
- Automated CI checks
- An audit trail of who approved the change
- Discussion context

Direct pushes bypass all of these controls. In a supply chain attack,
an attacker with write access would prefer direct pushes to avoid review.

### False positive scenarios

- Initial repository setup commits
- Emergency hotfixes by admins (should still be rare)
- Repos without branch protection (open-source, early-stage)
- Force-push rewrites that break PR linkage

### Investigation steps

1. Check if the committer has admin/maintain access to the repo
2. Inspect the commit content for suspicious changes
3. Check if branch protection was temporarily disabled
4. Look for any communication (Slack, etc.) explaining the direct push
5. Verify the commit wasn't created by rebasing an existing PR

---

## 4. Bypassed CI

**Category:** `bypassed_ci`
**Default Risk:** High

### What it detects

Pull requests that were merged despite having one or more check suites in
a failing, skipped, or timed-out state.

### Why it matters

CI checks serve as automated security gates:
- Linting catches suspicious patterns
- Tests verify code behavior hasn't changed unexpectedly
- Security scanners detect vulnerabilities and secrets
- Build verification ensures reproducibility

Merging with failed CI means these gates were intentionally bypassed,
which could indicate:
- Urgency overriding process (risky but not malicious)
- An attacker with merge access forcing malicious code through
- Check suites that were manipulated or race-conditioned

### What constitutes "bypassed"

| Check conclusion | Flagged? | Rationale |
|-----------------|----------|-----------|
| `failure` | Yes | Explicit failure |
| `timed_out` | Yes | May indicate manipulated checks |
| `action_required` | Yes | Unresolved required action |
| `skipped` | Yes | Deliberately skipped |
| `cancelled` | No | Usually user-initiated re-run |
| `success` | No | Normal |
| `neutral` | No | Informational checks |

### Investigation steps

1. Identify which checks failed and why
2. Determine who merged the PR and their role
3. Check if the failures were related to the PR's changes
4. Look for admin override patterns
5. Verify the merge wasn't forced via API

---

## 5. Post-Merge Pushes

**Category:** `post_merge_push`
**Default Risk:** Critical

### What it detects

Commits that appear on a branch AFTER its associated pull request has already
been merged or closed. This is the most suspicious pattern because:

- Normal workflow: branch → PR → review → merge → branch deleted
- Attack pattern: branch → PR → merge → additional commits pushed

### Why it matters

This is a known supply chain attack vector. The attack flow:

1. Attacker creates a legitimate-looking PR
2. PR passes review and is merged
3. After merge, attacker pushes additional commits to the same branch
4. If any downstream CI/CD pulls from the branch (not the merge commit),
   it picks up the post-merge malicious code

This was observed in real-world attacks where the merge commit is clean
but the branch contains additional malicious content.

### How it works technically

- GitHub doesn't delete branches immediately after merge by default
- Branch protection only applies to the default branch
- Feature branches can receive pushes even after their PR is merged
- Some CI systems reference branches, not specific SHAs

### Investigation steps

1. **Immediately** check what was pushed after the merge
2. Verify no CI/CD system references this branch by name
3. Check if any deployment pulled from this branch after the merge date
4. Inspect the post-merge commits for malicious content
5. Check if the branch was eventually deleted and when
6. Determine if the pusher is the same person who authored the PR

---

## 6. Replicated Commit Messages

**Category:** `replicated_message`
**Default Risk:** High (different author) / Low (same author)

### What it detects

Commit messages that are near-duplicates (Jaccard similarity > 0.95) of
earlier commits in the same repository, particularly when from different
authors.

### Why it matters

Supply chain attackers often copy legitimate commit messages to make their
malicious commits blend in. The pattern:

1. Observe the style and content of legitimate commits
2. Create a malicious commit with a message copied from an earlier commit
3. The commit appears routine at first glance

A commit by "Author B" with the same message as an earlier commit by
"Author A" warrants investigation.

### Jaccard similarity

We use Jaccard similarity on word tokens:

```
similarity = |words_A ∩ words_B| / |words_A ∪ words_B|
```

Threshold: 0.95 (nearly identical messages)

### False positive scenarios

- Release commits that follow a template (e.g., "Release v1.2.3")
- Automated commits (dependabot updates with similar messages)
- Revert commits that quote the original message
- Cherry-picks that preserve the original message

### Investigation steps

1. Compare the two commits — are they from the same author?
2. If different authors, check if the second commit is legitimate
3. Inspect the commit content (not just the message)
4. Check if this follows an automated pattern (bots, releases)

---

## 7. Suspicious Dependency Timing

**Category:** `suspicious_dep_timing`
**Default Risk:** High

### What it detects

Dependencies whose version was released on a package registry (PyPI/npm)
fewer than 7 days before being adopted in one of the target repositories.

### Why it matters

Supply chain attacks via package registries follow a time pattern:

1. Attacker compromises a package or publishes a malicious version
2. The malicious version is pulled in by downstream projects
3. The malicious version is detected and removed

The window between (1) and (3) is typically short. A dependency adopted
within days of its release is more likely to have pulled in a compromised
version before it was flagged.

### Threshold rationale

- **< 7 days**: High risk — very rapid adoption of a new release
- **7-30 days**: Moderate — worth noting but less suspicious
- **> 30 days**: Normal adoption cadence

### Context that reduces risk

- The package is owned by the same organization (internal dep)
- The update was explicitly planned (linked to a tracking issue)
- The package is well-known and the release was announced
- Automated tools (dependabot/renovate) performed the update

### Investigation steps

1. Check who released the package version
2. Verify the package maintainer hasn't been compromised
3. Look for advisories or retractions for that version
4. Check if the version was later yanked
5. Compare the release contents with the previous version

---

## 8. Yanked/Deleted Package Versions

**Category:** `yanked_version`
**Default Risk:** Critical

### What it detects

Dependencies that reference a version which has been yanked (PyPI) or
deprecated (npm) on the package registry.

### Why it matters

Packages are yanked for serious reasons:
- Security vulnerability discovered
- Accidental publication of malicious code
- Compromised maintainer account
- Supply chain attack detected and mitigated

If a repo pulled in a version that was later yanked, it may have been
exposed to whatever caused the yank.

### PyPI yanking

PyPI allows maintainers to "yank" a release, which:
- Removes it from the simple index (new installs won't get it)
- Keeps it available for existing pins (reproducibility)
- Marks it with a `yanked` flag in the JSON API

### npm deprecation

npm uses `deprecated` field rather than yanking:
- The package remains installable
- A warning is shown during install
- Indicates the version should not be used

### Investigation steps

1. Determine WHY the version was yanked (advisory, CVE, compromise?)
2. Check if the project ever installed/deployed with this version
3. Review what the yanked version contained vs. the previous version
4. Assess whether any builds were produced during the exposure window
5. Check for downstream artifacts that may have bundled the yanked version

---

## 10. Post-Approval Commits in PRs

### What it detects

Commits pushed to a PR branch **after** the last review approval and before
merge. This inspects individual commits within each PR, not just the
final squash/merge commit on `main`.

### Why it matters

This is the "sneak code in mid-PR" attack vector:
1. Attacker opens a PR with benign code
2. Reviewer approves it
3. Attacker pushes a malicious commit after approval
4. If the repo does NOT require "dismiss approvals on new push" or
   "require approval of the most recent push," the PR can be merged
   with unapproved code

### Risk levels

| Scenario | Risk |
|----------|------|
| Commits from unknown third party (neither PR author nor approver) | CRITICAL |
| Commits from PR author pushed after someone else approved | HIGH |
| Commits from the approver themselves (self-authored fixup) | MEDIUM |

### False positives

- **Reviewer pushes a suggestion commit**: GitHub's "commit suggestion"
  feature creates a commit authored by the reviewer. This is flagged as
  MEDIUM since the approver is accountable.
- **Rebases after approval**: If a maintainer rebases the branch to resolve
  conflicts, all commit timestamps reset. This can appear as post-approval
  activity.
- **Bot auto-updates (renovate, dependabot)**: Bots may push updates after
  approval if auto-merge is enabled with an approval policy.
- **PR author adds a small fixup**: The author might add a typo fix or
  linting correction after approval — technically unapproved but low risk.

### Investigation steps

1. Check `git log --oneline` for the PR branch — what was the actual content
   of the post-approval commit(s)?
2. Look at the PR timeline on GitHub — was there a re-review or did the
   merge happen without anyone seeing the new commit?
3. Verify whether the repo has "dismiss stale reviews" or "require approval
   of most recent push" enabled (branch protection / rulesets)
4. If a third party pushed code, verify their identity and authorization
5. Compare the diff of the post-approval commit against the final merged state

---

## 11. Bot-Only Approval (No Human Review)

### What it detects

Pull requests that were merged where **all** review approvals came from bot
accounts (e.g. `ansibuddy`, `dependabot[bot]`), meaning no human ever
reviewed the code diff before it landed on `main`.

### Why it matters

Bot approvals are automated and typically only check metadata (CI passed,
labels present, etc.) — they do NOT review code for:
- Malicious payloads hidden in dependency updates
- Backdoors introduced by compromised upstream packages
- Logic bombs in seemingly routine changes
- Credential exfiltration in build scripts

If an attacker compromises an upstream package, the bot will happily approve
and merge the poisoned update with zero human oversight.

### Known bot accounts (configurable)

The following are treated as bot accounts:
- `ansibuddy`
- `dependabot[bot]`
- `renovate[bot]`
- `github-actions[bot]`
- `pre-commit-ci[bot]`
- `codecov[bot]`
- `mergify[bot]`
- Any account ending in `[bot]`

### Risk levels

| Scenario | Risk |
|----------|------|
| Bot PR (renovate/dependabot) + bot approval + dep-only title | LOW |
| Bot PR + bot approval + non-dep title | MEDIUM |
| Human-authored PR + bot-only approval | HIGH |

### False positives

- **Intentional auto-merge for trivial updates**: Teams may configure
  `ansibuddy` to auto-approve lockfile-only renovate PRs by design.
  These are LOW risk but still flagged for visibility.
- **Bot approves but human reviewed informally**: A human may have reviewed
  the diff without formally submitting a GitHub review (e.g., looked at
  the PR but only commented, didn't click "Approve").

### Investigation steps

1. Check the PR timeline — did any human interact (comment, react, etc.)?
2. Review the actual diff: was it truly a trivial update or did it contain
   code changes?
3. Verify the team's intended automation policy for this type of PR
4. For dependency updates: cross-reference with the package's release history
   and changelog
5. Consider whether "require human approval" should be enforced via branch
   protection rulesets

---

## 12. Renovate Cooldown Violated

### What it detects

Dependencies adopted **before** the repo's configured `minimumReleaseAge`
cooldown period has elapsed. This is a policy violation — the team's own
security contract was broken.

### Why it matters

Renovate's `minimumReleaseAge` exists specifically to provide a buffer
window where:
- Compromised packages can be detected and yanked by maintainers
- Community reports of malicious code can surface
- Security scanners can flag the release

If a package bypasses this cooldown, it means one of:
1. Someone manually overrode renovate and merged the update early
2. The renovate config was temporarily modified
3. A dependency was added outside the renovate workflow entirely
4. A vulnerability fix was fast-tracked (legitimate but should be documented)

### How it works

1. During collection, the tool reads each repo's `renovate.json` (or shared
   preset via `extends`) to determine the configured `minimumReleaseAge`
2. Package rules are resolved (e.g., major updates may have a longer cooldown)
3. For each dependency change, the actual `days_since_release` is compared
   against the effective cooldown
4. If `days_since_release < configured_cooldown` → CRITICAL finding

### Configured policies (ansible devtools)

| Repos | Default Cooldown | Major Update Cooldown | Source |
|-------|------------------|-----------------------|--------|
| Most repos | 2 days | 7 days | `github>ansible/actions//config/renovate.json` |
| vscode-ansible | 1 day | (inherits default) | Local `renovate.json` |

### False positives

- **Security hotfixes**: A critical CVE fix may be intentionally fast-tracked
  past the cooldown. This is legitimate but should be documented in the PR.
- **Renovate schedule vs. merge timing**: Renovate may open the PR respecting
  the cooldown, but the merge happens to coincide with a very recent release
  due to batching.

### Investigation steps

1. Check the PR that introduced the dependency — was it via renovate or manual?
2. If manual, who overrode the policy and why?
3. Check if the renovate config was modified around the same time
4. Verify whether the package in question had a security advisory justifying
   early adoption
5. Check the package's release history for signs of compromise

---

## 13. Known Vulnerabilities (OSV.dev)

### What it detects

Packages currently installed in any repo that have **disclosed security
vulnerabilities** according to the OSV.dev database. This checks ALL
packages from lock files, not just those that changed during the audit window.

### Why it matters

A known vulnerability in a dependency is an active risk, regardless of when
it was introduced. This pass answers: "Right now, today, are we running code
with known security issues?"

Common scenarios:
- A CVE was disclosed for a package version the repo has pinned
- A vulnerability exists in a transitive dependency buried in the lock file
- The repo hasn't updated its dependencies recently enough to pick up fixes
- A package was deprecated due to security concerns

### Data source

- **OSV.dev** (Google): Free, no authentication required
- Batch endpoint: `POST https://api.osv.dev/v1/querybatch` (100 packages/request)
- Covers: PyPI, npm, Go, Rust, and most major ecosystems
- Includes: GitHub Security Advisories (GHSA), PYSEC, CVEs, and more

### Risk levels

| OSV Severity | Audit Risk Level |
|--------------|------------------|
| Critical / High | CRITICAL |
| Medium | HIGH |
| Low / Unknown | MEDIUM |

### What gets scanned

The tool reads lock files from the default branch to build a complete
package inventory:
- **Python**: `uv.lock`, `poetry.lock`, `pdm.lock` (all `[[package]]` entries)
- **npm**: `package.json` (direct `dependencies` and `devDependencies`)

### False positives

- **Disputed advisories**: Some GHSA/CVE entries are disputed or only
  exploitable under very specific conditions
- **Dev-only dependencies**: A vulnerability in a devDependency (e.g., a
  test framework) may not affect production deployments
- **Already mitigated**: The vulnerable code path may not be reachable in
  the repo's specific usage pattern
- **Pending fix**: The latest available version may not yet have a patch

### Investigation steps

1. Look up the vulnerability ID (GHSA/PYSEC/CVE) for full details and
   affected version ranges
2. Determine if a fixed version is available
3. Check if the dependency is direct or transitive — can it be updated
   independently?
4. Assess whether the vulnerable code path is actually exercised
5. For critical/high: open an issue or PR to update immediately
6. For medium/low: schedule update via normal renovate cycle
