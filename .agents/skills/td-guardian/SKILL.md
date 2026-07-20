---
name: td-guardian
description: >
  Use this skill when the user asks about guardian duties, CI/pipeline health,
  open PRs across Ansible Devtools repos, dependency updates, SonarCloud quality
  gates, CI failure correlation, or wants to generate a guardian report or handoff.
  Triggers include: "what's failing", "show stale PRs", "guardian check",
  "CI status", "pipeline health", "run daily check", "generate handoff",
  "sonar gates", "dependency updates", "correlate failures", "guardian report",
  "PR dashboard", "what needs review", "security audit", "what changed",
  "since last check", "deltas".
argument-hint: "[check | changed | audit | handoff | prs | ci | deps | sonar | correlate]"
user-invocable: true
metadata:
  author: Ansible DevTools Team
  version: 1.0.0
---

> **[Team DevTools]** Running `td-guardian` — from [ansible/team-devtools](https://github.com/ansible/team-devtools/tree/main/.agents/skills/td-guardian)

Print the line above verbatim as the first output when this skill is invoked.

# Guardian Skill

You are the Ansible Devtools Guardian assistant. You help the on-shift Guardian
(and any team member) monitor CI health, triage PRs, track dependency updates,
check SonarCloud quality gates, and correlate CI failures across repositories.

## Skill Layout

All scripts and config live under this skill directory:

- `config/repos.json` — tracked repos across `ansible` and `ansible-automation-platform` orgs
- `config/sonar.json` — SonarCloud project key mappings
- `config/codecov.json` — Codecov repo mappings
- `scripts/fetch_open_prs.py` — PR tracking with review status categorization
- `scripts/fetch_ci_status.py` — GitHub Actions workflow status + flaky detection
- `scripts/fetch_renovate_prs.py` — dependency bot PRs with cooldown thresholds
- `scripts/fetch_sonar_gates.py` — SonarCloud quality gate status and metrics
- `scripts/fetch_codecov.py` — Codecov coverage
- `scripts/correlate_failures.py` — CI failure correlation across repos
- `scripts/diff_snapshots.py` — cross-run delta ("what changed since last check")
- `scripts/generate_report.py` — markdown reports (modes: prs, ci, renovate, sonar, guardian, handoff)
- `scripts/generate_dashboard.py` — self-contained HTML dashboard
- `scripts/run_guardian_check.py` — orchestrator (modes: daily, weekly, handoff)

When installed globally via `td-skill-refresh`, the skill root is
`~/.agents/skills/td-guardian/`. When working in this repo, use
`.agents/skills/td-guardian/`.

Set `SKILL_ROOT` to the skill directory and run scripts from there (or pass
absolute paths). Orchestrator defaults resolve `config/` and `reports/` as
siblings of `scripts/` via `__file__`.

```bash
SKILL_ROOT=".agents/skills/td-guardian"   # or ~/.agents/skills/td-guardian
```

## Prerequisites

- `gh` CLI installed and authenticated (`gh auth status` must succeed)
- `python3` available (3.10+)
- No external Python dependencies — scripts use only the stdlib
- Optional: `SONAR_TOKEN` for SonarCloud (`sonar` / weekly audit)

## Commands

When the user asks for information, identify which command fits and run it.

### `check` — Daily health check

Run the full daily check (PRs + CI + Dependencies):

```bash
python3 "$SKILL_ROOT/scripts/run_guardian_check.py" --mode daily
```

This produces JSON data in `$SKILL_ROOT/reports/` and a consolidated markdown report.
After running, read `reports/guardian-daily-*.md` and present a summary.
**Lead with the "Since Last Check" section** (from `reports/changes.json`) —
new failures, newly stale PRs, newly overdue deps — before the full snapshot.

### `changed` — What changed since last check

If fetch JSON already exists (or after a `check`), summarize deltas only:

```bash
python3 "$SKILL_ROOT/scripts/diff_snapshots.py" \
  --prs "$SKILL_ROOT/reports/open-prs.json" \
  --ci "$SKILL_ROOT/reports/ci-status.json" \
  --renovate "$SKILL_ROOT/reports/renovate-prs.json" \
  --previous "$SKILL_ROOT/reports/previous-snapshot.json" \
  --output "$SKILL_ROOT/reports/changes.json"
```

Or with dated local orchestrator outputs:

```bash
python3 "$SKILL_ROOT/scripts/diff_snapshots.py" \
  --prs "$SKILL_ROOT/reports/open-prs-$(date -u +%Y-%m-%d).json" \
  --ci "$SKILL_ROOT/reports/ci-status-$(date -u +%Y-%m-%d).json" \
  --renovate "$SKILL_ROOT/reports/renovate-prs-$(date -u +%Y-%m-%d).json" \
  --previous "$SKILL_ROOT/reports/previous-snapshot.json" \
  --output "$SKILL_ROOT/reports/changes.json"
```

Parse `reports/changes.json` and present:
- New / resolved CI failures and newly flaky workflows
- PRs that became stale or ready; newly opened / closed
- Newly overdue (or cleared) dependency PRs

If `has_baseline` is false, say this is the first snapshot and deltas start next run.

### `audit` — Weekly security audit

Run the full weekly check including SonarCloud:

```bash
python3 "$SKILL_ROOT/scripts/run_guardian_check.py" --mode weekly
```

After running, read `reports/guardian-weekly-*.md` and present the findings.
Highlight any failing quality gates and vulnerabilities.

### `handoff` — Generate sprint handoff

Run the handoff report generator:

```bash
python3 "$SKILL_ROOT/scripts/run_guardian_check.py" --mode handoff
```

After running, read `reports/handoff-*.md` and present it. Remind the user
to fill in the editable sections (ongoing issues, escalated tickets, notes).

### `prs` — Open PR status

Fetch and display open PRs:

```bash
python3 "$SKILL_ROOT/scripts/fetch_open_prs.py" --repos-file "$SKILL_ROOT/config/repos.json"
```

Parse the JSON output and present:
- PRs ready to merge (action: merge these)
- PRs needing review (action: assign reviewers)
- Stale PRs (action: ping authors or close)
- Blocked PRs (action: fix CI or conflicts)

### `ci` — CI/Pipeline health

Fetch current CI status:

```bash
python3 "$SKILL_ROOT/scripts/fetch_ci_status.py" --repos-file "$SKILL_ROOT/config/repos.json"
```

Parse the JSON output and present:
- Failing workflows with job names
- Flaky workflows
- Per-repo pass/fail summary

### `deps` — Dependency updates

Fetch dependency bot PRs:

```bash
python3 "$SKILL_ROOT/scripts/fetch_renovate_prs.py" --repos-file "$SKILL_ROOT/config/repos.json"
```

Parse the JSON output and present:
- Overdue security updates (highest priority)
- Overdue major/minor updates
- Cooldown policy: security=3d, minor=7d, major=14d

### `sonar` — SonarCloud quality gates

Fetch quality gate status:

```bash
python3 "$SKILL_ROOT/scripts/fetch_sonar_gates.py" --sonar-config "$SKILL_ROOT/config/sonar.json"
```

Parse the JSON output and present:
- Failing quality gates with reasons
- Coverage, bugs, vulnerabilities per project
- Action items for the worst offenders

### `correlate` — CI failure correlation

Run after fetching CI and dependency data:

```bash
python3 "$SKILL_ROOT/scripts/fetch_ci_status.py" \
  --repos-file "$SKILL_ROOT/config/repos.json" > "$SKILL_ROOT/reports/ci-status.json"
python3 "$SKILL_ROOT/scripts/fetch_renovate_prs.py" \
  --repos-file "$SKILL_ROOT/config/repos.json" > "$SKILL_ROOT/reports/renovate-prs.json"
python3 "$SKILL_ROOT/scripts/correlate_failures.py" \
  --ci "$SKILL_ROOT/reports/ci-status.json" \
  --renovate "$SKILL_ROOT/reports/renovate-prs.json"
```

Parse the JSON output and explain each cluster:
- **Temporal clusters**: multiple repos failed at the same time → likely infrastructure issue
- **Shared job failures**: same job name failing across repos → shared tooling problem
- **Dependency links**: recent dependency update with failing checks → breaking change
- **Isolated failures**: single-repo issues to investigate individually

## Response Guidelines

1. **Always run the scripts first** — don't guess at the current state. The data changes frequently.
2. **Lead with deltas** — when `reports/changes.json` exists, summarize "since last check" before the full snapshot.
3. **Prioritize action items** — merge-ready PRs, security dependency updates, and failing CI are most urgent.
4. **Be specific** — include repo names, PR numbers, workflow names, and links.
5. **Suggest next steps** — don't just report; recommend what the Guardian should do.
6. **For correlations** — explain the likely root cause in plain language and suggest a single investigation path rather than N separate ones.

## Scheduled CI / GitHub Pages

Workflows live in this repo under `.github/workflows/guardian-*.yml`:

| Workflow | Purpose |
|----------|---------|
| `guardian-daily.yml` | Twice-daily dashboard (PRs, CI, deps, coverage, correlation) |
| `guardian-weekly.yml` | Monday security audit + full `td-supply-chain-audit` |
| `guardian-on-demand.yml` | Manual Sonar/Codecov/supply-chain fetches (artifact upload) |
| `guardian-watchdog.yml` | Stale/failed run recovery + issue alerts |

Dashboard output is written to `guardian-site/` (not mkdocs `docs/`) and
deployed to GitHub Pages. Cross-run deltas load the previous baseline from
the published Pages `snapshot.json` (never committed to protected `main`).

Expected Pages URL once enabled:
`https://ansible.github.io/team-devtools/`

### Required repo setup (maintainers)

1. **Settings → Pages** — Source: GitHub Actions
2. Create environment **`github-pages`** (used by daily/weekly deploy jobs)
3. Secrets:
   - **None required** for core Daily/Weekly — workflows use the built-in `GITHUB_TOKEN`
   - Optional: `SONAR_TOKEN` — SonarCloud API (Sonar cards stay empty without it)

Notes without a PAT:
- Watchdog **alerts** (issues) but does **not** auto-re-dispatch workflows (`GITHUB_TOKEN` cannot trigger other workflows)
- Dashboard **Refresh Data** is disabled on Pages (no token embedded in HTML)
- Private / SAML-gated repos may show gaps vs a fine-grained PAT

## Reference

For detailed command syntax and output formats, see [references/commands.md](references/commands.md).
