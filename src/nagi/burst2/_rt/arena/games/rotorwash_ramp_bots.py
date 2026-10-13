"""Rotorwash-Ramp bot ladder (CPU, deterministic given (seed, seat); privileged: bots read the engine state).

Ladder (docs/arena_v3/ROTORWASH_RAMP.md §5), all flying the SAME ramp, calibrated through the realtime runner's
timing with a 1-tick reply delay (arena.v3.delay; FAIL_FIRST_BRIEF Amendment 3):
  naive     rw1_creep    the frozen v2 L1 bot (terrain-following hover at 2 m/s, no hook): outrun by the front.
  heuristic rw3_mission  the frozen v2 L3 reference (flies the rescue mission, ignores the front: caught while it
                         hovers to hook). Replaced rw2_naive as the rung on 2026-09-27: with the 1-tick delay rw2_naive
                         dies on cave terrain at a fixed distance (median 20.1 s, below the 22-35 s band) that no
                         clock lever moves; rw3_mission's death is clock-driven (the front).
  planner   rwP_ramp     NEW (this module): privileged corridor planner. It reads the exact course, the lowered
                         roof and the ramp schedule, picks a forward speed that keeps a margin to the collapse
                         front (anticipating its acceleration), flies the centre of the tightest corridor ahead
                         (look-ahead scaled with speed) and skips rescues (survival is the metric). Then a
                         one-tick safety filter simulates the 5 collective options (the engine's own physics, 2 s
                         horizon with the planner's cyclic) and vetoes any that crash. Delay-aware: with `lag`
                         set it plans from the exactly predicted state where its reply lands.
  reported, not a rung: rw0_hold (defaults), rw2_naive (the v2 L2 bot; the pre-delay heuristic rung).
v2 bots are imported unchanged from arena.v2.bots (their ladder hash stays 825b031a...).
"""
from __future__ import annotations

import contextlib
import hashlib
import math

from nagi.burst2._rt.arena.v2.bots import Bot, make_bot

LADDER_IDS = ("rw1_creep", "rw3_mission", "rwP_ramp")        # naive, heuristic, planner (seats 1..3 in v3)
REPORTED_IDS = ("rw0_hold", "rw2_naive")
COLL_STEPS = (("down2", -2), ("down1", -1), ("hold", 0), ("up1", 1), ("up2", 2))
CYC_U = (("aft2", -0.6), ("aft1", -0.3), ("center", 0.0), ("fwd1", 0.3), ("fwd2", 0.6))


def ramp_seed(split: str, i: int, game: str = "rotorwash_ramp") -> int:
    """v3 seed formula (scripts/arena_v3_registry.seed_for): sha256('arena-v3|game|split|i') mod 2^31."""
    return int(hashlib.sha256(f"arena-v3|{game}|{split}|{i}".encode()).hexdigest(), 16) % (2 ** 31)


def _nearest(pairs, v):
    return min(pairs, key=lambda kv: abs(kv[1] - v))[0]


class RampPlanner(Bot):
    """rwP_ramp: see the module docstring. Every choice is a pure function of the state (no RNG)."""

    LOOK = (0.4, 0.8, 1.2, 1.6, 2.0, 2.6, 3.2)   # s of look-ahead along the planned speed
    belief = None   # optional RampGame whose rules the planner ASSUMES (flip shares / value of knowing); None = truth
    SAFETY_TICKS = 8
    SEARCH_CYCLIC = False

    def _corridor(self, eng, s, x, vx, k):
        from nagi.burst2._rt.arena.games.rotorwash_ramp import ramp_course, ramp_at, TICKS_PER_LEVEL, N_TICKS
        rc_now = ramp_course(s.seed, eng.sched, k)
        rc_fut = ramp_course(s.seed, eng.sched, min(N_TICKS, k + 12))
        lo, hi = -1e9, 1e9
        for tau in self.LOOK:
            xx = x + max(vx, 2.0) * tau
            fl = rc_now.floor_at(xx)
            ce = (rc_fut if tau > 1.5 else rc_now).ceil_at(xx)
            for sh in rc_now.ships:
                if abs(xx - sh[0]) <= 16.0:
                    fl = max(fl, sh[1] + 1.4 * sh[2] + 1.0)
            lo, hi = max(lo, fl), min(hi, ce)
        return lo, hi

    def _decide(self):
        from nagi.burst2._rt.arena.games.rotorwash_ramp import REAR, TICK_MS, front_m, ramp_at
        g, s, p = self.belief or self.game, self.state, self.seat
        eng = g.engine
        h = s.helis[p]
        k = s.t_ms // TICK_MS
        x, y, vx, vy = h["x"], h["y"], h["vx"], h["vy"]
        gap = x - REAR - front_m(eng.sched, s.k)
        v_front = ramp_at(eng.sched, min(k + 12, 360)).front_mm_s / 1000
        # speed: front speed 3 s ahead + a margin controller on the gap (target 45 m)
        vxd = v_front + 0.15 * (45.0 - gap) + 1.0
        vxd = max(3.0, min(24.0, vxd))
        lo, hi = self._corridor(eng, s, x, vx, k)
        # vertical target: centre of the tightest corridor ahead, kept >= 4 m from each side when possible
        yc = (lo + hi) / 2 + 0.5
        e_alt = yc - y
        room = hi - lo
        lim = 3.0 + 0.1 * vx
        vyd = max(-lim, min(lim, 0.45 * e_alt))
        ay = (vy - self.mem.get("vy", vy)) / 0.25
        self.mem["vy"] = vy
        dc = 1.1 * (vyd - vy) - 0.35 * ay
        o = eng.observe(s, p)
        if o["rpm"] < 96.0 or o["power_margin"] < 3.0:
            dc = min(dc, 0.0)
        coll = _nearest(COLL_STEPS, dc)
        # cyclic: speed tracking, limited when the corridor is tight (a pitched rotor disc sweeps more height)
        pitch_lim = 15.0 if room > 14 else 10.0
        cyc = _nearest(tuple((n, v * 33.3) for n, v in CYC_U),
                       max(-pitch_lim, min(pitch_lim, 7.0 * (vxd - vx))))
        coll, cyc = self._safety(eng, s, p, coll, cyc)
        return {"collective": coll, "cyclic": cyc, "winch": "up" if h["L"] > 5.5 else "hold"}

    def _safety(self, eng, s, p, coll, cyc):
        """Roll out the controller's (collective, cyclic) for one tick, then hold, over SAFETY_TICKS ticks on a copy
        of the heli (the engine's own step). Keep it if it survives the horizon; otherwise search the candidates
        (collective only; or collective x cyclic when SEARCH_CYCLIC) and take the one that survives longest, ties
        -> closest to the controller's choice (L1 distance in option index)."""
        if self._rollout(eng, s, p, coll, cyc) >= self.SAFETY_TICKS:
            return coll, cyc
        co_order = [c for c, _ in COLL_STEPS]
        cy_order = [c for c, _ in CYC_U]
        wc, wy = co_order.index(coll), cy_order.index(cyc)
        cands = [(c, cyc) for c in co_order] if not self.SEARCH_CYCLIC else [(c, y) for c in co_order for y in cy_order]
        best, best_key = (coll, cyc), None
        for c, y in cands:
            if (c, y) == (coll, cyc):
                continue
            t_alive = self._rollout(eng, s, p, c, y)
            key = (t_alive, -(abs(co_order.index(c) - wc) + abs(cy_order.index(y) - wy)))
            if best_key is None or key > best_key:
                best, best_key = (c, y), key
            if t_alive >= self.SAFETY_TICKS and not self.SEARCH_CYCLIC:
                pass
        return best

    def _rollout(self, eng, s, p, coll, cyc):
        from nagi.burst2._rt.arena.games.rotorwash import RWState
        h = dict(s.helis[p])
        h["alive"] = True
        st = RWState(seed=s.seed, k=s.k, t_ms=s.t_ms, helis=[h], ended=False)
        acts = {"collective": coll, "cyclic": cyc, "winch": "hold"}
        step = getattr(self.belief or self.game, "step", eng.step)   # the wrapper applies its variant's constants
        for i in range(self.SAFETY_TICKS):
            st, _ = step(st, {0: acts}, 250)
            if not st.helis[0]["alive"]:
                return i
            acts = {"collective": "hold", "cyclic": cyc, "winch": "hold"}
        return self.SAFETY_TICKS

    lag = None   # set by arena.v3.delay.Delayed: (controls the runner applies before this reply lands, ticks)

    def _predict(self):
        """Delay-aware (realtime ladder): the state where this reply lands, exact (the engine's own step on a copy of
        this heli): the runner's controls of the current tick, then its hold rules (collective one_shot -> hold,
        cyclic and winch persistent). None if the heli crashes meanwhile (then plan from the observed state)."""
        from nagi.burst2._rt.arena.games.rotorwash import RWState
        acts, n = self.lag
        h = dict(self.state.helis[self.seat])
        st = RWState(seed=self.state.seed, k=self.state.k, t_ms=self.state.t_ms, helis=[h], ended=False)
        g = self.belief or self.game
        step = getattr(g, "step", g.engine.step)
        for i in range(n):
            st, _ = step(st, {0: acts}, 250)
            if not st.helis[0]["alive"]:
                return None
            acts = dict(acts, collective="hold")
        return st

    def choose(self, q):
        if self._plan is None:
            g = self.belief or self.game
            with (g.ctx() if hasattr(g, "ctx") else contextlib.nullcontext()):
                pred = self._predict() if self.lag else None
                if pred is not None:
                    obs, seat = self.state, self.seat
                    self.state, self.seat = pred, 0
                    try:
                        self._plan = self._decide()
                    finally:
                        self.state, self.seat = obs, seat
                else:
                    self._plan = self._decide()
        return self._plan.get(q.key, q.default)

    def see(self, game, state):
        self.game, self.state = game, state
        self._plan = None


class RampOracle(RampPlanner):
    """rwO_oracle (reported, not a rung): the planner with a 3 s safety horizon searching collective x cyclic (25
    candidates) whenever the controller's choice would crash: a stronger, slower search probe that shows the ramp
    still defeats a search oracle before the cap."""
    SAFETY_TICKS = 12
    SEARCH_CYCLIC = True


RAMP_BOTS = {"rwP_ramp": RampPlanner, "rwO_oracle": RampOracle}


def make_ramp_bot(bot_id: str):
    if bot_id in RAMP_BOTS:
        return RAMP_BOTS[bot_id](bot_id)
    return make_bot(bot_id)
