try:
    from ._version import __version__
except ImportError:  # pragma: no cover
    __version__ = "unknown"
from dataclasses import dataclass
from typing import Generator
import yaml


@dataclass
class Repo:
    name: str
    org: str = ""
    repo: str = ""

    def __post_init__(self):
        if "/" not in self.name:
            raise ValueError(f"Invalid repo name: {self.name}")
        self.org, self.repo = self.name.split("/", 1)

@dataclass
class Label:
    name: str
    color: str = ""
    description: str = ""


def get_repos() -> Generator[Repo]:
    data = yaml.safe_load(open("config/devtools.yml"))
    for repo in data["repos"]:
        if "/" in repo:
            yield Repo(name=repo)

def get_labels() -> Generator[Label]:
    data = yaml.safe_load(open("config/devtools.yml"))
    for k, v in data["labels"].items():
        yield Label(name=k, **v)
