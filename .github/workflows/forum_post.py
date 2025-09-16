# cspell:ignore devcontainer  # noqa: INP001
"""A forum poster."""

from __future__ import annotations

import argparse
import json
import urllib.request
from urllib.request import Request


POST_MD = """Hello everyone,

We are happy to announce the release of {project_short} {release}.

# How to get it

You can install the latest version of all the ansible developer tools by running the following command:

```bash
python3 -m pip install -U ansible-dev-tools
```

This will install the following developer tools:

- [ansible-builder](https://ansible.readthedocs.io/projects/builder/): a utility for building Ansible execution environments.
- [ansible-core](https://ansible.readthedocs.io/projects/ansible/): Ansible is a radically simple IT automation platform that makes your applications and systems easier to deploy and maintain. Automate everything from code deployment to network configuration to cloud management, in a language that approaches plain English, using SSH, with no agents to install on remote systems.
- [ansible-creator](https://ansible.readthedocs.io/projects/creator/): a utility for scaffolding Ansible project and content with recommended practices.
- [ansible-dev-environment](https://ansible.readthedocs.io/projects/dev-environment/): a utility for building and managing a virtual environment for Ansible content development.
- [ansible-lint](https://ansible.readthedocs.io/projects/lint/): a utility to identify and correct stylistic errors and anti-patterns in Ansible playbooks and roles.
- [ansible-navigator](https://ansible.readthedocs.io/projects/navigator/) a text-based user interface (TUI) for developing and troubleshooting Ansible content with execution environments.
- [ansible-sign](https://ansible.readthedocs.io/projects/sign/): a utility for signing and verifying Ansible content.
- [molecule](https://ansible.readthedocs.io/projects/molecule/): a functional test runner for Ansible collections, playbooks and roles
- [pytest-ansible](https://ansible.readthedocs.io/projects/pytest-ansible/): a pytest testing framework extension that provides additional functionality for testing Ansible module and plugin Python code.
- [tox-ansible](https://ansible.readthedocs.io/projects/tox-ansible/): an extension to the tox testing utility that provides additional functionality to check Ansible module and plugin Python code under different Python interpreters and Ansible core versions.

For a single tool, you can install it by running:

```bash
python3 -m pip -U install <project>==<release>
```

All ansible developer tools are also packaged in an image that you can use as a [VS Code development container](https://code.visualstudio.com/docs/devcontainers/containers). The image is updated shortly after releases of any individual tool.
The [community-dev-tools](https://github.com/ansible/ansible-dev-tools/pkgs/container/community-ansible-dev-tools) image is available on GitHub Container Registry.

```
podman run -it ghcr.io/ansible/community-ansible-dev-tools:latest
```

Sample `devcontainer.json` files are available in the [ansible-dev-tools](https://github.com/ansible/ansible-dev-tools/tree/main/.devcontainer) repository.

# Release notes for {project_short} {release}

{release_notes}

Release notes for all versions can be found in the [changelog](https://github.com/ansible/{project_short}/releases).

"""


class Post:
    """A class to post a release on the Ansible forum."""

    def __init__(
        self, project: str, release: str, forum_api_key: str, forum_user: str
    ) -> None:
        """Initialize the Post class.

        Args:
            project: The project name.
            release: The release version.
            forum_api_key: The forum API key.
            forum_user: The forum user.
        """
        self.category_id: int
        self.created: str
        self.forum_api_key = forum_api_key
        self.forum_user = forum_user
        self.project = project
        self.project_short = project.split("/")[-1]
        self.release = release
        self.release_notes: str

        # Populate release notes and forum category
        self._get_release_notes()
        self._get_category_id()

    def _get_release_notes(self) -> None:
        """Get the release notes for the project."""
        release_url = f"https://api.github.com/repos/{self.project}/releases/tags/{self.release}"
        with urllib.request.urlopen(release_url) as url:  # noqa: S310
            data = json.load(url)
        self.release_notes = data["body"]
        self.created = data["published_at"]

    def _get_category_id(self) -> None:
        """Get the category ID for the project."""
        categories_url = "https://forum.ansible.com/categories.json?include_subcategories=true"
        categories_request = Request(categories_url)  # noqa: S310
        categories_request.add_header("Api-Key", self.forum_api_key)
        categories_request.add_header("Api-Username", self.forum_user)
        with urllib.request.urlopen(url=categories_request) as url:  # noqa: S310
            data = json.load(url)
        category = next(
            c for c in data["category_list"]["categories"] if c["name"] == "News & Announcements"
        )
        self.category_id = next(
            c for c in category["subcategory_list"] if c["name"] == "Ecosystem Releases"
        )["id"]

    def _prepare_post(self) -> dict[str, str | list[str]]:
        post_md = POST_MD.format(
            project_short=self.project_short,
            release=self.release,
            release_notes=self.release_notes,
        )
        title = f"Release Announcement: {self.project_short} {self.release}"

        return {
            "title": title,
            "raw": post_md,
            "category": self.category_id,
            "created_at": self.created,
            "tags": ["devtools", "release-management"],
        }

    def post(self) -> None:
        """Post the release announcement to the forum."""
        url = "https://forum.ansible.com/posts.json"
        request = Request(url)  # noqa: S310
        request.method = "POST"
        request.add_header("Api-Key", self.forum_api_key)
        request.add_header("Api-Username", self.forum_user)
        request.add_header("Content-Type", "application/json")

        payload = self._prepare_post()
        data = json.dumps(payload).encode("utf-8")
        with urllib.request.urlopen(url=request, data=data):  # noqa: S310
            print(f"Posted {payload['title']} to the forum.")  # noqa: T201


def main() -> None:
    """Run the Post class."""
    parser = argparse.ArgumentParser(
        description="Post a release announcement to the Ansible forum.",
    )
    parser.add_argument("project", help="The project name. e.g. ansible/tox-ansible")
    parser.add_argument("release", help="The release version.")
    parser.add_argument("forum_api_key", help="The forum API key.")
    parser.add_argument("forum_user", help="The forum user.")
    args = parser.parse_args()
    post = Post(args.project, args.release, args.forum_api_key, args.forum_user)
    post.post()


if __name__ == "__main__":
    main()
