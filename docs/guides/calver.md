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
