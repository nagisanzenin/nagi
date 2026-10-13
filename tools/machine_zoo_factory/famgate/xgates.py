# SPDX-License-Identifier: Apache-2.0
"""Frozen per-instance mz-1x gates X0, X1, G2-G8, X3, X4d, X4h, X5 (thresholds fixed 2026-10-11).

Vendored from the research gate unchanged except this docstring and the import lines. Language and semantics:
docs/DSL_REFERENCE.md. Every probability is an exact 100-tick chain value from the uniform start
(xteacher.chain / view_oracle_chain).
"""

from __future__ import annotations

import time

import numpy as np

from nagi.burst2._rt.bv2n.zoo_new import xdsl
from nagi.burst2._rt.bv2n.zoo_new.xteacher import XBudgetExceeded, XTeacher

ORACLE_MIN = 0.90  # G2
MINORITY_MIN = 0.05  # G3
TIE_MAX = 0.25  # G4
KEEP_MAX = 0.20  # G5
WEAK_MAX = 0.80  # G6
MIN_ORACLE_LEN = 5.0  # G7
LOAD_SUCC = 0.20  # X4: a feature-blind probe loses >= 0.20 success ...
LOAD_RET = 10.0  # ... or >= 10 return points
LONG_MEDIAN = 20  # X5
FEATURES = ("delay", "hidden", "long")
GATES = ("X0", "X1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "X3", "X4d", "X4h", "X5")


def _slot_minority(T: XTeacher, labels: np.ndarray, w: np.ndarray) -> list[dict]:
    """G3 on visit-weighted label sets (labels bool (n, nv) over valid positions, w visit weights)."""
    out = []
    tot = float(w.sum())
    jv = T.valid
    for s, c in enumerate(T.base_program["controls"]):
        digit = (jv // (9, 3, 1)[s]) % 3
        vo = [o for o in range(3) if c["opts"][o] is not None]
        pres = np.stack([(labels & (digit == o)[None, :]).any(axis=1) for o in vo], axis=1)  # (n, |vo|)
        decisive = ~pres.all(axis=1)
        counts = {int(o): float((w * (pres[:, k] & decisive)).sum()) for k, o in enumerate(vo)}
        srt = sorted(counts.values(), reverse=True)
        minority = srt[1] / tot if (tot > 0 and len(srt) >= 2) else 0.0
        out.append({"slot": s, "name": c["name"], "minority_share": minority,
                    "decisive_share": float((w * decisive).sum() / tot) if tot else 0.0,
                    "pass": bool(minority >= MINORITY_MIN)})
    return out


def run_gates(px: dict, features=(), budgets: dict | None = None) -> dict:
    t0 = time.perf_counter()
    rep: dict = {"machine_id": None, "features": sorted(features)}
    feats = set(features)
    try:
        xdsl.validate(px)
        ok0 = feats <= set(FEATURES) and (("delay" in feats) == (px["delay"] >= 1)) and \
            (("hidden" in feats) == bool(px["hidden"]))
        rep["X0"] = {"pass": bool(ok0)}
    except Exception as ex:  # noqa: BLE001 (any validity failure is a gate failure)
        rep["X0"] = {"pass": False, "error": str(ex)}
        return _finish(rep, t0)
    rep["machine_id"], rep["signature"] = xdsl.machine_id(px), xdsl.signature(px)
    try:
        T = XTeacher(px, **(budgets or {}))
    except XBudgetExceeded as ex:
        rep["X1"] = {"pass": False, "what": ex.what, "n_seen": ex.n_seen, "budget": ex.budget}
        return _finish(rep, t0)
    rep["X1"] = {"pass": True, "n_base": int(T.base.n_states), "n_aug": int(T.N),
                 "n_views": None if T.views is None else len(T.views)}
    rep["timing"] = {k: round(v, 3) for k, v in T.timing.items()}
    orc = T.view_oracle_chain()
    keep = T.chain(T.pol_keep())
    weak = T.chain(T.pol_weak())
    rnd = T.chain(T.pol_random())
    rep["success"] = {"oracle": orc["success"], "keep": keep["success"], "weak": weak["success"],
                      "random": rnd["success"]}
    rep["crash"] = {"oracle": orc["crash"], "keep": keep["crash"], "weak": weak["crash"], "random": rnd["crash"]}
    rep["mean_return"] = {"oracle": orc["mean_return"], "keep": keep["mean_return"], "weak": weak["mean_return"]}
    rep["len"] = orc["len"]
    if T.hidden:
        labels, w = T.I, orc["view_visits"]
    else:
        labels, w = T.acc, orc["visits"]
    ctrl = _slot_minority(T, labels, w)
    tie = float((w * labels.all(axis=1)).sum() / w.sum()) if w.sum() else 1.0
    mean_len = orc["len"]["mean"] if orc["len"] else None
    dead = [int(r) for r in np.flatnonzero(~T.base.fired_changed)]
    rep["G2"] = {"pass": orc["success"] >= ORACLE_MIN, "oracle_success": orc["success"]}
    rep["G3"] = {"pass": bool(ctrl) and all(c["pass"] for c in ctrl), "controls": ctrl}
    rep["G4"] = {"pass": tie <= TIE_MAX, "tie_share": tie}
    rep["G5"] = {"pass": keep["success"] <= KEEP_MAX, "keep_success": keep["success"]}
    rep["G6"] = {"pass": weak["success"] <= WEAK_MAX, "weak_success": weak["success"]}
    rep["G7"] = {"pass": mean_len is not None and mean_len >= MIN_ORACLE_LEN, "oracle_mean_len": mean_len}
    rep["G8"] = {"pass": not dead, "dead_rules": dead}
    if T.hidden:
        n_bad = int((~T.I.any(axis=1)).sum())
        rep["X3"] = {"pass": n_bad == 0, "n_views": len(T.views), "n_unidentifiable": n_bad,
                     "max_belief": int(T.belief_size.max()), "mean_belief": float(T.belief_size.mean())}
    else:
        rep["X3"] = {"pass": True, "skipped": "nothing hidden"}

    def load(P, name):
        c = T.chain(P)
        ds, dr = orc["success"] - c["success"], orc["mean_return"] - c["mean_return"]
        return {"pass": bool(ds >= LOAD_SUCC or dr >= LOAD_RET), "probe": name, "probe_success": c["success"],
                "probe_return": c["mean_return"], "d_success": ds, "d_return": dr}

    rep["X4d"] = load(T.pol_delay_blind(), "delay_blind") if px["delay"] else {"pass": True, "skipped": "d = 0"}
    rep["X4h"] = load(T.pol_memoryless(), "memoryless") if T.hidden else {"pass": True, "skipped": "no hidden"}
    if "long" in feats:
        med = orc["len"]["median"] if orc["len"] else None
        rep["X5"] = {"pass": med is not None and med >= LONG_MEDIAN, "median": med}
    else:
        rep["X5"] = {"pass": True, "skipped": "not declared", "median": orc["len"]["median"] if orc["len"] else None}
    return _finish(rep, t0)


def _finish(rep: dict, t0: float) -> dict:
    for g in GATES:
        rep.setdefault(g, {"pass": False, "skipped": "earlier gate failed"})
    rep["pass"] = all(rep[g]["pass"] for g in GATES)
    rep["failed"] = [g for g in GATES if not rep[g]["pass"]]
    rep["time_s"] = round(time.perf_counter() - t0, 3)
    return rep
