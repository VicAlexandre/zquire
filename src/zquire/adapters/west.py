from dataclasses import dataclass
from pathlib import Path

from west.configuration import Configuration
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
