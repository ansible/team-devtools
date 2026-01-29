"""CSV batch issue creation for JIRA."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from team_devtools.jira.create_issue import (
    create_issue,
    parse_affects_version,
    parse_component,
    parse_issue_type,
    parse_priority,
)
from team_devtools.jira.utils import error, info, warning


if TYPE_CHECKING:
    from jira import JIRA


def create_issues_from_csv(jira_conn: JIRA, csv_file: str, config: dict[str, Any]) -> None:  # noqa: C901, PLR0912, PLR0915
    """Create multiple issues from a CSV file.

    CSV format:
        summary,priority,issue_type,component,epic_link,affects_version,description_file,acceptance_criteria_file

    Required columns: summary
    Optional columns: priority, issue_type, component, epic_link, affects_version, description_file, acceptance_criteria_file
    """
    try:
        csv_path = Path(csv_file)
        with csv_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)

            # Validate required columns
            if "summary" not in list(reader.fieldnames or []):
                error("Error: CSV must have a 'summary' column")
                sys.exit(1)

            issues_created = []
            issues_failed = []

            for row_num, row in enumerate(reader, start=2):  # start=2 because row 1 is header
                summary = row.get("summary", "").strip()
                if not summary:
                    info(f"Row {row_num}: Skipping - no summary")
                    continue

                # Parse and validate priority (use default if not provided or invalid)
                priority_str = row.get("priority", "").strip()
                if priority_str:
                    try:
                        priority = parse_priority(priority_str)
                    except argparse.ArgumentTypeError as e:
                        warning(
                            f"Row {row_num}: Invalid priority '{priority_str}', using default 'Normal'. Error: {e}",
                        )
                        priority = "Normal"
                else:
                    priority = "Normal"

                # Parse and validate issue type (use default if not provided or invalid)
                issue_type_str = row.get("issue_type", "").strip()
                if issue_type_str:
                    try:
                        issue_type = parse_issue_type(issue_type_str)
                    except argparse.ArgumentTypeError as e:
                        warning(
                            f"Row {row_num}: Invalid issue_type '{issue_type_str}', using default 'Task'. Error: {e}",
                        )
                        issue_type = "Task"
                else:
                    issue_type = "Task"

                # Parse and validate component (use default if not provided or invalid)
                component_str = row.get("component", "").strip()
                if component_str:
                    try:
                        component = parse_component(component_str)
                    except argparse.ArgumentTypeError as e:
                        warning(
                            f"Row {row_num}: Invalid component '{component_str}', using default 'dev-tools'. Error: {e}",
                        )
                        component = "dev-tools"
                else:
                    component = "dev-tools"

                # Optional fields
                epic_link = row.get("epic_link", "").strip() or None
                affects_version_str = row.get("affects_version", "").strip()

                # Validate affects_version
                affects_version = None
                if affects_version_str:
                    if issue_type != "Bug":
                        warning(
                            f"Row {row_num}: Warning - affects_version '{affects_version_str}' ignored (only valid for Bug issue type, not '{issue_type}')",
                        )
                    else:
                        try:
                            affects_version = parse_affects_version(affects_version_str)
                        except argparse.ArgumentTypeError as e:
                            warning(
                                f"Row {row_num}: Invalid affects_version '{affects_version_str}', skipping. Error: {e}",
                            )
                            affects_version = None

                description_file = row.get("description_file", "").strip() or "description.txt"
                acceptance_criteria_file = (
                    row.get("acceptance_criteria_file", "").strip() or "acceptance_criteria.txt"
                )

                info(f"Row {row_num}: Creating issue '{summary}'...")
                try:
                    issue = create_issue(
                        jira_conn=jira_conn,
                        summary=summary,
                        priority=priority,
                        issue_type=issue_type,
                        component=component,
                        epic_link=epic_link,
                        affects_version=affects_version,
                        description_file=description_file,
                        acceptance_criteria_file=acceptance_criteria_file,
                    )
                    issue_url = f"{config['jira_server']}/browse/{issue.key}"
                    issues_created.append((row_num, issue.key, summary, issue_url))
                except Exception as e:  # noqa: BLE001
                    error(f"Row {row_num}: Failed to create issue: {e}")
                    issues_failed.append((row_num, summary, str(e)))

            # Summary
            info(f"\n{'=' * 60}")
            info("Batch creation complete!")
            info(f"Created: {len(issues_created)} issues")
            if issues_failed:
                error(f"✗ Failed: {len(issues_failed)} issues")
            info(f"{'=' * 60}")

            if issues_created:
                info("\nSuccessfully created issues:")
                for row_num, key, summary, url in issues_created:
                    info(f"  Row {row_num}: {key} - {summary}")
                    info(f"             {url}")

            if issues_failed:
                info("\nFailed to create issues:")
                for row_num, summary, error_msg in issues_failed:
                    info(f"  Row {row_num}: {summary} - {error_msg}")

    except FileNotFoundError:
        msg = f"Error: CSV file '{csv_file}' not found"
        error(msg)
        sys.exit(1)
    except Exception:  # noqa: BLE001
        error(f"Error reading CSV file: {sys.exc_info()[1]}")
        sys.exit(1)
