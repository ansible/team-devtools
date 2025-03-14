"""Test module for the package."""

import logging
import os
from collections.abc import Generator
from subprocess import run

import pytest
from _pytest.mark.structures import ParameterSet

from team_devtools import Label, Repo, get_labels, get_repos


LOGGER = logging.getLogger(__name__)
CI = False
if "CI" in os.environ and os.environ["CI"] in ("true", "1"):
    CI = True


def each_repo_label() -> Generator[ParameterSet, None, None]:
    """Generate a parameter set for each repo and label.

    Yields:
        ParameterSet: A parameter set for each repo and label.
    """
    for repo in get_repos():
        for label in get_labels():
            yield pytest.param(repo, label, id=f"{repo.repo}:{label.name}")


@pytest.mark.parametrize(("repo", "label"), each_repo_label())
@pytest.mark.skipif(bool(os.environ.get("CI", "")), reason="Not running in CI yet.")
def test_label(repo: Repo, label: Label) -> None:
    """Reconfigure label inside a repo."""
    assert label.name
    assert label.color, f"Label {label.name} does not have a color"
    result = run(  # noqa: S602
        f"gh label create {label.name} --color {label.color.strip('#')} --force --repo {repo.name}",
        shell=True,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result
