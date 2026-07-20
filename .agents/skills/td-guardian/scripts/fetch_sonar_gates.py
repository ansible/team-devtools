#!/usr/bin/env python3
"""
Fetch SonarCloud quality gate status and metrics across Ansible Devtools projects.

Reports quality gate pass/fail, coverage, bugs, vulnerabilities, code smells,
duplication, and security hotspots for each project.

Usage:
    python3 scripts/fetch_sonar_gates.py --sonar-config config/sonar.json
    python3 scripts/fetch_sonar_gates.py --project-key ansible_ansible-lint
    SONAR_TOKEN=xxx python3 scripts/fetch_sonar_gates.py --sonar-config config/sonar.json
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone


METRICS = [
    "coverage",
    "bugs",
    "vulnerabilities",
    "code_smells",
    "duplicated_lines_density",
    "security_hotspots",
    "ncloc",
    "reliability_rating",
    "security_rating",
    "sqale_rating",
]

RATING_MAP = {"1.0": "A", "2.0": "B", "3.0": "C", "4.0": "D", "5.0": "E"}


def sonar_api(base_url, endpoint, token=None):
    """Call SonarCloud API and return parsed JSON. Returns None on failure."""
    url = f"{base_url}{endpoint}"
    print(f"  sonar api {endpoint[:80]}...", file=sys.stderr)

    req = urllib.request.Request(url)
    if token:
        import base64
        credentials = base64.b64encode(f"{token}:".encode()).decode()
        req.add_header("Authorization", f"Basic {credentials}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        print(f"  WARN: {endpoint} -> HTTP {e.code}: {body}", file=sys.stderr)
        return None
    except urllib.error.URLError as e:
        print(f"  WARN: {endpoint} -> network error: {e.reason}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  WARN: {endpoint} -> {type(e).__name__}: {e}", file=sys.stderr)
        return None


def fetch_quality_gate(base_url, project_key, token=None):
    """Fetch quality gate status for a project."""
    data = sonar_api(
        base_url,
        f"/api/qualitygates/project_status?projectKey={project_key}",
        token,
    )
    if not data or "projectStatus" not in data:
        return None

    status = data["projectStatus"]
    conditions = []
    for cond in status.get("conditions", []):
        conditions.append({
            "metric": cond.get("metricKey", ""),
            "status": cond.get("status", ""),
            "value": cond.get("actualValue", ""),
            "threshold": cond.get("errorThreshold", ""),
            "comparator": cond.get("comparator", ""),
        })

    return {
        "status": status.get("status", "UNKNOWN"),
        "conditions": conditions,
    }


def fetch_metrics(base_url, project_key, token=None):
    """Fetch project metrics from SonarCloud."""
    metric_keys = ",".join(METRICS)
    data = sonar_api(
        base_url,
        f"/api/measures/component?component={project_key}&metricKeys={metric_keys}",
        token,
    )
    if not data or "component" not in data:
        return {}

    metrics = {}
    for measure in data["component"].get("measures", []):
        key = measure.get("metric", "")
        value = measure.get("value", "")

        if key in ("reliability_rating", "security_rating", "sqale_rating"):
            metrics[key] = RATING_MAP.get(value, value)
        elif key in ("coverage", "duplicated_lines_density"):
            try:
                metrics[key] = round(float(value), 1)
            except (ValueError, TypeError):
                metrics[key] = value
        elif key in ("bugs", "vulnerabilities", "code_smells", "security_hotspots", "ncloc"):
            try:
                metrics[key] = int(float(value))
            except (ValueError, TypeError):
                metrics[key] = value
        else:
            metrics[key] = value

    return metrics


def fetch_project(base_url, project_key, owner, repo, token=None):
    """Fetch full quality data for a single project."""
    print(f"\nFetching SonarCloud for {owner}/{repo} ({project_key})...", file=sys.stderr)

    gate = fetch_quality_gate(base_url, project_key, token)
    metrics = fetch_metrics(base_url, project_key, token)

    if gate is None and not metrics:
        return {
            "owner": owner,
            "repo": repo,
            "project_key": project_key,
            "error": "Failed to fetch from SonarCloud — check project key, network, or token",
            "gate_status": "UNKNOWN",
            "conditions": [],
            "metrics": {},
        }

    failing_conditions = []
    if gate:
        failing_conditions = [c for c in gate.get("conditions", []) if c["status"] == "ERROR"]

    return {
        "owner": owner,
        "repo": repo,
        "project_key": project_key,
        "error": None,
        "gate_status": gate["status"] if gate else "UNKNOWN",
        "conditions": gate.get("conditions", []) if gate else [],
        "failing_conditions": failing_conditions,
        "metrics": metrics,
    }


def load_sonar_config(path):
    """Load SonarCloud config from file."""
    with open(path) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Fetch SonarCloud quality gate status")
    parser.add_argument("--sonar-config", help="Path to sonar.json config file")
    parser.add_argument("--project-key", help="Single SonarCloud project key")
    parser.add_argument("--owner", help="GitHub org (for single project mode)")
    parser.add_argument("--repo", help="Repo name (for single project mode)")
    parser.add_argument("--base-url", default="https://sonarcloud.io",
                        help="SonarCloud base URL (default: https://sonarcloud.io)")
    args = parser.parse_args()

    token = os.environ.get("SONAR_TOKEN")
    now = datetime.now(timezone.utc)

    if args.sonar_config:
        config = load_sonar_config(args.sonar_config)
        base_url = config.get("base_url", args.base_url)
        results = []
        for project in config["projects"]:
            result = fetch_project(
                base_url,
                project["key"],
                project["owner"],
                project["repo"],
                token,
            )
            result["fetched_at"] = now.isoformat()
            results.append(result)

        gate_ok = sum(1 for r in results if r["gate_status"] == "OK")
        gate_error = sum(1 for r in results if r["gate_status"] == "ERROR")
        gate_warn = sum(1 for r in results if r["gate_status"] == "WARN")
        gate_unknown = sum(1 for r in results if r["gate_status"] == "UNKNOWN")

        output = {
            "mode": "batch",
            "organization": config.get("organization", ""),
            "total_projects": len(config["projects"]),
            "fetched_at": now.isoformat(),
            "results": results,
            "aggregate": {
                "gate_ok": gate_ok,
                "gate_error": gate_error,
                "gate_warn": gate_warn,
                "gate_unknown": gate_unknown,
                "total_bugs": sum(r["metrics"].get("bugs", 0) for r in results if not r["error"]),
                "total_vulnerabilities": sum(
                    r["metrics"].get("vulnerabilities", 0) for r in results if not r["error"]
                ),
                "total_code_smells": sum(
                    r["metrics"].get("code_smells", 0) for r in results if not r["error"]
                ),
                "total_security_hotspots": sum(
                    r["metrics"].get("security_hotspots", 0) for r in results if not r["error"]
                ),
                "projects_with_errors": sum(1 for r in results if r["error"]),
            },
        }
    elif args.project_key:
        owner = args.owner or "unknown"
        repo = args.repo or args.project_key.split("_", 1)[-1] if "_" in args.project_key else args.project_key
        result = fetch_project(args.base_url, args.project_key, owner, repo, token)
        result["fetched_at"] = now.isoformat()
        output = result
    else:
        parser.error("Provide --sonar-config or --project-key")
        return

    json.dump(output, sys.stdout, indent=2)
    print(file=sys.stdout)


if __name__ == "__main__":
    main()
