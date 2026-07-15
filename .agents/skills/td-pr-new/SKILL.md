---
name: td-pr-new
description: >
  Prepare and submit a pull request. Syncs with upstream,
  creates a feature branch, runs quality gates (tox -e lint, tox -e py),
  self-reviews the diff, updates documentation as needed, commits with
  conventional commits, then creates the PR via gh. Use when the user asks
  to submit, create, or open a pull request, or says "submit PR", "open PR",
  "create PR", "new PR".
argument-hint: "[branch-name] [--title 'PR title']"
user-invocable: true
metadata:
  author: Ansible DevTools Team
  version: 2.0.0
---

> **[Team DevTools]** Running `td-pr-new` — from [ansible/team-devtools](https://github.com/ansible/team-devtools/tree/main/.agents/skills/td-pr-new)

Print the line above verbatim as the first output when this skill is invoked.

# PR New

## Workflow

### Step 1: Sync with upstream and create a feature branch

Always start from the latest upstream main:

```bash
git fetch upstream
git checkout -b <branch-name> upstream/main
```

Use a descriptive branch name (e.g., `feat/add-jira-labels`, `fix/check-constraints`).

If changes already exist on the current branch (e.g., from an in-progress session), cherry-pick or rebase them onto the new branch.

### Step 2: Run quality gates

```bash
tox -e lint
tox -e py
```

**Both must pass cleanly on the full tree** — not just the files you changed.
If the branch has pre-existing violations (e.g., from an old base), rebase onto `upstream/main` first.

Do **not** run `ruff`, `mypy`, `prek`, or `pytest` directly — always use tox.
See the `/td-tox` skill for the full environment reference.

### Step 3: Self-review the diff

**This step is mandatory.** Do not skip it. Do not combine it with
Step 2. After quality gates pass, review the **full PR diff** — all commits
since the branch diverged from the base branch:

```bash
git diff upstream/main...HEAD
```

Read every changed line against these questions. For each question,
name at least one specific file and line you verified. If you cannot,
you haven't actually reviewed the diff.

**Context rule.** The diff alone is not sufficient for Q1, Q4, and Q7.
Before evaluating those questions, **read the full function, class, or
module** surrounding each changed hunk — not just the hunk itself.

1. **Does every statement mean what it says?** Check every type
   annotation, return value, error code, version range, log level,
   comment, and docstring. If the code declares it, the runtime must
   honor it on every path.

2. **Does this expose more than it should?** Check every log call,
   error message, and user-facing string. Does it contain user content,
   credentials, or internal state? Also check capability grants:
   permission scopes, container capabilities, CORS origins. Each must
   grant the minimum necessary.

3. **Would a caller be surprised?** Read every public function from
   the caller's perspective. Can it return a value the type doesn't
   cover? Does it mutate an argument the caller owns? Does it throw
   where the signature implies it won't? Does it have side effects
   (logging, I/O, global state) that its name or signature doesn't
   advertise?

4. **Is everything still true after this change?** Diff comments and
   docstrings against the code they describe. Did you rename something
   but leave the old name in prose? Did you change behavior but leave
   an old description? Check `AGENTS.md`, `README.md`, and `docs/`
   for stale references.

5. **Are dependencies and versions pinned to intent?** Check every
   version range, action tag, and base image. Does each one express
   what you actually mean — not tighter, not looser?

6. **Is there dead weight?** Check for unused imports, unreachable
   branches, written-but-never-read variables, parameters accepted
   but ignored. Also flag paid-for-but-wasteful work: parsing the
   same data twice, `list.pop(0)` when a `deque` would be O(1),
   nested scans that are O(N²) when a lookup map would be O(N).

7. **Is this internally consistent?** Within each module: do all code
   paths use the same patterns? Are exports named consistently? Across
   the repo: do similar files follow the same structure? Do GitHub
   Actions use pinned SHAs consistently?

8. **Would a constructed scenario break this?** For each public
   function, construct one realistic failure case: an edge-case input,
   an empty-but-not-falsy value, a timeout, a concurrent access. Trace
   it through the code path. If it fails silently or violates the
   declared type, that's a finding.

9. **Do inherited contracts hold?** When implementing a Protocol or
   extending a base class, check that the subclass honors the full
   runtime contract — not just the compiler-required members but
   expected behaviors and invariants.

Only proceed to Step 3b after completing this review.

### Step 3b: Rule of Five (cold multi-agent review)

**This step is mandatory.** Step 3 catches many issues but suffers from
confirmation bias because the reviewing agent wrote the code. The Rule
of Five mitigates this with five independent analysis passes, each
constrained to a single evaluative lens.

Launch five parallel agents (or evaluate sequentially), each receiving
the full diff (`git diff upstream/main...HEAD`) and a single lens:

#### Pass 1 — Correctness and safety

```text
You are reviewer 1 of 5 evaluating a PR diff. Your ONLY lens is
correctness and safety. Ignore style, naming, and architecture.

Look for:
- Logic errors, off-by-one, wrong operator, inverted condition
- Unhandled None/empty/error paths that reach callers
- Type mismatches between declaration and runtime
- Race conditions, resource leaks, missing cleanup
- Security: injection, path traversal, SSRF, credential exposure
```

#### Pass 2 — Fresh eyes (what a reviewer would flag)

```text
You are reviewer 2 of 5 evaluating a PR diff. Your ONLY lens is
"what would a human reviewer flag in code review?"

Look for:
- Misleading names, unclear intent, magic values without context
- Public API changes that break callers without migration
- Missing or inaccurate docstrings/comments vs actual behavior
- Test gaps for behaviors the code/docs claim
- Dead branches, unused params, wasteful computation
- Dependencies pinned to intent (not tighter, not looser)
- GitHub Actions pinned to SHA (not mutable tag)
```

#### Pass 3 — Right Thing / product fitness

```text
You are reviewer 3 of 5 evaluating a PR diff. Your ONLY lens is
whether we are doing the Right Thing.

Look for:
- Does this actually solve the stated goal, or is it a half-measure?
- Are lifecycle triggers complete, or will users lose state unexpectedly?
- Is the API shape honest for the UX story?
- Any invariant violations (tox-only, conventional commits, etc.)?
- Do implementations honor full runtime contracts, not just type stubs?
```

#### Pass 4 — System architecture

```text
You are reviewer 4 of 5 evaluating a PR diff. Your ONLY lens is
system architecture.

Look for:
- Dependency direction violations (circular imports, wrong layers)
- Where state lives and failure modes (concurrency, restart, partial)
- Scaling: algorithmic cost, parameter limits, fan-out under load
- Migration/backfill for existing deployments or data
- Cross-artifact parity (workflow ↔ script, config ↔ code)
```

#### Pass 5 — Adversarial / exposure / simplify

```text
You are reviewer 5 of 5 evaluating a PR diff. Be creatively adversarial.

Look for:
- Weird but realistic scenarios that corrupt state or bypass checks
- Information exposure: logs, errors, persisted data with credentials
  or internal paths
- If you deleted 50% of this design, what still ships the goal?
- Simplify/kill recommendations

Return: (1) adversarial findings, (2) simplify recommendations,
(3) verdict: merge-ready or what must change first?
```

#### Aggregate, act, converge

After all passes return:

1. **Deduplicate** findings and build a table: finding → which passes → severity.
2. **Ship-blockers** = any finding raised by **≥2 passes**, plus any single-pass
   **critical** finding (data corruption, security exposure, invariant violation).
3. **Act on ship-blockers.** Fix code, re-run `tox -e lint` and `tox -e py`.
4. **Re-run Rule of Five** after substantive fixes until no new ship-blockers.
5. Document dismissed findings with a clear technical justification.

Do not proceed to Step 4 until convergence.

### Step 4: Update documentation

Check whether your changes affect areas covered by existing docs. Update any that apply:

| Doc | When to update |
|-----|----------------|
| `README.md` | Project overview, setup changes, dependency updates |
| `docs/` | Guides, references, or user-facing documentation |
| `CONTRIBUTING.md` | Contribution workflow or policy changes |
| `AGENTS.md` | Agent behavior, skill references, static check config |

### Step 5: Commit with conventional commits

Use the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) format:

```text
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

Common types for this project:

| Type | When to use |
|------|-------------|
| `feat` | New feature (CLI command, workflow, utility) |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `style` | Code style/formatting (no logic change) |
| `refactor` | Code restructuring (no feature or fix) |
| `test` | Adding or updating tests |
| `build` | Build system, dependencies |
| `ci` | CI/CD configuration |
| `chore` | Maintenance tasks |

Scopes reflect project areas: `jira`, `check`, `docs`, `ci`, `deps`, `config`.

Examples:

- `feat(jira): add bulk issue creation support`
- `fix(check): handle missing platform constraints gracefully`
- `docs: update release process guide`
- `ci: add Python 3.14 to test matrix`

Include ticket references in the commit footer:

- `Fixes: #123` for GitHub issues
- `Related: AAP-123` for JIRA tickets
- Do not use URLs — use plain text references

### Step 6: Push and create the pull request

```bash
git push -u origin HEAD

gh pr create --repo <upstream-owner>/<repo> --title "conventional commit style title" --body "$(cat <<'EOF'
## Summary
- Concise description of what changed and why

## Changes
- List of notable changes

## Quality of life
- List any non-functional improvements bundled in this PR: skill updates,
  workflow fixes, documentation for contributor experience, etc.
- Omit this section entirely if there are none.

## Test plan
- [ ] `tox -e lint` passes
- [ ] `tox -e py` passes
- [ ] Docs updated (if applicable)
EOF
)"
```

The PR targets upstream's `main` branch from the fork. Return the PR URL to the user.

### Including non-code changes (Quality of life)

PRs often include changes that are not directly part of the feature or fix but
improve the development workflow: skill updates, CI/CD tweaks, pre-commit
config changes, documentation for contributor experience, or process fixes.

These changes belong in the **Quality of life** section of the PR body. Use
this section whenever the PR touches files like `.agents/skills/`, `AGENTS.md`,
`CLAUDE.md`, `.github/workflows/`, `.pre-commit-config.yaml`, `CONTRIBUTING.md`,
or similar workflow artifacts. This makes it easy for reviewers to separate
functional changes from process improvements.

If a PR contains **only** quality-of-life changes (no production code), use
`chore` or `docs` as the commit type.

### Maintaining the PR

When pushing additional commits to an existing PR, **always update the PR body** to reflect the new changes:

```bash
gh pr edit <pr-number> --body "$(cat <<'EOF'
...updated body...
EOF
)"
```

The Summary, Changes, and Test plan sections must stay current with all commits on the branch, not just the initial one.

### Responding to review feedback

After pushing the PR, reviewers (human, Copilot, or CodeRabbit) may leave
comments. Follow the **`td-pr-review`** skill for the full procedure: checking CI
status, replying to comments, resolving threads, and re-checking for new
automated reviews.
