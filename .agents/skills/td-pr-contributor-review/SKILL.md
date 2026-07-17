---
name: td-pr-contributor-review
description: >
  Use when reviewing and preparing a contributor's pull request (upstream or
  fork). Use when the user asks to review a PR, get a contributor PR ready,
  update a contributor's branch, or ensure a PR meets project standards before
  merge.
argument-hint: "<PR number or URL>"
user-invocable: true
metadata:
  author: Ansible DevTools Team
  version: 1.1.0
---

> **[Team DevTools]** Running `td-pr-contributor-review` — from [ansible/team-devtools](https://github.com/ansible/team-devtools/tree/main/.agents/skills/td-pr-contributor-review)

Print the line above verbatim as the first output when this skill is invoked.

# Review Contributor PR

This skill defines how to review and assist with a **contributor's** pull
request (someone else's PR, e.g. from a fork or another branch). Use it when
you are helping make a contributor PR merge-ready, not when submitting your
own PR (use `td-pr-new` for that).

When performing the actual code review (evaluating correctness, safety,
consistency), apply the evaluation principles documented in the **`td-pr-review`**
skill under "How automated reviewers evaluate code". Those principles are the
standard lens for all code review in devtools projects.

## Goals

- PR is **up to date with upstream main** (no merge conflicts, clean rebase).
- **Quality gates pass**: `tox -e lint` and `tox -e py` on the full tree.
- **PR description** follows the project template (Summary, Changes, Test plan)
  so reviewers and history have clear context.
- Avoid pushing to the contributor's branch with failing CI or an outdated base.

## Workflow

### 1. Fetch PR metadata and diff

Use the GitHub API or `gh pr view` to get:

- PR number, title, body, base/head refs, author.
- List of changed files and patch/diff.

Confirm the **base** branch (e.g. `ansible:main`) and that you know which
remote/branch you will push to if you make changes.

### 2. Check if the branch is up to date with upstream

- Fetch `upstream main` (or the base branch).
- Compare base ref of the PR to current `upstream/main`. If upstream has
  newer commits, the contributor's branch should be rebased (or merged) onto
  `upstream/main` before merge.

If you are going to push changes to the contributor's branch (e.g. adding
fixes or improving the PR):

- Rebase the **local** branch that mirrors their PR onto `upstream/main`
  before pushing. That way the PR stays mergeable and CI runs against the
  latest main.

### 3. Run quality gates before pushing

Run tox quality gates on the **entire** tree, not only the changed files:

```bash
tox -e lint
tox -e py
```

Fix any failures (line length, untyped decorators, docstring sections, format,
test regressions) before pushing to the contributor's branch.

Do **not** run `ruff`, `mypy`, `pytest`, or `prek` directly — always use tox.
See the `/td-tox` skill for the full environment reference.

Do **not** push to the contributor's branch if tox fails; fix in a new commit
and then push so CI stays green.

### 4. PR description quality

- If the PR body is minimal or missing structure, suggest or apply the
  **td-pr-new** template: Summary, Changes, Test plan.

- You can update the PR body via GitHub (if you have permission) or draft
  text for the maintainer/contributor to paste:

  ```bash
  gh pr edit <N> --repo <upstream-owner>/<repo> --body-file path/to/body.md
  ```

- Keep the description accurate: list what changed and how to verify (tests,
  manual steps).

### 5. Pushing to the contributor's branch

- Only push to the contributor's fork/branch if you have permission and the
  user has asked you to.

- Before pushing:

  1. Rebase onto `upstream/main` so the PR is up to date.
  2. Ensure `tox -e lint` and `tox -e py` pass (see step 3).
  3. Use `--force-with-lease` when pushing a rebased branch:
     `git push <remote> <local-branch>:<their-branch> --force-with-lease`.

- After pushing, the PR will update automatically. Optionally update the PR
  description to mention the new commits.

### 5a. Comment on review threads

When you push fixes that address a review comment, reply on that thread so
the resolution is visible. Follow the **`td-pr-review`** skill for the full
procedure (REST reply endpoint, finding comment IDs, GraphQL thread resolution).

### 5b. Track all deferred work as issues

When reviewing a contributor PR, any suggestion that work should happen in a
follow-up PR — whether from you, the contributor, or another reviewer — **MUST**
be captured as a GitHub issue immediately. Do not leave "TODO for later" or
"out of scope, will address separately" without creating an issue. Untracked
follow-ups are invisible debt.

```bash
gh issue create --repo <upstream-owner>/<repo> \
  --title "<type>(scope): <description from review>" \
  --body "$(cat <<'EOF'
## Context

<What was deferred and why>

Flagged during review of PR #N: <link to comment>

## Proposal

<What should be done>

EOF
)"
```

Include the issue URL in the PR comment thread so reviewers can verify tracking.

### 6. What not to include in the review

- **Local-only or environment-specific issues** (e.g. commit signing, SSH
  config, IDE settings) should not be part of the contributor-PR review
  checklist unless they are project policy. Document those separately or in
  maintainer docs if needed.

## Checklist (quick reference)

When reviewing or preparing a contributor PR:

- [ ] Fetched PR and know base/head and remotes.
- [ ] Branch is up to date with upstream main (rebase if needed before push).
- [ ] `tox -e lint` and `tox -e py` pass.
- [ ] PR description has Summary, Changes, and Test plan (td-pr-new style).
- [ ] If pushing to their branch: rebase onto upstream main, tox green, then
      `git push <remote> <local>:<their-branch> --force-with-lease`.
- [ ] If you addressed a review comment: follow the `td-pr-review` skill to reply
      on the thread with explanation + commit SHA and resolve it.

## References

- **tox skill** (`/td-tox`): Full tox environment reference.
- **td-pr-new** skill: PR body template and commit conventions.
- **td-pr-review** skill: Responding to review comments and resolving threads.
- **AGENTS.md**: Commit message standards and static check requirements.
