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
    post = forum_post.Post(
        project="ansible/molecule",
        release="v25.3.1",
        forum_api_key="unused",
        forum_user="unused",
    )
    # prefill values that need network access.
    post.category_id = "18"
    post.created = "2025-02-19T12:53:51Z"
    post.release_notes = (
        "## Bugfixes\r\n\r\n- Fix molecule matrix with no scenario name. (#4400) @Qalthos\r\n"
    )
    return post


def test_prepare_post(post_instance: forum_post.Post) -> None:
    """Test that discourse post payload is generated correctly."""
    payload = post_instance._prepare_post()  # noqa: SLF001
    release_notes = forum_post.POST_MD.format(
        project_short="molecule",
        release=post_instance.release,
        release_notes=post_instance.release_notes,
    )
    assert payload == {
        "title": "Release Announcement: molecule v25.3.1",
        "raw": release_notes,
        "category": post_instance.category_id,
        "created_at": post_instance.created,
        "tags": ["devtools", "release-management", "molecule"],
    }
