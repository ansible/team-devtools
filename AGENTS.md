## Static checks

## Agents

- `.vscode/extensions.json` file must:
  - have `tombi-toml.tombi` entry inside `recommendations` list
- `panekj.even-betterer-toml` must not be listed inside `recommendations` list
- `.vscode/settings.json` file must:
  - contain `[toml]` entry with `"editor.defaultFormatter": "tombi-toml.tombi"` inside
- file `.taplo.toml` must be removed if present
- `.pre-commit-config.yaml` file must:
  - not not have a hook that uses `repo: https://github.com/pappasam/toml-sort`. If present the entire entry for this hook must be removed
  - have a hook that uses https://github.com/tombi-toml/tombi-pre-commit that looks like below:

````yaml
- repo: https://github.com/tombi-toml/tombi-pre-commit
  rev: v0.6.17
  hooks:
    - id: tombi-format
      alias: toml
    - id: tombi-lint
      alias: toml```
````

Inside the same file the the root level key `ci` must contain a key `skip` that
is a sequence that must contain `tombi-format` and `tombi-lint` entries at least.

Ensure that running `pre-commit run all` is passing. Keep in mind that this
might need to run more than once in case it does reformat some files.
