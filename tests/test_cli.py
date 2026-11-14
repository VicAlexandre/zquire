import argparse
import json

import pytest

from tests.conftest import NO_WORKSPACE, call_mcp
from tests.workspaces import t2
from zquire import __version__, cli
from zquire.mcp_server import build_server
from zquire.tools import TOOLS


@pytest.fixture(autouse=True)
def outside_any_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def run_cli(tools, argv, capsys):
    parser = argparse.ArgumentParser(prog="zquire")
    cli.add_commands(parser, tools)
    exit_code = cli.run(parser.parse_args(argv), tools)
    return exit_code, json.loads(capsys.readouterr().out)


@pytest.mark.parametrize(
    ("argv", "name", "arguments", "exit_code"),
    [
        (
            ["echo", "--text", "hi", "--repeat-count", "2"],
            "echo",
            {"text": "hi", "repeat_count": 2},
            0,
        ),
        (["fail"], "fail", {}, 1),
        (["fail", "--hint", "retry"], "fail", {"hint": "retry"}, 1),
        (
            ["echo", "--text", "hi", "--repeat-count", "two"],
            "echo",
            {"text": "hi", "repeat_count": "two"},
            1,
        ),
    ],
    ids=["success", "error", "error-with-hint", "invalid-argument"],
)
def test_cli_prints_the_same_json_as_mcp(fake_tools, capsys, argv, name, arguments, exit_code):
    mcp_result = call_mcp(build_server(NO_WORKSPACE, fake_tools), name, arguments)
    assert run_cli(fake_tools, argv, capsys) == (exit_code, json.loads(mcp_result.content[0].text))


def test_string_option_is_not_parsed_as_json(fake_tools, capsys):
    assert run_cli(fake_tools, ["echo", "--text", "123"], capsys) == (0, {"text": "123"})


def test_non_string_option_is_parsed_as_json(fake_tools, capsys):
    assert run_cli(fake_tools, ["echo", "--text", "a", "--repeat-count", "3"], capsys) == (
        0,
        {"text": "aaa"},
    )


def test_absent_option_is_not_passed(fake_tools, capsys):
    assert run_cli(fake_tools, ["echo", "--text", "a"], capsys) == (0, {"text": "a"})


def test_missing_required_option_is_invalid_argument(fake_tools, capsys):
    exit_code, payload = run_cli(fake_tools, ["echo"], capsys)
    assert (exit_code, payload["code"]) == (1, "INVALID_ARGUMENT")


@pytest.mark.parametrize("name", TOOLS)
def test_every_registered_tool_is_a_subcommand(name, capsys):
    if TOOLS[name].input_schema.get("required"):
        pytest.skip("needs arguments")
    assert cli.main([name]) == 0
    capsys.readouterr()


def test_status_prints_version(capsys):
    assert cli.main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["zquire_version"] == __version__


def test_server_fault_propagates_instead_of_printing_a_tool_error(fake_tools, capsys):
    with pytest.raises(RuntimeError, match="boom"):
        run_cli(fake_tools, ["crash"], capsys)
    assert capsys.readouterr().out == ""


def test_serve_starts_the_mcp_server(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "serve", calls.append)
    assert cli.main(["serve"]) == 0
    assert len(calls) == 1


@pytest.mark.parametrize("argv", [[], ["nope"]], ids=["no-command", "unknown-command"])
def test_bad_command_is_a_usage_error(argv):
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2


def test_workspace_option_selects_the_workspace(tmp_path, capsys):
    root = t2(tmp_path / "ws")
    assert cli.main(["--workspace", str(root), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["workspace"]["root"] == str(root)


def test_workspace_option_must_name_the_topdir(tmp_path, capsys):
    root = t2(tmp_path / "ws")
    assert cli.main(["--workspace", str(root / "application"), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["workspace"] is None


def test_workspace_is_found_from_the_working_directory(tmp_path, monkeypatch, capsys):
    root = t2(tmp_path / "ws")
    monkeypatch.chdir(root / "application")
    assert cli.main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["workspace"]["root"] == str(root)


def test_no_workspace_is_reported_from_the_cli(fake_tools, capsys):
    assert run_cli(fake_tools, ["workspace_root"], capsys) == (
        1,
        {
            "code": "NO_WORKSPACE",
            "message": "No west workspace was found.",
            "hint": "Run `west init`, or pass --workspace with the path of a west workspace.",
        },
    )


def test_serve_receives_the_located_workspace(tmp_path, monkeypatch):
    root = t2(tmp_path / "ws")
    contexts = []
    monkeypatch.setattr(cli, "serve", contexts.append)
    cli.main(["--workspace", str(root), "serve"])
    assert contexts[0].workspace.root == root
