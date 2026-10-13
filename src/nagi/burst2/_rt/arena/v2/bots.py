"""Arena Live v2 scripted bot ladder (CPU, deterministic given (seed, seat)). PLAN §3.

Bots are opponents / references, not contestants: they read the FULL engine state (privileged), which the runner
hands them via `see(game, state)` right before each decision point. Every stochastic choice uses
random.Random(f"{bot_id}|{seed}|{seat}") advanced once per decision, so a round is a pure function of the seed and
of the focal agent's replies.

Relation to scripts/arena_live_dryrun.py (the v1 text-parsing video bots): lc2 / st2 / rw3 are the same policy
families (flood-fill, cost-minimising stack, PD rescue controller) re-implemented on the engine state, without
slot jitter or simulated latency, so they are exact and deterministic. Random floors (normalisation 0):
rwR_random, lcR_random (uniform over all 6 moves), st1_random.

Ladders (level 0 = floor anchor, not in the composite):
  rotorwash : rw0_hold (all defaults) < rw1_creep (terrain-following hover, 2 m/s, no hook) < rw2_naive (10 m/s
              cruise, ignores terrain) < rw3_mission (PD: fly the gap, hook, deliver; the frozen copy of the v1
              test controller `tests/test_arena_rotorwash.py::mission`).  rw3 is the Rotorwash REFERENCE.
  (Levels 2-3 add a small seeded jitter / random tie-break per candidate so that the three opponent seats, which
  otherwise play identical symmetric trajectories, are decorrelated; this lowers per-round variance.)
  lightcycle: lc0_straight < lc1_random_safe (uniform over non-crash moves) < lc2_greedy_area (max flood-fill area,
              then run; = what the L1 sensors alone suggest; never boosts) < lc3_territory (shrink-aware Voronoi
              territory with 1-tick head-on avoidance and boost when it gains territory).
  stack     : st0_spawn_drop (the default) < st1_random < st2_greedy_sensor (min holes, then max height, then
              -lines: the L1 shared sensor read greedily) < st3_eltetris (El-Tetris 6-feature evaluation,
              published weights, over every rotation x column).
"""
from __future__ import annotations

import math
import random

import numpy as np

from nagi.burst2._rt.arena.core import Query
from nagi.burst2._rt.arena.games import lightcycle as lc
from nagi.burst2._rt.arena.games import stack as st
from nagi.burst2._rt.arena.games.rotorwash import COLL_OPTS, CYC_OPTS, SKID_H, WINCH_OPTS


class Bot:
    wants_state = True

    def __init__(self, bot_id: str):
        self.bot_id = self.name = bot_id
        self.game = self.state = None
        self.seat = self.seed = None
        self.rng = random.Random(0)
        self.mem: dict = {}

    def bind(self, seat: int, seed: int) -> "Bot":
        self.seat, self.seed = seat, seed
        self.rng = random.Random(f"{self.bot_id}|{seed}|{seat}")
        self.mem = {}
        return self

    def see(self, game, state) -> None:
        self.game, self.state = game, state
        self._plan = None

    def choose(self, q: Query) -> str:
        raise NotImplementedError


# ================================================================ Rotorwash

def _nearest(opts, vals, v):
    return min(zip(opts, vals), key=lambda ov: abs(ov[1] - v))[0]


def rw_mission(o, mem, vx_cruise=10.0, hook=True):
    """Frozen copy of tests/test_arena_rotorwash.py::mission (vx_cruise=10, hook=True is byte-for-byte the same
    policy). Only reads the numeric observation (Rotorwash.observe)."""
    up, up45, fu, fw, fd, dn45, dn = o["rays"]
    dx, dy, vx, vy = o["target_dx"], o["target_dy"], o["vx"], o["vy"]
    winch, e_alt, vxd, near = "hold", (up - dn) / 2, vx_cruise, abs(o["target_dx"]) < 60 and hook
    if not o["hooked"]:
        if near:
            vxd, e_alt = max(-4, min(4, 0.35 * dx)), dy + 14.0
            winch = "down" if o["rope"] < 14.5 else "hold"
    else:
        if near:
            vxd = max(-4, min(4, 0.35 * dx))
            e_alt = dy + SKID_H if abs(dx) < 2.5 and abs(vx) < 1.0 else dy + 8.0
        winch = "up" if o["rope"] > 5.5 else "hold"
    if not near:
        if fd < 30 or dn45 < 20:
            e_alt += 8
        if fu < 30 or up45 < 20:
            e_alt -= 8
        if min(fw, fu) < 25:
            vxd = min(vxd, 1.0)
    lim = 2.0 if near else 2.5
    vyd = max(-lim, min(2.5, 0.3 * e_alt))
    ay = (vy - mem.get("vy", vy)) / 0.25
    mem["vy"] = vy
    dc = 0.9 * (vyd - vy) - 0.35 * ay
    return {"collective": _nearest(COLL_OPTS, (-2, -1, 0, 1, 2), dc),
            "cyclic": _nearest(CYC_OPTS, (-20, -10, 0, 10, 20), max(-15, min(15, 7.0 * (vxd - vx)))),
            "winch": winch}


def rw_naive(o, mem):
    """Frozen copy of tests/test_arena_rotorwash.py::naive: hold vy ~ 0, cruise ~10 m/s, never looks at terrain."""
    coll = "up1" if o["vy"] < -0.5 else ("down1" if o["vy"] > 0.5 else "hold")
    cyc = "fwd1" if o["vx"] < 10 else ("aft1" if o["vx"] > 12 else "center")
    return {"collective": coll, "cyclic": cyc, "winch": "hold"}


class RotorwashBot(Bot):
    POLICIES = {
        "rwR_random": None,  # uniform random per axis (seeded): the normalization floor (random = 0)
        "rw0_hold": lambda o, m: {},
        "rw1_creep": lambda o, m: rw_mission(o, m, vx_cruise=2.0, hook=False),
        "rw2_naive": rw_naive,
        "rw3_mission": rw_mission,
    }

    def choose(self, q: Query) -> str:
        if self._plan is None:
            if self.bot_id == "rwR_random":
                self._plan = {"collective": self.rng.choice(COLL_OPTS), "cyclic": self.rng.choice(CYC_OPTS),
                              "winch": self.rng.choice(WINCH_OPTS)}
            else:
                o = self.game.engine.observe(self.state, self.seat)
                self._plan = self.POLICIES[self.bot_id](o, self.mem)
        return self._plan.get(q.key, q.default)


# ================================================================ Lightcycle

_WW = lc.W
_RING = np.array(lc.RING, dtype=np.int16).reshape(_WW, _WW)


def _dilate(a: np.ndarray) -> np.ndarray:
    o = a.copy()
    o[1:, :] |= a[:-1, :]
    o[:-1, :] |= a[1:, :]
    o[:, 1:] |= a[:, :-1]
    o[:, :-1] |= a[:, 1:]
    return o


def _path(blk, h, d, opt, charges, boost_need):
    nd = (d + lc.TURN[opt.removeprefix("boost_")]) % 4
    path = [h + lc.STEP[nd]]
    boost = opt.startswith("boost_") and charges >= boost_need
    if boost and not blk[path[0]]:
        path.append(path[0] + lc.STEP[nd])
    return nd, path, boost


def lc_safe_options(blk, h, d, charges, boost_need=1, allow_boost=True):
    out = []
    for o in lc.OPTIONS:
        if o.startswith("boost_") and (not allow_boost or charges < boost_need):
            continue
        _, path, _ = _path(blk, h, d, o, charges, boost_need)
        if not any(blk[c] for c in path):
            out.append(o)
    return out


class LightcycleBot(Bot):
    def _boost_need(self):
        v = getattr(self.game, "variant", None)
        return 2 if v is not None and v.id == "lc_boost_cost2" else 1

    def choose(self, q: Query) -> str:
        s, p = self.state, self.seat
        u = self.rng.random()  # advance the stream exactly once per decision
        if self.bot_id == "lc0_straight":
            return "straight"
        if self.bot_id == "lcR_random":  # uniform over all 6 options, crashes included: the floor
            return lc.OPTIONS[int(u * len(lc.OPTIONS))]
        blk, h, d, ch, need = s.blocked(), s.head[p], s.dir[p], s.charges[p], self._boost_need()
        if self.bot_id == "lc1_random_safe":
            safe = lc_safe_options(blk, h, d, ch, need)
            return safe[int(u * len(safe))] if safe else "straight"
        if self.bot_id == "lc2_greedy_area":
            best, key = "straight", None
            for i, o in enumerate(("straight", "left", "right")):
                sens = lc.Lightcycle._sensor(blk, h, d, o, ch)
                if sens == "crash":
                    continue
                run, area = (int(x.split()[1]) for x in sens.split(", "))
                k = (area, run, self.rng.random())  # seeded tie-break decorrelates the 3 opponent seats
                if key is None or k > key:
                    best, key = o, k
            return best
        return self._territory(s, p, blk, h, d, ch, need)

    def _territory(self, s, p, blk, h, d, ch, need):
        free0 = np.frombuffer(blk, dtype=np.uint8).reshape(_WW, _WW) == 0
        opps = [q for q in range(4) if q != p and s.alive[q]]
        danger = set()
        for q in opps:
            for turn in (0, 1, 3):
                nd = (s.dir[q] + turn) % 4
                c = s.head[q] + lc.STEP[nd]
                danger.add(c)
                if s.charges[q] > 0 and not blk[c]:
                    danger.add(c + lc.STEP[nd])
        # per-BFS-step closed-ring masks (a cell reached at step k is entered at time t + k * 125 ms)
        horizon = 120
        ring_ok = [None] * (horizon + 1)
        best, bkey = "straight", None
        for i, o in enumerate(lc.OPTIONS):
            if o.startswith("boost_") and ch < need:
                continue
            nd, path, boost = _path(blk, s.head[p], d, o, ch, need)
            if any(blk[c] for c in path):
                continue
            free = free0.copy()
            for c in path:
                free.flat[c] = False
            own = np.zeros_like(free)
            own.flat[path[-1]] = True
            opp = np.zeros_like(free)
            for q in opps:
                opp.flat[s.head[q]] = True
            seen = own | opp
            # opponents move this tick too: give them their first step before we count ours
            opp_front = _dilate(opp) & free & ~seen
            seen |= opp_front
            own_front, n_own = own, 0
            for k in range(1, horizon + 1):
                if ring_ok[k] is None:
                    ring_ok[k] = _RING >= lc.rings_closed(s.t + (k + 1) * lc.Lightcycle.decision_period_ms)
                ok = free & ring_ok[k] & ~seen
                a = _dilate(own_front) & ok
                b = _dilate(opp_front) & ok
                both = a & b
                a &= ~both
                seen |= a | b
                n_own += int(a.sum())
                own_front, opp_front = a, b
                if not own_front.any():
                    break
            risk = 1000 if any(c in danger for c in path) else 0
            # keep >= 3 rings of margin to the ring that will be closed 3 s from now
            margin = int(_RING.flat[path[-1]]) - lc.rings_closed(s.t + 3000)
            edge = 40 * max(0, 3 - margin)
            hugs = sum(1 for st_ in lc.STEP if not free0.flat[path[-1] + st_] and _RING.flat[path[-1] + st_] >= 0)
            jitter = 3.0 * self.rng.random()  # seeded, decorrelates otherwise-identical opponent seats
            key = (n_own - risk - edge - (4 if boost else 0) + jitter, hugs, -i)
            if bkey is None or key > bkey:
                best, bkey = o, key
        return best


# ================================================================ Stack

_ELT = (-4.500158825082766, 3.4181268101392694, -3.2178882868487753, -9.348695305445199, -7.899265427351652,
        -3.3855972247263626)  # El-Tetris weights: landing h, rows cleared, row trans, col trans, holes, well sums


def _land(rows, piece, rot, col):
    _, cells, _, _ = st._orient(piece, rot)
    y0 = st.H_TOTAL
    while y0 > 0 and all(y0 - 1 + dy >= 0 and not (y0 - 1 + dy < st.H_TOTAL and rows[y0 - 1 + dy] >> (col + dx) & 1)
                         for dx, dy in cells):
        y0 -= 1
    return y0, cells


def eltetris_value(rows, piece, rot, col) -> float | None:
    y0, cells = _land(rows, piece, rot, col)
    new, n, top = st.drop(rows, piece, rot, col)
    if top:
        return None
    hgt = max(dy for _, dy in cells) + 1
    landing = y0 + (hgt - 1) / 2.0
    full = (1 << st.W) - 1
    vis = new[:st.H]
    rt = 0
    for r in vis:
        rr = (r << 1) | 1 | (1 << (st.W + 1))  # walls on both sides are filled
        rt += bin((rr ^ (rr >> 1)) & ((1 << (st.W + 1)) - 1)).count("1")
    ct = 0
    for c in range(st.W):
        prev = 1  # floor is filled
        for y in range(st.H):
            b = vis[y] >> c & 1
            ct += b != prev
            prev = b
        ct += prev != 0  # sky is empty
    hs = st.heights(new)
    holes_ = sum(1 for c in range(st.W) for y in range(hs[c]) if not new[y] >> c & 1)
    wells = 0
    for c in range(st.W):
        for y in range(st.H):
            if vis[y] >> c & 1:
                continue
            left = c == 0 or vis[y] >> (c - 1) & 1
            right = c == st.W - 1 or vis[y] >> (c + 1) & 1
            if left and right:
                depth = 0
                yy = y
                while yy >= 0 and not vis[yy] >> c & 1:
                    depth += 1
                    yy -= 1
                wells += depth
    del full
    f = (landing, n, rt, ct, holes_, wells)
    return sum(w * x for w, x in zip(_ELT, f))


class StackBot(Bot):
    def _pick(self):
        s, p = self.state, self.seat
        b = s.boards[p]
        piece = s.seq[b.idx]
        rots = st.rotation_options(piece)
        u1, u2 = self.rng.random(), self.rng.random()  # two draws per decision point, always
        if self.bot_id == "st0_spawn_drop":
            return "rot0", st.default_column(piece, "rot0")
        if self.bot_id == "st1_random":
            r = rots[int(u1 * len(rots))]
            cols = st.column_options(piece, r)
            return r, cols[int(u2 * len(cols))]
        best, bkey = None, None
        for ri, r in enumerate(rots):
            for ci, cid in enumerate(st.column_options(piece, r)):
                col = int(cid[1:])
                if self.bot_id == "st2_greedy_sensor":
                    new, n, top = st.drop(b.rows, piece, r, col)
                    key = (0 if top else 1, -st.holes(new), -max(st.heights(new)), n, self.rng.random())
                else:
                    v = eltetris_value(b.rows, piece, r, col)
                    jit = self.rng.random()  # seeded jitter in [0, 1) decorrelates identical opponent boards
                    key = (0, 0.0, -ri, -ci) if v is None else (1, v + jit, -ri, -ci)
                if bkey is None or key > bkey:
                    best, bkey = (r, cid), key
        return best

    def choose(self, q: Query) -> str:
        if self._plan is None:
            self._plan = self._pick()
        r, c = self._plan
        if q.key == "rotation":
            return r
        # column stage: the engine asks for the column of the rotation actually applied
        return c if c in q.options else q.default


BOTS = {**{k: RotorwashBot for k in RotorwashBot.POLICIES},
        **{k: LightcycleBot for k in ("lcR_random", "lc0_straight", "lc1_random_safe", "lc2_greedy_area", "lc3_territory")},
        **{k: StackBot for k in ("st0_spawn_drop", "st1_random", "st2_greedy_sensor", "st3_eltetris")}}


def make_bot(bot_id: str) -> Bot:
    return BOTS[bot_id](bot_id)
