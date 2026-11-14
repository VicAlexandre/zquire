from collections.abc import Callable
from dataclasses import dataclass

import jsonschema

from zquire.core.status import status
from zquire.errors import ZquireError


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    handler: Callable[..., dict]


def invoke(tool: Tool, arguments: dict) -> dict:
    try:
        jsonschema.validate(arguments, tool.input_schema)
    except jsonschema.ValidationError as error:
        raise ZquireError("INVALID_ARGUMENT", f"{error.json_path}: {error.message}") from error
    result = tool.handler(**arguments)
    jsonschema.validate(result, tool.output_schema)
    return result


TOOLS = {
    tool.name: tool
    for tool in [
        Tool(
            name="status",
            description="Report zquire's version.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            output_schema={
                "type": "object",
                "properties": {"zquire_version": {"type": "string"}},
                "required": ["zquire_version"],
            },
            handler=status,
        ),
    ]
}
