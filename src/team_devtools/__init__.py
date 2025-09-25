"""Team DevTools package."""

try:
    from ._version import __version__
except ImportError:  # pragma: no cover
    __version__ = "unknown"
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Repo:
    """Repository class."""

    name: str
    org: str = ""
    repo: str = ""

    def __post_init__(self) -> None:
        """Post init.

        Raises:
            ValueError: If the repo name is invalid.
        """
        if "/" not in self.name:
            msg = f"Invalid repo name: {self.name}"
            raise ValueError(msg)
        self.org, self.repo = self.name.split("/", 1)


@dataclass
class Label:
    """Label class."""

    name: str
    color: str = ""
    description: str = ""


def get_repos() -> Generator[Repo]:
    """Get all repos.

    Yields:
        Repo: A repository.
    """
    with Path("config/devtools.yml").open(encoding="utf-8") as file:
        data = yaml.safe_load(file)
        for repo in data["repos"]:
            if "/" in repo:
                yield Repo(name=repo)


def get_labels() -> Generator[Label]:
    """Get all labels.

    Yields:
        Label: A label.
    """
    with Path("config/devtools.yml").open(encoding="utf-8") as file:
        data = yaml.safe_load(file)
        for k, v in data["labels"].items():
            yield Label(name=k, **v)
