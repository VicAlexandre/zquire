# 1. One tool registry drives the MCP server and the CLI

## Context

NFR-01 requires every capability as an MCP tool and as an equivalent `zquire <command>` CLI subcommand printing the same JSON. NFR-02 fixes the result and error shapes. Keeping two front ends in step by hand drifts.

## Decision

Each tool is declared once in `zquire.tools.TOOLS`: name, description, input schema, output schema, handler. `zquire.tools.invoke` validates arguments (failing with `INVALID_ARGUMENT`), runs the handler and checks the result against the output schema.

- `zquire.mcp_server` lists and calls tools from the registry. A `ZquireError` becomes `isError: true` with its JSON; an unknown tool is a JSON-RPC `INVALID_PARAMS` error; any other exception is a server fault.
- `zquire.cli` builds one subcommand per tool, one `--option` per input property, and prints the same JSON, exiting 1 on a `ZquireError`.

Dependencies point inward: front ends (MCP, CLI, west extension) → `tools` → `core` → adapters. `core` never imports a front end. The one front-end-to-front-end edge is `zquire serve`, through which the CLI starts the MCP server.

## Consequences

A tool added to the registry appears in both front ends with no extra code. Handlers raise `ZquireError` instead of formatting errors themselves. CLI options are derived from JSON Schema, so non-string options are given as JSON (`--threads '["main"]'`).
