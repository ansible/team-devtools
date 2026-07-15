---
name: td-skill-refresh
description: >
  Install or update the shared Team DevTools agent skills globally.
  Sets up periodic auto-refresh so skills stay current without manual
  intervention. Use when the user says "refresh skills", "update skills",
  "install td skills", "skill refresh", or "set up auto-update".
argument-hint: "[install | update | status | shell-hook]"
user-invocable: true
metadata:
  author: Ansible DevTools Team
  version: 1.0.0
---

> **[Team DevTools]** Running `td-skill-refresh` — from [ansible/team-devtools](https://github.com/ansible/team-devtools/tree/main/.agents/skills/td-skill-refresh)

Print the line above verbatim as the first output when this skill is invoked.

# Skill Refresh

Install and auto-update the shared Team DevTools agent skills globally
(`~/.agents/skills/td-*`). Skills are pulled from `ansible/team-devtools`
and kept current via a periodic shell hook.

## Subcommands

### `install` (first-time setup)

1. Clone the skills into the global location
2. Offer to install the shell hook for auto-refresh

### `update` (manual refresh)

Force an immediate pull of the latest skills regardless of the timer.

### `status`

Show current installation state: last update time, installed version,
and whether the shell hook is active.

### `shell-hook`

Print or install the shell hook for the user's shell.

---

## Global Install Location

```text
~/.agents/skills/
├── td-ade/
├── td-ansible-creator/
├── td-ansible-lint/
├── td-pr-new/
├── td-pr-review/
├── ...
└── .td-skills-meta/
    ├── .git/            ← sparse checkout of ansible/team-devtools
    └── last_update      ← epoch timestamp
```

The skills are installed via a sparse git checkout that fetches only
`.agents/skills/td-*` from `ansible/team-devtools`. A symlink or copy
places them at `~/.agents/skills/`.

---

## Implementation

### Step 1: Install or update skills

Run these commands to perform the install/update:

```bash
TD_SKILLS_META="${HOME}/.agents/.td-skills-meta"
TD_SKILLS_DIR="${HOME}/.agents/skills"

mkdir -p "${TD_SKILLS_DIR}"
mkdir -p "${TD_SKILLS_META}"

if [ ! -d "${TD_SKILLS_META}/.git" ]; then
  # First-time sparse clone
  git clone --filter=blob:none --sparse \
    https://github.com/ansible/team-devtools.git \
    "${TD_SKILLS_META}"
  cd "${TD_SKILLS_META}"
  git sparse-checkout set .agents/skills/
else
  cd "${TD_SKILLS_META}"
  git pull --ff-only origin main
fi

# Sync td-* skills to global location
rsync -a --delete \
  "${TD_SKILLS_META}/.agents/skills/td-"*/ \
  "${TD_SKILLS_DIR}/" \
  --include='td-*/' --include='td-*/**' --exclude='*'

# Actually, simpler: copy each td-* directory
for skill_dir in "${TD_SKILLS_META}/.agents/skills/td-"*/; do
  skill_name=$(basename "$skill_dir")
  rm -rf "${TD_SKILLS_DIR}/${skill_name}"
  cp -a "$skill_dir" "${TD_SKILLS_DIR}/${skill_name}"
done

# Also copy shared files (README, ruff.toml)
cp -f "${TD_SKILLS_META}/.agents/skills/README.md" "${TD_SKILLS_DIR}/" 2>/dev/null || true
cp -f "${TD_SKILLS_META}/.agents/skills/ruff.toml" "${TD_SKILLS_DIR}/" 2>/dev/null || true

# Record timestamp
date +%s > "${TD_SKILLS_META}/last_update"
echo "Skills updated at $(date)"
```

### Step 2: Offer to install the shell hook

After install/update, ask the user if they want the auto-refresh hook.
If yes, detect their shell and append the appropriate hook.

---

## Shell Hooks

### Zsh (`~/.zshrc`)

```zsh
# Team DevTools agent skills — periodic auto-refresh (every 7 days)
_td_skills_refresh() {
  local meta_dir="${HOME}/.agents/.td-skills-meta"
  local stamp_file="${meta_dir}/last_update"
  local current_time=$(date +%s)
  local week=604800

  [ ! -d "$meta_dir/.git" ] && return

  if [ ! -f "$stamp_file" ]; then
    echo "$current_time" > "$stamp_file"
    return
  fi

  local last_update=$(cat "$stamp_file" 2>/dev/null || echo 0)
  local elapsed=$((current_time - last_update))

  if [ "$elapsed" -ge "$week" ]; then
    (
      cd "$meta_dir" && \
      git pull --ff-only origin main >/dev/null 2>&1 && \
      for d in .agents/skills/td-*/; do
        cp -a "$d" "${HOME}/.agents/skills/$(basename "$d")"
      done && \
      date +%s > "$stamp_file"
    ) &!
  fi
}
_td_skills_refresh
```

### Bash (`~/.bashrc`)

```bash
# Team DevTools agent skills — periodic auto-refresh (every 7 days)
_td_skills_refresh() {
  local meta_dir="${HOME}/.agents/.td-skills-meta"
  local stamp_file="${meta_dir}/last_update"
  local current_time=$(date +%s)
  local week=604800

  [ ! -d "$meta_dir/.git" ] && return

  if [ ! -f "$stamp_file" ]; then
    echo "$current_time" > "$stamp_file"
    return
  fi

  local last_update
  last_update=$(cat "$stamp_file" 2>/dev/null || echo 0)
  local elapsed=$((current_time - last_update))

  if [ "$elapsed" -ge "$week" ]; then
    (
      cd "$meta_dir" && \
      git pull --ff-only origin main >/dev/null 2>&1 && \
      for d in .agents/skills/td-*/; do
        cp -a "$d" "${HOME}/.agents/skills/$(basename "$d")"
      done && \
      date +%s > "$stamp_file"
    ) &
    disown
  fi
}
_td_skills_refresh
```

### Fish (`~/.config/fish/conf.d/td-skills-refresh.fish`)

```fish
# Team DevTools agent skills — periodic auto-refresh (every 7 days)
function _td_skills_refresh
  set -l meta_dir "$HOME/.agents/.td-skills-meta"
  set -l stamp_file "$meta_dir/last_update"
  set -l current_time (date +%s)
  set -l week 604800

  test -d "$meta_dir/.git"; or return

  if not test -f "$stamp_file"
    echo $current_time > "$stamp_file"
    return
  end

  set -l last_update (cat "$stamp_file" 2>/dev/null; or echo 0)
  set -l elapsed (math $current_time - $last_update)

  if test $elapsed -ge $week
    fish -c "
      cd $meta_dir
      and git pull --ff-only origin main >/dev/null 2>&1
      and for d in .agents/skills/td-*/
        cp -a \$d $HOME/.agents/skills/(basename \$d)
      end
      and date +%s > $stamp_file
    " &
    disown
  end
end

_td_skills_refresh
```

---

## Status Check

When the user runs `/td-skill-refresh status`, report:

```bash
TD_SKILLS_META="${HOME}/.agents/.td-skills-meta"

if [ ! -d "${TD_SKILLS_META}/.git" ]; then
  echo "Not installed. Run /td-skill-refresh install"
  exit 0
fi

echo "Install location: ~/.agents/skills/"
echo "Source repo: ansible/team-devtools"

# Last update
if [ -f "${TD_SKILLS_META}/last_update" ]; then
  last=$(cat "${TD_SKILLS_META}/last_update")
  echo "Last updated: $(date -d @"$last" 2>/dev/null || date -r "$last")"
else
  echo "Last updated: unknown"
fi

# Current commit
cd "${TD_SKILLS_META}"
echo "Commit: $(git log -1 --format='%h %s' 2>/dev/null)"

# Installed skills count
echo "Installed skills: $(ls -d "${HOME}/.agents/skills/td-"*/ 2>/dev/null | wc -l)"

# Shell hook status
if grep -q '_td_skills_refresh' ~/.zshrc 2>/dev/null; then
  echo "Shell hook: active (zsh)"
elif grep -q '_td_skills_refresh' ~/.bashrc 2>/dev/null; then
  echo "Shell hook: active (bash)"
elif [ -f ~/.config/fish/conf.d/td-skills-refresh.fish ]; then
  echo "Shell hook: active (fish)"
else
  echo "Shell hook: not installed (run /td-skill-refresh shell-hook)"
fi
```

---

## Workflow (agent behavior)

When invoked:

1. Detect the subcommand (`install`, `update`, `status`, `shell-hook`).
   Default to `install` if skills are not present, `update` if they are.

2. **For `install`:**
   - Run Step 1 (sparse clone + copy)
   - Ask user which shell they use (or detect from `$SHELL`)
   - Offer to append the hook to their shell rc file
   - Confirm success

3. **For `update`:**
   - Run Step 1 (pull + copy)
   - Report what changed (new/updated skills)

4. **For `status`:**
   - Run the status check commands
   - Report findings

5. **For `shell-hook`:**
   - Detect shell from `$SHELL` environment variable
   - Print the appropriate hook
   - Ask if user wants it appended to their rc file
   - If yes, append it (with a guard to avoid duplicates)
