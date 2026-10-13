"""Exact V-infinity teacher for mz-1 programs (docs/machine_zoo/SPEC.md §5), vectorized with numpy.

    T = solve(program, budget=60_000)        # raises StateBudgetExceeded(n_seen, budget) when |S| > budget

States are int64 mixed-radix codes over the var ranges (code = sum_i (x_i - lo_i) * mult_i, last var least
significant), so increasing code order == lexicographic order of state tuples; S is stored sorted by code.

Reachable set S: breadth-first from the start set over every valid joint and every rand outcome; a transition's
successor joins S only when its outcome is running. Every state of S is expanded exactly once; the expansion is kept
and becomes the transition table (no second pass).

Fields of a solved Teacher (also used by lane A2 gates/weak bot):
    X       int64 (n, n_vars)   state values, row i = state i (codes ascending)
    codes   int64 (n,)
    valid   int64 (n_valid,)    valid joints, increasing
    w_vals  int64 (n_w,), pw float64 (n_w,)   rand outcomes in listed order (w = 0, p = 1 when rand is null)
    nxt     int32 (n, n_valid, n_w)   next state index, or NXT_CRASH = -1 (crash, incl. out-of-range), NXT_SUCCESS = -2
    Qv      float64 (n, n_valid); Q float64 (n, 27) with -inf at invalid joints; V float64 (n,)
    fired_changed bool[n_rules]  rule fired and assigned a value != the target's pre-rule value (or out-of-range
                                 crash) in at least one transition from S (SPEC §8 G8)
    residual  max_s |V(s) - max_j Q(s, j)| (asserted <= 1e-9), solve_info, timing (enumerate_s, solve_s, total_s)
    index_of(state) -> int, state(i) -> tuple, states() -> list[tuple], acceptable(i) -> bool[27]

Solver: Jacobi value iteration from 0 (<= 60 sweeps, stops at max|dV| < 1e-6); if not converged (long horizons),
<= 10 Gauss-Seidel sweeps from the lower bound V = -200 over states ordered by backward-BFS distance to a success
transition; then policy iteration with exact sparse solves (scipy.sparse.linalg.spsolve) until the greedy policy is
stable (a state switches only on an improvement > PI_SWITCH = 5e-10); then the Bellman residual is checked (VI polish
sweeps if needed) and asserted <= 1e-9. Stored V = max_j Q(s, j) with Q from the final policy's exact values.
"""

from __future__ import annotations

import time

import numpy as np

from nagi.burst2._rt.machine_zoo import interp

GAMMA = interp.GAMMA
TOL = interp.TOL
STATE_BUDGET = interp.STATE_BUDGET
NXT_CRASH, NXT_SUCCESS = -1, -2
R_RUN, R_CRASH, R_SUCCESS = -1.0, -200.0, 49.0
RESIDUAL_MAX = 1e-9
PI_SWITCH = 5e-10  # policy iteration switches a state's action only on a larger improvement (|V - V*| <= 100x)
_CHUNK_ROWS = 262_144


class StateBudgetExceeded(RuntimeError):
    """|S| exceeds the state budget (SPEC §8 G1); n_seen is a lower bound of |S| when BFS stopped."""

    def __init__(self, n_seen: int, budget: int):
        super().__init__(f"reachable set exceeds budget: > {budget} states (seen {n_seen})")
        self.n_seen, self.budget = n_seen, budget

    def __reduce__(self):
        return (StateBudgetExceeded, (self.n_seen, self.budget))


# ---------------------------------------------------------------------------------------------- vector evaluation
# Arrays broadcast over (n_states, n_valid, n_w): vars start as (n, 1, 1), commands are (1, J, 1), w is (1, 1, W).


def _vev(e, xs, cm, wv):
    k, terms = e
    out = None
    for c, kind, i in terms:
        if kind == 0:
            a = xs[i]
        elif kind == 1:
            a = np.abs(xs[i])
        elif kind == 2:
            a = np.sign(xs[i])
        elif kind == 3:
            a = cm[i]
        elif kind == 4:
            a = np.abs(cm[i])
        else:
            a = wv
        t = a if c == 1 else (-a if c == -1 else c * a)
        out = t if out is None else out + t
    if out is None:
        return np.int64(k)
    return out + k if k else out


def _vcmp(v, op, c):
    if op == 0:
        return v <= c
    if op == 1:
        return v >= c
    if op == 2:
        return v == c
    if op == 3:
        return v != c
    if op == 4:
        return v < c
    return v > c


def _vpt(p, xs, cm, wv):
    is_all, items = p
    acc = None
    for it in items:
        r = _vpt(it[1], xs, cm, wv) if it[0] == 1 else _vcmp(_vev(it[1], xs, cm, wv), it[2], it[3])
        acc = r if acc is None else ((acc & r) if is_all else (acc | r))
    return acc


class VecProg:
    """Vectorized SPEC §4 transition kernel of a compiled program (interp.Prog)."""

    def __init__(self, prog: interp.Prog):
        self.prog = prog
        self.nv = prog.nv
        self.lo = np.array(prog.lo, dtype=np.int64)
        self.hi = np.array(prog.hi, dtype=np.int64)
        self.radix = self.hi - self.lo + 1
        mult = np.ones(self.nv, dtype=np.int64)
        for i in range(self.nv - 2, -1, -1):
            mult[i] = mult[i + 1] * self.radix[i + 1]
        self.mult = mult
        self.valid = np.array(prog.valid_joints, dtype=np.int64)
        self.J = len(self.valid)
        cmd = np.array([prog.cmds[j] for j in prog.valid_joints], dtype=np.int64).reshape(self.J, prog.nc)
        self.cm = [cmd[:, c].reshape(1, self.J, 1) for c in range(prog.nc)]
        self.w_vals = np.array(prog.w_vals, dtype=np.int64)
        self.W = len(self.w_vals)
        self.wv = self.w_vals.reshape(1, 1, self.W)
        self.pw = np.array(prog.w_probs, dtype=np.float64)
        self.n_rules = len(prog.rules)

    def encode(self, state) -> int:
        return int(sum((int(v) - int(lo)) * int(m) for v, lo, m in zip(state, self.lo, self.mult)))

    def decode(self, codes: np.ndarray) -> np.ndarray:
        codes = np.asarray(codes, dtype=np.int64)
        return (codes[:, None] // self.mult[None, :]) % self.radix[None, :] + self.lo[None, :]

    def expand(self, codes: np.ndarray, fc: np.ndarray) -> np.ndarray:
        """Successor codes (n, J, W) of ``codes`` (NXT_CRASH / NXT_SUCCESS sentinels); ORs G8 flags into ``fc``."""
        n = len(codes)
        X = self.decode(codes)
        xs = [X[:, i].reshape(n, 1, 1) for i in range(self.nv)]
        cm, wv = self.cm, self.wv
        shape = (n, self.J, self.W)
        alive = None  # None == every row alive
        oob = None
        prog = self.prog
        for r, (t, e, g) in enumerate(prog.rules):
            fire = alive if g is None else (_vpt(g, xs, cm, wv) if alive is None else alive & _vpt(g, xs, cm, wv))
            val = _vev(e, xs, cm, wv)
            old = xs[t]
            lo, hi = prog.lo[t], prog.hi[t]
            if prog.oob_crash[t]:
                inr = (val >= lo) & (val <= hi)
                bad = ~inr if fire is None else (fire & ~inr)
                upd = inr if fire is None else (fire & inr)
                if not fc[r]:
                    fc[r] = bool(np.any(bad)) or bool(np.any(upd & (val != old)))
                xs[t] = np.where(upd, val, old)
                if np.any(bad):
                    bad = np.broadcast_to(bad, shape)
                    alive = ~bad if alive is None else (alive & ~bad)
                    oob = bad if oob is None else (oob | bad)
            else:
                nvl = np.clip(val, lo, hi)
                if fire is None:
                    if not fc[r]:
                        fc[r] = bool(np.any(nvl != old))
                    xs[t] = nvl
                else:
                    if not fc[r]:
                        fc[r] = bool(np.any(fire & (nvl != old)))
                    xs[t] = np.where(fire, nvl, old)
        crash = oob
        for q in prog.crash:
            c = _vpt(q, xs, cm, wv)
            crash = c if crash is None else (crash | c)
        goal = _vpt(prog.goal, xs, cm, wv)
        code = np.zeros(shape, dtype=np.int64)
        for i in range(self.nv):
            if self.mult[i]:
                code += (xs[i] - self.lo[i]) * self.mult[i]
        code = np.where(goal, NXT_SUCCESS, code)
        if crash is not None:
            code = np.where(crash, NXT_CRASH, code)
        return np.broadcast_to(code, shape)


# ---------------------------------------------------------------------------------------------- teacher


class Teacher:
    """Reachable set, transition table and exact values of one program (see module docstring)."""

    def __init__(self, program, budget: int = STATE_BUDGET):
        t0 = time.perf_counter()
        self.prog = interp.compile_program(program)
        self.program = self.prog.program
        self.vp = vp = VecProg(self.prog)
        self.valid, self.w_vals, self.pw = vp.valid, vp.w_vals, vp.pw
        self.fired_changed = np.zeros(vp.n_rules, dtype=bool)
        self._enumerate(budget)
        t1 = time.perf_counter()
        self._solve()
        t2 = time.perf_counter()
        self.timing = {"enumerate_s": t1 - t0, "solve_s": t2 - t1, "total_s": t2 - t0}

    # ------------------------------------------------------------------ BFS + table
    def _enumerate(self, budget: int) -> None:
        vp = self.vp
        starts = np.unique(np.array([vp.encode(s) for s in self.prog.start], dtype=np.int64))
        if len(starts) > budget:
            raise StateBudgetExceeded(len(starts), budget)
        visited = starts
        frontier = starts
        chunk = max(1, _CHUNK_ROWS // (vp.J * vp.W))
        store_src, store_nk = [], []
        while len(frontier):
            parts = []
            for c in range(0, len(frontier), chunk):
                src = frontier[c : c + chunk]
                nk = vp.expand(src, self.fired_changed)
                store_src.append(src)
                store_nk.append(nk)
                run = nk[nk >= 0]
                if run.size:
                    parts.append(np.unique(run))
            if not parts:
                break
            succ = np.unique(np.concatenate(parts)) if len(parts) > 1 else parts[0]
            pos = np.searchsorted(visited, succ)
            found = visited[np.minimum(pos, len(visited) - 1)] == succ
            new = succ[~found]
            if len(visited) + len(new) > budget:
                raise StateBudgetExceeded(len(visited) + len(new), budget)
            if len(new):
                visited = np.concatenate([visited, new])
                visited.sort(kind="stable")
            frontier = new
        self.codes = visited
        n = len(visited)
        self.n_states = n
        self.X = vp.decode(visited)
        nxt = np.empty((n, vp.J, vp.W), dtype=np.int32)
        for src, nk in zip(store_src, store_nk):
            rows = np.searchsorted(visited, src)
            idx = np.searchsorted(visited, nk)
            run = nk >= 0
            ok = visited[np.minimum(idx, n - 1)] == nk
            if not np.array_equal(ok, run):
                raise AssertionError("running successor outside the enumerated set")
            nxt[rows] = np.where(run, idx, nk)
        self.nxt = nxt

    # ------------------------------------------------------------------ Bellman solution
    def _prepare(self) -> None:
        n = self.n_states
        nxt = self.nxt
        rew = np.where(nxt == NXT_CRASH, R_CRASH, np.where(nxt == NXT_SUCCESS, R_SUCCESS, R_RUN))
        base = self.pw[0] * rew[:, :, 0]
        for w in range(1, len(self.pw)):
            base = base + self.pw[w] * rew[:, :, w]
        self._base = base
        self._nxt_ext = np.where(nxt >= 0, nxt, n).astype(np.int64)  # sentinel n has value 0
        self._gpw = GAMMA * self.pw

    def q_valid(self, V: np.ndarray) -> np.ndarray:
        """Q over valid joints (n, n_valid) for a value vector V (n,)."""
        if getattr(self, "_base", None) is None:
            self._prepare()
        Vext = np.append(V, 0.0)
        acc = self._base.copy()
        for w in range(len(self.pw)):
            acc += self._gpw[w] * Vext[self._nxt_ext[:, :, w]]
        return acc

    def _policy_eval(self, pi: np.ndarray) -> np.ndarray:
        from scipy.sparse import csr_matrix, identity
        from scipy.sparse.linalg import spsolve

        n = self.n_states
        ar = np.arange(n)
        cols = self.nxt[ar, pi, :]  # (n, W)
        run = cols >= 0
        rows = np.broadcast_to(ar[:, None], cols.shape)[run]
        vals = np.broadcast_to(self.pw[None, :], cols.shape)[run]
        P = csr_matrix((vals, (rows, cols[run])), shape=(n, n))
        A = (identity(n, format="csr") - GAMMA * P).tocsc()
        return np.asarray(spsolve(A, self._base[ar, pi]), dtype=np.float64)

    def _layers(self) -> list[np.ndarray]:
        """States grouped by backward-BFS distance to a success transition (any joint, any w), nearest first;
        states that cannot reach success form the last group. Used to order Gauss-Seidel sweeps."""
        n = self.n_states
        J, W = self.nxt.shape[1], self.nxt.shape[2]
        flat = self.nxt.reshape(-1)
        run = flat >= 0
        dst = flat[run].astype(np.int64)
        src = (np.flatnonzero(run) // (J * W)).astype(np.int64)
        order = np.argsort(dst, kind="stable")
        src_sorted = src[order]
        indptr = np.searchsorted(dst[order], np.arange(n + 1))
        layer = np.full(n, -1, dtype=np.int64)
        frontier = np.flatnonzero((self.nxt == NXT_SUCCESS).any(axis=(1, 2)))
        layer[frontier] = 0
        groups = [frontier] if frontier.size else []
        k = 0
        while frontier.size:
            k += 1
            a, b = indptr[frontier], indptr[frontier + 1]
            lens = b - a
            tot = int(lens.sum())
            if tot == 0:
                break
            idx = np.repeat(a - np.cumsum(lens) + lens, lens) + np.arange(tot)
            preds = np.unique(src_sorted[idx])
            preds = preds[layer[preds] < 0]
            layer[preds] = k
            if preds.size:
                groups.append(preds)
            frontier = preds
        rest = np.flatnonzero(layer < 0)
        if rest.size:
            groups.append(rest)
        return groups

    def _gs_sweep(self, Vext: np.ndarray, groups: list[np.ndarray], inner: int = 4) -> float:
        """One in-place Gauss-Seidel Bellman sweep over ``groups`` in order; returns max |dV|."""
        d = 0.0
        for idx in groups:
            base, nx = self._base[idx], self._nxt_ext[idx]
            for _inner in range(inner):  # repeated updates resolve chains inside one distance layer
                acc = base.copy()
                for w in range(len(self.pw)):
                    acc += self._gpw[w] * Vext[nx[:, :, w]]
                v = acc.max(axis=1)
                dd = float(np.max(np.abs(v - Vext[idx])))
                Vext[idx] = v
                if _inner == 0:
                    d = max(d, dd)
                if dd < 1e-6:
                    break
        return d

    def _solve(self) -> None:
        n = self.n_states
        self._prepare()
        info: dict = {}
        V = np.zeros(n)
        vi = 0
        d = np.inf
        for vi in range(1, 61):
            Vn = self.q_valid(V).max(axis=1)
            d = float(np.max(np.abs(Vn - V)))
            V = Vn
            if d < 1e-6:
                break
        if d >= 1e-6:
            # Long horizons: Gauss-Seidel sweeps ordered by distance to success, started from the lower bound
            # V = -200 <= V* (no policy is worth less than crashing now), propagate values along whole paths.
            groups = self._layers()
            Vext = np.append(np.full(n, R_CRASH), 0.0)
            gs = 0
            for gs in range(1, 11):
                if self._gs_sweep(Vext, groups) < 1e-6:
                    break
            V = Vext[:n].copy()
            info["gs_sweeps"] = gs
            info["n_layers"] = len(groups)
        info["vi_sweeps"] = vi
        ar = np.arange(n)
        pi = self.q_valid(V).argmax(axis=1)
        pit = 0
        for pit in range(1, 501):
            V = self._policy_eval(pi)
            Q = self.q_valid(V)
            best = Q.max(axis=1)
            keep = Q[ar, pi] >= best - PI_SWITCH  # residual at exit <= PI_SWITCH + solve error
            if keep.all():
                break
            pi = np.where(keep, pi, Q.argmax(axis=1))
        else:
            raise AssertionError("policy iteration did not stabilise in 500 iterations")
        info["pi_iters"] = pit
        res = float(np.max(np.abs(V - best))) if n else 0.0
        polish = 0
        while res > RESIDUAL_MAX and polish < 2000:
            V = best
            Q = self.q_valid(V)
            best = Q.max(axis=1)
            res = float(np.max(np.abs(V - best)))
            polish += 1
        info["polish_sweeps"] = polish
        if res > RESIDUAL_MAX:
            raise AssertionError(f"Bellman residual {res} > {RESIDUAL_MAX}")
        self.V = best  # == max_j Q(s, j) exactly; |best - V^pi| = residual
        self.residual = res
        self.solve_info = info
        Q27 = np.full((n, interp.N_JOINT), -np.inf)
        Q27[:, self.valid] = Q
        self.Q = Q27
        self._base = self._nxt_ext = None  # free solver work arrays (rebuilt on demand by q_valid)

    # ------------------------------------------------------------------ lookup
    @property
    def Qv(self) -> np.ndarray:
        """Q over valid joints (n, n_valid)."""
        return self.Q[:, self.valid]

    def index_of(self, state) -> int:
        k = self.vp.encode(state)
        i = int(np.searchsorted(self.codes, k))
        if i >= self.n_states or self.codes[i] != k or len(state) != self.vp.nv:
            raise KeyError(f"state not in the reachable non-terminal set: {tuple(state)}")
        return i

    def state(self, i: int) -> tuple:
        return tuple(int(v) for v in self.X[i])

    def states(self) -> list[tuple]:
        return [tuple(r) for r in self.X.tolist()]

    def acceptable(self, i: int) -> np.ndarray:
        q = self.Q[i]
        return q >= q.max() - TOL


def solve(program, budget: int = STATE_BUDGET) -> Teacher:
    """Solved Teacher of ``program``; raises StateBudgetExceeded when |S| > budget."""
    return Teacher(program, budget=budget)


def try_solve(program, budget: int = STATE_BUDGET):
    """Teacher, or the StateBudgetExceeded instance (marker with ``.n_seen``) when |S| > budget."""
    try:
        return Teacher(program, budget=budget)
    except StateBudgetExceeded as ex:
        return ex
