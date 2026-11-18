import json
import re
from pathlib import Path

import yaml

from zquire.adapters.store import prepare_state_dir
from zquire.adapters.west import run_west
from zquire.core import board_lock, profiles
from zquire.core.context import Context
from zquire.errors import ZquireError

STACK_RISK_PERCENT = 80
ZVIEW_TIMEOUT_S = 60
LOG_LINES = 30
# What ZView reads threads and their stacks through.
REQUIRED = ("CONFIG_INIT_STACKS", "CONFIG_THREAD_MONITOR", "CONFIG_THREAD_STACK_INFO")
_OPTIONAL = (
    ("CONFIG_THREAD_RUNTIME_STATS", "Threads have no CPU percent"),
    ("CONFIG_SYS_HEAP_RUNTIME_STATS", "Heaps are not listed"),
)
# The runner argument that names the target MCU, for the runners ZView knows one for.
_TARGET_ARGUMENTS = {"jlink": "--device", "pyocd": "--target"}
# thread_state bits, from Zephyr's kernel_structs.h, in the order a thread's state is named.
_THREAD_STATES = (
    (1 << 3, "dead"),
    (1 << 5, "aborting"),
    (1 << 4, "suspended"),
    (1 << 6, "suspending"),
    (1 << 1, "pending"),
    (1 << 2, "sleeping"),
)
ZVIEW_PROJECT = """\
manifest:
  projects:
    - name: zview
      url: https://github.com/wkhadgar/zview
      revision: main
      path: modules/tools/zview
      west-commands: scripts/west-commands.yml
"""


def _build_dir(context: Context, profile: str | None) -> tuple[str, Path]:
    workspace = context.workspace
    name = profile if profile is not None else profiles.active_profile(workspace)
    if name is None:
        raise ZquireError(
            "NO_PROFILE",
            "No profile named and no active profile.",
            "Pass profile, or activate one with profile_activate.",
        )
    settings = profiles.get(profiles.load(workspace), name)
    build_dir = workspace.resolve(settings["build_dir"])
    if not (build_dir / "zephyr" / ".config").is_file():
        raise ZquireError(
            "NO_BUILD",
            f"Profile '{name}' has no build for ZView to read.",
            f"Call build with profile '{name}' first, and flash it.",
        )
    return name, build_dir


def _enabled(build_dir: Path) -> set[str]:
    config = (build_dir / "zephyr" / ".config").read_text()
    return set(re.findall(r"^(CONFIG_\w+)=y$", config, re.MULTILINE))


def _check(name: str, enabled: set[str]) -> list[dict]:
    missing = [option for option in REQUIRED if option not in enabled]
    if missing:
        lines = "\n".join(f"{option}=y" for option in missing)
        raise ZquireError(
            "ZVIEW_PREREQ",
            f"ZView needs options that profile '{name}' does not set:\n{lines}",
            "Add those lines to the application's prj.conf, then build and flash it again.",
        )
    return [
        {
            "code": "option_disabled",
            "message": f"{effect}: set {option}=y in prj.conf to read them.",
        }
        for option, effect in _OPTIONAL
        if option not in enabled
    ]


def _probe(build_dir: Path, runner: str | None, target: str | None) -> tuple[str | None, ...]:
    runners_yaml = build_dir / "zephyr" / "runners.yaml"
    config = yaml.safe_load(runners_yaml.read_text()) if runners_yaml.is_file() else None
    config = config or {}
    runner = runner or config.get("flash-runner")
    if target is None and runner in _TARGET_ARGUMENTS:
        prefix = _TARGET_ARGUMENTS[runner]
        arguments = config.get("args", {}).get(runner, [])
        for index, argument in enumerate(arguments):
            if argument.startswith(prefix + "="):
                target = argument.split("=", 1)[1]
            elif argument == prefix and index + 1 < len(arguments):
                target = arguments[index + 1]
    return runner, target


def _state(bits: int | None) -> str | None:
    if bits is None:
        return None
    return next((name for bit, name in _THREAD_STATES if bits & bit), "ready")


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _thread(row: dict, threshold: float) -> dict:
    runtime = row.get("runtime") or {}
    watermark = _round(runtime.get("stack_watermark_percent"))
    return {
        "name": row["name"],
        "priority": row.get("priority"),
        "state": _state(row.get("state")),
        "stack_size": row.get("stack_size"),
        "stack_used": runtime.get("stack_watermark"),
        "watermark_percent": watermark,
        # The share of all CPU time, the idle threads' included.
        "cpu_percent": _round(runtime.get("cpu_normalized")),
        "flags": ["stack_risk"] if watermark is not None and watermark >= threshold else [],
    }


def _heap(row: dict) -> dict:
    used, free = row["allocated_bytes"], row["free_bytes"]
    return {
        "name": row["name"],
        "size": used + free,
        "used": used,
        "free": free,
        "max_used": row.get("max_allocated_bytes"),
    }


def _frame(output: str) -> dict | None:
    # ZView prints the frame as one line of JSON, among the notices it writes to stderr.
    for line in reversed(output.splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def _failure(output: str, log_path: str) -> ZquireError:
    if 'unknown command "zview"' in output:
        return ZquireError(
            "ZVIEW_MISSING",
            "ZView is not installed in this workspace.",
            f"Add this project to west.yml, then run `west update zview` and install its "
            f"requirements with `pip install -r modules/tools/zview/scripts/requirements.txt`:"
            f"\n{ZVIEW_PROJECT}",
        )
    tail = "\n".join(output.splitlines()[-LOG_LINES:])
    return ZquireError(
        "ZVIEW_FAILED",
        f"ZView could not read the board:\n{tail}",
        f"Check the board is running and its probe is connected. The full log is {log_path}.",
    )


def _sections(include: str, threads: list[str] | None, heaps: list[str] | None) -> list[str]:
    sections = ["threads", "heaps"] if include == "both" else [include]
    for section, names in (("threads", threads), ("heaps", heaps)):
        if names is not None and section not in sections:
            raise ZquireError(
                "INVALID_ARGUMENT",
                f"{section} filters a section that include leaves out.",
                f"Drop {section}, or include {section}.",
            )
    return sections


def _select(rows: list[dict], names: list[str] | None) -> tuple[list[dict], list[str]]:
    if names is None:
        return rows, []
    found = {row["name"] for row in rows}
    return [row for row in rows if row["name"] in names], [n for n in names if n not in found]


def runtime_stats(
    context: Context,
    profile: str | None = None,
    runner: str | None = None,
    runner_target: str | None = None,
    stack_risk_percent: float = STACK_RISK_PERCENT,
    include: str = "both",
    threads: list[str] | None = None,
    heaps: list[str] | None = None,
) -> dict:
    workspace = context.workspace
    sections = _sections(include, threads, heaps)
    name, build_dir = _build_dir(context, profile)
    warnings = _check(name, _enabled(build_dir))
    runner, runner_target = _probe(build_dir, runner, runner_target)
    arguments = ["zview", "dump", "--json", "-d", str(build_dir)]
    if runner is not None:
        arguments += ["-r", runner]
    if runner_target is not None:
        arguments += ["-t", runner_target]
    log = prepare_state_dir(workspace.root) / "logs" / "zview.log"
    with board_lock.hold(workspace, "runtime_stats"):
        exit_code = run_west(workspace.root, arguments, log, ZVIEW_TIMEOUT_S)
    output = log.read_text(errors="replace")
    frame = _frame(output) if exit_code == 0 else None
    if frame is None:
        if exit_code is None:
            output += f"\nZView did not finish within {ZVIEW_TIMEOUT_S} s."
        raise _failure(output, workspace.relative(log))
    result = {"profile": name, "runner": runner, "runner_target": runner_target}
    found_threads, missing_threads = _select(frame.get("threads", []), threads)
    found_heaps, missing_heaps = _select(frame.get("heaps", []), heaps)
    if "threads" in sections:
        result["threads"] = [_thread(row, stack_risk_percent) for row in found_threads]
    if "heaps" in sections:
        result["heaps"] = [_heap(row) for row in found_heaps]
    not_found = missing_threads + missing_heaps
    requested = (threads or []) + (heaps or [])
    if requested and not_found == requested:
        raise ZquireError(
            "NOT_FOUND",
            f"The board has no thread or heap named {', '.join(requested)}.",
            "Call runtime_stats without names to list them.",
        )
    return {
        **result,
        "not_found": not_found,
        "log_path": workspace.relative(log),
        "warnings": warnings,
    }
