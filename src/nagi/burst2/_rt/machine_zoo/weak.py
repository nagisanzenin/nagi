"""Generic weak bot, SPEC §7 (baseline and gate G6).

Goal violation of a PRED on x (comparison item ``e op c``, e = EXPR(x)): ``<=`` max(0, e - c); ``<`` max(0, e - c + 1);
``>=`` max(0, c - e); ``>`` max(0, c - e + 1); ``==`` |e - c|; ``!=`` 1 if e = c else 0. ``all`` = sum over items,
``any`` = min over items (nested PREDs recursively). For each valid joint j (increasing): E_j = sum_w p_w cost_w with
cost = -1 on success, 10^6 on crash (out-of-range crash included), else the goal violation of the next state.
Candidates = {j : E_j <= min E + 1e-9}; action = candidates[rng.integers(len(candidates))] (one call per decision).

Exactness: p_w = weight_w / W, so W * E_j = sum_w weight_w * cost_w is an exact integer. Two different E values differ
by at least 1/W >= 1e-3 > 1e-9, so the 1e-9 rule is EXACTLY "W * E_j == min_j W * E_j"; this module compares the
integers (no float rounding can move a joint in or out of the candidate set).

Two implementations, tested equal:
- ``WeakTable`` (vectorized over the teacher's reachable set S, from its transition table) -- used by gates and rollouts;
- ``weak_scores_scalar`` / ``weak_action_scalar`` (one state, any one-tick function) -- the reference.
Every state an episode can visit before termination is in S (S is closed under every valid joint and every w with
positive weight), so the table covers all decisions of every policy.
"""

from __future__ import annotations

import numpy as np

CRASH_COST = 10 ** 6
SUCCESS_COST = -1

# transition-table sentinels (teacher.nxt): next index >= 0 = running next state in S
NXT_CRASH = -1
NXT_SUCCESS = -2


def rand_weights(program: dict) -> list[int]:
    """Integer outcome weights in listed order ([1] when ``rand`` is null)."""
    r = program.get("rand")
    return [1] if not r else [int(wt) for _v, wt in r]


# ------------------------------------------------------------------------------------------------ goal violation
def _atom_vec(atom: str, X: np.ndarray, col: dict) -> np.ndarray:
    if atom.startswith("abs(") and atom.endswith(")"):
        return np.abs(X[:, col[atom[4:-1]]])
    if atom.startswith("sgn(") and atom.endswith(")"):
        return np.sign(X[:, col[atom[4:-1]]])
    return X[:, col[atom]]


def _expr_vec(e: dict, X: np.ndarray, col: dict) -> np.ndarray:
    out = np.full(X.shape[0], int(e.get("k", 0)), dtype=np.int64)
    for coef, atom in e.get("t", []):
        out += int(coef) * _atom_vec(atom, X, col)
    return out


def _item_violation_vec(e: np.ndarray, op: str, c: int) -> np.ndarray:
    if op == "<=":
        return np.maximum(0, e - c)
    if op == "<":
        return np.maximum(0, e - c + 1)
    if op == ">=":
        return np.maximum(0, c - e)
    if op == ">":
        return np.maximum(0, c - e + 1)
    if op == "==":
        return np.abs(e - c)
    if op == "!=":
        return (e == c).astype(np.int64)
    raise ValueError(f"unknown op {op!r}")


def violation_vec(pred: dict, X: np.ndarray, var_names: list[str]) -> np.ndarray:
    """Goal violation (int64[n]) of ``pred`` on every row of X (int64[n, n_vars], vars in program order)."""
    col = {n: i for i, n in enumerate(var_names)}
    X = np.asarray(X, dtype=np.int64).reshape(-1, len(var_names))
    return _pred_viol_vec(pred, X, col)


def _pred_viol_vec(pred: dict, X: np.ndarray, col: dict) -> np.ndarray:
    (kind, items), = pred.items()
    parts = []
    for it in items:
        if isinstance(it, dict):
            parts.append(_pred_viol_vec(it, X, col))
        else:
            e, op, c = it
            parts.append(_item_violation_vec(_expr_vec(e, X, col), op, int(c)))
    if kind == "all":
        return np.sum(parts, axis=0, dtype=np.int64)
    if kind == "any":
        return np.min(parts, axis=0)
    raise ValueError(f"unknown PRED kind {kind!r}")


def violation_scalar(pred: dict, x, var_names: list[str]) -> int:
    """Reference goal violation of ``pred`` on one state (pure Python ints)."""
    val = dict(zip(var_names, (int(v) for v in x)))

    def atom(a: str) -> int:
        if a.startswith("abs("):
            return abs(val[a[4:-1]])
        if a.startswith("sgn("):
            v = val[a[4:-1]]
            return (v > 0) - (v < 0)
        return val[a]

    def item(e, op, c) -> int:
        v = int(e.get("k", 0)) + sum(int(k) * atom(a) for k, a in e.get("t", []))
        c = int(c)
        return {"<=": max(0, v - c), "<": max(0, v - c + 1), ">=": max(0, c - v), ">": max(0, c - v + 1),
                "==": abs(v - c), "!=": int(v == c)}[op]

    def pred_v(p) -> int:
        (kind, items), = p.items()
        vs = [pred_v(it) if isinstance(it, dict) else item(*it) for it in items]
        return sum(vs) if kind == "all" else min(vs)

    return pred_v(pred)


# ------------------------------------------------------------------------------------------------ vectorized bot
class WeakTable:
    """Weak-bot candidate sets for every state of the teacher's reachable set S.

    nxt: int[n, n_valid, n_w] next-state index in S, or NXT_CRASH / NXT_SUCCESS; states: int[n, n_vars];
    valid_joints: int[n_valid] increasing; weights: int[n_w] outcome weights in the same order as nxt's last axis.
    ``score`` = W * E (int64[n, n_valid]); ``cand`` = bool[n, n_valid] (score == row minimum).
    """

    def __init__(self, program: dict, states: np.ndarray, nxt: np.ndarray, valid_joints, weights=None):
        names = [v["name"] for v in program["vars"]]
        wts = np.asarray(rand_weights(program) if weights is None else weights, dtype=np.int64)
        nxt = np.asarray(nxt)
        if nxt.ndim != 3 or nxt.shape[2] != len(wts):
            raise ValueError(f"nxt shape {nxt.shape} does not match {len(wts)} outcomes")
        viol = violation_vec(program["goal"], states, names)  # violation of every state in S
        score = np.zeros(nxt.shape[:2], dtype=np.int64)
        for k in range(len(wts)):  # outcome order = listed order
            nk = nxt[:, :, k]
            cost = np.where(nk >= 0, viol[np.maximum(nk, 0)], np.where(nk == NXT_SUCCESS, SUCCESS_COST, CRASH_COST))
            if ((nk < 0) & (nk != NXT_CRASH) & (nk != NXT_SUCCESS)).any():
                raise ValueError("unknown sentinel in nxt")
            score += wts[k] * cost
        self.valid_joints = np.asarray(valid_joints, dtype=np.int64)
        self.score = score
        self.cand = score == score.min(axis=1, keepdims=True)
        self.n_cand = self.cand.sum(axis=1)

    def action(self, i: int, rng: np.random.Generator) -> int:
        """Weak joint at state index ``i`` (exactly one ``rng.integers`` call)."""
        c = np.flatnonzero(self.cand[i])
        return int(self.valid_joints[c[rng.integers(len(c))]])

    def candidates(self, i: int) -> list[int]:
        return [int(j) for j in self.valid_joints[self.cand[i]]]


# ------------------------------------------------------------------------------------------------ scalar reference
def weak_scores_scalar(program: dict, state, valid_joints, outcomes, tick) -> list[int]:
    """W * E_j for every valid joint (reference). outcomes = [(w, weight), ...] in listed order (``[(0, 1)]`` when
    rand is null); tick(state, j, w) -> (next_state, outcome) with outcome in running / success / crash."""
    names = [v["name"] for v in program["vars"]]
    out = []
    for j in valid_joints:
        tot = 0
        for w, wt in outcomes:
            nx, oc = tick(state, int(j), w)
            cost = SUCCESS_COST if oc == "success" else CRASH_COST if oc == "crash" else violation_scalar(
                program["goal"], nx, names)
            tot += int(wt) * cost
        out.append(tot)
    return out


def weak_action_scalar(program: dict, state, valid_joints, outcomes, tick, rng: np.random.Generator) -> int:
    sc = weak_scores_scalar(program, state, valid_joints, outcomes, tick)
    m = min(sc)
    cands = [int(j) for j, s in zip(valid_joints, sc) if s == m]
    return cands[rng.integers(len(cands))]


def table_for(program: dict, teacher) -> WeakTable:
    """WeakTable from a lane-A1 teacher (fields X, nxt, valid)."""
    return WeakTable(program, teacher.X, teacher.nxt, teacher.valid)


def weak_action(machine, state, rng: np.random.Generator) -> int:
    """SPEC §7 weak joint for ``state`` of ``machine`` (lane A1 Machine: .program / .teacher). The candidate table
    over S is built once per machine and cached on it (``_weak_table``); one ``rng.integers`` call per decision."""
    wt = getattr(machine, "_weak_table", None)
    if wt is None:
        prog = getattr(machine, "program", None) or machine.descriptor
        wt = table_for(prog, machine.teacher)
        machine._weak_table = wt
    return wt.action(machine.teacher.index_of(tuple(state)), rng)
