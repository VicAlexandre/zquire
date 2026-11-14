import pytest

from zquire.adapters.git import head_commit

COMMIT = "a" * 40
OTHER = "b" * 40


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "repo" / ".git" / "refs" / "heads").mkdir(parents=True)
    return tmp_path / "repo"


def test_no_git_directory(tmp_path):
    assert head_commit(tmp_path) is None


def test_git_directory_without_head(repo):
    assert head_commit(repo) is None


def test_detached_head(repo):
    (repo / ".git" / "HEAD").write_text(f"{COMMIT}\n")
    assert head_commit(repo) == COMMIT


def test_branch_head(repo):
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (repo / ".git" / "refs" / "heads" / "main").write_text(f"{COMMIT}\n")
    assert head_commit(repo) == COMMIT


def test_packed_branch_head(repo):
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (repo / ".git" / "packed-refs").write_text(
        f"# pack-refs with: peeled fully-peeled sorted\n{OTHER} refs/heads/other\n"
        f"{COMMIT} refs/heads/main\n^{OTHER}\n"
    )
    assert head_commit(repo) == COMMIT


def test_unresolvable_branch(repo):
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/gone\n")
    (repo / ".git" / "packed-refs").write_text(f"{OTHER} refs/heads/other\n")
    assert head_commit(repo) is None


def test_unresolvable_branch_without_packed_refs(repo):
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/gone\n")
    assert head_commit(repo) is None


@pytest.mark.parametrize("absolute", [False, True], ids=["relative", "absolute"])
def test_git_file_points_at_the_git_directory(tmp_path, absolute):
    git_dir = tmp_path / "store" / "modules" / "zephyr"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text(f"{COMMIT}\n")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    target = git_dir if absolute else "../store/modules/zephyr"
    (checkout / ".git").write_text(f"gitdir: {target}\n")
    assert head_commit(checkout) == COMMIT


def test_worktree_reads_branches_from_the_common_directory(repo, tmp_path):
    worktree_git = repo / ".git" / "worktrees" / "wt"
    worktree_git.mkdir(parents=True)
    (worktree_git / "HEAD").write_text("ref: refs/heads/feature\n")
    (worktree_git / "commondir").write_text("../..\n")
    (repo / ".git" / "refs" / "heads" / "feature").write_text(f"{COMMIT}\n")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {worktree_git}\n")
    assert head_commit(worktree) == COMMIT


def test_worktree_packed_refs_live_in_the_common_directory(repo, tmp_path):
    worktree_git = repo / ".git" / "worktrees" / "wt"
    worktree_git.mkdir(parents=True)
    (worktree_git / "HEAD").write_text("ref: refs/heads/feature\n")
    (worktree_git / "commondir").write_text("../..\n")
    (repo / ".git" / "packed-refs").write_text(f"{COMMIT} refs/heads/feature\n")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {worktree_git}\n")
    assert head_commit(worktree) == COMMIT
