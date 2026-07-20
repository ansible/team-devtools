---
name: td-pr-contributor-review
description: >
  Use when reviewing and preparing a contributor's pull request (upstream or
  fork). Use when the user asks to review a PR, get a contributor PR ready,
  update a contributor's branch, ensure a PR meets project standards before
  merge, or leave an agent-executable follow-up comment for another session.
argument-hint: "<PR number or URL>"
user-invocable: true
metadata:
  author: Ansible DevTools Team
  version: 1.2.0
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

### 5c. Agent-executable follow-up comments

When the review outcome is **needs work** and a human or another agent will
land the fixes (not this session), post a single PR comment that a follow-up
agent can execute without re-deriving intent from chat history.

Use this when the user asks to “comment for follow-up”, “leave instructions
for another agent”, or when you deliberately stop after review without
pushing fixes. Prefer fixing in-session when the user asked you to land the
changes; do not dump work into a comment as a substitute for doing the work
you were asked to do.

#### When to post

| Situation | Action |
| --- | --- |
| You will push fixes now | Fix, reply on threads, resolve (see `td-pr-review`). No agent-executable dump needed. |
| Contributor / another agent will fix | Post one agent-executable comment (this section). |
| Work is deferred out of this PR | File a GitHub issue (section 5b) **and** link it from the comment. |

#### Required structure

Post via `gh pr comment <N> --repo <owner>/<repo> --body-file …` (or equivalent).
The body **must** include all of the following sections, in order:

1. **Title / role** — e.g. `## Maintainer assist — agent-executable follow-up`
2. **Context** — one short paragraph: what the PR is for (finding ID, Jira,
   user-visible bug), current CI/merge state, and that this comment is the
   execution brief.
3. **How to use** — instruct the executing agent to: work items in order;
   treat **P0** as merge-blocking; not invent extra scope; reply on the same
   thread with commit SHAs when done; respect any “do not file issues” /
   “do not push” constraints from the human.
4. **P0 items (merge-blocking)** — one subsection per item (`### P0-1 — …`).
5. **P1 / optional items** — clearly marked non-blocking; “do only if cheap
   while touching related code” unless the human said otherwise.
6. **Out of scope / non-goals** — explicit list so the agent does not expand.
7. **Verification** — exact commands for this repo (e.g. `tox -e lint`,
   `tox -e py`, or the project’s npm/vitest equivalents). Include rebase
   onto `upstream/main` when DR numbers or base drift are involved.
8. **Done definition** — checklist the executing agent must satisfy before
   stopping (pushed commits, CI green, PR body updated, reply on thread).

#### Per-item template (every P0/P1)

Each actionable item **must** spell out all four parts. Vague “please fix X”
is not enough.

```markdown
### P0-N — <short title>

**Problem:** What is wrong today (quote code, cite files/lines, name colliding
PRs or DR IDs). Include a minimal snippet when the failing assertion or stub
is the point.

**Why it matters:** Security, correctness, merge conflict, project policy, or
reviewer/DoD impact. Tie to Jira/finding/DR when relevant.

**What to do:** Numbered steps with concrete paths and symbols
(`packages/…/file.ts`, `docs/decisions.md`, `gh pr edit …`). When there is a
tradeoff, name **Option A (preferred)** vs **Option B** and justify the
preference so the agent does not flip a coin.

**Acceptance:**
- [ ] Observable outcome 1
- [ ] Observable outcome 2
- [ ] Tests / docs / CI expectation
```

#### Writing rules

- **Prioritize.** Merge-blocking first (`P0`). Nice-to-haves are `P1` or
  “optional”. Never mix blocking and optional in one undifferentiated list.
- **Be executable.** Name files, functions, DR numbers, colliding PR numbers,
  and commands. Prefer paste-ready PR body markdown when description format
  is the ask.
- **Justify tradeoffs.** If two fixes are valid, state which to prefer and why
  (e.g. fail-closed vs register-port-earlier for a security guard).
- **Constrain scope.** Explicit non-goals prevent drive-by refactors.
- **Respect issue policy.** Agent-executable comments do **not** replace
  section 5b. If an item is “later PR”, file the issue and link it, unless the
  human explicitly said not to file issues — then say so in **How to use** and
  **Out of scope**.
- **Do not resolve others’ threads** for work that is still open. The
  executing agent should only resolve threads they actually fixed.
- **One comment, not many.** Prefer a single consolidated brief over
  fragmented nits the next agent must assemble.

#### Skeleton (copy and fill)

```markdown
## Maintainer assist — agent-executable follow-up

**Context:** <PR purpose + finding/Jira + CI/merge state>.

**How to use this comment:** Execute items in order. **P0** is merge-blocking.
Do not invent extra scope. <any human constraints>. When done, reply on this
thread with commit SHAs and which options you chose.

---

### P0-1 — <title>

**Problem:** …
**Why it matters:** …
**What to do:** …
**Acceptance:**
- [ ] …

### P0-2 — <title>
…

### P1 — <optional title> (non-blocking)
…

---

### Out of scope

- …

### Verification

Run the repo’s quality gates (examples): `tox -e lint`, `tox -e py`,
plus any package-specific tests named in the P0 items. Rebase onto
`upstream/main` first when base drift or DR collisions apply.

### Done definition for the executing agent

1. All P0 items landed and pushed.
2. CI green.
3. Reply on this thread: SHAs, DR numbers chosen, P1 items included or skipped.
```

#### Anti-patterns

- Prose-only review with no files, acceptance checks, or ordering.
- “Please address the other reviewer’s comments” without restating them as
  executable items.
- Mixing “must fix before merge” with “nice follow-up” without labels.
- Asking the agent to open issues when the human said not to (or the reverse:
  leaving deferred work with no issue and no explicit waiver).
- Pasting huge diffs instead of pointing at paths and describing the change.

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
- [ ] If leaving work for a contributor/another agent: post one agent-executable
      comment (section 5c) with P0/P1, problem/why/what/acceptance, non-goals,
      verification, and a done definition.
- [ ] Deferred out-of-PR work has a GitHub issue (section 5b) unless the human
      explicitly waived filing.

## References

- **tox skill** (`/td-tox`): Full tox environment reference.
- **td-pr-new** skill: PR body template and commit conventions.
- **td-pr-review** skill: Responding to review comments and resolving threads.
- **AGENTS.md**: Commit message standards and static check requirements.
