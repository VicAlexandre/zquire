import json
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from tests.conftest import call_mcp
from tests.workspaces import make_workspace, query_build, t1, t2, t3
from zquire.adapters.west import read_manifest
from zquire.core.context import Context
from zquire.core.workspace import locate
from zquire.mcp_server import build_server
from zquire.tools import TOOLS, invoke


@scenario("features/workspace.feature", "Report workspace status")
def test_report_workspace_status():
    pass


@scenario("features/workspace.feature", "No workspace found")
def test_no_workspace_found():
    pass


@scenario("features/workspace.feature", "Explain why a Kconfig symbol is off")
def test_explain_kconfig_symbol():
    pass


@scenario("features/workspace.feature", "Query without a build")
def test_query_without_build():
    pass


@scenario("features/topology.feature", "T1, zephyr is the manifest repository")
def test_t1():
    pass


@scenario("features/topology.feature", "T2, application is the manifest repository")
def test_t2():
    pass


@scenario("features/topology.feature", "T3, forest with several applications")
def test_t3():
    pass


@scenario("features/topology.feature", "Manifest cannot be loaded")
def test_unknown():
    pass


@scenario("features/topology.feature", "Topdir is a git repository")
def test_topdir_git_repository():
    pass


@pytest.fixture
def root(tmp_path):
    return tmp_path / "ws"


@given("zquire is started in a directory with no west workspace above it")
def no_workspace(root):
    root.mkdir()
    assert locate(root) is None


@given("zquire is started inside a west workspace using Zephyr 4.4")
def zephyr_4_4_workspace(root):
    t2(root)


@given(parsers.parse('a workspace created with "west init" from zephyrproject-rtos/zephyr'))
def t1_workspace(root):
    t1(root)


@given(parsers.parse('a workspace whose manifest repository "{name}" contains a Zephyr app'))
def t2_workspace(root, name):
    assert name == "application"
    t2(root)


@given(parsers.parse('"{name}" is a project imported by that manifest'))
def zephyr_is_a_project(root, name):
    assert name in read_manifest(root).projects


@given(parsers.parse('a workspace whose manifest repository "{name}" holds only west.yml'))
def t3_manifest_repository(name):
    assert name == "manifest-repo"


@given(parsers.parse('projects "{first}" and "{second}" each contain a Zephyr app'))
def t3_workspace(root, first, second):
    t3(root, first, second)


@given("a workspace whose west.yml is invalid")
def invalid_manifest(root):
    make_workspace(root, "app", {"app/west.yml": "manifest: [bad"})


@given(parsers.parse('a T2 workspace whose topdir also contains "{name}"'))
def t2_with_git(root, name):
    t2(root)
    (root / name).mkdir()


def profiled(root):
    t3(root, "app")
    context = Context(locate(root))
    invoke(
        TOOLS["profile_create"], {"name": "bench-1", "application": "app", "board": "b"}, context
    )
    invoke(TOOLS["profile_activate"], {"name": "bench-1"}, context)
    return root / "app" / "build" / "bench-1"


@given("an active build where CONFIG_THREAD_RUNTIME_STATS is not set")
def kconfig_build(root):
    kconfig = (
        'config SCHED_THREAD_USAGE\n\tbool "Usage"\n\n'
        'config THREAD_RUNTIME_STATS\n\tbool "Runtime stats"\n\tdepends on SCHED_THREAD_USAGE\n'
    )
    query_build(
        root, profiled(root), kconfig=kconfig, config="# CONFIG_SCHED_THREAD_USAGE is not set\n"
    )


@given("no active build directory")
def no_build(root):
    assert not profiled(root).exists()


@when(parsers.parse('the agent queries Kconfig symbol "{name}"'), target_fixture="result")
def query_kconfig(root, name):
    return agent_calls(root, "kconfig_symbol", {"symbol": name})


@then(parsers.parse('the result shows value "{value}"'))
def shows_value(result, value):
    assert result["value"] == value


@then("the result lists the symbol's unmet dependencies, if any")
def lists_unmet(result):
    assert result["unmet_dependencies"] == ["SCHED_THREAD_USAGE"]


@when(parsers.parse('the agent calls "{tool}"'), target_fixture="result")
def agent_calls(root, tool, arguments=None):
    result = call_mcp(build_server(Context(locate(root))), tool, arguments)
    if result.is_error:
        return {"error": json.loads(result.content[0].text)}
    return result.structured_content


@then(parsers.parse('the call fails with error "{code}"'))
def fails_with(result, code):
    assert result["error"]["code"] == code


@then(parsers.parse('the error hint mentions "{text}"'))
def hint_mentions(result, text):
    assert text in result["error"]["hint"]


@then("the result contains the workspace root")
def contains_root(result, root):
    assert result["workspace"]["root"] == str(root)


@then(parsers.parse('the result contains zephyr_version "{version}"'))
def contains_zephyr_version(result, version):
    assert result["workspace"]["zephyr_version"] == version


@then("the result contains the manifest path")
def contains_manifest_path(result, root):
    assert result["workspace"]["manifest_path"] == str(root / "application" / "west.yml")


@then(parsers.re(r'the topology is (?:still )?"(?P<kind>[^"]+)"'))
def topology_is(result, kind):
    assert result["workspace"]["topology"] == kind


@then(parsers.parse('the manifest repository path ends with "{suffix}"'))
def manifest_repository_ends_with(result, suffix):
    assert Path(result["workspace"]["manifest_repository"]).name == suffix


@then(parsers.parse('the evidence mentions "{text}"'))
def evidence_mentions(result, text):
    assert any(text in line for line in result["workspace"]["topology_evidence"])


@then(parsers.parse('the default application is "{name}"'))
def default_application_is(result, name):
    assert result["workspace"]["default_application"] == name


@then(parsers.parse('the application candidates are "{first}" and "{second}"'))
def candidates_are(result, first, second):
    assert result["workspace"]["application_candidates"] == [first, second]


@then("no default application is set")
def no_default_application(result):
    assert result["workspace"]["default_application"] is None


@then("the evidence includes west's error message")
def evidence_includes_west_error(result, root):
    error = read_manifest(root).load_error
    assert any(error in line for line in result["workspace"]["topology_evidence"])


@then(parsers.parse('the result contains an "{code}" warning'))
def contains_warning(result, code):
    assert code in [warning["code"] for warning in result["warnings"]]
