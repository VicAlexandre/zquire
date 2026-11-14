from collections.abc import Callable
from dataclasses import dataclass

import jsonschema

from zquire.core.context import Context
from zquire.core.status import status
from zquire.errors import ZquireError


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    handler: Callable[..., dict]
    needs_workspace: bool = True


def invoke(tool: Tool, arguments: dict, context: Context) -> dict:
    if tool.needs_workspace and context.workspace is None:
        raise ZquireError(
            "NO_WORKSPACE",
            "No west workspace was found.",
            "Run `west init`, or pass --workspace with the path of a west workspace.",
        )
    try:
        jsonschema.validate(arguments, tool.input_schema)
    except jsonschema.ValidationError as error:
        raise ZquireError("INVALID_ARGUMENT", f"{error.json_path}: {error.message}") from error
    result = tool.handler(context, **arguments)
    jsonschema.validate(result, tool.output_schema)
    return result


_STRING_OR_NULL = {"type": ["string", "null"]}

_STATUS_OUTPUT = {
    "type": "object",
    "properties": {
        "zquire_version": {"type": "string"},
        "sdk_version": _STRING_OR_NULL,
        "workspace": {
            "type": ["object", "null"],
            "properties": {
                "root": {"type": "string"},
                "manifest_path": {"type": "string"},
                "manifest_repository": {"type": "string"},
                "zephyr_base": _STRING_OR_NULL,
                "zephyr_version": _STRING_OR_NULL,
                "topology": {"enum": ["T1", "T2", "T3", "unknown"]},
                "topology_evidence": {"type": "array", "items": {"type": "string"}},
                "application_candidates": {"type": "array", "items": {"type": "string"}},
                "default_application": _STRING_OR_NULL,
            },
            "required": [
                "root",
                "manifest_path",
                "manifest_repository",
                "zephyr_base",
                "zephyr_version",
                "topology",
                "topology_evidence",
                "application_candidates",
                "default_application",
            ],
        },
        "warnings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"code": {"type": "string"}, "message": {"type": "string"}},
                "required": ["code", "message"],
            },
        },
    },
    "required": ["zquire_version", "sdk_version", "workspace", "warnings"],
}

TOOLS = {
    tool.name: tool
    for tool in [
        Tool(
            name="status",
            description=(
                "Report zquire's version, the SDK version and the west workspace: root, "
                "manifest, Zephyr base and version, topology and application candidates."
            ),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            output_schema=_STATUS_OUTPUT,
            handler=status,
            needs_workspace=False,
        ),
    ]
}
