import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_HELPER = Path(__file__).with_name("kconfig_helper.py")
# Zephyr keeps the environment Kconfig needs only in the menuconfig target's command.
_COMMAND_FILES = ("build.ninja", "CMakeFiles/menuconfig.dir/build.make")


class KconfigError(Exception):
    pass


@dataclass(frozen=True)
class KconfigSetup:
    environment: dict[str, str]
    kconfig_file: str


def _parse_command(line: str) -> KconfigSetup:
    tokens = shlex.split(line.replace("$$", "$"))
    start = next(i for i in range(1, len(tokens)) if tokens[i - 1 : i + 1] == ["-E", "env"])
    environment = {}
    for token in tokens[start + 1 :]:
        if "=" not in token:
            break
        key, _, value = token.partition("=")
        environment[key] = value
    script = next(i for i, token in enumerate(tokens) if token.endswith("menuconfig.py"))
    return KconfigSetup(environment, tokens[script + 1])


def setup(build_dir: Path) -> KconfigSetup | None:
    for name in _COMMAND_FILES:
        path = build_dir / name
        if path.is_file():
            for line in path.read_text(errors="replace").splitlines():
                if "menuconfig.py" in line and " -E env " in line:
                    return _parse_command(line)
    return None


def query_symbol(kconfig: KconfigSetup, name: str) -> dict | None:
    completed = subprocess.run(
        [sys.executable, str(_HELPER), kconfig.kconfig_file, name],
        env={**os.environ, **kconfig.environment},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        lines = completed.stderr.strip().splitlines()
        raise KconfigError(lines[-1] if lines else f"exit code {completed.returncode}")
    return json.loads(completed.stdout)
