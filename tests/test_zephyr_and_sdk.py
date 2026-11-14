import pytest

from tests.workspaces import make_workspace, manifest, t1, t2, t3, under, zephyr_tree
from zquire.core.sdk import sdk_version
from zquire.core.topology import infer
from zquire.core.workspace import locate
from zquire.core.zephyr import zephyr_base, zephyr_version


def base_of(root):
    workspace = locate(root)
    return zephyr_base(workspace, infer(workspace))


@pytest.mark.parametrize("make", [t2, t3], ids=["T2", "T3"])
def test_zephyr_base_is_the_zephyr_project(tmp_path, make):
    assert base_of(make(tmp_path)) == tmp_path / "zephyr"


def test_zephyr_base_is_the_manifest_repository_in_t1(tmp_path):
    assert base_of(t1(tmp_path)) == tmp_path / "zephyr"


def test_zephyr_base_is_none_without_a_zephyr_project(tmp_path):
    root = make_workspace(tmp_path, "app", {"app/west.yml": manifest("lib1", self_path="app")})
    assert base_of(root) is None


def test_zephyr_base_is_none_when_zephyr_is_not_cloned(tmp_path):
    files = {"app/west.yml": manifest("zephyr", self_path="app")}
    assert base_of(make_workspace(tmp_path, "app", files)) is None


def test_zephyr_base_is_none_when_the_project_is_not_a_zephyr_tree(tmp_path):
    files = {"app/west.yml": manifest("zephyr", self_path="app"), "zephyr/README": ""}
    assert base_of(make_workspace(tmp_path, "app", files)) is None


def test_zephyr_base_is_none_when_the_manifest_fails_to_load(tmp_path):
    files = {"app/west.yml": "manifest: [bad", **under("zephyr", zephyr_tree())}
    assert base_of(make_workspace(tmp_path, "app", files)) is None


@pytest.mark.parametrize(
    ("version", "expected"),
    [((4, 4, 0, ""), "4.4.0"), ((4, 5, 0, "rc1"), "4.5.0-rc1"), ((10, 0, 12, ""), "10.0.12")],
    ids=["release", "extraversion", "multi-digit"],
)
def test_zephyr_version(tmp_path, version, expected):
    (tmp_path / "VERSION").write_text(zephyr_tree(*version)["VERSION"])
    assert zephyr_version(tmp_path) == expected


def install_sdk(path, version):
    path.mkdir(parents=True)
    (path / "cmake").mkdir()
    (path / "sdk_version").write_text(version + "\n")
    return path


def register(home, name, sdk):
    registry = home / ".cmake/packages/Zephyr-sdk"
    registry.mkdir(parents=True, exist_ok=True)
    (registry / name).write_text(str(sdk / "cmake") + "\n")


def test_sdk_from_environment(tmp_path):
    sdk = install_sdk(tmp_path / "sdk", "0.17.4")
    assert sdk_version({"ZEPHYR_SDK_INSTALL_DIR": str(sdk)}, tmp_path / "home") == "0.17.4"


def test_environment_wins_over_the_registry(tmp_path):
    register(tmp_path / "home", "a", install_sdk(tmp_path / "registered", "1.0.0"))
    sdk = install_sdk(tmp_path / "sdk", "0.17.4")
    assert sdk_version({"ZEPHYR_SDK_INSTALL_DIR": str(sdk)}, tmp_path / "home") == "0.17.4"


@pytest.mark.parametrize("value", ["", "/nonexistent/sdk"], ids=["empty", "no-sdk-there"])
def test_environment_without_an_sdk_falls_back_to_the_registry(tmp_path, value):
    register(tmp_path / "home", "a", install_sdk(tmp_path / "registered", "1.0.0"))
    assert sdk_version({"ZEPHYR_SDK_INSTALL_DIR": value}, tmp_path / "home") == "1.0.0"


@pytest.mark.parametrize("names", [("a", "b"), ("b", "a")], ids=["older-first", "newer-first"])
def test_highest_registered_sdk_wins_numerically(tmp_path, names):
    home = tmp_path / "home"
    register(home, names[0], install_sdk(tmp_path / "old", "0.9.0"))
    register(home, names[1], install_sdk(tmp_path / "new", "0.17.4"))
    assert sdk_version({}, home) == "0.17.4"


def test_registry_entries_without_an_sdk_are_ignored(tmp_path):
    home = tmp_path / "home"
    register(home, "gone", tmp_path / "deleted-sdk")
    register(home, "ok", install_sdk(tmp_path / "ok", "0.17.4"))
    (home / ".cmake/packages/Zephyr-sdk/a-directory").mkdir()
    assert sdk_version({}, home) == "0.17.4"


@pytest.mark.parametrize("registered", [False, True], ids=["no-registry", "empty-registry"])
def test_no_sdk_found(tmp_path, registered):
    if registered:
        (tmp_path / ".cmake/packages/Zephyr-sdk").mkdir(parents=True)
    assert sdk_version({}, tmp_path) is None
