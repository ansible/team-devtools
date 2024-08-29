# Releases

## Overview

The projects maintained by the Ansible dev tools team have a target release frequency of 1 month. Some project may have more than 1 release per month based on project velocity or frequency of bug fixes or feature additions.

One person within the devtools team will act as "release manager" each month. This will ensure each project is reviewed to ensure a release for that month was made. If a particular project's CI tests are failing, the project maintainer will work with the release manager to clear the block. If a project already has a release within the current month a new release is not necessary unless there are merged PRs and release notes available for a new release.

The following project should be released first, in no particular order:

- [ansible-compat](https://github.com/ansible/ansible-compat/releases)

The following projects should be released second, in no particular order:

- [ansible-creator](https://github.com/ansible/ansible-creator/releases)
- [ansible-dev-environment](https://github.com/ansible/ansible-dev-environment/releases)
- [ansible-lint](https://github.com/ansible/ansible-lint/releases)
- [ansible-navigator](https://github.com/ansible/ansible-navigator/releases)
- [molecule](https://github.com/ansible/ansible-molecule/releases)
- [pytest-ansible](https://github.com/ansible/ansible-creator/releases)
- [tox-ansible](https://github.com/ansible/tox-ansible/releases)
- [VsCode extension](https://github.com/ansible/vscode-ansible/releases)

Finally, after running dependabot so the release notes are updated with dependencies:

- [ansible-dev-tools](https://github.com/ansible/ansible-dev-tools/releases)

This will release both a python project and image. Both the resulting python package and image should be validated to ensure each reflects the latest releases.

- [ansible-dev-tools on pypi](https://pypi.org/project/ansible-dev-tools/#history)
- [ansible-dev-tools image](https://github.com/ansible/ansible-dev-tools/pkgs/container/community-ansible-dev-tools)

## Schedule

Releases should be made on the first Wednesday of the month, but can be made the following Wednesday if necessary. This document should be updated with a pull request after the releases are complete.

### 2024-11

Release manager:

Completed date:

Notes:

### 2024-10

Release manager:

Completed date:

Notes:

### 2024-09

Release manager: @shatakshiiii

Completed date:

Notes:

### 2024-08

Release manager: @Qalthos

Completed date:

Notes:

- ansible-navigator [24.8.0](https://github.com/ansible/ansible-navigator/releases/tag/v24.8.0) released 2024-08-13
- pytest-ansible [24.8.0](https://github.com/ansible/pytest-ansible/releases/tag/v24.8.0) released 2024-08-16
- tox-ansible [24.8.0](https://github.com/ansible/tox-ansible/releases/tag/v24.8.0) released 2024-08-16
- molecule [24.8.0](https://github.com/ansible/molecule/releases/tag/v24.8.0) released 2024-08-16
- ansible-compat [24.8.0](https://github.com/ansible/ansible-compat/releases/tag/v24.8.0) released 2024-08-19

### 2024-07

Release manager: @alisonlhart

Completed date: 2024-07-18

Notes:
