import argparse
import sys
from pathlib import Path

import pytest

pytest.importorskip("west")

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts" / "west_commands"))

from zquire_cmd import ZquireCommand  # noqa: E402


def west_run(argv):
    command = ZquireCommand()
    parser = command.do_add_parser(argparse.ArgumentParser().add_subparsers())
    with pytest.raises(SystemExit) as raised:
        command.do_run(parser.parse_args(argv), [])
    return raised.value.code


def test_west_zquire_status_prints_the_cli_json(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert west_run(["status"]) == 0
    west_output = capsys.readouterr().out
    from zquire import cli

    cli.main(["status"])
    assert west_output == capsys.readouterr().out


def test_west_extension_registers_zquire():
    assert ZquireCommand().name == "zquire"
