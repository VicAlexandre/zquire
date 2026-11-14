import hashlib
import os
from pathlib import Path

from zquire.adapters.git import head_commit
from zquire.core.workspace import Workspace
from zquire.core.zephyr import zephyr_base


def build_dirs(workspace: Workspace, profiles: dict[str, dict]) -> set[Path]:
    return {workspace.resolve(settings["build_dir"]) for settings in profiles.values()}


def _zephyr_head(workspace: Workspace) -> str | None:
    base = zephyr_base(workspace)
    return None if base is None else head_commit(base)


def _application_files(application: Path, excluded: set[Path]) -> list[Path]:
    found = []
    for directory, subdirectories, files in os.walk(application):
        current = Path(directory)
        subdirectories[:] = sorted(
            name
            for name in subdirectories
            # West compiles extension commands found in the application while it builds.
            if not name.startswith(".")
            and name != "__pycache__"
            and current / name not in excluded
            and not (current / name / "CMakeCache.txt").exists()
        )
        found += [current / name for name in sorted(files)]
    return found


def _fingerprint(application: Path, files: list[Path]) -> str:
    # Catches files removed or renamed, which leave no newer modification time behind.
    names = "\n".join(path.relative_to(application).as_posix() for path in files)
    return hashlib.sha256(names.encode()).hexdigest()


def snapshot(workspace: Workspace, settings: dict, started_ns: int, excluded: set[Path]) -> dict:
    """Record what a successful build depended on, to judge later whether it is stale."""
    application = workspace.resolve(settings["application"])
    record = {
        "started_ns": started_ns,
        "settings": settings,
        "application_files": _fingerprint(application, _application_files(application, excluded)),
    }
    head = _zephyr_head(workspace)
    if head is not None:
        record["zephyr_head"] = head
    return record


def _modified_since(path: Path, since_ns: int) -> bool:
    try:
        return path.stat().st_mtime_ns > since_ns
    except FileNotFoundError:
        return True


def is_stale(workspace: Workspace, settings: dict, success: dict, excluded: set[Path]) -> bool:
    if success["settings"] != settings:
        return True
    if success.get("zephyr_head") != _zephyr_head(workspace):
        return True
    since = success["started_ns"]
    application = workspace.resolve(settings["application"])
    named = [application / path for path in (*settings["conf_files"], *settings["overlays"])]
    files = _application_files(application, excluded)
    return _fingerprint(application, files) != success["application_files"] or any(
        _modified_since(path, since) for path in [*named, *files]
    )
