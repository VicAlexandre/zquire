import time
from datetime import datetime, timezone

from zquire.adapters.store import prepare_state_dir
from zquire.adapters.west import run_build
from zquire.core import profiles
from zquire.core.context import Context
from zquire.core.diagnostics import diagnostics, memory_usage
from zquire.core.workspace import Workspace
from zquire.errors import ZquireError

DEFAULT_PROFILE = "default"


def _choose_profile(
    context: Context, profile: str | None, application: str | None, board: str | None
) -> tuple[str, bool]:
    workspace = context.workspace
    existing = profiles.load(workspace)
    given = {
        key: value
        for key, value in (("application", application), ("board", board))
        if value is not None
    }
    if given:
        if existing or profile is not None:
            raise ZquireError(
                "INVALID_ARGUMENT",
                "application and board only set up the default profile, when no profile exists.",
                "Build a profile by name, or change its settings with profile_update.",
            )
        profiles.create(context, DEFAULT_PROFILE, **given)
        profiles.activate(context, DEFAULT_PROFILE)
        return DEFAULT_PROFILE, True
    name = profile if profile is not None else profiles.active_profile(workspace)
    if name is None:
        raise ZquireError(
            "NO_PROFILE",
            "No profile named, no active profile, and no application and board given.",
            "Pass application and board to create the default profile, "
            "or create one with profile_create and activate it with profile_activate.",
        )
    profiles.get(existing, name)
    return name, False


def west_arguments(workspace: Workspace, settings: dict, pristine: str) -> list[str]:
    arguments = [
        "-d",
        str(profiles.workspace_path(workspace, settings["build_dir"])),
        "-b",
        settings["board"],
        "-s",
        str(profiles.workspace_path(workspace, settings["application"])),
        "-p",
        pristine,
    ]
    for snippet in settings["snippets"]:
        arguments += ["-S", snippet]
    cmake = [
        f"-D{variable}={';'.join(settings[key])}"
        for variable, key in (
            ("EXTRA_CONF_FILE", "conf_files"),
            ("EXTRA_DTC_OVERLAY_FILE", "overlays"),
            ("SHIELD", "shields"),
        )
        if settings[key]
    ]
    cmake += settings["cmake_args"]
    return arguments + ["--", *cmake] if cmake else arguments


def _record(workspace: Workspace, name: str, result: dict, finished: str) -> None:
    state = profiles.read_state(workspace)
    builds = state.setdefault("builds", {})
    record = {
        "status": result["status"],
        "time": finished,
        "duration_s": result["duration_s"],
        "build_dir": result["build_dir"],
    }
    if result["status"] == "success":
        record["last_success"] = {"time": finished}
    elif "last_success" in builds.get(name, {}):
        record["last_success"] = builds[name]["last_success"]
    builds[name] = record
    profiles.write_state(workspace, state)


def build(
    context: Context,
    profile: str | None = None,
    pristine: str | None = None,
    application: str | None = None,
    board: str | None = None,
) -> dict:
    workspace = context.workspace
    name, created = _choose_profile(context, profile, application, board)
    settings = profiles.load(workspace)[name]
    prepare_state_dir(workspace.root)
    log = profiles.build_log(workspace, name)
    started = time.monotonic()
    exit_code = run_build(
        workspace.root, west_arguments(workspace, settings, pristine or settings["pristine"]), log
    )
    duration = round(time.monotonic() - started, 3)
    output = log.read_text(errors="replace")
    succeeded = exit_code == 0
    result = {
        "profile": name,
        "profile_created": created,
        "status": "success" if succeeded else "failure",
        "duration_s": duration,
        "build_dir": settings["build_dir"],
        "log_path": workspace.relative(log),
        "diagnostics": diagnostics(output, workspace.root, failed=not succeeded),
        "memory": memory_usage(output) if succeeded else [],
    }
    _record(workspace, name, result, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return result
