"""Anytime exact search on the rulebook (LANES ``search``): iterative deepening under a wall-clock deadline.

    action, stats = search(machine, state, history=None, core=None, deadline_ms=200, max_sims=None)

Model (exact, from the rulebook only; never a teacher table, never a full solve; north-star compute rule):
    nodes = augmented states z = (base mz-1 state s, in-flight queue q_1..q_d)  (ZOO_NEW_SPEC §3; d = 0: z = s)
    z --j, w--> (tick(s, q_1, w), q_2..q_d, j)   (d = 0: tick(s, j, w)),  chance w with p_w = weight_w / W
    Q_k(z, j) = Σ_w p_w [ r(s, applied, w) + γ · 1{running} · V_{k-1}(z'_w) ],   V_0 ≡ 0,   V_d = max_j Q_d
    rewards −1 / −200 / +49, γ = 0.99 (mz-1 SPEC §4);  A_k = {j : Q̄_k(j) ≥ max Q̄_k − 1e-6}
    Q̄_k(j) = Q_k(z, j) for a known state; = mean over the belief roots z ∈ B of Q_k(z, j) for hidden vars (uniform
    belief over the consistent augmented states, v2g.machine.Machine.belief; "QMDP-k": after this decision the search
    treats the state as observed). With one root Q̄ IS Q (no averaging), so a fixed-depth run reproduces mc-2 S_k.
Delay: the pending queue is simulated exactly (the applied joint of the next d ticks is q_1..q_d). For k ≤ d the
decision cannot change any reward inside the horizon (all joints tie), so ``stats["lookahead"] = depth − d`` is the
number of ticks in which the decision matters.

Modes (prereg binding requirement, coordinator 2026-10-12 ~16:10: gates A/G/G+ score decisions as pure functions of
the request bytes, so every decision can be replayed):
    deterministic=True (DEFAULT, the eval/scoring mode): stop rules are k / kmax / exhausted / sims / memory only, with
    ``max_sims = DEFAULT_MAX_SIMS`` (S*) fixed, so Q, A_k, sims and depth are pure functions of the request; the pick
    inside A_k is ``tie="sample"`` with the caller's stream in the eval harness (CRN policy stream, mc-2 rule) and the
    SDK (session + step), or ``tie="hash"`` in the audit mode (owner/coordinator decision 2026-10-12 ~16:35);
    no state is carried across calls (the per-machine model is rebuilt inside every call unless the caller passes
    ``reuse_model=True``, which never changes a result); nothing branches on wall-clock time. The deadline is only a
    serving cap: it is reported (``stats["over_deadline"]`` = ms > deadline_ms) but never consulted. Gate L times this
    exact configuration on one core, uncached (scripts/v2g/latency.py).
    deterministic=False (serving fallback for hosts slower than the calibration host, opt-in): the wall-clock deadline
    also stops deepening (anytime); such decisions are host-dependent and are never used for scoring.

Algorithm: layered expansion (distinct nodes per depth, exact int64 keys = mixed-radix base key · nJ^d + queue code),
one-tick transitions by ``machine_zoo.tokens.Compiled.exec_tick`` (tested equal to ``interp.step_dist``), backward
induction with the float64 expression of ``machine_zoo.search`` (``acc = acc + p * (r + γ v)``, w in listed order),
so Q is bit-identical to mc-2's ``Searcher.q`` for d = 0 (test). Iterative deepening k = 1, 2, ...: each iteration
adds one layer (the shallower layers are reused, not recomputed); the decision uses the deepest
COMPLETED depth (one backup after the last layer). Stop rules, checked before each new layer (depth 1 is always
completed):
    k        fixed depth reached (``k=``)                 kmax      ``k_max`` (default 40)
    exhausted no running node left (deeper = same Q)      sims      next layer would exceed ``max_sims`` (exec_tick rows)
    deadline  (serving mode only) elapsed + predicted > budget_frac · deadline_ms, predicted = (seconds per transition
              of the last layer's expansion) × (next-layer transitions + BACKUP_COST × all transitions)
    memory    next layer > MAX_LAYER transitions
Wall-clock deadlines make the reached depth host-dependent; ``max_sims`` gives a deterministic budget (use it for
parity tests and reproducible dev runs).

Tie-break inside A_k: ``tie="uniform"`` (one ``rng.integers(len(A))`` on the policy stream: mc-2 S_k CRN),
``"sample"`` (= uniform, or a draw from the gated core prior inside A_k when the gate opened; the SDK / eval default,
see v2g.operate), ``"lowest"`` (lowest joint index) or ``"hash"`` (deterministic from the machine and the view; audit
mode). WARNING (dev, lanes/runtime.md §5): a deterministic tie-break on a stateless request is a stationary
deterministic policy and cycles when the goal is beyond the horizon (T4, S4: hash − uniform = −0.50 success).
The search itself (Q, A_k, sims, depth) never depends on the tie rule or the stream.
Coverage reporting (PREREG_V2G v0.1 C8; additive, never read by a decision): every decision's stats carry
``exhausted`` (the tree ran out of running nodes) and ``visited`` (distinct full states, i.e. augmented keys incl. the
delay queue and hidden vars, reached within the horizon, over all belief roots); ``reachable_count(machine)`` gives the
exact |R(M)| for the eval runner.

Core hook (optional; LANES Core.predict, shape agreed with lane v2g-core): the learned prior hurt search on unseen
machines (mc-2: H4 − S4 = −0.082 [−0.135, −0.029] on T_opus), so the core is used only through a confidence gate and
never overrides an exact search distinction: prior p over A_k (softmax of the core logits restricted to A_k);
gate open iff conf ≥ ``tau`` (default 0.9) -> choose argmax p within A_k, else the plain tie-break, where
conf = the core's calibrated ``p_opt[a]`` (P(a ∈ A*), per-joint BCE head of lane core) at a = argmax p when the core
returns ``p_opt``, else max p (a softmax splits mass over tied optima, so p_opt is the right gate when available).
``stats["gated"]`` = True iff the gate opened (the core decided the tie). Full-width layered expectimax has no
pruning, so a prior cannot reorder moves usefully; its only role is this gated tie-break. Optional leaf values
(``core_value=True``): when the final frontier has ≤ VALUE_LEAF_MAX nodes, the core value v ∈ [0, 1] (estimated
optimal success probability) is mapped to V_leaf = 49 v − 200 (1 − v) and Q̄ recomputed with those leaves; this Q̄ only
orders joints inside A_k (lexicographic after the exact search), under the same gate.
"""

from __future__ import annotations

import hashlib
import json
import math
import time

import numpy as np

GAMMA = 0.99
TOL = 1e-6
R_RUN, R_CRASH, R_SUCC = -1.0, -200.0, 49.0
OC_RUN, OC_SUCC, OC_CRASH = 0, 1, 2
DEFAULT_DEADLINE_MS = 200.0
DEFAULT_MAX_SIMS = 100_000  # S*: recommended by the 1-core uncached latency run (lanes/runtime.md §4), pending prereg
BUDGET_FRAC = 0.85
PREIMAGE_FRAC = 0.8  # search config v1: belief image rows allowed per decision, as a share of max_sims (charged)
BACKUP_COST = 0.5  # [E] backup time per transition / expansion time per transition (serving-mode deadline only)
K_MAX = 40
MAX_LAYER = 3_000_000
BELIEF_SEARCH_MAX = 512
VALUE_LEAF_MAX = 256
KEY_LIMIT = 2 ** 62


class SearchUnsupported(RuntimeError):
    pass


# ================================================================================ exact model on augmented keys
class ZooModel:
    """Vectorized exact one-tick model of an mz-1 / mz-1x Machine on int64 augmented keys (see module doc)."""

    def __init__(self, machine):
        self.m = machine
        cp = self.cp = machine.cp
        self.width = (cp.hi - cp.lo + 1).astype(np.int64)
        radix = np.ones(cp.nv, np.int64)
        for i in range(1, cp.nv):
            radix[i] = radix[i - 1] * self.width[i - 1]
        self.radix = radix
        self.vj = np.asarray(cp.valid_joints, np.int64)
        self.nJ, self.nW = len(self.vj), len(cp.w_vals)
        self.p = [float(x) for x in cp.w_p]
        self.cmds = cp.cmd[self.vj, :cp.nc]
        self.jpos = np.full(27, -1, np.int64)
        self.jpos[self.vj] = np.arange(self.nJ)
        self.d = int(machine.delay)
        self.M = self.nJ ** self.d
        space = 1
        for w in self.width.tolist():
            space *= int(w)
        if space * self.M >= KEY_LIMIT:
            raise SearchUnsupported(f"augmented key space {space * self.M} >= 2^62")

    def encode_base(self, X) -> np.ndarray:
        return ((np.asarray(X, np.int64) - self.cp.lo) * self.radix).sum(-1)

    def decode_base(self, keys) -> np.ndarray:
        keys = np.asarray(keys, np.int64)
        return (keys[:, None] // self.radix) % self.width + self.cp.lo

    def keys(self, base: np.ndarray, queue: np.ndarray) -> np.ndarray:
        k = self.encode_base(base)
        if self.d:
            qp = self.jpos[np.asarray(queue, np.int64)]
            if (qp < 0).any():
                raise ValueError("invalid joint in the in-flight queue")
            code = np.zeros(len(k), np.int64)
            for c in range(self.d):
                code = code * self.nJ + qp[:, c]
            k = k * self.M + code
        return k

    def expand(self, keys: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
        """(next key int64[n, nJ, nW] (-1 terminal), outcome int8[n, nJ, nW], exec_tick rows) for nodes ``keys``."""
        n, nJ, nW, cp = len(keys), self.nJ, self.nW, self.cp
        if self.d == 0:
            S = self.decode_base(keys)
            X = np.repeat(S, nJ * nW, axis=0)
            C = np.tile(np.repeat(self.cmds, nW, axis=0), (n, 1))
            W = np.tile(cp.w_vals, n * nJ)
            Xn, crash, succ, _ = cp.exec_tick(X, C, W)
            oc = np.where(crash, OC_CRASH, np.where(succ, OC_SUCC, OC_RUN)).astype(np.int8)
            nk = np.where(oc == OC_RUN, self.encode_base(Xn), -1)
            return nk.reshape(n, nJ, nW), oc.reshape(n, nJ, nW), n * nJ * nW
        base, qc = keys // self.M, keys % self.M
        top = nJ ** (self.d - 1)
        q1, rest = qc // top, qc % top
        S = self.decode_base(base)
        X = np.repeat(S, nW, axis=0)
        C = self.cmds[np.repeat(q1, nW)]
        W = np.tile(cp.w_vals, n)
        Xn, crash, succ, _ = cp.exec_tick(X, C, W)
        ocb = np.where(crash, OC_CRASH, np.where(succ, OC_SUCC, OC_RUN)).astype(np.int8).reshape(n, nW)
        nkb = self.encode_base(Xn).reshape(n, nW)
        child = (nkb[:, None, :] * self.M + (rest * nJ)[:, None, None] + np.arange(nJ, dtype=np.int64)[None, :, None])
        oc = np.broadcast_to(ocb[:, None, :], (n, nJ, nW))
        nk = np.where(oc == OC_RUN, child, -1)
        return nk, np.ascontiguousarray(oc), n * nW


def model_of(machine, reuse: bool = False) -> ZooModel:
    """Per-machine model (compiled rulebook + key radix). Built inside the decision; ``reuse=True`` keeps it on the
    machine object for later calls (speed only: the model is a pure function of the rulebook)."""
    mod = getattr(machine, "_v2g_model", None) if reuse else None
    if mod is None:
        mod = ZooModel(machine)
        if reuse:
            machine._v2g_model = mod
    return mod


def _backup(layers: list, p: list, nW: int, leaf_v: np.ndarray | None = None) -> np.ndarray:
    """Q at the roots (n_root_keys, nJ) from the layers; leaves (children of the deepest layer) have V = 0, or
    ``leaf_v`` (one value per deepest-layer child key) when given."""
    V_next = leaf_v
    for d in range(len(layers) - 1, -1, -1):
        oc, run, inv = layers[d]
        v = np.zeros(oc.shape, np.float64)
        if V_next is not None:
            v[run] = V_next[inv]
        r = np.where(oc == OC_CRASH, R_CRASH, np.where(oc == OC_SUCC, R_SUCC, R_RUN))
        acc = np.zeros(oc.shape[:2], np.float64)
        for w in range(nW):
            acc = acc + p[w] * (r[:, :, w] + GAMMA * v[:, :, w])
        if d == 0:
            return acc
        V_next = acc.max(1)
    raise AssertionError("no layers")


def deepen(model: ZooModel, root_keys: np.ndarray, t0: float, deadline_s: float | None, max_sims: int | None,
           k: int | None, k_max: int = K_MAX, track: bool = False) -> dict:
    """Iterative deepening from the (unique) root keys. Returns {Q (n_roots, nJ) at the deepest completed depth,
    depth, sims, transitions, stop, layers, frontier}. ``deadline_s`` = None makes the result a pure function of
    (model, root keys, max_sims, k, k_max). The backward induction runs once, after the last completed layer (no stop
    rule reads Q, so the intermediate backups of a textbook iterative deepening are not needed; same floats)."""
    keys, root_inv = np.unique(root_keys, return_inverse=True)
    layers = []
    seen = [keys] if track else None  # coverage audit only (distinct augmented states expanded or reached)
    depth = sims = transitions = 0
    rate = None
    stop = None
    nJ, nW = model.nJ, model.nW
    sims_per_node = nW if model.d else nJ * nW
    while True:
        if k is not None and depth >= k:
            stop = "k"
            break
        if depth >= k_max:
            stop = "kmax"
            break
        n_next = len(keys) * nJ * nW
        if depth >= 1:
            if max_sims is not None and sims + len(keys) * sims_per_node > max_sims:
                stop = "sims"
                break
            if n_next > MAX_LAYER:
                stop = "memory"
                break
            # serving mode only: predicted next layer + final backup (backup ~ BACKUP_COST x expansion per transition)
            if deadline_s is not None and (time.perf_counter() - t0) + rate * (
                    n_next + BACKUP_COST * (transitions + n_next)) > deadline_s:
                stop = "deadline"
                break
        t1 = time.perf_counter()
        nk, oc, rows = model.expand(keys)
        run = oc == OC_RUN
        nxt, inv = np.unique(nk[run], return_inverse=True)
        layers.append((oc, run, inv.reshape(-1)))
        depth += 1
        sims += rows
        transitions += n_next
        rate = (time.perf_counter() - t1) / max(n_next, 1)
        keys = nxt
        if track:
            seen.append(keys)
        if len(keys) == 0:
            stop = "exhausted"
            break
    Q = _backup(layers, model.p, nW)
    out = {"Q": Q[root_inv], "root_inv": root_inv, "depth": depth, "sims": sims, "transitions": transitions,
           "stop": stop, "layers": layers, "frontier": keys}
    if track:
        out["visited"] = int(len(np.unique(np.concatenate(seen))))
    return out


def reachable_count(machine, cap: int = 5_000_000) -> int:
    """|R(M)| (PREREG_V2G v0.1 C8): distinct non-terminal full states (base incl. hidden vars + in-flight queue)
    reachable from reset, by exact layered BFS over the one-tick model. Eval-runner reporting only (never called by
    a decision). Returns -1 when the count exceeds ``cap``."""
    from nagi.burst2._rt.v2g.machine import KEEP  # noqa: PLC0415

    model = ZooModel(machine)
    base = np.asarray(machine.start_states, np.int64).reshape(-1, model.cp.nv)
    q = np.full((len(base), model.d), KEEP, np.int64)
    visited = np.unique(model.keys(base, q))
    frontier = visited
    while len(frontier):
        nk, oc, _rows = model.expand(frontier)
        nxt = np.unique(nk[oc == OC_RUN])
        new = np.setdiff1d(nxt, visited, assume_unique=True)
        if len(visited) + len(new) > cap:
            return -1
        visited = np.union1d(visited, new)
        frontier = new
    return int(len(visited))


# ================================================================================ decision
def _softmax(x: np.ndarray) -> np.ndarray:
    z = np.exp(x - x.max())
    return z / z.sum()


def _hash_index(machine, state, n: int) -> int:
    def enc(o):
        if isinstance(o, dict):
            return {k: enc(v) for k, v in sorted(o.items())}
        if isinstance(o, (list, tuple)):
            return [enc(v) for v in o]
        if hasattr(o, "base"):
            return [enc(o.base), enc(o.queue)]
        return o if not isinstance(o, np.integer) else int(o)

    key = json.dumps([getattr(machine, "machine_id", ""), enc(state)], sort_keys=True, default=str)
    return int.from_bytes(hashlib.sha256(("v2g-tie|" + key).encode()).digest()[:8], "little") % n


def _core_predict(core, machine, state, history, legal):
    out = core.predict({"machine": machine, "items": [{"state": state, "history": history, "legal": legal}]})
    prior = np.asarray(out["prior"], np.float64).reshape(-1, 27)[0]
    p_opt = out.get("p_opt")
    if p_opt is not None:
        p_opt = np.asarray(p_opt, np.float64).reshape(-1, 27)[0]
    sup = out.get("supported")
    supported = True if sup is None else bool(np.asarray(sup).reshape(-1)[0])
    return prior, p_opt, out.get("value"), supported


_UNSET = object()


def search(machine, state, history=None, core=None, deadline_ms: float | None = DEFAULT_DEADLINE_MS,
           max_sims=_UNSET, k: int | None = None, k_max: int = K_MAX, tie: str = "hash", rng=None,
           tau: float = 0.9, core_value: bool = False, budget_frac: float = BUDGET_FRAC, deterministic: bool = True,
           reuse_model: bool = False, track_coverage: bool = True, belief: str = "v0",
           preimage_frac: float = PREIMAGE_FRAC) -> tuple[int, dict]:
    """LANES search -> (joint, stats{sims, depth, ms, gated, ...}). ``state`` = a full state (tuple / XState: the
    privileged path, tests and fully observed machines) or the client view dict (``machine.view``).
    Default = deterministic search (module doc): max_sims = DEFAULT_MAX_SIMS unless ``k`` is given (then no sims cap
    unless one is passed), deadline reported only. ``tie`` picks inside the exact tie set A_k (see module doc)."""
    t0 = time.perf_counter()
    c0 = time.thread_time()
    if max_sims is _UNSET:
        max_sims = DEFAULT_MAX_SIMS if k is None else None
    if getattr(machine, "kind", "zoo") != "zoo":
        return machine.search(state, history=history, core=core, deadline_ms=deadline_ms, max_sims=max_sims, k=k,
                              tie=tie, rng=rng, tau=tau, deterministic=deterministic)
    model = model_of(machine, reuse_model)
    tb = time.perf_counter()
    max_sims_cfg = max_sims
    pre_max = int(preimage_frac * max_sims) if (belief in ("v1", "v1b") and max_sims) else 0
    B, Qq, binfo = machine.roots(state, belief, pre_max)
    pre_rows = int(binfo.get("preimage_rows", 0))
    if pre_rows and max_sims is not None:  # v1: the image rows are charged to this decision's sims budget
        max_sims = max_sims - pre_rows
    belief_ms = (time.perf_counter() - tb) * 1e3
    sampled_roots = False
    if len(B) > BELIEF_SEARCH_MAX:
        sel = np.sort(np.random.default_rng(_hash_index(machine, state, 2 ** 31)).choice(len(B), BELIEF_SEARCH_MAX,
                                                                                         replace=False))
        B, Qq, sampled_roots = B[sel], Qq[sel], True
    if len(B) == 0:
        raise ValueError("empty belief: the view is inconsistent with the rulebook")
    rk = model.keys(B, Qq)
    if deterministic and max_sims is None and k is None:
        raise ValueError("deterministic search needs max_sims or k (a wall-clock deadline is not a stop rule here)")
    deadline_s = None if (deadline_ms is None or deterministic) else budget_frac * deadline_ms / 1e3
    res = deepen(model, rk, t0, deadline_s, max_sims, k, k_max, track=track_coverage)
    Q = res["Q"]
    Qbar = Q[0] if len(Q) == 1 else Q.mean(0)
    vj = model.vj
    A = [int(j) for j, x in zip(vj.tolist(), Qbar) if x >= Qbar.max() - TOL]
    gated, conf, core_ms, prior_A = False, None, 0.0, None
    choice = None
    if core is not None and len(A) > 1:
        tc = time.perf_counter()
        prior, p_opt, _value, supported = _core_predict(core, machine, state, history, [int(j) for j in vj])
        pa = _softmax(prior[A])
        if not supported:  # lane core: mz-1x with delay / hidden vars is outside its v0 contract -> gate closed
            conf = 0.0
        elif p_opt is not None:  # lane core's calibrated P(j in A*): gate on the prior's pick (agreed 2026-10-12)
            conf = float(np.nan_to_num(p_opt[A[int(np.argmax(pa))]], nan=0.0))
        else:  # renormalised prior mass inside A_k
            conf = float(pa.max())
        if conf >= tau:
            score = [(0.0, float(pa[i])) for i in range(len(A))]
            fr = res["frontier"]
            if core_value and 0 < len(fr) <= VALUE_LEAF_MAX and not machine.hidden:  # core never reads hidden vars
                qv = _leaf_q(core, machine, model, res, len(Q))
                if qv is not None:
                    pos = {int(j): i for i, j in enumerate(vj.tolist())}
                    score = [(float(qv[pos[a]]), float(pa[i])) for i, a in enumerate(A)]
            choice = A[max(range(len(A)), key=lambda i: (score[i], -i))]
            gated, prior_A = True, [float(x) for x in pa]
        core_ms = (time.perf_counter() - tc) * 1e3
    if choice is None or (tie == "sample" and gated):
        if tie == "sample":  # SDK / eval default: sample the returned distribution with the caller's stream
            if rng is None:
                raise ValueError("tie='sample' needs rng (a seeded stream: session + step, or the CRN policy stream)")
            if gated and max(prior_A) > min(prior_A):  # PREREG_V2G §3: one random(), inverse CDF over A (increasing)
                cdf = np.cumsum(np.asarray(prior_A, np.float64) / np.sum(prior_A))
                choice = A[min(int(np.searchsorted(cdf, rng.random(), side="right")), len(A) - 1)]
            else:
                choice = A[int(rng.integers(len(A)))]  # uniform: one integers(|A|) (mc-2 S_k rule)
        elif tie == "uniform":
            if rng is None:
                raise ValueError("tie='uniform' needs rng (the policy stream)")
            choice = A[int(rng.integers(len(A)))]
        elif tie == "lowest":
            choice = A[0]
        elif tie == "hash":
            choice = A[_hash_index(machine, state, len(A))]
        else:
            raise ValueError(f"unknown tie {tie!r}")
    ms = (time.perf_counter() - t0) * 1e3
    stats = {"sims": int(res["sims"]) + pre_rows, "transitions": int(res["transitions"]), "depth": int(res["depth"]),
             "lookahead": int(res["depth"]) - model.d, "ms": ms, "deterministic": bool(deterministic),
             "max_sims": max_sims_cfg, "over_deadline": bool(deadline_ms is not None and ms > deadline_ms),
             "cpu_ms": (time.thread_time() - c0) * 1e3, "gated": gated,
             "core_conf": conf, "core_prior_A": prior_A, "core_ms": core_ms, "belief_ms": belief_ms, "visited": res.get("visited"), "exhausted": res["stop"] == "exhausted",
             "belief_mode": belief, "preimage_rows": pre_rows, "preimage": binfo.get("preimage"),
             "n_acc": len(A), "acceptable": A, "stop": res["stop"], "belief": int(binfo.get("belief", len(B))),
             "belief_exact": bool(binfo.get("exact", True)), "belief_sampled": bool(binfo.get("sampled", False))
             or sampled_roots, "qbar": [float(x) for x in Qbar]}
    return int(choice), stats


def _leaf_q(core, machine, model: ZooModel, res: dict, n_roots: int):
    """Q̄ with core values at the deepest frontier (V_leaf = 49 v − 200 (1 − v)); None if the core gives no value."""
    from nagi.burst2._rt.v2g.machine import XState  # noqa: PLC0415

    fr = res["frontier"]
    base = model.decode_base(fr // model.M)
    items = []
    for i, b in enumerate(base.tolist()):
        if model.d:
            code, q = int(fr[i] % model.M), []
            for _ in range(model.d):
                q.append(int(model.vj[code % model.nJ]))
                code //= model.nJ
            st = XState(tuple(b), tuple(reversed(q)))
        elif machine.px is not None:
            st = XState(tuple(b), ())
        else:
            st = tuple(b)
        items.append({"state": st, "history": None, "legal": [int(j) for j in model.vj]})
    out = core.predict({"machine": machine, "items": items})
    if out.get("v_reward") is not None:  # lane core: V* in reward units (same units as Q_k)
        leaf_v = np.nan_to_num(np.asarray(out["v_reward"], np.float64).reshape(-1), nan=0.0)
    elif out.get("value") is not None:
        leaf_v = np.asarray([leaf_value_from_success(v) for v in np.asarray(out["value"]).reshape(-1)], np.float64)
    else:
        return None
    Qv = _backup(res["layers"], model.p, model.nW, leaf_v)[res["root_inv"]]
    return Qv.mean(0) if len(Qv) > 1 else Qv[0]


class UniformCore:
    """Stub core for tests (uniform prior, value 0.5, conf = 1/len(legal)): the gate never opens at tau > 1/|A|."""

    def predict(self, batch: dict) -> dict:
        items = batch["items"]
        prior = np.full((len(items), 27), -1e9, np.float32)
        for i, it in enumerate(items):
            prior[i, it["legal"]] = 0.0
        return {"prior": prior, "value": np.full(len(items), 0.5, np.float32),
                "conf": np.asarray([1.0 / len(it["legal"]) for it in items], np.float32)}


def leaf_value_from_success(v) -> float:
    """Core value (estimated optimal success probability) -> reward scale (used only for ordering inside A_k)."""
    v = min(max(float(v), 0.0), 1.0)
    return R_SUCC * v + R_CRASH * (1.0 - v) if math.isfinite(v) else 0.0
