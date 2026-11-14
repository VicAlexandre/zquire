from pathlib import Path


def _git_dir(repository: Path) -> Path | None:
    dot_git = repository / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        # Worktrees and submodules point at their git directory from a .git file.
        target = dot_git.read_text().strip().removeprefix("gitdir:").strip()
        return (repository / target).resolve()
    return None


def head_commit(repository: Path) -> str | None:
    """Read the commit checked out in repository from its git files, without running git."""
    git_dir = _git_dir(repository)
    if git_dir is None or not (git_dir / "HEAD").is_file():
        return None
    head = (git_dir / "HEAD").read_text().strip()
    if not head.startswith("ref:"):
        return head
    ref = head.removeprefix("ref:").strip()
    common = git_dir
    if (git_dir / "commondir").is_file():
        common = (git_dir / (git_dir / "commondir").read_text().strip()).resolve()
    for directory in (git_dir, common):
        if (directory / ref).is_file():
            return (directory / ref).read_text().strip()
    packed = common / "packed-refs"
    if packed.is_file():
        for line in packed.read_text().splitlines():
            commit, _, name = line.partition(" ")
            if name == ref:
                return commit
    return None
