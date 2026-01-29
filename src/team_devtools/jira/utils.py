"""Utils for Jira."""

import questionary


def render_link(uri: str, label: str | None = None) -> str:
    """Return an ANSI escape sequence for a link (OSC 8)."""
    if label is None:
        label = uri
    parameters = ""

    # OSC 8 ; params ; URI ST <name> OSC 8 ;; ST
    escape_mask = "\033]8;{};{}\033\\{}\033]8;;\033\\"

    return escape_mask.format(parameters, uri, label)


def info(message: str) -> None:
    """Print information message."""
    questionary.print(message, style="fg:ansibrightblue")


def error(message: str) -> None:
    """Print error message."""
    questionary.print(message, style="fg:ansibrightred")


def warning(message: str) -> None:
    """Print warning message."""
    questionary.print(message, style="fg:ansibrightyellow")
