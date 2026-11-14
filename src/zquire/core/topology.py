import os
from dataclasses import dataclass
from pathlib import Path

from zquire.core.workspace import Workspace

_APPLICATION_MARKER = "find_package(Zephyr"


@dataclass(frozen=True)
class Topology:
    kind: str
    evidence: list[str]
    candidates: list[Path]


def is_zephyr_tree(path: Path) -> bool:
    return (path / "VERSION").is_file() and (path / "Kconfig.zephyr").is_file()


def find_applications(root: Path) -> list[Path]:
    applications = []
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = sorted(d for d in subdirectories if not d.startswith("."))
        if "CMakeLists.txt" in files:
            cmake = Path(directory, "CMakeLists.txt").read_text(errors="replace")
            if _APPLICATION_MARKER in cmake:
                applications.append(Path(directory))
    return applications


def infer(workspace: Workspace) -> Topology:
    manifest = workspace.manifest
    if manifest.projects is None:
        return Topology("unknown", [f"manifest failed to load: {manifest.load_error}"], [])
    repository = manifest.repository
    if is_zephyr_tree(repository):
        return Topology(
            "T1", [f"{repository.name}/VERSION and {repository.name}/Kconfig.zephyr exist"], []
        )
    applications = find_applications(repository)
    if applications:
        evidence = (
            f"{repository.name} holds {len(applications)} Zephyr application(s), "
            f"e.g. {workspace.relative(applications[0])}"
        )
        return Topology("T2", [evidence], applications)
    candidates = [
        application
        for name, path in manifest.projects.items()
        if name != "zephyr" and path.is_dir()
        for application in find_applications(path)
    ]
    return Topology(
        "T3",
        [f"{repository.name} holds neither the Zephyr tree nor a Zephyr application"],
        candidates,
    )
