# Agent Skills

Agent skills for development and maintenance workflow automation in Ansible Devtools.

All skills are prefixed with `td-` (team-devtools) to avoid naming conflicts
when synced to downstream repositories that may have their own local skills.

## Available Skills

### Pull Requests (`td-pr-*`)

| Skill | Purpose | Arguments |
|-------|---------|-----------|
| `td-pr-new` | Prepare and submit a pull request | `[branch-name] [--title 'PR title']` |
| `td-pr-review` | Handle PR review feedback | `<PR number>` |
| `td-pr-contributor-review` | Review and prepare a contributor's PR (upstream/fork) | `<PR number or URL>` |

### Bot PR Maintenance (`td-fix-bot-prs`, `td-scan-bot-prs`, `td-rebase-pr`, `td-diagnose-ci`, `td-verify-local`)

| Skill | Purpose | Arguments |
|-------|---------|-----------|
| `td-fix-bot-prs` | Orchestrator: find, diagnose, and fix broken renovate/dependabot PRs | `[repo] [PR number] [--interactive]` |
| `td-scan-bot-prs` | Scan repos for failing bot PRs, produce prioritized list | `[repo]` |
| `td-rebase-pr` | Rebase a PR onto main, push, wait for CI | `<repo> <PR number>` |
| `td-diagnose-ci` | Fetch CI failure logs, categorize, assess fix complexity | `<repo> <PR number>` |
| `td-verify-local` | Run lint + pkg checks locally before pushing | `[--with-tests]` |

### Security & Auditing

| Skill | Purpose | Arguments |
|-------|---------|-----------|
| `td-supply-chain-audit` | Comprehensive supply-chain vulnerability analysis | `[last N days] [help] [dive SCA-NNN]` |

Guardian dashboard / `td-guardian` now lives in
[devtools1/guardian-dashboard](https://gitlab.cee.redhat.com/devtools1/guardian-dashboard)
(GitLab CEE), including scheduled CI and Pages.

### Utilities

| Skill | Purpose | Arguments |
|-------|---------|-----------|
| `td-tox` | tox environment reference (lint, test, docs, pkg) | `[environment-name]` |
| `td-release-order` | Determine correct release ordering across devtools packages | — |
| `td-architecture-diagram` | Generate architecture diagrams for devtools repos | — |

### Ansible Developer Tools

| Skill | Purpose | Arguments |
|-------|---------|-----------|
| `td-ansible-creator` | Scaffold collections, playbooks, EEs, plugins | `[subcommand]` |
| `td-ansible-lint` | Ansible playbook/role/collection linting reference | `[options]` |
| `td-ade` | Development environment setup with ansible-dev-environment | `[subcommand]` |

## Skill Structure

```text
skills/
├── README.md                        ← You are here
├── td-ade/
│   └── SKILL.md
├── td-ansible-creator/
│   └── SKILL.md
├── td-ansible-lint/
│   └── SKILL.md
├── td-architecture-diagram/
│   └── SKILL.md
├── td-diagnose-ci/
│   └── SKILL.md
├── td-fix-bot-prs/
│   └── SKILL.md
├── td-pr-contributor-review/
│   └── SKILL.md
├── td-pr-new/
│   └── SKILL.md
├── td-pr-review/
│   └── SKILL.md
├── td-rebase-pr/
│   └── SKILL.md
├── td-release-order/
│   └── SKILL.md
├── td-scan-bot-prs/
│   └── SKILL.md
├── td-supply-chain-audit/
│   └── SKILL.md
├── td-tox/
│   └── SKILL.md
└── td-verify-local/
    └── SKILL.md
```

## SKILL.md Format

Each skill has YAML front matter:

```yaml
---
name: td-skill-name
description: >-
  What the skill does. When to use it. Trigger phrases.
argument-hint: "[expected arguments]"
user-invocable: true
metadata:
  author: Ansible DevTools Team
  version: 1.0.0
---
```

## Version

- **Version**: 1.1.0
- **Author**: Ansible DevTools Team
- **License**: GPL-3.0-or-later
