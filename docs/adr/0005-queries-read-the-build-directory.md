# 5. Kconfig and devicetree queries read the build directory

## Context

WS-05 asks for a Kconfig symbol's value, whether it is set, and its unmet dependencies, from the active build's `.config` and Kconfig tree. WS-06 asks for a devicetree node's status, compatible and properties from the build's processed devicetree. Values alone are in `.config`, but dependencies need the whole Kconfig tree, and Zephyr loads that tree only with an environment of about 130 variables (board, SoC, toolchain, module directories) that CMake computes during the build. The build keeps that environment in one place: the command of its `menuconfig` target.

## Decision

- `adapters/kconfig` reads the environment and the top Kconfig file from the `menuconfig` command in `build.ninja`, or in `CMakeFiles/menuconfig.dir/build.make` for Makefile builds. It runs `adapters/kconfig_helper.py` with that environment under `sys.executable`. The helper imports the `kconfiglib` of the Zephyr checkout that made the build, loads the tree and the build's `.config`, and prints the symbol as JSON.
- The unmet dependencies are the `&&` terms of each definition's conditions, including enclosing menus and `if`s, that evaluate to `n`. They are listed only when no definition's conditions are met. A symbol defined for hundreds of SoCs would otherwise return its whole `||` expression.
- `core/devicetree` reads `zephyr/zephyr.dts`, the merged tree dtlib writes after applying overlays. It keeps property values as written.
- Tests install `kconfiglib` from PyPI to stand in for Zephyr's copy, and write small Kconfig trees, `.config` files and `zephyr.dts` files.

## Alternatives

- **Rebuilding the Kconfig environment from `CMakeCache.txt`** misses variables that are not cached, such as `HWM_SCHEME` and `KCONFIG_BOARD_DIR`.
- **Loading `kconfiglib` in-process** would mean setting the build's variables in zquire's own environment, and importing a different Zephyr's scripts for each workspace.
- **Unpickling `edt.pickle`** gives values typed by their bindings, but needs Zephyr's devicetree package at the version that wrote the pickle. It only covers nodes that have a binding.

## Consequences

Each Kconfig query loads the tree, about 1.5 s on Zephyr 4.5. Loading it relies on the `menuconfig` command keeping its current form. If the form changes, queries fail with `NO_BUILD` and say the target is missing. Devicetree values are untyped text such as `< 0x40003000 0x1000 >`, which the agent reads as written. A failed build can still be queried once it has produced `.config` or `zephyr.dts`.
