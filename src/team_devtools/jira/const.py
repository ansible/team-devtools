"""Constants for Jira."""

from typing import ClassVar


class JD:
    """Jira Data Class."""

    ACCEPTANCE_CRITERIA_FIELD: ClassVar[str] = "customfield_12315940"
    AFFECTS_VERSIONS: ClassVar[list[str]] = ["2.4", "2.5", "2.6", "aap-devel"]
    COMPONENTS: ClassVar[list[str]] = ["dev-tools", "vscode-plugin"]
    EPIC_LINK_FIELD: ClassVar[str] = "customfield_12311140"
    ISSUE_TYPES: ClassVar[list[str]] = ["Task", "Story", "Spike", "Bug", "Epic"]
    JQL_MY_EPICS: ClassVar[str] = (
        "issueType = Epic AND (assignee = currentUser() OR SME in (currentUser()) OR Contributors in (currentUser())) AND resolution is EMPTY order by Sprint"
    )
    PRIORITIES: ClassVar[list[str]] = ["Critical", "Major", "Normal", "Minor"]
    SPRINT_BOARD_ID: ClassVar[int] = 18011
    SPRINT_FIELD: ClassVar[str] = "customfield_12310940"
    STORY_POINTS: ClassVar[list[str]] = ["1", "2", "3", "5", "8", "13", "21"]
    STORY_POINTS_FIELD: ClassVar[str] = "customfield_12310243"
    WORKSTREAM: ClassVar[str] = "Dev Tools"
    WORKSTREAM_FIELD: ClassVar[str] = "customfield_12319275"
