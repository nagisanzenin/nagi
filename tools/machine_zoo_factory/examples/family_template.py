# SPDX-License-Identifier: Apache-2.0
"""TEMPLATE family: copy this file to <job>/FAMILIES/<your_name>.py and REPLACE the machine with your own.

It is a complete, passing family (stratum `long`), kept as small as possible so every part of the format is easy to
see. validate.py indexes examples/, so a copy that only renames things or changes numbers fails V7 (near-duplicate):
change the mechanism, not the skin.

Machine: a tram must stop exactly at a platform. One throttle (brake / coast / power) changes the speed by
one per tick; the speed moves the tram. Running into the buffer at the end of the track is a failure. The
decision that matters is WHEN to start braking: the stopping distance grows with the speed, so a policy that looks
only a few ticks ahead brakes too late or stops short (`long`: the oracle needs >= 20 ticks at the median).

Docstring rule of thumb: say what the machine is, which strata it carries and why each one is load-bearing.
"""

# The ONLY allowed imports in a family file: machine_zoo.dsl, bv2n.zoo_new.xdsl, math, itertools (and __future__).
# No I/O, no randomness, no time, no eval/exec, no print, no hash()/id(), no dunder attributes.
from machine_zoo import dsl
from bv2n.zoo_new import xdsl

FAMILY = {
    "name": "family_template",          # must equal the file stem; [a-z][a-z0-9_]{2,40}; unique in your index
    "domain_id": "template_tram_stop",  # with BATCHES/batches.txt: must equal your batch's domain
    "batch": "example",                 # your claimed batch id (b01, b02, ...)
    "slot": 0,                          # the slot of the batch's plan you fill (1..6 for plans A-C)
    "author": "machine-zoo-factory-template",
    "title": "Tram stopping at a platform",
    "story": (                          # plain words; never state the value of a hidden variable
        "A tram must come to rest exactly at the platform. Power and braking change its speed one step per "
        "tick, so the operator has to start braking early enough without stopping short."
    ),
    "strata": ["long"],                 # any of: delay hidden long interlock axes3 budget multibudget
    # "mode_var": "mode",               # only with interlock: the var whose value changes what a control does
    # "budget_vars": ["fuel"],          # only with budget (>= 1 var) / multibudget (>= 2 vars)
}

# 2..5 integer parameters; the grid (product of the lists) has 8..64 points. Each grid point is one instance.
PARAMS = {
    "track": [72, 76, 80, 84],  # last cell of the track (the buffer)
    "vmax": [3, 4],             # top speed
    "gap": [3, 5],              # platform = track - gap
}


def build(p: dict) -> dict:
    """Pure function of p: same p -> same program; never mutate p. Returns a valid mz-1x program."""
    track, vmax = p["track"], p["vmax"]
    stop = track - p["gap"]
    base = dsl.program(
        vars=[
            # dsl.var(name, lo, hi, start value(s), oob="clamp" | "crash")
            dsl.var("pos", 0, track, [0, 1, 2]),
            dsl.var("speed", 0, vmax, 0),
        ],
        # dsl.control(name, [DEC value or None, KEEP value, INC value or None]); up to 3 controls
        controls=[dsl.control("throttle", [-1, 0, 1])],
        # rules run in this order every tick; each sees the results of the earlier ones (docs/DSL_REFERENCE.md §2.6)
        rules=[
            "speed := speed + @throttle",
            "pos := pos + speed",
        ],
        crash=[f"pos >= {track}"],                 # checked after all rules; a crash beats the goal
        goal=f"all(pos == {stop}, speed == 0)",
    )
    # mz-1x extension: xdsl.make(base, delay=d, hidden=[...], window=H) for reply delay / hidden vars.
    return xdsl.make(base)


# Optional: identifier -> plain words (for readers of the code; the gate does not score it).
GLOSSARY = {"pos": "track cell of the tram", "speed": "cells moved per tick", "throttle": "brake / coast / power"}


def prose(p: dict) -> str:
    """The rulebook of THIS instance in plain words, written by you (never generated from the program by code).

    It must determine the program exactly (a blind reviewer rebuilds it; prose_check.py must print EXACT), use every
    var and control identifier verbatim, contain every number of the instance, and contain no DSL syntax (the exact
    parser must reject it). GATES.md §5 lists everything P2 checks.
    """
    track, vmax = p["track"], p["vmax"]
    stop = track - p["gap"]
    return f"""Tram, operator card.

The tram runs on a straight track whose cells are numbered 0 to {track}. Its position, pos, starts at cell 0, 1
or 2, each equally likely, and the platform is cell {stop}. Its speed, speed, counts the cells it moves per tick,
from 0 up to {vmax}; the tram always starts at rest, with speed 0.

The operator has one control, the throttle, with three settings in increasing order: brake (minus 1), coast (0) and
power (plus 1). Coast is the neutral setting. A setting acts only on the tick it is chosen; nothing is latched.

Each tick is processed in this order, each step seeing the result of the one before. First the throttle setting is
added to speed; speed never drops below 0 and never rises above {vmax}, it simply stays at the limit. Then the
tram moves: speed is added to pos, and pos likewise stays within 0 and {track}.

After both updates the end conditions are checked. The run fails, because the tram hits the buffer, if pos is
cell {track} or beyond. The run succeeds when pos is exactly cell {stop} and speed is 0. A failure always beats
success: if both happen on the same tick, the tick counts as a failure.

Everything is shown on the panel, every command acts on the tick it is given, nothing here is random, and there is
no score other than stopping at the platform without failing.
"""
