import jsonschema
import pytest

from tests.conftest import NO_WORKSPACE
from tests.workspaces import t1, t2, t3
from zquire.core.context import Context
from zquire.core.workspace import locate
from zquire.errors import ZquireError
from zquire.tools import TOOLS, invoke


def status_of(root):
    return invoke(TOOLS["status"], {}, Context(locate(root)))


def test_degraded_status_has_no_workspace():
    result = invoke(TOOLS["status"], {}, NO_WORKSPACE)
    assert (result["workspace"], result["warnings"]) == (None, [])


def test_tools_other_than_status_fail_without_a_workspace(fake_tools):
    with pytest.raises(ZquireError) as raised:
        invoke(fake_tools["workspace_root"], {}, NO_WORKSPACE)
    assert raised.value.code == "NO_WORKSPACE"
    assert "--workspace" in raised.value.hint and "west init" in raised.value.hint


def test_no_workspace_is_reported_before_invalid_arguments(fake_tools):
    with pytest.raises(ZquireError) as raised:
        invoke(fake_tools["workspace_root"], {"bogus": 1}, NO_WORKSPACE)
    assert raised.value.code == "NO_WORKSPACE"


def test_tools_needing_a_workspace_run_with_one(fake_tools, tmp_path):
    context = Context(locate(t2(tmp_path)))
    assert invoke(fake_tools["workspace_root"], {}, context) == {"root": str(tmp_path)}


def test_status_reports_the_workspace(tmp_path):
    workspace = status_of(t2(tmp_path))["workspace"]
    assert workspace == {
        "root": str(tmp_path),
        "manifest_path": str(tmp_path / "application/west.yml"),
        "manifest_repository": str(tmp_path / "application"),
        "zephyr_base": str(tmp_path / "zephyr"),
        "zephyr_version": "4.4.0",
        "topology": "T2",
        "topology_evidence": ["application holds 1 Zephyr application(s), e.g. application"],
        "application_candidates": ["application"],
        "default_application": "application",
        "active_profile": None,
    }


@pytest.mark.parametrize(
    ("make", "args", "candidates", "default"),
    [
        (t1, (), [], None),
        (t2, ("application/a",), ["application/a"], "application/a"),
        (t2, ("application/a", "application/b"), ["application/a", "application/b"], None),
        (t3, ("app1",), ["app1"], "app1"),
        (t3, ("app1", "app2"), ["app1", "app2"], None),
    ],
    ids=["T1-none", "T2-one", "T2-two", "T3-one", "T3-two"],
)
def test_candidates_and_default_application(tmp_path, make, args, candidates, default):
    workspace = status_of(make(tmp_path, *args))["workspace"]
    assert workspace["application_candidates"] == candidates
    assert workspace["default_application"] == default


def test_no_zephyr_gives_null_base_and_version(tmp_path):
    root = t2(tmp_path)
    for name in ("VERSION", "Kconfig.zephyr"):
        (root / "zephyr" / name).unlink()
    workspace = status_of(root)["workspace"]
    assert (workspace["zephyr_base"], workspace["zephyr_version"]) == (None, None)


@pytest.mark.parametrize("as_file", [False, True], ids=["git-dir", "git-file"])
def test_topdir_git_repository_warns_and_continues(tmp_path, as_file):
    root = t2(tmp_path)
    if as_file:
        (root / ".git").write_text("gitdir: elsewhere\n")
    else:
        (root / ".git").mkdir()
    result = status_of(root)
    assert [w["code"] for w in result["warnings"]] == ["unsupported_topology"]
    assert result["workspace"]["topology"] == "T2"


def test_no_warning_without_a_topdir_git_repository(tmp_path):
    assert status_of(t2(tmp_path))["warnings"] == []


@pytest.mark.parametrize("make", [t1, t2, t3], ids=["T1", "T2", "T3"])
def test_status_conforms_to_its_output_schema(tmp_path, make):
    jsonschema.validate(status_of(make(tmp_path)), TOOLS["status"].output_schema)
