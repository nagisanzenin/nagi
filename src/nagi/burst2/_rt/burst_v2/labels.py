"""Latency-aware, observation-consistent soft-Q chord labels (docs/burst_v2/LABELS.md §2).

For a served request observing s_k with the runner's pending controls p_log (applied at tick k):

    Q_b(s_k, p_log, d, a) = value (K3 points, game adapter's definition) of: p_log at tick k, the runner's hold rules at
                            ticks k+1..k+d-1, joint a from tick k+d (held by the runner until the next reply lands),
                            then the adapter's continuation policy (whose later replies also pass the latency
                            emulator); world b = a sample of the hidden exogenous future given what the prompt shows
                            (b = the true world only for the 'cheat' diagnostic)
    Q-bar(x, a)           = sum_d P-hat(d) * (1/B) sum_b Q_b(s_k, p_log, d, a)          (math.fsum)
    a*                    = the tie rule: control by control in declared order, the base (continuation) policy's
                            own option on this prompt if an optimal joint (Q-bar >= max - TOL) with the prefix chosen
                            so far has it, else the first such option in declared option order.
                            Any fixed optimal a* makes the per-slot argmaxes compose to a* (R2.13 / R1.13 Thm 3); the
                            base-first rule removes 'act later' ties that a first-option rule resolves toward never
                            acting (Booster legs: stowed < deploy -> the legs never come down).
    M_k(o)                = max {Q-bar(a) : a_k = o}                                      (max-marginal)
    target_k              = softmax(tie-broken M_k / T); tied o != a*_k get max - T ln(TIE_RATIO)  (R2.13 / R1.21)

T is in K3 points (adapter.TEMPERATURE); TOL = 1e-9 as LC; TIE_RATIO = 4 as multiaction.chord.
Monte-Carlo labels use a tie tolerance at the estimator's resolution (adapter.TIE_TOL, Booster 0.05 K3 points):
joints within TIE_TOL of the best are treated as ties and resolved toward the base policy (conservative policy
improvement: deviate from the base only when the estimated gain exceeds the MC noise). Composition still holds:
a* is within tol of the best and tied options are demoted to best - T ln 4 < best - tol (needs tol < T ln 4 = 0.069).
"""
from __future__ import annotations

import itertools
import math

TOL = 1e-9
TIE_RATIO = 4.0


def joints(controls, options) -> list[tuple]:
    return list(itertools.product(*[tuple(options[c]) for c in controls]))


def qbar(q_by_d: dict, p_hat: dict) -> dict:
    """q_by_d = {d: [ {joint: Q_b} for each world b ]}; returns {joint: Q-bar}."""
    assert set(q_by_d) == set(p_hat), (sorted(q_by_d), sorted(p_hat))
    first = q_by_d[min(q_by_d)][0]
    out = {}
    for a in first:
        out[a] = math.fsum(p_hat[d] * math.fsum(w[a] for w in q_by_d[d]) / len(q_by_d[d]) for d in sorted(p_hat))
    return out


def canonical(q: dict, order: list[tuple], tol: float = TOL) -> tuple:
    b = max(q.values())
    for a in order:
        if q[a] >= b - tol:
            return a
    raise ValueError("empty Q")


def acceptable(q: dict, tol: float = TOL) -> set:
    b = max(q.values())
    return {a for a, v in q.items() if v >= b - tol}


def canonical_base(q: dict, order: list[tuple], base: tuple | None, tol: float = TOL) -> tuple:
    """a*: control by control (declared order), the base policy's option if some optimal joint with the prefix chosen
    so far has it, else the first such option in declared order. = canonical(q) when base is None."""
    if base is None:
        return canonical(q, order, tol)
    cand = acceptable(q, tol)
    K = len(base)
    opts = [list(dict.fromkeys(a[k] for a in order)) for k in range(K)]
    for k in range(K):
        pref = [base[k]] + [o for o in opts[k] if o != base[k]]
        o = next(o for o in pref if any(a[k] == o for a in cand))
        cand = {a for a in cand if a[k] == o}
    (a,) = cand
    return a


def slot_tables(controls, options, q: dict, T: float, canon: tuple | None = None, tol: float = TOL) -> list[dict]:
    """Per control (declared order): max-marginals, tie-broken values, soft target (list in option order), the
    max-marginal-optimal options and a*_k. Equals multiaction.chord.slot_values + softmax (tested). canon = a*
    (default: first optimal joint in product order); it must be optimal."""
    order = joints(controls, options)
    canon = canonical(q, order, tol) if canon is None else canon
    assert q[canon] >= max(q.values()) - tol, "a* must be optimal (within tol)"
    best = max(q.values())
    out = []
    for k, c in enumerate(controls):
        m = {o: max(v for a, v in q.items() if a[k] == o) for o in options[c]}
        top = [o for o in options[c] if m[o] >= best - tol]
        tb = dict(m)
        for o in top:
            if o != canon[k]:
                tb[o] = best - T * math.log(TIE_RATIO)
        mx = max(tb.values())
        e = [math.exp((tb[o] - mx) / T) for o in options[c]]
        z = math.fsum(e)
        out.append({"control": c, "values": [m[o] for o in options[c]], "tie_broken": [tb[o] for o in options[c]],
                    "target": [x / z for x in e], "acceptable": top, "canonical": canon[k],
                    "all_tied": len(top) == len(options[c])})
    return out


def summary(q: dict) -> dict:
    vals = sorted(set(round(v, 12) for v in q.values()), reverse=True)
    return {"best": vals[0], "gap2": (vals[0] - vals[1]) if len(vals) > 1 else 0.0,
            "n_acceptable": len(acceptable(q)), "n_joints": len(q), "informative": len(vals) > 1,
            "spread": vals[0] - vals[-1]}


def argmax_disagree(qa: dict, qb: dict) -> bool:
    """True when the canonical-free argmax sets are disjoint (the stricter 'labels disagree' estimand)."""
    return not (acceptable(qa) & acceptable(qb))
