# 2. Install as a west project and as a pip package

## Context

NFR-08 requires installing zquire as a west project run with `west zquire`, and as a `pip install zquire` package providing `zquire`, both running the same core.

## Decision

- Source lives in `src/zquire`. `pyproject.toml` exposes `zquire = "zquire.cli:main"`.
- `scripts/west-commands.yml` registers `west zquire`. `scripts/west_commands/zquire_cmd.py` puts the checkout's `src/` first on `sys.path` and delegates to `zquire.cli`, so a west checkout runs without installing zquire itself.
- Runtime dependencies are listed once, in `scripts/requirements.txt`. `pyproject.toml` reads them from there, and `zephyr/module.yml` points `west packages pip` at the same file.

## Consequences

Both routes run the same `zquire.cli`. With a pip-installed zquire also present, `west zquire` uses the checkout. `west` is not a runtime dependency; only the extension file imports it.
