# 6. Flash runs `west -v flash --no-rebuild` and reads no-device errors from its log

## Context

FLS-01 asks `flash` to run `west flash` for a profile, and BLD-18 says activating and flashing a profile must not rebuild it. FLS-03 and FLS-04 tie flashing to the profile's last successful build and its staleness (BLD-23). FLS-06 asks for `NO_DEVICE`, carrying the runner's own message, when no probe or board is found. `west flash` rebuilds the build directory before flashing unless told not to. Each runner wraps a vendor tool (OpenOCD, J-Link Commander, nrfutil and others), and a missing probe shows up only as that tool's output and a non-zero exit. Some runners hide that output unless west is verbose. For emulated boards, the `qemu`, `native` and `arc-nsim` runners implement flash by starting the emulator, which runs until it is stopped.

## Decision

- `core/flash` runs `west -v flash --no-rebuild -d <build_dir> [-r <runner>]` through `adapters/west.run_west`, the same way as `build` (ADR 0004), logging to `.zquire/logs/<profile>-flash.log`. `--no-rebuild` needs Zephyr 4.3 or later, which NFR-12's 4.4 floor covers.
- It refuses with `NOT_FLASHABLE`, before running west, when the runner is an emulator: the `runner` argument, or else the build's `flash-runner` in `zephyr/runners.yaml`.
- It flashes only a profile whose state records a successful build and whose build directory still exists. Otherwise it fails with `NO_BUILD` before running west. Staleness is judged against that successful build, which gives a `stale_build` warning, or `STALE_BUILD` with `require_fresh`.
- A failed flash becomes `NO_DEVICE` when its log contains a known no-device message. The first matching line is quoted in the error. Every other failure is a result with status `failure` and the last 30 lines of the log. The runner used is read from west's `using runner` line.
- The known messages are recorded output from OpenOCD with an ST-Link and from J-Link Commander, plus the message Zephyr's own Nordic runners raise.

## Alternatives

- **Letting `west flash` rebuild** would break BLD-18 and could flash firmware zquire never reported a build result for.
- **Probing for devices before flashing** (`nrfutil device list`, `JLinkExe ShowEmuList`) needs a probe-listing command for each runner and still races with the flash itself.
- **A timeout on every flash** would also stop emulators, but no requirement says how long a real flash may take, and an emulator would still report `success` when stopped.
- **Treating every failed flash as `NO_DEVICE`** would hide real failures, such as a missing tool or a locked chip.

## Consequences

Runners whose no-device message is not in the list report a plain `failure` with the excerpt, which still shows the message. New messages are added from recorded logs. Verbose output makes the log longer, but the result carries only its last 30 lines. Flashing holds the tool call until west finishes, with no progress reporting or cancellation.
