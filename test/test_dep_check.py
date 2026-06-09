"""Tests for the dep-check security script."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / ".github" / "scripts"
_spec = importlib.util.spec_from_file_location(
    "dep_check", SCRIPTS_DIR / "dep-check.py"
)
assert _spec
assert _spec.loader
dep_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dep_check)


# ─── Fixtures ──────────────────────────────────────────────────────────────


UV_LOCK_DIFF = """\
diff --git a/uv.lock b/uv.lock
index abc1234..def5678 100644
--- a/uv.lock
+++ b/uv.lock
@@ -10,7 +10,7 @@

 [[package]]
 name = "requests"
-version = "2.31.0"
+version = "2.32.0"
 source = { registry = "https://pypi.org/simple" }

 [[package]]
 name = "cryptography"
-version = "41.0.0"
+version = "42.0.0"
 source = { registry = "https://pypi.org/simple" }
"""

PNPM_LOCK_DIFF = """\
diff --git a/pnpm-lock.yaml b/pnpm-lock.yaml
index abc1234..def5678 100644
--- a/pnpm-lock.yaml
+++ b/pnpm-lock.yaml
@@ -50,7 +50,7 @@
    packages:
        lodash:
-            version: 4.17.20
+            version: 4.17.21
"""

PACKAGE_JSON_DIFF = """\
diff --git a/package.json b/package.json
index abc1234..def5678 100644
--- a/package.json
+++ b/package.json
@@ -5,7 +5,7 @@
   "dependencies": {
-    "express": "^4.18.1"
+    "express": "^4.19.0"
   }
"""

PYPROJECT_DIFF = """\
diff --git a/pyproject.toml b/pyproject.toml
index abc1234..def5678 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -10,7 +10,7 @@
 dependencies = [
-    "ansible-core>=2.15.0",
+    "ansible-core>=2.16.0",
 ]
"""

NO_DEP_DIFF = """\
diff --git a/src/main.py b/src/main.py
index abc1234..def5678 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,4 @@
+import os
 import sys
"""


# ─── Test is_dep_file ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "expected"),
    (
        ("uv.lock", True),
        ("pyproject.toml", True),
        ("package.json", True),
        ("pnpm-lock.yaml", True),
        ("requirements.txt", True),
        ("requirements-dev.txt", True),
        ("Pipfile.lock", True),
        ("src/main.py", False),
        ("README.md", False),
        (".github/workflows/ci.yml", False),
        ("sub/dir/pnpm-lock.yaml", True),
    ),
)
def test_is_dep_file(path: str, *, expected: bool) -> None:
    """Verify dependency file detection."""
    assert dep_check.is_dep_file(path) is expected


# ─── Test detect_dep_files_in_diff ─────────────────────────────────────────


def test_detect_dep_files_in_diff_uv_lock() -> None:
    """Detect uv.lock in a diff."""
    files = dep_check.detect_dep_files_in_diff(UV_LOCK_DIFF)
    assert "uv.lock" in files


def test_detect_dep_files_in_diff_no_deps() -> None:
    """Return empty list when no dep files are changed."""
    files = dep_check.detect_dep_files_in_diff(NO_DEP_DIFF)
    assert files == []


# ─── Test parsers ──────────────────────────────────────────────────────────


EXPECTED_UV_LOCK_CHANGES = 2


def test_parse_uv_lock_diff() -> None:
    """Parse version changes from uv.lock diff."""
    changes = dep_check.parse_uv_lock_diff(UV_LOCK_DIFF)
    assert len(changes) == EXPECTED_UV_LOCK_CHANGES
    names = {c["name"] for c in changes}
    assert "requests" in names
    assert "cryptography" in names
    req = next(c for c in changes if c["name"] == "requests")
    assert req["oldVersion"] == "2.31.0"
    assert req["newVersion"] == "2.32.0"
    assert req["ecosystem"] == "PyPI"


def test_parse_pnpm_lock_diff() -> None:
    """Parse version changes from pnpm-lock.yaml diff."""
    changes = dep_check.parse_pnpm_lock_diff(PNPM_LOCK_DIFF)
    assert len(changes) == 1
    assert changes[0]["name"] == "lodash"
    assert changes[0]["oldVersion"] == "4.17.20"
    assert changes[0]["newVersion"] == "4.17.21"
    assert changes[0]["ecosystem"] == "npm"


def test_parse_package_json_diff() -> None:
    """Parse version changes from package.json diff."""
    changes = dep_check.parse_package_json_diff(PACKAGE_JSON_DIFF)
    assert len(changes) == 1
    assert changes[0]["name"] == "express"
    assert changes[0]["oldVersion"] == "4.18.1"
    assert changes[0]["newVersion"] == "4.19.0"
    assert changes[0]["ecosystem"] == "npm"


def test_parse_pyproject_diff() -> None:
    """Parse version changes from pyproject.toml diff."""
    changes = dep_check.parse_pyproject_diff(PYPROJECT_DIFF)
    assert len(changes) == 1
    assert changes[0]["name"] == "ansible-core"
    assert changes[0]["oldVersion"] == "2.15.0"
    assert changes[0]["newVersion"] == "2.16.0"
    assert changes[0]["ecosystem"] == "PyPI"


# ─── Test parse_diff integration ──────────────────────────────────────────


def test_parse_diff_deduplicates() -> None:
    """Verify deduplication in parse_diff."""
    double_diff = UV_LOCK_DIFF + UV_LOCK_DIFF
    dep_files = dep_check.detect_dep_files_in_diff(double_diff)
    packages = dep_check.parse_diff(double_diff, dep_files)
    names = [p["name"] for p in packages]
    assert names.count("requests") == 1


# ─── Test OSV query ───────────────────────────────────────────────────────


def test_query_osv_handles_empty_list() -> None:
    """Empty package list should return empty results."""
    results = dep_check.query_osv([])
    assert results == {}


def test_query_osv_handles_network_error() -> None:
    """Network errors should be handled gracefully."""
    import urllib.error

    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        packages = [{"name": "foo", "newVersion": "1.0", "ecosystem": "PyPI"}]
        results = dep_check.query_osv(packages)
        assert results == {}


# ─── Test comment formatting ──────────────────────────────────────────────


def test_format_comment_clean() -> None:
    """Format comment with no vulnerabilities."""
    packages = [{"name": "requests", "newVersion": "2.32.0", "ecosystem": "PyPI"}]
    vulns: dict[str, list[dict[str, str]]] = {}
    comment = dep_check.format_comment(packages, vulns, ["uv.lock"])
    assert "PASS" in comment
    assert "requests" in comment
    assert "Clean" in comment
    assert dep_check.COMMENT_MARKER in comment


def test_format_comment_vulnerable() -> None:
    """Format comment with vulnerabilities."""
    packages = [{"name": "cryptography", "newVersion": "42.0.0", "ecosystem": "PyPI"}]
    vulns = {
        "cryptography:42.0.0:PyPI": [
            {"id": "GHSA-xxxx-yyyy-zzzz", "summary": "Test vuln"},
        ],
    }
    comment = dep_check.format_comment(packages, vulns, ["uv.lock"])
    assert "FAIL" in comment
    assert "**VULNERABLE**" in comment
    assert "GHSA-xxxx-yyyy-zzzz" in comment
    assert "https://github.com/advisories/GHSA-xxxx-yyyy-zzzz" in comment


def test_format_no_deps_comment() -> None:
    """Format comment when no deps changed."""
    comment = dep_check.format_no_deps_comment()
    assert "PASS" in comment
    assert "No dependency file changes" in comment
    assert dep_check.COMMENT_MARKER in comment


# ─── Test osv_url ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("advisory_id", "expected_prefix"),
    (
        ("GHSA-xxxx-yyyy-zzzz", "https://github.com/advisories/"),
        ("PYSEC-2024-001", "https://osv.dev/vulnerability/"),
        ("CVE-2024-12345", "https://osv.dev/vulnerability/"),
    ),
)
def test_osv_url(advisory_id: str, expected_prefix: str) -> None:
    """Verify advisory URL generation."""
    url = dep_check.osv_url(advisory_id)
    assert url.startswith(expected_prefix)
    assert advisory_id in url
