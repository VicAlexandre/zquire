import re
import shutil
from pathlib import Path

from zquire.adapters.store import prepare_state_dir, read_toml, write_toml
from zquire.adapters.west import config_value
from zquire.core.context import Context
from zquire.core.topology import infer
from zquire.core.workspace import Workspace
from zquire.errors import ZquireError

_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
_DEFAULTS = {
    "pristine": "auto",
    "cmake_args": [],
    "conf_files": [],
    "overlays": [],
    "snippets": [],
    "shields": [],
}


def _profiles_file(workspace: Workspace) -> Path:
    return workspace.root / ".zquire" / "profiles.toml"


def _state_file(workspace: Workspace) -> Path:
    return workspace.root / ".zquire" / "state.toml"


def build_log(workspace: Workspace, name: str) -> Path:
    return workspace.root / ".zquire" / "logs" / f"{name}-build.log"


def load(workspace: Workspace) -> dict[str, dict]:
    return read_toml(_profiles_file(workspace))


def read_state(workspace: Workspace) -> dict:
    return read_toml(_state_file(workspace))


def write_state(workspace: Workspace, state: dict) -> None:
    prepare_state_dir(workspace.root)
    write_toml(_state_file(workspace), state)


def active_profile(workspace: Workspace) -> str | None:
    return read_state(workspace).get("active_profile")


def _save(workspace: Workspace, profiles: dict[str, dict]) -> None:
    prepare_state_dir(workspace.root)
    write_toml(_profiles_file(workspace), profiles)


def _set_active(workspace: Workspace, name: str) -> None:
    state = read_state(workspace)
    state["active_profile"] = name
    write_state(workspace, state)


def get(profiles: dict[str, dict], name: str) -> dict:
    if name not in profiles:
        raise ZquireError(
            "PROFILE_NOT_FOUND",
            f"No build profile named '{name}'.",
            "Call profile_list to see the profiles.",
        )
    return profiles[name]


def _view(name: str, settings: dict) -> dict:
    return {"name": name, **settings}


def workspace_path(workspace: Workspace, path: str) -> Path:
    return (workspace.root / path).resolve()


def _stored_path(workspace: Workspace, path: Path) -> str:
    try:
        return path.relative_to(workspace.root).as_posix()
    except ValueError:
        return str(path)


def _check_build_dir_free(workspace: Workspace, profiles: dict, name: str, build_dir: str) -> None:
    wanted = workspace_path(workspace, build_dir)
    for other, settings in profiles.items():
        if other != name and workspace_path(workspace, settings["build_dir"]) == wanted:
            raise ZquireError(
                "BUILD_DIR_IN_USE",
                f"Build directory '{build_dir}' is already used by profile '{other}'.",
                "Give this profile its own build_dir.",
            )


def _default_application(workspace: Workspace) -> str:
    candidates = infer(workspace).candidates
    if len(candidates) == 1:
        return workspace.relative(candidates[0])
    listed = ", ".join(workspace.relative(c) for c in candidates) or "none found"
    raise ZquireError(
        "NO_APPLICATION",
        "No application given and no single default application.",
        f"Pass application. Candidates: {listed}.",
    )


def _default_board(workspace: Workspace) -> tuple[str, str]:
    found = config_value(workspace.root, "build.board")
    if found is None:
        raise ZquireError(
            "NO_BOARD",
            "No board given and `west config build.board` is not set.",
            "Pass board, e.g. nrf52840dk/nrf52840.",
        )
    return found


def _normalised(workspace: Workspace, settings: dict) -> dict:
    for key in ("application", "build_dir"):
        if key in settings:
            settings[key] = _stored_path(workspace, workspace_path(workspace, settings[key]))
    return settings


def create(context: Context, name: str, **changes) -> dict:
    workspace = context.workspace
    if not _NAME.fullmatch(name):
        raise ZquireError(
            "INVALID_PROFILE_NAME",
            f"'{name}' is not a valid profile name.",
            "Use lowercase letters, digits and dashes, starting with a letter or digit.",
        )
    profiles = load(workspace)
    if name in profiles:
        raise ZquireError(
            "PROFILE_EXISTS",
            f"A build profile named '{name}' already exists.",
            "Choose another name, or call profile_update.",
        )
    source = changes.pop("from", None)
    settings = dict(_DEFAULTS)
    if source is not None:
        settings.update({k: v for k, v in get(profiles, source).items() if k != "build_dir"})
    settings.update(_normalised(workspace, changes))
    defaults_applied = []
    if "application" not in settings:
        settings["application"] = _default_application(workspace)
        defaults_applied.append({"setting": "application", "source": "default_application"})
    if "board" not in settings:
        settings["board"], level = _default_board(workspace)
        defaults_applied.append({"setting": "board", "source": "west config", "level": level})
    settings.setdefault("build_dir", f"{settings['application']}/build/{name}")
    _check_build_dir_free(workspace, profiles, name, settings["build_dir"])
    profiles[name] = settings
    _save(workspace, profiles)
    return {"profile": _view(name, settings), "defaults_applied": defaults_applied}


def update(context: Context, name: str, **changes) -> dict:
    workspace = context.workspace
    profiles = load(workspace)
    settings = {**get(profiles, name), **_normalised(workspace, changes)}
    _check_build_dir_free(workspace, profiles, name, settings["build_dir"])
    profiles[name] = settings
    _save(workspace, profiles)
    return {"profile": _view(name, settings)}


def delete(context: Context, name: str, remove_build_dir: bool = False) -> dict:
    workspace = context.workspace
    profiles = load(workspace)
    settings = get(profiles, name)
    if active_profile(workspace) == name:
        raise ZquireError(
            "PROFILE_ACTIVE",
            f"'{name}' is the active profile.",
            "Activate another profile first.",
        )
    build_dir = workspace_path(workspace, settings["build_dir"])
    removed = remove_build_dir and build_dir.is_dir()
    if removed:
        _check_removable(workspace, build_dir, settings)
    del profiles[name]
    _save(workspace, profiles)
    state = read_state(workspace)
    if state.get("builds", {}).pop(name, None) is not None:
        write_state(workspace, state)
    build_log(workspace, name).unlink(missing_ok=True)
    if removed:
        shutil.rmtree(build_dir)
    return {"deleted": name, "build_dir_removed": removed}


def _check_removable(workspace: Workspace, build_dir: Path, settings: dict) -> None:
    application = workspace_path(workspace, settings["application"])
    inside = workspace.root in build_dir.parents
    if not inside or build_dir == application or build_dir in application.parents:
        raise ZquireError(
            "UNSAFE_BUILD_DIR",
            f"Refusing to remove '{build_dir}': it is not a build directory inside the workspace.",
            "Delete it by hand if that is really intended.",
        )


def activate(context: Context, name: str) -> dict:
    workspace = context.workspace
    get(load(workspace), name)
    _set_active(workspace, name)
    return {"active_profile": name}


def _last_build(record: dict | None) -> dict | None:
    if record is None:
        return None
    return {key: record[key] for key in ("status", "time", "duration_s", "build_dir")}


def list_profiles(context: Context) -> dict:
    workspace = context.workspace
    state = read_state(workspace)
    builds = state.get("builds", {})
    return {
        "profiles": [
            {
                **_view(name, settings),
                "active": name == state.get("active_profile"),
                "last_build": _last_build(builds.get(name)),
            }
            for name, settings in load(workspace).items()
        ]
    }
