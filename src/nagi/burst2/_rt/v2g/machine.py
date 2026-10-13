"""The LANES ``Machine`` API (docs/burst_v2_general/LANES.md) over Machine Zoo ``mz-1`` / ``mz-1x`` programs.

Wraps ``machine_zoo.{dsl, interp, tokens}`` (mz-1 SPEC) and ``bv2n.zoo_new.xdsl`` (ZOO_NEW_SPEC §1-§2) without
forking them: every tick is ``machine_zoo.interp`` (scalar reference) or ``machine_zoo.tokens.Compiled.exec_tick``
(vectorized, tested equal to the reference), the mz-1x queue semantics are those of ``bv2n.zoo_new.env.XEnv``.

    m = Machine.from_rules_text(text)          # exact reader (v2g.reader): mz-1 rulebook, mz-1x rulebook (+ extension)
    m = Machine.from_program(program_or_px)    # structured path
    s = m.initial(seed_or_rng)                 # mz-1: tuple of var values; mz-1x: XState(base, queue)
    s2, terminal, success = m.step(s, joint, rng)            # one rng.random() per tick (mz-1 CRN)
    m.step_full(s, joint, u) -> (s2, reward, done, outcome)   m.step_dist(s, joint) -> [(p, s2, reward, outcome)]
    m.legal(s) -> [joint, ...]                 # increasing joint index; joint = o0*9 + o1*3 + o2, KEEP = 13
    m.view(s, history) -> dict                 # what the client sees (mz-1: the state; mz-1x: obs window + decided)
    m.delay, m.hidden, m.window                # 0 / [] / 1 for mz-1
    m.belief(view) -> (base states int64[n, nv], queues int64[n, d], exact: bool)   # hidden vars (search.py)

States. mz-1: the tuple of all var values (program order). mz-1x: ``XState(base, queue)``, the base mz-1 state and the
in-flight decided joints, oldest first (len = delay); this is ZOO_NEW_SPEC §3's augmented state z. The client never
sees an XState: it sees ``view(state, history)`` = ``{"obs": H displayed observations (None = before start),
"dec": K = max(H-1, d) decided joints (KEEP for pre-start in-flight, None before that)}`` (= ``xteacher.XView``).
``history`` = list of (previous state, decided joint) pairs, oldest first, since reset (only the last max(H, K) are
read). ``Episode`` keeps that bookkeeping and equals ``XEnv`` decision for decision (test).

Belief (hidden vars; ZOO_NEW_SPEC §4 reads B(x) from the full reachable set S_x, which needs an exhaustive enumeration
that the north-star compute rule forbids at decision time). ``belief(view)`` computes, from the rulebook and the view
only, the set of augmented states consistent with the observed window:
  * the episode started inside the window (a PAD observation is shown): start states (rulebook start sets) whose
    displayed vars match, KEEP in flight, filtered forward through every shown tick -> EXACTLY B(x) (exact=True);
  * else: every assignment of the hidden vars in their declared ranges x every in-flight joint not shown in the window,
    restricted to states that are a start state (KEEP in flight) or satisfy neither a crash condition nor the goal
    (every state reached by a running tick does), then filtered forward through the shown ticks (decided joints,
    every rand outcome with p > 0, running, displayed vars equal the next observation). This is a SUPERSET of B(x):
    reachability from reset is not checked (exact=False). When the candidate box exceeds ``BELIEF_ENUM_MAX`` a
    deterministic uniform sample (seeded by the view) of that size is filtered instead (``stats['sampled']``).
"""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass

import numpy as np

from nagi.burst2._rt.machine_zoo import dsl, interp
from nagi.burst2._rt.machine_zoo import tokens as TK

N_JOINT = 27
KEEP = 13
BELIEF_ENUM_MAX = 200_000  # candidate augmented states enumerated exactly; above: deterministic sample of this size
OC_RUN, OC_SUCC, OC_CRASH = 0, 1, 2


@dataclass(frozen=True)
class XState:
    """mz-1x environment state = augmented state z of ZOO_NEW_SPEC §3."""

    base: tuple
    queue: tuple


class Machine:
    """One mz-1 or mz-1x program behind the LANES Machine API (see module doc)."""

    kind = "zoo"

    def __init__(self, spec: dict):
        if spec.get("dsl") == "mz-1x":
            from nagi.burst2._rt.bv2n.zoo_new import xdsl  # noqa: PLC0415

            xdsl.validate(spec)
            px = xdsl.canonicalize(spec)
            if xdsl.is_plain(px):
                spec, px = xdsl.to_plain(px), None
        else:
            px = None
        base = dsl.canonicalize(px["base"] if px is not None else spec)
        dsl.validate(base)
        self.program = base  # canonical mz-1 base program
        self.px = px  # canonical mz-1x program, or None (plain mz-1)
        self.dsl = "mz-1x" if px is not None else "mz-1"
        self.delay = px["delay"] if px is not None else 0
        self.hidden = list(px["hidden"]) if px is not None else []
        self.window = px["window"] if px is not None else 1
        self.K = max(self.window - 1, self.delay)
        if px is not None:
            from nagi.burst2._rt.bv2n.zoo_new import xdsl  # noqa: PLC0415

            self.machine_id, self.signature = xdsl.machine_id(px), xdsl.signature(px)
        else:
            self.machine_id, self.signature = dsl.machine_id(base), dsl.signature(base)
        self.prog = interp.compile_program(base)
        self.var_names = list(self.prog.var_names)
        self.ctl_names = list(self.prog.ctl_names)
        hid = set(self.hidden)
        self.disp_cols = [i for i, n in enumerate(self.var_names) if n not in hid]
        self.hid_cols = [i for i, n in enumerate(self.var_names) if n in hid]
        self.valid = list(self.prog.valid_joints)
        self.start_states = list(self.prog.start)
        self._cp = None

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_program(cls, spec: dict) -> Machine:
        return cls(spec)

    @classmethod
    def from_rules_text(cls, text: str) -> Machine:
        from nagi.burst2._rt.v2g import reader  # noqa: PLC0415

        return reader.read_rules(text)

    @property
    def cp(self) -> TK.Compiled:
        """Vectorized compiled program (lazy; per-machine, built inside the first decision's budget)."""
        if self._cp is None:
            self._cp = TK.Compiled(self.program)
        return self._cp

    @property
    def spec(self) -> dict:
        """The canonical program this machine was built from (mz-1x dict, or the mz-1 program)."""
        return self.px if self.px is not None else self.program

    def rules_text(self) -> str:
        """The served rulebook text (mz-1: dsl.render; mz-1x: xdsl.render_rulebook)."""
        if self.px is None:
            return dsl.render(self.program)
        from nagi.burst2._rt.bv2n.zoo_new import xdsl  # noqa: PLC0415

        return xdsl.render_rulebook(self.px)

    # ------------------------------------------------------------------ environment
    def initial(self, seed) -> tuple | XState:
        """mz-1 SPEC §3 reset: start_set[rng.integers(len(start_set))]; ``seed`` = int or np.random.Generator."""
        rng = seed if isinstance(seed, np.random.Generator) else np.random.default_rng(seed)
        s = tuple(self.start_states[int(rng.integers(len(self.start_states)))])
        return XState(s, (KEEP,) * self.delay) if self.px is not None else s

    def legal(self, state=None) -> list[int]:
        return list(self.valid)

    def _split(self, state) -> tuple[tuple, tuple]:
        if isinstance(state, XState):
            return tuple(state.base), tuple(state.queue)
        if self.delay:
            raise ValueError("an mz-1x machine with delay needs an XState (base, queue)")
        return tuple(state), ()

    def _join(self, base: tuple, queue: tuple):
        return XState(tuple(base), tuple(queue)) if self.px is not None else tuple(base)

    def step_full(self, state, joint: int, u: float) -> tuple:
        """One tick given the uniform draw u -> (next state, reward, done, outcome). The DECIDED joint must be valid;
        the APPLIED joint is the oldest in-flight one when delay > 0 (ZOO_NEW_SPEC §2)."""
        base, q = self._split(state)
        interp.commands(self.program, int(joint))  # decided joint valid even while it waits in the queue
        applied = q[0] if self.delay else int(joint)
        nq = (q[1:] + (int(joint),)) if self.delay else ()
        nxt, r, done, oc = interp.step(self.program, base, applied, u)
        return self._join(nxt, nq), r, done, oc

    def step(self, state, joint: int, rng=None, u: float | None = None) -> tuple:
        """LANES step -> (next state, terminal, success). Exactly one ``rng.random()`` per tick when u is None."""
        if u is None:
            if rng is None:
                if self.prog.has_rand:
                    raise ValueError("this machine has a random input: pass rng or u")
                u = 0.0
            else:
                u = rng.random()
        s2, _r, done, oc = self.step_full(state, joint, u)
        return s2, done, oc == interp.SUCCESS

    def step_dist(self, state, joint: int) -> list[tuple]:
        """[(prob, next state, reward, outcome)] per rand outcome in listed order (exact chance node)."""
        base, q = self._split(state)
        interp.commands(self.program, int(joint))
        applied = q[0] if self.delay else int(joint)
        nq = (q[1:] + (int(joint),)) if self.delay else ()
        return [(p, self._join(nxt, nq), r, oc) for p, nxt, r, oc in interp.step_dist(self.program, base, applied)]

    # ------------------------------------------------------------------ client view
    def project(self, base) -> tuple:
        return tuple(int(base[c]) for c in self.disp_cols)

    def view(self, state, history=None) -> dict:
        """Client view. mz-1: {"kind", "state", "vars"}. mz-1x: {"kind", "obs", "dec"} (= XView), built from the
        current state and ``history`` = [(previous state, decided joint), ...] oldest first since reset."""
        if self.px is None:
            s = tuple(int(x) for x in state)
            return {"kind": "mz-1", "state": s, "vars": dict(zip(self.var_names, s))}
        history = list(history or [])
        H, K, d = self.window, self.K, self.delay
        past = [self.project(self._split(s)[0]) for s, _j in history[-(H - 1):]] if H > 1 else []
        obs = [None] * (H - 1 - len(past)) + past + [self.project(self._split(state)[0])]
        decs = [int(j) for _s, j in history[-K:]] if K else []
        n_pre = K - len(decs)  # pre-start entries: KEEP when in flight (age <= d), else None
        # pre-start entry i has tick index len(decs) - (K - i) < 0; it is in flight at reset (KEEP) iff that index >= -d
        pre = [KEEP if (K - i) - len(decs) <= d else None for i in range(n_pre)]
        return {"kind": "mz-1x", "obs": tuple(obs), "dec": tuple(pre + decs)}

    def xview(self, view: dict):
        from nagi.burst2._rt.bv2n.zoo_new.xteacher import XView  # noqa: PLC0415

        return XView(tuple(None if o is None else tuple(o) for o in view["obs"]), tuple(view["dec"]))

    def request_text(self, view: dict, order=None) -> str:
        """Served request bytes for this view (mz-1: bv2n.zoo.render.render_request; mz-1x: render_hook.request)."""
        if self.px is None:
            from nagi.burst2._rt.bv2n.zoo import render as R  # noqa: PLC0415

            return R.render_request(self.program, tuple(view["state"]), order)
        from nagi.burst2._rt.bv2n.zoo_new import render_hook as RH  # noqa: PLC0415

        return RH.request(self.px, self.xview(view), order=order)

    def episode(self, rng_reset) -> Episode:
        return Episode(self, rng_reset)

    # ------------------------------------------------------------------ belief (see module doc)
    def roots(self, state_or_view, belief_mode: str = "v0", preimage_max: int = 0) -> tuple[np.ndarray, np.ndarray,
                                                                                               dict]:
        """Search roots for a decision: (base int64[n, nv], queue int64[n, d], info). A full state (tuple / XState)
        gives one root; a view gives the belief roots (exact when nothing is hidden)."""
        if isinstance(state_or_view, XState) or not isinstance(state_or_view, dict):
            b, q = self._split(state_or_view)
            return np.asarray([b], np.int64), np.asarray([q], np.int64).reshape(1, self.delay), {"belief": 1,
                                                                                                "exact": True}
        v = state_or_view
        if v.get("kind") == "mz-1" or "state" in v:
            return self.roots(tuple(v["state"]))
        if not self.hidden:
            base = tuple(v["obs"][-1])
            q = tuple(v["dec"][len(v["dec"]) - self.delay:]) if self.delay else ()
            return self.roots(XState(base, q))
        B, Q, info = self.belief(v, belief_mode, preimage_max)
        return B, Q, info

    def belief(self, view: dict, mode: str = "v0", preimage_max: int = 0) -> tuple[np.ndarray, np.ndarray, dict]:
        """mode "v0": module doc. mode "v1" (search config v1, lanes/runtime.md §5b): in the non-exact branch the
        window-start candidates must also be a start state (KEEP in flight) or in the one-tick image of the full
        declared box (any valid applied joint, chance outcome with p > 0, running tick), computed when its exec_tick
        rows <= ``preimage_max`` (else v0); ``info["preimage_rows"]`` reports the rows used."""
        H, K, d = self.window, self.K, self.delay
        obs, dec = list(view["obs"]), list(view["dec"])
        if len(obs) != H or len(dec) != K:
            raise ValueError(f"view needs {H} obs and {K} dec entries")
        cp = self.cp
        m = next(k for k in range(H) if obs[k] is not None)
        info = {"exact": m > 0, "sampled": False}
        disp = np.asarray(self.disp_cols, np.int64)
        if m > 0:
            S = np.asarray([s for s in self.start_states if self.project(s) == tuple(obs[m])], np.int64)
            S = np.unique(S.reshape(-1, cp.nv), axis=0)
            Q = np.full((len(S), d), KEEP, np.int64)
        else:
            j0 = K - H + 1  # dec index of the window's first tick
            qopts = []
            for k in range(d):
                jd = j0 - d + k
                qopts.append([int(dec[jd])] if jd >= 0 and dec[jd] is not None else list(self.valid))
            hid_ranges = [range(int(cp.lo[c]), int(cp.hi[c]) + 1) for c in self.hid_cols]
            n_box = int(np.prod([len(r) for r in hid_ranges] + [len(o) for o in qopts]))
            if n_box <= BELIEF_ENUM_MAX:
                combos = np.asarray(list(itertools.product(*hid_ranges, *qopts)), np.int64).reshape(n_box, -1)
            else:
                info["sampled"] = True
                seed = int.from_bytes(hashlib.sha256(json.dumps(
                    [self.machine_id, [None if o is None else list(o) for o in obs], dec]).encode()).digest()[:8],
                    "little")
                rng = np.random.default_rng(seed)
                cols = [np.asarray(list(r), np.int64)[rng.integers(len(r), size=BELIEF_ENUM_MAX)] for r in hid_ranges]
                cols += [np.asarray(o, np.int64)[rng.integers(len(o), size=BELIEF_ENUM_MAX)] for o in qopts]
                combos = np.unique(np.stack(cols, 1), axis=0)
            n = len(combos)
            S = np.zeros((n, cp.nv), np.int64)
            S[:, disp] = np.asarray(obs[0], np.int64)
            nh = len(self.hid_cols)
            if nh:
                S[:, np.asarray(self.hid_cols, np.int64)] = combos[:, :nh]
            Q = combos[:, nh:nh + d].astype(np.int64).reshape(n, d)
            # a state reached by a running tick satisfies neither a crash condition nor the goal (var-only PREDs)
            ok = ~cp.goal.eval(S, None, None)
            for p in cp.crash:
                ok &= ~p.eval(S, None, None)
            starts = {tuple(s) for s in self.start_states}
            if d:
                keepq = (Q == KEEP).all(1)
            else:
                keepq = np.ones(n, bool)
            is_start = np.fromiter((tuple(r) in starts for r in S.tolist()), bool, n) & keepq
            sel = ok | is_start
            if mode in ("v1", "v1b"):
                img = self._image_mask(S, tuple(obs[0]), preimage_max, info, prune=mode == "v1b")
                if img is not None:
                    sel = is_start | (ok & img)
            S, Q = S[sel], Q[sel]
        for s in range(m, H - 1):
            a = dec[K - H + 1 + s]
            S, Q = self._filter_step(S, Q, int(a), tuple(obs[s + 1]))
        info["belief"] = len(S)
        return S, Q, info

    def _pred_values(self, obs0: tuple) -> list[np.ndarray]:
        """Search config v1b (lanes/runtime.md §5c): a SOUND superset of each var's possible predecessor values, from
        the rulebook and the displayed values ``obs0`` of the post state (module tests: pruned image == full-box
        image). Incremental var (exactly one rule assigns it, of the form v := v + e, e not reading v): {post - e} for
        e in [e_min, e_max], plus post if the rule is conditional, plus the values clamping can map onto a range bound;
        a var first touched by an unconditional reset v := e (e not reading v): one representative (its pre value
        cannot reach the post state); anything else: the full declared range."""
        from nagi.burst2._rt.machine_zoo import dsl as D  # noqa: PLC0415

        prog = self.program
        vars_ = prog["vars"]
        rng = {v["name"]: (int(v["lo"]), int(v["hi"])) for v in vars_}
        cmd = {c["name"]: [o for o in c["opts"] if o is not None] for c in prog["controls"]}
        wv = [int(x[0]) for x in (prog.get("rand") or [])] or [0]

        def atom_range(a):
            kind, name = D.parse_atom(a)
            if kind == D.K_VAR:
                return rng[name]
            if kind == D.K_ABS:
                lo, hi = rng[name]
                return (0 if lo <= 0 <= hi else min(abs(lo), abs(hi))), max(abs(lo), abs(hi))
            if kind == D.K_SGN:
                lo, hi = rng[name]
                return int(np.sign(lo)), int(np.sign(hi))
            if kind == D.K_CMD:
                return min(cmd[name]), max(cmd[name])
            if kind == D.K_ABSCMD:
                return min(abs(o) for o in cmd[name]), max(abs(o) for o in cmd[name])
            return min(wv), max(wv)

        def reads(obj) -> set:
            out = set()
            if isinstance(obj, dict) and "t" in obj:
                for _c, a in obj["t"]:
                    kind, name = D.parse_atom(a)
                    if kind in (D.K_VAR, D.K_ABS, D.K_SGN):
                        out.add(name)
            elif isinstance(obj, dict):
                for items in obj.values():
                    for it in items:
                        out |= reads(it)
            elif isinstance(obj, (list, tuple)) and obj and isinstance(obj[0], dict):
                out |= reads(obj[0])
            return out

        rules = prog["rules"]
        disp = {self.var_names[c]: obs0[i] for i, c in enumerate(self.disp_cols)}
        out = []
        for v in vars_:
            name, (lo, hi) = v["name"], rng[v["name"]]
            full = np.arange(lo, hi + 1, dtype=np.int64)
            sets = [i for i, r in enumerate(rules) if r["set"] == name]
            touched = [i for i, r in enumerate(rules) if r["set"] == name or name in reads(r.get("to")) or
                       name in reads(r.get("if", {}))]
            if sets and touched and touched[0] == sets[0] and "if" not in rules[sets[0]] and \
                    name not in reads(rules[sets[0]]["to"]):
                out.append(np.asarray([lo], np.int64))  # reset before any use: pre value is irrelevant
                continue
            if len(sets) == 1 and name in disp:
                r = rules[sets[0]]
                terms = [(c, a) for c, a in r["to"]["t"]]
                self_terms = [c for c, a in terms if a == name]
                others = [(c, a) for c, a in terms if a != name]
                if self_terms == [1] and all(name not in reads({"t": [[c, a]], "k": 0}) for c, a in others):
                    e_lo = e_hi = int(r["to"]["k"])
                    for c, a in others:
                        alo, ahi = atom_range(a)
                        e_lo += min(c * alo, c * ahi)
                        e_hi += max(c * alo, c * ahi)
                    post = int(disp[name])
                    vals = set(range(post - e_hi, post - e_lo + 1))
                    if "if" in r:
                        vals.add(post)
                    if post == hi:
                        vals |= set(range(hi - e_hi, hi + 1))
                    if post == lo:
                        vals |= set(range(lo, lo - e_lo + 1))
                    vals = sorted(x for x in vals if lo <= x <= hi)
                    out.append(np.asarray(vals, np.int64))
                    continue
            out.append(full)
        return out

    def _image_mask(self, S: np.ndarray, obs0: tuple, preimage_max: int, info: dict, prune: bool = False):
        """Bool mask over candidate base states S: in the one-tick image of the declared box (v1), or of the soundly
        pruned predecessor box (v1b). None when box x valid joints x outcomes exceeds ``preimage_max`` rows (caller
        keeps v0)."""
        cp = self.cp
        width = (cp.hi - cp.lo + 1).astype(np.int64)
        radix = np.ones(cp.nv, np.int64)
        for i in range(1, cp.nv):
            radix[i] = radix[i - 1] * width[i - 1]
        vals = self._pred_values(obs0) if prune else [np.arange(cp.lo[i], cp.hi[i] + 1, dtype=np.int64)
                                                       for i in range(cp.nv)]
        box = int(np.prod([float(len(x)) for x in vals]))
        pw = np.asarray(cp.w_p, np.float64)
        wsel = np.flatnonzero(pw > 0)
        nj = len(self.valid)
        rows = box * nj * len(wsel)
        if rows > preimage_max:
            info["preimage_rows"] = 0
            info["preimage"] = "skipped"
            return None
        X = np.stack(np.meshgrid(*vals, indexing="ij"), -1).reshape(box, cp.nv).astype(np.int64)
        X = np.repeat(X, nj * len(wsel), axis=0)
        J = np.tile(np.repeat(np.asarray(self.valid, np.int64), len(wsel)), box)
        W = np.tile(cp.w_vals[wsel], box * nj)
        Xn, crash, succ, _ = cp.exec_tick(X, cp.cmd[J, :cp.nc], W)
        keep = ~crash & ~succ & (Xn[:, self.disp_cols] == np.asarray(obs0, np.int64)).all(1)
        img = Xn[keep]
        info["preimage_rows"] = rows
        info["preimage"] = "applied"
        if not len(img):
            return np.zeros(len(S), bool)
        kimg = np.unique(((img - cp.lo) * radix).sum(1))
        ks = ((S - cp.lo) * radix).sum(1)
        return np.isin(ks, kimg)

    def _filter_step(self, S: np.ndarray, Q: np.ndarray, a: int, next_obs: tuple):
        """One shown tick of the forward filter: decided joint a, every rand outcome with p > 0, keep running
        successors whose displayed vars equal next_obs. Returns unique (S', Q')."""
        cp, d = self.cp, self.delay
        n = len(S)
        if n == 0:
            return S, Q
        applied = Q[:, 0] if d else np.full(n, a, np.int64)
        pw = np.asarray(cp.w_p, np.float64)
        wsel = np.flatnonzero(pw > 0)
        X = np.repeat(S, len(wsel), axis=0)
        C = cp.cmd[np.repeat(applied, len(wsel)), :cp.nc]
        W = np.tile(cp.w_vals[wsel], n)
        Xn, crash, succ, _ = cp.exec_tick(X, C, W)
        keep = ~crash & ~succ & (Xn[:, self.disp_cols] == np.asarray(next_obs, np.int64)).all(1)
        Qn = np.repeat(np.concatenate([Q[:, 1:], np.full((n, 1), a, np.int64)], 1) if d else Q, len(wsel), axis=0)
        Z = np.concatenate([Xn[keep], Qn[keep]], 1)
        if len(Z) == 0:
            return Xn[:0], Qn[:0]
        Z = np.unique(Z, axis=0)
        return Z[:, :cp.nv], Z[:, cp.nv:]


class Episode:
    """Live runner over the Machine API with the client's bookkeeping (state, history, view). Uses the same random
    draws as ``bv2n.zoo_new.env.XEnv`` / ``machine_zoo.evaluate.run_policy``: one rng.integers at reset, one
    rng.random() per tick."""

    def __init__(self, machine: Machine, rng_reset):
        self.m = machine
        self.state = machine.initial(rng_reset)
        self.history: list = []
        self.t = 0
        self.done = False
        self.outcome = "running"
        self.ret = 0.0

    def view(self) -> dict:
        return self.m.view(self.state, self.history)

    def step(self, joint: int, rng) -> tuple:
        s2, r, done, oc = self.m.step_full(self.state, int(joint), rng.random())
        self.history.append((self.state, int(joint)))
        if len(self.history) > 8:
            self.history = self.history[-8:]
        self.state = s2
        self.t += 1
        self.ret += float(r)
        self.done, self.outcome = done, oc
        return self.view(), r, done, oc
