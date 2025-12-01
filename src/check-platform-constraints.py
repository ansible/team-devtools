#!/usr/bin/env python3
"""Validate and enforce platform constraints.

This script:
1. Reads platform constraints from .config/platform-constraints.txt
2. Validates dependencies in pyproject.toml against these constraints
3. Updates renovate.json with allowedVersions rules to prevent automated bumps
"""

import json
import re
import sys
from pathlib import Path

import tomllib


def parse_constraints_file(path: Path) -> dict[str, str]:
    """Parse platform constraints file.

    Returns dict like: {"ansible-core": "<2.17", "cffi": "<1.17"}
    """
    constraints: dict[str, str] = {}
    if not path.exists():
        return constraints

    for line in path.read_text().splitlines():
        line = line.strip()
        # Skip comments and empty lines
        if not line or line.startswith("#"):
            continue

        # Parse package constraint (e.g., "ansible-core<2.17")
        match = re.match(r"^([a-zA-Z0-9_-]+)([<>=!]+.*)$", line)
        if match:
            package, constraint = match.groups()
            constraints[package] = constraint

    return constraints


def check_dependency_compatibility(
    dep_str: str, constraints: dict[str, str]
) -> list[str]:
    """Check if a dependency violates platform constraints.

    Returns list of violation messages.
    """
    violations = []

    for package, platform_constraint in constraints.items():
        # Check if this dependency is for the constrained package
        if not dep_str.startswith(f"{package}>=") and not dep_str.startswith(
            f"{package}>"
        ):
            continue

        # Extract the minimum version requirement from dependency
        # Handle formats like: "package>=1.2.3" or "package>=1.2.3,<2.0"
        min_match = re.search(r">=([0-9.]+)", dep_str)
        if not min_match:
            continue

        min_version = min_match.group(1)

        # Extract the platform's maximum allowed version
        # e.g., "<2.17" means platform provides up to 2.16.x
        platform_match = re.search(r"<([0-9.]+)", platform_constraint)
        if not platform_match:
            continue

        platform_max = platform_match.group(1)

        # Check if minimum required version exceeds platform maximum
        # This is a simple string comparison which works for versions like "2.17" vs "2.16"
        # For more complex cases, you'd want packaging.version.Version
        if min_version >= platform_max:
            violations.append(
                f"❌ {dep_str}\n"
                f"   Platform maximum: {package}{platform_constraint}\n"
                f"   Your minimum ({min_version}) exceeds platform maximum ({platform_max})\n"
                f"   Lower the minimum version to be compatible"
            )

    return violations


def update_renovate_config(
    renovate_path: Path, constraints: dict[str, str]
) -> tuple[bool, str]:
    """Update renovate.json with packageRules for platform constraints.

    Returns (changed, message) tuple.
    """
    if not renovate_path.exists():
        return False, "renovate.json not found"

    with renovate_path.open(encoding="utf-8") as f:
        config = json.load(f)

    # Build packageRules for our constraints
    new_rules = []
    for package, constraint in constraints.items():
        new_rules.append({
            "matchPackageNames": [package],
            "allowedVersions": constraint,
            "description": "Platform compatibility constraint from .config/platform-constraints.txt",
        })

    # Get existing packageRules or create new
    existing_rules = config.get("packageRules", [])

    # Remove old auto-generated rules (those with our description)
    filtered_rules = [
        rule
        for rule in existing_rules
        if rule.get("description")
        != "Platform compatibility constraint from .config/platform-constraints.txt"
    ]

    # Add new rules
    config["packageRules"] = filtered_rules + new_rules

    # Check if anything changed
    if config.get("packageRules") == existing_rules:
        return False, "renovate.json already up to date"

    # Write back with pretty formatting
    with renovate_path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    return True, f"Updated renovate.json with {len(new_rules)} constraint rule(s)"


def main() -> int:
    """Main entry point."""
    root = Path(__file__).parent.parent
    constraints_file = root / ".config" / "platform-constraints.txt"
    pyproject_file = root / "pyproject.toml"
    renovate_file = root / "renovate.json"

    # Parse constraints
    constraints = parse_constraints_file(constraints_file)
    if not constraints:
        print(f"⚠️  No constraints found in {constraints_file}")  # noqa: T201
        return 0

    print(f"📋 Platform constraints loaded: {len(constraints)}")  # noqa: T201
    for package, constraint in constraints.items():
        print(f"   • {package}{constraint}")  # noqa: T201
    print()  # noqa: T201

    # Check pyproject.toml dependencies
    violations = []
    if pyproject_file.exists():
        with pyproject_file.open("rb") as f:
            pyproject = tomllib.load(f)

        dependencies = pyproject.get("project", {}).get("dependencies", [])

        for dep in dependencies:
            dep_violations = check_dependency_compatibility(dep, constraints)
            violations.extend(dep_violations)

    # Update renovate.json
    changed, message = update_renovate_config(renovate_file, constraints)
    if changed:
        print(f"✅ {message}")  # noqa: T201
    else:
        print(f"[i] {message}")  # noqa: T201
    print()  # noqa: T201

    # Report violations
    if violations:
        print("🚫 Platform constraint violations in pyproject.toml:")  # noqa: T201
        print()  # noqa: T201
        for violation in violations:
            print(violation)  # noqa: T201
        print()  # noqa: T201
        return 1

    print("✅ All dependencies compatible with platform constraints")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
