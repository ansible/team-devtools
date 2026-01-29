"""Test module for the package."""


def test_placeholder() -> None:
    """Placeholder test."""
    from team_devtools import __version__  # type: ignore[attr-defined]

    assert __version__
