# Releases

## Overview

The projects maintained by the Ansible dev tools team have a target release frequency of 1 month. Some project may have more than 1 release per month based on project velocity or frequency of bug fixes or feature additions.

One person within the devtools team will act as **release manager** each month. This will ensure each project is reviewed to ensure a release for that month was made.

## Checklist

- [ ] If a particular project's CI tests are failing, the release manager will coordinate with the project' SME to clear the block using [#ansible-devtools] slack channel.
- [ ] If a project already has a release within the current month a new release is not necessary unless there are merged PRs and release notes available for a new release.
- [ ] A release should be made only if it contains at least one change that is changing the deliverable.

## Release order

### Python projects

Stage 1, release below if needed:

- [ansible-compat](https://github.com/ansible/ansible-compat/releases)

Stage 2, release the following projects, in no particular order:

- [ansible-creator](https://github.com/ansible/ansible-creator/releases)
- [ansible-dev-environment](https://github.com/ansible/ansible-dev-environment/releases)
- [ansible-lint](https://github.com/ansible/ansible-lint/releases)
- [ansible-navigator](https://github.com/ansible/ansible-navigator/releases)
- [molecule](https://github.com/ansible/molecule/releases)
- [pytest-ansible](https://github.com/ansible/pytest-ansible/releases)
- [tox-ansible](https://github.com/ansible/tox-ansible/releases)

### Update galaxy-importer before downstream release

- [galaxy-importer](https://github.com/ansible/galaxy-importer)
  - Update ansible-lint version in [setup.cfg](https://github.com/ansible/galaxy-importer/blob/master/setup.cfg) and open a PR. Ensure the ansible-lint version is confirmed for the downstream release before doing this. Ask the Hub team to review the PR in either [#ansible-galaxy-internal] or [#wg-hub-delivery] Slack channels.
  - Notify Partner Engineering about the ansible-lint version update in importer in the [#ansible-partners] Slack channel using `@ansible-pe`.
  - Ask the Hub team to make a new release of galaxy-importer.
  - Add the new released version of importer to downstream packages list to notify PDE of the change.

### ADT Release

Finally, after running dependabot so the release notes are updated with dependencies:

- [ansible-dev-tools](https://github.com/ansible/ansible-dev-tools/releases)

This will release both a python project and image. Both the resulting python package and image should be validated to ensure each reflects the latest releases.

- [ansible-dev-tools on pypi](https://pypi.org/project/ansible-dev-tools/#history)
- [ansible-dev-tools image](https://github.com/ansible/ansible-dev-tools/pkgs/container/community-ansible-dev-tools)

### vscode-ansible

Our [vscode-ansible](https://github.com/ansible/vscode-ansible/releases) extension needs to be released after ADT package is released because it uses both the python packages and the container image. Trying to release it with only the python packages being updated will result in testing with older versions when using the execution environment.

### Update DevSpaces image

Whenever the upstream `ansible-devspaces` container is released, the image SHA in the `devfile.yaml` of [ansible-devspaces-demo](https://github.com/redhat-developer-demos/ansible-devspaces-demo) repository must be updated. Verification needed whether the automated pull request for this update has been created correctly.

## Schedule

Releases should be made on the first Wednesday of the month, but can be made the following Wednesday if necessary. This document should be updated with a pull request after the releases are complete.

### 2025-05

Release manager: @shatakshiiii

Releases:

- ansible-compat - [v25.5.0](https://github.com/ansible/ansible-compat/releases/tag/v25.5.0)
- ansible-dev-environment - [v25.5.0](https://github.com/ansible/ansible-dev-environment/releases/tag/v25.5.0)
- ansible-lint - [v25.5.0](https://github.com/ansible/ansible-lint/releases/tag/v25.5.0)
- ansible-creator - [v25.5.0](https://github.com/ansible/ansible-creator/releases/tag/v25.5.0)
- molecule - [v25.5.0](https://github.com/ansible/molecule/releases/tag/v25.5.0)
- pytest-ansible - [v25.5.0](https://github.com/ansible/pytest-ansible/releases/tag/v25.5.0)
- ansible-navigator - [v25.5.0](https://github.com/ansible/ansible-navigator/releases/tag/v25.5.0)
- tox-ansible - [v25.5.0](https://github.com/ansible/tox-ansible/releases/tag/v25.5.0)
- ansible-dev-tools - [v25.5.2](https://github.com/ansible/ansible-dev-tools/releases/tag/v25.5.2)

### 2025-04

Release manager: @abhikdps

Releases:

- ansible-creator - [v25.4.1](https://github.com/ansible/ansible-creator/releases/tag/v25.4.1)
- ansible-dev-environment - [v25.4.0](https://github.com/ansible/ansible-dev-environment/releases/tag/v25.4.0)
- ansible-dev-tools - [v25.4.1](https://github.com/ansible/ansible-dev-tools/releases/tag/v25.4.1)
- ansible-lint - [v25.4.0](https://github.com/ansible/ansible-lint/releases/tag/v25.4.0)
- ansible-navigator - [v25.4.1](https://github.com/ansible/ansible-navigator/releases/tag/v25.4.1)
- molecule [v25.4.0](https://github.com/ansible/molecule/releases/tag/v25.4.0)
- pytest-ansible - [v25.4.1](https://github.com/ansible/pytest-ansible/releases/tag/v25.4.1)
- tox-ansible [v25.4.0](https://github.com/ansible/tox-ansible/releases/tag/v25.4.0)

### 2025-03

Release manager: @alisonlhart

Completed date:

Releases:

- ansible-creator [v25.3.1](https://github.com/ansible/ansible-creator/releases/tag/v25.3.1)

### 2025-01

Release manager: @audgirka

Completed date:

Releases:

- ansible-creator [v25.0.0](https://github.com/ansible/ansible-creator/releases/tag/v25.0.0)
- ansible-dev-environment [25.1.0](https://github.com/ansible/ansible-dev-environment/releases/tag/v25.1.0)
- ansible-dev-tools [v25.1.0](https://github.com/ansible/ansible-dev-tools/releases/tag/v25.1.0)
- ansible-lint [v25.1.0](https://github.com/ansible/ansible-lint/releases/tag/v25.1.0)
- ansible-navigator [v25.1.0](https://github.com/ansible/ansible-navigator/releases/tag/v25.1.0)
- molecule [25.1.0](https://github.com/ansible/molecule/releases/tag/v25.1.0)
- pytest-ansible [v25.1.0](https://github.com/ansible/pytest-ansible/releases/tag/v25.1.0)
- tox-ansible [v25.1.0](https://github.com/ansible/tox-ansible/releases/tag/v25.1.0)

### 2024-12

Release manager: @shatakshiiii

Completed date: 2024-12-17

Notes: All projects are released

### 2024-11

Release manager:

Completed date:

Notes:

### 2024-10

Release manager: @audgirka

Completed date:

Notes:

- ansible-compat [v24.10.0](https://github.com/ansible/ansible-compat/releases/tag/v24.10.0)
- ansible-lint [v24.10.0](https://github.com/ansible/ansible-lint/releases/tag/v24.10.0)
- tox-ansible [v24.10.0](https://github.com/ansible/tox-ansible/releases/tag/v24.10.0)
- ansible-navigator [v24.10.0](https://github.com/ansible/ansible-navigator/releases/tag/v24.10.0)
- ansible-creator [v24.11.0](https://github.com/ansible/ansible-creator/releases/tag/v24.11.0)
- ansible-dev-tools [v24.11.0](https://github.com/ansible/ansible-dev-tools/releases/tag/v24.11.0)

### 2024-09

Release manager: @shatakshiiii

Completed date: 2024-09-18

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

[#ansible-partners]: https://redhat.enterprise.slack.com/archives/CE3UL7F8V
[#ansible-galaxy-internal]: https://redhat.enterprise.slack.com/archives/CBPKRHHG9
[#wg-hub-delivery]: https://redhat.enterprise.slack.com/archives/C07BMJL2X42
[#ansible-devtools]: https://redhat.enterprise.slack.com/archives/C01NQV614EA
