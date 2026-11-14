from pathlib import Path

APPLICATION = {"CMakeLists.txt": "find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})\n"}


def zephyr_tree(major=4, minor=4, patch=0, extra=""):
    version = (
        f"VERSION_MAJOR = {major}\nVERSION_MINOR = {minor}\nPATCHLEVEL = {patch}\n"
        f"VERSION_TWEAK = 0\nEXTRAVERSION = {extra}\n"
    )
    return {"VERSION": version, "Kconfig.zephyr": ""}


def under(prefix, files):
    return {f"{prefix}/{path}": content for path, content in files.items()}


def project(name):
    return f"    - name: {name}\n      url: https://example.com/{name}\n      revision: main\n"


def manifest(*projects, self_path=None):
    text = "manifest:\n"
    if projects:
        text += "  projects:\n" + "".join(project(name) for name in projects)
    if self_path:
        text += f"  self:\n    path: {self_path}\n"
    return text


def make_workspace(root: Path, repository: str, files: dict, manifest_file="west.yml") -> Path:
    """Lay out a west workspace as `west init -l` leaves it, without git or network."""
    (root / ".west").mkdir(parents=True)
    (root / ".west" / "config").write_text(
        f"[manifest]\npath = {repository}\nfile = {manifest_file}\n"
    )
    for path, content in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(content)
    return root


def t1(root: Path) -> Path:
    return make_workspace(
        root,
        "zephyr",
        {"zephyr/west.yml": manifest(self_path="zephyr"), **under("zephyr", zephyr_tree())},
    )


def t2(root: Path, *applications: str) -> Path:
    files = {
        "application/west.yml": manifest("zephyr", self_path="application"),
        **under("zephyr", zephyr_tree()),
    }
    for application in applications or ("application",):
        files.update(under(application, APPLICATION))
    return make_workspace(root, "application", files)


def t3(root: Path, *projects: str) -> Path:
    files = {
        "manifest-repo/west.yml": manifest("zephyr", *projects, self_path="manifest-repo"),
        **under("zephyr", zephyr_tree()),
    }
    for name in projects:
        files.update(under(name, APPLICATION))
    return make_workspace(root, "manifest-repo", files)
