import sys
from pathlib import Path

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text()) if path.is_file() else {}


def write_toml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write then rename, so a crash never leaves a half-written file behind.
    partial = path.with_name(path.name + ".partial")
    partial.write_text(tomli_w.dumps(data))
    partial.replace(path)
