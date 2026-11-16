import re
import time
from pathlib import Path

from zquire.adapters.store import prepare_state_dir
from zquire.adapters.west import run_west
from zquire.core import profiles, staleness
from zquire.core.context import Context
from zquire.errors import ZquireError

EXCERPT_LINES = 30
_RUNNER = re.compile(r"-- west flash: using runner (\S+)")
_COLOUR = re.compile(r"\x1b\[[0-9;]*m")
_DEFAULT_RUNNER = re.compile(r"^flash-runner:\s*(\S+)\s*$", re.MULTILINE)
# Runners whose flash starts an emulator, which runs until it is stopped.
_EMULATORS = {"qemu", "native", "arc-nsim"}
_NO_DEVICE = re.compile(
    r"There are no boards connected"  # Zephyr's nrfjprog and nrfutil runners
    r"|Cannot connect to the probe/programmer"  # J-Link Commander
    r"|Error: open failed"  # OpenOCD, when no ST-Link answers
)


def _target(context: Context, profile: str | None) -> tuple[str, dict, dict, set]:
    workspace = context.workspace
    name = profile if profile is not None else profiles.active_profile(workspace)
    if name is None:
        raise ZquireError(
            "NO_BUILD",
            "Flashing needs a build, and no profile was named and none is active.",
            "Pass profile, or call build to create and activate one.",
        )
    existing = profiles.load(workspace)
    settings = profiles.get(existing, name)
    record = profiles.read_state(workspace).get("builds", {}).get(name, {})
    if "last_success" not in record or not workspace.resolve(settings["build_dir"]).is_dir():
        raise ZquireError(
            "NO_BUILD",
            f"Flashing needs a successful build, and profile '{name}' has none.",
            f"Call build with profile '{name}' first.",
        )
    return name, settings, record["last_success"], staleness.build_dirs(workspace, existing)


def _check_flashable(build_dir: Path, runner: str | None) -> None:
    if runner is None:
        runners = build_dir / "zephyr" / "runners.yaml"
        found = _DEFAULT_RUNNER.search(runners.read_text()) if runners.is_file() else None
        runner = found.group(1) if found else None
    if runner in _EMULATORS:
        raise ZquireError(
            "NOT_FLASHABLE",
            f"Runner '{runner}' starts an emulator instead of flashing a board, "
            "and would not return.",
            "Flash a profile built for a hardware board, or pass a hardware runner.",
        )


def _warnings(
    context: Context, name: str, settings: dict, success: dict, excluded: set, require_fresh: bool
) -> list[dict]:
    if not staleness.is_stale(context.workspace, settings, success, excluded):
        return []
    if require_fresh:
        raise ZquireError(
            "STALE_BUILD",
            f"Profile '{name}' changed after its last successful build.",
            f"Call build with profile '{name}' first, or flash without require_fresh.",
        )
    return [
        {
            "code": "stale_build",
            "message": f"Profile '{name}' changed after its last successful build, "
            "so the firmware flashed may not match its sources.",
        }
    ]


def flash(
    context: Context,
    profile: str | None = None,
    runner: str | None = None,
    require_fresh: bool = False,
) -> dict:
    workspace = context.workspace
    name, settings, success, excluded = _target(context, profile)
    build_dir = workspace.resolve(settings["build_dir"])
    _check_flashable(build_dir, runner)
    warnings = _warnings(context, name, settings, success, excluded, require_fresh)
    prepare_state_dir(workspace.root)
    log = profiles.flash_log(workspace, name)
    # -v makes runners show their tools' output, which says why a probe was not found.
    arguments = ["-v", "flash", "--no-rebuild", "-d", str(build_dir)]
    if runner is not None:
        arguments += ["-r", runner]
    started = time.monotonic()
    exit_code = run_west(workspace.root, arguments, log)
    duration = round(time.monotonic() - started, 3)
    lines = _COLOUR.sub("", log.read_text(errors="replace")).splitlines()
    if exit_code != 0:
        message = next((line.strip() for line in lines if _NO_DEVICE.search(line)), None)
        if message is not None:
            raise ZquireError(
                "NO_DEVICE",
                f"No probe or board was found: {message}",
                f"Connect the board and check its probe is powered and accessible. "
                f"The full log is {workspace.relative(log)}.",
            )
    used = next((m.group(1) for line in lines if (m := _RUNNER.search(line))), runner)
    return {
        "profile": name,
        "status": "success" if exit_code == 0 else "failure",
        "runner": used,
        "duration_s": duration,
        "build_dir": settings["build_dir"],
        "log_path": workspace.relative(log),
        "log_excerpt": "\n".join(lines[-EXCERPT_LINES:]),
        "warnings": warnings,
    }
