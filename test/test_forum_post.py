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
    """Return a Post object."""
    # Bypass untestable category
    forum_post.Post._get_category_id = lambda x: "18"  # noqa: ARG005, SLF001
    return forum_post.Post(
        project="ansible/molecule",
        release="v25.3.1",
        forum_api_key="unused",
        forum_user="unused",
    )


def test_post_params(post_instance: forum_post.Post) -> None:
    """Test that release notes are generated correctly."""
    notes = """## Bugfixes\r
\r
- Fix molecule matrix with no scenario name. (#4400) @Qalthos\r
"""
    assert post_instance.project_short == "molecule"  # noqa: S101
    assert post_instance.release_notes == notes  # noqa: S101
    assert post_instance.created == "2025-02-19T12:53:51Z"  # noqa: S101


def test_prepare_post(post_instance: forum_post.Post) -> None:
    """Test output of forum post payload."""
    payload = post_instance._prepare_post()  # noqa: SLF001
    assert payload["title"] == "Release Announcement: molecule v25.3.1"  # noqa: S101
    assert payload["tags"] == ["devtools", "release-management"]  # noqa: S101
