from __future__ import annotations

from pathlib import Path
import os


def load_dotenv_file(path: Path, *, override: bool = False) -> dict[str, str]:
    if not path.exists():
        return {}

    loaded_values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed_key = key.strip()
        parsed_value = _strip_quotes(value.strip())
        if override or parsed_key not in os.environ:
            os.environ[parsed_key] = parsed_value
        loaded_values[parsed_key] = parsed_value
    return loaded_values


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
