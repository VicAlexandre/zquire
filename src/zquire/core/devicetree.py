"""Read the processed devicetree a build writes to zephyr/zephyr.dts.

That file is dtlib's output: one tree, no includes and no overlays left to apply, so a
statement scanner is enough. Property values are kept as written.
"""

import re
from dataclasses import dataclass

_HEADER = re.compile(r"((?:\w+:\s*)*)(\S+)")
_STRING = re.compile(r'"((?:\\.|[^"\\])*)"')


@dataclass(frozen=True)
class Node:
    path: str
    labels: list[str]
    properties: dict[str, str | bool]

    @property
    def compatible(self) -> list[str]:
        value = self.properties.get("compatible")
        return _STRING.findall(value) if isinstance(value, str) else []

    @property
    def status(self) -> str:
        value = self.properties.get("status")
        strings = _STRING.findall(value) if isinstance(value, str) else []
        return strings[0] if strings else "okay"


def _statements(text: str):
    buffer = []
    i = 0
    while i < len(text):
        if text[i] == '"':
            end = i + 1
            while end < len(text) and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            buffer.append(text[i : end + 1])
            i = end + 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
        elif text[i] in "{;}":
            statement = re.sub(r"\s+", " ", "".join(buffer)).strip()
            buffer = []
            if text[i] != ";" or statement:
                yield text[i], statement
            i += 1
        else:
            buffer.append(text[i])
            i += 1


def parse(text: str) -> list[Node]:
    nodes = []
    stack = []
    for kind, statement in _statements(text):
        if kind == "{":
            labels, name = _HEADER.fullmatch(statement).groups()
            parent = stack[-1].path if stack else ""
            path = "/" if name == "/" else f"{parent.rstrip('/')}/{name}"
            node = Node(path, re.findall(r"\w+", labels), {})
            nodes.append(node)
            stack.append(node)
        elif kind == "}":
            stack.pop()
        elif stack:
            name, equals, value = statement.partition("=")
            node = stack[-1]
            node.properties[name.strip()] = value.strip() if equals else True
    return nodes


def find(nodes: list[Node], wanted: str) -> Node | None:
    if wanted.startswith("/"):
        path = wanted.rstrip("/") or "/"
        matches = (node for node in nodes if node.path == path)
    else:
        label = wanted.removeprefix("&")
        matches = (node for node in nodes if label in node.labels)
    return next(matches, None)
