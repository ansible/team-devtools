# Github Actions

- workflow name should be **short** and **lowercase** and match the name of the workflow file
- do not use a workflow name like "ci" because all workflows are related to CI one way or another so they would not be informative

## Common workflow names

- `tox` : testing jobs that rely on tox, job names should match `tox -e xxx`
- `npm` : testing jobs that reply on npm, job name should match `npm run xxx`
- `ack` : shared workflow that is triggered on any pull-request review, like editing labels
- `push` : shared workflow that is triggered on a merge, usually updates release note drafts
- `release` : workflow that is triggered when a release is made

## Use a final `check` job to summarize results

All GHA pipelines should use a finalizing job named `check` that depends on the other ones. This allows us to make only this job as required in branch protection, thus lowering the manual maintenance of branch protection.

The current spinnet to use is documented below. It looks bit more complex because we use a special action developed by @webknjaz for checking the result of dependent jobs and avoiding a known bug with GHA that can cause skipped jobs to not set the build status to failed.

```yaml
jobs:
  ...
  check: # This job does nothing and is only used for the branch protection
    if: always()

    needs:
    - linters
    - unit

    runs-on: ubuntu-latest

    steps:
    - name: Decide whether the needed jobs succeeded or failed
      uses: re-actors/alls-green@release/v1
      with:
        jobs: ${{ toJSON(needs) }}
```
