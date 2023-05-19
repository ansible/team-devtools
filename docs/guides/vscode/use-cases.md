WIP work to codify various use-cases for vscode-ansible extension.

- Host OS:
  - Linux (`L`)
  - MacOS (`M`)
  - Windows (`W`)
- Execution
  - Native (`N`) -- ansible installed locally, likely inside a virtualenv
  - Podman (`P`) - creator-ee
  - Docker (`C`) - creator-ee

## Cases

- If user opens project on Windows without using WSL, we need to display error that LS is in broken state
- If `ansible`, `docker` and `podman` are all 3 missing, we need to display visible error that LS is in broken state
- We need a status/support page that reports current detected configuration, with info like
  - local ansible and ansible-lint, path, venv or not, versions
  - podman status: server, container version and tag, container sanity check
  - docker status: same as podman
