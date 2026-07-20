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

Stage 1, release below if needed (no devtools runtime deps):

- [ansible-compat](https://github.com/ansible/ansible-compat/releases)
- [ansible-creator](https://github.com/ansible/ansible-creator/releases)
- [ansible-dev-environment](https://github.com/ansible/ansible-dev-environment/releases)

Stage 2, release below if needed (depend on Stage 1):

- [ansible-lint](https://github.com/ansible/ansible-lint/releases) (depends on ansible-compat)
- [molecule](https://github.com/ansible/molecule/releases) (depends on ansible-compat)
- [pytest-ansible](https://github.com/ansible/pytest-ansible/releases) (depends on ansible-compat)

Stage 3, release below if needed (depend on Stage 2):

- [ansible-navigator](https://github.com/ansible/ansible-navigator/releases) (depends on ansible-lint)
- [tox-ansible](https://github.com/ansible/tox-ansible/releases) (depends on pytest-ansible)

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

Preferred release days are Monday, Tuesday, or Wednesday. No releases on Friday.

[#ansible-partners]: https://redhat.enterprise.slack.com/archives/CE3UL7F8V
[#ansible-galaxy-internal]: https://redhat.enterprise.slack.com/archives/CBPKRHHG9
[#wg-hub-delivery]: https://redhat.enterprise.slack.com/archives/C07BMJL2X42
[#ansible-devtools]: https://redhat.enterprise.slack.com/archives/C01NQV614EA
