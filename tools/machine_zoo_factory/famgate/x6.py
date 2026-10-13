# SPDX-License-Identifier: Apache-2.0
"""Gate X6: the exact teacher and an independently written blind checker must agree on every reachable augmented
state (same state set, |dV| <= 1e-7, same acceptable action sets), on every view of a hidden program (same belief and
same acceptable set I), and on the oracle success (|d| <= 1e-9).

Vendored from the research gate (``blind_equivalence`` and ``compare``) unchanged except the import lines.
"""

from __future__ import annotations

from nagi.burst2._rt.bv2n.zoo_new.xteacher import XTeacher

from .blind.blind import solve_x


def blind_equivalence(pxs: list[dict]) -> dict:
    """X6: compare the exact teacher (xteacher) against the independent blind checker (blind/blind.py)."""
    out = []
    for px in pxs:
        out.append(compare(XTeacher(px), solve_x(px)))
    return {"pass": all(o["pass"] for o in out), "instances": out}


def compare(T, b: dict) -> dict:
    mine = {}
    for z in range(T.N):
        mine[T.aug_state(z)] = (float(T.Qv[z].max()), frozenset(int(j) for j in T.valid[T.acc[z]]))
    r = {"n_aug": T.N, "n_blind": len(b["states"])}
    r["same_states"] = set(mine) == set(b["states"])
    dv, acc_bad = 0.0, 0
    for k, (v, a) in mine.items():
        if k in b["states"]:
            dv = max(dv, abs(v - b["states"][k]["V"]))
            acc_bad += a != frozenset(b["states"][k]["acceptable"])
    r["max_dV"], r["acc_mismatch"] = dv, acc_bad
    ok = r["same_states"] and dv <= 1e-7 and acc_bad == 0
    if T.hidden:
        mv = {}
        for n, key in enumerate(T.views):
            obs = tuple(None if c < 0 else T.obs_vals[c] for c in key[:T.H])
            dec = tuple(None if c < 0 else int(T.valid[c]) for c in key[T.H:])
            bel = frozenset(T.aug_state(int(z)) for z in T.belief(key))
            mv[(obs, dec)] = (bel, frozenset(int(j) for j in T.valid[T.I[n]]))
        bv = b["views"] or {}
        r["n_views"], r["n_views_blind"] = len(mv), len(bv)
        r["same_views"] = set(mv) == set(bv)
        r["belief_mismatch"] = sum(mv[k][0] != frozenset(bv[k]["belief"]) for k in mv if k in bv)
        r["I_mismatch"] = sum(mv[k][1] != frozenset(bv[k]["I"]) for k in mv if k in bv)
        ok = ok and r["same_views"] and r["belief_mismatch"] == 0 and r["I_mismatch"] == 0
    so = T.view_oracle_chain()["success"]
    r["d_oracle_success"] = abs(so - b["oracle_success"])
    ok = ok and r["d_oracle_success"] <= 1e-9
    r["pass"] = bool(ok)
    return r
