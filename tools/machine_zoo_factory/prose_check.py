#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Blind sufficiency check: is the reviewer's program, written from the prose ALONE, transition-exact with the
family's program for the same params (identity name map)?

    python3 prose_check.py <family.py> <reading.txt> [--params '{"a": 1, "b": 2}'] [--profile train]

reading.txt = the reviewer's program in the rulebook text format (docs/DSL_REFERENCE.md §2 layout: the mz-1
rulebook, plus the `extension mz-1x:` block when there is delay or hidden state). Default params = the family's first
grid point in the profile's instance order (usually its first kept instance). Prints EXACT or DIFF <first
difference>; exit 0 only on EXACT.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import famgate as fg  # noqa: E402


def check(family: str, reading_text: str, params: dict | None = None, profile: str = "train") -> tuple[bool, str]:
    mod = fg.load_module(family)
    name = os.path.splitext(os.path.basename(family))[0]
    p = params if params is not None else fg.instance_order(name, mod.PARAMS, fg.PROFILES[profile].inst_salt)[0]
    px = fg.as_px(mod.build(dict(p)))
    tag = f"params={json.dumps(p, sort_keys=True)}"
    try:
        mine = fg.parse_rulebook_x(reading_text)
    except Exception as ex:  # noqa: BLE001
        return False, f"DIFF reading does not parse: {type(ex).__name__}: {ex} {tag}"
    d = fg.transition_diff(px, mine)
    return d is None, ("EXACT" if d is None else f"DIFF {d}") + f" {tag}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("family")
    ap.add_argument("reading")
    ap.add_argument("--params", default=None, help="JSON grid point (default: first in instance order)")
    ap.add_argument("--profile", default="train", choices=sorted(fg.PROFILES))
    a = ap.parse_args(argv)
    with open(a.reading) as f:
        text = f.read()
    ok, msg = check(a.family, text, json.loads(a.params) if a.params else None, a.profile)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
