#!/usr/bin/env python3
"""Validate and enforce platform constraints.

This script:
1. Defines platform constraints as constants
2. Validates dependencies in pyproject.toml against these constraints
3. Updates renovate.json with allowedVersions rules to prevent automated bumps
"""

import json
import sys
from pathlib import Path

import tomllib
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version


# Platform compatibility constraints for AAP and RHEL
# These represent the MAXIMUM versions we can use to remain compatible
# with downstream platform packages
PLATFORM_CONSTRAINTS = {
    "ansible-core": "<2.17",  # AAP 2.5/2.6 ships ansible-core 2.16.x
    "cffi": "<1.16",  # RHEL 8/9 ships cffi 1.15.x
    "django": "<4.3",  # at 4.2
    "importlib-metadata": "<6.1",  # at 6.0.1
    "jsonschema": "<4.22",  # at 4.21.1
    "packaging": "<25.0",  # galaxy-importer constraint
    "python-gnupg": "<0.5.3",  # at 0.5.2,
    "setuptools": "<65.6",  # RHEL 8/9 ships setuptools 65.5.1
}


def get_constraints() -> dict[str, SpecifierSet]:
    """Get platform constraints as SpecifierSet objects.

    Returns dict like: {"ansible-core": SpecifierSet("<2.17"), "cffi": SpecifierSet("<1.16")}
    """
    return {name: SpecifierSet(spec) for name, spec in PLATFORM_CONSTRAINTS.items()}


def check_dependency_compatibility(dep_str: str, constraints: dict[str, SpecifierSet]) -> list[str]:
    """Check if a dependency violates platform constraints.

    Returns list of violation messages.
    """
    violations = []

    try:
        req = Requirement(dep_str)
    except Exception:  # noqa: BLE001
        return violations

    # Check if this package has platform constraints
    if req.name not in constraints:
        return violations

    platform_specifier = constraints[req.name]

    # Find the minimum version required by the dependency
    min_version = None
    for spec in req.specifier:
        if spec.operator in (">=", ">"):
            version = Version(spec.version)
            if min_version is None or version > min_version:
                min_version = version

    if min_version is None:
        return violations

    # Check if minimum version satisfies platform constraints
    if min_version not in platform_specifier:
        violations.append(
            f"❌ {dep_str}\n"
            f"   Platform constraint: {req.name}{platform_specifier}\n"
            f"   Your minimum version ({min_version}) violates platform constraint\n"
            f"   Lower the minimum version to be compatible"
        )

    return violations


def update_renovate_config(
    renovate_path: Path, constraints: dict[str, SpecifierSet]
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
        new_rules.append(
            {
                "matchPackageNames": [package],
                "allowedVersions": str(constraint),
                "description": "Platform compatibility constraint from .config/platform-constraints.txt",
            }
        )

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
    # Get constraints from constants
    constraints = get_constraints()

    # Check the current working directory's pyproject.toml and renovate.json
    cwd = Path.cwd()
    pyproject_file = cwd / "pyproject.toml"
    renovate_file = cwd / "renovate.json"

    print(f"📋 Platform constraints loaded: {len(constraints)}")  # noqa: T201
    for package, constraint in constraints.items():
        print(f"   • {package}{constraint!s}")  # noqa: T201
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


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
