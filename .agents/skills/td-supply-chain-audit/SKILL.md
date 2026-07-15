---
name: td-supply-chain-audit
description: "Perform a supply chain vulnerability analysis across ADT ecosystem repos. Verifies commit signing, PR traceability, CI integrity, and dependency provenance within a time frame. Generates a standalone HTML dashboard report and PDF."
version: "1.0"
allowed-tools: Read, Grep, Glob, Shell, WebSearch, WebFetch, Write, AskUserQuestion
argument-hint: "[YYYY-MM-DD YYYY-MM-DD] or [YYYY-MM-DD YYYY-MM-DD package-name compromise-date]"
mandatory: false
type: workflow
triggers:
  - "supply chain audit"
  - "supply chain"
  - "commit integrity"
  - "dependency provenance"
---

# Supply Chain Audit

Perform a two-phase supply chain vulnerability analysis across the Ansible DevTools ecosystem repositories.

## Target Repositories

All under `github.com/ansible/`:

1. ansible-builder
2. ansible-compat
3. ansible-creator
4. ansible-dev-environment
5. ansible-lint
6. ansible-navigator
7. ansible-sign
8. molecule
9. pytest-ansible
10. tox-ansible
11. ansible-dev-tools
12. vscode-ansible

## Input

The user provides arguments as: `$ARGUMENTS`

### Phase 1 (Full Audit)

```
<start-date> <end-date>
```

Example: `2025-01-01 2025-03-01`

### Phase 2 (Package Focus)

```
<start-date> <end-date> <package-name> <compromise-date>
```

Example: `2025-01-01 2025-03-01 requests 2025-02-15`

The compromise-date is the date the package is suspected to have been compromised.

## Prerequisites

- `gh` CLI installed and authenticated (`gh auth status` must succeed)
- `python3` available (3.10+)
- Network access to GitHub API and PyPI/npm registries
- `playwright` Python package with Chromium (for PDF export): `pip install playwright && playwright install chromium`

## Instructions

### Step 1: Validate inputs

Parse `$ARGUMENTS` to extract:
- `start_date` and `end_date` (required, ISO format YYYY-MM-DD)
- Optionally: `package_name` and `compromise_date` (for Phase 2)

If arguments are missing or malformed, ask the user to provide them in the correct format and stop.

Verify prerequisites:
```bash
gh auth status
python3 --version
```

If either fails, inform the user and stop.

### Step 2: Run data collection

Execute the collection script from the skill's scripts directory:

```bash
python3 .agents/skills/td-supply-chain-audit/scripts/collect.py \
  --start "$start_date" \
  --end "$end_date" \
  --cache-dir ".supply-chain-audit/cache"
```

This will:
- Create the cache directory structure
- Fetch commits, PRs, check suites, and dependency diffs for all 12 repos
- Fetch all individual commits and review timelines within each merged PR
- Fetch branch protection rules and rulesets for each repo
- Store results as JSON in the cache directory
- Write a `manifest.json` for reproducibility

The script is idempotent: if cache files already exist for the same time frame, they are reused without re-fetching.

Monitor progress output. The script prints per-repo status. If rate-limited, it will back off automatically.

### Step 3: Run anomaly analysis

```bash
python3 .agents/skills/td-supply-chain-audit/scripts/analyze.py \
  --cache-dir ".supply-chain-audit/cache"
```

This detects (13 passes):
- Unsigned commits
- GitHub-web-signed commits (signer is GitHub, not a personal key)
- Orphan commits (no associated PR)
- Bypassed CI (merged with failing required checks)
- Post-merge pushes (commits after PR closed/merged)
- Replicated commit messages (near-duplicate of earlier commit)
- Renovate cooldown violations (dep adopted before configured `minimumReleaseAge`)
- Yanked/deleted package versions
- Branch protection rule changes or weak protection posture
- Post-approval commits in PRs (code pushed after review approval)
- Bot-only approvals (PRs merged without any human review)
- Self-approved PRs (author approved their own code with no independent review)
- Known vulnerabilities (all current packages scanned against OSV.dev)

Output: `findings.json` in the cache directory.

### Step 4: (Optional) Run package focus analysis

If the user provided a package name and compromise date:

```bash
python3 .agents/skills/td-supply-chain-audit/scripts/check_package.py \
  --cache-dir ".supply-chain-audit/cache" \
  --package "$package_name" \
  --compromise-date "$compromise_date"
```

Output: `package_focus.json` in the cache directory.

### Step 5: Write security recommendations

After analysis completes, **you** (the agent) must read the findings and write a prioritized top-10 list of actionable security recommendations specific to what was found.

1. Read the findings summary: `.supply-chain-audit/cache/<hash>/findings_summary.json` (compact aggregate view — categories, risk counts, per-repo breakdown, top findings per category)
2. If you need more detail on specific findings, read the full: `.supply-chain-audit/cache/<hash>/findings.json`
3. Read the protection rules: `.supply-chain-audit/cache/<hash>/protection/*.json`
4. Read the renovate configs: `.supply-chain-audit/cache/<hash>/renovate/*.json`
5. Reason about the most impactful actions the team should take based on:
   - Severity and count of findings by category
   - Patterns across repos (e.g., many repos missing the same protection)
   - Quick wins vs. systemic improvements
   - What would prevent the *worst* findings from recurring
5. Write `.supply-chain-audit/cache/<hash>/recommendations.json` as a JSON array of objects:

```json
[
  {
    "title": "Short actionable title",
    "detail": "HTML-safe explanation with context, affected repos, and concrete steps."
  }
]
```

Guidelines for writing recommendations:
- Be specific to what was actually found (reference repo names, counts, categories)
- Order by impact: what would eliminate the most critical/high findings first
- Don't be generic — tailor every recommendation to this audit's actual data
- Link findings to their root cause (e.g., "bot-only approvals exist because branch protection doesn't require human review")
- Recommendations should span THREE categories:
  1. **Technical controls** — GitHub settings, branch protection rules, CI config changes
  2. **Process/behavioral changes** — team policies, review norms, merge hygiene (e.g., "adopt a policy that bot-only approvals are never sufficient for human-authored code", "require a second human reviewer for changes to CI or dependency files")
  3. **Operational practices** — audit cadence, monitoring, incident response readiness
- Don't just tell them what to configure — tell them what habits to adopt and what behaviors to stop tolerating
- Concrete examples: "Stop merging PRs with only bot approval", "Rotate a security champion weekly to review this report", "Treat post-approval commits as a blocking concern in code review culture"

### Step 6: Generate HTML report

```bash
python3 .agents/skills/td-supply-chain-audit/scripts/report.py \
  --cache-dir ".supply-chain-audit/cache" \
  --output ".supply-chain-audit/report.html"
```

This produces a standalone HTML file (no CDN dependencies) with:
- Executive summary (traffic-light per repo)
- Timeline visualization (SVG)
- Commit integrity table (sortable, filterable)
- Dependency changes table with release dates
- Suspicious patterns grouped by category
- Security recommendations (from step 5)
- Package focus section (if Phase 2 data exists)

### Step 7: Generate PDF report

```bash
python3 .agents/skills/td-supply-chain-audit/scripts/pdf_export.py \
  --html ".supply-chain-audit/report.html" \
  --output ".supply-chain-audit/report.pdf"
```

This converts the HTML dashboard into a print-optimized PDF with:
- Light theme (white background) for readability on paper
- All collapsible sections expanded
- Interactive controls (sort, filter) hidden
- Proper page breaks between major sections
- A4 format with margins

The script requires `playwright` with Chromium. If not installed, run:
```bash
pip install playwright && playwright install chromium
```

### Step 8: Present results

After the reports are generated:

1. Print a summary of findings:
   - Total commits analyzed
   - Number of anomalies found per category
   - Repos with highest risk indicators
2. Provide the paths to the HTML and PDF report files
3. Highlight the top 3 recommendations with brief rationale
4. If Phase 2 was run, summarize which repos pulled in the suspect package and when

If critical findings are detected (bypassed CI, post-merge pushes, suspicious dep timing), highlight these prominently and recommend immediate investigation.

## Cache Behavior

- Cache location: `.supply-chain-audit/cache/`
- Cache key: first 16 hex chars of SHA-256(`start_date + end_date + sorted_repo_list`)
- Re-running with identical parameters produces identical output
- To force a fresh collection, delete the cache directory or pass `--force` to collect.py
- Git history is effectively immutable for merged PRs; cached data reflects the state at collection time
