import codecs
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from tests.serial_device import Device, captured
from tests.workspaces import fake_west_build, t3
from zquire.core.context import Context
from zquire.core.workspace import locate
from zquire.tools import TOOLS, invoke

FEATURE = "features/serial.feature"


@scenario(FEATURE, "Read new output since a cursor")
def test_read_new_output_since_a_cursor():
    pass


@scenario(FEATURE, "Invalid UTF-8 from the device")
def test_invalid_utf8_from_the_device():
    pass


@scenario(FEATURE, "Filtered read advances the cursor")
def test_filtered_read_advances_the_cursor():
    pass


@scenario(FEATURE, "Wait for a pattern")
def test_wait_for_a_pattern():
    pass


@scenario(FEATURE, "Wait times out")
def test_wait_times_out():
    pass


@scenario(FEATURE, "Send a shell command")
def test_send_a_shell_command():
    pass


@scenario(FEATURE, "Board unplugged")
def test_board_unplugged():
    pass


@scenario(FEATURE, "Cursor older than the buffer")
def test_cursor_older_than_the_buffer():
    pass


@scenario(FEATURE, "Detect a fatal error")
def test_detect_a_fatal_error():
    pass


FATAL_ERROR_DUMP = [
    "[00:00:00.010,000] <err> os: ***** MPU FAULT *****",
    "[00:00:00.010,000] <err> os:   Data Access Violation",
    "[00:00:00.010,000] <err> os:   MMFAR Address: 0x0",
    "[00:00:00.010,000] <err> os: r0/a1:  0x00000000  r1/a2:  0x00000001  r2/a3:  0x00000000",
    "[00:00:00.010,000] <err> os: Faulting instruction address (r15/pc): 0x000002d6",
    "[00:00:00.010,000] <err> os: >>> ZEPHYR FATAL ERROR 19: Unknown error on CPU 0",
    "[00:00:00.010,000] <err> os: Current thread: 0x20000578 (main)",
    "[00:00:00.120,000] <err> os: Halting system",
]


@pytest.fixture
def outcome():
    return {}


@pytest.fixture
def root(tmp_path):
    root = fake_west_build(t3(tmp_path / "ws", "app"))
    (root / "app" / "src").mkdir()
    (root / "app" / "src" / "main.c").write_text("int main(void) { return 0; }\n")
    return root


@pytest.fixture
def call(root):
    context = Context(locate(root))
    call = lambda tool, **arguments: invoke(TOOLS[tool], arguments, context)  # noqa: E731
    yield call
    call("serial_close")


@pytest.fixture
def console(tmp_path, device):
    """The board's port as USB names it: a link that re-enumerating points elsewhere."""
    link = tmp_path / "console"
    link.symlink_to(device.port)
    return link


@pytest.fixture
def replugged():
    """The device the console comes back as after it re-enumerates."""
    device = Device()
    yield device
    device.close()


@given("a serial capture is open")
def capture_open(call, console):
    call("serial_open", port=str(console))


@given(parsers.parse("the buffer has dropped lines up to cursor {dropped:d}"))
def buffer_dropped(call, console, device, dropped):
    call("serial_open", port=str(console), buffer_lines=100)
    device.print("".join(f"line {n}\n" for n in range(1, dropped + 101)))
    captured(call, dropped + 100)


@given(parsers.parse("the device has printed {count:d} lines"))
def device_printed(device, call, count):
    device.print("".join(f"line {n}\r\n" for n in range(1, count + 1)))
    captured(call, count)


@given(parsers.parse('the buffer holds {count:d} lines, {matching:d} containing "{text}"'))
def buffer_holds(device, call, console, count, matching, text):
    call("serial_open", port=str(console))
    marked = set(range(count // (matching + 1), count, count // (matching + 1)))
    assert len(marked) == matching
    device.print(
        "".join(
            f"[00:00:{n:02}.000,000] {text if n in marked else '<inf>'} app: event {n}\r\n"
            for n in range(count)
        )
    )
    captured(call, count)


@when(parsers.parse("the device prints a line containing the bytes 0xFF 0xFE"))
def device_prints_invalid(device, call, outcome):
    device.print(b"bad \xff\xfe bytes\r\n")
    captured(call, 1)
    outcome["line"] = call("serial_read")["lines"][0]


@when(
    parsers.re(
        r'the agent calls "serial_read" with cursor (?P<cursor>\d+)( and filter "(?P<filter>.*)")?'
    )
)
def agent_reads(call, outcome, cursor, filter):
    arguments = {"cursor": int(cursor)}
    if filter is not None:
        arguments["filter"] = filter
    outcome["result"] = call("serial_read", **arguments)


@when(parsers.parse('the agent calls "serial_wait" for "{pattern}" with timeout {timeout:d} s'))
def agent_waits(outcome, pattern, timeout):
    outcome["wait"] = {"pattern": pattern, "timeout_s": timeout}


@when(parsers.parse('the device prints "{text}" after {delay:d} s'))
def device_prints_later(device, call, outcome, text, delay):
    printer = threading.Timer(delay, device.print, [f"{text}\r\n"])
    printer.start()
    outcome["result"] = call("serial_wait", **outcome["wait"])
    printer.join()


@when(parsers.parse("the device prints nothing matching within {delay:d} s"))
def device_prints_nothing(device, call, outcome, delay):
    printer = threading.Timer(delay / 4, device.print, ["booting\r\n"])
    printer.start()
    outcome["result"] = call("serial_wait", **outcome["wait"])
    printer.join()


@when(parsers.parse('the agent calls "serial_write" with "{text}"'))
def agent_writes(call, outcome, text):
    outcome["text"] = text
    outcome["result"] = call("serial_write", text=text)


@then(parsers.parse("{count:d} lines are returned"))
def lines_returned(outcome, count):
    assert len(outcome["result"]["lines"]) == count


@then(parsers.parse("the next cursor is {cursor:d}"))
def next_cursor_is(outcome, cursor):
    assert outcome["result"]["next_cursor"] == cursor


@then("the line is stored with U+FFFD in place of the invalid bytes")
def replaced(outcome):
    assert outcome["line"]["text"] == "bad �� bytes"


@then("the line is flagged as containing invalid UTF-8")
def flagged(outcome):
    assert outcome["line"]["invalid_utf8"] is True


@then("the line has a host timestamp and the next cursor")
def timestamp_and_cursor(outcome):
    captured_at = datetime.fromisoformat(outcome["line"]["time"])
    assert timedelta(0) <= datetime.now(timezone.utc) - captured_at < timedelta(seconds=10)
    assert outcome["line"]["cursor"] == 1


@then(parsers.parse('the result is the line "{text}"'))
def result_is_line(outcome, text):
    assert outcome["result"]["status"] == "matched"
    assert outcome["result"]["line"]["text"] == text


@then(parsers.parse('the result is "{status}"'))
def result_is(outcome, status):
    assert outcome["result"]["status"] == status
    assert [line["text"] for line in outcome["result"]["lines"]] == ["booting"]


@then(parsers.parse('"{sent}" is sent to the device'))
def sent_to_device(device, sent):
    expected = codecs.decode(sent, "unicode_escape").encode()
    assert device.received(len(expected) + 1, timeout=0.5) == expected


@then(parsers.parse('the buffer contains a "{kind}" entry with that text'))
def buffer_contains(call, outcome, kind):
    entries = call("serial_read")["lines"]
    assert [(e["kind"], e["text"]) for e in entries] == [(kind, outcome["text"])]
    assert entries[0]["cursor"] == outcome["result"]["cursor"]


@when("the port disappears")
def port_disappears(device, console):
    device.close()
    console.unlink()


@when("the device prints a Zephyr fatal error dump")
def device_prints_a_fatal_error(device, call, outcome):
    device.print("*** Booting Zephyr OS build v4.4.0 ***\n")
    device.print("".join(f"{line}\r\n" for line in FATAL_ERROR_DUMP))
    captured(call, 1 + len(FATAL_ERROR_DUMP))
    outcome["line"] = 2 + next(n for n, text in enumerate(FATAL_ERROR_DUMP) if "FATAL" in text)


def markers(call, kind):
    return [e for e in call("serial_read", limit=1000)["lines"] if e["kind"] == kind]


@then(parsers.parse('the buffer contains a "{kind}" marker'))
def buffer_contains_marker(call, kind):
    captured(call, 1)
    assert [e["kind"] for e in call("serial_read")["lines"]] == [kind]


@then("capture resumes when the port reappears")
def capture_resumes(call, console, replugged):
    console.symlink_to(replugged.port)
    # Lines printed before the port is reopened are lost, as on a real board.
    deadline = time.monotonic() + 5
    while not call("serial_read", cursor=1)["lines"]:
        assert time.monotonic() < deadline
        replugged.print("back\n")
        time.sleep(0.1)
    assert call("serial_read", cursor=1)["lines"][0]["text"] == "back"


@then("the result has truncated true")
def result_truncated(outcome):
    assert outcome["result"]["truncated"] is True


@then(parsers.parse("returned lines start at cursor {cursor:d}"))
def lines_start_at(outcome, cursor):
    assert outcome["result"]["lines"][0]["cursor"] == cursor
    assert outcome["result"]["lines"][0]["text"] == f"line {cursor}"


@then(parsers.parse('"serial_events" returns a "{event}" event at that line'))
def events_at_that_line(call, outcome, event):
    found = call("serial_events")["events"]
    assert [(e["cursor"], e["event"]) for e in found] == [(1, "boot"), (outcome["line"], event)]
