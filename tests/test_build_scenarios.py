import pytest
from pytest_bdd import given, parsers, scenario, then, when

from tests.workspaces import build_output, fake_west_build, t3
from zquire.core.context import Context
from zquire.core.diagnostics import EXCERPT_LINES
from zquire.core.workspace import locate
from zquire.tools import TOOLS, invoke

FEATURE = "features/build.feature"


@scenario(FEATURE, "Successful build")
def test_successful_build():
    pass


@scenario(FEATURE, "Compiler error")
def test_compiler_error():
    pass


@scenario(FEATURE, "Kconfig misconfiguration")
def test_kconfig_misconfiguration():
    pass


@scenario(FEATURE, "Devicetree error")
def test_devicetree_error():
    pass


@scenario(FEATURE, "Unrecognised failure")
def test_unrecognised_failure():
    pass


@scenario(FEATURE, "RAM overflow")
def test_ram_overflow():
    pass


@scenario(FEATURE, "Repeated warning")
def test_repeated_warning():
    pass


@pytest.fixture
def root(tmp_path):
    root = fake_west_build(t3(tmp_path / "ws", "app"))
    call(root, "profile_create", name="bench-1", application="app", board="qemu_cortex_m3")
    call(root, "profile_activate", name="bench-1")
    return root


@pytest.fixture
def outcome():
    return {}


def call(root, tool, **arguments):
    return invoke(TOOLS[tool], arguments, Context(locate(root)))


def write(root, path, text):
    (root / "app" / path).parent.mkdir(parents=True, exist_ok=True)
    (root / "app" / path).write_text(text)


@given("an application that compiles cleanly for the active board")
def clean_application(root):
    write(root, "src/main.c", "int main(void)\n{\n\treturn 0;\n}\n")
    build_output(root, "success")


@given(parsers.parse('"{path}" line {line:d} calls an undeclared function "{name}"'))
def undeclared_function(root, path, line, name):
    write(root, path, "\n" * (line - 1) + f"int main(void) {{ {name}(); return 0; }}\n")
    build_output(root, "compiler")


@given("prj.conf sets a symbol whose dependencies are not met")
def unmet_dependency(root):
    write(root, "prj.conf", "CONFIG_UART_NRFX=y\n")
    build_output(root, "kconfig")


@given("an overlay references a node label that does not exist")
def undefined_label(root):
    write(root, "app.overlay", '/ {\n};\n\n&nosuchlabel {\n\tstatus = "okay";\n};\n')
    build_output(root, "devicetree")


@given("a build fails with output zquire cannot parse")
def unparsable_failure(root):
    build_output(root, "unknown")


@given(parsers.parse("an application whose static RAM exceeds the board's RAM by {over:d} bytes"))
def ram_overflow(root, over):
    assert over == 2048, "the recorded log overflows by 2048 bytes"
    build_output(root, "overflow")


@given(parsers.parse("a header produces the same warning in {count:d} source files"))
def repeated_warning(root, count):
    assert count == 12, "the recorded log repeats its warning 12 times"
    build_output(root, "repeat")


@when('the agent calls "build"')
def agent_builds(root, outcome):
    outcome["result"] = call(root, "build")


def with_category(outcome, category):
    return [d for d in outcome["result"]["diagnostics"] if d["category"] == category]


@then(parsers.parse('the status is "{status}"'))
def status_is(outcome, status):
    assert outcome["result"]["status"] == status


@then("the result contains flash and RAM usage per region")
def memory_per_region(outcome):
    regions = {r["region"]: r for r in outcome["result"]["memory"]}
    assert {"FLASH", "RAM"} <= regions.keys()
    for region in regions.values():
        assert region["used"] <= region["total"]
        assert region["percent"] == pytest.approx(100 * region["used"] / region["total"], abs=0.01)


@then("the active profile records this as its latest successful build")
def recorded_as_latest_success(root):
    active = next(p for p in call(root, "profile_list")["profiles"] if p["active"])
    assert active["last_build"]["status"] == "success"


@then(
    parsers.re(
        r'there is a diagnostic with category "(?P<category>[^"]+)"'
        r'(?: and severity "(?P<severity>[^"]+)")?'
    )
)
def diagnostic_with(outcome, category, severity):
    found = [d for d in with_category(outcome, category) if severity in (None, d["severity"])]
    assert found
    outcome["diagnostic"] = found[0]


@then(parsers.parse('that diagnostic points to "{path}" line {line:d}'))
def points_to(outcome, path, line):
    assert (outcome["diagnostic"]["file"], outcome["diagnostic"]["line"]) == (f"app/{path}", line)


@then("its message names the symbol and its unmet dependency")
def names_symbol_and_dependency(outcome):
    message = outcome["diagnostic"]["message"]
    assert "CONFIG_UART_NRFX" in message
    assert "DT_HAS_NORDIC_NRF_UART_ENABLED" in message


@then("it points to the overlay file and line")
def points_to_overlay(outcome):
    assert (outcome["diagnostic"]["file"], outcome["diagnostic"]["line"]) == (
        "app/app.overlay",
        4,
    )


@then(parsers.parse('there is exactly one diagnostic with category "{category}"'))
def exactly_one(outcome, category):
    (outcome["diagnostic"],) = with_category(outcome, category)


@then(parsers.parse("it includes a log excerpt of at most {lines:d} lines"))
def log_excerpt(outcome, lines):
    assert lines == EXCERPT_LINES
    assert 0 < len(outcome["diagnostic"]["log_excerpt"].splitlines()) <= lines


@then("the result contains the path to the full build log")
def full_log(root, outcome):
    log = root / outcome["result"]["log_path"]
    assert log.read_text() == (root / "fake-build" / "output.log").read_text()


@then(parsers.parse('it names region "{region}" and overflow {over:d} bytes'))
def names_region(outcome, region, over):
    assert (outcome["diagnostic"]["region"], outcome["diagnostic"]["overflow_bytes"]) == (
        region,
        over,
    )
    assert region in outcome["diagnostic"]["message"]


@then(parsers.parse("that warning appears once with repeat count {count:d}"))
def appears_once(outcome, count):
    (warning,) = [d for d in outcome["result"]["diagnostics"] if d["severity"] == "warning"]
    assert warning["count"] == count
