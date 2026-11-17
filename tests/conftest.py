import asyncio

import pytest
from mcp import Client, MCPError

from tests.serial_device import Device
from tests.workspaces import fake_west_build, t2
from zquire.core.context import Context
from zquire.core.workspace import locate
from zquire.errors import ZquireError
from zquire.tools import TOOLS, Tool, invoke

_OBJECT = {"type": "object"}


def _echo(context, text, repeat_count=1):
    return {"text": text * repeat_count}


def _fail(context, hint=None):
    raise ZquireError("SOMETHING_FAILED", "it failed", hint)


def _crash(context):
    raise RuntimeError("boom")


def _bad_output(context):
    return {"unexpected": True}


FAKE_TOOLS = {
    tool.name: tool
    for tool in [
        Tool(
            name="echo",
            description="Repeat text.",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}, "repeat_count": {"type": "integer"}},
                "required": ["text"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
            handler=_echo,
            needs_workspace=False,
        ),
        Tool(
            name="fail",
            description="Always fail.",
            input_schema={"type": "object", "properties": {"hint": {"type": "string"}}},
            output_schema=_OBJECT,
            handler=_fail,
            needs_workspace=False,
        ),
        Tool(
            name="crash",
            description="Raise.",
            input_schema=_OBJECT,
            output_schema=_OBJECT,
            handler=_crash,
            needs_workspace=False,
        ),
        Tool(
            name="workspace_root",
            description="Needs a workspace.",
            input_schema=_OBJECT,
            output_schema=_OBJECT,
            handler=lambda context: {"root": str(context.workspace.root)},
        ),
        Tool(
            name="bad_output",
            description="Break the output schema.",
            input_schema=_OBJECT,
            output_schema={"type": "object", "additionalProperties": False},
            handler=_bad_output,
            needs_workspace=False,
        ),
    ]
}


NO_WORKSPACE = Context(None)


@pytest.fixture(autouse=True)
def isolated_west_config(tmp_path, monkeypatch):
    for level in ("GLOBAL", "SYSTEM"):
        monkeypatch.setenv(f"WEST_CONFIG_{level}", str(tmp_path / f"west-{level.lower()}.cfg"))


def pytest_bdd_apply_tag(tag, function):
    pytest.mark.requirement(tag)(function)
    return True


@pytest.fixture
def device():
    device = Device()
    yield device
    device.close()


@pytest.fixture
def ready_workspace(tmp_path, device, request, monkeypatch):
    """A T2 workspace with an active profile that the fake `west build` can build, and a
    serial capture open on a pseudo-terminal."""
    root = fake_west_build(t2(tmp_path / "ws"))
    context = Context(locate(root))
    invoke(TOOLS["build"], {"application": "application", "board": "b"}, context)
    with monkeypatch.context() as directory:
        # The capture process inherits it, and under mutmut needs it to find mutmut's config.
        directory.chdir(request.config.invocation_params.dir)
        invoke(TOOLS["serial_open"], {"port": device.port}, context)
    yield root
    invoke(TOOLS["serial_close"], {}, context)


@pytest.fixture
def capture(tmp_path, device):
    """A T2 workspace with a serial capture open on a pseudo-terminal."""
    root = t2(tmp_path / "ws")
    context = Context(locate(root))
    invoke(TOOLS["serial_open"], {"port": device.port}, context)
    yield root
    invoke(TOOLS["serial_close"], {}, context)


@pytest.fixture
def fake_tools():
    return FAKE_TOOLS


def call_mcp(server, name, arguments=None):
    async def call():
        async with Client(server) as client:
            try:
                return await client.call_tool(name, arguments)
            except MCPError as error:
                return error

    # Raised outside the client so the error is not wrapped in its task group's ExceptionGroup.
    outcome = asyncio.run(call())
    if isinstance(outcome, MCPError):
        raise outcome
    return outcome


def list_mcp(server):
    async def list_tools():
        async with Client(server) as client:
            return await client.list_tools()

    return asyncio.run(list_tools())
