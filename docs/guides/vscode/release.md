## Release cadence

A pre-release will be done every time we do a stable release.
This will ensure VSCode extension `auto-update` functionality doesn't break.
Refer vscode [docs](https://code.visualstudio.com/api/working-with-extensions/publishing-extension#prerelease-extensions) for pre-release and release versions.

## Release steps

These steps are currently manual but we should consider automating, at least some of them in the future.

Assuming that the next version is `0.8.1`:

1. `git checkout -b release/0.8.1`
1. Copy draft release notes from github
1. Edit `CHANGELOG.md` and insert copied text
1. `npm version 0.8.1 --no-git-tag-version --no-commit-hooks`
1. `git commit -a -m "Release 0.8.1"`. If done correctly you should see 3 files modified, the changelog and the two package files.
1. `tox -e lint`
1. `gh pr create --draft --label skip-changelog`
1. Open pull request on github wait for it to pass. Merge it.
1. Go github releases and release it! while being sure that you create a discussion thread for it. This will create a \*_tag_.
1. Go to https://studio-jenkins-csb-codeready.apps.ocp-c1.prod.psi.redhat.com/job/ansible/job/vscode-ansible/ and login using IPA/kerberos password (that is **not** the pin+otp one) and requires you to be on corporate VPN. In case you forgot it, you can reset it using https://identity.corp.redhat.com/resetipa
1. trigger the effective publishing. Remember to check both publishing options as they are disabled by default.
1. Use the `Approve` button to approve the effective publishing. This can be found either in the live console last line or on the graphical pipeline view as a dialog.

On average it takes 5-10 minutes for the uploaded new release to appear on marketplace but it takes up to 48h for users to receive it as vscode does not check for newer extensions even if you try to use the manual refresh button.

## Implementation details

The first part of our jenkins release pipeline is defined at https://gitlab.cee.redhat.com/codeready-studio/cci-config/-/blob/master/jobs/ansible/vscode-ansible.groovy and the rest inside ./Jenkinsfile
