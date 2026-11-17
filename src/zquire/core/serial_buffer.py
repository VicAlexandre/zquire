import re
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone


class Lines:
    """Splits the bytes a port delivers into lines, holding back an unfinished one."""

    def __init__(self) -> None:
        self._pending = b""

    def feed(self, data: bytes) -> list[bytes]:
        *lines, self._pending = (self._pending + data).split(b"\n")
        return lines

    def flush(self) -> list[bytes]:
        pending, self._pending = self._pending, b""
        return [pending] if pending else []


def decode(raw: bytes) -> tuple[str, bool]:
    """Return a line's text without its line ending, and whether it held invalid UTF-8."""
    raw = raw.removesuffix(b"\r")
    try:
        return raw.decode(), False
    except UnicodeDecodeError:
        return raw.decode(errors="replace"), True


DEFAULT_CAPACITY = 50_000

# The first that matches tags the line, so a kernel panic is not also a plain fatal error.
_EVENTS = [
    ("boot", re.compile(r"\*\*\* Booting Zephyr OS")),
    ("assertion", re.compile(r"ASSERTION FAIL \[")),
    ("kernel_panic", re.compile(r"ZEPHYR FATAL ERROR \d+: Kernel panic")),
    ("fatal_error", re.compile(r"ZEPHYR FATAL ERROR")),
]


def event(text: str) -> str | None:
    return next((name for name, pattern in _EVENTS if pattern.search(text)), None)


class Buffer:
    """Captured entries, each numbered by a cursor that starts at 1."""

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        self._entries: list[dict] = []
        self._dropped = 0
        self._capacity = capacity
        self._changed = threading.Condition()
        self._closed = False

    def last_cursor(self) -> int:
        with self._changed:
            return self._dropped + len(self._entries)

    def _after(self, cursor: int) -> list[dict]:
        return self._entries[max(cursor - self._dropped, 0) :]

    def add(self, kind: str, text: str, invalid_utf8: bool = False) -> dict:
        with self._changed:
            entry = {
                "cursor": self._dropped + len(self._entries) + 1,
                "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "kind": kind,
                "text": text,
                "invalid_utf8": invalid_utf8,
                "event": event(text) if kind == "rx" else None,
            }
            self._entries.append(entry)
            if len(self._entries) > self._capacity:
                del self._entries[0]
                self._dropped += 1
            self._changed.notify_all()
            return entry

    def read(self, cursor: int, limit: int, keep: Callable[[dict], bool] | None = None) -> dict:
        lines: list[dict] = []
        next_cursor = cursor
        with self._changed:
            truncated = cursor < self._dropped
            for entry in self._after(cursor):
                if len(lines) == limit:
                    break
                next_cursor = entry["cursor"]
                if keep is None or keep(entry):
                    lines.append(entry)
        return {"lines": lines, "next_cursor": next_cursor, "truncated": truncated}

    def wait(self, pattern: re.Pattern, cursor: int, timeout: float, limit: int) -> dict:
        """Wait for a received line matching pattern after cursor, or until timeout seconds."""
        deadline = time.monotonic() + timeout
        seen: list[dict] = []
        position = cursor
        truncated = False
        with self._changed:
            while True:
                truncated = truncated or position < self._dropped
                for entry in self._after(position):
                    position = entry["cursor"]
                    if entry["kind"] == "rx" and pattern.search(entry["text"]):
                        return {
                            "status": "matched",
                            "line": entry,
                            "lines": [],
                            "next_cursor": position,
                            "truncated": truncated,
                        }
                    seen.append(entry)
                remaining = deadline - time.monotonic()
                if self._closed or remaining <= 0:
                    break
                self._changed.wait(remaining)
        if len(seen) > limit:
            # Resume after the last line returned, so the rest can still be read.
            seen = seen[:limit]
            position = seen[-1]["cursor"]
        return {
            "status": "closed" if self._closed else "timeout",
            "line": None,
            "lines": seen,
            "next_cursor": position,
            "truncated": truncated,
        }

    def close(self) -> None:
        with self._changed:
            self._closed = True
            self._changed.notify_all()
