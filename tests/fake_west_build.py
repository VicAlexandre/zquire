"""Stands in for Zephyr's `west build` and `west flash` in fixture workspaces, which provide
them as west extensions.

`build` records its arguments in <topdir>/fake-build/calls.jsonl, prints fake-build/output.log,
then fake-build/stderr.log to stderr if present, and exits with the code in fake-build/exit_code.
`flash` does the same with flash-calls.jsonl, flash-output.log and flash-exit_code. With
fake-build/flash-port.json it first checks the board's port is free and re-enumerates it.
`twister` records its arguments in twister-calls.jsonl, prints twister-output.log, writes
twister.json into its output directory if present, and exits with twister-exit_code.
"""

import json
import sys
import time
from pathlib import Path

import serial
from west.commands import WestCommand


class Build(WestCommand):
    def __init__(self):
        super().__init__("build", "fake west build", "Replay a canned build log.")

    def do_add_parser(self, parser_adder):
        parser = parser_adder.add_parser(self.name)
        parser.add_argument("-d", dest="build_dir")
        parser.add_argument("-b", dest="board")
        parser.add_argument("-s", dest="source_dir")
        parser.add_argument("-p", dest="pristine")
        parser.add_argument("-S", dest="snippets", action="append", default=[])
        parser.add_argument("cmake_args", nargs="*")
        return parser

    def do_run(self, args, unknown):
        fake = Path(self.topdir) / "fake-build"
        keys = ("build_dir", "board", "source_dir", "pristine", "snippets", "cmake_args")
        with (fake / "calls.jsonl").open("a") as calls:
            calls.write(json.dumps({key: getattr(args, key) for key in keys}) + "\n")
        build_dir = Path(args.build_dir)
        build_dir.mkdir(parents=True, exist_ok=True)
        (build_dir / "CMakeCache.txt").write_text("")
        sys.stdout.buffer.write((fake / "output.log").read_bytes())
        stderr = fake / "stderr.log"
        if stderr.exists():
            sys.stderr.write(stderr.read_text())
        sys.exit(int((fake / "exit_code").read_text()))


def _port_free(port: dict) -> bool:
    """Whether the board's port can be opened, as a flash tool would. Then re-enumerate it:
    remove the port's link and, after a while, point it at another device, or at none."""
    try:
        serial.Serial(port["link"], exclusive=True).close()
        free = True
    except serial.SerialException:
        free = False
    link = Path(port["link"])
    link.unlink()
    if port["device"] is not None:
        time.sleep(port["delay"])
        link.symlink_to(port["device"])
    return free


class Flash(WestCommand):
    def __init__(self):
        super().__init__("flash", "fake west flash", "Replay a canned flash log.")

    def do_add_parser(self, parser_adder):
        parser = parser_adder.add_parser(self.name)
        parser.add_argument("-d", dest="build_dir")
        parser.add_argument("-r", dest="runner")
        parser.add_argument("--no-rebuild", action="store_true")
        return parser

    def do_run(self, args, unknown):
        fake = Path(self.topdir) / "fake-build"
        call = {key: getattr(args, key) for key in ("build_dir", "runner", "no_rebuild")}
        hook = fake / "flash-port.json"
        if hook.exists():
            call["port_free"] = _port_free(json.loads(hook.read_text()))
        with (fake / "flash-calls.jsonl").open("a") as calls:
            calls.write(json.dumps({**call, "verbosity": int(self.verbosity)}) + "\n")
        sys.stdout.buffer.write((fake / "flash-output.log").read_bytes())
        sys.exit(int((fake / "flash-exit_code").read_text()))


class Twister(WestCommand):
    def __init__(self):
        super().__init__("twister", "fake west twister", "Replay a canned Twister report.")

    def do_add_parser(self, parser_adder):
        parser = parser_adder.add_parser(self.name)
        parser.add_argument("-p", dest="platform")
        parser.add_argument("-O", dest="outdir")
        parser.add_argument("-T", dest="testsuite_roots", action="append", default=[])
        parser.add_argument("-s", dest="scenarios", action="append", default=[])
        parser.add_argument("--device-testing", action="store_true")
        parser.add_argument("--device-serial")
        return parser

    def do_run(self, args, unknown):
        fake = Path(self.topdir) / "fake-build"
        keys = ("platform", "outdir", "testsuite_roots", "scenarios", "device_testing")
        call = {key: getattr(args, key) for key in (*keys, "device_serial")}
        with (fake / "twister-calls.jsonl").open("a") as calls:
            calls.write(json.dumps(call) + "\n")
        sys.stdout.buffer.write((fake / "twister-output.log").read_bytes())
        report = fake / "twister.json"
        if report.exists():
            outdir = Path(args.outdir)
            outdir.mkdir(parents=True, exist_ok=True)
            (outdir / "twister.json").write_bytes(report.read_bytes())
        sys.exit(int((fake / "twister-exit_code").read_text()))
