import sys
from pathlib import Path

from west.commands import WestCommand

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from zquire import cli  # noqa: E402


class ZquireCommand(WestCommand):
    def __init__(self) -> None:
        super().__init__(
            "zquire",
            "MCP server and CLI for agent-driven Zephyr development",
            "Run zquire's tools from west. `west zquire serve` starts the MCP server over stdio.",
        )

    def do_add_parser(self, parser_adder):
        parser = parser_adder.add_parser(self.name, help=self.help, description=self.description)
        cli.add_commands(parser)
        return parser

    def do_run(self, args, unknown) -> None:
        sys.exit(cli.run(args))
