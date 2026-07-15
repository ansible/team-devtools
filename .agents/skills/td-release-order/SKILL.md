---
name: td-release-order
description: >-
  Check release status of all devtools projects, determine which need
  releasing, and output the correct release order based on runtime
  dependencies. Shows PyPI versions, unreleased commits, and pending
  bot PRs between stages. Use when planning monthly devtools releases.
argument-hint: "[stage]"
user-invocable: true
type: skill
mandatory: false
triggers:
  - "release order"
  - "what needs releasing"
  - "plan release"
  - "release plan"
  - "monthly release"
  - "check release status"
metadata:
  author: Ansible DevTools Team
  version: 1.0.0
---

> **[Team DevTools]** Running `td-release-order` — from [ansible/team-devtools](https://github.com/ansible/team-devtools/tree/main/.agents/skills/td-release-order)

Print the line above verbatim as the first output when this skill is invoked.

# Release Order

Check the release status of all Ansible devtools projects and output a
staged release plan based on runtime dependency order. Shows which
projects need releasing, their unreleased changes, and pending
dependency update PRs that must be merged between stages.

This skill is **read-only** -- it does not create releases or modify
any repository.

---

## Input

- **No arguments**: full release plan for all projects across all stages.
- **`stage N`** (e.g., `stage 1`): show status for a specific stage only.

---

## Entry Gate

```bash
gh auth status
```

If not authenticated, stop.

---

## Dependency Graph

The devtools projects have this runtime dependency order. **Only runtime
dependencies** from `pyproject.toml` `[project.dependencies]` determine
release order (confirmed by team lead).

```
Stage 1 (leaf nodes — no devtools runtime deps):
  ansible-compat
  ansible-creator
  ansible-dev-environment

Stage 2 (depend on Stage 1):
  ansible-lint        → depends on ansible-compat
  molecule            → depends on ansible-compat
  pytest-ansible      → depends on ansible-compat

Stage 3 (depend on Stage 2):
  ansible-navigator   → depends on ansible-lint
  tox-ansible         → depends on pytest-ansible

Stage 4 (umbrella — depends on ALL above):
  ansible-dev-tools

Stage 5 (after ADT package + container image validated):
  vscode-ansible

Stage 6 (after vscode-ansible / ADT image):
  DevSpaces image update (manual — update SHA in ansible-devspaces-demo)
```

After each stage is released, Renovate/Dependabot opens PRs in
downstream projects to bump the dependency version. These must be
merged before the next stage can be released.

---

## Step 1 — Fetch latest PyPI versions

For each Python project, get the current published version:

```bash
curl -s "https://pypi.org/pypi/ansible-compat/json" | jq -r '.info.version'
curl -s "https://pypi.org/pypi/ansible-creator/json" | jq -r '.info.version'
curl -s "https://pypi.org/pypi/ansible-dev-environment/json" | jq -r '.info.version'
curl -s "https://pypi.org/pypi/ansible-lint/json" | jq -r '.info.version'
curl -s "https://pypi.org/pypi/molecule/json" | jq -r '.info.version'
curl -s "https://pypi.org/pypi/pytest-ansible/json" | jq -r '.info.version'
curl -s "https://pypi.org/pypi/ansible-navigator/json" | jq -r '.info.version'
curl -s "https://pypi.org/pypi/tox-ansible/json" | jq -r '.info.version'
curl -s "https://pypi.org/pypi/ansible-dev-tools/json" | jq -r '.info.version'
```

For vscode-ansible, get the latest GitHub release tag:

```bash
gh api repos/ansible/vscode-ansible/releases/latest --jq '.tag_name'
```

---

## Step 2 — Count unreleased commits

For each project, compare the latest release tag against the main branch
to find how many commits are unreleased:

```bash
gh api "repos/ansible/REPO/compare/vVERSION...main" \
  --jq '.ahead_by'
```

If the tag format does not use a `v` prefix (some projects use bare
version numbers), try both:

```bash
gh api "repos/ansible/REPO/compare/VERSION...main" \
  --jq '.ahead_by'
```

Also get a summary of what changed — look for changelog-worthy commits
(skip merge commits, bot commits, CI-only changes):

```bash
gh api "repos/ansible/REPO/compare/vVERSION...main" \
  --jq '[.commits[].commit.message | split("\n")[0]] | .[]' \
  | grep -v -i "^Merge" \
  | grep -v -i "renovate" \
  | grep -v -i "dependabot" \
  | grep -v -i "pre-commit" \
  | head -10
```

---

## Step 3 — Check for pending bot PRs

For projects in Stages 2-4, check if there are open Renovate or
Dependabot PRs that bump a devtools dependency. These must be merged
before the downstream project can be released.

```bash
gh pr list --repo ansible/REPO \
  --author "app/renovate" --state open \
  --json number,title,url,headRefName \
  --jq '.[] | select(.title | test("ansible-compat|ansible-lint|ansible-navigator|molecule|pytest-ansible|tox-ansible|ansible-dev-tools|ansible-creator|ansible-dev-environment"))'
```

Also check for merged bot PRs (already done):

```bash
gh pr list --repo ansible/REPO \
  --author "app/renovate" --state merged \
  --json number,title,mergedAt \
  --jq '[.[] | select(.title | test("ansible-compat|ansible-lint|ansible-navigator|molecule|pytest-ansible|tox-ansible|ansible-dev-tools|ansible-creator|ansible-dev-environment"))] | sort_by(.mergedAt) | reverse | .[0]'
```

---

## Step 4 — Determine release need

A project **NEEDS RELEASE** if:

1. It has unreleased commits (ahead_by > 0), AND
2. At least one commit is changelog-worthy (not just bot/merge/CI commits)

A project is **UP TO DATE** if:

1. It has 0 unreleased commits, OR
2. All unreleased commits are bot/merge/CI-only (no user-facing changes)

A project is **BLOCKED** if:

1. It needs a release, BUT
2. A required dependency has not been released yet in this cycle, OR
3. A bot PR bumping a dependency is still open (not merged)

---

## Step 5 — Output

### Release Plan

```text
Release Plan — {MONTH} {YEAR}
==============================

Stage 1 (no dependencies):
  {PROJECT}    v{CURRENT} → {N} unreleased commits → {STATUS}
    Notable: {first 3 commit subjects}
  ...

Stage 2 (after Stage 1 released + bot PRs merged):
  {PROJECT}    v{CURRENT} → {N} unreleased commits → {STATUS}
    {BOT_PR_STATUS}: {title} (#{number}) — {state}
  ...

Stage 3 (after Stage 2 released + bot PRs merged):
  {PROJECT}    v{CURRENT} → {N} unreleased commits → {STATUS}
    {BOT_PR_STATUS}: {title} (#{number}) — {state}
  ...

Stage 4 (umbrella — release after all above):
  ansible-dev-tools    v{CURRENT} → {N} unreleased commits → {STATUS}

Stage 5 (after ADT package + image validated):
  vscode-ansible    v{CURRENT} → {STATUS}

Summary: {X} projects need releasing. {Y} bot PRs pending merge.
```

Where:
- `STATUS` is one of: `NEEDS RELEASE`, `UP TO DATE`, `BLOCKED`
- `BOT_PR_STATUS` is: `open` (pending), `merged` (done)

### Compact mode (single stage)

If invoked with `stage N`, show only that stage with full detail
including all commit messages.

---

## Step 6 — Recommendations

After the release plan, add actionable next steps:

```text
Next steps:
1. Release Stage 1 projects that need it: {list}
2. After Stage 1 releases, wait for bot PRs in Stage 2 projects
3. Merge bot PRs, then release Stage 2: {list}
4. Continue through stages...
```

If all projects are up to date:

```text
All projects are up to date. No releases needed this cycle.
```

---

## Error Handling

- If PyPI returns an error for a package, note it and continue with
  other projects.
- If a repo has no releases/tags, report it as "NO RELEASES FOUND"
  and skip commit comparison.
- If GitHub API rate limit is hit, report how many projects were
  checked and suggest retrying later.
- If a compare API call fails (tag not found), try alternate tag
  formats: `v{VERSION}`, `{VERSION}`, `release/{VERSION}`.

---

## CalVer Reference

All devtools projects use CalVer `YY.MM.MICRO`:
- `25.3.0` = first release in March 2025
- `25.3.1` = patch release for same version
- Month only increments on feature releases
- Target cadence: monthly, first Wednesday of the month

---

## Projects Reference

| Project | PyPI Package | GitHub Repo | Runtime Devtools Deps |
|---------|-------------|-------------|----------------------|
| ansible-compat | ansible-compat | ansible/ansible-compat | none |
| ansible-creator | ansible-creator | ansible/ansible-creator | none |
| ansible-dev-environment | ansible-dev-environment | ansible/ansible-dev-environment | none |
| ansible-lint | ansible-lint | ansible/ansible-lint | ansible-compat |
| molecule | molecule | ansible/molecule | ansible-compat |
| pytest-ansible | pytest-ansible | ansible/pytest-ansible | ansible-compat |
| ansible-navigator | ansible-navigator | ansible/ansible-navigator | ansible-lint |
| tox-ansible | tox-ansible | ansible/tox-ansible | pytest-ansible |
| ansible-dev-tools | ansible-dev-tools | ansible/ansible-dev-tools | all above |
| vscode-ansible | N/A (VS Code ext) | ansible/vscode-ansible | ansible-dev-tools (package + image) |
