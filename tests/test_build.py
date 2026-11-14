import time
from datetime import datetime

import pytest

from tests.workspaces import build_calls, build_output, fake_west_build, t3
from zquire.adapters.store import read_toml
from zquire.core.build import west_arguments
from zquire.core.context import Context
from zquire.core.workspace import locate
from zquire.errors import ZquireError
from zquire.tools import TOOLS, invoke

BOARD = "nrf52840dk/nrf52840"


@pytest.fixture
def root(tmp_path):
    return fake_west_build(t3(tmp_path / "ws", "app"))


def call(root, tool, **arguments):
    return invoke(TOOLS[tool], arguments, Context(locate(root)))


def fails(root, tool, **arguments):
    with pytest.raises(ZquireError) as raised:
        call(root, tool, **arguments)
    assert raised.value.message and raised.value.hint
    return raised.value.code


def create(root, name, **settings):
    call(root, "profile_create", name=name, **{"application": "app", "board": BOARD, **settings})


def listed(root):
    return {p["name"]: p for p in call(root, "profile_list")["profiles"]}


def builds(root):
    return read_toml(root / ".zquire" / "state.toml").get("builds", {})


def test_build_tool_is_registered():
    assert "build" in TOOLS


def test_named_profile_is_built_and_stays_inactive(root):
    create(root, "one")
    create(root, "two")
    call(root, "profile_activate", name="one")
    assert call(root, "build", profile="two")["profile"] == "two"
    assert build_calls(root)[0]["build_dir"] == str(root / "app" / "build" / "two")
    assert call(root, "status")["workspace"]["active_profile"] == "one"


def test_active_profile_is_built_by_default(root):
    create(root, "one")
    call(root, "profile_activate", name="one")
    result = call(root, "build")
    assert (result["profile"], result["profile_created"]) == ("one", False)


def test_unknown_named_profile(root):
    assert fails(root, "build", profile="nope") == "PROFILE_NOT_FOUND"
    assert build_calls(root) == []


@pytest.mark.parametrize("with_profiles", [False, True], ids=["no-profiles", "none-active"])
def test_nothing_to_build(root, with_profiles):
    if with_profiles:
        create(root, "one")
    assert fails(root, "build") == "NO_PROFILE"
    assert build_calls(root) == []


def test_application_and_board_create_and_activate_the_default_profile(root):
    result = call(root, "build", application="app", board=BOARD)
    assert (result["profile"], result["profile_created"]) == ("default", True)
    default = listed(root)["default"]
    assert (default["application"], default["board"], default["active"]) == ("app", BOARD, True)
    assert default["build_dir"] == "app/build/default"


def test_default_profile_takes_missing_settings_from_the_profile_defaults(root):
    with (root / ".west" / "config").open("a") as config:
        config.write(f"\n[build]\nboard = {BOARD}\n")
    call(root, "build", application="app")
    assert listed(root)["default"]["board"] == BOARD


def test_default_profile_uses_the_application_given(tmp_path):
    root = fake_west_build(t3(tmp_path / "ws", "app", "other"))
    call(root, "build", application="other", board=BOARD)
    assert listed(root)["default"]["application"] == "other"


def test_board_alone_uses_the_single_application(root):
    call(root, "build", board=BOARD)
    assert listed(root)["default"]["application"] == "app"


def test_later_builds_reuse_the_default_profile(root):
    call(root, "build", application="app", board=BOARD)
    assert call(root, "build")["profile_created"] is False


@pytest.mark.parametrize(
    "arguments",
    [{"application": "app"}, {"board": BOARD}, {"application": "app", "board": BOARD}],
    ids=["application", "board", "both"],
)
def test_application_or_board_with_existing_profiles_is_rejected(root, arguments):
    create(root, "one")
    call(root, "profile_activate", name="one")
    assert fails(root, "build", **arguments) == "INVALID_ARGUMENT"
    assert build_calls(root) == []


def test_application_and_board_with_a_profile_name_is_rejected(root):
    assert fails(root, "build", profile="x", application="app", board=BOARD) == "INVALID_ARGUMENT"
    assert listed(root) == {}


def settings(**changes):
    return {
        "application": "app",
        "board": BOARD,
        "build_dir": "app/build/x",
        "pristine": "auto",
        "cmake_args": [],
        "conf_files": [],
        "overlays": [],
        "snippets": [],
        "shields": [],
        **changes,
    }


def test_west_arguments_for_minimal_settings(root):
    workspace = locate(root)
    assert west_arguments(workspace, settings(), "auto") == [
        "-d",
        str(root / "app" / "build" / "x"),
        "-b",
        BOARD,
        "-s",
        str(root / "app"),
        "-p",
        "auto",
    ]


def test_west_arguments_for_every_setting(root, tmp_path):
    workspace = locate(root)
    full = settings(
        application=str(tmp_path / "outside"),
        snippets=["s1", "s2"],
        conf_files=["a.conf", "b.conf"],
        overlays=["x.overlay"],
        shields=["sh1", "sh2"],
        cmake_args=["-DFOO=1", "-DBAR=2"],
    )
    assert west_arguments(workspace, full, "always")[5:] == [
        str(tmp_path / "outside"),
        "-p",
        "always",
        "-S",
        "s1",
        "-S",
        "s2",
        "--",
        "-DEXTRA_CONF_FILE=a.conf;b.conf",
        "-DEXTRA_DTC_OVERLAY_FILE=x.overlay",
        "-DSHIELD=sh1;sh2",
        "-DFOO=1",
        "-DBAR=2",
    ]


def test_cmake_args_alone_follow_the_separator(root):
    arguments = west_arguments(locate(root), settings(cmake_args=["-DX=1"]), "never")
    assert arguments[-2:] == ["--", "-DX=1"]


def test_profile_settings_reach_west_build(root):
    create(root, "one", pristine="never", conf_files=["debug.conf"], snippets=["rtt"])
    call(root, "build", profile="one")
    assert build_calls(root) == [
        {
            "build_dir": str(root / "app" / "build" / "one"),
            "board": BOARD,
            "source_dir": str(root / "app"),
            "pristine": "never",
            "snippets": ["rtt"],
            "cmake_args": ["-DEXTRA_CONF_FILE=debug.conf"],
        }
    ]


def test_pristine_overrides_the_profile_for_one_build(root):
    create(root, "one", pristine="never")
    call(root, "build", profile="one", pristine="always")
    call(root, "build", profile="one")
    assert [c["pristine"] for c in build_calls(root)] == ["always", "never"]
    assert listed(root)["one"]["pristine"] == "never"


def test_successful_build_result(root):
    result = call(root, "build", application="app", board=BOARD)
    assert (result["status"], result["diagnostics"]) == ("success", [])
    assert [r["region"] for r in result["memory"]] == ["FLASH", "RAM", "IDT_LIST"]
    assert result["build_dir"] == "app/build/default"


def test_duration_is_the_time_west_build_took(root):
    started = time.monotonic()
    duration = call(root, "build", application="app", board=BOARD)["duration_s"]
    assert 0 < duration <= time.monotonic() - started


def test_log_is_stored_in_full_and_its_path_returned(root):
    result = call(root, "build", application="app", board=BOARD)
    assert result["log_path"] == ".zquire/logs/default-build.log"
    assert (root / result["log_path"]).read_text() == build_output(root, "success")


def test_errors_are_logged_after_the_output_they_follow(root):
    (root / "fake-build" / "output.log").write_text("-- west build: running\n")
    (root / "fake-build" / "stderr.log").write_text("CMake Error: on stderr\n")
    result = call(root, "build", application="app", board=BOARD)
    log = (root / result["log_path"]).read_text()
    assert log == "-- west build: running\nCMake Error: on stderr\n"
    assert [d["category"] for d in result["diagnostics"]] == ["cmake"]


def test_output_that_is_not_utf8_is_still_parsed(root):
    (root / "fake-build" / "output.log").write_bytes(b"\xff\xfe junk\n/ws/a.c:1:2: error: bad\n")
    (root / "fake-build" / "exit_code").write_text("1")
    result = call(root, "build", application="app", board=BOARD)
    assert [d["message"] for d in result["diagnostics"]] == ["bad"]


def test_each_build_replaces_the_profile_log(root):
    call(root, "build", application="app", board=BOARD)
    output = build_output(root, "compiler")
    log_path = call(root, "build")["log_path"]
    assert (root / log_path).read_text() == output


def test_failed_build_result(root):
    build_output(root, "compiler")
    result = call(root, "build", application="app", board=BOARD)
    assert (result["status"], result["memory"]) == ("failure", [])
    assert [d["category"] for d in result["diagnostics"]] == ["compiler"]


@pytest.mark.parametrize("exit_code", [1, 2, 255])
def test_any_nonzero_exit_is_a_failure(root, exit_code):
    build_output(root, "success", exit_code)
    result = call(root, "build", application="app", board=BOARD)
    assert (result["status"], result["memory"]) == ("failure", [])


def test_success_after_warnings_has_memory_and_diagnostics(root):
    build_output(root, "repeat")
    result = call(root, "build", application="app", board=BOARD)
    assert result["status"] == "success"
    assert result["memory"] and result["diagnostics"][0]["count"] == 12


def test_build_is_recorded_against_its_profile(root):
    call(root, "build", application="app", board=BOARD)
    record = builds(root)["default"]
    assert (record["status"], record["build_dir"]) == ("success", "app/build/default")
    assert datetime.fromisoformat(record["time"]).utcoffset().total_seconds() == 0
    assert listed(root)["default"]["last_build"] == {
        key: record[key] for key in ("status", "time", "duration_s", "build_dir")
    }


def test_failure_keeps_the_last_success(root):
    call(root, "build", application="app", board=BOARD)
    success = builds(root)["default"]["last_success"]
    build_output(root, "compiler")
    call(root, "build")
    record = builds(root)["default"]
    assert (record["status"], record["last_success"]) == ("failure", success)


def test_failure_without_an_earlier_success(root):
    build_output(root, "compiler")
    call(root, "build", application="app", board=BOARD)
    assert "last_success" not in builds(root)["default"]


def test_unbuilt_profile_has_no_last_build(root):
    create(root, "one")
    assert listed(root)["one"]["last_build"] is None


def test_building_one_profile_leaves_the_others_records(root):
    create(root, "one")
    create(root, "two")
    call(root, "build", profile="one")
    call(root, "build", profile="two")
    assert builds(root).keys() == {"one", "two"}


def test_deleting_a_profile_forgets_its_builds(root):
    create(root, "one")
    create(root, "two")
    call(root, "build", profile="one")
    call(root, "build", profile="two")
    call(root, "profile_delete", name="one")
    assert builds(root).keys() == {"two"}


def test_deleting_a_profile_removes_its_log(root):
    create(root, "one")
    create(root, "two")
    one = call(root, "build", profile="one")["log_path"]
    two = call(root, "build", profile="two")["log_path"]
    call(root, "profile_delete", name="one")
    assert (not (root / one).exists(), (root / two).exists()) == (True, True)


def test_deleting_an_unbuilt_profile_leaves_state_alone(root):
    create(root, "one")
    call(root, "profile_delete", name="one")
    assert not (root / ".zquire" / "state.toml").exists()


def test_build_keeps_state_out_of_git(root):
    call(root, "build", application="app", board=BOARD)
    assert (root / ".zquire" / ".gitignore").read_text() == "*\n"
