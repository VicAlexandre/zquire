import pytest

from tests.workspaces import fake_west_build, t3
from zquire.core.build import LOG_CHARACTERS, LOG_LINES
from zquire.core.context import Context
from zquire.core.workspace import locate
from zquire.errors import ZquireError
from zquire.tools import TOOLS, invoke


@pytest.fixture
def root(tmp_path):
    root = fake_west_build(t3(tmp_path / "ws", "app"))
    for name in ("one", "two"):
        call(root, "profile_create", name=name, application="app", board="b")
    call(root, "profile_activate", name="one")
    return root


def call(root, tool, **arguments):
    return invoke(TOOLS[tool], arguments, Context(locate(root)))


def fails(root, **arguments):
    with pytest.raises(ZquireError) as raised:
        call(root, "build_log", **arguments)
    assert raised.value.message and raised.value.hint
    return raised.value.code


def built(root, lines, profile="one"):
    (root / "fake-build" / "output.log").write_text("".join(f"{line}\n" for line in lines))
    call(root, "build", profile=profile)


def numbered(count):
    return [f"line {n}" for n in range(1, count + 1)]


def window(result):
    return result["first_line"], result["last_line"], result["text"].splitlines()


def test_build_log_tool_is_registered():
    assert "build_log" in TOOLS


def test_short_log_is_returned_whole(root):
    built(root, numbered(3))
    result = call(root, "build_log")
    assert window(result) == (1, 3, numbered(3))
    assert (result["profile"], result["total_lines"], result["truncated"]) == ("one", 3, False)
    assert result["log_path"] == ".zquire/logs/one-build.log"


@pytest.mark.parametrize("total", [LOG_LINES - 1, LOG_LINES, LOG_LINES + 1])
def test_default_is_the_last_lines(root, total):
    built(root, numbered(total))
    first = max(total - LOG_LINES + 1, 1)
    assert window(call(root, "build_log")) == (first, total, numbered(total)[first - 1 :])


def test_line_count_sets_the_tail_length(root):
    built(root, numbered(10))
    assert window(call(root, "build_log", line_count=1)) == (10, 10, ["line 10"])


@pytest.mark.parametrize(
    ("start_line", "line_count", "expected"),
    [(1, 2, (1, 2)), (4, 3, (4, 6)), (9, 5, (9, 10)), (10, 1, (10, 10))],
    ids=["from-start", "middle", "past-the-end", "last-line"],
)
def test_start_line_reads_forward(root, start_line, line_count, expected):
    built(root, numbered(10))
    result = call(root, "build_log", start_line=start_line, line_count=line_count)
    first, last = expected
    assert window(result) == (first, last, numbered(10)[first - 1 : last])


def test_start_beyond_the_log_is_empty(root):
    built(root, numbered(10))
    assert window(call(root, "build_log", start_line=11)) == (11, 10, [])


def test_lines_beyond_the_size_budget_are_left_out(root):
    line = "x" * 999
    built(root, [line] * 40)
    result = call(root, "build_log", start_line=1)
    assert (result["last_line"], result["truncated"]) == (LOG_CHARACTERS // 1000, True)
    assert len(result["text"]) < LOG_CHARACTERS


def test_log_exactly_at_the_budget_is_whole(root):
    lines = ["x" * 999] * (LOG_CHARACTERS // 1000)
    built(root, lines)
    result = call(root, "build_log")
    assert (result["last_line"], result["truncated"]) == (len(lines), False)


def test_overlong_single_line_is_cut(root):
    built(root, ["y" * (LOG_CHARACTERS * 2)])
    result = call(root, "build_log")
    assert (window(result)[:2], result["truncated"]) == ((1, 1), True)
    assert result["text"] == "y" * LOG_CHARACTERS


def test_named_profile(root):
    built(root, ["for two"], profile="two")
    assert call(root, "build_log", profile="two")["text"] == "for two"


def test_unknown_profile(root):
    assert fails(root, profile="nope") == "PROFILE_NOT_FOUND"


def test_no_active_profile(tmp_path):
    root = fake_west_build(t3(tmp_path / "ws", "app"))
    assert fails(root) == "NO_PROFILE"
    assert not (root / ".zquire").exists()


def test_profile_never_built(root):
    assert fails(root, profile="two") == "NO_BUILD_LOG"


@pytest.mark.parametrize("arguments", [{"start_line": 0}, {"line_count": 0}])
def test_lines_are_counted_from_one(root, arguments):
    with pytest.raises(ZquireError) as raised:
        call(root, "build_log", **arguments)
    assert raised.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    ("count", "truncated"), [(LOG_CHARACTERS // 2, False), (LOG_CHARACTERS // 2 + 1, True)]
)
def test_budget_counts_each_line_and_its_newline(root, count, truncated):
    built(root, ["x"] * count)
    result = call(root, "build_log", start_line=1, line_count=count)
    assert (result["last_line"], result["truncated"]) == (LOG_CHARACTERS // 2, truncated)


def test_log_that_is_not_utf8_is_still_read(root):
    built(root, [])
    (root / ".zquire" / "logs" / "one-build.log").write_bytes(b"ok\n\xff bad\n")
    assert call(root, "build_log")["text"].splitlines()[0] == "ok"
