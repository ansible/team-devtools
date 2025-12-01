"""Tests for check-platform-constraints script."""

import json

# Import functions from the script
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from check_platform_constraints import (
    check_dependency_compatibility,
    parse_constraints_file,
    update_renovate_config,
)


# Constants
EXPECTED_RULE_COUNT = 2


def test_parse_constraints_file_empty(tmp_path: Path) -> None:
    """Test parsing empty constraints file."""
    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text("")

    result = parse_constraints_file(constraints_file)

    assert result == {}


def test_parse_constraints_file_with_comments(tmp_path: Path) -> None:
    """Test parsing constraints file with comments."""
    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text(
        "# This is a comment\nansible-core<2.17\n# Another comment\ncffi<1.17\n"
    )

    result = parse_constraints_file(constraints_file)

    assert result == {
        "ansible-core": "<2.17",
        "cffi": "<1.17",
    }


def test_parse_constraints_file_nonexistent(tmp_path: Path) -> None:
    """Test parsing nonexistent file returns empty dict."""
    constraints_file = tmp_path / "nonexistent.txt"

    result = parse_constraints_file(constraints_file)

    assert result == {}


def test_check_dependency_compatibility_no_violations() -> None:
    """Test dependency that doesn't violate constraints."""
    constraints = {"ansible-core": "<2.17"}
    dep = "ansible-core>=2.16.14"

    violations = check_dependency_compatibility(dep, constraints)

    assert violations == []


def test_check_dependency_compatibility_with_violation() -> None:
    """Test dependency that violates platform constraint."""
    constraints = {"ansible-core": "<2.17"}
    dep = "ansible-core>=2.17.10"

    violations = check_dependency_compatibility(dep, constraints)

    assert len(violations) == 1
    assert "ansible-core>=2.17.10" in violations[0]
    assert "2.17.10" in violations[0]
    assert "2.17" in violations[0]


def test_check_dependency_compatibility_unrelated_package() -> None:
    """Test dependency for package not in constraints."""
    constraints = {"ansible-core": "<2.17"}
    dep = "pytest>=8.0.0"

    violations = check_dependency_compatibility(dep, constraints)

    assert violations == []


def test_check_dependency_compatibility_multiple_constraints() -> None:
    """Test with multiple platform constraints."""
    constraints = {
        "ansible-core": "<2.17",
        "cffi": "<1.17",
    }
    dep = "cffi>=1.15.1"

    violations = check_dependency_compatibility(dep, constraints)

    assert violations == []


def test_check_dependency_compatibility_edge_case_equal_version() -> None:
    """Test when minimum version equals platform maximum."""
    constraints = {"ansible-core": "<2.17"}
    dep = "ansible-core>=2.17.0"

    violations = check_dependency_compatibility(dep, constraints)

    assert len(violations) == 1


def test_update_renovate_config_new_rules(tmp_path: Path) -> None:
    """Test adding new rules to renovate.json."""
    renovate_file = tmp_path / "renovate.json"
    renovate_file.write_text(
        json.dumps(
            {
                "$schema": "https://docs.renovatebot.com/renovate-schema.json",
                "extends": ["config:base"],
            },
            indent=2,
        )
    )

    constraints = {
        "ansible-core": "<2.17",
        "cffi": "<1.17",
    }

    changed, message = update_renovate_config(renovate_file, constraints)

    assert changed is True
    assert "2 constraint rule(s)" in message

    # Verify the file was updated
    config = json.loads(renovate_file.read_text())
    assert "packageRules" in config
    assert len(config["packageRules"]) == EXPECTED_RULE_COUNT
    assert config["packageRules"][0]["matchPackageNames"] == ["ansible-core"]
    assert config["packageRules"][0]["allowedVersions"] == "<2.17"


def test_update_renovate_config_preserves_existing_rules(tmp_path: Path) -> None:
    """Test that existing non-platform rules are preserved."""
    renovate_file = tmp_path / "renovate.json"
    renovate_file.write_text(
        json.dumps(
            {
                "$schema": "https://docs.renovatebot.com/renovate-schema.json",
                "packageRules": [
                    {
                        "matchPackageNames": ["pytest"],
                        "allowedVersions": "<9.0",
                        "description": "Some other rule",
                    },
                ],
            },
            indent=2,
        )
    )

    constraints = {"ansible-core": "<2.17"}

    changed, _message = update_renovate_config(renovate_file, constraints)

    assert changed is True

    config = json.loads(renovate_file.read_text())
    assert len(config["packageRules"]) == EXPECTED_RULE_COUNT
    # Original rule preserved
    assert config["packageRules"][0]["matchPackageNames"] == ["pytest"]
    # New rule added
    assert config["packageRules"][1]["matchPackageNames"] == ["ansible-core"]


def test_update_renovate_config_replaces_old_platform_rules(tmp_path: Path) -> None:
    """Test that old platform constraint rules are replaced."""
    renovate_file = tmp_path / "renovate.json"
    renovate_file.write_text(
        json.dumps(
            {
                "$schema": "https://docs.renovatebot.com/renovate-schema.json",
                "packageRules": [
                    {
                        "matchPackageNames": ["ansible-core"],
                        "allowedVersions": "<2.16",
                        "description": "Platform compatibility constraint from .config/platform-constraints.txt",
                    },
                ],
            },
            indent=2,
        )
    )

    constraints = {"ansible-core": "<2.17"}

    changed, _message = update_renovate_config(renovate_file, constraints)

    assert changed is True

    config = json.loads(renovate_file.read_text())
    assert len(config["packageRules"]) == 1
    assert config["packageRules"][0]["allowedVersions"] == "<2.17"


def test_update_renovate_config_nonexistent_file(tmp_path: Path) -> None:
    """Test handling of nonexistent renovate.json."""
    renovate_file = tmp_path / "renovate.json"
    constraints = {"ansible-core": "<2.17"}

    changed, message = update_renovate_config(renovate_file, constraints)

    assert changed is False
    assert "not found" in message


def test_update_renovate_config_no_changes_needed(tmp_path: Path) -> None:
    """Test when renovate.json already has correct rules."""
    constraints = {"ansible-core": "<2.17"}

    renovate_file = tmp_path / "renovate.json"
    renovate_file.write_text(
        json.dumps(
            {
                "$schema": "https://docs.renovatebot.com/renovate-schema.json",
                "packageRules": [
                    {
                        "matchPackageNames": ["ansible-core"],
                        "allowedVersions": "<2.17",
                        "description": "Platform compatibility constraint from .config/platform-constraints.txt",
                    },
                ],
            },
            indent=2,
        )
    )

    changed, message = update_renovate_config(renovate_file, constraints)

    assert changed is False
    assert "already up to date" in message
