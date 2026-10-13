"""Strict request-only teachers; no engine-state or true-course input path.

Both teachers start from the same rendered information and deterministic prior.
C keeps the old finite-horizon Q/continuation/tie algorithm, on repaired inputs;
T keeps the newer anchored controller/continuation, on repaired inputs. Neither
is bit-identical to the historical residual-privilege pipeline.

Unobserved actuator state uses a declared prior: stall age zero, delivered engine
power equal to displayed required power. No true timer is made visible. Terrain
is the displayed seven-ray reconstruction; course dimensions, bay intervals and
heave amplitudes are public generator priors. x/y are a canonical frame inferred
from mean ship position and rendered dx; they never come from hidden state.
"""
from __future__ import annotations

import dataclasses
import hashlib
import math
import types

from nagi.burst2._rt.arena.games import rotorwash as rw
from nagi.burst2._rt.arena.games import rotorwash_ramp as ramp
from nagi.burst2._rt.arena.games import rotorwash_ramp_v31 as V
from nagi.burst2._rt.burst_v2 import qengine as QE
from nagi.burst2._rt.burst_v2 import rr as R
from nagi.burst2._rt.burst_v2 import rr_teacher as RT
from nagi.burst2._rt.rr_teacher_pilot.contract import Request, NOMINAL_P_HAT

CONFIG = dict(RT.DEFAULTS, filt_delays=(1,), lag_pred=True)


class InformationWorld(R.World):
    """No ``gap_min(seed)`` lookup: roof lower bounds come from this belief."""
    def rc(self, k):
        rc = self.rcs.get(k)
        if rc is None:
            gap = information_gap(self.course, self.sched)
            rc = ramp.RampCourse(self.course, gap, V.ramp_at(self.sched, k).roof_mm / 1000)
            rc.R = [rc.C[i] for i in range(rc.n)]
            self.rcs[k] = rc
        return rc


def information_gap(co, sched):
    return tuple((rw.DECK_ABOVE_WATER + 1.4 * co.ships[min(int(i * rw.DX // rw.LEG_LEN),
                                                       len(co.ships) - 1)][2] + sched.bay_gap_mm / 1000)
                 if co.BAY[i] else sched.roof_gap_mm / 1000 for i in range(co.n))


def canonical_state_and_course(req: Request, ad):
    o = RT.parse_prompt(req.state)
    tick = round(o["t"] * 1000 / R.TICK_MS)
    if abs(tick * R.TICK_MS / 1000 - o["t"]) > 1e-9:
        raise ValueError("request clock must be on a 0.25s boundary")
    j = o["ship"]
    if not 0 <= j < rw.N_LEGS:
        raise ValueError("invalid displayed ship")
    # Generator mean, not actual ship x. Global vertical origin is arbitrary.
    sx, y = j * rw.LEG_LEN + 435.0, 100.0
    x = sx - o["ship_dx"]
    n = int(rw.N_LEGS * rw.LEG_LEN / rw.DX) + 1
    ce, fl = RT.ray_terrain(o, x, y, CONFIG["extrap"])
    floor = [RT._interp(fl, i * rw.DX) for i in range(n)]
    ceiling = [RT._interp(ce, i * rw.DX) + o["roof"] for i in range(n)]
    t = tick * R.TICK_MS / 1000
    ships = [RT._mean_deck(i, t, y + o["ship_dy"], o["ship_vy"],
                          sx + (i - j) * rw.LEG_LEN) for i in range(rw.N_LEGS)]
    landed = j - 1 if o["landed"] and j > 0 else -1
    if landed >= 0:
        ships[landed] = RT._mean_deck(landed, t, y - rw.SKID_H, o["vy"], x)
    bay = [int(370 <= (i * rw.DX) % rw.LEG_LEN <= 500) for i in range(n)]
    shipc = [-1] * n
    for i in range(n):
        for sj, sh in enumerate(ships):
            if abs(i * rw.DX - sh[0]) <= rw.SHIP_HALF + 12:
                shipc[i] = sj
    leg = max(0, min(int(x // rw.LEG_LEN), rw.N_LEGS - 1))
    surv = [(i * rw.LEG_LEN + 215., y - o["agl"]) for i in range(rw.N_LEGS)]
    if not o["hooked"]:
        surv[leg] = (x + o["surv_dx"], y + o["surv_dy"])
    gsx, gsy = RT._gust_scale(o)
    # Synthetic seed is keyed by visible bytes only, never the game seed.
    seed = int(req.sha256[:15], 16)
    nG = rw.MAX_STEPS + 8 * rw.HZ
    co = rw.Course(seed, n, rw.N_LEGS * rw.LEG_LEN, floor, ceiling,
                   [max(floor[max(0,i-2):i+3]) for i in range(n)],
                   [min(ceiling[max(0,i-2):i+3]) for i in range(n)], bay,
                   [o["wind"][0]] * n, [gsx] * n, [gsy] * n, [0.] * n,
                   [0.] * n, [o["wind"][1] / o["gust_gain"]] * n, shipc,
                   [0.] * nG, [0.] * nG, tuple(surv), tuple(ships), (), (), y)
    h = rw.new_heli(x, y)
    h.update(ships_landed=tuple(range(j)), td_E=None, td_ship=None, t_first_land=None,
             t_last_point=None, ckpt=0, leg=leg, landed=landed, att=o["hooked"],
             last=tuple(req.p_log[c] for c in ad.CONTROLS))
    pav = rw.P_AVAIL * V.ramp_at(ad.sched, tick).power_q / 1024
    h = RT.display_heli(h, o, pav)
    # Score bookkeeping is an information-derived prior, irrelevant to ship-1
    # readiness before landing; root increments use the same state in C/T.
    h["deliveries"] = max(0, int(o["points"]) - j)
    h["ckpt"] = max(0, min(V.N_CHECK, round(20 * (o["points"] - int(o["points"])))))
    h["max_x"] = max(x, V.X_START)
    return rw.RWState(seed=seed, k=tick * R.SUB, t_ms=tick * R.TICK_MS,
                      helis=[h], ended=False, extra={}), co


class InformationAdapter(R.RRAdapter):
    def __init__(self, req: Request):
        super().__init__()
        self.req = req
        self.root, self.course = canonical_state_and_course(req, self)
        self.truth = lambda seed: self.course
        self.eng.observation = lambda state, seat: req.state
        # Keep frozen integrator bytecode exactly, but replace its ONLY hidden
        # lookup with a per-instance information-course gap. No monkey patch of
        # shared modules and no global side effect. Canary checks bytecode parity.
        original = V.RotorwashRampV31._integrate31
        namespace = dict(original.__globals__)
        namespace["RR"] = types.SimpleNamespace(gap_min=lambda seed, sched: information_gap(self.course, sched))
        integrate = types.FunctionType(original.__code__, namespace, original.__name__, original.__defaults__,
                                       original.__closure__)
        self.eng._integrate31 = types.MethodType(integrate, self.eng)

    def _anchor(self, world, state):
        world = InformationWorld(world.course, world.tag, world.winch_free, world.sched)
        return super()._anchor(world, state)


class _New(RT.RRTeacherPlanner):
    def belief(self, state, p_log, n):
        # RT.Belief only sees canonical state and the constructed prior course.
        bel = RT.Belief(self.ad, self.ad.root, self.ad.req.p_log, n, text=self.ad.req.state,
                        extrap=self.extrap, decay=self.decay)
        bel.worlds = [InformationWorld(w.course, w.tag, w.winch_free, w.sched) for w in bel.worlds]
        return bel


class Teacher:
    """A pure function of the complete served Request plus fixed sampler key.

    Create once per request, then call ``controller`` / ``label``. No API accepts
    the true state, hidden timers, actual course, seed or control-history metadata.
    ``label`` is diagnostic; use controller only after exact equality canary.
    """
    def __init__(self, req: Request, kind="new", key="rrtp", worlds=4):
        if kind not in ("old", "new"):
            raise ValueError(kind)
        self.req, self.kind = req, kind
        self.ad = InformationAdapter(req)
        if kind == "new":
            self.planner = _New(self.ad, NOMINAL_P_HAT, markov=None, key=key,
                                **dict(CONFIG, B=worlds))
        else:
            self.planner = QE.LabelPlanner(self.ad, NOMINAL_P_HAT, worlds, False, None, key=key)

    def controller(self):
        if self.kind != "new":
            raise ValueError("old pipeline requires its Q labels")
        return self.planner.base_answer(self.ad.root, self.req.p_log)

    def label(self, sampler_key="fixed"):
        return self.planner.label(self.ad.root, self.req.p_log, sampler_key)


def source_sha256():
    from pathlib import Path
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
