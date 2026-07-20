# Guardian Command Reference

## Script Locations

Skill root examples:

- Repo checkout: `.agents/skills/td-guardian/`
- Global install: `~/.agents/skills/td-guardian/`

All scripts are in `$SKILL_ROOT/scripts/`.
Config files are in `$SKILL_ROOT/config/`.
Reports are generated in `$SKILL_ROOT/reports/`.

Orchestrator path defaults are relative to the scripts directory (`__file__`),
so invoking `run_guardian_check.py` with an absolute path works without
setting `$SKILL_ROOT`.

## fetch_open_prs.py

```bash
# Single repo
python3 "$SKILL_ROOT/scripts/fetch_open_prs.py" ansible ansible-lint

# All repos
python3 "$SKILL_ROOT/scripts/fetch_open_prs.py" --repos-file "$SKILL_ROOT/config/repos.json"

# Custom stale threshold
python3 "$SKILL_ROOT/scripts/fetch_open_prs.py" --repos-file "$SKILL_ROOT/config/repos.json" --stale-days 14

# Include bot PR details
python3 "$SKILL_ROOT/scripts/fetch_open_prs.py" --repos-file "$SKILL_ROOT/config/repos.json" --include-bots
```

**PR Categories:**
- `ready_to_merge` — approved, checks passing, no conflicts
- `needs_review` — no reviews yet or review requested
- `changes_requested` — reviewer requested changes
- `draft` — PR is in draft state
- `stale` — no activity in 14+ days
- `blocked` — merge conflicts or failing checks

## fetch_ci_status.py

```bash
# Single repo
python3 "$SKILL_ROOT/scripts/fetch_ci_status.py" ansible ansible-lint

# All repos, last 3 days
python3 "$SKILL_ROOT/scripts/fetch_ci_status.py" --repos-file "$SKILL_ROOT/config/repos.json"

# Custom time range
python3 "$SKILL_ROOT/scripts/fetch_ci_status.py" --repos-file "$SKILL_ROOT/config/repos.json" --days 7

# Scheduled runs only (matches official DevTools status page)
python3 "$SKILL_ROOT/scripts/fetch_ci_status.py" --repos-file "$SKILL_ROOT/config/repos.json" --event schedule
```

**Primary CI tracking:** Each repo's main CI workflow (configured via
`ci_workflow` in repos.json) is tracked separately using `event=schedule`,
matching the official Ansible DevTools status page badges.

**Flaky detection:** A workflow is flagged as flaky if its last 5 runs
alternate between success and failure 2+ times.

## fetch_renovate_prs.py

```bash
# Single repo
python3 "$SKILL_ROOT/scripts/fetch_renovate_prs.py" ansible ansible-lint

# All repos
python3 "$SKILL_ROOT/scripts/fetch_renovate_prs.py" --repos-file "$SKILL_ROOT/config/repos.json"
```

**Cooldown thresholds:**
- Security updates: overdue after 3 days
- Minor/patch updates: overdue after 7 days
- Major version bumps: overdue after 14 days

## fetch_sonar_gates.py

```bash
# All projects
python3 "$SKILL_ROOT/scripts/fetch_sonar_gates.py" --sonar-config "$SKILL_ROOT/config/sonar.json"

# Single project
python3 "$SKILL_ROOT/scripts/fetch_sonar_gates.py" --project-key ansible_ansible-lint

# With authentication
SONAR_TOKEN=xxx python3 "$SKILL_ROOT/scripts/fetch_sonar_gates.py" --sonar-config "$SKILL_ROOT/config/sonar.json"
```

**Metrics fetched:** coverage, bugs, vulnerabilities, code_smells,
duplicated_lines_density, security_hotspots, ncloc, reliability_rating,
security_rating, sqale_rating.

## fetch_codecov.py

```bash
# All repos from codecov config
python3 "$SKILL_ROOT/scripts/fetch_codecov.py" --codecov-config "$SKILL_ROOT/config/codecov.json"

# All repos from repos.json
python3 "$SKILL_ROOT/scripts/fetch_codecov.py" --repos-file "$SKILL_ROOT/config/repos.json"

# Single repo
python3 "$SKILL_ROOT/scripts/fetch_codecov.py" ansible ansible-lint
```

**Metrics fetched:** coverage percentage, lines, hits, misses, branches,
language, and active status per repo. Aggregates include average/min/max
coverage, repos above 80%, and repos below 50%.

## correlate_failures.py

```bash
# CI data only
python3 "$SKILL_ROOT/scripts/correlate_failures.py" --ci "$SKILL_ROOT/reports/ci-status.json"

# With dependency correlation
python3 "$SKILL_ROOT/scripts/correlate_failures.py" \
  --ci "$SKILL_ROOT/reports/ci-status.json" \
  --renovate "$SKILL_ROOT/reports/renovate-prs.json"

# Save to file
python3 "$SKILL_ROOT/scripts/correlate_failures.py" \
  --ci "$SKILL_ROOT/reports/ci-status.json" \
  -o "$SKILL_ROOT/reports/correlation.json"
```

**Cluster types:**
- `temporal` — repos failing within 2-hour window
- `shared_job` — same job name failing across 2+ repos
- `dependency` — failing dependency PR + downstream test failures

## diff_snapshots.py

```bash
# Compare current fetch JSON to the rotating baseline
python3 "$SKILL_ROOT/scripts/diff_snapshots.py" \
  --prs "$SKILL_ROOT/reports/open-prs.json" \
  --ci "$SKILL_ROOT/reports/ci-status.json" \
  --renovate "$SKILL_ROOT/reports/renovate-prs.json" \
  --previous "$SKILL_ROOT/reports/previous-snapshot.json" \
  --output "$SKILL_ROOT/reports/changes.json" \
  --write-previous "$SKILL_ROOT/reports/previous-snapshot.json"
```

**Outputs:**
- `reports/changes.json` — structured deltas (new failures, became stale, newly overdue, …)
- `reports/previous-snapshot.json` — compact baseline rotated after each successful diff (when `--write-previous` is set)

In CI, the previous baseline is loaded from the published GitHub Pages
`snapshot.json` (not committed to `main`), then redeployed with the Pages artifact.

**Summary keys:** `new_failures`, `resolved_failures`, `new_flaky`, `became_stale`,
`became_ready`, `newly_opened`, `closed_or_merged`, `newly_overdue`, `no_longer_overdue`.

If `--previous` is missing, `has_baseline` is false and lists are empty (first-run case).

## generate_report.py

```bash
# Individual reports
python3 "$SKILL_ROOT/scripts/generate_report.py" prs "$SKILL_ROOT/reports/open-prs.json"
python3 "$SKILL_ROOT/scripts/generate_report.py" ci "$SKILL_ROOT/reports/ci-status.json"
python3 "$SKILL_ROOT/scripts/generate_report.py" renovate "$SKILL_ROOT/reports/renovate-prs.json"
python3 "$SKILL_ROOT/scripts/generate_report.py" codecov "$SKILL_ROOT/reports/codecov.json"
python3 "$SKILL_ROOT/scripts/generate_report.py" sonar "$SKILL_ROOT/reports/sonar-gates.json"

# Consolidated reports (include --changes for Since Last Check)
python3 "$SKILL_ROOT/scripts/generate_report.py" guardian \
  --prs FILE --ci FILE --renovate FILE --codecov FILE --sonar FILE \
  --changes "$SKILL_ROOT/reports/changes.json"
python3 "$SKILL_ROOT/scripts/generate_report.py" handoff \
  --prs FILE --ci FILE --renovate FILE --codecov FILE --sonar FILE

# Write to file
python3 "$SKILL_ROOT/scripts/generate_report.py" prs \
  "$SKILL_ROOT/reports/open-prs.json" -o "$SKILL_ROOT/reports/pr-dashboard.md"
```

## run_guardian_check.py

```bash
# Daily (PRs + CI + Dependencies + Coverage + snapshot diff)
python3 "$SKILL_ROOT/scripts/run_guardian_check.py" --mode daily

# Weekly (Daily + SonarCloud)
python3 "$SKILL_ROOT/scripts/run_guardian_check.py" --mode weekly

# Handoff (Weekly + Jira template)
python3 "$SKILL_ROOT/scripts/run_guardian_check.py" --mode handoff
```

**Exit codes:** 0 = all green, 1 = issues found, 2 = script errors.

Also writes/updates `reports/changes.json` and `reports/previous-snapshot.json`.
