import re
from pathlib import Path

from zquire.core.topology import Topology, is_zephyr_tree
from zquire.core.workspace import Workspace


def zephyr_base(workspace: Workspace, topology: Topology) -> Path | None:
    if topology.kind == "T1":
        return workspace.manifest.repository
    path = (workspace.manifest.projects or {}).get("zephyr")
    return path if path is not None and is_zephyr_tree(path) else None


def zephyr_version(base: Path) -> str:
    fields = dict(re.findall(r"^(\w+)\s*=\s*(\S*)", (base / "VERSION").read_text(), re.M))
    version = f"{fields['VERSION_MAJOR']}.{fields['VERSION_MINOR']}.{fields['PATCHLEVEL']}"
    extra = fields.get("EXTRAVERSION")
    return f"{version}-{extra}" if extra else version
