"""Tests for check-platform-constraints script."""

import json

# Import functions from the script
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))
from packaging.specifiers import SpecifierSet

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

    assert len(result) == EXPECTED_RULE_COUNT
    assert "ansible-core" in result
    assert "cffi" in result
    assert str(result["ansible-core"]) == "<2.17"
    assert str(result["cffi"]) == "<1.17"


def test_parse_constraints_file_nonexistent(tmp_path: Path) -> None:
    """Test parsing nonexistent file returns empty dict."""
    constraints_file = tmp_path / "nonexistent.txt"

    result = parse_constraints_file(constraints_file)

    assert result == {}


def test_check_dependency_compatibility_no_violations() -> None:
    """Test dependency that doesn't violate constraints."""
    constraints = {"ansible-core": SpecifierSet("<2.17")}
    dep = "ansible-core>=2.16.14"

    violations = check_dependency_compatibility(dep, constraints)

    assert violations == []


def test_check_dependency_compatibility_with_violation() -> None:
    """Test dependency that violates platform constraint."""
    constraints = {"ansible-core": SpecifierSet("<2.17")}
    dep = "ansible-core>=2.17.10"

    violations = check_dependency_compatibility(dep, constraints)

    assert len(violations) == 1
    assert "ansible-core>=2.17.10" in violations[0]
    assert "2.17.10" in violations[0]


def test_check_dependency_compatibility_unrelated_package() -> None:
    """Test dependency for package not in constraints."""
    constraints = {"ansible-core": SpecifierSet("<2.17")}
    dep = "pytest>=8.0.0"

    violations = check_dependency_compatibility(dep, constraints)

    assert violations == []


def test_check_dependency_compatibility_multiple_constraints() -> None:
    """Test with multiple platform constraints."""
    constraints = {
        "ansible-core": SpecifierSet("<2.17"),
        "cffi": SpecifierSet("<1.17"),
    }
    dep = "cffi>=1.15.1"

    violations = check_dependency_compatibility(dep, constraints)

    assert violations == []


def test_check_dependency_compatibility_edge_case_equal_version() -> None:
    """Test when minimum version equals platform maximum."""
    constraints = {"ansible-core": SpecifierSet("<2.17")}
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
        "ansible-core": SpecifierSet("<2.17"),
        "cffi": SpecifierSet("<1.17"),
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

    constraints = {"ansible-core": SpecifierSet("<2.17")}

    changed, _message = update_renovate_config(renovate_file, constraints)

    assert changed is True

    config = json.loads(renovate_file.read_text())
    assert len(config["packageRules"]) == 1
    assert config["packageRules"][0]["allowedVersions"] == "<2.17"


def test_update_renovate_config_nonexistent_file(tmp_path: Path) -> None:
    """Test handling of nonexistent renovate.json."""
    renovate_file = tmp_path / "renovate.json"
    constraints = {"ansible-core": SpecifierSet("<2.17")}

    changed, message = update_renovate_config(renovate_file, constraints)

    assert changed is False
    assert "not found" in message


def test_update_renovate_config_no_changes_needed(tmp_path: Path) -> None:
    """Test when renovate.json already has correct rules."""
    constraints = {"ansible-core": SpecifierSet("<2.17")}

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


def test_parse_constraints_file_with_malformed_lines(tmp_path: Path) -> None:
    """Test parsing constraints file with malformed lines."""
    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text(
        "# Valid constraint\n"
        "ansible-core<2.17\n"
        "not-a-valid-line\n"
        "also bad format!!!\n"
        "cffi<1.17\n"
    )

    result = parse_constraints_file(constraints_file)

    # Should only parse valid lines
    assert len(result) == EXPECTED_RULE_COUNT
    assert "ansible-core" in result
    assert "cffi" in result


def test_check_dependency_compatibility_malformed_dependency() -> None:
    """Test handling of malformed dependency string."""
    constraints = {"ansible-core": SpecifierSet("<2.17")}
    dep = "not a valid dependency string!!!"

    violations = check_dependency_compatibility(dep, constraints)

    # Should handle gracefully and return no violations
    assert violations == []


def test_check_dependency_compatibility_no_minimum_version() -> None:
    """Test dependency with no minimum version specifier."""
    constraints = {"ansible-core": SpecifierSet("<2.17")}
    dep = "ansible-core<2.18"  # Only upper bound, no minimum

    violations = check_dependency_compatibility(dep, constraints)

    # Should return no violations since there's no minimum to check
    assert violations == []


def test_check_dependency_compatibility_greater_than_operator() -> None:
    """Test dependency with > operator instead of >=."""
    constraints = {"ansible-core": SpecifierSet("<2.17")}
    dep = "ansible-core>2.17.0"

    violations = check_dependency_compatibility(dep, constraints)

    # Should detect violation with > operator
    assert len(violations) == 1


def test_check_dependency_compatibility_multiple_version_specs() -> None:
    """Test dependency with multiple version specifiers to check max version selection."""
    constraints = {"ansible-core": SpecifierSet("<2.17")}
    # Multiple >= specs - should pick the higher one
    dep = "ansible-core>=2.15.0,>=2.16.5"

    violations = check_dependency_compatibility(dep, constraints)

    # Should use 2.16.5 as minimum (higher version)
    assert violations == []

    # Now with a violation
    dep2 = "ansible-core>=2.16.0,>=2.17.5"
    violations2 = check_dependency_compatibility(dep2, constraints)
    assert len(violations2) == 1

    # Test where second version is lower (covers the branch where version <= min_version)
    dep3 = "ansible-core>=2.16.5,>=2.15.0"
    violations3 = check_dependency_compatibility(dep3, constraints)
    # Should still use 2.16.5 as the minimum (ignores lower version)
    assert violations3 == []


def test_main_no_constraints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test main function when no constraints are found."""
    # Create empty constraints file
    config_dir = tmp_path / ".config"
    config_dir.mkdir()
    constraints_file = config_dir / "platform-constraints.txt"
    constraints_file.write_text("")

    # Mock the root path
    import check_platform_constraints

    monkeypatch.setattr(
        check_platform_constraints, "__file__", str(tmp_path / "hooks" / "check_platform_constraints.py")
    )

    result = check_platform_constraints.main()

    assert result == 0


def test_main_with_violations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Test main function when violations are found."""
    # Setup files
    config_dir = tmp_path / ".config"
    config_dir.mkdir()
    constraints_file = config_dir / "platform-constraints.txt"
    constraints_file.write_text("ansible-core<2.17\n")

    pyproject_file = tmp_path / "pyproject.toml"
    pyproject_file.write_text(
        '[project]\n'
        'dependencies = ["ansible-core>=2.17.5"]\n'
    )

    renovate_file = tmp_path / "renovate.json"
    renovate_file.write_text('{"packageRules": []}\n')

    # Mock the root path
    import check_platform_constraints

    monkeypatch.setattr(
        check_platform_constraints, "__file__", str(tmp_path / "hooks" / "check_platform_constraints.py")
    )

    result = check_platform_constraints.main()

    assert result == 1
    captured = capsys.readouterr()
    assert "constraint violations" in captured.out.lower()


def test_main_no_violations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Test main function when no violations are found."""
    # Setup files
    config_dir = tmp_path / ".config"
    config_dir.mkdir()
    constraints_file = config_dir / "platform-constraints.txt"
    constraints_file.write_text("ansible-core<2.17\n")

    pyproject_file = tmp_path / "pyproject.toml"
    pyproject_file.write_text(
        '[project]\n'
        'dependencies = ["ansible-core>=2.16.0"]\n'
    )

    renovate_file = tmp_path / "renovate.json"
    renovate_file.write_text('{"packageRules": []}\n')

    # Mock the root path
    import check_platform_constraints

    monkeypatch.setattr(
        check_platform_constraints, "__file__", str(tmp_path / "hooks" / "check_platform_constraints.py")
    )

    result = check_platform_constraints.main()

    assert result == 0
    captured = capsys.readouterr()
    assert "compatible with platform constraints" in captured.out.lower()


def test_main_no_pyproject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test main function when pyproject.toml doesn't exist."""
    # Setup files
    config_dir = tmp_path / ".config"
    config_dir.mkdir()
    constraints_file = config_dir / "platform-constraints.txt"
    constraints_file.write_text("ansible-core<2.17\n")

    renovate_file = tmp_path / "renovate.json"
    renovate_file.write_text('{"packageRules": []}\n')

    # Mock the root path
    import check_platform_constraints

    monkeypatch.setattr(
        check_platform_constraints, "__file__", str(tmp_path / "hooks" / "check_platform_constraints.py")
    )

    result = check_platform_constraints.main()

    assert result == 0


def test_main_renovate_no_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Test main function when renovate.json already has correct rules."""
    # Setup files
    config_dir = tmp_path / ".config"
    config_dir.mkdir()
    constraints_file = config_dir / "platform-constraints.txt"
    constraints_file.write_text("ansible-core<2.17\n")

    pyproject_file = tmp_path / "pyproject.toml"
    pyproject_file.write_text(
        '[project]\n'
        'dependencies = ["ansible-core>=2.16.0"]\n'
    )

    renovate_file = tmp_path / "renovate.json"
    renovate_file.write_text(
        json.dumps({
            "packageRules": [
                {
                    "matchPackageNames": ["ansible-core"],
                    "allowedVersions": "<2.17",
                    "description": "Platform compatibility constraint from .config/platform-constraints.txt",
                },
            ],
        })
    )

    # Mock the root path
    import check_platform_constraints

    monkeypatch.setattr(
        check_platform_constraints, "__file__", str(tmp_path / "hooks" / "check_platform_constraints.py")
    )

    result = check_platform_constraints.main()

    assert result == 0
    captured = capsys.readouterr()
    assert "[i]" in captured.out
    assert "already up to date" in captured.out


def test_main_script_entry_point(tmp_path: Path) -> None:
    """Test the if __name__ == '__main__' entry point by running script directly."""
    # Setup files
    config_dir = tmp_path / ".config"
    config_dir.mkdir()
    constraints_file = config_dir / "platform-constraints.txt"
    constraints_file.write_text("ansible-core<2.17\n")

    renovate_file = tmp_path / "renovate.json"
    renovate_file.write_text('{"packageRules": []}\n')

    # Copy the script to temp directory
    import shutil
    src_script = Path(__file__).parent.parent / "hooks" / "check_platform_constraints.py"
    dest_script = tmp_path / "check_platform_constraints.py"
    shutil.copy(src_script, dest_script)

    # Run the script using subprocess
    import subprocess
    result = subprocess.run(
        [sys.executable, str(dest_script)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path)
    )

    assert result.returncode == 0
