import os
from pathlib import Path

from zquire import __version__
from zquire.core.context import Context
from zquire.core.profiles import active_profile
from zquire.core.sdk import sdk_version
from zquire.core.topology import infer
from zquire.core.workspace import Workspace
from zquire.core.zephyr import zephyr_base, zephyr_version


def status(context: Context) -> dict:
    workspace = context.workspace
    return {
        "zquire_version": __version__,
        "sdk_version": sdk_version(os.environ, Path.home()),
        "workspace": None if workspace is None else _describe(workspace),
        "warnings": [] if workspace is None else _warnings(workspace),
    }


def _describe(workspace: Workspace) -> dict:
    topology = infer(workspace)
    base = zephyr_base(workspace, topology)
    candidates = [workspace.relative(path) for path in topology.candidates]
    return {
        "root": str(workspace.root),
        "manifest_path": str(workspace.manifest.path),
        "manifest_repository": str(workspace.manifest.repository),
        "zephyr_base": None if base is None else str(base),
        "zephyr_version": None if base is None else zephyr_version(base),
        "topology": topology.kind,
        "topology_evidence": topology.evidence,
        "application_candidates": candidates,
        "default_application": candidates[0] if len(candidates) == 1 else None,
        "active_profile": active_profile(workspace),
    }


def _warnings(workspace: Workspace) -> list[dict]:
    if not (workspace.root / ".git").exists():
        return []
    return [
        {
            "code": "unsupported_topology",
            "message": "The workspace topdir is a git repository, which west does not support.",
        }
    ]
