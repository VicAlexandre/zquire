import os
import re
from pathlib import Path

EXCERPT_LINES = 60

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_LOCATED = re.compile(
    r"^(?P<file>[^\s:][^:]*):(?P<line>\d+):(?:(?P<column>\d+):)? "
    r"(?P<severity>fatal error|error|warning): (?P<message>.+)$"
)
_KCONFIG = re.compile(r"^(?P<severity>error|warning): (?P<message>.+)$")
_UNMET = re.compile(
    r"^(?P<symbol>\w+) \(defined at [^)]*\) was assigned the value '(?P<assigned>[^']*)' "
    r"but got the value '(?P<got>[^']*)'\. Check these unsatisfied dependencies: "
    r"(?P<dependencies>.+?)\. See "
)
_DEVICETREE = re.compile(
    r"^devicetree error: (?:(?P<file>[^:]+):(?P<line>\d+) \(column (?P<column>\d+)\): )?"
    r"(?P<message>.+)$"
)
_LINKER = re.compile(
    r"^(?P<file>[^\s:][^:]*):(?P<line>\d+):\(.*?\): "
    r"(?P<message>(?:undefined reference to|multiple definition of) .+)$"
)
_OVERFLOW = re.compile(r"region `(?P<region>[^']+)' overflowed by (?P<bytes>\d+) bytes")
_CMAKE = re.compile(
    r"^CMake (?P<severity>Error|Warning)(?: \(dev\))?"
    r"(?: at (?P<file>.+?):(?P<line>\d+) \(\w+\))?:\s*(?P<message>.*)$"
)
_TOOLCHAIN = re.compile(r"toolchain|zephyr-sdk|ZEPHYR_SDK", re.I)
_MEMORY_ROW = re.compile(
    r"^\s*(?P<region>\S+):\s+(?P<used>\d+)\s*(?P<used_unit>[KMG]?B)"
    r"\s+(?P<total>\d+)\s*(?P<total_unit>[KMG]?B)\s+(?P<percent>[\d.]+)%\s*$"
)
_UNITS = {"B": 1, "KB": 1 << 10, "MB": 1 << 20, "GB": 1 << 30}

_HINTS = [
    (
        re.compile(r"implicit declaration of function '(\w+)'"),
        "Declare '{0}', or include the header that declares it.",
    ),
    (
        re.compile(r"undefined reference to `(\w+)'"),
        "Define '{0}', or add the source file or library that provides it to the build.",
    ),
    (
        re.compile(r"undefined node label '(\w+)'"),
        "Use a node label that exists in the board's devicetree, or define '{0}'.",
    ),
]


def _lines(log: str) -> list[str]:
    return _ANSI.sub("", log).splitlines()


def _relative(root: Path, file: str) -> str:
    path = Path(file)
    if not path.is_absolute():
        return file
    path = Path(os.path.normpath(path))
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _category(file: str) -> str:
    name = Path(file).name
    if name.endswith((".conf", "_defconfig")) or name.startswith("Kconfig"):
        return "kconfig"
    if name.endswith((".overlay", ".dts", ".dtsi")):
        return "devicetree"
    return "compiler"


def _diagnostic(root: Path, severity: str, category: str, message: str, match=None) -> dict:
    diagnostic = {
        "severity": "error" if severity.lower() == "fatal error" else severity.lower(),
        "category": category,
        "message": message,
    }
    groups = match.groupdict() if match else {}
    if groups.get("file"):
        diagnostic["file"] = _relative(root, groups["file"])
    for key in ("line", "column"):
        if groups.get(key):
            diagnostic[key] = int(groups[key])
    for pattern, hint in _HINTS:
        found = pattern.search(message)
        if found:
            diagnostic["hint"] = hint.format(*found.groups())
    return diagnostic


def _paragraph(lines: list[str], start: int) -> tuple[str, int]:
    """Join a Kconfig message, which wraps across lines up to a blank one."""
    end = start
    while end < len(lines) and lines[end].strip():
        end += 1
    return " ".join(line.strip() for line in lines[start:end]), end


def _cmake_message(lines: list[str], start: int, first: str) -> tuple[str, int]:
    parts = [first] if first else []
    end = start
    while end < len(lines):
        line = lines[end]
        if line.strip() and not line.startswith(" "):
            break
        if line.strip():
            parts.append(line.strip())
        end += 1
    return " ".join(parts), end


def _kconfig(root: Path, severity: str, message: str) -> dict:
    unmet = _UNMET.match(message)
    if unmet is None:
        message = message.split(" See http", 1)[0]
        return _diagnostic(root, severity, "kconfig", message)
    symbol = unmet["symbol"]
    diagnostic = _diagnostic(
        root,
        severity,
        "kconfig",
        f"CONFIG_{symbol} was assigned '{unmet['assigned']}' but got '{unmet['got']}': "
        f"unsatisfied dependencies {unmet['dependencies']}.",
    )
    diagnostic["hint"] = f"Enable the dependencies first, or drop CONFIG_{symbol}."
    return diagnostic


def _overflow(root: Path, match) -> dict:
    region, over = match["region"], int(match["bytes"])
    diagnostic = _diagnostic(
        root, "error", "memory_overflow", f"Region {region} overflowed by {over} bytes."
    )
    diagnostic.update(
        region=region,
        overflow_bytes=over,
        hint=f"Free at least {over} bytes of {region}, or place data in another region.",
    )
    return diagnostic


def _extract(log: str, root: Path) -> list[dict]:
    lines = _lines(log)
    found = []
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if match := _OVERFLOW.search(line):
            found.append(_overflow(root, match))
        elif match := _LINKER.match(line):
            found.append(_diagnostic(root, "error", "linker", match["message"], match))
        elif match := _DEVICETREE.match(line):
            found.append(_diagnostic(root, "error", "devicetree", match["message"], match))
        elif match := _LOCATED.match(line):
            category = _category(match["file"])
            found.append(_diagnostic(root, match["severity"], category, match["message"], match))
        elif match := _KCONFIG.match(line):
            message, index = _paragraph(lines, index - 1)
            found.append(_kconfig(root, match["severity"], _KCONFIG.match(message)["message"]))
        elif match := _CMAKE.match(line):
            message, index = _cmake_message(lines, index, match["message"])
            category = "toolchain" if _TOOLCHAIN.search(f"{match['file']} {message}") else "cmake"
            found.append(_diagnostic(root, match["severity"], category, message, match))
    # Zephyr's CMake modules wrap a failing Kconfig or devicetree step in a CMake error of
    # their own, which only repeats a failure already reported.
    if any(d["severity"] == "error" and d["category"] != "cmake" for d in found):
        found = [d for d in found if d["category"] != "cmake"]
    return found


def _deduplicated(diagnostics: list[dict]) -> list[dict]:
    unique: dict[tuple, dict] = {}
    for diagnostic in diagnostics:
        key = tuple(sorted(diagnostic.items()))
        if key in unique:
            unique[key]["count"] += 1
        else:
            unique[key] = {**diagnostic, "count": 1}
    return list(unique.values())


def diagnostics(log: str, root: Path, failed: bool) -> list[dict]:
    found = _deduplicated(_extract(log, root))
    if failed and not any(d["severity"] == "error" for d in found):
        found.append(
            {
                "severity": "error",
                "category": "unknown",
                "message": "The build failed and no diagnostic could be extracted from its output.",
                "hint": "Read log_excerpt, or the full log at log_path.",
                "count": 1,
                "log_excerpt": "\n".join(_lines(log)[-EXCERPT_LINES:]),
            }
        )
    return found


def memory_usage(log: str) -> list[dict]:
    """Read the last memory usage table the linker printed."""
    regions: list[dict] = []
    in_table = False
    for line in _lines(log):
        if line.startswith("Memory region"):
            regions, in_table = [], True
        elif in_table and (row := _MEMORY_ROW.match(line)):
            regions.append(
                {
                    "region": row["region"],
                    "used": int(row["used"]) * _UNITS[row["used_unit"]],
                    "total": int(row["total"]) * _UNITS[row["total_unit"]],
                    "percent": float(row["percent"]),
                }
            )
        else:
            in_table = False
    return regions
