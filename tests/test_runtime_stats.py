import json
import time

import pytest
import yaml

from tests.workspaces import (
    fake_west_build,
    fake_zview,
    t3,
    zview_build,
    zview_calls,
    zview_dump,
    zview_heap,
    zview_thread,
)
from zquire.core import board_lock, runtime_stats
from zquire.core.context import Context
from zquire.core.runtime_stats import LOG_LINES, REQUIRED, STACK_RISK_PERCENT
from zquire.core.workspace import locate
from zquire.errors import ZquireError
from zquire.tools import TOOLS, invoke

OPTIONAL = ("CONFIG_THREAD_RUNTIME_STATS", "CONFIG_SYS_HEAP_RUNTIME_STATS")
EVERY = (*REQUIRED, *OPTIONAL)


@pytest.fixture
def root(tmp_path):
    root = fake_zview(fake_west_build(t3(tmp_path / "ws", "app")))
    for name in ("one", "two"):
        call(root, "profile_create", name=name, application="app", board="nrf52840dk/nrf52840")
        call(root, "build", profile=name)
    call(root, "profile_activate", name="one")
    configure(root)
    return root


def call(root, tool, **arguments):
    return invoke(TOOLS[tool], arguments, Context(locate(root)))


def fails(root, **arguments):
    with pytest.raises(ZquireError) as error:
        call(root, "runtime_stats", **arguments)
    return error.value


def build_dir(root, profile="one"):
    return root / "app" / "build" / profile


def configure(root, options=EVERY, runners=None, profile="one"):
    if runners is None:
        runners = {"flash-runner": "jlink", "args": {"jlink": ["--device=nRF52840_xxAA"]}}
    config = "# CONFIG_DEBUG is not set\n" + "".join(f"{option}=y\n" for option in options)
    text = runners if isinstance(runners, str) or runners is False else yaml.safe_dump(runners)
    if text is False:
        (build_dir(root, profile) / "zephyr" / "runners.yaml").unlink(missing_ok=True)
    zview_build(root, build_dir(root, profile), config, None if text is False else text)


def made(root):
    (made,) = zview_calls(root)
    return made


def test_dumps_the_active_profile_once_as_json(root):
    result = call(root, "runtime_stats")
    assert result["profile"] == "one"
    assert (made(root)["cmd"], made(root)["json"]) == ("dump", True)
    assert made(root)["build_dir"] == str(build_dir(root))
    assert result["log_path"] == ".zquire/logs/zview.log"


def test_dumps_a_named_profile(root):
    configure(root, profile="two")
    assert call(root, "runtime_stats", profile="two")["profile"] == "two"
    assert made(root)["build_dir"] == str(build_dir(root, "two"))


def test_no_profile(tmp_path):
    root = fake_zview(fake_west_build(t3(tmp_path / "ws", "app")))
    assert fails(root).code == "NO_PROFILE"


def test_unknown_profile(root):
    assert fails(root, profile="three").code == "PROFILE_NOT_FOUND"


def test_profile_without_a_build(root):
    (build_dir(root) / "zephyr" / ".config").unlink()
    error = fails(root)
    assert (error.code, error.hint) == (
        "NO_BUILD",
        "Call build with profile 'one' first, and flash it.",
    )
    assert zview_calls(root) == []


@pytest.mark.parametrize("option", REQUIRED)
def test_each_required_option(root, option):
    configure(root, [o for o in EVERY if o != option])
    error = fails(root)
    assert (error.code, error.message.splitlines()[1:]) == ("ZVIEW_PREREQ", [f"{option}=y"])
    assert zview_calls(root) == []


def test_lists_every_missing_option(root):
    configure(root, OPTIONAL)
    error = fails(root)
    assert error.message.splitlines() == [
        "ZView needs options that profile 'one' does not set:",
        *(f"{option}=y" for option in REQUIRED),
    ]
    assert "prj.conf" in error.hint


def test_options_set_to_something_else_are_missing(root):
    configure(root, ["CONFIG_INIT_STACKS_EXTRA", *REQUIRED[1:], *OPTIONAL])
    config = build_dir(root) / "zephyr" / ".config"
    config.write_text(config.read_text() + "CONFIG_INIT_STACKS=n\n")
    assert fails(root).message.splitlines()[1:] == ["CONFIG_INIT_STACKS=y"]


def test_no_warnings_with_every_option(root):
    assert call(root, "runtime_stats")["warnings"] == []


def test_warns_for_each_optional_option(root):
    configure(root, REQUIRED)
    assert call(root, "runtime_stats")["warnings"] == [
        {
            "code": "option_disabled",
            "message": "Threads have no CPU percent: set CONFIG_THREAD_RUNTIME_STATS=y in "
            "prj.conf to read them.",
        },
        {
            "code": "option_disabled",
            "message": "Heaps are not listed: set CONFIG_SYS_HEAP_RUNTIME_STATS=y in prj.conf "
            "to read them.",
        },
    ]


def test_runner_and_target_from_the_board(root):
    result = call(root, "runtime_stats")
    assert (result["runner"], result["runner_target"]) == ("jlink", "nRF52840_xxAA")
    assert (made(root)["runner"], made(root)["runner_target"]) == ("jlink", "nRF52840_xxAA")


@pytest.mark.parametrize(
    "arguments, target",
    [
        (["--target=nrf52840"], "nrf52840"),
        (["--target", "nrf52840"], "nrf52840"),
        (["--frequency=4M", "--target", "nrf52840", "--x"], "nrf52840"),
        (["--target"], None),
        (["--targets=nrf52840"], None),
        ([], None),
    ],
)
def test_target_from_the_runners_arguments(root, arguments, target):
    configure(root, runners={"flash-runner": "pyocd", "args": {"pyocd": arguments}})
    assert call(root, "runtime_stats")["runner_target"] == target
    assert made(root)["runner_target"] == target


def test_runner_override_takes_that_runners_target(root):
    runners = {"flash-runner": "jlink", "args": {"jlink": ["--device=X"], "pyocd": ["--target=Y"]}}
    configure(root, runners=runners)
    result = call(root, "runtime_stats", runner="pyocd")
    assert (result["runner"], result["runner_target"]) == ("pyocd", "Y")


def test_target_override(root):
    result = call(root, "runtime_stats", runner_target="nRF52833_xxAA")
    assert (result["runner"], result["runner_target"]) == ("jlink", "nRF52833_xxAA")


def test_runner_without_a_known_target_argument(root):
    configure(root, runners={"flash-runner": "nrfutil", "args": {"nrfutil": ["--x=y"]}})
    result = call(root, "runtime_stats")
    assert (result["runner"], result["runner_target"]) == ("nrfutil", None)


@pytest.mark.parametrize("runners", [False, "", {"runners": ["jlink"]}])
def test_no_runner_configuration_leaves_it_to_zview(root, runners):
    configure(root, runners=runners)
    result = call(root, "runtime_stats")
    assert (result["runner"], result["runner_target"]) == (None, None)
    assert (made(root)["runner"], made(root)["runner_target"]) == (None, None)


def test_thread_fields(root):
    zview_dump(root, [zview_thread("sensor", 2048, 333, cpu=12.345, priority=-2, state=0)], [])
    (thread,) = call(root, "runtime_stats")["threads"]
    assert thread == {
        "name": "sensor",
        "priority": -2,
        "state": "ready",
        "stack_size": 2048,
        "stack_used": 333,
        "watermark_percent": 16.3,
        "cpu_percent": 12.3,
        "flags": [],
    }


@pytest.mark.parametrize(
    "bits, state",
    [
        (0, "ready"),
        (1 << 7, "ready"),
        (1 << 1, "pending"),
        (1 << 2, "sleeping"),
        ((1 << 1) | (1 << 2), "pending"),
        (1 << 4, "suspended"),
        ((1 << 4) | (1 << 1), "suspended"),
        (1 << 6, "suspending"),
        ((1 << 6) | (1 << 1), "suspending"),
        (1 << 5, "aborting"),
        ((1 << 5) | (1 << 4), "aborting"),
        (1 << 3, "dead"),
        ((1 << 3) | (1 << 5), "dead"),
        (None, None),
    ],
)
def test_thread_state(root, bits, state):
    zview_dump(root, [zview_thread("main", state=bits)], [])
    assert call(root, "runtime_stats")["threads"][0]["state"] == state


def test_cpu_percent_is_the_share_of_all_cpu_time(root):
    row = zview_thread("main", cpu=50.0)
    row["runtime"]["cpu"] = 80.0
    zview_dump(root, [row], [])
    assert call(root, "runtime_stats")["threads"][0]["cpu_percent"] == 50.0


@pytest.mark.parametrize("used, flagged", [(800, True), (799, False), (1000, True), (0, False)])
def test_stack_risk_from_the_default_threshold(root, used, flagged):
    assert STACK_RISK_PERCENT == 80
    zview_dump(root, [zview_thread("main", 1000, used)], [])
    flags = call(root, "runtime_stats")["threads"][0]["flags"]
    assert flags == (["stack_risk"] if flagged else [])


def test_stack_risk_threshold(root):
    zview_dump(root, [zview_thread("a", 1000, 500), zview_thread("b", 1000, 499)], [])
    threads = call(root, "runtime_stats", stack_risk_percent=50)["threads"]
    assert [t["flags"] for t in threads] == [["stack_risk"], []]


def test_thread_without_stack_data(root):
    row = zview_thread("main", used=None)
    row["stack_size"] = None
    zview_dump(root, [row], [])
    thread = call(root, "runtime_stats", stack_risk_percent=0)["threads"][0]
    assert (thread["stack_size"], thread["stack_used"], thread["watermark_percent"]) == (
        None,
        None,
        None,
    )
    assert thread["flags"] == []


def test_thread_without_runtime(root):
    row = zview_thread("main")
    row["runtime"] = None
    zview_dump(root, [row], [])
    thread = call(root, "runtime_stats")["threads"][0]
    assert (thread["stack_used"], thread["cpu_percent"]) == (None, None)


def test_heap_fields(root):
    zview_dump(root, [], [zview_heap("app_heap", 4096, 1000, 3000), zview_heap("other", 64, 0, 0)])
    assert call(root, "runtime_stats")["heaps"] == [
        {"name": "app_heap", "size": 4096, "used": 1000, "free": 3096, "max_used": 3000},
        {"name": "other", "size": 64, "used": 0, "free": 64, "max_used": 0},
    ]


def test_frame_without_heaps(root):
    (root / "fake-build" / "zview.json").write_text(json.dumps({"threads": []}) + "\n")
    assert call(root, "runtime_stats")["heaps"] == []


def test_frame_among_notices(root):
    zview_dump(root, [zview_thread("main")], [], stderr="{not json\nNO thread names\n")
    assert [t["name"] for t in call(root, "runtime_stats")["threads"]] == ["main"]


def test_frame_before_a_later_notice(root):
    frame = json.dumps({"threads": [zview_thread("main")], "heaps": []})
    (root / "fake-build" / "zview.json").write_text(f"{frame}\nzview: disconnected\n")
    assert [t["name"] for t in call(root, "runtime_stats")["threads"]] == ["main"]


def test_no_frame_fails(root):
    (root / "fake-build" / "zview.json").write_text("{broken\n")
    error = fails(root)
    assert (error.code, error.message.splitlines()[-1]) == ("ZVIEW_FAILED", "{broken")


def test_zview_failure_keeps_the_log_tail(root):
    notices = "".join(f"notice {n}\n" for n in range(LOG_LINES + 5))
    zview_dump(root, [], [], stderr=notices + "Could not connect to the probe\n", exit_code=1)
    (root / "fake-build" / "zview.json").write_text("")
    error = fails(root)
    lines = error.message.splitlines()
    assert lines[0] == "ZView could not read the board:"
    assert len(lines) == 1 + LOG_LINES
    assert lines[-1] == "Could not connect to the probe"
    assert ".zquire/logs/zview.log" in error.hint


def test_zview_missing(root):
    commands = root / "manifest-repo" / "zquire-fake-build" / "west-commands.yml"
    commands.write_text(
        commands.read_text().replace("      - name: zview\n        class: Zview\n", "")
    )
    error = fails(root)
    assert error.code == "ZVIEW_MISSING"
    assert error.message == "ZView is not installed in this workspace."
    manifest = yaml.safe_load(error.hint[error.hint.index("manifest:") :])
    assert manifest["manifest"]["projects"][0]["url"] == "https://github.com/wkhadgar/zview"


def test_zview_that_hangs(root, monkeypatch):
    monkeypatch.setattr(runtime_stats, "ZVIEW_TIMEOUT_S", 1)
    (root / "fake-build" / "zview-delay").write_text("30")
    started = time.monotonic()
    error = fails(root)
    assert time.monotonic() - started < 10
    assert error.code == "ZVIEW_FAILED"
    assert error.message.splitlines()[-1] == "ZView did not finish within 1 s."


def test_waits_for_the_board(root, monkeypatch):
    monkeypatch.setattr(board_lock, "LOCK_TIMEOUT_S", 0.2)
    with board_lock.hold(locate(root), "flash"):
        assert fails(root).code == "BUSY"
    assert zview_calls(root) == []


def test_missing_prerequisites_do_not_wait_for_the_board(root, monkeypatch):
    monkeypatch.setattr(board_lock, "LOCK_TIMEOUT_S", 5)
    configure(root, OPTIONAL)
    with board_lock.hold(locate(root), "flash"):
        started = time.monotonic()
        assert fails(root).code == "ZVIEW_PREREQ"
        assert time.monotonic() - started < 1


def test_flash_fails_busy_while_a_dump_holds_the_board(root, monkeypatch):
    monkeypatch.setattr(board_lock, "LOCK_TIMEOUT_S", 0.2)
    with board_lock.hold(locate(root), "runtime_stats"), pytest.raises(ZquireError) as error:
        call(root, "flash")
    assert error.value.code == "BUSY"
    assert "in use by runtime_stats" in error.value.message
