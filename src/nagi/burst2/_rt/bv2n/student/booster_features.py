"""Booster featurizer of the PARSED BoosterView (bv2n.data.booster_src.view_dict(parse(text))); never the runner state.

Inputs are the view's own fields only: the displayed frame, the applied controls p_log, the actuator states (ignition
delay left, fin deployment / deflection) and the 8-tick history window. Features (SI-like units):
  frame      age, height, vx, vy, tilt, rate, ship dx, zone, deck vx / vy / pitch, wind, thrust, relights (left, of),
             gimbal, fuel (kg, share), q, TWR min/mid/max, hop, landed; one-hot engine level, fins, legs; legs %
  derived    deck-relative velocity; required deceleration v^2 / 2h and its ratio to the max-throttle margin
             (TWR_max - 1) g; time-to-go h / |vy|; predicted ship-dx miss after 0.5 / 1 / 2 s and at time-to-go
             (all / zone); tilt one tick ahead; per-tick finite differences vs the newest history row (vx, vy, rate,
             deck vx / vy) and vs 2 ticks back (vy)
  applied    one-hot p_log (throttle 4, gimbal 5, fins 4, legs 2)
  act        ignition delay / 300 ms, fins out %, fin deflection %
  hist       8 rows x (height - now, vx, vy, ship dx - now, tilt, rate, deck vx, vy, pitch, wind) + seen mask
Outputs: one softmax head per control (throttle 4, gimbal 5, fins 4, legs 2).
"""
from __future__ import annotations

import numpy as np

CONTROLS = ("throttle", "gimbal", "fins", "legs")
OPTIONS = {"throttle": ("off", "min", "mid", "max"), "gimbal": ("L2", "L1", "0", "R1", "R2"),
           "fins": ("stowed", "left", "neutral", "right"), "legs": ("stowed", "deploy")}
ENG = ("OFF", "min", "mid", "max")
FINS = ("stowed", "left", "neutral", "right")
LEGS = ("stowed", "deploying", "down")
H = 8


def _clip(v, lo, hi):
    return max(lo, min(hi, v))


def booster_x(v: dict) -> np.ndarray:
    f, a, hist = v["frame"], v["act"], v["hist"]
    alt, vx, vy = float(f["alt"]), f["vx"] / 10, f["vy"] / 10
    tilt, rate, dx, zone = f["tilt"] / 10, f["rate"] / 10, float(f["dx"]), max(1.0, float(f["zone"]))
    dvx, dvy, pitch, wind = f["dvx"] / 10, f["dvy"] / 10, f["pitch"] / 10, f["wind"] / 10
    twr = [x / 100 for x in f["twr"]]
    x = [f["age"] / 100 / 22, alt / 100, vx / 10, vy / 10, tilt / 10, rate / 10, dx / 50, zone / 20, dvx, dvy, pitch,
         wind / 10, (f["thr"] or 0) / 1000, f["relights"], f["relights0"], f["gim"] / 50, f["fuel"] / 1000,
         f["fuel"] / max(1, f["fuel0"]), f["q"] / 100, *twr, f["hop"], f["landed"], (f["legs_pct"] or 0) / 100]
    x += [float(f["eng"] == e) for e in ENG] + [float(f["fins"] == e) for e in FINS] + [float(f["legs"] == e) for e in LEGS]
    rvx, rvy = vx - dvx, vy - dvy
    h = max(alt, 0.5)
    req = _clip(vy * vy / (2 * h), 0, 100) if vy < 0 else 0.0
    amax = max(0.1, (twr[2] - 1) * 9.81)
    ttg = _clip(h / max(-vy, 0.5), 0, 60)
    x += [rvx / 10, rvy / 10, req / 10, _clip(req / amax, 0, 10), ttg / 10]
    x += [_clip((dx - rvx * tau) / zone, -20, 20) for tau in (0.5, 1.0, 2.0, min(ttg, 10.0))]
    x += [(tilt + rate * 0.25) / 10]
    last = hist[-1] if hist else None
    if last is not None:
        x += [vx - last[1] / 10, vy - last[2] / 10, rate - last[5] / 10, dvx - last[6] / 10, dvy - last[7] / 10, 1.0]
    else:
        x += [0.0] * 5 + [0.0]
    prev2 = hist[-2] if len(hist) >= 2 else None
    x += [vy - prev2[2] / 10, 1.0] if prev2 is not None else [0.0, 0.0]
    for c, opts in OPTIONS.items():
        x += [float(v["applied"][CONTROLS.index(c)] == o) for o in opts]
    x += [a["ign_ms"] / 300, a["fin_out"] / 100, a["fin_defl"] / 100]
    for r in hist:
        if r is None:
            x += [0.0] * 11
        else:
            x += [(r[0] - alt) / 20, r[1] / 100, r[2] / 100, (r[3] - dx) / 20, r[4] / 100, r[5] / 100, r[6] / 10,
                  r[7] / 10, r[8] / 10, r[9] / 100, 1.0]
    return np.asarray(x, np.float32)


BOOSTER_DIM = 25 + 11 + 5 + 4 + 1 + 6 + 2 + 15 + 3 + H * 11


def booster_y(view: dict, joint: dict) -> list[int]:
    return [OPTIONS[c].index(joint[c]) for c in CONTROLS]


def booster_joint(view: dict, cls: list[int]) -> dict:
    return {c: OPTIONS[c][k] for c, k in zip(CONTROLS, cls)}


SPEC = {"x": booster_x, "y": booster_y, "joint": booster_joint, "heads": (4, 5, 4, 2), "dim": BOOSTER_DIM}
