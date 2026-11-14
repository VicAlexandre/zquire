import re
from collections.abc import Mapping
from pathlib import Path


def sdk_version(environ: Mapping[str, str], home: Path) -> str | None:
    install_dir = environ.get("ZEPHYR_SDK_INSTALL_DIR")
    if install_dir:
        version = _read_version(Path(install_dir))
        if version is not None:
            return version
    return _registered_version(home / ".cmake" / "packages" / "Zephyr-sdk")


def _registered_version(registry: Path) -> str | None:
    if not registry.is_dir():
        return None
    # Each registry entry holds the path of an SDK's cmake/ directory.
    versions = [
        _read_version(Path(entry.read_text().strip()).parent)
        for entry in sorted(registry.iterdir())
        if entry.is_file()
    ]
    return max((v for v in versions if v is not None), key=_version_key, default=None)


def _read_version(install_dir: Path) -> str | None:
    version_file = install_dir / "sdk_version"
    return version_file.read_text().strip() if version_file.is_file() else None


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))
