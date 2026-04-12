from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

WEIGHT_ENV_NAMES = (
    ("LOCUST_WEIGHT_HEALTH_LIVE", "GET /v1/health/live"),
    ("LOCUST_WEIGHT_HEALTH_READY", "GET /v1/health/ready"),
    ("LOCUST_WEIGHT_METRICS", "GET /v1/monitoring/metrics"),
    ("LOCUST_WEIGHT_WORKSPACE_LIST_ORDERS", "GET /v1/workspace/orders"),
    ("LOCUST_WEIGHT_WORKSPACE_CREATE_CANCEL", "POST /v1/workspace/orders -> cancel"),
    (
        "LOCUST_WEIGHT_WORKSPACE_FULL_LIFECYCLE",
        "POST /v1/workspace/orders [lifecycle] -> entered -> steps -> pickup/signature",
    ),
)


def _read_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bool_label(value: str) -> str:
    return "yes" if value.lower() in {"1", "true", "yes", "on"} else "no"


def build_archive_markdown(report_basename: str) -> str:
    generated_at = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Load Baseline Archive",
        "",
        "## Run Context",
        f"- Generated At UTC: {generated_at}",
        f"- Base URL: {_read_env('LOAD_BASE_URL', 'http://localhost:8000')}",
        f"- Users: {_read_env('LOAD_USERS', '50')}",
        f"- Spawn Rate: {_read_env('LOAD_SPAWN_RATE', '10')}",
        f"- Duration: {_read_env('LOAD_DURATION', '10m')}",
        f"- Workspace Auth Required: {_bool_label(_read_env('LOAD_REQUIRE_WORKSPACE_AUTH', '0'))}",
        f"- Workspace Lifecycle Enabled: {_bool_label(_read_env('LOCUST_WORKSPACE_FULL_LIFECYCLE', '0'))}",
        "",
        "## Task Weights",
    ]
    for env_name, label in WEIGHT_ENV_NAMES:
        lines.append(f"- {label}: {_read_env(env_name, '0')}")

    lines.extend(
        [
            "",
            "## Artifacts",
            f"- {report_basename}_stats.csv",
            f"- {report_basename}_failures.csv",
            f"- {report_basename}_exceptions.csv",
            f"- {report_basename}.html",
            f"- {report_basename}.summary.md",
            "",
            "## Notes To Fill",
            "- Environment: ",
            "- Peak RPS: ",
            "- p95 Latency: ",
            "- Error Rate: ",
            "- Dominant Failure Mode: ",
            "- Follow-up Actions: ",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    report_basename = _read_env("LOAD_REPORT_BASENAME")
    if not report_basename:
        print("LOAD_REPORT_BASENAME must be set")
        return 1

    output_path = Path(f"{report_basename}.summary.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_archive_markdown(report_basename), encoding="utf-8")
    print(f"load baseline archive template written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
