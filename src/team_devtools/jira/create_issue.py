#!/usr/bin/env python3
#
# Simplified BSD License https://opensource.org/licenses/BSD-2-Clause)
#
"""Script to create Jira issues in the AAP project with dev-tools component."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import questionary

from .const import JD
from .ui import get_priority, select_epic
from .utils import error, info, warning


if TYPE_CHECKING:
    from collections.abc import Callable

    from jira import JIRA
    from jira.resources import Component, Issue


def load_config() -> dict[str, Any]:
    """Load Jira configuration."""
    # these env var names match the ones used by atlassian-mcp server
    result = {
        "jira_token": os.environ.get("JIRA_PERSONAL_TOKEN", ""),
        "jira_server": os.environ.get("JIRA_URL", ""),
    }
    if not result["jira_token"] or not result["jira_server"]:
        msg = "JIRA_PERSONAL_TOKEN and JIRA_URL must be set to use this tool."
        raise ValueError(msg)
    return result


def load_template(filename: str) -> str:
    """Load text from a template file."""
    script_dir = Path(__file__).parent

    # Try resources directory first
    template_path = script_dir / "resources" / filename
    if not template_path.exists():
        # Fall back to current directory
        template_path = Path(filename)

    try:
        return template_path.read_text().strip()
    except FileNotFoundError:
        warning(f"Template file '{filename}' not found. Using default value '.'")
        return "."


def get_component(jira_conn: JIRA, project: str, component_name: str) -> Component:
    """Get component object by name."""
    prj_components = jira_conn.project_components(project=project)
    for comp in prj_components:
        if comp.name == component_name:
            return comp  # type: ignore[no-any-return]
    msg = f"Component '{component_name}' not found in project {project}"
    raise ValueError(msg)


def select_from_list(
    prompt: str,
    options: list[str],
    default: str | None = None,
    validator: Callable[[str], str] | None = None,
) -> str:
    """Display numbered options and get user selection (0-based indexing)."""
    info(f"\n{prompt}")
    for i, option in enumerate(options):
        default_marker = " (default)" if default and option == default else ""
        info(f"  {i}. {option}{default_marker}")

    default_index = options.index(default) if default else None
    prompt_text = f"Select [0-{len(options) - 1}]"
    if default_index is not None:
        prompt_text += f" [default: {default_index}]"

    while True:
        user_input = input(f"{prompt_text}: ").strip()

        if not user_input and default:
            return default
        if validator:
            try:
                return validator(user_input)
            except argparse.ArgumentTypeError as e:
                error(f"Error: {e}")  # Exception details already included by exception()


def parse_index_or_name(value: str, options: list[str], field_name: str) -> str:
    """Convert index or name to option name."""
    if value.isdigit():
        index = int(value)
        if 0 <= index < len(options):
            return options[index]
        msg = f"{field_name} index must be 0-{len(options) - 1}"
        raise argparse.ArgumentTypeError(msg)
    if value in options:
        return value
    msg = f"Invalid {field_name}. Use 0-{len(options) - 1} or {', '.join(options)}"
    raise argparse.ArgumentTypeError(msg)


def parse_priority(value: str) -> str:
    """Convert priority index or name to priority name."""
    return parse_index_or_name(value, JD.PRIORITIES, "priority")


def parse_issue_type(value: str) -> str:
    """Convert issue type index or name to issue type name."""
    return parse_index_or_name(value, JD.ISSUE_TYPES, "issue type")


def parse_affects_version(value: str) -> str:
    """Convert affects version index or name to version string."""
    return parse_index_or_name(value, JD.AFFECTS_VERSIONS, "affects version")


def parse_component(value: str) -> str:
    """Convert component index or name to component name."""
    return parse_index_or_name(value, JD.COMPONENTS, "component")


def create_issue(
    jira_conn: JIRA,
    summary: str,
    priority: str = "Normal",
    issue_type: str = "Task",
    component: str | list[str] = "dev-tools",
    epic_link: str | None = None,
    affects_version: str | None = None,
    story_points: int | None = None,
    sprint: int | None = None,
    description_file: str = "description.txt",
    description: str | None = None,
    acceptance_criteria: str | None = None,
    acceptance_criteria_file: str = "acceptance_criteria.txt",
    assignee: str | None = None,
) -> Issue:
    """Create an issue in the AAP project.

    Args:
        jira_conn: JIRA connection object
        summary: Issue summary/title
        priority: Priority name (e.g., 'Critical', 'Major', 'Normal', 'Minor'), default: 'Normal'
        issue_type: Issue type (e.g., 'Task', 'Story', 'Spike', 'Bug', 'Epic'), default: 'Task'
        component: Component name (e.g., 'dev-tools', 'vscode-plugin'), default: 'dev-tools'
        epic_link: Epic link ID (e.g., 'AAP-123'), optional
        affects_version: Affects Version (for bugs), optional
        description_file: Path to description template file
        acceptance_criteria: Acceptance criteria text, optional
        acceptance_criteria_file: Path to acceptance criteria template file

    """
    # Validate: affects_version can only be used with Bug issue type
    if affects_version and issue_type != "Bug":
        msg = f"affects_version can only be specified for Bug issue types, not '{issue_type}'"
        raise ValueError(msg)

    # Load templates from files
    description = description or load_template(description_file)
    acceptance_criteria = acceptance_criteria or load_template(acceptance_criteria_file)

    # Get the component
    components = []
    try:
        for comp in [component] if isinstance(component, str) else component:
            component_obj = get_component(jira_conn, "AAP", comp)
            components.append({"name": component_obj.name})
    except ValueError as e:
        error(f"Error: {e}")
        sys.exit(1)

    issue_template = {
        "assignee": assignee,
        "project": "AAP",
        "summary": summary,
        "description": description,
        "issuetype": {"name": issue_type},
        "components": components,
        "priority": {"name": priority},
        JD.WORKSTREAM_FIELD: [{"value": JD.WORKSTREAM}],  # Workstream (array format)
        JD.ACCEPTANCE_CRITERIA_FIELD: acceptance_criteria,  # Acceptance Criteria
    }
    if story_points:
        issue_template[JD.STORY_POINTS_FIELD] = int(story_points)  # type: ignore[assignment]
    if sprint:
        issue_template[JD.SPRINT_FIELD] = sprint  # type: ignore[assignment]

    # Add Epic Link only if provided
    if epic_link:
        issue_template[JD.EPIC_LINK_FIELD] = epic_link

    # Add Affects Version only if provided (typically for bugs)
    if affects_version:
        issue_template["versions"] = [{"name": affects_version}]

    if sprint and not assignee:
        # Auto-assign issue to current user if added to a sprint
        issue_template["assignee"] = jira_conn.myself()["key"]

    try:
        issue = jira_conn.create_issue(fields=issue_template)
    except Exception as e:  # noqa: BLE001
        error(f"Error creating issue: {e}")
        sys.exit(1)
    else:
        username = jira_conn.myself()["key"]
        info(
            f"{username} successfully created issue {issue.key} > {jira_conn.server_url}/browse/{issue.key}"
        )
        return issue


def main() -> None:  # noqa: PLR0912, PLR0915
    """Main function to parse arguments and create Jira issues."""
    parser = argparse.ArgumentParser(
        description="Create AAP Jira issues with dev-tools component",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -s "Implement new feature" -p Major -e AAP-100
  %(prog)s -s "Fix bug" -p Critical -e AAP-100
  %(prog)s --interactive
  %(prog)s -s "Custom template" -d custom_desc.txt -a custom_ac.txt
  %(prog)s -b issues.csv

Batch CSV format (required: summary; optional: priority, issue_type, epic_link, affects_version,
description_file, acceptance_criteria_file):
  summary,priority,issue_type,epic_link,affects_version
  "Fix login bug",Critical,Bug,AAP-100,2.5
  "Add dark mode",Normal,Task,AAP-101,

Affects Version options (ONLY for bugs): 0=2.4, 1=2.5, 2=2.6, 3=aap-devel

Note: Description and Acceptance Criteria are loaded from template files.
      Default files: description.txt and acceptance_criteria.txt
      Override with -d/--description-file and -a/--acceptance-criteria-file
        """,
    )

    parser.add_argument("-s", "--summary", help="Issue summary/title")
    parser.add_argument(
        "-p",
        "--priority",
        type=parse_priority,
        default=None,
        help="Issue priority: 0=Critical, 1=Major, 2=Normal, 3=Minor (default: Normal)",
    )
    parser.add_argument(
        "-t",
        "--issue-type",
        type=parse_issue_type,
        help="Issue type: 0=Task, 1=Story, 2=Spike, 3=Bug, 4=Epic (default: Task)",
    )
    parser.add_argument(
        "-c",
        "--component",
        type=parse_component,
        help="Component: 0=dev-tools, 1=vscode-plugin (default: dev-tools)",
    )
    parser.add_argument("-e", "--epic-link", help="Epic Link (e.g., AAP-123) - optional")
    parser.add_argument(
        "-v",
        "--affects-version",
        type=parse_affects_version,
        help="Affects Version: 0=2.4, 1=2.5, 2=2.6, 3=aap-devel (ONLY for bugs) - optional",
    )
    parser.add_argument(
        "-d",
        "--description-file",
        default="description.txt",
        help="Path to description template file (default: description.txt)",
    )
    parser.add_argument(
        "-a",
        "--acceptance-criteria-file",
        default="acceptance_criteria.txt",
        help="Path to acceptance criteria template file (default: acceptance_criteria.txt)",
    )
    parser.add_argument(
        "-b", "--batch-file", help="CSV file with multiple issues to create (batch mode)"
    )
    parser.add_argument("-i", "--interactive", action="store_true", help="Run in interactive mode")

    args = parser.parse_args()

    # Import jira only when actually needed (lazy import for optional dependency)
    try:
        from jira import JIRA  # noqa: PLC0415
    except ImportError:
        error("The 'jira' package is required. Install with: uv sync")
        sys.exit(1)

    # Load configuration
    try:
        config = load_config()
        info("Connecting to Jira...")
        jira_conn = JIRA(token_auth=config["jira_token"], server=config["jira_server"])
        info("Connected to Jira")
    except ValueError as e:
        error(f"Error loading Jira configuration: {e}")
        sys.exit(1)

    create_data = {
        "summary": args.summary,
        "priority": args.priority or "Normal",
        "issue_type": args.issue_type or "Task",
        "component": args.component or "dev-tools",
        "epic_link": args.epic_link,
        "affects_version": args.affects_version,
    }

    """Get the list of epics."""

    # Interactive mode - always prompt unless explicitly provided via CLI
    if args.interactive or not args.summary:
        try:
            info("=== AAP Issue Creation (Interactive Mode) ===\n")
            summary = args.summary
            sprint: int | None = None

            while not summary:
                summary = questionary.text(
                    "Summary",
                    validate=lambda text: True if len(text) > 0 else "Cannot be empty",
                ).unsafe_ask()
                if summary is None:
                    sys.exit(1)

            story_points = None
            description = (
                questionary.text(
                    "Description",
                    default="",
                    multiline=True,
                )
                .unsafe_ask()
                .strip()
            )
            acceptance_criteria = (
                questionary.text(
                    "Acceptance Criteria",
                    default="",
                    multiline=True,
                )
                .unsafe_ask()
                .strip()
            )

            epic_link = args.epic_link or select_epic(jira_conn)
            # Only prompt for affects_version if issue type is Bug

            # Only prompt if not explicitly provided on command line
            priority = args.priority if args.priority is not None else get_priority()

            if args.issue_type is not None:
                issue_type = args.issue_type
            else:
                issue_type = questionary.select(
                    "Issue Type",
                    choices=JD.ISSUE_TYPES,
                    default="Task",
                    use_shortcuts=True,
                ).unsafe_ask()

            if args.component is not None:
                component = args.component
            else:
                component = questionary.checkbox(
                    "Component",
                    choices=JD.COMPONENTS,
                    default="dev-tools",
                ).unsafe_ask()

            if issue_type == "Bug":
                if args.affects_version is not None:
                    affects_version = args.affects_version
                else:
                    affects_version = select_from_list(
                        "Select Affects Version:",
                        JD.AFFECTS_VERSIONS,
                        default=None,
                        validator=parse_affects_version,
                    )
                    if not affects_version:  # User pressed Enter without selecting
                        affects_version = None
            else:
                if args.affects_version:
                    warning(
                        f"Warning: affects_version ignored (only valid for Bug issue type, not '{issue_type}')"
                    )
                affects_version = None

            if issue_type != "Epic":
                sprints = jira_conn.sprints(board_id=JD.SPRINT_BOARD_ID, state="active,future")
                info(f"Sprints: {sprints}")

                sprint_choices = [
                    questionary.Choice(
                        f"{sprint.name} ({sprint.state} {datetime.fromisoformat(sprint.startDate).strftime('%b %-d')} - {datetime.fromisoformat(sprint.endDate).strftime('%b %-d')})",
                        sprint.id,
                    )
                    for sprint in sprints
                ]
                sprint_choices.append(questionary.Choice("None", None))
                sprint = questionary.select("Sprint", choices=sprint_choices).unsafe_ask()

                story_points = questionary.select(
                    "Story Points", choices=JD.STORY_POINTS, default=None
                ).unsafe_ask()

            create_data = {
                "summary": summary,
                "priority": priority,
                "issue_type": issue_type,
                "component": component,
                "description": description,
                "acceptance_criteria": acceptance_criteria,
                "epic_link": epic_link,
                "affects_version": affects_version,
                "story_points": story_points,
                "sprint": sprint,
            }
            info(f"Creating issue with the following details\n {create_data}")

            confirm = questionary.confirm("Create this issue?", default=True).unsafe_ask()
            if not confirm:
                info(f"Cancelled. {confirm}")
                sys.exit(0)
        except KeyboardInterrupt:
            sys.exit(1)

    # Create the issue
    create_issue(
        jira_conn=jira_conn,
        description_file=args.description_file,
        acceptance_criteria_file=args.acceptance_criteria_file,
        **create_data,
    )


if __name__ == "__main__":
    main()
