from __future__ import annotations

import os
from urllib.parse import urlparse


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
