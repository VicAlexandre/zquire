import os
import time

import pytest

from tests.workspaces import (
    APPLICATION,
    build_output,
    fake_west_build,
    make_workspace,
    manifest,
    t3,
    under,
)
from zquire.core.context import Context
from zquire.core.workspace import locate
from zquire.tools import TOOLS, invoke

BOARD = "nrf52840dk/nrf52840"


@pytest.fixture
def root(tmp_path):
    root = fake_west_build(t3(tmp_path / "ws", "app"))
    (root / "app" / "src").mkdir()
    (root / "app" / "src" / "main.c").write_text("int main(void) { return 0; }\n")
    return root


def call(root, tool, **arguments):
    return invoke(TOOLS[tool], arguments, Context(locate(root)))


def create(root, name="one", **settings):
    call(root, "profile_create", name=name, **{"application": "app", "board": BOARD, **settings})


def stale(root, name="one"):
    return {p["name"]: p["stale"] for p in call(root, "profile_list")["profiles"]}[name]


def write(path, text="changed\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    later = time.time_ns() + 10**10
    os.utime(path, ns=(later, later))


def set_old_time(path):
    os.utime(path, ns=(10**9, 10**9))


@pytest.fixture
def built(root):
    create(root)
    call(root, "build", profile="one")
    return root


def test_never_built_is_not_judged(root):
    create(root)
    assert stale(root) is None


def test_only_failed_builds_are_not_judged(root):
    create(root)
    build_output(root, "compiler")
    call(root, "build", profile="one")
    assert stale(root) is None


def test_fresh_build_is_not_stale(built):
    assert stale(built) is False


def test_modified_application_file(built):
    write(built / "app" / "src" / "main.c")
    assert stale(built) is True


def test_added_application_file(built):
    write(built / "app" / "src" / "extra.c")
    assert stale(built) is True


def test_removed_application_file(built):
    (built / "app" / "src" / "main.c").unlink()
    assert stale(built) is True


def test_renamed_file_keeping_its_old_time(built):
    set_old_time(built / "app" / "src" / "main.c")
    (built / "app" / "src" / "main.c").rename(built / "app" / "src" / "start.c")
    assert stale(built) is True


def test_file_older_than_the_build_is_not_a_change(built):
    set_old_time(built / "app" / "src" / "main.c")
    assert stale(built) is False


@pytest.mark.parametrize(
    "path",
    [
        "build/one/zephyr/zephyr.elf",
        "build/one/CMakeCache.txt",
        ".git/index",
        "src/.cache/x",
        "scripts/__pycache__/cmd.cpython-313.pyc",
    ],
    ids=["own-build-dir", "own-cmake-cache", "dot-directory", "nested-dot-directory", "pycache"],
)
def test_ignored_application_paths(built, path):
    write(built / "app" / path)
    assert stale(built) is False


def test_other_profiles_build_directories_are_ignored(built):
    create(built, "two")
    write(built / "app" / "build" / "two" / "zephyr.elf")
    assert stale(built) is False


def test_unprofiled_build_directory_is_ignored(built):
    write(built / "app" / "build" / "CMakeCache.txt")
    write(built / "app" / "build" / "zephyr" / "zephyr.elf")
    assert stale(built) is False


def test_new_profile_build_directory_does_not_make_others_stale(built):
    create(built, "two")
    call(built, "build", profile="two")
    assert (stale(built, "one"), stale(built, "two")) == (False, False)


@pytest.mark.parametrize("setting", ["conf_files", "overlays"])
@pytest.mark.parametrize(
    "path",
    ["debug.conf", "../shared/debug.conf", "/abs/debug.conf"],
    ids=["in-application", "outside-application", "absolute"],
)
def test_named_fragment_or_overlay_modified(root, tmp_path, setting, path):
    if path.startswith("/abs"):
        path = str(tmp_path / "abs" / "debug.conf")
    target = root / "app" / path
    write(target)
    set_old_time(target)
    create(root, **{setting: [path]})
    call(root, "build", profile="one")
    assert stale(root) is False
    write(target)
    assert stale(root) is True


def test_missing_named_fragment(root):
    create(root, conf_files=["debug.conf"])
    call(root, "build", profile="one")
    assert stale(root) is True


def test_changed_settings(built):
    call(built, "profile_update", name="one", board="other")
    assert stale(built) is True


def test_settings_updated_to_the_same_values(built):
    call(built, "profile_update", name="one", board=BOARD)
    assert stale(built) is False


def zephyr_head(root, commit):
    git = root / "zephyr" / ".git"
    git.mkdir(exist_ok=True)
    (git / "HEAD").write_text(f"{commit}\n")


def test_zephyr_checkout_changed(root):
    zephyr_head(root, "a" * 40)
    create(root)
    call(root, "build", profile="one")
    assert stale(root) is False
    zephyr_head(root, "b" * 40)
    assert stale(root) is True


def test_zephyr_checkout_appearing(built):
    zephyr_head(built, "a" * 40)
    assert stale(built) is True


def test_workspace_without_a_zephyr_checkout(tmp_path):
    root = fake_west_build(
        make_workspace(
            tmp_path / "ws",
            "app",
            {"app/west.yml": manifest(self_path="app"), **under("app", APPLICATION)},
        )
    )
    create(root)
    call(root, "build", profile="one")
    assert stale(root) is False


def test_failure_after_a_success_is_judged_against_that_success(built):
    build_output(built, "compiler")
    call(built, "build", profile="one")
    assert stale(built) is False
    write(built / "app" / "src" / "main.c")
    assert stale(built) is True


def test_rebuilding_clears_staleness(built):
    write(built / "app" / "src" / "main.c")
    set_old_time(built / "app" / "src" / "main.c")
    call(built, "build", profile="one")
    assert stale(built) is False
