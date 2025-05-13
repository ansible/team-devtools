"""Test module for the package."""
from subprocess import run
import pytest
from team_devtools import get_repos, Repo, Label, get_labels
import logging

LOGGER = logging.getLogger(__name__)

def each_repo_label():
    for repo in get_repos():
        for label in get_labels():
            yield pytest.param(repo, label, id=f"{repo.repo}:{label.name}")

@pytest.mark.parametrize("repo,label", each_repo_label())
def test_label(repo: Repo, label: Label):
    result = run(f"gh label create {label.name} --color {label.color.strip('#')} --force --repo {repo.name}", shell=True, check=False, capture_output=True, text=True)
    assert result.returncode == 0, result
