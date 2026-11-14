from tests.workspaces import APPLICATION, make_workspace, manifest, t1, t2, t3, under, zephyr_tree
from zquire.core.topology import find_applications, infer
from zquire.core.workspace import locate


def topology(root):
    return infer(locate(root))


def test_t1_when_the_manifest_repository_is_the_zephyr_tree(tmp_path):
    result = topology(t1(tmp_path))
    assert (result.kind, result.candidates) == ("T1", [])
    assert "Kconfig.zephyr" in result.evidence[0]


def test_t1_wins_over_applications_inside_the_zephyr_tree(tmp_path):
    files = {
        "zephyr/west.yml": manifest(self_path="zephyr"),
        **under("zephyr", zephyr_tree()),
        **under("zephyr/samples/hello", APPLICATION),
    }
    assert topology(make_workspace(tmp_path, "zephyr", files)).kind == "T1"


def test_version_without_kconfig_zephyr_is_not_a_zephyr_tree(tmp_path):
    files = {
        "zephyr/west.yml": manifest(self_path="zephyr"),
        "zephyr/VERSION": zephyr_tree()["VERSION"],
    }
    assert topology(make_workspace(tmp_path, "zephyr", files)).kind == "T3"


def test_t2_when_the_manifest_repository_holds_an_application(tmp_path):
    result = topology(t2(tmp_path))
    assert result.kind == "T2"
    assert result.candidates == [tmp_path / "application"]
    assert result.evidence == ["application holds 1 Zephyr application(s), e.g. application"]


def test_t2_finds_nested_applications_in_order(tmp_path):
    root = t2(tmp_path, "application/apps/b", "application/apps/a")
    assert topology(root).candidates == [
        tmp_path / "application/apps/a",
        tmp_path / "application/apps/b",
    ]


def test_t3_when_the_manifest_repository_holds_neither(tmp_path):
    result = topology(t3(tmp_path, "app1", "app2"))
    assert result.kind == "T3"
    assert result.candidates == [tmp_path / "app1", tmp_path / "app2"]


def test_t3_ignores_applications_inside_zephyr(tmp_path):
    root = t3(tmp_path)
    (root / "zephyr/samples/hello").mkdir(parents=True)
    (root / "zephyr/samples/hello/CMakeLists.txt").write_text(APPLICATION["CMakeLists.txt"])
    assert topology(root).candidates == []


def test_t3_skips_declared_projects_that_are_not_cloned(tmp_path):
    root = t3(tmp_path, "app1")
    text = (root / "manifest-repo/west.yml").read_text()
    (root / "manifest-repo/west.yml").write_text(
        text.replace(
            "  self:",
            "    - name: lib2\n      url: https://example.com/lib2\n      revision: main\n  self:",
        )
    )
    assert topology(root).candidates == [tmp_path / "app1"]


def test_unknown_when_the_manifest_fails_to_load(tmp_path):
    root = make_workspace(
        tmp_path, "app", {"app/west.yml": "manifest: [bad", **under("app", APPLICATION)}
    )
    result = topology(root)
    assert (result.kind, result.candidates) == ("unknown", [])
    assert result.evidence[0].startswith("manifest failed to load: ")
    assert len(result.evidence[0]) > len("manifest failed to load: ")


def test_cmakelists_without_find_package_zephyr_is_not_an_application(tmp_path):
    (tmp_path / "CMakeLists.txt").write_text("project(plain)\n")
    assert find_applications(tmp_path) == []


def test_hidden_directories_are_skipped(tmp_path):
    (tmp_path / ".git/app").mkdir(parents=True)
    (tmp_path / ".git/app/CMakeLists.txt").write_text(APPLICATION["CMakeLists.txt"])
    assert find_applications(tmp_path) == []


def test_undecodable_cmakelists_is_still_scanned(tmp_path):
    (tmp_path / "CMakeLists.txt").write_bytes(b"\xff\xfe" + APPLICATION["CMakeLists.txt"].encode())
    assert find_applications(tmp_path) == [tmp_path]
