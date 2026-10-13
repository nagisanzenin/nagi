# SPDX-License-Identifier: Apache-2.0
"""Runtime wiring: the exact Machine Zoo engine (DSL, interpreter, exact teacher) comes from this repository's
``nagi.burst2._rt`` package (numpy + scipy, no torch). Those modules are the research engine vendored with import
paths rewritten only (see ``src/nagi/burst2/_rt/MANIFEST.json``), so labels and gate values are the same.

Family files import ``from machine_zoo import dsl`` and ``from bv2n.zoo_new import xdsl`` (the published Machine Zoo
families do too). This module registers those two names as aliases of the vendored modules, so a family file runs
unchanged here and in the published dataset.
"""

from __future__ import annotations

import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)
REPO_SRC = os.path.abspath(os.path.join(TOOL_DIR, "..", "..", "src"))
if os.path.isdir(os.path.join(REPO_SRC, "nagi")) and REPO_SRC not in sys.path:
    sys.path.insert(0, REPO_SRC)  # a clone works without `pip install`; nagi imports torch lazily, never here

_RT = "nagi.burst2._rt"
_ALIASES = (
    ("machine_zoo", f"{_RT}.machine_zoo"),
    ("machine_zoo.dsl", f"{_RT}.machine_zoo.dsl"),
    ("bv2n", f"{_RT}.bv2n"),
    ("bv2n.zoo_new", f"{_RT}.bv2n.zoo_new"),
    ("bv2n.zoo_new.xdsl", f"{_RT}.bv2n.zoo_new.xdsl"),
)


def install_aliases() -> None:
    for alias, real in _ALIASES:
        try:
            mod = importlib.import_module(real)
        except ImportError as ex:
            nagi = sys.modules.get("nagi")
            raise ImportError(f"the factory needs {real} from this repository's src/ (got nagi from "
                              f"{getattr(nagi, '__file__', None)}): install this repository (pip install -e .) or "
                              f"run with PYTHONPATH={REPO_SRC}") from ex
        have = sys.modules.get(alias)
        if have is None:
            sys.modules[alias] = mod
        elif have is not mod:
            raise ImportError(f"a different module {alias!r} ({getattr(have, '__file__', '?')}) is already imported; "
                              f"the factory needs {real}. Run the factory in a fresh Python process.")


install_aliases()

from nagi.burst2._rt.bv2n.zoo_new import xdsl, xteacher  # noqa: E402,F401
from nagi.burst2._rt.machine_zoo import dsl, interp, tokens  # noqa: E402,F401
