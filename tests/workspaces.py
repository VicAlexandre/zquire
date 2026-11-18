import configparser
import json
import re
import shutil
from pathlib import Path

APPLICATION = {"CMakeLists.txt": "find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})\n"}


def zephyr_tree(major=4, minor=4, patch=0, extra=""):
    version = (
        f"VERSION_MAJOR = {major}\nVERSION_MINOR = {minor}\nPATCHLEVEL = {patch}\n"
        f"VERSION_TWEAK = 0\nEXTRAVERSION = {extra}\n"
    )
    return {"VERSION": version, "Kconfig.zephyr": ""}


def under(prefix, files):
    return {f"{prefix}/{path}": content for path, content in files.items()}


def project(name):
    return f"    - name: {name}\n      url: https://example.com/{name}\n      revision: main\n"


def manifest(*projects, self_path=None):
    text = "manifest:\n"
    if projects:
        text += "  projects:\n" + "".join(project(name) for name in projects)
    if self_path:
        text += f"  self:\n    path: {self_path}\n"
    return text


def make_workspace(root: Path, repository: str, files: dict, manifest_file="west.yml") -> Path:
    """Lay out a west workspace as `west init -l` leaves it, without git or network."""
    (root / ".west").mkdir(parents=True)
    (root / ".west" / "config").write_text(
        f"[manifest]\npath = {repository}\nfile = {manifest_file}\n"
    )
    for path, content in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(content)
    return root


def t1(root: Path) -> Path:
    return make_workspace(
        root,
        "zephyr",
        {"zephyr/west.yml": manifest(self_path="zephyr"), **under("zephyr", zephyr_tree())},
    )


def t2(root: Path, *applications: str) -> Path:
    files = {
        "application/west.yml": manifest("zephyr", self_path="application"),
        **under("zephyr", zephyr_tree()),
    }
    for application in applications or ("application",):
        files.update(under(application, APPLICATION))
    return make_workspace(root, "application", files)


def t3(root: Path, *projects: str) -> Path:
    files = {
        "manifest-repo/west.yml": manifest("zephyr", *projects, self_path="manifest-repo"),
        **under("zephyr", zephyr_tree()),
    }
    for name in projects:
        files.update(under(name, APPLICATION))
    return make_workspace(root, "manifest-repo", files)


FAKE_BUILD = Path(__file__).with_name("fake_west_build.py")
LOGS = Path(__file__).with_name("logs")


def fake_west_build(root: Path) -> Path:
    """Give the workspace a `west build`, `west flash` and `west twister` that replay logs
    instead."""
    config = configparser.ConfigParser()
    config.read(root / ".west" / "config")
    repository = root / config["manifest"]["path"]
    scripts = repository / "zquire-fake-build"
    scripts.mkdir()
    shutil.copy(FAKE_BUILD, scripts / "fake_west_build.py")
    (scripts / "west-commands.yml").write_text(
        "west-commands:\n"
        "  - file: zquire-fake-build/fake_west_build.py\n"
        "    commands:\n"
        "      - name: build\n"
        "        class: Build\n"
        "      - name: flash\n"
        "        class: Flash\n"
        "      - name: twister\n"
        "        class: Twister\n"
    )
    with (repository / config["manifest"]["file"]).open("a") as manifest_file:
        manifest_file.write("    west-commands: zquire-fake-build/west-commands.yml\n")
    (root / "fake-build").mkdir()
    build_output(root, "success")
    flash_output(root, "flash-success")
    twister_report(root, [])
    return root


def build_output(root: Path, log: str, exit_code: int | None = None) -> str:
    """Make the next fake build print tests/logs/<log>.log and exit with exit_code.

    The logs were recorded in a workspace at /ws, which becomes root.
    """
    output = re.sub(r"/ws\b", str(root), (LOGS / f"{log}.log").read_text())
    (root / "fake-build" / "output.log").write_text(output)
    if exit_code is None:
        exit_code = 0 if log in ("success", "kconfig", "repeat") else 1
    (root / "fake-build" / "exit_code").write_text(str(exit_code))
    return output


def flash_output(root: Path, log: str, exit_code: int | None = None) -> str:
    """Make the next fake flash print tests/logs/<log>.log and exit with exit_code."""
    output = re.sub(r"/ws\b", str(root), (LOGS / f"{log}.log").read_text())
    (root / "fake-build" / "flash-output.log").write_text(output)
    if exit_code is None:
        exit_code = 0 if log == "flash-success" else 1
    (root / "fake-build" / "flash-exit_code").write_text(str(exit_code))
    return output


def flash_port(root: Path, link: Path, device: str | None, delay: float = 0.3) -> None:
    """Make the next fake flash check the port behind link is free, then re-enumerate it to
    device after delay seconds, or remove it for good when device is None."""
    hook = {"link": str(link), "device": device, "delay": delay}
    (root / "fake-build" / "flash-port.json").write_text(json.dumps(hook))


def twister_suite(name: str, status: str, cases=(), **fields) -> dict:
    """A test suite as Twister's twister.json reports it, with cases as (identifier, status)."""
    testcases = [
        {"identifier": identifier, "execution_time": "0.00", "status": case_status}
        for identifier, case_status in cases
    ]
    suite = {
        "name": name,
        "arch": "posix",
        "platform": "native_sim",
        "path": name.rsplit(".", 1)[0].replace(".", "/"),
        "runnable": True,
        "retries": 0,
        "status": status,
        "execution_time": "0.10",
        "build_time": "1.00",
        "testcases": testcases,
    }
    return {**suite, **fields}


def twister_report(
    root: Path, suites: list[dict] | None, output: str = "", exit_code: int | None = None
) -> None:
    """Make the next fake Twister run print output, write a report of suites unless None, and
    exit with exit_code, by default 1 when a suite failed."""
    fake = root / "fake-build"
    report = fake / "twister.json"
    if suites is None:
        report.unlink(missing_ok=True)
    else:
        environment = {"os": "Linux", "zephyr_version": "v4.4.0", "toolchain": "zephyr"}
        text = json.dumps({"environment": environment, "testsuites": suites}, indent=4)
        report.write_text(re.sub(r"/ws\b", str(root), text))
    (fake / "twister-output.log").write_text(output)
    if exit_code is None:
        exit_code = int(any(s["status"] in ("failed", "error") for s in suites or []))
    (fake / "twister-exit_code").write_text(str(exit_code))


def twister_hang(root: Path, mode: str) -> None:
    """Make the next fake Twister run hang until interrupted, or until killed when mode is
    "ignore"."""
    (root / "fake-build" / "twister-hang").write_text(mode)


def twister_port(root: Path, link: Path, device: str | None, delay: float = 0.3) -> None:
    """As flash_port, for the next fake Twister run."""
    hook = {"link": str(link), "device": device, "delay": delay}
    (root / "fake-build" / "twister-port.json").write_text(json.dumps(hook))


def fake_zview(root: Path) -> Path:
    """Give the workspace a `west zview` that replays a dump instead, as installing ZView
    would."""
    config = configparser.ConfigParser()
    config.read(root / ".west" / "config")
    commands = root / config["manifest"]["path"] / "zquire-fake-build" / "west-commands.yml"
    with commands.open("a") as west_commands:
        west_commands.write("      - name: zview\n        class: Zview\n")
    zview_dump(root, [], [])
    return root


def zview_thread(name, stack_size=1024, used=256, cpu=None, priority=0, state=0, idle=False):
    """A thread as ZView's dump --json writes it."""
    runtime = {
        "cpu": cpu,
        "cpu_normalized": cpu,
        "is_active": bool(cpu),
        "stack_watermark": used,
        "stack_watermark_percent": None if used is None else used / stack_size * 100,
        "is_cpu_coherent": None,
    }
    return {
        "address": 0x20000000 + len(name) * 0x100,
        "stack_start": 0x20001000,
        "stack_size": stack_size,
        "name": name,
        "runtime": runtime,
        "priority": priority,
        "state": state,
        "user_options": 0,
        "entry_point": 0x1235,
        "entry_symbol": f"{name}_entry",
        "entry_site": None,
        "is_idle": idle,
        "line": f"thread {name:30s} stack={stack_size:>6}  watermark={used}",
    }


def zview_heap(name, size=4096, used=1024, max_used=2048):
    """A heap as ZView's dump --json writes it."""
    return {
        "name": name,
        "address": 0x20004000,
        "free_bytes": size - used,
        "allocated_bytes": used,
        "max_allocated_bytes": max_used,
        "usage_percent": used / size * 100,
        "chunks": None,
        "waiters": [],
        "decl_site": None,
        "line": f"heap {name:20s} free={size - used} alloc={used} max={max_used} waiters=-",
        "glance": {"fill": used / size * 100, "text": f"{used}/{size}B", "level": "normal"},
    }


def zview_dump(
    root: Path, threads: list, heaps: list, stderr: str = "", exit_code: int = 0
) -> None:
    """Make the next fake ZView dump print a frame of threads and heaps, and stderr."""
    fake = root / "fake-build"
    frame = {"threads": threads, "heaps": heaps, "semaphores": [], "mutexes": []}
    (fake / "zview.json").write_text(json.dumps(frame) + "\n")
    (fake / "zview-stderr.log").write_text(stderr)
    (fake / "zview-exit_code").write_text(str(exit_code))


def zview_calls(root: Path) -> list[dict]:
    calls = root / "fake-build" / "zview-calls.jsonl"
    return [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []


def zview_build(root: Path, build_dir: Path, config: str, runners: str | None = None) -> None:
    """Give a build directory the .config and runners.yaml ZView reads."""
    (build_dir / "zephyr").mkdir(parents=True, exist_ok=True)
    (build_dir / "zephyr" / ".config").write_text(config)
    if runners is not None:
        (build_dir / "zephyr" / "runners.yaml").write_text(runners)


def twister_calls(root: Path) -> list[dict]:
    calls = root / "fake-build" / "twister-calls.jsonl"
    return [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []


def flash_calls(root: Path) -> list[dict]:
    calls = root / "fake-build" / "flash-calls.jsonl"
    return [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []


def build_calls(root: Path) -> list[dict]:
    calls = root / "fake-build" / "calls.jsonl"
    return [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []


def _cmake_quoted(path) -> str:
    return f'"{path}"' if " " in str(path) else str(path)


def query_build(root: Path, build_dir: Path, kconfig="", config="", dts=None, generator="ninja"):
    """Leave in build_dir what a Zephyr build leaves for Kconfig and devicetree queries.

    The Kconfig tree starts at <root>/zephyr/Kconfig and is read with the kconfiglib the tests
    install, standing in for the copy in Zephyr's scripts/kconfig.
    """
    import kconfiglib

    zephyr = root / "zephyr"
    (zephyr / "Kconfig").write_text(kconfig)
    (zephyr / "scripts" / "kconfig").mkdir(parents=True, exist_ok=True)
    shutil.copy(kconfiglib.__file__, zephyr / "scripts" / "kconfig" / "kconfiglib.py")
    (build_dir / "zephyr").mkdir(parents=True, exist_ok=True)
    (build_dir / "zephyr" / ".config").write_text(config)
    if dts is not None:
        (build_dir / "zephyr" / "zephyr.dts").write_text(dts)
    environment = (
        f"srctree={_cmake_quoted(zephyr)} ZEPHYR_BASE={_cmake_quoted(zephyr)} "
        f"KCONFIG_CONFIG={_cmake_quoted(build_dir / 'zephyr' / '.config')} ARCH=*"
    )
    command = (
        f"cd {_cmake_quoted(build_dir / 'zephyr' / 'kconfig')} && /usr/bin/cmake -E env "
        f"{environment} /usr/bin/python3 "
        f"{_cmake_quoted(zephyr / 'scripts' / 'kconfig' / 'menuconfig.py')} "
        f"{_cmake_quoted(zephyr / 'Kconfig')}"
    )
    if generator == "ninja":
        (build_dir / "build.ninja").write_text(
            "rule CUSTOM_COMMAND\n  command = $COMMAND\n\n"
            "build zephyr/misc: CUSTOM_COMMAND\n  COMMAND = cd /b && /usr/bin/cmake -E env "
            "KCONFIG_CONFIG=/elsewhere /usr/bin/python3 gen.py\n\n"
            "build menuconfig: phony CMakeFiles/menuconfig # runs menuconfig.py\n\n"
            "build CMakeFiles/menuconfig | ${cmake_ninja_workdir}CMakeFiles/menuconfig: "
            f"CUSTOM_COMMAND\n  COMMAND = {command.replace('$', '$$')}\n  pool = console\n"
        )
    else:
        make = build_dir / "CMakeFiles" / "menuconfig.dir" / "build.make"
        make.parent.mkdir(parents=True, exist_ok=True)
        make.write_text(f"CMakeFiles/menuconfig:\n\t{command.replace('$', '$$')}\n")
