"""Generic latency-aware joint-Q evaluator and the label planner (docs/burst_v2/LABELS.md §2-3).

A game adapter (burst_v2.booster.BoosterAdapter, burst_v2.rr.RRAdapter) supplies the world primitives:

    SEED_GAME, GAME_ID, VERSION, CONTROLS (declared order), OPTIONS {control: options}, TEMPERATURE (K3 points),
    MAX_TICKS (rollout cap in ticks), binding (arena.v3.games.Binding: hold rules + safe defaults)
    worlds(state, key, n, cheat) -> [world]      n samples of the hidden exogenous future given the served
                                                 observation of `state` (cheat=True: [the true world])
    step(world, state, acts) -> state            one 250 ms decision tick of seat 0 in `world`
    value(world, s0, state) -> float | None      terminal value of the Q rollout (None = keep rolling)
    horizon_value(world, s0, state) -> float     value when the rollout reaches MAX_TICKS
    continuation(world, state, key) -> policy    fresh continuation policy; policy.decide(state) -> {control: option},
                                                 policy.clone() -> independent copy (memory included)

Q_b(s_k, p_log, d, a), d >= 1 (runner semantics, arena.v3.runner._controls):
    tick k:            p_log                    (already applied when the request is made)
    ticks k+1..k+d-1:  the hold rules of p_log  (persistent -> same, one_shot -> the safe default)
    tick k+d:          a  (the reply lands); at the same boundary the next request is submitted on s_{k+d}
                       (the continuation's first reply: it observes s_{k+d}, which a has not touched yet, so it
                       is shared by every a) and lands d2 ticks later; meanwhile the hold rules of a apply
    later:             the continuation, every reply through the emulated latency (delays: the measured first-order
                       chain, one common random sequence per (row, world, d) for every a = common random numbers)
d = 0 is the lag-free diagnostic: a at tick k and a lockstep continuation (delay 0).
Adapters with CONT_LOCKSTEP = True use a lockstep continuation after a (a applies for one tick, then the continuation
decides on every state and acts at once), the bg3_planner rollout design: the labelled reply's timing (p_log, d, hold
rules) stays exact, the continuation is optimistic about its own later latency. Under the single-stream profile
(P-hat(1) = 0.85) a is held one tick in 85% of cases anyway.
"""
from __future__ import annotations

import hashlib
import math
import random

from nagi.burst2._rt.burst_v2 import labels as L
from nagi.burst2._rt.burst_v2.latency import held_after


def _rng(key: str) -> random.Random:
    return random.Random(hashlib.sha256(f"bv2-q|{key}".encode()).hexdigest())


def delay_seq(key: str, prev: int, markov: dict | None, p_hat: dict | None = None, n: int = 400) -> list[int]:
    """[prev] + the continuation's reply delays: i.i.d. from p_hat (markov None) or the first-order chain from prev.
    prev 0 -> lockstep (all 0)."""
    if prev == 0:
        return [0] * n
    r, out, d = _rng(key), [prev], prev
    for _ in range(n - 1):
        dist = markov[d] if markov is not None else p_hat
        u, acc, nd = r.random(), 0.0, None
        for dd, p in sorted(dist.items()):
            acc += p
            if u < acc:
                nd = dd
                break
        d = nd if nd is not None else max(dist)
        out.append(d)
    return out


def _held(ad, acts: dict) -> dict:
    return held_after(ad.binding, acts)


def rollout(ad, world, s0, s, a: dict, cont, first_reply: dict | None, delays: list[int], t_used: int) -> float:
    """Value of applying `a` at state s (tick k+d) then the continuation. delays = delay_seq(...): delays[0] = d,
    delays[1] = the delay of first_reply (the continuation's reply submitted on s), then later replies."""
    acts = dict(a)
    lock = delays[0] == 0
    pending = None if lock else (first_reply, delays[1])
    di, t = 2, 0
    cont_lock = getattr(ad, "CONT_LOCKSTEP", False)
    while True:
        s = ad.step(world, s, acts)
        t += 1
        lock = lock or cont_lock
        v = ad.value(world, s0, s)
        if v is not None:
            return v
        if t + t_used >= ad.MAX_TICKS:
            return ad.horizon_value(world, s0, s)
        if lock:
            acts = cont.decide(s)
            continue
        if pending is not None and t >= pending[1]:
            acts = dict(pending[0])
            pending = None
        else:
            acts = _held(ad, acts)
        if pending is None:
            pending = (cont.decide(s), t + delays[di])
            di += 1


def q_world(ad, world, s0, p_log: dict | None, d: int, joint_list: list[tuple], key: str, markov: dict | None,
            p_hat: dict | None = None, cont_factory=None) -> dict:
    """{joint: Q_b} for one world and one first-reply delay d."""
    s, t_used = s0, 0
    if d > 0:
        acts = dict(p_log)
        for i in range(d):
            s = ad.step(world, s, acts)
            t_used += 1
            v = ad.value(world, s0, s)
            if v is not None:
                return {"self": v} if joint_list == "self" else {a: v for a in joint_list}
            acts = _held(ad, acts)
    delays = delay_seq(f"{key}|d{d}", d, markov, p_hat)
    cont = (cont_factory or ad.continuation)(world, s, key)
    first = None if (d == 0 or getattr(ad, "CONT_LOCKSTEP", False)) else cont.decide(s)
    if joint_list == "self":             # the continuation's own action (hop-parameter shooting)
        return {"self": rollout(ad, world, s0, s, first if first is not None else cont.decide(s), cont.clone(), first,
                                delays, t_used)}
    out, memo = {}, {}
    rep = getattr(ad, "representative", None)
    for a in joint_list:
        r = rep(s, a) if rep is not None else a      # exact equivalence classes (identical physics from s)
        if r not in memo:
            memo[r] = rollout(ad, world, s0, s, dict(zip(ad.CONTROLS, r)), cont.clone(), first, delays, t_used)
        out[a] = memo[r]
    return out


def q_table(ad, state, p_log: dict | None, key: str, n_worlds: int, p_hat: dict, delays=None, cheat: bool = False,
            markov: dict | None = None, joint_list: list[tuple] | None = None, worlds=None, cont_factory=None) -> dict:
    """{d: [ {joint: Q_b} per world ]} for d in `delays` (default: the support of p_hat)."""
    delays = tuple(sorted(p_hat)) if delays is None else tuple(delays)
    jl = joint_list or L.joints(ad.CONTROLS, ad.OPTIONS)
    ws = worlds if worlds is not None else ad.worlds(state, key, n_worlds, cheat)
    minor = getattr(ad, "MINOR_DELAY_WORLDS", None)     # worlds for a delay of P-hat < 0.5 (cost; unbiased MC)
    return {d: [q_world(ad, w, state, p_log, d, jl, f"{key}|w{i}", markov, p_hat, cont_factory)
                for i, w in enumerate(ws if (minor is None or p_hat.get(d, 1.0) >= 0.5) else ws[:minor])]
            for d in delays}


class LabelPlanner:
    """The label policy: at each request, Q-bar over the adapter's worlds (obs-limited, or the true world when cheat)
    and the marginal P-hat, answer = the canonical joint a*. Returns the full label record for the generator."""

    def __init__(self, ad, p_hat: dict, n_worlds: int, cheat: bool = False, markov: dict | None = None,
                 key: str = ""):
        self.ad, self.p_hat, self.B, self.cheat, self.markov, self.key = ad, dict(p_hat), n_worlds, cheat, markov, key
        self.order = L.joints(ad.CONTROLS, ad.OPTIONS)

    def label(self, state, p_log: dict, rkey: str) -> dict:
        key = f"{self.key}|{rkey}"
        ws = self.ad.worlds(state, key, self.B, self.cheat)
        cf, info = self.ad.prepare(ws, state, p_log, key) if hasattr(self.ad, "prepare") else (None, {})
        qd = q_table(self.ad, state, p_log, key, self.B, self.p_hat, cheat=self.cheat, markov=self.markov,
                     worlds=ws, cont_factory=cf)
        q = L.qbar(qd, self.p_hat)
        ref = getattr(self.ad, "REFINE", None)
        if ref and not self.cheat:
            q, qd = self._refine(state, p_log, key, ws, cf, q, qd, *ref)
        base = None
        if hasattr(self.ad, "base_action"):
            base = tuple(self.ad.base_action(ws, state, cf, key)[c] for c in self.ad.CONTROLS)
        tol = getattr(self.ad, "TIE_TOL", L.TOL) if not self.cheat else L.TOL
        a = L.canonical_base(q, self.order, base, tol)
        tabs = L.slot_tables(self.ad.CONTROLS, self.ad.OPTIONS, q, self.ad.TEMPERATURE, a, tol)
        return {"q": q, "q_by_d": qd, "tables": tabs, "joint": a, "answers": dict(zip(self.ad.CONTROLS, a)),
                "worlds": ws, "cont_factory": cf, "prep": info, "base": base, "tie_tol": tol}


    def _refine(self, state, p_log, key, ws, cf, q, qd, top_n: int, extra: int):
        """Adaptive sampling: the top_n joints of the first-pass Q-bar (plus the base joint) are re-estimated on
        `extra` additional worlds for the MAJOR delay (P-hat >= 0.5); every joint's Q-bar stays an unbiased average
        over its own worlds (refined joints over B + extra, the others over B). Stabilises the argmax at +~25% cost."""
        major = [d for d, p in self.p_hat.items() if p >= 0.5]
        ranked = sorted(q, key=lambda a: -q[a])[:top_n]
        ws2 = self.ad.worlds(state, f"{key}|refine", extra, False)
        rep = getattr(self.ad, "representative", None)
        sel = list(dict.fromkeys(ranked))
        if rep is not None:                  # whole equivalence classes (identical Q by construction)
            reps = {rep(state, a) for a in sel}
            sel += [a for a in q if a not in sel and rep(state, a) in reps]
        for d in major:
            extra_q = [q_world(self.ad, w, state, p_log, d, sel, f"{key}|refine|w{i}", self.markov, self.p_hat, cf)
                       for i, w in enumerate(ws2)]
            for a in sel:
                n0 = len(qd[d])
                tot = math.fsum(w[a] for w in qd[d]) + math.fsum(e[a] for e in extra_q)
                mean = tot / (n0 + extra)
                old = math.fsum(w[a] for w in qd[d]) / n0
                q[a] += self.p_hat[d] * (mean - old)
        return q, qd


def entropy_norm(t: list[float]) -> float:
    return -sum(p * math.log(p) for p in t if p > 0) / math.log(len(t))
