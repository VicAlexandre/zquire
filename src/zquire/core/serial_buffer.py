import re
import threading
import time
from datetime import datetime, timezone


class Lines:
    """Splits the bytes a port delivers into lines, holding back an unfinished one."""

    def __init__(self) -> None:
        self._pending = b""

    def feed(self, data: bytes) -> list[bytes]:
        *lines, self._pending = (self._pending + data).split(b"\n")
        return lines


def decode(raw: bytes) -> tuple[str, bool]:
    """Return a line's text without its line ending, and whether it held invalid UTF-8."""
    raw = raw.removesuffix(b"\r")
    try:
        return raw.decode(), False
    except UnicodeDecodeError:
        return raw.decode(errors="replace"), True


class Buffer:
    """Captured entries, each numbered by a cursor that starts at 1."""

    def __init__(self) -> None:
        self._entries: list[dict] = []
        self._changed = threading.Condition()
        self._closed = False

    def last_cursor(self) -> int:
        with self._changed:
            return len(self._entries)

    def add(self, kind: str, text: str, invalid_utf8: bool = False) -> dict:
        with self._changed:
            entry = {
                "cursor": len(self._entries) + 1,
                "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "kind": kind,
                "text": text,
                "invalid_utf8": invalid_utf8,
            }
            self._entries.append(entry)
            self._changed.notify_all()
            return entry

    def read(self, cursor: int, limit: int, pattern: re.Pattern | None = None) -> dict:
        lines: list[dict] = []
        next_cursor = cursor
        with self._changed:
            for entry in self._entries[cursor:]:
                if len(lines) == limit:
                    break
                next_cursor = entry["cursor"]
                if pattern is None or pattern.search(entry["text"]):
                    lines.append(entry)
        return {"lines": lines, "next_cursor": next_cursor}

    def wait(self, pattern: re.Pattern, cursor: int, timeout: float, limit: int) -> dict:
        """Wait for a received line matching pattern after cursor, or until timeout seconds."""
        deadline = time.monotonic() + timeout
        seen: list[dict] = []
        position = cursor
        with self._changed:
            while True:
                for entry in self._entries[position:]:
                    position = entry["cursor"]
                    if entry["kind"] == "rx" and pattern.search(entry["text"]):
                        return {
                            "status": "matched",
                            "line": entry,
                            "lines": [],
                            "next_cursor": position,
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
        status = "closed" if self._closed else "timeout"
        return {"status": status, "line": None, "lines": seen, "next_cursor": position}

    def close(self) -> None:
        with self._changed:
            self._closed = True
            self._changed.notify_all()
