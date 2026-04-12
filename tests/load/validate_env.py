from __future__ import annotations

import os
from urllib.parse import urlparse

WEIGHT_ENV_NAMES = (
    "LOCUST_WEIGHT_HEALTH_LIVE",
    "LOCUST_WEIGHT_HEALTH_READY",
    "LOCUST_WEIGHT_METRICS",
    "LOCUST_WEIGHT_WORKSPACE_LIST_ORDERS",
    "LOCUST_WEIGHT_WORKSPACE_CREATE_CANCEL",
    "LOCUST_WEIGHT_WORKSPACE_FULL_LIFECYCLE",
)


def _validate_non_negative_int(name: str, errors: list[str]) -> None:
    raw_value = os.getenv(name)
    if raw_value is None:
        return
    if not raw_value.strip():
        errors.append(f"{name} must not be empty")
        return
    if not raw_value.strip().isdigit():
        errors.append(f"{name} must be a non-negative integer")


def _is_valid_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate() -> tuple[bool, list[str]]:
    errors: list[str] = []

    base_url = os.getenv("LOAD_BASE_URL", "http://localhost:8000")
    if not _is_valid_http_url(base_url):
        errors.append("LOAD_BASE_URL must be an absolute http(s) URL")

    users = os.getenv("LOAD_USERS", "50")
    if not users.isdigit() or int(users) <= 0:
        errors.append("LOAD_USERS must be a positive integer")

    spawn_rate = os.getenv("LOAD_SPAWN_RATE", "10")
    try:
        if float(spawn_rate) <= 0:
            errors.append("LOAD_SPAWN_RATE must be > 0")
    except ValueError:
        errors.append("LOAD_SPAWN_RATE must be numeric")

    duration = os.getenv("LOAD_DURATION", "2m")
    if not duration:
        errors.append("LOAD_DURATION must not be empty")

    report_basename = os.getenv("LOAD_REPORT_BASENAME", "").strip()
    if "LOAD_REPORT_BASENAME" in os.environ and not report_basename:
        errors.append("LOAD_REPORT_BASENAME must not be empty when set")

    for env_name in WEIGHT_ENV_NAMES:
        _validate_non_negative_int(env_name, errors)

    require_workspace_auth = os.getenv("LOAD_REQUIRE_WORKSPACE_AUTH", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if require_workspace_auth:
        if not os.getenv("LOCUST_WORKSPACE_EMAIL", "").strip():
            errors.append(
                "LOCUST_WORKSPACE_EMAIL is required for authenticated workspace baselines"
            )
        if not os.getenv("LOCUST_WORKSPACE_PASSWORD", "").strip():
            errors.append(
                "LOCUST_WORKSPACE_PASSWORD is required for authenticated workspace baselines"
            )

    return len(errors) == 0, errors


def main() -> int:
    ok, errors = validate()
    if ok:
        print("load environment validation passed")
        return 0

    for err in errors:
        print(f"validation error: {err}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
