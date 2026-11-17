import re
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from zquire.core.serial_buffer import DEFAULT_CAPACITY, Buffer, Lines, decode, event


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


def containing(text):
    return lambda entry: text in entry["text"]


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
        "event": None,
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
    result = filled("x <err> 1", "ok", "<err> 2", "ok").read(0, 200, containing("<err>"))
    assert (texts(result["lines"]), result["next_cursor"]) == (["x <err> 1", "<err> 2"], 4)


def test_filter_with_limit_stops_after_the_last_match_returned():
    buffer = filled("e1", "ok", "e2", "ok", "e3")
    result = buffer.read(0, 2, containing("e"))
    assert (texts(result["lines"]), result["next_cursor"]) == (["e1", "e2"], 3)


def test_filter_matching_nothing():
    assert filled("a", "b").read(0, 200, containing("z")) == {
        "lines": [],
        "next_cursor": 2,
        "truncated": False,
    }


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
        "truncated": False,
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


@pytest.mark.parametrize(("pending", "expected"), [(b"", []), (b"uart:~$ ", [b"uart:~$ "])])
def test_flush_returns_the_unfinished_line_once(pending, expected):
    lines = Lines()
    lines.feed(b"done\n" + pending)
    assert lines.flush() == expected
    assert lines.flush() == []
    assert lines.feed(b"next\n") == [b"next"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("*** Booting Zephyr OS build v4.4.0 ***", "boot"),
        ("[00:00:00.010,000] <err> os: >>> ZEPHYR FATAL ERROR 19: Unknown error", "fatal_error"),
        ("E: >>> ZEPHYR FATAL ERROR 0: CPU exception on CPU 0", "fatal_error"),
        (">>> ZEPHYR FATAL ERROR 4: Kernel panic on CPU 0", "kernel_panic"),
        ("ASSERTION FAIL [x == 1] @ src/main.c:12", "assertion"),
        ("ZEPHYR FATAL ERROR", "fatal_error"),
        ("*** Booting MCUboot v2.1.0 ***", None),
        ("Kernel panic", None),
        ("ASSERTION FAIL", None),
        ("uart:~$ ", None),
    ],
)
def test_events(text, expected):
    assert event(text) == expected
    assert Buffer().add("rx", text)["event"] == expected


@pytest.mark.parametrize("kind", ["tx", "flash", "disconnected"])
def test_only_received_lines_have_events(kind):
    assert Buffer().add(kind, "*** Booting Zephyr OS build v4.4.0 ***")["event"] is None


def capped(count, capacity):
    buffer = Buffer(capacity)
    for n in range(1, count + 1):
        buffer.add("rx", f"line {n}")
    return buffer


def test_default_capacity():
    assert DEFAULT_CAPACITY == 50_000
    assert len(capped(50_001, DEFAULT_CAPACITY).read(0, 60_000)["lines"]) == 50_000


@pytest.mark.parametrize(("count", "first"), [(2, 1), (3, 1), (4, 2), (7, 5)])
def test_oldest_entries_are_dropped(count, first):
    buffer = capped(count, 3)
    result = buffer.read(0, 200)
    assert [e["cursor"] for e in result["lines"]] == list(range(first, count + 1))
    assert buffer.last_cursor() == count


@pytest.mark.parametrize(
    ("cursor", "truncated", "first"),
    [
        (0, True, 1001),
        (10, True, 1001),
        (999, True, 1001),
        (1000, False, 1001),
        (1050, False, 1051),
    ],
)
def test_reading_from_before_the_buffer(cursor, truncated, first):
    result = capped(1100, 100).read(cursor, 1)
    assert (result["truncated"], result["lines"][0]["cursor"], result["next_cursor"]) == (
        truncated,
        first,
        first,
    )


def test_reading_past_the_end_of_a_full_buffer():
    assert capped(5, 3).read(5, 200) == {"lines": [], "next_cursor": 5, "truncated": False}


@pytest.mark.parametrize(("cursor", "truncated"), [(1, True), (2, False)])
def test_wait_from_before_the_buffer(cursor, truncated):
    buffer = capped(5, 3)
    assert buffer.wait(re.compile("line 5"), cursor, 0, 200)["truncated"] is truncated
    assert buffer.wait(re.compile("never"), cursor, 0, 200)["truncated"] is truncated


def test_wait_notices_lines_dropped_while_waiting():
    buffer = capped(1, 2)

    def flood():
        for n in range(5):
            buffer.add("rx", f"flood {n}")

    flooder = threading.Timer(0.1, flood)
    flooder.start()
    result = buffer.wait(re.compile("never"), 1, 0.4, 200)
    flooder.join()
    assert result["truncated"] is True
    assert texts(result["lines"])[-1] == "flood 4"


def test_events_read_through_a_filter():
    buffer = filled("boot", "*** Booting Zephyr OS ***", "x", "ASSERTION FAIL [a] @ c:1")
    result = buffer.read(0, 200, lambda entry: entry["event"] is not None)
    assert [e["cursor"] for e in result["lines"]] == [2, 4]
