# 4. Build runs `west build` in a subprocess and parses its log

## Context

BLD-01 asks for `west build`, with its handling of boards, pristine builds, snippets and CMake arguments. BLD-02 to BLD-08 ask for classified, located and deduplicated diagnostics and per-region memory usage. BLD-09 asks for the full log on disk. `west build` is an extension command that lives in Zephyr's `scripts/`, not in the west package. The real work happens in CMake, ninja, the compiler, the linker, and Zephyr's Kconfig and devicetree scripts.

## Decision

- `adapters/west.run_build` runs `sys.executable -m west build` from the topdir, with stdout and stderr interleaved into `.zquire/logs/<profile>-build.log`. `sys.executable` is the interpreter zquire runs in: west's own under `west zquire`, and otherwise one that has west as a dependency (ADR 0003). The `build` command itself comes from the workspace.
- `core/diagnostics` classifies the log line by line, with one pattern per tool's output format: GCC and GNU ld, Zephyr's Kconfig and devicetree scripts, and CMake. It also reads the linker's memory usage table. CMake errors are dropped when any other error was found, since Zephyr wraps a failing Kconfig or devicetree step in a CMake error of its own.
- Parser tests run against real Zephyr 4.5.0-rc1 logs recorded in `tests/logs/`. Integration tests give fixture workspaces a stand-in `build` extension command, so they run real west without a Zephyr build.

## Alternatives

- **Calling Zephyr's `build` command class in-process** would import Zephyr's scripts into zquire and still not capture the output of the tools it spawns.
- **Running CMake and ninja directly** means reimplementing `west build`'s argument and pristine logic.
- **Structured compiler output** (`-fdiagnostics-format=json`, SARIF) changes the user's build flags and covers only the compiler, not Kconfig, devicetree, CMake or the linker.

## Consequences

The classifier depends on output formats that tools may change. New formats are added from recorded logs, and anything unrecognised still produces a failure with the last 60 lines (BLD-05). Zephyr's Python requirements must be installed in zquire's environment, as for any `west build`. An isolated install such as pipx fails at the first Zephyr script, which shows up as an `unknown` diagnostic. A build holds the tool call until it finishes, with no progress reporting or cancellation.
