import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from west.configuration import ConfigFile, Configuration
from west.manifest import ImportFlag, Manifest
from west.util import WestNotFound, west_topdir


@dataclass(frozen=True)
class ManifestInfo:
    path: Path
    repository: Path
    projects: dict[str, Path] | None
    load_error: str | None


def find_topdir(start: Path) -> Path | None:
    try:
        return Path(west_topdir(start, fall_back=False))
    except WestNotFound:
        return None


def read_manifest(topdir: Path) -> ManifestInfo:
    config = Configuration(topdir)
    repository = topdir / config.get("manifest.path", "")
    path = repository / config.get("manifest.file", "west.yml")
    try:
        # IGNORE_PROJECTS keeps to the projects this manifest declares and never runs git.
        manifest = Manifest.from_topdir(
            topdir, config=config, import_flags=ImportFlag.IGNORE_PROJECTS
        )
    except Exception as error:
        return ManifestInfo(path, repository, None, str(error))
    projects = {project.name: Path(project.abspath) for project in manifest.projects[1:]}
    return ManifestInfo(path, repository, projects, None)


_CONFIG_LEVELS = (
    ("local", ConfigFile.LOCAL),
    ("global", ConfigFile.GLOBAL),
    ("system", ConfigFile.SYSTEM),
)


def config_value(topdir: Path, option: str) -> tuple[str, str] | None:
    """Return the effective value of a west config option and the level that set it."""
    config = Configuration(topdir)
    for level, config_file in _CONFIG_LEVELS:
        value = config.get(option, configfile=config_file)
        if value:
            return value, level
    return None


def run_build(topdir: Path, arguments: list[str], log: Path) -> int:
    """Run `west build` with output and errors interleaved into log, and return its exit code."""
    log.parent.mkdir(exist_ok=True)
    with log.open("w") as output:
        return subprocess.run(
            [sys.executable, "-m", "west", "build", *arguments],
            cwd=topdir,
            # Under `zquire serve` stdin carries the MCP stream, which the build must not read.
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            # Unbuffered, so west's own messages stay in order with the tools it runs.
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            check=False,
        ).returncode
