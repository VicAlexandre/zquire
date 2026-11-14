import asyncio
import json

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import MCPError

from zquire import __version__
from zquire.errors import ZquireError
from zquire.tools import TOOLS, Tool, invoke


def _as_text(payload: dict) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(payload))]


def build_server(tools: dict[str, Tool] = TOOLS) -> Server:
    async def list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=tool.name,
                    description=tool.description,
                    input_schema=tool.input_schema,
                    output_schema=tool.output_schema,
                )
                for tool in tools.values()
            ]
        )

    async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        tool = tools.get(params.name)
        if tool is None:
            raise MCPError(types.INVALID_PARAMS, f"Unknown tool: {params.name}")
        try:
            result = invoke(tool, params.arguments or {})
        except ZquireError as error:
            return types.CallToolResult(content=_as_text(error.to_dict()), is_error=True)
        return types.CallToolResult(content=_as_text(result), structured_content=result)

    return Server("zquire", version=__version__, on_list_tools=list_tools, on_call_tool=call_tool)


def serve() -> None:
    async def run() -> None:
        server = build_server()
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())
