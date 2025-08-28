# Managing Python dependencies

To upgrade all dependencies from the uv.lock file, run the command below:

```shell
uv sync --upgrade
```

### Exporting dependencies

To obtain a classic pip `requirements.txt` file with runtime (non testing)
dependencies, you can run:

```shell
uv export --all-extras --no-dev --no-default-groups
```
