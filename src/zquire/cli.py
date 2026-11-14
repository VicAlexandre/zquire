import argparse
import json
from collections.abc import Callable

from zquire.errors import ZquireError
from zquire.mcp_server import serve
from zquire.tools import TOOLS, Tool, invoke

_COMMAND = "zquire_command"


def _option_parser(schema: dict) -> type[str] | Callable[[str], object]:
    if schema.get("type") == "string":
        return str
    return _json_or_raw


def _json_or_raw(value: str) -> object:
    # Unparseable input is passed through so schema validation reports it as INVALID_ARGUMENT.
    try:
        return json.loads(value)
    except ValueError:
        return value


def add_commands(parser: argparse.ArgumentParser, tools: dict[str, Tool] = TOOLS) -> None:
    commands = parser.add_subparsers(dest=_COMMAND, required=True, metavar="COMMAND")
    commands.add_parser("serve", help="Run the MCP server over stdio.")
    for tool in tools.values():
        command = commands.add_parser(tool.name, help=tool.description)
        for name, schema in tool.input_schema.get("properties", {}).items():
            command.add_argument(
                "--" + name.replace("_", "-"),
                dest=name,
                type=_option_parser(schema),
                default=argparse.SUPPRESS,
            )


def run(args: argparse.Namespace, tools: dict[str, Tool] = TOOLS) -> int:
    command = getattr(args, _COMMAND)
    if command == "serve":
        serve()
        return 0
    tool = tools[command]
    arguments = {
        name: getattr(args, name)
        for name in tool.input_schema.get("properties", {})
        if hasattr(args, name)
    }
    try:
        payload, exit_code = invoke(tool, arguments), 0
    except ZquireError as error:
        payload, exit_code = error.to_dict(), 1
    print(json.dumps(payload))
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zquire")
    add_commands(parser)
    return run(parser.parse_args(argv))
