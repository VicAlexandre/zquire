# 11. Runtime stats run ZView's one-shot dump through west

## Context

ZV-01 asks `runtime_stats` to run a one-shot ZView dump against a profile's ELF and return threads and heaps as structured data. ZV-02–04 name the thread and heap fields and the `stack_risk` flag. ZV-05–07 check the build's Kconfig before running ZView, and ZV-08 asks for a manifest snippet when ZView is missing. ZV-09 derives ZView's runner and target from the board's runner configuration, with overrides. FLS-07 keeps flashing and dumping apart (ADR 0010). ZView is a Zephyr module (`wkhadgar/zview`) that adds `west zview`. Its `dump --json` subcommand reads one polling frame through a debug probe, prints it as one line of JSON on stdout, and writes notices to stderr. Its rows are its own dataclasses, and change as ZView grows.

## Decision

- `runtime_stats` runs `west zview dump --json -d <build dir>`, with `-r` and `-t` when zquire knows them, holding the board, with a 60 s limit. The frame is the last line of output that parses as JSON.
- Before running it, zquire reads the build's `zephyr/.config`. A required option that is not `=y` fails with `ZVIEW_PREREQ`, listing the `CONFIG_…=y` lines to add. A missing optional option gives an `option_disabled` warning.
- The runner is the override, else `flash-runner` from `runners.yaml`. The target is the override, else the value the board passes that runner as `--device` (J-Link) or `--target` (pyOCD). For other runners, ZView fills in what zquire leaves unset from the build directory.
- `west: unknown command "zview"` in the output means ZView is not installed, and gives `ZVIEW_MISSING` with the project to add to `west.yml`. Any other failure gives `ZVIEW_FAILED` with the log's last 30 lines.
- zquire maps ZView's rows to its own fields. A thread's state is named from its `thread_state` bits. Its CPU percent is its share of all CPU time, idle included. Its watermark is rounded to 0.1 %, and it is flagged when the rounded value reaches the threshold.

## Alternatives

- **Importing ZView's Python package** would skip a process, but would tie zquire to ZView's internals and to pyOCD and J-Link's libraries. It would also stop zquire from running ZView in a workspace with a different Python environment.
- **Leaving runner and target to ZView** would work, but the result could not say which probe it used, and ZV-09 asks zquire to derive them.
- **Reading `zephyr.elf` for the prerequisites** would also work on a moved build, but `.config` is what the build used, and is plain text.

## Consequences

zquire reads only ZView's `threads` and `heaps`, so new ZView fields and kinds pass unseen until zquire maps them. A ZView that renames a field breaks the mapping, which the fake's rows, copied from ZView's `to_json`, will not show.
