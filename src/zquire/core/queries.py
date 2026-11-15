from pathlib import Path

from zquire.adapters import kconfig
from zquire.core import devicetree, profiles
from zquire.core.context import Context
from zquire.errors import ZquireError


def _build_dir(context: Context, profile: str | None) -> tuple[str, Path]:
    workspace = context.workspace
    name = profile if profile is not None else profiles.active_profile(workspace)
    if name is None:
        raise ZquireError(
            "NO_BUILD",
            "A build is required, and no profile was named and none is active.",
            "Pass profile, or call build to create and activate one.",
        )
    settings = profiles.get(profiles.load(workspace), name)
    return name, workspace.resolve(settings["build_dir"])


def _no_build(name: str, missing: str) -> ZquireError:
    return ZquireError(
        "NO_BUILD",
        f"A build is required: profile '{name}' has no {missing}.",
        f"Call build with profile '{name}' first.",
    )


def kconfig_symbol(context: Context, symbol: str, profile: str | None = None) -> dict:
    name, build_dir = _build_dir(context, profile)
    if not (build_dir / "zephyr" / ".config").is_file():
        raise _no_build(name, "zephyr/.config")
    setup = kconfig.setup(build_dir)
    if setup is None:
        raise _no_build(name, "menuconfig target to load Kconfig from")
    wanted = symbol.removeprefix("CONFIG_")
    try:
        found = kconfig.query_symbol(setup, wanted)
    except kconfig.KconfigError as error:
        raise ZquireError(
            "KCONFIG_FAILED",
            f"The Kconfig tree of profile '{name}' could not be loaded: {error}",
            f"Rebuild with profile '{name}' and pristine 'always'.",
        ) from error
    if found is None:
        raise ZquireError(
            "SYMBOL_NOT_FOUND",
            f"Kconfig symbol '{wanted}' is not defined in the build of profile '{name}'.",
            "Check the symbol's name.",
        )
    return {"profile": name, **found}


def devicetree_node(context: Context, node: str, profile: str | None = None) -> dict:
    name, build_dir = _build_dir(context, profile)
    dts = build_dir / "zephyr" / "zephyr.dts"
    if not dts.is_file():
        raise _no_build(name, "zephyr/zephyr.dts")
    found = devicetree.find(devicetree.parse(dts.read_text(errors="replace")), node)
    if found is None:
        raise ZquireError(
            "NODE_NOT_FOUND",
            f"No devicetree node '{node}' in the build of profile '{name}'.",
            "Give a node label, or a full path starting with '/'.",
        )
    return {
        "profile": name,
        "path": found.path,
        "labels": found.labels,
        "status": found.status,
        "compatible": found.compatible,
        "properties": found.properties,
    }
