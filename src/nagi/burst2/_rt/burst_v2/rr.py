"""Rotorwash-Ramp v3.1 (rules ramp2.0 now, ramp2.1 when bound) label adapter for burst_v2.qengine (RR_LABELS.md).

Value of a Q rollout (K3-RR points, horizon-limited):
    V = Y(end) - Y(s0) + Phi(end)          Y = the engine's own round score (S + D + P under ramp2.0)
    the rollout stops at a crash (Phi = 0; a failing touchdown keeps its partial credit in Y), at a new landing or
    delivery (S or D grows; Phi of the landed state = the next ship), at the round cap, or at MAX_TICKS (Phi of the
    state reached). MAX_TICKS = 16 ticks = 4 s from the request (latency ticks included).
    Phi(s) = G * exp(-LAM * T_go) * F_cap * S_safe      (alive; 0 when dead)
        G      = points of the next valid touchdown n = 1 (next ship not yet landed on) + 1 (survivor hooked)
                 - the approach credit already banked (ramp2.1; 0 under ramp2.0)
                 + n FUTURE (T_left - T_go)+ / cap (round time left after it: more points fit, as Booster V2;
                 a realised landing / delivery likewise adds FUTURE (cap - t) / cap per point to Y)
        T_go   = T_h + T_v: bang-bang time to reach the next ship's x and stop there (accel A_ACC, brake A_BRK,
                 cruise V_CRUISE; moving away first stops), overlapped with the fast descent to E_DESC above the
                 deck (V_DESC_FAST): T_go = max(T_h, (e - E_DESC)+ / V_DESC_FAST) + min(e, E_DESC) / V_DESC
        F_cap  = clip((T_left - T_go) / 4 s + 0.5, 0, 1): no value for a landing after the round cap
        S_safe = S_up * S_dn: vertical closing-speed check at the end state against the lowered roof and the
                 floor / deck below (1 while the required deceleration <= A_OK, 0 from twice that), times a
                 vortex-ring factor for a fast sink at low speed, times the flight envelope S_env (linear to 0
                 between ok / bad: |vx| 17 / 22 m/s, |vy| 6 / 9 m/s, |pitch| 15 / 25 deg): a greedy root choice must
                 not buy time-to-go with a state the continuation cannot recover from
    Why not stalling: a hover keeps T_go (so Phi) constant while any progress lowers T_go, so under equal risk a
    progressing joint always has the larger Q; there is no time term that a hover could collect (RR_LABELS.md §3).

Trust region (conservative policy improvement): V also subtracts KAPPA_DEV = 0.004 per control in which the labelled
joint differs from the continuation's own answer at the request state (per world; the winch is exempt while it
provably cannot matter). Without it the one-step greedy label policy compounds sub-noise Phi gains the continuation
never gets to realise (measured: 29 m/s / 30 deg runaways into the roof, K3 0 on 2/2 seeds, see RR_LABELS.md §3).

Observation-consistent worlds (cheat=False). What the prompt shows at tick k: the heli's own state (rounded), the rays
(7 directions, <= 80 m, the lowered roof), the current wind at the heli (0.1 m/s), the next ship's deck dx / dy / vy,
the survivor dx / dy, t, level, roof drop, storm gain, power. A world is one sample of the hidden exogenous future:
  * GUSTS: the unit OU gust (tau 2.5 s, the engine's 30 Hz law) restarted from the value implied by the displayed
    wind (+-0.05 display rounding, uniform) through the static wind field of the heli's cell; fresh innovations;
  * DECK HEAVE of the next ship (and of the ship the heli sits on): periods / phases / base sampled from the course
    generator's prior (leg amplitude law) conditioned on the displayed deck height and speed (+-0.05) by solving the
    first harmonic's phase and the base (importance weight 1 / |J|, J = the Jacobian of (y, vy) wrt (base, phase));
  * TERRAIN: the true cave only inside the observed window [x - 10 m, x + RAY_MAX]; beyond it the floor / roof are
    extended flat from the window edge (the heli cannot leave the window within MAX_TICKS below 18 m/s);
  * ROOF: its future drop is the rules' clock-only schedule (the prompt shows t and the current drop).
Residual privileges (disclosed, RR_LABELS.md §2): the terrain shape between the rays inside the window, the static
wind field (mean wind, gust scale, shear zones) inside the window, ship / survivor x to below display rounding, the
heli's own unrounded state, the deck motion of ships other than the next / landed one (unreachable in 4 s).
cheat=True returns the true world (diagnostic only).

The continuation (RRCont) is non-clairvoyant: every decision reads only the current state of its world, through the
same seven rays the prompt shows (cast in that world, lowered roof) plus the next ship's deck state: the rwL_planner
controller's flight / stop / heave-matched descent laws without the rescue, the privileged corridor look-ahead or
the safety filter. The latency-aware root Q (qengine) is the look-ahead.

Exact compute saving (tested): when the load is not hooked and the survivor is out of reach within the horizon, the
winch cannot change anything the rollout reads (rope length enters only the load dynamics and the hook test), so the
world's step normalises the winch to 'hold' and memoises (state, joint) steps: the 3 winch variants of a joint share
one trajectory and get bit-identical Q.
"""
from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import math
import random
import re
import time

from nagi.burst2._rt.arena.games import rotorwash as rw
from nagi.burst2._rt.arena.games import rotorwash_ramp as RR
from nagi.burst2._rt.arena.games import rotorwash_ramp_v31 as V
from nagi.burst2._rt.arena.games.rotorwash import DT, RAY_MAX, SKID_H, RWState, build_course
from nagi.burst2._rt.arena.games.rotorwash_ramp_bots import COLL_STEPS
from nagi.burst2._rt.arena.games.rotorwash_ramp_v31_planner import LandingPlanner
from nagi.burst2._rt.burst_v2 import labels as L

SUB = V.SUB                                   # 60 substeps per tick
TICK_MS = V.TICK_MS
# ---- potential constants (RR_LABELS.md §3)
FUTURE = 0.5          # K3 points per point scored x the share of the round left (as burst_v2.booster.FUTURE)
LAM = 0.02            # 1/s: value decay per second of time-to-go (crash hazard + ramp difficulty + cap pressure)
V_CRUISE = 16.0       # m/s reference cruise of the time-to-go model (a faster current speed counts as V_CRUISE)
ENV = ((17.0, 22.0), (6.0, 9.0), (15.0, 25.0))   # flight envelope: |vx| m/s, |vy| m/s, |pitch| deg: (ok, bad)
A_ACC, A_BRK = 1.5, 1.2
V_DESC, E_DESC = 1.0, 6.0     # m/s final descent speed over the last E_DESC m (the rwL hover height above the deck)
V_DESC_FAST = 2.5             # m/s descent speed above that height
A_OK_UP, A_OK_DN = 2.0, 2.0   # m/s^2 decelerations the heli can hold (down: stop a climb; up: stop a sink)
V_SINK_OK, V_SINK_BAD = 3.0, 5.0   # m/s sink at low airspeed: safe / vortex-ring onset (0.6 v_h, v_h = 8.45 m/s)
V_TD = 1.5                    # m/s sink accepted at touchdown over a deck in the safety check
# ---- continuation (rwL_planner laws, non-clairvoyant)
KV, KP_V = 5.0, 1.0
# rwL_fast (arena.games.rotorwash_ramp_v31_planner.FastPlanner) constants
V_MAX, BRAKE, STOP_DX, LEAD_S = 22.0, 2.0, 3.0, 1.0
SINK, FLARE, FLARE_GAP, SINK_APP = 2.5, 1.0, 3.0, 4.0
FINAL_DX, FINAL_VX = 8.0, 3.0
V_ROOM0, V_ROOM_K, ROOM0 = 6.0, 0.8, 10.0
GLIDE, GLIDE_APP, MARGIN_LO, MARGIN_HI, DWELL_MS = 0.25, 0.3, 8.0, 6.0, 1500
KAPPA_DEV = 0.02     # K3 points per control the labelled joint changes vs the continuation's own answer (trust region)
COLL_BY_STEP = {v: n for n, v in COLL_STEPS}
WINDOW_BACK = 10.0
OBS_WIND = re.compile(r"wind ([-+]\d+\.\d),([-+]\d+\.\d) m/s \(x,y\)")
OBS_SHIP = re.compile(r"next ship (\d+): deck dx ([-+]\d+\.\d) m, dy ([-+]\d+\.\d) m, vy ([-+]\d+\.\d) m/s")
C45, C15, S15 = math.sqrt(0.5), math.cos(math.radians(15)), math.sin(math.radians(15))


def _h(key: str) -> random.Random:
    return random.Random(hashlib.sha256(key.encode()).hexdigest())


def parse_obs(text: str) -> dict:
    mw, ms = OBS_WIND.search(text), OBS_SHIP.search(text)
    if not (mw and ms):
        raise ValueError("rotorwash observation lines not found")
    return {"wind": (float(mw.group(1)), float(mw.group(2))), "ship": int(ms.group(1)) - 1,
            "ship_dx": float(ms.group(2)), "ship_dy": float(ms.group(3)), "ship_vy": float(ms.group(4))}


# ---------------------------------------------------------------------------------------------- worlds
@dataclasses.dataclass(eq=False)
class World:
    course: object              # a rotorwash.Course (true, or with the sampled / windowed hidden parts)
    tag: str
    winch_free: bool            # winch provably irrelevant within the horizon (see module docstring)
    sched: object
    memo: dict = dataclasses.field(default_factory=dict)
    rcs: dict = dataclasses.field(default_factory=dict)
    base: tuple | None = None   # the continuation's answer at the request state (trust-region anchor, KAPPA_DEV)
    root: object = None         # the state where the labelled joint is applied (set by continuation())
    s0: object = None           # the request state (its prefix steps are not memoised, so each d gets its own root)

    def rc(self, k: int):
        r = self.rcs.get(k)
        if r is None:
            r = self.rcs[k] = RR.RampCourse(self.course, RR.gap_min(self.course.seed, self.sched),
                                            V.ramp_at(self.sched, k).roof_mm / 1000)
            r.R = [r.C[i] for i in range(r.n)]           # the lowered roof nodes, materialised for fast_rays
        return r


RAY_DIRS = tuple((math.cos(math.radians(a)), math.sin(math.radians(a))) for a in rw.RAY_ANGLES)


def fast_rays(rc, x: float, y: float, t: float) -> list[float]:
    """rotorwash.Rotorwash.rays(rc, x, y, t) (the prompt's seven rays), bit-identical (tested), ~4x faster: the same
    operations in the same order on the materialised roof list rc.R instead of _Roof lookups and closures."""
    co, F, R, n, DXc = rc.co, rc.F, rc.R, rc.n, rw.DX
    boxes = []
    for j, sh in enumerate(co.ships):
        sx = sh[0]
        if abs(sx - x) > RAY_MAX + rw.SHIP_HALF:
            continue
        boxes.append((sx - rw.SHIP_HALF, sx + rw.SHIP_HALF, sh[1] - rw.DECK_ABOVE_WATER - rw.HULL_DEPTH,
                      co.deck(j, t)[0]))
    out = []
    for dx, dy in RAY_DIRS:
        best = RAY_MAX
        for xlo, xhi, bot, top in boxes:
            tmin, tmax = 0.0, best
            ok = True
            for o, d, lo, hi in ((x, dx, xlo, xhi), (y, dy, bot, top)):
                if abs(d) < 1e-12:
                    if o < lo or o > hi:
                        ok = False
                        break
                else:
                    a, b = (lo - o) / d, (hi - o) / d
                    if a > b:
                        a, b = b, a
                    tmin, tmax = max(tmin, a), min(tmax, b)
                    if tmin > tmax:
                        ok = False
                        break
            if ok:
                best = min(best, tmin)
        if abs(dx) < 1e-9:
            if dy > 0:
                out.append(round(min(best, max(0.0, rc.ceil_at(x) - y)), 3))
            else:
                out.append(round(min(best, max(0.0, y - rc.floor_at(x))), 3))
            continue
        x_end = x + dx * best
        i = int(x / DXc)
        s_prev = 0.0
        while True:
            xa, xb = i * DXc, (i + 1) * DXc
            sa = max(s_prev, (xa - x) / dx) if dx > 0 else max(s_prev, (xb - x) / dx)
            sb = (xb - x) / dx if dx > 0 else (xa - x) / dx
            sb = min(sb, best)
            if sa > sb or i < 0 or i >= n - 1:
                break
            f0, f1 = F[i], F[i + 1]
            ga = (y + dy * sa) - (f0 + (f1 - f0) * ((x + dx * sa) / DXc - i))
            gb = (y + dy * sb) - (f0 + (f1 - f0) * ((x + dx * sb) / DXc - i))
            if ga <= 0.0:
                best = min(best, sa)
            elif gb <= 0.0:
                best = min(best, sa + (sb - sa) * ga / (ga - gb))
            r0, r1 = R[i], R[i + 1]
            ga = -((y + dy * sa) - (r0 + (r1 - r0) * ((x + dx * sa) / DXc - i)))
            gb = -((y + dy * sb) - (r0 + (r1 - r0) * ((x + dx * sb) / DXc - i)))
            if ga <= 0.0:
                best = min(best, sa)
            elif gb <= 0.0:
                best = min(best, sa + (sb - sa) * ga / (ga - gb))
            if (dx > 0 and x_end <= xb) or (dx < 0 and x_end >= xa) or sb >= best:
                break
            s_prev = sb
            i += 1 if dx > 0 else -1
        out.append(round(max(0.0, best), 3))
    return out


def _ou_path(r: random.Random, v0: float, n: int) -> list[float]:
    """Unit OU (tau 2.5 s) knots every 8 substeps (the engine's 30 Hz law) from v0, linearly interpolated, n values."""
    a = math.exp(-1.0 / (30 * 2.5))
    b = math.sqrt(1 - a * a)
    knots = [v0]
    for _ in range(n // 8 + 2):
        knots.append(a * knots[-1] + b * r.gauss(0.0, 1.0))
    return [knots[m // 8] + (knots[m // 8 + 1] - knots[m // 8]) * (m % 8) / 8 for m in range(n)]


def _deck_posterior(r: random.Random, j: int, t: float, y_obs: float, vy_obs: float, x: float, m: int = 24) -> tuple:
    """A ship tuple (x, base, a1, w1, p1, a2, w2, p2, a3, w3, p3) for leg j given the deck height / speed at time t,
    under rotorwash.build_course's prior (amplitudes a1 = min(0.5 + 0.6 j, 3.5), a2 = a1/4, a3 = 0.15 a1; period
    max(7 - 0.3 j, 5) x U(0.9, 1.1); secondary period factors U(0.45, 0.6), U(1.6, 2.2); phases uniform; base flat)."""
    a1 = min(0.5 + 0.6 * j, 3.5)
    a2, a3 = 0.25 * a1, 0.15 * a1
    per0 = max(7.0 - 0.3 * j, 5.0)
    cands, ws = [], []
    for attempt in range(4 * m):
        per = per0 * r.uniform(0.9, 1.1)
        w1 = 2 * math.pi / per
        w2, p2 = 2 * math.pi / (per * r.uniform(0.45, 0.6)), r.uniform(0, 2 * math.pi)
        w3, p3 = 2 * math.pi / (per * r.uniform(1.6, 2.2)), r.uniform(0, 2 * math.pi)
        yo, vo = y_obs + r.uniform(-0.05, 0.05), vy_obs + r.uniform(-0.05, 0.05)
        ry = a2 * math.sin(w2 * t + p2) + a3 * math.sin(w3 * t + p3)
        rv = a2 * w2 * math.cos(w2 * t + p2) + a3 * w3 * math.cos(w3 * t + p3)
        c = (vo - rv) / (a1 * w1)
        if abs(c) >= 1.0:
            if attempt < 3 * m or cands:
                continue
            c = math.copysign(0.999, c)            # nothing feasible (display / model mismatch): nearest extreme
        s1 = math.sqrt(1 - c * c) * (1 if r.random() < 0.5 else -1)
        p1 = math.atan2(s1, c) - w1 * t
        cands.append((x, yo - a1 * s1 - ry, a1, w1, p1, a2, w2, p2, a3, w3, p3))
        ws.append(1.0 / max(abs(s1), 0.05))
        if len(cands) >= m:
            break
    u, acc = r.random() * math.fsum(ws), 0.0
    for c, w in zip(cands, ws):
        acc += w
        if u < acc:
            return c
    return cands[-1]


def _window(co, x: float) -> dict:
    """F, C, FH, CL with the cave outside [x - WINDOW_BACK, x + RAY_MAX] replaced by a flat extension of the window
    edge (what the prompt can see)."""
    n = co.n
    lo = max(0, min(n - 1, int((x - WINDOW_BACK) / rw.DX)))
    hi = max(0, min(n - 1, int(math.ceil((x + RAY_MAX) / rw.DX))))
    F, C = list(co.F), list(co.C)
    for i in range(0, lo):
        F[i], C[i] = F[lo], C[lo]
    for i in range(hi + 1, n):
        F[i], C[i] = F[hi], C[hi]
    FH = [max(F[max(0, i - 2):i + 3]) for i in range(n)]
    CL = [min(C[max(0, i - 2):i + 3]) for i in range(n)]
    return {"F": F, "C": C, "FH": FH, "CL": CL}


# ---------------------------------------------------------------------------------------------- continuation
class RRCont:
    """Non-clairvoyant continuation: the rwL_fast flight / approach / descent laws (no rescue, no privileged corridor
    look-ahead, no safety filter; proportional collective law) fed by the seven rays cast in its own world at the
    current state and the next ship's deck state."""
    __slots__ = ("ad", "w", "mem")

    def __init__(self, ad, world: World, mem: dict | None = None):
        self.ad, self.w, self.mem = ad, world, dict(mem or {})

    def clone(self):
        return RRCont(self.ad, self.w, self.mem)

    def decide(self, s) -> dict:
        h = s.helis[0]
        if not h["alive"]:
            return {"collective": "hold", "cyclic": "center", "winch": "hold"}
        w, eng = self.w, self.ad.eng
        t, k = s.k * DT, s.t_ms // TICK_MS
        rc = w.rc(k)
        x, y, vx, vy = h["x"], h["y"], h["vx"], h["vy"]
        up, up45, f15u, fwd, f15d, dn45, dn = fast_rays(rc, x, y, t)
        co = w.course
        j = eng.next_ship(h)
        sh = co.ships[j]
        sx = sh[0]
        dky, dkv, _ = co.deck(j, t)
        deck_max = sh[1] + 1.4 * sh[2]
        dx = sx - x
        look = max(vx, 2.0) * 3.2
        hi, lo = y + up, y - dn
        if up45 < RAY_MAX and C45 * up45 <= look:
            hi = min(hi, y + C45 * up45)
        if f15u < RAY_MAX and C15 * f15u <= look:
            hi = min(hi, y + S15 * f15u)
        if dn45 < RAY_MAX and C45 * dn45 <= look:
            lo = max(lo, y - C45 * dn45)
        if f15d < RAY_MAX and C15 * f15d <= look:
            lo = max(lo, y - S15 * f15d)
        # the roof keeps coming down (clock-only rule, shown as 'roof -X m'): plan against its drop 3 s ahead
        hi -= (V.ramp_at(w.sched, k + 12).roof_mm - V.ramp_at(w.sched, k).roof_mm) / 1000
        if sx - 16.0 <= x + look and x - 16.0 <= sx:
            lo = max(lo, deck_max + 1.0)
        room = hi - lo
        pitch_lim = 15.0 if room > 14 else 10.0
        # rwL_fast laws (ramp2.1 planner rung): braking-limited transit, glide path, gliding approach, fast sink with
        # a flare, dwell 1.5 s on a new deck then a vertical lift-off
        d_eff = abs(dx) - STOP_DX - LEAD_S * abs(vx)
        vmax = min(V_MAX, V_ROOM0 + V_ROOM_K * max(0.0, room - ROOM0), math.sqrt(2 * BRAKE * max(0.0, d_eff)) + 1.0)
        if fwd < RAY_MAX:                               # something straight ahead: be able to stop before it
            vmax = min(vmax, math.sqrt(2 * BRAKE * max(0.0, fwd - 10.0)) + 1.0)
        vxd = max(-vmax, min(vmax, 0.35 * dx))
        winch = "hold"
        if abs(dx) < 45:                                # gliding approach toward a point just above the deck
            y_t = min(deck_max + SKID_H + 2.0 + GLIDE_APP * abs(dx), y + up - 4.0)
            vyd = max(-SINK_APP, min(2.5, 0.5 * (y_t - y)))
            if abs(dx) < FINAL_DX and abs(vx) < FINAL_VX:
                vyd = dkv - (SINK if y - SKID_H - dky > FLARE_GAP else FLARE)
            pitch_lim = min(pitch_lim, 8.0 if abs(dx) < 10 else 15.0)
        else:                                           # transit on a glide path toward the deck, inside the corridor
            glide = deck_max + SKID_H + 3.0 + GLIDE * abs(dx)
            a_lo, a_hi = lo + MARGIN_LO, hi - MARGIN_HI
            yc = min(max(glide, a_lo), a_hi) if a_lo <= a_hi else (lo + hi) / 2 + 0.5
            lim = 3.0 + 0.1 * abs(vx)
            vyd = max(-lim, min(lim, 0.45 * (yc - y)))
        if h["att"]:                                    # carry gently: reel in, small pitch, damp the swing
            winch = "up" if h["L"] > 5.5 else "hold"
            cap = 0.0 if h["L"] > 7.0 else 11.0
            vxd = max(-cap, min(cap, vxd)) + 3.0 * math.sin(h["phi"]) + 0.3 * h["L"] * h["phid"]
            pitch_lim = 6.0
        if h["landed"] >= 0:                            # on a deck: dwell, then lift off vertically
            t0 = self.mem.setdefault("land_t", s.t_ms)
            vyd, vxd = (0.0, 0.0) if s.t_ms - t0 < DWELL_MS else (2.0, 0.0)
            self.mem["climb_from"] = y
        else:
            self.mem.pop("land_t", None)
            if "climb_from" in self.mem:                # lift-off: climb 5 m clear of the deck before moving on
                if y - self.mem["climb_from"] < 5.0:
                    vyd, vxd = 2.0, 0.0
                else:
                    del self.mem["climb_from"]
        # collective: proportional on the collective itself (the option is a one-shot step, so a PD on vy would
        # integrate through the reply lag): c_target = hover collective * (1 + KP_V (vyd - vy) / g)
        r = h["Om"] / rw.OMEGA_N
        surf = rc.floor_at(x)
        if abs(dx) <= rw.SHIP_HALF and dky > surf:
            surf = dky
        hh = y + rw.HUB_H * math.cos(h["th"]) - surf
        ge = 1.0 + rw.GE_GAIN * math.exp(-hh / rw.R_ROTOR) if hh > 0 else 1.0 + rw.GE_GAIN
        m = rw.M_AIR + h["fuel"] + (rw.M_LOAD if h["att"] else 0.0)
        c_hov = m * rw.G / (rw.K_T * r * r * ge * max(math.cos(h["th"]), 0.8))
        a_cmd = max(-3.0, min(3.0, KP_V * (vyd - vy)))
        steps = max(-2, min(2, round((c_hov * (1 + a_cmd / rw.G) - h["c"]) / rw.C_STEP)))
        p_av = rw.P_AVAIL * V.ramp_at(w.sched, k).power_q / 1024
        if 100 * r < 96.0 or 100 * (p_av - h["Preq"]) / p_av < 3.0:
            steps = min(steps, 0)
        th_d = max(-pitch_lim, min(pitch_lim, KV * (vxd - vx)))
        return {"collective": COLL_BY_STEP[steps], "cyclic": LandingPlanner._cyclic_for(h, math.radians(th_d)),
                "winch": winch}


# ---------------------------------------------------------------------------------------------- adapter
def t_travel(D: float, v0: float, V_ref: float = V_CRUISE) -> float:
    """Bang-bang time to cover D >= 0 and stop, from speed v0 toward the target (negative = away), accel A_ACC, brake
    A_BRK, cruise V_ref (a faster current speed counts as V_ref)."""
    t = 0.0
    if v0 < 0:
        t += -v0 / A_BRK
        D += v0 * v0 / (2 * A_BRK)
        v0 = 0.0
    d_stop = v0 * v0 / (2 * A_BRK)
    if d_stop >= D:                                  # overshoot: brake, then come back (rest to rest)
        return t + v0 / A_BRK + 2 * math.sqrt((d_stop - D) / A_BRK)
    v0 = min(v0, V_ref)                              # speed beyond the reference cruise buys nothing (and see S_env)
    Vc = V_ref
    vp = math.sqrt((2 * A_ACC * A_BRK * D + A_BRK * v0 * v0) / (A_ACC + A_BRK))
    if vp <= Vc:
        return t + (vp - v0) / A_ACC + vp / A_BRK
    d_acc = (Vc * Vc - v0 * v0) / (2 * A_ACC)
    d_dec = Vc * Vc / (2 * A_BRK)
    return t + (Vc - v0) / A_ACC + Vc / A_BRK + (D - d_acc - d_dec) / Vc


class RRAdapter:
    SEED_GAME = "rotorwash_ramp"
    GAME_ID = V.GAME_ID
    CONTROLS = ("collective", "cyclic", "winch")
    OPTIONS = {"collective": rw.COLL_OPTS, "cyclic": rw.CYC_OPTS, "winch": rw.WINCH_OPTS}
    TEMPERATURE = KAPPA_DEV          # 0.004 K3 points = the trust-region margin (RR_LABELS.md §4)
    MAX_TICKS = 16

    def __init__(self, version: str = V.RULES_VERSION, max_ticks: int | None = None, truth=None):
        self.VERSION = version
        if max_ticks is not None:
            self.MAX_TICKS = max_ticks
        self.game = self._make_game(1)
        self.eng = self.game.engine
        self.sched = self.eng.sched
        self.cap_ms = self.game.max_round_ms
        if version == V.RULES_VERSION:                # the registered live binding (arena.v3.games)
            from nagi.burst2._rt.arena.v3.games import FACTORIES
            self.binding = FACTORIES[self.GAME_ID]()
        else:
            self.binding = V.v31_binding(version)
        assert tuple(self.binding.controls) == self.CONTROLS
        assert all(getattr(rw, k) == v for k, v in RR.DEFAULTS.items()), "rotorwash constants are patched"
        self.truth = truth or build_course          # seed -> the true Course (tests swap it for hidden-future checks)
        self._pert = None
        self._start_pts: dict = {}                  # seed -> S + D at the last start_state (episode_outcome)

    def _make_game(self, n_players: int):
        if "rules_version" in inspect.signature(V.RampGame31).parameters:
            return V.RampGame31(n_players=n_players, rules_version=self.VERSION)
        if self.VERSION != V.RULES_VERSION:
            raise ValueError(f"rules version {self.VERSION} not available (module has {V.RULES_VERSION})")
        return V.RampGame31(n_players=n_players)

    # ------------------------------------------------------------------ generator side
    def real_game(self):
        return self.game

    def served_game(self):
        return self.binding.make()

    @staticmethod
    def project(s):
        """Seat 0 of a served (4-seat, ghost ladder) state: the ghosts never interact (DAgger replay -> labels)."""
        import dataclasses as _dc
        return _dc.replace(s, helis=[s.helis[0]])

    def reset(self, seed: int):
        return self.game.reset(seed)

    def done(self, s) -> bool:
        return self.game.done(s)

    def parts(self, h: dict) -> dict:
        return V.k3_parts(h)

    def y(self, h: dict) -> float:
        return self.parts(h)["k3"]

    def k3(self, s) -> float:
        return self.y(s.helis[0])

    # ------------------------------------------------------------------ qengine protocol
    def _winch_free(self, s) -> bool:
        h = s.helis[0]
        if h["att"]:
            return False
        sxv = self.truth(s.seed).surv[h["leg"]][0]          # displayed: survivor dx
        T = self.MAX_TICKS * TICK_MS / 1000
        reach = rw.HOOK_DX + abs(h["vx"]) * T + 0.5 * 6.0 * T * T + 2.0
        return abs(sxv - h["x"]) > reach

    def worlds(self, s, key: str, n: int, cheat: bool) -> list[World]:
        co = self.truth(s.seed)
        free = self._winch_free(s)
        if cheat:
            return [self._anchor(World(co, "true", free, self.sched), s)]
        h = s.helis[0]
        obs = parse_obs(self.eng.observation(s, 0))
        x, y = h["x"], h["y"]
        t = s.k * DT
        win = _window(co, x)
        # implied unit gust at the displayed wind (the last substep of the previous tick)
        i = min(max(int(x * 0.2), 1), co.n - 3)
        k_prev = max(s.t_ms // TICK_MS - 1, 0)
        gain = V.ramp_at(self.sched, k_prev).gust_q / 1024 if s.k > 0 else 1.0
        m0 = max(s.k - 1, 0)
        n_sub = (self.MAX_TICKS + 3) * SUB
        nG = len(co.GX)
        j = obs["ship"]
        out = []
        for b in range(n):
            r = _h(f"bv2-rr-world|{key}|{b}")
            wx = obs["wind"][0] + r.uniform(-0.05, 0.05)
            wy = obs["wind"][1] + r.uniform(-0.05, 0.05)
            shear = co.SHA[i] * gain * math.tanh((y - co.SHY[i]) * 0.2) if co.SHA[i] else 0.0
            gx0 = (wx - co.WMX[i] - shear) / (co.GSX[i] * gain)
            gy0 = (wy - co.DD[i] * gain) / (co.GSY[i] * gain)
            px, py = _ou_path(r, gx0, n_sub), _ou_path(r, gy0, n_sub)
            GX = [gx0] * m0 + px + [px[-1]] * max(0, nG - m0 - n_sub)
            GY = [gy0] * m0 + py + [py[-1]] * max(0, nG - m0 - n_sub)
            ships = list(co.ships)
            ships[j] = _deck_posterior(r, j, t, y + obs["ship_dy"], obs["ship_vy"], co.ships[j][0])
            if h["landed"] >= 0 and h["landed"] != j:
                L = h["landed"]
                ships[L] = _deck_posterior(r, L, t, round(y - SKID_H, 1), round(h["vy"], 1), co.ships[L][0])
            wco = dataclasses.replace(co, GX=GX[:nG], GY=GY[:nG], ships=tuple(ships), **win)
            out.append(self._anchor(World(wco, f"b{b}", free, self.sched), s))
        return out

    def _anchor(self, w: World, s) -> World:
        a = RRCont(self, w).decide(s)
        w.base, w.s0 = tuple(a[c] for c in self.CONTROLS), s
        return w

    def step(self, world: World, s, acts: dict):
        a = (acts.get("collective", "hold"), acts.get("cyclic", "center"),
             "hold" if world.winch_free else acts.get("winch", "hold"))
        memo = not (s is world.s0 and s is not world.root)
        key = (id(s), a)
        hit = world.memo.get(key) if memo else None
        if hit is not None:
            return hit[1]
        h = dict(s.helis[0])
        if h["alive"] and not s.ended:
            ca = a[0] if a[0] in rw.COLL else "hold"
            cy = a[1] if a[1] in rw.CYCLIC else "center"
            wi = a[2] if a[2] in rw.WINCH else "hold"
            if rw.COLL[ca]:
                h["c"] = min(1.0, max(0.0, round(h["c"] + rw.C_STEP * rw.COLL[ca], 4)))
            h["u"] = rw.CYCLIC[cy]
            h["Ld"] = rw.WINCH[wi]
            h["last"] = (ca, cy, wi)
            self.eng._integrate31(h, world.course, s.k, SUB, [], 0, V.ramp_at(self.sched, s.t_ms // TICK_MS))
        dev = s.extra.get("dev", 0)
        if s is world.root and world.base is not None:      # the labelled joint: count slots off the anchor
            dev += sum(1 for i, c in enumerate(self.CONTROLS)
                       if a[i] != world.base[i] and not (c == "winch" and world.winch_free))
        s2 = RWState(seed=s.seed, k=s.k + SUB, t_ms=s.t_ms + TICK_MS, helis=[h],
                     ended=s.ended or not h["alive"] or s.t_ms + TICK_MS >= self.cap_ms, extra={"dev": dev})
        if memo:
            world.memo[key] = (s, s2)                   # keeps s alive: ids stay unique while the memo lives
        return s2

    def _score_events(self, h: dict) -> int:
        return len(h["ships_landed"]) + int(h["deliveries"])

    def value(self, world: World, s0, s) -> float | None:
        h, h0 = s.helis[0], s0.helis[0]
        dy = self.y(h) - self.y(h0) - KAPPA_DEV * s.extra.get("dev", 0)
        if not h["alive"]:
            return dy
        n_new = self._score_events(h) - self._score_events(h0)
        if n_new > 0:                                   # points leave round time for more points (Booster FUTURE)
            return dy + n_new * FUTURE * max(0, self.cap_ms - s.t_ms) / self.cap_ms + self.potential(world, s)
        if s.t_ms >= self.cap_ms:
            return dy
        return None

    def horizon_value(self, world: World, s0, s) -> float:
        return (self.y(s.helis[0]) - self.y(s0.helis[0]) - KAPPA_DEV * s.extra.get("dev", 0)
                + self.potential(world, s))

    def continuation(self, world: World, s, key: str) -> RRCont:
        world.root = s                                  # qengine applies every labelled joint at this state next
        return RRCont(self, world)

    def base_action(self, worlds: list[World], s, cont_factory, key: str) -> dict:
        """Tie rule base policy (labels.canonical_base): the continuation's own answer at s in the first world, so an
        exactly tied slot (e.g. the winch while it provably cannot matter) is labelled with what the controller does
        ('hold') instead of the first option in declared order ('up')."""
        return dict(zip(self.CONTROLS, worlds[0].base))

    # ------------------------------------------------------------------ terminal potential
    def potential(self, world: World, s, parts: bool = False):
        h = s.helis[0]
        if not h["alive"] or s.t_ms >= self.cap_ms:
            return {"phi": 0.0} if parts else 0.0
        co = world.course
        j = self.eng.next_ship(h)
        p = self.parts(h)
        n_pts = (0.0 if j in h["ships_landed"] else 1.0) + (1.0 if h["att"] else 0.0)
        G = n_pts - (p.get("approach", 0.0) or 0.0)
        if n_pts <= 0:
            return {"phi": 0.0, "G": G} if parts else 0.0
        t = s.k * DT
        sh = co.ships[j]
        dx = sh[0] - h["x"]
        sgn = 1.0 if dx >= 0 else -1.0
        T_h = t_travel(abs(dx), sgn * h["vx"])
        dky, dkv, _ = co.deck(j, t)
        e = max(0.0, h["y"] - SKID_H - dky)
        # the fast descent to E_DESC above the deck overlaps the transit; the final E_DESC m come after it
        T_go = max(T_h, max(0.0, e - E_DESC) / V_DESC_FAST) + min(e, E_DESC) / V_DESC
        T_v = T_go - T_h
        T_left = (self.cap_ms - s.t_ms) / 1000
        f_cap = min(1.0, max(0.0, (T_left - T_go) / 4.0 + 0.5))
        G += n_pts * FUTURE * max(0.0, T_left - T_go) / (self.cap_ms / 1000)   # time left after that landing
        # vertical closing-speed safety at the end state
        rc = world.rc(s.t_ms // TICK_MS)
        x, y, vy = h["x"], h["y"], h["vy"]
        s_up = s_dn = 1.0
        if h["landed"] < 0:
            if vy > 0:
                d_up = max(0.1, rc.ceil_at(x) - y - 2.0)
                s_up = min(1.0, max(0.0, 2.0 - vy * vy / (2 * d_up) / A_OK_UP))
            surf, v_ok, v_rel = co.floor_at(x), 0.0, -vy
            for jj, shp in enumerate(co.ships):
                if abs(x - shp[0]) <= rw.SHIP_HALF:
                    yy, vv, _ = co.deck(jj, t)
                    if yy > surf:
                        surf, v_ok, v_rel = yy, V_TD, vv - vy
                    break
            if v_rel > v_ok:
                d_dn = max(0.1, y - SKID_H - surf)
                s_dn = min(1.0, max(0.0, 2.0 - (v_rel * v_rel - v_ok * v_ok) / (2 * d_dn) / A_OK_DN))
            if abs(h["vx"]) < 4.0 and -vy > V_SINK_OK:  # slow and sinking fast: vortex ring onset (0.6 v_h ~ 5 m/s)
                s_dn *= min(1.0, max(0.0, (V_SINK_BAD + vy) / (V_SINK_BAD - V_SINK_OK)))
        # flight envelope: speed, vertical speed, pitch beyond what the continuation can still recover from
        s_env = 1.0
        for v, (ok, bad) in zip((abs(h["vx"]), abs(vy), abs(math.degrees(h["th"]))), ENV):
            if v > ok:
                s_env *= max(0.0, (bad - v) / (bad - ok))
        phi = G * math.exp(-LAM * T_go) * f_cap * s_up * s_dn * s_env
        if parts:
            return {"phi": phi, "G": G, "T_h": T_h, "T_v": T_v, "f_cap": f_cap, "s_up": s_up, "s_dn": s_dn,
                    "s_env": s_env}
        return phi

    # ------------------------------------------------------------------ generator: starts and perturbations
    def plan_start(self, r: random.Random) -> dict:
        """Start tick of an episode: uniform over the first half of the round (0-30 s under ramp2.1), i.e. before the
        reference flight's typical first landing (~32 s): episodes cover cruise, approach and the landing, the
        audit's failure regime, and the episode sanity (a point scored during the episode) stays meaningful;
        post-landing states still appear within an episode (up to max_rows requests)."""
        return {"tick": r.randrange(0, max(1, self.cap_ms // TICK_MS // 2))}

    def start_state(self, seed: int, start: dict):
        """The state at start['tick'] of the reference flight (the continuation controller on the true course through
        a 1-tick reply lag: a cruise / altitude-hold / landing flight). If it crashes first: 12 ticks before the
        crash."""
        s = self.game.reset(seed)
        w = World(self.truth(seed), "true", False, self.sched)
        cont = RRCont(self, w)
        hist, acts = [s], {}
        for _ in range(int(start.get("tick", 0))):
            nxt = cont.decide(s)
            s = self.step(w, s, acts)
            w.memo.clear()
            acts = nxt
            if not s.helis[0]["alive"]:
                s = hist[max(0, len(hist) - 12)]
                break
            hist.append(s)
            if self.game.done(s):
                break
        s = RWState(seed=s.seed, k=s.k, t_ms=s.t_ms, helis=[dict(s.helis[0])], ended=s.ended)
        self._start_pts[seed] = len(s.helis[0]["ships_landed"]) + int(s.helis[0]["deliveries"])
        return s

    def episode_outcome(self, s, hop0=None) -> dict:
        """generate / validate outcome record. 'hop_landed' = a point (landing or delivery) was scored DURING the
        episode: S + D at the end > S + D at the episode's start state (start_state records it per seed)."""
        h = s.helis[0]
        p = self.parts(h)
        pts0 = self._start_pts.get(s.seed, 0)
        return {"hop_landed": p["ships"] + p["deliveries"] > pts0, "points_at_start": pts0, "k3": p["k3"], "ships": p["ships"],
                "deliveries": p["deliveries"], "t_end_ms": s.t_ms, "cause": h["cause"], "status":
                "crashed" if not h["alive"] else "flying"}

    def reference_outcome(self, ep: dict, bot: str = "rwL_fast", max_ticks: int | None = None) -> dict:
        """Privileged reference from the same start (generate.py sanity): rwL_fast (the ramp2.1 planner rung) through arena.v3.delay.Delayed
        at delay 1 in the 1-seat game, to the end of the round (or max_ticks / ep['ref_ticks'] ticks)."""
        max_ticks = max_ticks or ep.get("ref_ticks")
        from nagi.burst2._rt.arena.games.rotorwash_ramp_v31_bots import make_bot
        from nagi.burst2._rt.arena.v3.delay import Delayed
        g = self.game
        s = self.start_state(ep["seed"], ep.get("start", {"tick": 0}))
        me = Delayed(make_bot(bot), self.binding, 1).bind(0, ep["seed"])
        n = 0
        with g.ctx():
            while not g.done(s) and (max_ticks is None or n < max_ticks):
                me.see(g, s)
                s, _ = g.step(s, {0: dict(me.acts)}, TICK_MS)
                n += 1
        return dict(self.episode_outcome(s), bot=bot)

    PERTURB = (("slow_cruise", 0.35), ("creep_up", 0.30), ("aft_brake", 0.15), ("sink", 0.10), ("fwd_rush", 0.10))

    def perturb_script(self, r: random.Random, s) -> dict:
        """A Burst-like episode starting now (coordinator audit rr_audit.json / rr_takeover_d2.json: Burst cruises at
        7-8 m/s with the cyclic mostly centred, and its collective creeps up into the roof 2-4 s before the crash).
        Returns {'kind', 'ticks', 'act'}: the joint to answer for `ticks` requests (collective one_shot: 'up1' every
        request = a creeping collective)."""
        u, acc, kind = r.random(), 0.0, self.PERTURB[-1][0]
        for kd, p in self.PERTURB:
            acc += p
            if u < acc:
                kind = kd
                break
        act = {"slow_cruise": {"collective": "hold", "cyclic": r.choice(("center", "aft1", "center")), "winch": "hold"},
               "creep_up": {"collective": "up1", "cyclic": r.choice(("center", "fwd1")), "winch": "hold"},
               "aft_brake": {"collective": "hold", "cyclic": r.choice(("aft1", "aft2")), "winch": "hold"},
               "sink": {"collective": "down1", "cyclic": "center", "winch": "hold"},
               "fwd_rush": {"collective": "hold", "cyclic": "fwd2", "winch": "hold"}}[kind]
        ticks = {"slow_cruise": (4, 16), "creep_up": (2, 6), "aft_brake": (2, 6), "sink": (2, 4),
                 "fwd_rush": (2, 8)}[kind]
        return {"kind": kind, "ticks": r.randint(*ticks), "act": act}

    def perturb(self, rng: random.Random, s, k: int, p_start: float = 0.04) -> dict | None:
        """Stateful per-request wrapper: None (let the planner answer) or the scripted joint of a running episode;
        a new episode starts with probability p_start per request."""
        if self._pert is not None and self._pert["left"] > 0:
            self._pert["left"] -= 1
            return dict(self._pert["act"])
        self._pert = None
        if rng.random() < p_start:
            sc = self.perturb_script(rng, s)
            self._pert = dict(sc, left=sc["ticks"] - 1)
            return dict(sc["act"])
        return None


# ---------------------------------------------------------------------------------------------- measurement (§5)
def play(ad: RRAdapter, seed: int, policy_kind: str, B: int = 4, profile: str = "single_stream", diag_every: int = 0,
         max_ticks: int | None = None, log=None) -> dict:
    """One round of seat 0 in the 1-seat game. policy_kind: 'obs' / 'cheat' (the label planner through the latency
    emulator), 'cont' (the continuation controller alone, same emulator), 'rwL_planner' / 'rwH_lander' (arena ladder
    bots through arena.v3.delay.Delayed at delay 1)."""
    from nagi.burst2._rt.burst_v2 import latency as LT
    from nagi.burst2._rt.burst_v2 import qengine as QE
    game = ad.real_game()
    s = ad.reset(seed)
    key = f"rr-eval|{seed}|{policy_kind}"
    t_lab, diags, n = [], [], [0]
    if policy_kind.startswith(("rwL_", "rwH_", "rwN_")):
        from nagi.burst2._rt.arena.games.rotorwash_ramp_v31_bots import make_bot
        from nagi.burst2._rt.arena.v3.delay import Delayed
        me = Delayed(make_bot(policy_kind), ad.binding, 1).bind(0, seed)
        with game.ctx():
            while not game.done(s):
                me.see(game, s)
                s, _ = game.step(s, {0: dict(me.acts)}, TICK_MS)
    else:
        p_hat, mk = LT.profile(profile, ad.SEED_GAME)
        emu = LT.Emulator(ad.binding, p_hat, key, markov=mk)
        if policy_kind == "cont":
            w = World(ad.truth(seed), "true", False, ad.sched)
            cont = RRCont(ad, w)

            def policy(state, p_log, k):
                return cont.decide(state)
        else:
            lp = QE.LabelPlanner(ad, p_hat, 1 if policy_kind == "cheat" else B, policy_kind == "cheat", mk, key=key)

            def policy(state, p_log, k):
                t0 = time.perf_counter()
                lab = lp.label(state, p_log, f"k{k}")
                t_lab.append(time.perf_counter() - t0)
                if diag_every and n[0] % diag_every == 0:
                    diags.append(diagnose(ad, state, p_log, f"{key}|k{k}", lab, p_hat, mk))
                n[0] += 1
                if log and n[0] % 40 == 0:
                    log(f"{policy_kind} seed {seed} req {n[0]} t={state.t_ms / 1000:.1f}s x={state.helis[0]['x']:.0f}"
                        f" k3={ad.k3(state):g} {sum(t_lab) / len(t_lab):.2f} s/label")
                return lab["answers"]
        with game.ctx():
            while not game.done(s) and (max_ticks is None or s.t_ms // TICK_MS < max_ticks):
                acts = emu.tick(game, s, policy)
                s, _ = game.step(s, {0: acts}, TICK_MS)
    h = s.helis[0]
    p = ad.parts(h)
    return {"seed": seed, "policy": policy_kind, "k3": p["k3"], "ships": p["ships"], "deliveries": p["deliveries"],
            "partial": p.get("partial"), "cause": h["cause"], "t_end": s.t_ms / 1000, "x": round(h["x"], 1),
            "t_first_land": h.get("t_first_land"), "labels": len(t_lab),
            "s_per_label": (sum(t_lab) / len(t_lab)) if t_lab else None, "diag": diags}


def diagnose(ad, state, p_log: dict, key: str, lab: dict, p_hat: dict, mk) -> dict:
    """§5 disagreement record of one request: max-marginals of the obs-limited latency-aware Q-bar, the cheating
    latency-aware Q-bar and the cheating lag-free (d = 0) Q, joint acceptable-set disjointness, gap / MC error."""
    from nagi.burst2._rt.burst_v2 import qengine as QE
    cw = ad.worlds(state, key, 1, True)
    q_ch = L.qbar(QE.q_table(ad, state, p_log, f"{key}|cheat", 1, p_hat, cheat=True, markov=mk, worlds=cw), p_hat)
    cw = ad.worlds(state, key, 1, True)
    q_lf = L.qbar(QE.q_table(ad, state, p_log, f"{key}|lagfree", 1, {0: 1.0}, cheat=True, markov=None, worlds=cw),
                  {0: 1.0})

    def mm(q):
        return [[round(max(v for a, v in q.items() if a[k] == o), 7) for o in ad.OPTIONS[c]]
                for k, c in enumerate(ad.CONTROLS)]
    return {"t": state.t_ms / 1000, "x": round(state.helis[0]["x"], 1), "vx": round(state.helis[0]["vx"], 2),
            "obs": mm(lab["q"]), "cheat": mm(q_ch), "lagfree": mm(q_lf),
            "disjoint_cheat": L.argmax_disagree(lab["q"], q_ch), "disjoint_lagfree": L.argmax_disagree(lab["q"], q_lf),
            "a_star": list(lab["joint"]), "regret_cheat": round(max(q_ch.values()) - q_ch[lab["joint"]], 7),
            "regret_lagfree": round(max(q_lf.values()) - q_lf[lab["joint"]], 7),
            "gap_se": slot_gap_se(ad, lab, p_hat)}


def slot_gap_se(ad, lab: dict, p_hat: dict) -> list:
    """Per control: (gap between the best and second-best max-marginal, its Monte-Carlo standard error over the B
    worlds = std of the per-world P-hat-weighted Q difference of the two joints attaining them / sqrt(B))."""
    q, qd = lab["q"], lab["q_by_d"]
    B = len(qd[min(qd)])
    out = []
    for k, c in enumerate(ad.CONTROLS):
        best = {}
        for a, v in q.items():
            if a[k] not in best or v > q[best[a[k]]]:
                best[a[k]] = a
        ranked = sorted(best.values(), key=lambda a: -q[a])
        if len(ranked) < 2:
            out.append(None)
            continue
        a1, a2 = ranked[0], ranked[1]
        diffs = [math.fsum(p_hat[d] * (qd[d][b][a1] - qd[d][b][a2]) for d in p_hat) for b in range(B)]
        mu = math.fsum(diffs) / B
        se = math.sqrt(math.fsum((x - mu) ** 2 for x in diffs) / max(1, B - 1) / B) if B > 1 else None
        out.append([round(q[a1] - q[a2], 7), None if se is None else round(se, 7)])
    return out


def main(argv=None):
    import argparse
    import sys
    from nagi.burst2._rt.burst_v2 import seeds as SE
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--policies", default="rwL_fast,rwH_quick,rwL_fastrescue,cont,cheat,obs")
    ap.add_argument("--B", type=int, default=4)
    ap.add_argument("--diag-every", type=int, default=4)
    ap.add_argument("--version", default=V.RULES_VERSION)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    ad = RRAdapter(a.version)
    res = []

    def log(m):
        print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)
    for idx, seed in SE.train_seeds(ad.SEED_GAME, a.seeds, a.start):
        for pk in a.policies.split(","):
            t0 = time.perf_counter()
            r = play(ad, seed, pk, a.B, diag_every=a.diag_every if pk == "obs" else 0, log=log)
            r["train_index"], r["wall_s"] = idx, time.perf_counter() - t0
            res.append(r)
            log(f"{pk} seed#{idx}: k3={r['k3']:g} cause={r['cause']} t={r['t_end']} x={r['x']} "
                f"({r['wall_s']:.0f} s)")
            with open(a.out, "w") as f:
                json.dump({"version": a.version, "B": a.B, "results": res, "argv": sys.argv}, f)


if __name__ == "__main__":
    main()
