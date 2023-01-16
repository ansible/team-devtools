This document is work-in-progress. For the moment it contains only generic guidelines, most of them already used by our projects.

* Ensure we use `src/` layout so we do not accidentally import the module without installation
* Use PEP-517 and seek removal `setup.py`, test if via `tox -e pkg` command.
* Use PEP-621 and seek removal of `setup.cfg` and `pyprojects.toml` files.
* Make docs and test dependencies extras
* Have a single `requirements.txt` that is a lock file produced by pip-compile (pip-tools)
* Enable dependabot to update the `requirements.txt` lock file, optionally focus on a subset of dependencies and limit the maximum number of open pull-requests
* Create tox `deps` job that is updating all dependencies using pip-compile.


# tox -e pkg

Use the template below when implementing the packaging. You will need to update the last two commands that are used to verify that what was installed is functional.

```ini
[testenv:pkg]
description =
  Build package, verify metadata, install package
deps =
  build >= 0.7.0
  twine
skip_install = true
commands =
  # ensure dist/ folder is empty
  {envpython} -c 'import os.path, shutil, sys; \
  dist_dir = os.path.join("{toxinidir}", "dist"); \
  os.path.isdir(dist_dir) or sys.exit(0); \
  print("Removing \{!s\} contents...".format(dist_dir), file=sys.stderr); \
  shutil.rmtree(dist_dir)'

  # build wheel and sdist using PEP-517 (note that args
  {envpython} -m build \
    --outdir {toxinidir}/dist/ \
    {toxinidir}

  # Validate metadata using twine
  twine check --strict {toxinidir}/dist/*

  # Install the wheel
  sh -c "python3 -m pip install {toxinidir}/dist/*.whl"

  # Basic sanity check
  ansible-navigator --version

  # Uninstall package
  pip uninstall -y ansible-navigator
```
