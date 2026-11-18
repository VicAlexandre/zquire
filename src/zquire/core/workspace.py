import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path

from zquire.adapters.west import ManifestInfo, find_topdir, read_manifest


@dataclass(frozen=True)
class Workspace:
    root: Path
    manifest: ManifestInfo

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def resolve(self, path: str) -> Path:
        """Resolve a stored path, which is relative to the root unless absolute."""
        return (self.root / path).resolve()

    def runtime_path(self, suffix: str) -> Path:
        """A file in the temporary directory that belongs to this workspace."""
        # Short, as Unix socket paths are limited to about 100 bytes.
        digest = hashlib.sha256(str(self.root).encode()).hexdigest()[:16]
        return Path(tempfile.gettempdir()) / f"zquire-{digest}{suffix}"


def locate(start: Path, explicit: Path | None = None) -> Workspace | None:
    if explicit is not None:
        root = explicit.resolve() if (explicit / ".west").is_dir() else None
    else:
        root = find_topdir(start)
    if root is None:
        return None
    return Workspace(root, read_manifest(root))
