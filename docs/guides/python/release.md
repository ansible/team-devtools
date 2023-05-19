Thanks to the integrations which are in place, it is very easy to release a newer version of ansible-lint.

Anyone with appropriate permission to the `ansible-lint` project will be able to rollout a new release.

If we go to the Github releases section, we'll be able to see something like:

![Screenshot 2023-05-16 at 5 18 25 PM](https://github.com/ansible/devtools/assets/11896437/4052c662-3db3-4847-98f1-8187ae9ba10f)

This shows the latest available version for `ansible-lint`.
Also shows the upcoming version with changes to be included in the next release.

We use [release-drafter](https://github.com/release-drafter/release-drafter) which helps us to get the changelog for the releases.
When a PR is merged, release-drafter runs and adds PR details to the changelog as shown above.

# Releasing a new version
Go to Github releases and release it! while being sure that you create a discussion thread for it. This will create a *tag.
Once released, the latest version will be deployed and published to PyPI registry.

This release process is the same for all our python based projects.
