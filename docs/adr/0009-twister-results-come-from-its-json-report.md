# 9. Twister runs through west and its results come from its JSON report

## Context

TWS-01 asks `twister` to run Twister on test paths or scenario names, for the active profile's board or a given platform, optionally on attached hardware. TWS-02–05 ask for suite counts, failed cases with their reason and a log excerpt of at most 40 lines, build failures as build diagnostics (BLD-03), and the paths of Twister's output directory and JSON report. TWS-06 will release the serial capture during device testing, and TWS-07 will stop a run that exceeds its timeout and still return what finished. Twister prints a progress line per suite, but its format changes between releases and depends on its verbosity.

## Decision

- `twister` runs Zephyr's `west twister` command, with `-T` for each path, `-s` for each scenario and `-p` for the platform. Device testing adds `--device-testing --device-serial`, on the only USB serial port unless one is given.
- Twister writes into `.zquire/twister`, which zquire removes before each run, so a report left from the last run is never read as this one's. Its output goes to `.zquire/logs/twister.log`.
- Results come only from `twister.json`. Suites are counted by their status: `passed`, `failed`, `error`, `skipped`, and `not run`, which is how Twister reports a suite it only built. Filtered suites are not counted.
- An errored suite whose reason starts with `Build failure` or `CMake build failure` is a build failure. Its log, which Twister fills from `build.log`, goes through the build tool's diagnostics parser.
- Every other failed or errored suite gives one failure for each failed or errored case. A suite that failed outside any case, for example by timing out before a case started, gives one failure with no case. The excerpt is the case's own output, which Twister keeps from the case's `START` line to its `FAIL` line, or else the suite's log. Either way, it is the last 40 lines.
- When Twister writes no report, for example when its arguments are wrong, its counts are zero and the result carries the last 30 lines of its log.

## Alternatives

- **Parsing Twister's progress lines** would give results while it runs, but they change with its verbosity and between Zephyr releases. The JSON report is what Twister's own JUnit reports are made from.
- **Running Twister's `twister_main` in zquire's process** would skip west, but Twister's code comes from the Zephyr being tested, and would share zquire's logging, signals and imports.
- **Keeping earlier runs** as Twister does by default, in `twister-out.1` and so on, would let an agent compare runs, but nothing asks for it, and each run can hold a build per suite.

## Consequences

Each run deletes the last one's output. TWS-07 can stop Twister with SIGINT, after which Twister still writes its report for what finished. The excerpt of a suite with no failed case ends where the suite's log ends, which for a crash or a hang is where it stopped.
