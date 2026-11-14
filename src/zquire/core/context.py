from dataclasses import dataclass

from zquire.core.workspace import Workspace


@dataclass(frozen=True)
class Context:
    workspace: Workspace | None
