from collections.abc import Callable
from dataclasses import dataclass

import jsonschema

from zquire.core import profiles
from zquire.core.build import LOG_LINES, build, build_log
from zquire.core.context import Context
from zquire.core.flash import EXCERPT_LINES, flash
from zquire.core.queries import devicetree_node, kconfig_symbol
from zquire.core.serial import (
    DEFAULT_BAUD,
    DEFAULT_LIMIT,
    DEFAULT_WAIT_S,
    serial_close,
    serial_open,
    serial_read,
    serial_wait,
    serial_write,
)
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
                "active_profile": _STRING_OR_NULL,
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
                "active_profile",
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

_STRINGS = {"type": "array", "items": {"type": "string"}}

_SETTINGS = {
    "application": {
        "type": "string",
        "description": "Application directory, relative to the workspace root.",
    },
    "board": {"type": "string", "description": "Board target, e.g. nrf52840dk/nrf52840."},
    "build_dir": {
        "type": "string",
        "description": "Build directory, relative to the workspace root.",
    },
    "pristine": {"enum": ["auto", "always", "never"]},
    "cmake_args": _STRINGS,
    "conf_files": {
        **_STRINGS,
        "description": "Extra Kconfig fragments (EXTRA_CONF_FILE), relative to the application.",
    },
    "overlays": {
        **_STRINGS,
        "description": "Devicetree overlays (EXTRA_DTC_OVERLAY_FILE), relative to the application.",
    },
    "snippets": _STRINGS,
    "shields": _STRINGS,
}

_PROFILE = {
    "type": "object",
    "properties": {"name": {"type": "string"}, **_SETTINGS},
    "required": ["name", *_SETTINGS],
}

_NAME = {"name": {"type": "string"}}

_LAST_BUILD = {
    "type": ["object", "null"],
    "properties": {
        "status": {"enum": ["success", "failure"]},
        "time": {"type": "string", "description": "When the build finished, ISO 8601 UTC."},
        "duration_s": {"type": "number"},
        "build_dir": {"type": "string"},
    },
    "required": ["status", "time", "duration_s", "build_dir"],
}

_DIAGNOSTIC = {
    "type": "object",
    "properties": {
        "severity": {"enum": ["error", "warning"]},
        "category": {
            "enum": [
                "compiler",
                "linker",
                "kconfig",
                "devicetree",
                "cmake",
                "memory_overflow",
                "toolchain",
                "unknown",
            ]
        },
        "message": {"type": "string"},
        "file": {
            "type": "string",
            "description": "Relative to the workspace root when inside it, else absolute.",
        },
        "line": {"type": "integer"},
        "column": {"type": "integer"},
        "hint": {"type": "string"},
        "count": {"type": "integer", "description": "How many times the diagnostic repeated."},
        "region": {"type": "string"},
        "overflow_bytes": {"type": "integer"},
        "log_excerpt": {"type": "string", "description": "The last lines of the build output."},
    },
    "required": ["severity", "category", "message", "count"],
}

_MEMORY_REGION = {
    "type": "object",
    "properties": {
        "region": {"type": "string"},
        "used": {"type": "integer", "description": "Bytes."},
        "total": {"type": "integer", "description": "Bytes."},
        "percent": {"type": "number"},
    },
    "required": ["region", "used", "total", "percent"],
}


def _input(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _output(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties)}


_SERIAL_ENTRY = {
    "type": "object",
    "properties": {
        "cursor": {"type": "integer"},
        "time": {"type": "string", "description": "Host time it was captured, in UTC."},
        "kind": {"enum": ["rx", "tx"], "description": "Received from or sent to the device."},
        "text": {"type": "string"},
        "invalid_utf8": {
            "type": "boolean",
            "description": "Whether invalid UTF-8 was replaced with U+FFFD.",
        },
    },
    "required": ["cursor", "time", "kind", "text", "invalid_utf8"],
}

_SERIAL_LIMIT = {
    "limit": {
        "type": "integer",
        "minimum": 1,
        "description": f"Most lines to return. Default {DEFAULT_LIMIT}.",
    }
}

_NEXT_CURSOR = {
    "type": "integer",
    "description": "Pass as cursor to continue after the lines returned.",
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
        Tool(
            name="profile_list",
            description=(
                "List the build profiles, their settings, which one is active, how each was "
                "last built and whether that build is stale."
            ),
            input_schema=_input({}, []),
            output_schema=_output(
                {
                    "profiles": {
                        "type": "array",
                        "items": {
                            **_PROFILE,
                            "properties": {
                                **_PROFILE["properties"],
                                "active": {"type": "boolean"},
                                "last_build": _LAST_BUILD,
                                "stale": {
                                    "type": ["boolean", "null"],
                                    "description": (
                                        "Whether the application, the profile's fragments or "
                                        "overlays, its settings or the zephyr checkout changed "
                                        "since its last successful build. Null if it never "
                                        "built successfully."
                                    ),
                                },
                            },
                            "required": [*_PROFILE["required"], "active", "last_build", "stale"],
                        },
                    }
                }
            ),
            handler=profiles.list_profiles,
        ),
        Tool(
            name="profile_create",
            description=(
                "Create a named build profile. Without application or board, uses the "
                "workspace's single default application and `west config build.board`, "
                "and reports which defaults it applied."
            ),
            input_schema=_input(
                {
                    **_NAME,
                    "from": {"type": "string", "description": "Profile to copy settings from."},
                    **_SETTINGS,
                },
                ["name"],
            ),
            output_schema=_output(
                {
                    "profile": _PROFILE,
                    "defaults_applied": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "setting": {"type": "string"},
                                "source": {"type": "string"},
                                "level": {"type": "string"},
                            },
                            "required": ["setting", "source"],
                        },
                    },
                }
            ),
            handler=profiles.create,
        ),
        Tool(
            name="profile_update",
            description="Change settings of an existing build profile.",
            input_schema=_input({**_NAME, **_SETTINGS}, ["name"]),
            output_schema=_output({"profile": _PROFILE}),
            handler=profiles.update,
        ),
        Tool(
            name="profile_delete",
            description=(
                "Delete a build profile. Its build directory is kept unless remove_build_dir "
                "is true. The active profile cannot be deleted."
            ),
            input_schema=_input({**_NAME, "remove_build_dir": {"type": "boolean"}}, ["name"]),
            output_schema=_output(
                {"deleted": {"type": "string"}, "build_dir_removed": {"type": "boolean"}}
            ),
            handler=profiles.delete,
        ),
        Tool(
            name="profile_activate",
            description="Make a build profile the default for every tool. Does not rebuild.",
            input_schema=_input(_NAME, ["name"]),
            output_schema=_output({"active_profile": {"type": "string"}}),
            handler=profiles.activate,
        ),
        Tool(
            name="build",
            description=(
                "Run `west build` for the active profile, or the profile named. Returns status, "
                "duration, classified diagnostics, flash and RAM usage per region and the path "
                "of the full log. With no profile at all, application and board create and "
                "activate the 'default' profile."
            ),
            input_schema=_input(
                {
                    "profile": {"type": "string", "description": "Profile to build instead."},
                    "pristine": {
                        **_SETTINGS["pristine"],
                        "description": "Override the profile's pristine setting for this build.",
                    },
                    "application": _SETTINGS["application"],
                    "board": _SETTINGS["board"],
                },
                [],
            ),
            output_schema=_output(
                {
                    "profile": {"type": "string"},
                    "profile_created": {"type": "boolean"},
                    "status": {"enum": ["success", "failure"]},
                    "duration_s": {"type": "number"},
                    "build_dir": {"type": "string"},
                    "log_path": {
                        "type": "string",
                        "description": "Full build log, relative to the workspace root.",
                    },
                    "diagnostics": {"type": "array", "items": _DIAGNOSTIC},
                    "memory": {"type": "array", "items": _MEMORY_REGION},
                }
            ),
            handler=build,
        ),
        Tool(
            name="build_log",
            description=(
                "Read part of a profile's latest build log: its last line_count lines, or "
                "line_count lines from start_line. Defaults to the active profile."
            ),
            input_schema=_input(
                {
                    "profile": {"type": "string"},
                    "start_line": {"type": "integer", "minimum": 1, "description": "1-based."},
                    "line_count": {
                        "type": "integer",
                        "minimum": 1,
                        "description": f"Defaults to {LOG_LINES}.",
                    },
                },
                [],
            ),
            output_schema=_output(
                {
                    "profile": {"type": "string"},
                    "log_path": {"type": "string"},
                    "total_lines": {"type": "integer"},
                    "first_line": {"type": "integer"},
                    "last_line": {"type": "integer"},
                    "text": {"type": "string"},
                    "truncated": {
                        "type": "boolean",
                        "description": "Whether lines were left out to keep the result small.",
                    },
                }
            ),
            handler=build_log,
        ),
        Tool(
            name="flash",
            description=(
                "Flash the last successful build of the active or named profile with west flash, "
                "without rebuilding. Warns when the build is stale."
            ),
            input_schema=_input(
                {
                    "profile": {"type": "string"},
                    "runner": {"type": "string", "description": "Overrides the board's default."},
                    "require_fresh": {
                        "type": "boolean",
                        "description": "Fail with STALE_BUILD instead of flashing a stale build.",
                    },
                },
                [],
            ),
            output_schema=_output(
                {
                    "profile": {"type": "string"},
                    "status": {"enum": ["success", "failure"]},
                    "runner": _STRING_OR_NULL,
                    "duration_s": {"type": "number"},
                    "build_dir": {"type": "string"},
                    "log_path": {"type": "string"},
                    "log_excerpt": {
                        "type": "string",
                        "description": f"The log's last {EXCERPT_LINES} lines.",
                    },
                    "warnings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                            },
                            "required": ["code", "message"],
                        },
                    },
                }
            ),
            handler=flash,
        ),
        Tool(
            name="kconfig_symbol",
            description=(
                "Look up a Kconfig symbol in a profile's build: its type, value, whether it is "
                "set, and the dependencies keeping it off. Defaults to the active profile."
            ),
            input_schema=_input(
                {
                    "symbol": {"type": "string", "description": "With or without CONFIG_."},
                    "profile": {"type": "string"},
                },
                ["symbol"],
            ),
            output_schema=_output(
                {
                    "profile": {"type": "string"},
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "value": {"type": "string"},
                    "set": {"type": "boolean", "description": "Whether .config sets it."},
                    "unmet_dependencies": {
                        **_STRINGS,
                        "description": "Empty unless the symbol's dependencies are unmet.",
                    },
                }
            ),
            handler=kconfig_symbol,
        ),
        Tool(
            name="devicetree_node",
            description=(
                "Look up a devicetree node in a profile's build by label or path: its status, "
                "compatible and properties. Defaults to the active profile."
            ),
            input_schema=_input(
                {
                    "node": {
                        "type": "string",
                        "description": "A label, like 'i2c0', or a path, like '/soc/i2c@40003000'.",
                    },
                    "profile": {"type": "string"},
                },
                ["node"],
            ),
            output_schema=_output(
                {
                    "profile": {"type": "string"},
                    "path": {"type": "string"},
                    "labels": _STRINGS,
                    "status": {"type": "string"},
                    "compatible": _STRINGS,
                    "properties": {
                        "type": "object",
                        "additionalProperties": {"type": ["string", "boolean"]},
                        "description": "Values as written in zephyr.dts; true for empty ones.",
                    },
                }
            ),
            handler=devicetree_node,
        ),
        Tool(
            name="serial_open",
            description=(
                "Open a serial capture on a port, or on the only USB serial port when none is "
                "given. The capture keeps buffering lines until serial_close."
            ),
            input_schema=_input(
                {
                    "port": {
                        "type": "string",
                        "description": "Device, like /dev/ttyACM0. Detected when omitted.",
                    },
                    "baud": {
                        "type": "integer",
                        "minimum": 1,
                        "description": f"Default {DEFAULT_BAUD}.",
                    },
                },
                [],
            ),
            output_schema=_output(
                {
                    "port": {"type": "string"},
                    "baud": {"type": "integer"},
                    "detected": {"type": "boolean"},
                    "already_open": {
                        "type": "boolean",
                        "description": "Whether the capture was already open, and kept.",
                    },
                    "next_cursor": _NEXT_CURSOR,
                }
            ),
            handler=serial_open,
        ),
        Tool(
            name="serial_read",
            description=(
                "Read captured lines after a cursor, optionally only those matching a regex. "
                "The cursor still advances past lines the filter leaves out."
            ),
            input_schema=_input(
                {
                    "cursor": {"type": "integer", "minimum": 0, "description": "Default 0."},
                    **_SERIAL_LIMIT,
                    "filter": {"type": "string", "description": "Python regex to search for."},
                },
                [],
            ),
            output_schema=_output(
                {"lines": {"type": "array", "items": _SERIAL_ENTRY}, "next_cursor": _NEXT_CURSOR}
            ),
            handler=serial_read,
        ),
        Tool(
            name="serial_wait",
            description=(
                "Wait for the device to print a line matching a regex after a cursor, or until "
                "the timeout. On timeout, returns the lines captured meanwhile."
            ),
            input_schema=_input(
                {
                    "pattern": {"type": "string", "description": "Python regex to search for."},
                    "timeout_s": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 600,
                        "description": f"Default {DEFAULT_WAIT_S}.",
                    },
                    "cursor": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Default: the end of the buffer, so only new lines count.",
                    },
                    **_SERIAL_LIMIT,
                },
                ["pattern"],
            ),
            output_schema=_output(
                {
                    "status": {
                        "enum": ["matched", "timeout", "closed"],
                        "description": "closed if serial_close was called while waiting.",
                    },
                    "line": {**_SERIAL_ENTRY, "type": ["object", "null"]},
                    "lines": {
                        "type": "array",
                        "items": _SERIAL_ENTRY,
                        "description": "Lines captured while waiting, unless one matched.",
                    },
                    "next_cursor": _NEXT_CURSOR,
                }
            ),
            handler=serial_wait,
        ),
        Tool(
            name="serial_write",
            description="Send text to the device, followed by a line ending, and record it.",
            input_schema=_input(
                {
                    "text": {"type": "string"},
                    "line_ending": {"type": "string", "description": "Default \\r\\n."},
                },
                ["text"],
            ),
            output_schema=_output(
                {
                    "cursor": {"type": "integer", "description": "Of the tx entry recorded."},
                    "sent": {"type": "string"},
                }
            ),
            handler=serial_write,
        ),
        Tool(
            name="serial_close",
            description="Close the serial capture and release its port.",
            input_schema=_input({}, []),
            output_schema=_output(
                {"closed": {"type": "boolean", "description": "False if none was open."}}
            ),
            handler=serial_close,
        ),
    ]
}
