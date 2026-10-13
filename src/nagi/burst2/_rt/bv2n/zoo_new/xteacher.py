"""Exact teacher for ``mz-1x`` (docs/burst_v2_next/ZOO_NEW_SPEC.md §3-§5).

1. Base: ``machine_zoo.teacher.solve`` on the mz-1 base program (reachable set S, transition table nxt[i, a, w]).
2. Delay d: augmented MDP over z = (i, q_1..q_d), q = valid-joint positions in flight (q_1 applied next):
       (i, q) --a, w--> (nxt[i, q_1, w], q_2..q_d, a)          (d = 0: (i) --a, w--> nxt[i, a, w])
   enumerated breadth-first from (start, KEEP^d) and solved by the base teacher's own exact solver
   (value iteration / Gauss-Seidel + policy iteration with an exact sparse solve, Bellman residual <= 1e-9).
3. Hidden vars: a VIEW = (last H displayed observations, last K = max(H-1, d) decided joints). Its belief B(x) =
   the augmented states consistent with x (forward filter, §4); label set I(x) = AND_{z in B(x)} A(z). Every view
   reachable under any joint sequence is enumerated breadth-first (identifiability gate: I(x) != {} for all).
4. Exact finite-horizon chains (100 ticks, uniform start) for any policy: success/crash/timeout, success-time
   distribution, expected visits. No Monte Carlo anywhere.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from nagi.burst2._rt.machine_zoo import interp, teacher
from nagi.burst2._rt.machine_zoo.weak import WeakTable, rand_weights

from . import xdsl

NXT_CRASH = teacher.NXT_CRASH
NXT_SUCCESS = teacher.NXT_SUCCESS
TOL = 1e-6
MAX_STEPS = 100
BASE_BUDGET = 60_000
AUG_BUDGET = 100_000
VIEW_BUDGET = 200_000
R_RUN, R_CRASH, R_SUCCESS = -1.0, -200.0, 49.0


class XBudgetExceeded(RuntimeError):
    def __init__(self, what: str, n_seen: int, budget: int):
        super().__init__(f"{what}: more than {budget} (seen {n_seen})")
        self.what, self.n_seen, self.budget = what, n_seen, budget


@dataclass(frozen=True)
class XView:
    """What the client legitimately knows at a decision (LANES ClientView contract, Zoo flavour).

    obs: H entries, oldest first; None = before the episode start, else the tuple of displayed var values
         (program order of displayed vars). obs[-1] is the current observation.
    dec: K = max(H-1, d) entries, oldest first: joints (0..26) this client decided at the last K ticks; None = before
         start and not in flight; pre-start in-flight entries are KEEP (13). The last d entries are in flight.
    """

    obs: tuple
    dec: tuple


class _AugSolve(teacher.Teacher):
    """Reuse the verified mz-1 Bellman solver on an explicit transition table (no BFS, no program)."""

    def __init__(self, nxt: np.ndarray, valid: np.ndarray, pw: np.ndarray):  # noqa: D401 (no super().__init__)
        self.nxt, self.valid, self.pw = nxt, valid, pw
        self.n_states = int(nxt.shape[0])
        self._base = None
        t0 = time.perf_counter()
        self._solve()
        self.timing = {"solve_s": time.perf_counter() - t0}


class XTeacher:
    def __init__(self, px: dict, base_budget: int = BASE_BUDGET, aug_budget: int = AUG_BUDGET,
                 view_budget: int = VIEW_BUDGET):
        t0 = time.perf_counter()
        xdsl.validate(px)
        self.px = px
        self.d = d = px["delay"]
        self.H = px["window"]
        self.K = xdsl.history_len(px)
        self.base_program = px["base"]
        try:
            self.base = B = teacher.solve(px["base"], budget=base_budget)
        except teacher.StateBudgetExceeded as ex:
            raise XBudgetExceeded("base states", ex.n_seen, base_budget) from None
        self.valid = B.valid
        self.nv = nv = len(B.valid)
        self.pw = B.pw
        self.nw = len(B.pw)
        self.keep_pos = int(np.flatnonzero(B.valid == xdsl.KEEP_JOINT)[0])
        self.M = nv ** d
        self._enumerate_aug(aug_budget)
        t1 = time.perf_counter()
        if d == 0:
            self.Q = B.Q  # identical solve (the augmented table IS the base table)
            self.residual = B.residual
        else:
            S = _AugSolve(self.nxt, self.valid, self.pw)
            self.Q = S.Q
            self.residual = S.residual
        self.Qv = self.Q[:, self.valid]
        self.acc = self.Qv >= self.Qv.max(axis=1, keepdims=True) - TOL  # (N, nv)
        t2 = time.perf_counter()
        names = [v["name"] for v in self.base_program["vars"]]
        disp = xdsl.displayed(px)
        self.disp_cols = [names.index(n) for n in disp]
        rows, inv = np.unique(B.X[:, self.disp_cols], axis=0, return_inverse=True)
        self.obs_vals = [tuple(int(x) for x in r) for r in rows]
        self.obs_code = {v: k for k, v in enumerate(self.obs_vals)}
        self.oc_base = inv.reshape(-1).astype(np.int64)
        self.oc = self.oc_base[self.aug_base]
        self.hidden = bool(px["hidden"])
        self.views = None
        if self.hidden:
            self._enumerate_views(view_budget)
        t3 = time.perf_counter()
        self.timing = {"base_s": B.timing["total_s"], "aug_enum_s": t1 - t0 - B.timing["total_s"],
                       "aug_solve_s": t2 - t1, "views_s": t3 - t2, "total_s": t3 - t0}

    # ------------------------------------------------------------------ augmented MDP
    def _enumerate_aug(self, budget: int) -> None:
        B, d, nv, nw, M = self.base, self.d, self.nv, self.nw, self.M
        start_base = np.array([B.index_of(tuple(s)) for s in interp.start_states(self.base_program)], np.int64)
        qkeep = sum(self.keep_pos * nv ** (d - 1 - k) for k in range(d))
        starts = start_base * M + qkeep
        self.start_codes = starts  # SPEC §3 start-set order (distinct states)
        visited = np.unique(starts)
        frontier = visited
        store = []
        a_ar = np.arange(nv, dtype=np.int64)
        while len(frontier):
            nk = self._expand(frontier, a_ar)
            store.append((frontier, nk))
            run = nk[nk >= 0]
            succ = np.unique(run)
            pos = np.searchsorted(visited, succ)
            found = visited[np.minimum(pos, len(visited) - 1)] == succ
            new = succ[~found]
            if len(visited) + len(new) > budget:
                raise XBudgetExceeded("augmented states", len(visited) + len(new), budget)
            visited = np.sort(np.concatenate([visited, new]))
            frontier = new
        self.codes = visited
        n = self.N = len(visited)
        nxt = np.empty((n, nv, nw), dtype=np.int32)
        for src, nk in store:
            rows = np.searchsorted(visited, src)
            idx = np.searchsorted(visited, nk)
            nxt[rows] = np.where(nk >= 0, idx, nk)
        self.nxt = nxt
        self.aug_base = visited // M
        qc = visited % M
        self.aug_q = np.stack([(qc // nv ** (d - 1 - k)) % nv for k in range(d)], axis=1) if d else \
            np.zeros((n, 0), np.int64)
        self.start_idx = np.searchsorted(visited, starts)

    def _expand(self, codes: np.ndarray, a_ar: np.ndarray) -> np.ndarray:
        """Successor codes (f, nv, nw); negative = NXT_CRASH / NXT_SUCCESS."""
        B, d, nv, M = self.base, self.d, self.nv, self.M
        i = codes // M
        if d == 0:
            return B.nxt[i].astype(np.int64)
        qc = codes % M
        q1 = qc // nv ** (d - 1)
        rest = qc % nv ** (d - 1)
        nb = B.nxt[i, q1, :].astype(np.int64)  # (f, nw): the applied joint is q1, not a
        tail = (rest * nv)[:, None, None] + a_ar[None, :, None]
        out = nb[:, None, :] * M + tail
        return np.where(nb[:, None, :] >= 0, out, nb[:, None, :])

    def aug_index(self, base_state: tuple, queue: tuple) -> int:
        """Index of (base state, in-flight joints oldest first) in the augmented set (KeyError if unreachable)."""
        i = self.base.index_of(tuple(base_state))
        code = i * self.M + sum(self._pos(j) * self.nv ** (self.d - 1 - k) for k, j in enumerate(queue))
        p = int(np.searchsorted(self.codes, code))
        if p >= self.N or self.codes[p] != code:
            raise KeyError((base_state, queue))
        return p

    def _pos(self, j: int) -> int:
        p = np.flatnonzero(self.valid == j)
        if not len(p):
            raise ValueError(f"invalid joint {j}")
        return int(p[0])

    def aug_state(self, z: int) -> tuple[tuple, tuple]:
        return tuple(int(x) for x in self.base.X[self.aug_base[z]]), tuple(int(self.valid[q]) for q in self.aug_q[z])

    # ------------------------------------------------------------------ views (hidden vars)
    def belief(self, key: tuple) -> np.ndarray:
        """Augmented states consistent with a view key (obs codes, -1 = PAD; dec positions, -1 = PAD)."""
        H, K, d = self.H, self.K, self.d
        obs, dec = key[:H], key[H:]
        m = next(k for k in range(H) if obs[k] >= 0)
        if m > 0:  # the episode started inside the window: start states, KEEP in flight
            Bz = self.start_idx[self.oc[self.start_idx] == obs[m]]
            Bz = np.unique(Bz)
        else:
            mask = self.oc == obs[0]
            j0 = K - H + 1  # dec index of the window's first tick
            for k in range(d):
                jd = j0 - d + k
                if jd >= 0 and dec[jd] >= 0:
                    mask &= self.aug_q[:, k] == dec[jd]
            Bz = np.flatnonzero(mask)
        for s in range(m, H - 1):
            a = dec[K - H + 1 + s]
            nz = self.nxt[Bz, a, :].ravel()
            nz = np.unique(nz[nz >= 0])
            Bz = nz[self.oc[nz] == obs[s + 1]]
        return Bz

    def _start_keys(self) -> list[tuple]:
        H, K, d = self.H, self.K, self.d
        dec = (-1,) * (K - d) + (self.keep_pos,) * d
        return sorted({(-1,) * (H - 1) + (int(self.oc[z]),) + dec for z in self.start_idx})

    def _succ_keys(self, key: tuple, Bz: np.ndarray):
        H = self.H
        obs, dec = key[:H], key[H:]
        for a in range(self.nv):
            nz = self.nxt[Bz, a, :].ravel()
            nz = nz[nz >= 0]
            if not nz.size:
                continue
            for o in np.unique(self.oc[nz]):
                yield a, obs[1:] + (int(o),) + ((dec[1:] + (a,)) if self.K else ())

    def _enumerate_views(self, budget: int) -> None:
        keys = self._start_keys()
        index = {k: n for n, k in enumerate(keys)}
        I, bsize, succ = [], [], []
        n = 0
        while n < len(keys):
            key = keys[n]
            Bz = self.belief(key)
            if not Bz.size:
                raise AssertionError(f"reachable view with empty belief: {key}")
            I.append(self.acc[Bz].all(axis=0))
            bsize.append(len(Bz))
            row = []
            for a, k2 in self._succ_keys(key, Bz):
                if k2 not in index:
                    index[k2] = len(keys)
                    keys.append(k2)
                    if len(keys) > budget:
                        raise XBudgetExceeded("views", len(keys), budget)
                row.append((a, k2))
            succ.append(row)
            n += 1
        self.views = keys
        self.view_index = index
        self.I = np.array(I, dtype=bool).reshape(len(keys), self.nv)
        self.belief_size = np.array(bsize, dtype=np.int64)

    def view_key(self, v: XView) -> tuple:
        if len(v.obs) != self.H or len(v.dec) != self.K:
            raise ValueError(f"view needs {self.H} obs and {self.K} dec entries")
        obs = tuple(-1 if o is None else self.obs_code[tuple(o)] for o in v.obs)
        dec = tuple(-1 if j is None else self._pos(j) for j in v.dec)
        return obs + dec

    def label_set(self, v: XView) -> np.ndarray:
        """Bool over valid positions: I(x) (hidden) or A(z) (fully observed augmented state)."""
        key = self.view_key(v)
        if self.hidden:
            n = self.view_index.get(key)
            if n is not None:
                return self.I[n]
            Bz = self.belief(key)
            if not Bz.size:
                raise KeyError(f"view not reachable: {v}")
            return self.acc[Bz].all(axis=0)
        z = self.aug_index(tuple(v.obs[-1]), tuple(v.dec[len(v.dec) - self.d:]) if self.d else ())
        return self.acc[z]

    def label(self, v: XView) -> dict:
        """Teacher API (LANES): joint = lowest-index label joint a*; acceptable = the exact label set (I(x) for hidden
        views, A(z) otherwise); q27 = augmented Q when the view determines the augmented state (no hidden vars), else
        None. Per-slot targets are built by render_hook.targets (tie-broken max-marginals toward a*, R2.13) — never
        sum-marginals of the set."""
        I = self.label_set(v)
        joints = [int(j) for j in self.valid[I]]
        if not joints:
            raise AssertionError("empty label set (identifiability violated)")
        q27 = None
        if not self.hidden:
            z = self.aug_index(tuple(v.obs[-1]), tuple(v.dec[len(v.dec) - self.d:]) if self.d else ())
            q27 = [float(x) for x in self.Q[z]]
        return {"joint": joints[0], "acceptable": joints, "q27": q27}

    # ------------------------------------------------------------------ policies on augmented states
    def pol_oracle(self) -> np.ndarray:
        return _onehot(np.argmax(self.acc, axis=1), self.nv)

    def pol_keep(self) -> np.ndarray:
        return _onehot(np.full(self.N, self.keep_pos), self.nv)

    def pol_random(self) -> np.ndarray:
        return np.full((self.N, self.nv), 1.0 / self.nv)

    def pol_delay_blind(self) -> np.ndarray:
        """Plays the d = 0 oracle's lowest acceptable joint for the TRUE current base state (ignores the queue)."""
        Qb = self.base.Qv
        accb = Qb >= Qb.max(axis=1, keepdims=True) - TOL
        return _onehot(np.argmax(accb, axis=1)[self.aug_base], self.nv)

    def pol_weak(self) -> np.ndarray:
        """SPEC §7 weak bot on the TRUE current base state as if there were no delay (uniform over candidates)."""
        W = WeakTable(self.base_program, self.base.X, self.base.nxt, self.valid, rand_weights(self.base_program))
        c = W.cand[self.aug_base].astype(np.float64)
        return c / c.sum(axis=1, keepdims=True)

    def pol_memoryless(self) -> np.ndarray:
        """Hidden probe: acts on the current observation + in-flight queue only; argmax of the belief-average Q
        (uniform over consistent augmented states), lowest index on ties."""
        qcode = self.codes % self.M
        grp = self.oc * self.M + qcode
        u, inv = np.unique(grp, return_inverse=True)
        inv = inv.reshape(-1)
        meanQ = np.zeros((len(u), self.nv))
        np.add.at(meanQ, inv, self.Qv)
        cnt = np.bincount(inv, minlength=len(u))[:, None]
        meanQ /= cnt
        best = meanQ >= meanQ.max(axis=1, keepdims=True) - TOL
        return _onehot(np.argmax(best, axis=1)[inv], self.nv)

    # ------------------------------------------------------------------ exact chains
    def chain(self, P: np.ndarray, steps: int = MAX_STEPS) -> dict:
        """Exact episode statistics of a stationary policy P (N, nv) on the augmented MDP from a uniform start."""
        p = np.zeros(self.N)
        np.add.at(p, self.start_idx, 1.0 / len(self.start_idx))
        succ_t = np.zeros(steps + 1)
        crash_t = np.zeros(steps + 1)
        visits = np.zeros(self.N)
        ret = 0.0
        for t in range(1, steps + 1):
            visits += p
            q = np.zeros(self.N)
            for a in range(self.nv):
                pa = p * P[:, a]
                if not pa.any():
                    continue
                for w in range(self.nw):
                    m = pa * self.pw[w]
                    dst = self.nxt[:, a, w]
                    succ_t[t] += m[dst == NXT_SUCCESS].sum()
                    crash_t[t] += m[dst == NXT_CRASH].sum()
                    r = dst >= 0
                    np.add.at(q, dst[r], m[r])
            ret += R_RUN * q.sum() + R_CRASH * crash_t[t] + R_SUCCESS * succ_t[t]
            p = q
        return _chain_summary(succ_t, crash_t, p.sum(), ret, visits=visits)

    def view_oracle_chain(self, steps: int = MAX_STEPS) -> dict:
        """Exact chain of the label policy (lowest joint of I(x)) over (augmented state, view) pairs."""
        if not self.hidden:
            r = self.chain(self.pol_oracle(), steps)
            r["view_visits"] = r["visits"]
            return r
        pol = np.argmax(self.I, axis=1)
        H, K = self.H, self.K
        cur: dict = {}
        for z in self.start_idx:
            key = (-1,) * (H - 1) + (int(self.oc[z]),) + (-1,) * (K - self.d) + (self.keep_pos,) * self.d
            k = self.view_index[key]
            cur[(int(z), k)] = cur.get((int(z), k), 0.0) + 1.0 / len(self.start_idx)
        succ_t = np.zeros(steps + 1)
        crash_t = np.zeros(steps + 1)
        vv = np.zeros(len(self.views))
        zv = np.zeros(self.N)
        ret = 0.0
        for t in range(1, steps + 1):
            nxt: dict = {}
            for (z, k), m in cur.items():
                vv[k] += m
                zv[z] += m
                a = int(pol[k])
                key = self.views[k]
                for w in range(self.nw):
                    mw = m * self.pw[w]
                    nz = int(self.nxt[z, a, w])
                    if nz == NXT_SUCCESS:
                        succ_t[t] += mw
                    elif nz == NXT_CRASH:
                        crash_t[t] += mw
                    else:
                        k2 = key[1:H] + (int(self.oc[nz]),) + ((key[H + 1:] + (a,)) if K else ())
                        kk = (nz, self.view_index[k2])
                        nxt[kk] = nxt.get(kk, 0.0) + mw
            ret += R_RUN * sum(nxt.values()) + R_CRASH * crash_t[t] + R_SUCCESS * succ_t[t]
            cur = nxt
        r = _chain_summary(succ_t, crash_t, sum(cur.values()), ret, visits=zv)
        r["view_visits"] = vv
        r["undefined_mass"] = float(sum(vv[k] for k in np.flatnonzero(~self.I.any(axis=1))))
        if r["undefined_mass"] > 0:  # the label policy reaches a view with I(x) = {} (X3 fails): undefined
            r["success"] = float("nan")
        return r


def _onehot(idx: np.ndarray, nv: int) -> np.ndarray:
    P = np.zeros((len(idx), nv))
    P[np.arange(len(idx)), idx] = 1.0
    return P


def _chain_summary(succ_t, crash_t, timeout, ret, visits) -> dict:
    succ = float(succ_t.sum())
    out = {"success": succ, "crash": float(crash_t.sum()), "timeout": float(timeout), "mean_return": float(ret),
           "success_t": succ_t, "visits": visits}
    if succ > 0:
        cdf = np.cumsum(succ_t) / succ
        ts = np.arange(len(succ_t))
        q = {name: int(np.searchsorted(cdf, f - 1e-12)) for name, f in
             (("min", 1e-9), ("p10", .1), ("p25", .25), ("median", .5), ("p75", .75), ("p90", .9), ("max", 1.0))}
        q["mean"] = float((ts * succ_t).sum() / succ)
        out["len"] = q
    else:
        out["len"] = None
    return out
