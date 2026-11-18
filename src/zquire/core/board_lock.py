import fcntl
import time
from collections.abc import Iterator
from contextlib import contextmanager

from zquire.core.workspace import Workspace
from zquire.errors import ZquireError

LOCK_TIMEOUT_S = 30
_POLL_S = 0.05


@contextmanager
def hold(workspace: Workspace, operation: str) -> Iterator[None]:
    """Hold the workspace's board for operation, waiting up to LOCK_TIMEOUT_S for it."""
    # A lock on an open file, so it is shared with other zquire processes and is let go
    # of when its holder exits, however it exits.
    with workspace.runtime_path(".lock").open("a+") as handle:
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    handle.seek(0)
                    holder = handle.read().strip() or "another operation"
                    raise ZquireError(
                        "BUSY",
                        f"The board is in use by {holder}, which did not finish within "
                        f"{LOCK_TIMEOUT_S} s.",
                        "Call again once it has finished.",
                    ) from None
                time.sleep(_POLL_S)
        handle.truncate(0)
        handle.write(operation)
        handle.flush()
        yield
