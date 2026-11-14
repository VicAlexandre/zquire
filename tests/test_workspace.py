from pathlib import Path

import pytest

from tests.workspaces import make_workspace, manifest, t2
from zquire.core.workspace import locate


def test_found_from_the_topdir(tmp_path):
    assert locate(t2(tmp_path)).root == tmp_path


def test_found_by_searching_upward(tmp_path):
    t2(tmp_path)
    nested = tmp_path / "application" / "src" / "deep"
    nested.mkdir(parents=True)
    assert locate(nested).root == tmp_path


def test_not_found_outside_any_workspace(tmp_path):
    assert locate(tmp_path) is None


def test_explicit_workspace_is_used(tmp_path):
    workspace = t2(tmp_path / "ws")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert locate(elsewhere, explicit=workspace).root == workspace


def test_explicit_workspace_wins_over_the_working_directory(tmp_path):
    t2(tmp_path / "cwd-ws")
    other = t2(tmp_path / "other-ws")
    assert locate(tmp_path / "cwd-ws", explicit=other).root == other


@pytest.mark.parametrize("subpath", ["missing", "application"], ids=["missing", "not-a-topdir"])
def test_explicit_path_that_is_not_a_topdir_is_not_a_workspace(tmp_path, subpath):
    t2(tmp_path)
    assert locate(tmp_path, explicit=tmp_path / subpath) is None


def test_explicit_relative_path_is_resolved(tmp_path, monkeypatch):
    t2(tmp_path / "ws")
    monkeypatch.chdir(tmp_path)
    assert locate(tmp_path, explicit=Path("ws")).root == tmp_path / "ws"


def test_manifest_paths_come_from_the_west_config(tmp_path):
    make_workspace(tmp_path, "app", {"app/custom.yml": manifest(self_path="app")}, "custom.yml")
    found = locate(tmp_path).manifest
    assert (found.repository, found.path) == (tmp_path / "app", tmp_path / "app" / "custom.yml")
    assert found.load_error is None


def test_declared_projects_are_listed_without_imports(tmp_path):
    text = manifest("zephyr", "lib1", self_path="app").replace(
        "      revision: main\n", "      revision: main\n      import: true\n", 1
    )
    make_workspace(tmp_path, "app", {"app/west.yml": text})
    assert locate(tmp_path).manifest.projects == {
        "zephyr": tmp_path / "zephyr",
        "lib1": tmp_path / "lib1",
    }


def test_invalid_manifest_keeps_the_paths_and_records_the_error(tmp_path):
    make_workspace(tmp_path, "app", {"app/west.yml": "manifest: [bad"})
    found = locate(tmp_path).manifest
    assert (found.repository, found.path) == (tmp_path / "app", tmp_path / "app" / "west.yml")
    assert found.projects is None
    assert "did not find expected" in found.load_error


def test_manifest_file_defaults_to_west_yml(tmp_path):
    make_workspace(tmp_path, "app", {"app/west.yml": manifest(self_path="app")})
    (tmp_path / ".west/config").write_text("[manifest]\npath = app\n")
    found = locate(tmp_path).manifest
    assert (found.path, found.load_error) == (tmp_path / "app" / "west.yml", None)


def test_config_without_a_manifest_path_is_a_load_error(tmp_path):
    make_workspace(tmp_path, "app", {"app/west.yml": manifest(self_path="app")})
    (tmp_path / ".west/config").write_text("[manifest]\nfile = west.yml\n")
    found = locate(tmp_path).manifest
    assert found.repository == tmp_path
    assert found.load_error


def test_zephyr_base_environment_is_not_a_fallback(tmp_path, monkeypatch):
    root = t2(tmp_path / "ws")
    monkeypatch.setenv("ZEPHYR_BASE", str(root / "zephyr"))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert locate(elsewhere) is None
