# SPDX-License-Identifier: Apache-2.0
"""Blind checker for the Machine Zoo extension mz-1x (gate X6).

Written only from the language definition (docs/DSL_REFERENCE.md, mz-1 and the mz-1x extension). It never imports
the engine under nagi.burst2._rt. Base mz-1 semantics (start set, one tick given w, outcomes, valid joints) come from
the independent base checker `brute.BruteMachine`; everything mz-1x-specific is here:

1. augmented reachability: plain BFS over z = (base_state, queue) from (start, KEEP^d);
2. values: policy iteration with exact sparse solves, then Bellman polish to residual <= 1e-10;
3. views: NO belief filter. The joint process (z, view) is enumerated forward from reset under every valid decided
   joint and every outcome with p > 0; B(view) = the z seen with that view; I(view) = intersection of A(z);
4. oracle_success: exact forward propagation of probability mass for MAX_STEPS ticks from the uniform start.

Section marks (§) in comments follow the research language spec this checker was written from.
Vendored from the research test suite unchanged except this docstring and the import of the base checker.
"""
from __future__ import annotations

from collections import deque

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from .brute import BruteMachine

KEEP = 13          # mz-1 KEEP joint; also the in-flight placeholder before the episode (§2)
GAMMA = 0.99
TOL = 1e-6
MAX_STEPS = 100
R_SUCCESS = 49.0
PAD = None
PI_IMPROVE_EPS = 1e-12
POLISH_RESIDUAL = 1e-10
PX_KEYS = {"dsl", "base", "delay", "hidden", "window"}


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def check_px(px: dict) -> None:
    """§1 validity rules 2-5 (rule 1, base validity, is checked by BruteMachine)."""
    if not isinstance(px, dict) or set(px) != PX_KEYS or px["dsl"] != "mz-1x":
        raise ValueError("mz-1x program must have exactly the keys dsl/base/delay/hidden/window with dsl 'mz-1x'")
    d, hidden, H = px["delay"], px["hidden"], px["window"]
    if not _is_int(d) or d not in (0, 1, 2):
        raise ValueError("delay must be 0, 1 or 2")
    names = [v["name"] for v in px["base"]["vars"]]
    if not isinstance(hidden, list) or len(set(hidden)) != len(hidden) or any(h not in names for h in hidden):
        raise ValueError("hidden must be a list of distinct base var names")
    pos = [names.index(h) for h in hidden]
    if pos != sorted(pos):
        raise ValueError("hidden vars must be listed in program order")
    if len(hidden) >= len(names):
        raise ValueError("at least one var must stay displayed")
    if not _is_int(H) or not 1 <= H <= 6:
        raise ValueError("window must be an int in 1..6")
    if not hidden and H != 1:
        raise ValueError("window must be 1 when nothing is hidden")


class _XMachine:
    """The augmented controlled process on z = (s, q) (§3) and the client view process (§2)."""

    def __init__(self, px: dict):
        check_px(px)
        self.m = BruteMachine(px["base"])
        self.d = px["delay"]
        self.H = px["window"]
        self.K = max(self.H - 1, self.d)
        names = [v["name"] for v in px["base"]["vars"]]
        self.hidden = list(px["hidden"])
        self.shown = [i for i, nm in enumerate(names) if nm not in self.hidden]
        self.joints = list(self.m.valid_joints)          # increasing
        self.outs = [(w, p) for w, p in self.m.outcomes() if p > 0]
        self._tick = {}

    # ---- one base tick per applied joint, all outcomes (cached on (s, u)) ------------------------------------
    def base_dist(self, s: tuple, u: int):
        key = (s, u)
        if key not in self._tick:
            res = []
            for w, p in self.outs:
                s2, r, _done, outcome = self.m.tick_w(s, u, w)
                res.append((p, r, s2, outcome))
            self._tick[key] = res
        return self._tick[key]

    def succ(self, z, j: int):
        """[(p, reward, outcome, z' or None if terminal)] for decided joint j at augmented state z."""
        s, q = z
        u = q[0] if self.d else j
        nq = q[1:] + (j,) if self.d else ()
        return [(p, r, o, (s2, nq) if o == "running" else None) for p, r, s2, o in self.base_dist(s, u)]

    def resets(self):
        return [(s, (KEEP,) * self.d) for s in self.m.start_set()]

    # ---- views (§2) --------------------------------------------------------------------------------------------
    def shown_of(self, s: tuple) -> tuple:
        return tuple(s[i] for i in self.shown)

    def reset_view(self, s: tuple):
        obs = (PAD,) * (self.H - 1) + (self.shown_of(s),)
        # dec covers ticks -K..-1; tick k < 0 is in flight (KEEP) when k >= -d, else PAD
        dec = tuple(KEEP if k >= -self.d else PAD for k in range(-self.K, 0))
        return (obs, dec)

    def next_view(self, view, j: int, s2: tuple):
        obs, dec = view
        return (obs[1:] + (self.shown_of(s2),), dec[1:] + (j,) if self.K else ())


def _reachable(xm: _XMachine):
    order, index = [], {}
    frontier = deque()
    for z in xm.resets():
        if z not in index:
            index[z] = len(order)
            order.append(z)
            frontier.append(z)
    while frontier:
        z = frontier.popleft()
        for j in xm.joints:
            for _p, _r, _o, z2 in xm.succ(z, j):
                if z2 is not None and z2 not in index:
                    index[z2] = len(order)
                    order.append(z2)
                    frontier.append(z2)
    return order, index


def _solve_values(xm: _XMachine, order, index):
    """Policy iteration (exact sparse solves) then Bellman polish. Returns (V, Q) with Q of shape n x |J|."""
    n, nJ = len(order), len(xm.joints)
    rows, cols, vals = [], [], []
    R = np.zeros(n * nJ)
    for i, z in enumerate(order):
        for c, j in enumerate(xm.joints):
            row = i * nJ + c
            for p, r, _o, z2 in xm.succ(z, j):
                R[row] += p * r
                if z2 is not None:
                    rows.append(row)
                    cols.append(index[z2])
                    vals.append(p)
    P = sp.csr_matrix((vals, (rows, cols)), shape=(n * nJ, n))   # duplicate entries are summed

    def qmat(V):
        return (R + GAMMA * (P @ V)).reshape(n, nJ)

    eye = sp.identity(n, format="csc")
    policy = np.zeros(n, dtype=np.int64)
    ar = np.arange(n)
    for _ in range(10000):
        sel = ar * nJ + policy
        A = (eye - GAMMA * P[sel]).tocsc()
        V = np.atleast_1d(spla.spsolve(A, R[sel]))
        Q = qmat(V)
        improve = Q.max(axis=1) > Q[ar, policy] + PI_IMPROVE_EPS
        if not improve.any():
            break
        policy = np.where(improve, Q.argmax(axis=1), policy)
    else:
        raise RuntimeError("policy iteration did not stabilise")
    for _ in range(1_000_000):
        Q = qmat(V)
        best = Q.max(axis=1)
        if float(np.max(np.abs(best - V))) <= POLISH_RESIDUAL:
            break
        V = best
    else:
        raise RuntimeError("Bellman polish did not converge")
    return V, Q


def _enumerate_views(xm: _XMachine):
    """Forward closure of (z, view) pairs from reset; returns {view: set(z)}."""
    belief = {}
    seen = set()
    frontier = deque()
    for z in xm.resets():
        node = (z, xm.reset_view(z[0]))
        if node not in seen:
            seen.add(node)
            frontier.append(node)
    while frontier:
        z, view = frontier.popleft()
        belief.setdefault(view, set()).add(z)
        for j in xm.joints:
            for _p, _r, _o, z2 in xm.succ(z, j):
                if z2 is None:
                    continue
                node = (z2, xm.next_view(view, j, z2[0]))
                if node not in seen:
                    seen.add(node)
                    frontier.append(node)
    return belief


def _oracle_success(xm: _XMachine, acc, views) -> float:
    """Exact P(success within MAX_STEPS ticks) of the label policy (lowest joint of the label set)."""
    starts = xm.resets()
    mass = {}
    for z in starts:
        node = (z, xm.reset_view(z[0]) if views is not None else None)
        mass[node] = mass.get(node, 0.0) + 1.0 / len(starts)
    success = 0.0
    for _t in range(MAX_STEPS):
        nxt = {}
        for (z, view), pm in mass.items():
            label = views[view]["I"] if views is not None else acc[z]
            if not label:
                return float("nan")     # label policy undefined on a visited view (X3 fails)
            a = min(label)
            for p, r, o, z2 in xm.succ(z, a):
                if o == "success":
                    success += pm * p
                elif z2 is not None:
                    key = (z2, xm.next_view(view, a, z2[0]) if views is not None else None)
                    nxt[key] = nxt.get(key, 0.0) + pm * p
        mass = nxt
    return success


def solve_x(px: dict) -> dict:
    xm = _XMachine(px)
    order, index = _reachable(xm)
    V, Q = _solve_values(xm, order, index)
    states, acc = {}, {}
    for i, z in enumerate(order):
        m = Q[i].max()
        a = frozenset(j for c, j in enumerate(xm.joints) if Q[i, c] >= m - TOL)
        acc[z] = a
        states[z] = {"V": float(V[i]), "acceptable": a}
    views = None
    if xm.hidden:
        views = {}
        for view, zs in _enumerate_views(xm).items():
            label = frozenset(xm.joints)
            for z in zs:
                label = label & acc[z]
            views[view] = {"belief": frozenset(zs), "I": label}
    return {"states": states, "views": views, "oracle_success": _oracle_success(xm, acc, views)}
