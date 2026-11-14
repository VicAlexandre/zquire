import json

import jsonschema
import pytest
from mcp import MCPError, types

from tests.conftest import NO_WORKSPACE, call_mcp, list_mcp
from zquire.mcp_server import build_server
from zquire.tools import TOOLS


def test_every_registered_tool_is_listed_with_its_schemas():
    listed = {tool.name: tool for tool in list_mcp(build_server(NO_WORKSPACE)).tools}
    assert listed.keys() == TOOLS.keys()
    for name, tool in TOOLS.items():
        assert listed[name].input_schema == tool.input_schema
        assert listed[name].output_schema == tool.output_schema
        assert listed[name].description == tool.description


@pytest.mark.parametrize("name", TOOLS)
def test_registered_tools_without_required_arguments_succeed(name):
    if TOOLS[name].input_schema.get("required"):
        pytest.skip("needs arguments")
    result = call_mcp(build_server(NO_WORKSPACE), name)
    assert not result.is_error
    jsonschema.validate(result.structured_content, TOOLS[name].output_schema)


def test_success_mirrors_structured_content_as_text(fake_tools):
    result = call_mcp(
        build_server(NO_WORKSPACE, fake_tools), "echo", {"text": "hi", "repeat_count": 2}
    )
    assert not result.is_error
    assert result.structured_content == {"text": "hihi"}
    assert len(result.content) == 1
    assert json.loads(result.content[0].text) == result.structured_content


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({}, {"code": "SOMETHING_FAILED", "message": "it failed"}),
        ({"hint": "retry"}, {"code": "SOMETHING_FAILED", "message": "it failed", "hint": "retry"}),
    ],
    ids=["without-hint", "with-hint"],
)
def test_tool_failure_is_an_error_result(fake_tools, arguments, expected):
    result = call_mcp(build_server(NO_WORKSPACE, fake_tools), "fail", arguments)
    assert result.is_error
    assert result.structured_content is None
    assert json.loads(result.content[0].text) == expected


def test_invalid_arguments_are_a_tool_error_not_a_protocol_error(fake_tools):
    result = call_mcp(build_server(NO_WORKSPACE, fake_tools), "echo", {"text": 3})
    assert result.is_error
    assert json.loads(result.content[0].text)["code"] == "INVALID_ARGUMENT"


def test_missing_arguments_are_treated_as_empty(fake_tools):
    result = call_mcp(build_server(NO_WORKSPACE, fake_tools), "echo")
    assert json.loads(result.content[0].text)["code"] == "INVALID_ARGUMENT"


def test_unknown_tool_is_a_protocol_error(fake_tools):
    with pytest.raises(MCPError) as raised:
        call_mcp(build_server(NO_WORKSPACE, fake_tools), "nope")
    assert raised.value.error.code == types.INVALID_PARAMS
    assert raised.value.error.message == "Unknown tool: nope"


@pytest.mark.parametrize("name", ["crash", "bad_output"])
def test_server_fault_is_a_protocol_error(fake_tools, name):
    with pytest.raises(MCPError) as raised:
        call_mcp(build_server(NO_WORKSPACE, fake_tools), name)
    assert raised.value.error.code == types.INTERNAL_ERROR
