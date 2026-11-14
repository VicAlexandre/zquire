import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from zquire import __version__
from zquire.tools import TOOLS

_ZQUIRE = shutil.which("zquire", path=str(Path(sys.executable).parent))
pytestmark = pytest.mark.skipif(_ZQUIRE is None, reason="zquire is not installed")


def test_pip_entry_point_runs_status(tmp_path):
    completed = subprocess.run(
        [_ZQUIRE, "status"], capture_output=True, text=True, check=True, cwd=tmp_path
    )
    assert json.loads(completed.stdout)["zquire_version"] == __version__


def test_mcp_over_stdio(tmp_path):
    server = StdioServerParameters(command=_ZQUIRE, args=["serve"], cwd=tmp_path)

    async def session():
        async with Client(server) as client:
            return await client.list_tools(), await client.call_tool("status")

    listed, result = asyncio.run(session())
    assert {tool.name for tool in listed.tools} == TOOLS.keys()
    assert result.structured_content["zquire_version"] == __version__
