import pytest

from tests.workspaces import t2, t3
from zquire.adapters.store import read_toml
from zquire.core.context import Context
from zquire.core.workspace import locate
from zquire.errors import ZquireError
from zquire.tools import TOOLS, invoke

BOARD = "nrf52840dk/nrf52840"


@pytest.fixture
def root(tmp_path):
    return t3(tmp_path / "ws", "app")


def call(root, tool, **arguments):
    return invoke(TOOLS[tool], arguments, Context(locate(root)))


def fails(root, tool, **arguments):
    with pytest.raises(ZquireError) as raised:
        call(root, tool, **arguments)
    assert raised.value.message and raised.value.hint
    return raised.value


def profiles_file(root):
    return read_toml(root / ".zquire" / "profiles.toml")


def set_board(path, board):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as config:
        config.write(f"\n[build]\nboard = {board}\n")


def test_profile_tools_are_registered():
    names = {
        "profile_list",
        "profile_create",
        "profile_update",
        "profile_delete",
        "profile_activate",
    }
    assert names <= TOOLS.keys()


def test_create_stores_every_setting(root):
    settings = {
        "application": "app",
        "board": BOARD,
        "build_dir": "app/out",
        "pristine": "always",
        "cmake_args": ["-DFOO=1"],
        "conf_files": ["debug.conf"],
        "overlays": ["board.overlay"],
        "snippets": ["cdc-acm-console"],
        "shields": ["x_nucleo_iks01a3"],
    }
    result = call(root, "profile_create", name="bench-1", **settings)
    assert result == {"profile": {"name": "bench-1", **settings}, "defaults_applied": []}
    assert profiles_file(root) == {"bench-1": settings}


def test_create_fills_defaults(root):
    profile = call(root, "profile_create", name="bench-1", application="app", board=BOARD)[
        "profile"
    ]
    assert profile == {
        "name": "bench-1",
        "application": "app",
        "board": BOARD,
        "build_dir": "app/build/bench-1",
        "pristine": "auto",
        "cmake_args": [],
        "conf_files": [],
        "overlays": [],
        "snippets": [],
        "shields": [],
    }


def test_storage_layout_and_no_partial_file(root):
    call(root, "profile_create", name="bench-1", application="app", board=BOARD)
    call(root, "profile_activate", name="bench-1")
    assert sorted(p.name for p in (root / ".zquire").iterdir()) == [
        ".gitignore",
        "profiles.toml",
        "state.toml",
    ]
    assert read_toml(root / ".zquire" / "state.toml") == {"active_profile": "bench-1"}


def test_zquire_directory_ignores_itself_in_git(root):
    call(root, "profile_create", name="bench-1", application="app", board=BOARD)
    assert (root / ".zquire" / ".gitignore").read_text() == "*\n"


def test_an_existing_gitignore_is_left_alone(root):
    (root / ".zquire").mkdir()
    (root / ".zquire" / ".gitignore").write_text("profiles.toml\n")
    call(root, "profile_create", name="bench-1", application="app", board=BOARD)
    assert (root / ".zquire" / ".gitignore").read_text() == "profiles.toml\n"


def test_reading_does_not_create_the_zquire_directory(root):
    call(root, "status")
    call(root, "profile_list")
    assert not (root / ".zquire").exists()


def test_activate_alone_also_ignores_the_directory(root):
    call(root, "profile_create", name="bench-1", application="app", board=BOARD)
    (root / ".zquire" / ".gitignore").unlink()
    call(root, "profile_activate", name="bench-1")
    assert (root / ".zquire" / ".gitignore").is_file()


def test_create_from_copies_settings_but_not_the_build_dir(root):
    call(root, "profile_create", name="bench-1", application="app", board=BOARD, shields=["s1"])
    profile = call(
        root, "profile_create", name="bench-debug", conf_files=["debug.conf"], **{"from": "bench-1"}
    )["profile"]
    assert (profile["application"], profile["board"], profile["shields"]) == ("app", BOARD, ["s1"])
    assert profile["conf_files"] == ["debug.conf"]
    assert profile["build_dir"] == "app/build/bench-debug"


def test_given_settings_override_the_copied_ones(root):
    call(root, "profile_create", name="bench-1", application="app", board=BOARD)
    profile = call(root, "profile_create", name="other", board="qemu_x86", **{"from": "bench-1"})
    assert profile["profile"]["board"] == "qemu_x86"


def test_create_from_an_unknown_profile(root):
    error = fails(root, "profile_create", name="b", **{"from": "nope"})
    assert error.code == "PROFILE_NOT_FOUND"


@pytest.mark.parametrize("name", ["a", "0", "bench-1", "trailing-", "x86"])
def test_valid_profile_names(root, name):
    call(root, "profile_create", name=name, application="app", board=BOARD)


@pytest.mark.parametrize("name", ["", "Bench", "-a", "a_b", "a.b", "Bench Test", "a/b"])
def test_invalid_profile_names(root, name):
    error = fails(root, "profile_create", name=name, application="app", board=BOARD)
    assert error.code == "INVALID_PROFILE_NAME"
    assert profiles_file(root) == {}


def test_duplicate_profile_name(root):
    call(root, "profile_create", name="bench-1", application="app", board=BOARD)
    assert fails(root, "profile_create", name="bench-1", application="app", board="x").code == (
        "PROFILE_EXISTS"
    )
    assert profiles_file(root)["bench-1"]["board"] == BOARD


@pytest.mark.parametrize(
    "spelling", ["app/build/bench", "./app/build/bench", "app/build/../build/bench", "ABSOLUTE"]
)
def test_shared_build_directory_is_refused(root, spelling):
    call(
        root,
        "profile_create",
        name="bench-1",
        application="app",
        board=BOARD,
        build_dir="app/build/bench",
    )
    build_dir = str(root / "app/build/bench") if spelling == "ABSOLUTE" else spelling
    error = fails(
        root, "profile_create", name="bench-2", application="app", board=BOARD, build_dir=build_dir
    )
    assert error.code == "BUILD_DIR_IN_USE"
    assert "bench-2" not in profiles_file(root)


def test_update_onto_another_profiles_build_directory_is_refused(root):
    call(root, "profile_create", name="bench-1", application="app", board=BOARD)
    call(root, "profile_create", name="bench-2", application="app", board=BOARD)
    error = fails(root, "profile_update", name="bench-2", build_dir="app/build/bench-1")
    assert error.code == "BUILD_DIR_IN_USE"


def test_update_changes_only_the_given_settings(root):
    call(root, "profile_create", name="bench-1", application="app", board=BOARD)
    profile = call(root, "profile_update", name="bench-1", board="qemu_x86")["profile"]
    assert (profile["board"], profile["build_dir"]) == ("qemu_x86", "app/build/bench-1")
    assert profiles_file(root)["bench-1"]["board"] == "qemu_x86"


def test_update_an_unknown_profile(root):
    assert fails(root, "profile_update", name="nope", board=BOARD).code == "PROFILE_NOT_FOUND"


def test_paths_are_stored_relative_to_the_workspace_when_inside_it(root, tmp_path):
    outside = tmp_path / "elsewhere" / "app"
    profile = call(
        root,
        "profile_create",
        name="b",
        application=str(root / "app"),
        board=BOARD,
        build_dir=str(outside / "build"),
    )["profile"]
    assert (profile["application"], profile["build_dir"]) == ("app", str(outside / "build"))


def test_absolute_build_dir_inside_the_workspace_is_stored_relative(root):
    profile = call(
        root,
        "profile_create",
        name="b",
        application="app",
        board=BOARD,
        build_dir=str(root / "app" / "out"),
    )["profile"]
    assert profile["build_dir"] == "app/out"


def test_activate_sets_the_active_profile(root):
    call(root, "profile_create", name="bench-1", application="app", board=BOARD)
    assert call(root, "profile_activate", name="bench-1") == {"active_profile": "bench-1"}
    assert call(root, "status")["workspace"]["active_profile"] == "bench-1"


def test_activate_an_unknown_profile(root):
    assert fails(root, "profile_activate", name="nope").code == "PROFILE_NOT_FOUND"


def test_list_marks_the_active_profile(root):
    for name in ("bench-1", "bench-2"):
        call(root, "profile_create", name=name, application="app", board=BOARD)
    call(root, "profile_activate", name="bench-2")
    listed = call(root, "profile_list")["profiles"]
    assert [(p["name"], p["active"]) for p in listed] == [("bench-1", False), ("bench-2", True)]


def test_list_with_no_profiles(root):
    assert call(root, "profile_list") == {"profiles": []}


def test_deleting_the_active_profile_is_refused(root):
    call(root, "profile_create", name="bench-1", application="app", board=BOARD)
    call(root, "profile_activate", name="bench-1")
    assert fails(root, "profile_delete", name="bench-1").code == "PROFILE_ACTIVE"
    assert "bench-1" in profiles_file(root)


def make_build_dir(root, name):
    build_dir = root / "app" / "build" / name
    build_dir.mkdir(parents=True)
    (build_dir / "zephyr.elf").write_text("")
    return build_dir


def test_delete_keeps_the_build_directory_by_default(root):
    call(root, "profile_create", name="bench-1", application="app", board=BOARD)
    build_dir = make_build_dir(root, "bench-1")
    assert call(root, "profile_delete", name="bench-1") == {
        "deleted": "bench-1",
        "build_dir_removed": False,
    }
    assert profiles_file(root) == {}
    assert build_dir.is_dir()


def test_delete_removes_the_build_directory_when_asked(root):
    call(root, "profile_create", name="bench-1", application="app", board=BOARD)
    build_dir = make_build_dir(root, "bench-1")
    result = call(root, "profile_delete", name="bench-1", remove_build_dir=True)
    assert result["build_dir_removed"] is True
    assert not build_dir.exists()


def test_delete_with_remove_build_dir_and_no_build_directory(root):
    call(root, "profile_create", name="bench-1", application="app", board=BOARD)
    result = call(root, "profile_delete", name="bench-1", remove_build_dir=True)
    assert result["build_dir_removed"] is False


@pytest.mark.parametrize(
    "build_dir", ["app", ".", "OUTSIDE"], ids=["application", "root", "outside"]
)
def test_unsafe_build_directories_are_never_removed(root, tmp_path, build_dir):
    if build_dir == "OUTSIDE":
        build_dir = str(tmp_path / "outside")
        (tmp_path / "outside").mkdir()
    call(root, "profile_create", name="b", application="app", board=BOARD, build_dir=build_dir)
    error = fails(root, "profile_delete", name="b", remove_build_dir=True)
    assert error.code == "UNSAFE_BUILD_DIR"
    assert "b" in profiles_file(root)
    assert (root / "app" / "CMakeLists.txt").is_file()


def test_delete_an_unknown_profile(root):
    assert fails(root, "profile_delete", name="nope").code == "PROFILE_NOT_FOUND"


@pytest.mark.parametrize("level", ["local", "global", "system"])
def test_board_from_west_config(root, tmp_path, level):
    path = root / ".west/config" if level == "local" else tmp_path / f"west-{level}.cfg"
    set_board(path, BOARD)
    result = call(root, "profile_create", name="bench-3", application="app")
    assert result["profile"]["board"] == BOARD
    assert result["defaults_applied"] == [
        {"setting": "board", "source": "west config", "level": level}
    ]


def test_local_board_wins_over_global(root, tmp_path):
    set_board(tmp_path / "west-global.cfg", "global_board")
    set_board(root / ".west/config", "local_board")
    assert call(root, "profile_create", name="b", application="app")["profile"]["board"] == (
        "local_board"
    )


def test_explicit_board_wins_over_west_config(root):
    set_board(root / ".west/config", "config_board")
    result = call(root, "profile_create", name="b", application="app", board=BOARD)
    assert (result["profile"]["board"], result["defaults_applied"]) == (BOARD, [])


def test_no_board_anywhere(root):
    error = fails(root, "profile_create", name="b", application="app")
    assert error.code == "NO_BOARD"
    assert profiles_file(root) == {}


def test_single_candidate_becomes_the_application(root):
    result = call(root, "profile_create", name="b", board=BOARD)
    assert result["profile"]["application"] == "app"
    assert result["defaults_applied"] == [
        {"setting": "application", "source": "default_application"}
    ]


@pytest.mark.parametrize(
    ("apps", "listed"), [(("app1", "app2"), "app1, app2"), ((), "none found")], ids=["two", "none"]
)
def test_no_single_candidate_needs_an_application(tmp_path, apps, listed):
    root = t3(tmp_path / "ws", *apps)
    error = fails(root, "profile_create", name="b", board=BOARD)
    assert error.code == "NO_APPLICATION"
    assert listed in error.hint


def test_active_profile_survives_a_restart(tmp_path):
    root = t2(tmp_path / "ws")
    call(root, "profile_create", name="bench-1", board=BOARD)
    call(root, "profile_activate", name="bench-1")
    restarted = Context(locate(root))
    assert invoke(TOOLS["status"], {}, restarted)["workspace"]["active_profile"] == "bench-1"
