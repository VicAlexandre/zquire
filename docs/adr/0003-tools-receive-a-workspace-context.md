# 3. Tools receive a workspace context located at startup

## Context

WS-01 locates the west workspace when zquire starts, from the working directory or `--workspace`. WS-02 requires a degraded mode in which every tool except `status` fails with `NO_WORKSPACE`. Leaving that check to each handler invites a tool that forgets it.

## Decision

- The CLI (and through it `west zquire` and `zquire serve`) locates the workspace once and builds a `Context` holding it, or `None`.
- Handlers take the context as their first argument: `handler(context, **arguments)`.
- `Tool.needs_workspace` defaults to true. `invoke` raises `NO_WORKSPACE` for such a tool when the context has no workspace, before validating arguments. Only `status` sets it to false.
- West is reached only through `zquire.adapters.west`. It reads the manifest with `ImportFlag.IGNORE_PROJECTS`, so it sees only the projects the workspace's own manifest declares and never runs git.

## Consequences

Degraded mode holds for every future tool without per-tool code. The workspace is fixed for the life of the process: running `west init` later needs a restart. `west` becomes a runtime dependency of the pip package.
