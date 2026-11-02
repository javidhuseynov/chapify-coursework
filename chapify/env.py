"""Minimal .env loader (no third-party dependency).

Reads KEY=VALUE lines from a .env file in the project root and puts them into
os.environ unless the variable is already set in the real environment.
Blank lines and lines starting with '#' are ignored. Values may be wrapped in
single or double quotes.
"""

import os
from pathlib import Path


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]

        os.environ.setdefault(key, value)


def env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)

    if value is None:
        return default

    return value.strip().lower() in ("1", "true", "yes", "on")


def env_list(name: str, default: list[str]) -> list[str]:
    value = os.environ.get(name)

    if value is None:
        return default

    return [item.strip() for item in value.split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)

    if value is None or not value.strip():
        return default

    return int(value)
