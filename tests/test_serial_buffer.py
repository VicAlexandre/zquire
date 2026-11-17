import re
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from zquire.core.serial_buffer import Buffer, Lines, decode


@pytest.mark.parametrize(
    ("chunks", "expected"),
    [
        ([b""], []),
        ([b"no newline yet"], []),
        ([b"one\n"], [b"one"]),
        ([b"one\ntwo\nthr"], [b"one", b"two"]),
        ([b"sp", b"lit\n"], [b"split"]),
        ([b"\n\n"], [b"", b""]),
        ([b"a\r\n", b"b\r", b"\n"], [b"a\r", b"b\r"]),
    ],
)
def test_lines(chunks, expected):
    lines = Lines()
    assert [line for chunk in chunks for line in lines.feed(chunk)] == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"plain", ("plain", False)),
        (b"plain\r", ("plain", False)),
        (b"two\r\r", ("two\r", False)),
        (b"mid\rdle", ("mid\rdle", False)),
        ("µs".encode(), ("µs", False)),
        (b"bad \xff\xfe\r", ("bad \ufffd\ufffd", True)),
        (b"\xe2\x82", ("\ufffd", True)),
    ],
)
def test_decode(raw, expected):
    assert decode(raw) == expected


def filled(*texts, kind="rx"):
    buffer = Buffer()
    for text in texts:
        buffer.add(kind, text)
    return buffer


def texts(entries):
    return [entry["text"] for entry in entries]


def test_entries_are_numbered_from_one():
    buffer = Buffer()
    assert buffer.last_cursor() == 0
    assert [buffer.add("rx", t)["cursor"] for t in "abc"] == [1, 2, 3]
    assert buffer.last_cursor() == 3


def test_entry():
    entry = Buffer().add("tx", "hi")
    assert {k: v for k, v in entry.items() if k != "time"} == {
        "cursor": 1,
        "kind": "tx",
        "text": "hi",
        "invalid_utf8": False,
    }
    captured = datetime.fromisoformat(entry["time"])
    assert captured.utcoffset() == timedelta(0)
    assert timedelta(0) <= datetime.now(timezone.utc) - captured < timedelta(seconds=5)
    assert re.fullmatch(r".*T\d\d:\d\d:\d\d\.\d{3}\+00:00", entry["time"])


def test_invalid_utf8_flag():
    assert Buffer().add("rx", "\ufffd", True)["invalid_utf8"] is True


@pytest.mark.parametrize(
    ("cursor", "expected", "next_cursor"),
    [(0, ["a", "b", "c"], 3), (1, ["b", "c"], 3), (3, [], 3), (7, [], 7)],
)
def test_read_after_cursor(cursor, expected, next_cursor):
    result = filled("a", "b", "c").read(cursor, 200)
    assert (texts(result["lines"]), result["next_cursor"]) == (expected, next_cursor)


@pytest.mark.parametrize(
    ("limit", "expected", "next_cursor"),
    [(2, ["a", "b"], 2), (3, ["a", "b", "c"], 3), (4, ["a", "b", "c"], 3)],
)
def test_read_limit(limit, expected, next_cursor):
    result = filled("a", "b", "c").read(0, limit)
    assert (texts(result["lines"]), result["next_cursor"]) == (expected, next_cursor)


def test_filter_searches_anywhere_in_the_line_and_advances_past_the_rest():
    result = filled("x <err> 1", "ok", "<err> 2", "ok").read(0, 200, re.compile("<err>"))
    assert (texts(result["lines"]), result["next_cursor"]) == (["x <err> 1", "<err> 2"], 4)


def test_filter_with_limit_stops_after_the_last_match_returned():
    buffer = filled("e1", "ok", "e2", "ok", "e3")
    result = buffer.read(0, 2, re.compile("e"))
    assert (texts(result["lines"]), result["next_cursor"]) == (["e1", "e2"], 3)


def test_filter_matching_nothing():
    assert filled("a", "b").read(0, 200, re.compile("z")) == {"lines": [], "next_cursor": 2}


def test_wait_finds_a_line_already_captured_after_the_cursor():
    result = filled("old ready", "x", "new ready").wait(re.compile("ready"), 1, 5, 200)
    assert (result["status"], result["line"]["cursor"], result["next_cursor"]) == (
        "matched",
        3,
        3,
    )
    assert result["lines"] == []


def test_wait_ignores_sent_text():
    buffer = filled("ready", kind="tx")
    buffer.add("rx", "ready too")
    assert buffer.wait(re.compile("ready"), 0, 5, 200)["line"]["cursor"] == 2


def test_wait_for_a_line_still_to_come():
    buffer = filled("boot")
    adder = threading.Timer(0.2, buffer.add, ["rx", "app ready"])
    adder.start()
    started = time.monotonic()
    result = buffer.wait(re.compile("ready"), 1, 5, 200)
    adder.join()
    assert time.monotonic() - started < 2
    assert (result["status"], texts([result["line"]])) == ("matched", ["app ready"])


def test_wait_times_out_with_the_lines_seen():
    buffer = filled("before")
    adder = threading.Timer(0.05, buffer.add, ["rx", "during"])
    adder.start()
    started = time.monotonic()
    result = buffer.wait(re.compile("ready"), 1, 0.3, 200)
    adder.join()
    assert time.monotonic() - started >= 0.3
    assert result == {
        "status": "timeout",
        "line": None,
        "lines": result["lines"],
        "next_cursor": 2,
    }
    assert texts(result["lines"]) == ["during"]


def test_zero_timeout_checks_once():
    assert filled("ready").wait(re.compile("ready"), 0, 0, 200)["status"] == "matched"
    assert filled("no").wait(re.compile("ready"), 0, 0, 200)["status"] == "timeout"


@pytest.mark.parametrize(
    ("limit", "expected", "next_cursor"),
    [(1, ["a"], 1), (2, ["a", "b"], 2), (3, ["a", "b", "c"], 3), (4, ["a", "b", "c"], 3)],
)
def test_timeout_lines_are_limited(limit, expected, next_cursor):
    result = filled("a", "b", "c").wait(re.compile("ready"), 0, 0, limit)
    assert (texts(result["lines"]), result["next_cursor"]) == (expected, next_cursor)


def test_close_ends_a_wait():
    buffer = filled()
    closer = threading.Timer(0.1, buffer.close)
    closer.start()
    started = time.monotonic()
    result = buffer.wait(re.compile("ready"), 0, 10, 200)
    closer.join()
    assert time.monotonic() - started < 5
    assert (result["status"], result["line"]) == ("closed", None)


def test_wait_on_a_closed_buffer_still_finds_a_match():
    buffer = filled("ready")
    buffer.close()
    assert buffer.wait(re.compile("ready"), 0, 10, 200)["status"] == "matched"
