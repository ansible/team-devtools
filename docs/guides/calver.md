# CalVer Releases

Devtools projects are released with [CalVer](https://calver.org/) scheme version numbers.
The particular scheme we are using is `YY.MM.MICRO`, meaning that a release in
March 2025 will be named `25.3.0`, and if a patch (ie, non-feature) release is
required for that release, it will be named `25.3.1`, even if it is released in
April. The month will not increment until a new version with features or other
significant changes is released.

Because of the date-based approach, feature releases of this sort happen on a
regular cadence which depends on the project but is between every month and
every three months.

As this is currently a new scheme, care should be taken to ensure that releases
increment the month and year properly. No release should increment the most
significant section unless it takes place on a different year than the previous
release, and a release that happens more than one month after the previous release
should take care to increment the second most significant section of the version
appropriately.

Because this scheme eschews semantic meaning to the version numbers, extra care
should be taken at release time that the changelog is complete and appropriately
categorized.

- Deprecation notices should be added to the changelog as soon as they are
  agreed upon. The deprecation cycle cannot start before the deprecation has
  been announced.
- Changes should be properly categorized so that users can see at a glance what
  kind of changes are to be expected. Breaking changes should be clearly called
  out and announced well in advance to limit surprise, as version bounding is no
  longer possible.

# Devtools Projects Transitioning to CalVer Releases

Projects in the devtools space will be switching to [CalVer](https://calver.org/)
releases over the next few weeks. This is a surprising change, so let's get into
what that means.

## What

These are the projects that will be transitioning to CalVer:

- ansible-compat
- ansible-creator
- ansible-dev-environment
- ansible-lint
- ansible-navigator
- creator-ee
- molecule
- pytest-ansible
- tox-ansible
- vscode-ansible

We will use a `YY.MM.MICRO` version format. Thus, a release for March 2025 will be
named `25.3.0`, and if a patch (ie, non-feature) release is required for that release,
it will be named `25.3.1`, even if it is released in April, and the month will not
increment until a new version with features or other significant changes is released.

## Why

This is a bit of a change so let's go over what we hope to accomplish with it.

- Predictable, transparent release cadence

  With this, we are committing to time-based releases for all projects.
  While the exact frequency will vary between projects, each will have a release
  between one and three months after the last feature release.

- Version number indicates the age of a release

  With CalVer, the age of a release can be trivially determined from the version
  number, instead of having to look up the release notes as at present.

- Easier to translate versions between tools

  Many of our tools are interrelated. A consistent version scheme allows one to
  have a good idea of how related but independent tools are expected to work together.

## How

Following this announcement, the next feature release in each project will
be a CalVer release.

Feature releases will not happen more often than once a month, though
patch releases may happen more often as needed. We will also make
releases at least once every three months for each project.

Releases will still split out changes by category, including new features,
bugfixes, documentation updates, announced deprecations, and removed features.

One of the things we are bringing with this change is an emphasis on fewer
breaking changes / more emphasis on deprecation cycles and overlapping features.
When something is deprecated, it will be called out in the release notes, along
with replacement and how long the feature will remain in place.

## What's Next

As mentioned, this change will begin rolling out over the next few weeks. However,
if you have any comments or concerns, please let us know.
