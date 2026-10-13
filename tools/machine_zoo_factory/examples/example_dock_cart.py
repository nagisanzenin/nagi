# SPDX-License-Identifier: Apache-2.0
"""EXAMPLE family (format reference; not a real domain). validate.py indexes it, so a re-skin of it fails V7.

A dock cart has three modes on one selector: LIFT (0), PARK (1) and DRIVE (2). The lever means different things per
mode (interlock): in DRIVE, DEC = eco step (+1 cell, free) and INC = boost (+3 cells, 1 fuel); in PARK, INC
recharges the battery (+1, holds 3). The fork moves only in LIFT (raising costs 1 battery, lowering is free).
Driving with the fork raised tips the cart; rolling past the dock drops it off the quay. Goal: at the dock with the
fork at 3 in LIFT mode.

Strata: interlock (mode_var mode: 3 modes; the lever's meaning and the crash depend on it), axes3 (selector, lever and
fork are all decisive), multibudget (fuel decides boost vs eco; battery decides whether to stop and recharge).
"""

from machine_zoo import dsl
from bv2n.zoo_new import xdsl

FAMILY = {
    "name": "example_dock_cart",
    "domain_id": "example_dock_cart",
    "batch": "example",
    "slot": 0,
    "author": "machine-zoo-factory-example",
    "title": "Dock cart with a mode selector",
    "story": (
        "A small cart must reach the dock and raise its fork. One selector picks lift, park or drive mode; the same "
        "lever means eco step, boost or recharge depending on the mode, and fuel and battery are both scarce."
    ),
    "strata": ["interlock", "axes3", "multibudget"],
    "mode_var": "mode",
    "budget_vars": ["fuel", "battery"],
}

PARAMS = {
    "near": [1, 2, 4],  # one start cell (the other is 1)
    "lowb": [0, 1],  # low battery start (the other is 3)
    "dock": [10, 9],  # dock cell
}


def build(p: dict) -> dict:
    dock = p["dock"]
    base = dsl.program(
        vars=[
            dsl.var("pos", 0, dock + 2, sorted({1, p["near"]})),
            dsl.var("mode", 0, 2, 1),
            dsl.var("height", 0, 3, [0, 3]),
            dsl.var("fuel", 0, 2, [0, 2]),
            dsl.var("battery", 0, 3, [p["lowb"], 3]),
        ],
        controls=[dsl.control("selector", [-1, 0, 1]), dsl.control("lever", [-1, 0, 1]),
                  dsl.control("forklift", [-1, 0, 1])],
        rules=[
            "mode := mode + @selector",
            "if all(mode == 2, @lever == -1): pos := pos + 1",
            "if all(mode == 2, @lever == 1, fuel >= 1): pos := pos + 3",
            "if all(mode == 2, @lever == 1, fuel >= 1): fuel := fuel - 1",
            "if all(mode == 1, @lever == 1): battery := battery + 1",
            "if all(mode == 0, @forklift == 1, battery >= 1): height := height + 1",
            "if all(mode == 0, @forklift == 1, battery >= 1): battery := battery - 1",
            "if all(mode == 0, @forklift == -1): height := height - 1",
        ],
        crash=["all(mode == 2, height >= 1)", f"pos >= {dock + 1}"],
        goal=f"all(pos == {dock}, height == 3, mode == 0)",
    )
    return xdsl.make(base)


# ---- The prose rulebook, written by the author in words (NOT generated from the program). Every identifier
# (pos, mode, height, fuel, battery, selector, lever, forklift) appears verbatim (identity name map).
GLOSSARY = {"pos": "cell along the quay", "mode": "mode on the selector", "height": "fork height",
            "fuel": "boost fuel units", "battery": "battery charges", "selector": "mode selector",
            "lever": "drive lever", "forklift": "fork control"}


def prose(p: dict) -> str:
    dock = p["dock"]
    starts = "cell 1" if p["near"] == 1 else f"cell 1 or cell {p['near']} (either is possible)"
    return f"""Dock cart, operator notes.

The cart's position, pos, is a cell on a quay numbered from 0 to {dock + 2}. It starts at {starts}, and the dock is
cell {dock}. The selector sets the mode: mode 0 is lift, 1 is park and 2 is drive. Every run starts in park (mode 1).
Each tick the operator may turn the selector one step down, leave it alone, or turn it one step up; mode never goes
below 0 or above 2.

The fork height, height, runs from 0 to 3 and starts either fully lowered (0) or fully raised (3). The tank holds fuel
from 0 to 2 units and starts with either 0 or 2. The battery holds 0 to 3 charges and starts with either {p['lowb']}
or 3. The lever and the forklift control each have three positions: back, centre and forward.

A tick is processed in this order. First the selector change takes effect on mode. Then, in drive mode (2), pulling
the lever back creeps the cart forward by 1 cell at no cost, while pushing it forward boosts pos by 3 cells and burns 1
unit of fuel; with an empty tank the boost does nothing. In park mode (1), pushing the lever forward adds 1 charge to
the battery, which never goes above 3. In lift mode (0), pushing the forklift forward raises height by 1 and uses 1
battery charge (nothing happens with a flat battery), and pulling it back lowers height by 1 for free, never below 0.
Positions that do not belong to the current mode have no effect.

The run fails at once if the cart is in drive mode while height is 1 or more (the cart tips over), or if pos reaches
cell {dock + 1} or beyond (it rolls off the quay). The job is complete when pos is cell {dock}, height is 3 and the
selector is in lift mode. Failure is checked before success: a tick that would complete the job and also meets a
failure condition counts as a failure.

Everything is shown on the panel, every command acts on the tick it is given, and nothing here is random.
"""
