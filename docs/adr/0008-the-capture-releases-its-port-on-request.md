# 8. The capture releases its port on request and reopens it by polling

## Context

SER-07 and FLS-05 ask the capture to give up its port while a board is flashed, mark the flash in the buffer, and reopen the port afterwards, retrying for up to 10 s while a USB console re-enumerates. SER-08 asks it to mark a port that disappears unexpectedly, and to keep trying to reopen it until `serial_close`. TWS-06 will need the same release around device testing. SER-09 bounds the buffer at 50,000 lines by default. SER-10 and SER-11 tag Zephyr's boot banner, fatal errors, assertion failures and kernel panics, and return them by cursor.

## Decision

- The capture's reading thread owns the port. It is the only code that opens or closes it, and a lock keeps writes off a port while it is swapped. `release` and `resume` requests set a flag that the thread acts on within one read timeout (0.1 s).
- `release` returns once the port is closed, after any unfinished line and a `flash` marker. `resume` returns once the port has reopened, or after the timeout the caller gives. It then adds a `disconnected` marker and keeps polling. `flash` releases the port just before running west and resumes it afterwards, even when the flash fails. If the port does not come back, `flash` warns with `serial_not_reopened`. Flashes refused before running west leave the port alone.
- A read error closes the port and adds a `disconnected` marker. The thread then tries to reopen the same device name every 0.2 s.
- Markers are buffer entries with kinds `flash` and `disconnected`, numbered like lines. Each received line is tagged with the first event whose pattern it matches: `boot` (`*** Booting Zephyr OS`), `assertion` (`ASSERTION FAIL [`), `kernel_panic` (`ZEPHYR FATAL ERROR n: Kernel panic`), then `fatal_error` (`ZEPHYR FATAL ERROR`). Those are the strings Zephyr's `kernel/fatal.c` and `__assert.h` print.
- When more than `buffer_lines` entries are held, the oldest is dropped. A read, wait or events request whose cursor is older than the oldest entry kept reports `truncated`.

## Alternatives

- **Having `flash` kill the capture and start a new one** would lose the buffer, and cursors would start again from 1.
- **Watching for device files with udev or IOKit** would reopen sooner than polling, but needs a different mechanism on Linux and macOS (NFR-07), and polling every 0.2 s is quick enough for a console.
- **Tagging events when reading them**, rather than when lines arrive, would let patterns change without a new capture. It would scan the whole buffer on every `serial_events` call.

## Consequences

Lines a board prints before the port reopens are lost. pyserial also discards input waiting when it opens a port, so a boot banner can be missed on a board that boots quickly. A device that keeps its name but fails every read adds a `disconnected` marker on each attempt. Twister's device testing (TWS-06) can use `release` and `resume` as they are.
