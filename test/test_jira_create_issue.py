"""Tests for create_issue script."""

import argparse
from pathlib import Path

import pytest

from team_devtools.jira.create_issue import (
    AFFECTS_VERSIONS,
    COMPONENTS,
    ISSUE_TYPES,
    PRIORITIES,
    load_template,
    parse_affects_version,
    parse_component,
    parse_index_or_name,
    parse_issue_type,
    parse_priority,
)


class TestParsePriority:
    """Test priority parsing and validation."""

    def test_parse_priority_by_index(self) -> None:
        """Test parsing priority by numeric index."""
        assert parse_priority("0") == "Critical"
        assert parse_priority("1") == "Major"
        assert parse_priority("2") == "Normal"
        assert parse_priority("3") == "Minor"

    def test_parse_priority_by_name(self) -> None:
        """Test parsing priority by name."""
        assert parse_priority("Critical") == "Critical"
        assert parse_priority("Major") == "Major"
        assert parse_priority("Normal") == "Normal"
        assert parse_priority("Minor") == "Minor"

    def test_parse_priority_invalid_index(self) -> None:
        """Test parsing priority with invalid index."""
        with pytest.raises(argparse.ArgumentTypeError, match="priority index must be 0-3"):
            parse_priority("4")
        # Negative numbers fail isdigit() and fall through to name validation
        with pytest.raises(argparse.ArgumentTypeError, match="Invalid priority"):
            parse_priority("-1")

    def test_parse_priority_invalid_name(self) -> None:
        """Test parsing priority with invalid name."""
        with pytest.raises(
            argparse.ArgumentTypeError,
            match=r"Invalid priority.*Critical, Major, Normal, Minor",
        ):
            parse_priority("InvalidPriority")


class TestParseIssueType:
    """Test issue type parsing and validation."""

    def test_parse_issue_type_by_index(self) -> None:
        """Test parsing issue type by numeric index."""
        assert parse_issue_type("0") == "Task"
        assert parse_issue_type("1") == "Story"
        assert parse_issue_type("2") == "Spike"
        assert parse_issue_type("3") == "Bug"
        assert parse_issue_type("4") == "Epic"

    def test_parse_issue_type_by_name(self) -> None:
        """Test parsing issue type by name."""
        assert parse_issue_type("Task") == "Task"
        assert parse_issue_type("Story") == "Story"
        assert parse_issue_type("Spike") == "Spike"
        assert parse_issue_type("Bug") == "Bug"
        assert parse_issue_type("Epic") == "Epic"

    def test_parse_issue_type_invalid_index(self) -> None:
        """Test parsing issue type with invalid index."""
        with pytest.raises(argparse.ArgumentTypeError, match="issue type index must be 0-4"):
            parse_issue_type("5")
        # Negative numbers fail isdigit() and fall through to name validation
        with pytest.raises(argparse.ArgumentTypeError, match="Invalid issue type"):
            parse_issue_type("-1")

    def test_parse_issue_type_invalid_name(self) -> None:
        """Test parsing issue type with invalid name."""
        with pytest.raises(
            argparse.ArgumentTypeError,
            match=r"Invalid issue type.*Task, Story, Spike, Bug, Epic",
        ):
            parse_issue_type("InvalidType")


class TestParseAffectsVersion:
    """Test affects version parsing and validation."""

    def test_parse_affects_version_by_index(self) -> None:
        """Test parsing affects version by numeric index."""
        assert parse_affects_version("0") == "2.4"
        assert parse_affects_version("1") == "2.5"
        assert parse_affects_version("2") == "2.6"
        assert parse_affects_version("3") == "aap-devel"

    def test_parse_affects_version_by_name(self) -> None:
        """Test parsing affects version by name."""
        assert parse_affects_version("2.4") == "2.4"
        assert parse_affects_version("2.5") == "2.5"
        assert parse_affects_version("2.6") == "2.6"
        assert parse_affects_version("aap-devel") == "aap-devel"

    def test_parse_affects_version_invalid_index(self) -> None:
        """Test parsing affects version with invalid index."""
        with pytest.raises(
            argparse.ArgumentTypeError,
            match="affects version index must be 0-3",
        ):
            parse_affects_version("4")

    def test_parse_affects_version_invalid_name(self) -> None:
        """Test parsing affects version with invalid name."""
        with pytest.raises(
            argparse.ArgumentTypeError,
            match=r"Invalid affects version.*2\.4, 2\.5, 2\.6, aap-devel",
        ):
            parse_affects_version("2.7")


class TestParseComponent:
    """Test component parsing and validation."""

    def test_parse_component_by_index(self) -> None:
        """Test parsing component by numeric index."""
        assert parse_component("0") == "dev-tools"
        assert parse_component("1") == "vscode-plugin"

    def test_parse_component_by_name(self) -> None:
        """Test parsing component by name."""
        assert parse_component("dev-tools") == "dev-tools"
        assert parse_component("vscode-plugin") == "vscode-plugin"

    def test_parse_component_invalid_index(self) -> None:
        """Test parsing component with invalid index."""
        with pytest.raises(argparse.ArgumentTypeError, match="component index must be 0-1"):
            parse_component("2")
        # Negative numbers fail isdigit() and fall through to name validation
        with pytest.raises(argparse.ArgumentTypeError, match="Invalid component"):
            parse_component("-1")

    def test_parse_component_invalid_name(self) -> None:
        """Test parsing component with invalid name."""
        with pytest.raises(
            argparse.ArgumentTypeError,
            match=r"Invalid component.*dev-tools, vscode-plugin",
        ):
            parse_component("invalid-component")


class TestParseIndexOrName:
    """Test generic index or name parsing."""

    def test_parse_index_or_name_by_index(self) -> None:
        """Test parsing by numeric index."""
        options = ["Option1", "Option2", "Option3"]
        assert parse_index_or_name("0", options, "test") == "Option1"
        assert parse_index_or_name("1", options, "test") == "Option2"
        assert parse_index_or_name("2", options, "test") == "Option3"

    def test_parse_index_or_name_by_name(self) -> None:
        """Test parsing by name."""
        options = ["Option1", "Option2", "Option3"]
        assert parse_index_or_name("Option1", options, "test") == "Option1"
        assert parse_index_or_name("Option2", options, "test") == "Option2"
        assert parse_index_or_name("Option3", options, "test") == "Option3"

    def test_parse_index_or_name_invalid_index(self) -> None:
        """Test parsing with invalid index."""
        options = ["Option1", "Option2"]
        with pytest.raises(argparse.ArgumentTypeError, match="test index must be 0-1"):
            parse_index_or_name("2", options, "test")
        # Negative numbers fail isdigit() and fall through to name validation
        with pytest.raises(argparse.ArgumentTypeError, match="Invalid test"):
            parse_index_or_name("-1", options, "test")

    def test_parse_index_or_name_invalid_name(self) -> None:
        """Test parsing with invalid name."""
        options = ["Option1", "Option2"]
        with pytest.raises(argparse.ArgumentTypeError, match="Invalid test"):
            parse_index_or_name("InvalidOption", options, "test")


class TestLoadTemplate:
    """Test template loading functionality."""

    def test_load_template_from_resources(self, tmp_path: Path) -> None:
        """Test loading template from resources directory."""
        # Create a mock script location with resources directory
        jira_dir = tmp_path / "jira"
        resources_dir = jira_dir / "resources"
        resources_dir.mkdir(parents=True)

        template_file = resources_dir / "test_template.txt"
        template_content = "Test template content"
        template_file.write_text(template_content)

        # Mock __file__ to point to our temp directory
        import team_devtools.jira.create_issue as module

        original_file = module.__file__
        try:
            module.__file__ = str(jira_dir / "create_issue.py")
            result = load_template("test_template.txt")
            assert result == template_content
        finally:
            module.__file__ = original_file

    def test_load_template_file_not_found(self, tmp_path: Path) -> None:
        """Test loading template when file doesn't exist."""
        # Mock __file__ to point to our temp directory
        import team_devtools.jira.create_issue as module

        original_file = module.__file__
        try:
            module.__file__ = str(tmp_path / "create_issue.py")
            result = load_template("nonexistent.txt")
            assert result == "."  # Default value
        finally:
            module.__file__ = original_file

    def test_load_template_strips_whitespace(self, tmp_path: Path) -> None:
        """Test that template loading strips whitespace."""
        jira_dir = tmp_path / "jira"
        resources_dir = jira_dir / "resources"
        resources_dir.mkdir(parents=True)

        template_file = resources_dir / "test_template.txt"
        template_file.write_text("  \n  Test content  \n\n  ")

        import team_devtools.jira.create_issue as module

        original_file = module.__file__
        try:
            module.__file__ = str(jira_dir / "create_issue.py")
            result = load_template("test_template.txt")
            assert result == "Test content"
        finally:
            module.__file__ = original_file


class TestConstants:
    """Test that constants are properly defined."""

    def test_priorities_constant(self) -> None:
        """Test PRIORITIES constant."""
        expected_priorities = ["Critical", "Major", "Normal", "Minor"]
        assert expected_priorities == PRIORITIES
        assert len(PRIORITIES) == len(expected_priorities)

    def test_issue_types_constant(self) -> None:
        """Test ISSUE_TYPES constant."""
        expected_issue_types = ["Task", "Story", "Spike", "Bug", "Epic"]
        assert expected_issue_types == ISSUE_TYPES
        assert len(ISSUE_TYPES) == len(expected_issue_types)

    def test_affects_versions_constant(self) -> None:
        """Test AFFECTS_VERSIONS constant."""
        expected_versions = ["2.4", "2.5", "2.6", "aap-devel"]
        assert expected_versions == AFFECTS_VERSIONS
        assert len(AFFECTS_VERSIONS) == len(expected_versions)

    def test_components_constant(self) -> None:
        """Test COMPONENTS constant."""
        expected_components = ["dev-tools", "vscode-plugin"]
        assert expected_components == COMPONENTS
        assert len(COMPONENTS) == len(expected_components)
