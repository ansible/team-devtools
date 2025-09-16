"""Module for testing forum_post.py."""

from __future__ import annotations

import importlib.util
import sys

import pytest


spec = importlib.util.spec_from_file_location("forum_post", ".github/workflows/forum_post.py")
forum_post = importlib.util.module_from_spec(spec)
sys.modules["forum_post"] = forum_post
spec.loader.exec_module(forum_post)


@pytest.fixture
def post_instance() -> forum_post.Post:
    """A Post instance for testing."""
    return forum_post.Post(
        project="ansible/molecule",
        release="v25.3.1",
        forum_api_key="unused",
        forum_user="unused",
    )


def test_post_params(post_instance: forum_post.Post) -> None:
    """Test that derived parameters are generated correctly."""
    assert post_instance.project_short == "molecule"


def test_get_release_notes(post_instance: forum_post.Post) -> None:
    """Test that release notes are generated correctly."""
    release_notes, created = post_instance._get_release_notes()  # noqa: SLF001

    assert (
        release_notes
        == """## Bugfixes\r
\r
- Fix molecule matrix with no scenario name. (#4400) @Qalthos\r
"""
    )
    assert created == "2025-02-19T12:53:51Z"


def test_prepare_post(post_instance: forum_post.Post) -> None:
    """Test that discourse post payload is generated correctly."""
    # Set some arbitrary values to missing parameters
    post_instance.category_id = "10"
    post_instance.created = "A date"
    post_instance.release_notes = "Release notes go here"

    payload = post_instance._prepare_post()  # noqa: SLF001
    assert payload["title"] == "Release Announcement: molecule v25.3.1"
    assert payload["tags"] == ["devtools", "release-management"]
