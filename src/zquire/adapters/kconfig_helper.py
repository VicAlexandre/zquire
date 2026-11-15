"""Run by adapters.kconfig in the environment of a build's menuconfig target.

It imports the kconfiglib of the Zephyr checkout that made the build, so it must not
import zquire. Prints the symbol as JSON, or null when the tree does not define it.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.environ["srctree"], "scripts", "kconfig"))  # noqa: SIM112

import kconfiglib  # noqa: E402


def describe(kconf, name):
    symbol = kconf.syms.get(name)
    if symbol is None or not symbol.nodes:
        return None
    unmet = []
    # A symbol defined in several places depends on any one definition's conditions.
    if kconfiglib.expr_value(symbol.direct_dep) == 0:
        for node in symbol.nodes:
            for term in kconfiglib.split_expr(node.dep, kconfiglib.AND):
                text = kconfiglib.expr_str(term)
                if kconfiglib.expr_value(term) == 0 and text not in unmet:
                    unmet.append(text)
    return {
        "name": name,
        "type": kconfiglib.TYPE_TO_STR[symbol.orig_type],
        "value": symbol.str_value,
        "set": symbol.config_string.startswith(kconf.config_prefix),
        "unmet_dependencies": unmet,
    }


def main(kconfig_file, name):
    out = sys.stdout
    # Kconfig files can print while they load; only the JSON may reach stdout.
    sys.stdout = sys.stderr
    kconf = kconfiglib.Kconfig(kconfig_file, warn=False)
    kconf.load_config(os.environ["KCONFIG_CONFIG"])
    json.dump(describe(kconf, name), out)


if __name__ == "__main__":
    main(*sys.argv[1:])
