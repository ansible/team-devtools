Ansible DevTools team is using [tox](https://tox.wiki/) as a generic test runner even on projects that are not python based. We do this because npm is quite limited and it lacks ability to document various commands and to expose them in a friendly way.

Tox uses the concept of default tests (implicit) and optional ones. If you call tox without any arguments it will run all default ones. Most times you just want to run a specific one using `tox -e <name>`.

To list current test environments and their descriptions, just run `tox -va`. The output will look similar to:

```text
$ tox -av
default environments:
lint           -> Run linting
packaging      -> Build package, verify metadata, install package.
test-ui        -> Run UI tests (extest, install test)
test-e2e       -> Run e2e tests (mocha)

additional environments:
test-ui-oldest -> Run UI tests (extest, install test) Run UI tests using oldest version of vscode we support
code           -> Build extension and installs it in your vscode instance (forced)
deps           -> Update dependencies
```

The following sections are more aimed towards documenting practices about maintaining tox files across our repositories and CI/CD integration.

## envlist should not contain specific python versions

Instead of listing all currently supported python versions inside `envlist`, we should only list the generic `py`. This should allow a developer to run all tests for his current version of python with just `tox`.

On the other hand we should never use just `tox` or `tox -e py` on CI/CD pipelines as this would introduce bugs sooner or later as we will discover that the python version used for testing changed.

```ini
envlist =
   lint
   py{310,39,38}  # <-- BAD, replace with just `py`
```

One extra advantage for this approach is that we no longer need to update config file when we drop or remove one python version from the supported matrix.

## envlist items should be sorted by duration

In order to fail-fast, we want to run quick tests first, like `lint`. The longest test suite should be the last.

## all envlist entries must have description

When you run `tox -av`, you will also see the description of each environment, which can be quite informative for a new contributor. Be sure that all of them have a description, one that is less than ~100 characters as wrapping them in terminal makes the whole list harder to read. If you want to add extra details, use comments inside the ini file.

## use short and consistent naming for env names

Tox env names should be short (easy to type) and consistent across projects, so they do not conflict with muscle-memory.

Tox env name should not be about the tool as that may change, it should be more about the nature/category/area of the testing.

Current list of popular names:

- `py` - unitests
- `lint` - linting, runts all linters (likely pre-commit)
- `docs` - anything related to building docs (aka Sphinx)
- `packaging` - tests related to python packaging
- `deps` - Bumping of test dependencies. This should not be included in default `envlist`, expected to be run only manually.

## Dependency pinning

We never pin dependencies directly in the package metadata because we do not want to prevent people from using it with other tools. The general rule is that we keep the dependencies as relaxed as possible but we do have to add ceiling from time to time. Still, even ceiling is discouraged and should be done only when we already have knowledge that the new releases are going to break us.

We cannot really rely on semantic versioning for ceiling as we already know that there are project that are breaking even on minor patches and other projects which release major version often but even so unlikely to break us at all. In the end the decision should be taken case by case.

In order to keep our local testing and CI/CD pipelines from randomly getting broken we would pin test dependencies using a single project wide constraints file names `requirements.txt`. Do not confuse this file with normal dependencies declared in project metadata (`setup.cfg`). The reason why we use this little bit misleading filename is because that is the only filename recognized by dependabot.

This file is updated by either manually running `tox -e deps` job or dependabot scheduled runs. That one creates pull-requests for updating each dependency, so we would know before we start using it, and avoid getting our CI/CD broken due to external causes.

In order to achieve this, we define `PIP_CONSTRAINTS=requirements.txt` inside `tox.ini` and also on https://readthedocs.org/ configuration. This is telling pip to always use versions mentioned there.

There are few particular tox environments where we neuter this option by using `PIP_CONSTRAINTS=/dev/null`:

- `deps` - as we want to allow pip-compile to be able to bump dependencies
- `lint` as pre-commit tool has it own pinning logic which is incompatible with use of pip constraints file
- `devel` ones, where we usually use some pre-released or unreleased versions of key dependencies or sister projects. Use of pinning would prevent us from doing this.
