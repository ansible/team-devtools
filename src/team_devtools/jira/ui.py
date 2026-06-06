"""UI for Jira."""

import questionary
from jira import JIRA
from questionary import Choice

from .const import JD


def select_epic(jira_conn: JIRA) -> str | None:
    """Get an epic from the list of epics.

    Returns:
        The epic link, or None if the user pressed Enter.
    """
    return questionary.select(  # type: ignore[no-any-return]
        "Epic",
        instruction="Epic Link (e.g., AAP-123) [optional, press Enter to skip]",
        default=None,
        use_shortcuts=True,
        choices=get_epics(jira_conn),
    ).ask()


def get_priority() -> str:
    """Get a priority from the list of priorities."""
    result = questionary.select(
        "Priority",
        default="Normal",
        use_shortcuts=True,
        choices=JD.PRIORITIES,
    ).ask()
    return result if result is not None else "Normal"


def get_epics(jira: JIRA) -> list[Choice]:
    """Get the list of epics."""
    result = []
    issues = jira.search_issues(
        jql_str=JD.JQL_MY_EPICS,
        fields="key,summary,issuetype,labels,parent,permalink",
    )
    for issue in issues:
        name = f"{issue.key} - {issue.fields.summary}"
        if hasattr(issue.fields, "parent") and issue.fields.parent:
            name += f" - {issue.fields.parent.key}"
        result.append(Choice(name, issue.key))  # issues.permalink()
    result.append(Choice("None", None))
    return result
