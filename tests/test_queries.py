import pytest

from tests.workspaces import query_build, t3
from zquire.core.context import Context
from zquire.core.workspace import locate
from zquire.errors import ZquireError
from zquire.tools import TOOLS, invoke

KCONFIG = """
config GPIO
	bool "GPIO drivers"

config I2C
	bool "I2C drivers"

config FPU
	bool "FPU"

config I2C_NRFX
	bool "nRF I2C driver"
	depends on SOC_NRF && I2C && GPIO

menu "Statistics"
	depends on FPU

if GPIO
config STATS
	bool "Statistics"
	depends on I2C
endif

endmenu

config SHARED
	bool "Defined twice"
	depends on I2C

config SHARED
	bool
	depends on FPU || SOC_NRF

config SOC_NRF
	bool

config SPEED
	int "Speed"
	default 100

config NAME
	string "Name"

config ADDRESS
	hex "Address"
	default 0x40

config HIDDEN
	bool
"""

CONFIG = """\
CONFIG_GPIO=y
# CONFIG_I2C is not set
# CONFIG_FPU is not set
CONFIG_SPEED=250
CONFIG_NAME="bench"
CONFIG_ADDRESS=0x40
"""


@pytest.fixture
def root(tmp_path):
    root = t3(tmp_path / "ws", "app")
    for name in ("one", "two"):
        call(root, "profile_create", name=name, application="app", board="b")
    call(root, "profile_activate", name="one")
    return root


def call(root, tool, **arguments):
    return invoke(TOOLS[tool], arguments, Context(locate(root)))


def built(root, profile="one", **files):
    query_build(
        root, root / "app" / "build" / profile, **{"kconfig": KCONFIG, "config": CONFIG, **files}
    )
    return root


def symbol(root, name, **arguments):
    result = call(root, "kconfig_symbol", symbol=name, **arguments)
    return {key: result[key] for key in ("value", "set", "unmet_dependencies")}


def fails(root, tool, **arguments):
    with pytest.raises(ZquireError) as raised:
        call(root, tool, **arguments)
    assert raised.value.message and raised.value.hint
    return raised.value


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("GPIO", ("y", True)),
        ("I2C", ("n", False)),
        ("SPEED", ("250", True)),
        ("NAME", ("bench", True)),
        ("ADDRESS", ("0x40", True)),
        ("HIDDEN", ("n", False)),
    ],
    ids=["bool-on", "bool-not-set", "int", "string", "hex", "invisible"],
)
def test_symbol_value_and_whether_set(root, name, expected):
    built(root)
    result = symbol(root, name)
    assert (result["value"], result["set"], result["unmet_dependencies"]) == (*expected, [])


def test_result_names_the_profile_symbol_and_type(root):
    built(root)
    result = call(root, "kconfig_symbol", symbol="SPEED")
    assert (result["profile"], result["name"], result["type"]) == ("one", "SPEED", "int")


def test_config_prefix_is_optional(root):
    built(root)
    assert symbol(root, "CONFIG_GPIO") == symbol(root, "GPIO")
    assert call(root, "kconfig_symbol", symbol="CONFIG_GPIO")["name"] == "GPIO"


def test_unmet_dependencies_leave_out_the_met_ones(root):
    built(root)
    assert symbol(root, "I2C_NRFX")["unmet_dependencies"] == ["SOC_NRF", "I2C"]


def test_unmet_dependencies_include_enclosing_menus_and_ifs(root):
    built(root, config="# CONFIG_GPIO is not set\n")
    assert symbol(root, "STATS")["unmet_dependencies"] == ["I2C", "GPIO", "FPU"]


def test_no_unmet_dependencies_when_one_definition_is_met(root):
    built(root, config="CONFIG_I2C=y\n")
    assert symbol(root, "SHARED")["unmet_dependencies"] == []


def test_unmet_dependencies_of_every_definition(root):
    built(root)
    assert symbol(root, "SHARED")["unmet_dependencies"] == ["I2C", "FPU || SOC_NRF"]


def test_named_profile(root):
    built(root)
    built(root, profile="two", config="CONFIG_SPEED=9\n")
    assert symbol(root, "SPEED", profile="two")["value"] == "9"
    assert symbol(root, "SPEED")["value"] == "250"


def test_makefile_generator(root):
    built(root, generator="make")
    assert symbol(root, "GPIO")["value"] == "y"


def test_paths_with_spaces_dollars_and_equals(tmp_path):
    root = t3(tmp_path / "my $w=s", "app")
    call(root, "profile_create", name="one", application="app", board="b")
    call(root, "profile_activate", name="one")
    built(root)
    assert symbol(root, "GPIO")["value"] == "y"


def test_kconfig_output_does_not_reach_the_result(root):
    built(root, kconfig="$(info,loading)\n$(warning-if,y,careful)\n" + KCONFIG)
    assert symbol(root, "GPIO")["value"] == "y"


@pytest.mark.parametrize("name", ["NOPE", "SOC_MISSING"], ids=["unknown", "only-referenced"])
def test_symbol_not_found(root, name):
    built(root, kconfig=KCONFIG + "config USES\n\tbool\n\tdepends on SOC_MISSING\n")
    assert fails(root, "kconfig_symbol", symbol=name).code == "SYMBOL_NOT_FOUND"


def test_broken_kconfig_tree(root):
    built(root, kconfig="config BROKEN\n\tbool\n\tdepends on (\n")
    error = fails(root, "kconfig_symbol", symbol="BROKEN")
    assert error.code == "KCONFIG_FAILED"
    assert error.message.endswith("couldn't parse 'depends on (': malformed expression")


def test_no_active_profile(tmp_path):
    root = t3(tmp_path / "ws", "app")
    assert fails(root, "kconfig_symbol", symbol="GPIO").code == "NO_BUILD"
    assert not (root / ".zquire").exists()


def no_build(root, tool, missing, **arguments):
    error = fails(root, tool, **arguments)
    assert error.code == "NO_BUILD"
    assert f"profile 'one' has no {missing}" in error.message


def test_profile_never_built(root):
    no_build(root, "kconfig_symbol", "zephyr/.config", symbol="GPIO")


def test_build_without_menuconfig_target(root):
    built(root)
    (root / "app" / "build" / "one" / "build.ninja").write_text("rule phony\n")
    no_build(root, "kconfig_symbol", "menuconfig target", symbol="GPIO")


def test_unknown_profile(root):
    assert fails(root, "kconfig_symbol", symbol="GPIO", profile="nope").code == "PROFILE_NOT_FOUND"


def test_build_files_that_are_not_utf8(root):
    built(root)
    ninja = root / "app" / "build" / "one" / "build.ninja"
    ninja.write_bytes(b"# \xff\n" + ninja.read_bytes())
    assert symbol(root, "GPIO")["value"] == "y"
