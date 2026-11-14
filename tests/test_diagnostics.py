from pathlib import Path

import pytest

from zquire.core.diagnostics import EXCERPT_LINES, diagnostics, memory_usage

LOGS = Path(__file__).parent / "logs"
ROOT = Path("/ws")


def log(name):
    return (LOGS / f"{name}.log").read_text()


def parse(text, failed=True):
    return diagnostics(text, ROOT, failed)


def only(found):
    assert len(found) == 1, found
    return found[0]


def test_clean_build_has_no_diagnostics():
    assert parse(log("success"), failed=False) == []


def test_compiler_error():
    assert only(parse(log("compiler"))) == {
        "severity": "error",
        "category": "compiler",
        "message": "implicit declaration of function 'foo' [-Wimplicit-function-declaration]",
        "file": "app/src/main.c",
        "line": 42,
        "column": 18,
        "hint": "Declare 'foo', or include the header that declares it.",
        "count": 1,
    }


def test_kconfig_unmet_dependency_names_the_symbol_and_dependency():
    found = only(parse(log("kconfig"), failed=False))
    assert (found["category"], found["severity"]) == ("kconfig", "warning")
    assert "CONFIG_UART_NRFX" in found["message"]
    assert (
        "(DT_HAS_NORDIC_NRF_UART_ENABLED || DT_HAS_NORDIC_NRF_UARTE_ENABLED) (=n)"
        in (found["message"])
    )
    assert "CONFIG_UART_NRFX" in found["hint"]


def test_devicetree_error_points_to_the_overlay_and_drops_the_cmake_wrapper():
    found = only(parse(log("devicetree")))
    assert found == {
        "severity": "error",
        "category": "devicetree",
        "message": "parse error: undefined node label 'nosuchlabel'",
        "file": "app/app.overlay",
        "line": 4,
        "column": 1,
        "hint": "Use a node label that exists in the board's devicetree, or define 'nosuchlabel'.",
        "count": 1,
    }


def test_linker_error():
    found = only(parse(log("linker")))
    assert (found["category"], found["file"], found["line"]) == ("linker", "app/src/main.c", 4)
    assert found["message"] == "undefined reference to `bar'"
    assert "bar" in found["hint"]


def test_memory_overflow_names_region_and_bytes():
    found = only(parse(log("overflow")))
    assert found["category"] == "memory_overflow"
    assert (found["region"], found["overflow_bytes"]) == ("RAM", 2048)
    assert "2048" in found["hint"]


def test_cmake_error_joins_its_indented_message():
    found = only(parse(log("board")))
    assert found["category"] == "cmake"
    assert (
        found["message"]
        == "No board named 'no_such_board' found. Run 'west boards' for the full list."
    )
    assert (found["file"], found["line"]) == ("zephyr/cmake/modules/boards.cmake", 265)


def test_cmake_error_in_toolchain_setup_is_a_toolchain_diagnostic():
    found = only(parse(log("toolchain")))
    assert found["category"] == "toolchain"
    assert found["message"] == "Nothing found at GNUARMEMB_TOOLCHAIN_PATH: '/nonexistent'"


def test_warning_repeated_across_translation_units_appears_once_with_its_count():
    found = only(parse(log("repeat"), failed=False))
    assert (found["file"], found["line"], found["count"]) == ("app/src/h.h", 1, 12)


def test_unparsed_failure_is_one_unknown_diagnostic_with_the_log_tail():
    text = log("unknown")
    found = only(parse(text))
    assert (found["category"], found["count"]) == ("unknown", 1)
    assert found["hint"]
    assert found["log_excerpt"] == text.rstrip("\n")


@pytest.mark.parametrize("length", [EXCERPT_LINES - 1, EXCERPT_LINES, EXCERPT_LINES + 1])
def test_log_excerpt_is_the_last_60_lines(length):
    lines = [f"line {n}" for n in range(length)]
    excerpt = only(parse("\n".join(lines)))["log_excerpt"]
    assert excerpt.splitlines() == lines[-EXCERPT_LINES:]


def test_failure_with_only_warnings_adds_an_unknown_diagnostic():
    found = parse("/ws/a.c:1:2: warning: w")
    assert [d["category"] for d in found] == ["compiler", "unknown"]


def test_unparsed_success_has_no_unknown_diagnostic():
    assert parse("gibberish", failed=False) == []


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("/ws/a.c:3:4: fatal error: x.h: No such file", {"severity": "error", "column": 4}),
        ("/ws/a.c:3: warning: no column", {"severity": "warning", "line": 3}),
        ("/ws/app/prj.conf:2: warning: attempt to assign", {"category": "kconfig"}),
        ("/ws/zephyr/Kconfig.zephyr:2: error: e", {"category": "kconfig"}),
        ("/ws/b/x_defconfig:2: error: e", {"category": "kconfig"}),
        ("/ws/app/a.dtsi:2: error: e", {"category": "devicetree"}),
        ("/ws/app/a.overlay:2: error: e", {"category": "devicetree"}),
        ("/ws/app/a.dts:2: error: e", {"category": "devicetree"}),
        ("src/a.c:3:4: error: relative", {"file": "src/a.c"}),
        ("/opt/sdk/include/a.h:3:4: error: outside", {"file": "/opt/sdk/include/a.h"}),
        ("/ws/app/../lib/a.c:3:4: error: dotdot", {"file": "lib/a.c"}),
        ("\x1b[01m\x1b[K/ws/a.c:1:2: error: \x1b[31mcoloured\x1b[m", {"message": "coloured"}),
        ("error: Aborting due to Kconfig warnings", {"category": "kconfig"}),
        ("devicetree error: 'reg' property in <Node /x> has length 4", {"category": "devicetree"}),
        ("/ws/a.c:5:(.text+0x1): multiple definition of `x'", {"category": "linker"}),
        ("CMake Warning (dev) at CMakeLists.txt:3 (project):", {"severity": "warning"}),
        (
            "CMake Error: The source directory does not exist.",
            {"category": "cmake", "message": "The source directory does not exist."},
        ),
        (
            "CMake Error at /ws/zephyr/cmake/FindZephyr-sdk.cmake:1 (message):",
            {"category": "toolchain"},
        ),
    ],
)
def test_line_formats(line, expected):
    found = parse(line, failed=False)
    assert {key: found[0][key] for key in expected} == expected


def test_devicetree_error_without_location_has_no_file():
    found = only(parse("devicetree error: bad thing"))
    assert "file" not in found and "line" not in found


def test_zephyr_sdk_cmake_error_is_toolchain():
    found = only(parse("CMake Error at /ws/x.cmake:1 (message):\n  Could not find Zephyr-sdk\n"))
    assert found["category"] == "toolchain"


def test_cmake_error_message_stops_at_an_unindented_line():
    found = parse("CMake Error at /ws/a.cmake:1 (message):\n  first\n\n  second\n-- next\n")
    assert only(found)["message"] == "first second"


def test_cmake_error_is_kept_when_nothing_else_failed():
    text = "/ws/a.c:1:2: warning: w\nCMake Error at /ws/a.cmake:1 (message):\n  broke\n"
    assert [d["category"] for d in parse(text)] == ["compiler", "cmake"]


def test_kconfig_message_drops_the_documentation_boilerplate():
    text = "warning: something odd. See http://docs.zephyrproject.org/x and more\n\n"
    assert only(parse(text, failed=False))["message"] == "something odd."


def test_consecutive_kconfig_paragraphs():
    text = "x\nwarning: first\nwraps\n\nwarning: second\n\n/ws/a.c:1:2: warning: w\n"
    found = parse(text, failed=False)
    assert [(d["message"], d["count"]) for d in found] == [
        ("first wraps", 1),
        ("second", 1),
        ("w", 1),
    ]


def test_scanning_resumes_after_a_cmake_message():
    text = "x\nCMake Warning at /ws/a.cmake:1 (message):\n  w\n/ws/a.c:1:2: warning: w2\n"
    found = parse(text, failed=False)
    assert [(d["category"], d["count"]) for d in found] == [("cmake", 1), ("compiler", 1)]


def test_different_lines_are_not_merged():
    found = parse(
        "/ws/a.c:1:2: warning: w\n/ws/a.c:2:2: warning: w\n/ws/a.c:1:2: warning: w\n", failed=False
    )
    assert [(d["line"], d["count"]) for d in found] == [(1, 2), (2, 1)]


def test_memory_usage_per_region():
    assert memory_usage(log("success")) == [
        {"region": "FLASH", "used": 10252, "total": 256 * 1024, "percent": 3.91},
        {"region": "RAM", "used": 4176, "total": 64 * 1024, "percent": 6.37},
        {"region": "IDT_LIST", "used": 0, "total": 32 * 1024, "percent": 0.0},
    ]


def test_memory_usage_units():
    table = "Memory region Used Size Region Size %age Used\n  FLASH: 1 MB 2 GB 50.00%\n"
    assert memory_usage(table) == [
        {"region": "FLASH", "used": 1 << 20, "total": 2 << 30, "percent": 50.0}
    ]


def test_memory_usage_keeps_the_last_table_only():
    first = "Memory region\n  RAM: 1 B 2 B 50.00%\n"
    second = "Memory region\n  FLASH: 3 B 4 B 75.00%\nafter\n  RAM: 9 B 9 B 1.00%\n"
    assert [r["region"] for r in memory_usage(first + second)] == ["FLASH"]


def test_memory_rows_before_a_table_are_ignored():
    assert memory_usage("  RAM: 1 B 2 B 50.00%\n") == []


def test_memory_usage_without_a_table():
    assert memory_usage(log("compiler")) == []
