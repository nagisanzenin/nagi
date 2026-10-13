"""Stronger RR teacher (docs/v2_teachers/SPEC.md, lane rr): an observation-limited, latency-aware Rotorwash-Ramp v3.1
(ramp2.1) planner whose labels plug into burst_v2.labels / generate / validate. The existing LabelPlanner and RRAdapter
are not modified; this module only reads them.

OBSERVATION LIMIT (SPEC constraint 1). Every decision is a function of (the served prompt text at the request tick,
p_log = the runner's pending controls = the model's own previous reply). The prompt shows no history, so there is no
belief update across ticks. `obs_belief` parses the prompt and builds a belief world from it alone:
  * heli state: the displayed values (vx, vy, pitch, rate 0.1; RPM 0.1 %; collective % (exact: the 0.05 grid);
    cyclic; fuel %; rope, load angle / rate; hook timer); power from the margin. The engine's own x / y are used only
    as the frame origin: every belief object is placed RELATIVE to them from displayed quantities.
  * terrain: ONLY the seven displayed rays. Ceiling = piecewise-linear through the end points of the up / up45 /
    fwd15up rays, floor = through down / dn45 / fwd15dn (a clear ray's end point is used as a bound: the lowest
    ceiling / highest floor consistent with it); the fwd ray's hit goes to the floor when a passage shows above it
    (fwd15up reaches further), to the ceiling when below, else to both (a wall). Flat beyond the last point. The roof
    keeps dropping by the rules' clock-only schedule (prompt: t and the current drop).
  * next ship: x = displayed dx, deck = displayed dy / vy, heave law = the course generator's prior conditioned on
    them (rr._deck_posterior; mean world = phase-solved first harmonic, second/third harmonics zero).
  * wind: the displayed wind held, plus (sampled worlds only) a unit OU gust (tau 2.5 s) from 0, scaled by the
    generator's gust scale at the leg inferred from the displayed ship number and dx.
Residual leaks (disclosed in docs/v2_teachers/rr.md): the engine's roof floor (rotorwash_ramp.gap_min, rule
constants 12 m above floor / deck, keyed by the true course's bay cells), the hidden RPM-stall and engine-lag
timers, the landed-ship index while LANDED (inferable from the ship number), and score bookkeeping.
`test_rr_teacher.py::test_decision_is_prompt_function` checks that two different true states rendering the same prompt
(and p_log) give identical decisions and identical Q.

CONTROLLER (base policy). The rwL_fast laws (arena.games.rotorwash_ramp_v31_planner.FastPlanner, the ramp2.1
privileged planner rung that lands 16/16 dev seeds) re-fed from the belief: corridor look-ahead on the belief cave,
deck from the prompt, PD collective law whose derivative term is the belief model's predicted acceleration (no
memory). Latency-aware: it plans from the belief-predicted state where its reply lands (p_log for one tick, then the
runner's hold rules; d = 1, the mode of P-hat), and a safety filter vetoes (collective [, cyclic]) choices that crash
within SAFETY_TICKS in the belief world for either delay d in {1, 2}.

LABELS (Q per joint -> targets). qengine.q_table over B belief worlds (sampled gusts and heave), continuation = the
controller without the safety filter, terminal value = rr.RRAdapter's K3 + potential (unchanged). a* = the tie rule
with the controller's own answer as the base and TIE_TOL as the margin (deviate only for a resolved gain).
"""
from __future__ import annotations

import dataclasses
import hashlib
import math
import random
import re

from nagi.burst2._rt.arena.games import rotorwash as rw
from nagi.burst2._rt.arena.games import rotorwash_ramp_v31 as V
from nagi.burst2._rt.arena.games.rotorwash import DT, RAY_MAX, SKID_H, RWState
from nagi.burst2._rt.arena.games.rotorwash_ramp_bots import COLL_STEPS, CYC_U
from nagi.burst2._rt.arena.games.rotorwash_ramp_v31_planner import LandingPlanner
from nagi.burst2._rt.burst_v2 import labels as L
from nagi.burst2._rt.burst_v2 import qengine as QE
from nagi.burst2._rt.burst_v2 import rr as R

TICK_MS = R.TICK_MS
SUB = R.SUB
C45, C15, S15 = R.C45, R.C15, R.S15
COLL_ORDER = [c for c, _ in COLL_STEPS]
CYC_ORDER = [c for c, _ in CYC_U]

# ------------------------------------------------------------------------------------------------ prompt parsing
_NUM = r"([-+]?\d+(?:\.\d+)?)"
RX = {
    "state": re.compile(r"STATE t=" + _NUM + r"s of (\d+); POINTS " + _NUM + r"; roof -" + _NUM + r" m; gusts x" + _NUM
                        + r"; power " + _NUM + "%"),
    "heli": re.compile(r"fuel " + _NUM + r"%(, LANDED)?; altitude AGL " + _NUM + r" m; vx " + _NUM + r" m/s; vy " + _NUM
                       + r" m/s; pitch " + _NUM + r" deg, rate " + _NUM + r" deg/s"),
    "rotor": re.compile(r"rotor RPM " + _NUM + r"%; collective " + _NUM + r"%; cyclic " + _NUM + r"; power margin "
                        + _NUM + r"%; wind " + _NUM + "," + _NUM + r" m/s"),
    "rays": re.compile(r"up " + _NUM + r", up45 " + _NUM + r", fwd15up " + _NUM + r", fwd " + _NUM + r", fwd15dn " + _NUM
                       + r", dn45 " + _NUM + r", down " + _NUM),
    "ship": re.compile(r"next ship (\d+): deck dx " + _NUM + r" m, dy " + _NUM + r" m, vy " + _NUM + r" m/s"),
    "load": re.compile(r"load HOOKED; rope " + _NUM + r" m; load angle " + _NUM + r" deg, rate " + _NUM + r" deg/s"),
    "surv": re.compile(r"survivor: dx " + _NUM + r" m, dy " + _NUM + r" m; hook timer " + _NUM + r"/1\.5 s; rope " + _NUM
                       + r" m"),
}


def parse_prompt(text: str) -> dict:
    g = {k: rx.search(text) for k, rx in RX.items()}
    for k in ("state", "heli", "rotor", "rays", "ship"):
        if g[k] is None:
            raise ValueError(f"prompt line '{k}' not found")
    st, he, ro, ra, sh = (g[k].groups() for k in ("state", "heli", "rotor", "rays", "ship"))
    o = {"t": float(st[0]), "points": float(st[2]), "roof": float(st[3]), "gust_gain": float(st[4]),
         "power_pct": float(st[5]), "fuel": float(he[0]), "landed": he[1] is not None, "agl": float(he[2]),
         "vx": float(he[3]), "vy": float(he[4]), "pitch": float(he[5]), "rate": float(he[6]), "rpm": float(ro[0]),
         "coll": float(ro[1]), "cyc": float(ro[2]), "margin": float(ro[3]), "wind": (float(ro[4]), float(ro[5])),
         "rays": [float(v) for v in ra], "ship": int(sh[0]) - 1, "ship_dx": float(sh[1]), "ship_dy": float(sh[2]),
         "ship_vy": float(sh[3]), "hooked": g["load"] is not None}
    if g["load"] is not None:
        rope, ang, rate = (float(v) for v in g["load"].groups())
        o.update(rope=rope, load_angle=ang, load_rate=rate, hook_t=0.0)
    else:
        sdx, sdy, ht, rope = (float(v) for v in g["surv"].groups())
        o.update(rope=rope, load_angle=0.0, load_rate=0.0, hook_t=ht, surv_dx=sdx, surv_dy=sdy)
    return o


# ------------------------------------------------------------------------------------------------ belief world
def display_heli(h: dict, o: dict, p_av: float) -> dict:
    """The heli as the prompt shows it: every displayed dynamic quantity replaced by its displayed value. x / y stay as
    the frame origin (the belief world is built relative to them). Bookkeeping fields (legs, ships landed, score)
    are consequences of the displayed POINTS / ship number and are kept."""
    b = dict(h)
    b.update(vx=o["vx"], vy=o["vy"], th=math.radians(o["pitch"]), w=math.radians(o["rate"]),
             Om=o["rpm"] / 100 * rw.OMEGA_N, c=round(o["coll"] / 100 / rw.C_STEP) * rw.C_STEP, u=o["cyc"],
             fuel=o["fuel"] / 100 * rw.M_FUEL0, L=o["rope"], phi=math.radians(o["load_angle"]),
             phid=math.radians(o["load_rate"]), hover_t=o["hook_t"], wx=o["wind"][0], wy=o["wind"][1])
    preq = p_av * (1 - o["margin"] / 100)
    b["Preq"] = b["Pe"] = preq
    return b


def _interp(pts: list, xq: float) -> float:
    if xq <= pts[0][0]:
        return pts[0][1]
    for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
        if xq <= xb:
            return ya + (yb - ya) * (xq - xa) / (xb - xa) if xb > xa else min(ya, yb)
    return pts[-1][1]


def ray_terrain(o: dict, x: float, y: float, extrap: float = 0.0) -> tuple[list, list]:
    """(ceiling points, floor points) as (x, y) lists sorted by x, from the seven displayed rays only (see module
    docstring). A ray's end point is a hit (< 80 m) or the bound a clear ray implies."""
    up, up45, f15u, fwd, f15d, dn45, dn = o["rays"]
    ceil = [(x, y + up), (x + C45 * up45, y + C45 * up45), (x + C15 * f15u, y + S15 * f15u)]
    flo = [(x, y - dn), (x + C45 * dn45, y - C45 * dn45), (x + C15 * f15d, y - S15 * f15d)]
    if fwd < RAY_MAX - 0.05:
        p = (x + fwd, y)
        above = C15 * f15u > fwd + 0.5
        below = C15 * f15d > fwd + 0.5
        if above and not below:
            flo.append(p)
        elif below and not above:
            ceil.append(p)
        elif above and below:                       # a thin obstacle: the nearer interpolated surface owns it
            (ceil if _interp(sorted(ceil), p[0]) - y < y - _interp(sorted(flo), p[0]) else flo).append(p)
        else:
            ceil.append((p[0], y + 0.5))
            flo.append((p[0], y - 0.5))
    ceil.sort()
    flo.sort()
    if extrap:                                      # a descending roof / rising floor keeps its last slope
        for pts, sgn in ((ceil, -1.0), (flo, 1.0)):
            if len(pts) >= 2 and pts[-1][0] - pts[-2][0] > 1.0:
                sl = (pts[-1][1] - pts[-2][1]) / (pts[-1][0] - pts[-2][0])
                sl = sgn * min(max(sgn * sl, 0.0), extrap)
                pts.append((pts[-1][0] + 60.0, pts[-1][1] + 60.0 * sl))
    return ceil, flo


def _gust_scale(o: dict) -> tuple[float, float]:
    """build_course's gust scales at the leg inferred from the prompt: ship j sits at j*LEG_LEN + 435 +- 8 m."""
    xe = o["ship"] * rw.LEG_LEN + 435.0 - o["ship_dx"]
    d = min(max(xe, 0.0) / rw.LEG_LEN, 7.0)
    return min(1.0 + d, 6.0), min(0.4 + 0.35 * d, 2.5)


def _mean_deck(j: int, t: float, y_obs: float, vy_obs: float, x: float) -> tuple:
    """The deck tuple whose first harmonic matches the displayed height / speed with the prior's mean period and zero
    secondary harmonics (the mean belief world)."""
    a1 = min(0.5 + 0.6 * j, 3.5)
    w1 = 2 * math.pi / max(7.0 - 0.3 * j, 5.0)
    c = max(-0.999, min(0.999, vy_obs / (a1 * w1)))
    ph = math.acos(c)                                # first harmonic phase at t (the branch above the base)
    p1 = ph - w1 * t
    return (x, y_obs - a1 * math.sin(ph), a1, w1, p1, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0)


class Belief:
    """One belief world (a rotorwash Course built from the prompt) + the belief heli state."""

    def __init__(self, ad, s, p_log: dict | None, n: int, mean_first: bool = True, text: str | None = None,
                 extrap: float = 0.0, decay: bool = False):
        self.ad = ad
        eng = ad.eng
        h = s.helis[0]
        text = eng.observation(s, 0) if text is None else text
        # the world RNG is keyed by what the model sees (prompt) and its own pending reply only
        key = self.key = hashlib.sha256((text + "|" + repr(sorted((p_log or {}).items()))).encode()).hexdigest()
        o = self.o = parse_prompt(text)
        k = s.t_ms // TICK_MS
        rp = V.ramp_at(ad.sched, k)
        p_av = rw.P_AVAIL * rp.power_q / 1024
        hb = display_heli(h, o, p_av)
        self.s = RWState(seed=s.seed, k=s.k, t_ms=s.t_ms, helis=[hb], ended=s.ended, extra={})
        co = ad.truth(s.seed)
        x, y = h["x"], h["y"]
        drop = o["roof"]
        cpts, fpts = ray_terrain(o, x, y, extrap)
        n_cells = co.n
        F = [0.0] * n_cells
        C = [0.0] * n_cells
        for i in range(n_cells):
            xi = i * rw.DX
            F[i] = _interp(fpts, xi)
            C[i] = _interp(cpts, xi) + drop             # raw ceiling: the integrator subtracts the drop again
        FH = [max(F[max(0, i - 2):i + 3]) for i in range(n_cells)]
        CL = [min(C[max(0, i - 2):i + 3]) for i in range(n_cells)]
        j = o["ship"]
        sx = x + o["ship_dx"]
        T = ad.MAX_TICKS * TICK_MS / 1000            # RRAdapter._winch_free from the displayed survivor dx
        self.winch_free = (not o["hooked"]) and abs(o["surv_dx"]) > rw.HOOK_DX + abs(o["vx"]) * T + 3.0 * T * T + 2.0
        t = s.k * DT
        gsx, gsy = _gust_scale(o)
        gain = o["gust_gain"]
        wx0, wy0 = o["wind"]
        if decay:            # displayed wind = leg mean + gust: shrink toward the prior mean 0 (var a^2/3 vs gust var)
            a_m = min(0.5 + 0.7 * o["ship"], 4.0)
            vm, vg = a_m * a_m / 3.0, (gsx * gain) ** 2
            wmx, dd = wx0 * vm / (vm + vg), 0.0
        else:
            wmx, dd = wx0, wy0 / gain
        gx0 = (wx0 - wmx) / (gsx * gain)
        gy0 = (wy0 - dd * gain) / (gsy * gain)
        nG = len(co.GX)
        self.worlds = []
        # ships other than the next (and the landed) one: rule structure (ships LEG_LEN apart, +-8 m), unreachable
        # within the horizon except the ship just lifted off from (disclosed); needed by the checkpoint bookkeeping
        far = tuple((sx + (i - j) * rw.LEG_LEN,) + tuple(co.ships[i][1:]) for i in range(len(co.ships)))
        for b in range(n):
            r = R._h(f"bv2-rrt-world|{key}|{b}")
            ships = list(far)
            m0 = s.k
            n_sub = (ad.MAX_TICKS + 4) * SUB
            if mean_first and b == 0:
                ships[j] = _mean_deck(j, t, y + o["ship_dy"], o["ship_vy"], sx)
                if decay:                        # posterior-mean gust: the OU decays toward 0 (tau 2.5 s)
                    px = [gx0 * math.exp(-m * DT / 2.5) for m in range(n_sub)]
                    py = [gy0 * math.exp(-m * DT / 2.5) for m in range(n_sub)]
                else:
                    px, py = [0.0] * n_sub, [0.0] * n_sub
            else:
                ships[j] = R._deck_posterior(r, j, t, y + o["ship_dy"], o["ship_vy"], sx)
                px, py = R._ou_path(r, gx0, n_sub), R._ou_path(r, gy0, n_sub)
            GX = ([px[0]] * m0 + px + [px[-1]] * max(0, nG - m0 - n_sub))[:nG]
            GY = ([py[0]] * m0 + py + [py[-1]] * max(0, nG - m0 - n_sub))[:nG]
            if h["landed"] >= 0:
                Ld = h["landed"]
                if Ld != j:
                    ships[Ld] = (_mean_deck(Ld, t, y - SKID_H, o["vy"], x) if (mean_first and b == 0) else
                                 R._deck_posterior(r, Ld, t, y - SKID_H, o["vy"], x))
            shipc = [-1] * n_cells
            for jj, shp in enumerate(ships):
                if True:
                    lo_i = max(0, int((shp[0] - rw.SHIP_HALF - 12.0) / rw.DX))
                    hi_i = min(n_cells - 1, int((shp[0] + rw.SHIP_HALF + 12.0) / rw.DX) + 1)
                    for i in range(lo_i, hi_i + 1):
                        if abs(i * rw.DX - shp[0]) <= rw.SHIP_HALF + 12.0:
                            shipc[i] = jj
            wco = dataclasses.replace(
                co, F=F, C=C, FH=FH, CL=CL, ships=tuple(ships), SHIPC=shipc, GX=GX, GY=GY,
                WMX=[wmx] * n_cells, GSX=[gsx] * n_cells, GSY=[gsy] * n_cells, SHA=[0.0] * n_cells,
                DD=[dd] * n_cells, BAY=co.BAY)
            w = R.World(wco, f"belief{b}", self.winch_free, ad.sched)
            self.worlds.append(w)


# ------------------------------------------------------------------------------------------------ the controller
class ObsFast:
    """rwL_fast laws on a world (belief or sampled). `mem` holds only the controller's own rollout memory (vy of the
    previous tick inside a Q rollout / prediction); at the request state there is none (the prompt has no history),
    so the derivative term uses the world model's predicted acceleration."""
    __slots__ = ("ad", "w", "mem", "filt", "opt")

    BRAKE, V_MAX = 2.0, 22.0
    STOP_DX, LEAD_S = 3.0, 1.0
    SINK, FLARE, FLARE_GAP, SINK_APP = 2.5, 1.0, 3.0, 4.0
    FINAL_DX, FINAL_VX = 8.0, 3.0
    V_ROOM0, V_ROOM_K, ROOM0 = 6.0, 0.8, 10.0
    GLIDE, GLIDE_APP, MARGIN_LO, MARGIN_HI, DWELL_MS = 0.25, 0.3, 8.0, 6.0, 1500
    LOOK = (0.4, 0.8, 1.2, 1.6, 2.0, 2.6, 3.2)

    def __init__(self, ad, world, mem: dict | None = None, filt: bool = False, opt: dict | None = None):
        self.ad, self.w, self.mem, self.filt, self.opt = ad, world, dict(mem or {}), filt, opt or {}

    def clone(self):
        return ObsFast(self.ad, self.w, self.mem, self.filt, self.opt)

    def _corridor(self, x, vx, k):
        w = self.w
        rc_now, rc_fut = w.rc(k), w.rc(min(V.N_TICKS, k + 12))
        co = w.course
        lo, hi = -1e9, 1e9
        for tau in self.LOOK:
            xx = x + max(vx, 2.0) * tau
            fl = co.floor_at(xx)
            ce = (rc_fut if tau > 1.5 else rc_now).ceil_at(xx)
            for sh in co.ships:
                if abs(xx - sh[0]) <= 16.0:
                    fl = max(fl, sh[1] + 1.4 * sh[2] + 1.0)
            lo, hi = max(lo, fl), min(hi, ce)
        return lo, hi, rc_now

    def laws(self, s) -> tuple[float, float, float, str, bool]:
        """(vyd, vxd, pitch_lim, winch, final) of the rwL_fast laws at s."""
        h = s.helis[0]
        w, eng = self.w, self.ad.eng
        co = w.course
        k = s.t_ms // TICK_MS
        t = s.k * DT
        x, y, vx = h["x"], h["y"], h["vx"]
        lo, hi, rc = self._corridor(x, vx, k)
        room = hi - lo
        j = eng.next_ship(h)
        sh = co.ships[j]
        sx = sh[0]
        dky, dkv, _ = co.deck(j, t)
        deck_max = sh[1] + 1.4 * sh[2]
        dx = sx - x
        pitch_lim = 15.0 if room > 14 else 10.0
        d_eff = abs(dx) - self.STOP_DX - self.LEAD_S * abs(vx)
        vmax = min(self.V_MAX, self.V_ROOM0 + self.V_ROOM_K * max(0.0, room - self.ROOM0),
                   math.sqrt(2 * self.BRAKE * max(0.0, d_eff)) + 1.0)
        if self.opt.get("fwd_vmax"):                  # something straight ahead: be able to stop before it
            fwd = R.fast_rays(rc, x, y, t)[3]
            if fwd < RAY_MAX:
                vmax = min(vmax, math.sqrt(2 * self.BRAKE * max(0.0, fwd - self.opt["fwd_vmax"])) + 1.0)
        vxd = max(-vmax, min(vmax, 0.35 * dx))
        final = False
        if abs(dx) < 45:
            y_t = deck_max + SKID_H + 2.0 + self.GLIDE_APP * abs(dx)
            y_t = min(y_t, rc.ceil_at(x) - 4.0)
            vyd = max(-self.opt.get("sink_app", self.SINK_APP), min(2.5, 0.5 * (y_t - y)))
            if abs(dx) < self.FINAL_DX and abs(vx) < self.FINAL_VX:
                final = True
                gap = y - SKID_H - dky
                vyd = dkv - (self.opt.get("sink", self.SINK) if gap > self.FLARE_GAP else self.FLARE)
            pitch_lim = min(pitch_lim, 8.0 if abs(dx) < 10 else 15.0)
        else:
            glide = deck_max + SKID_H + 3.0 + self.GLIDE * abs(dx)
            a_lo, a_hi = lo + self.MARGIN_LO, hi - self.MARGIN_HI
            yc = min(max(glide, a_lo), a_hi) if a_lo <= a_hi else (lo + hi) / 2 + 0.5
            lim = 3.0 + 0.1 * abs(vx)
            vyd = max(-lim, min(lim, 0.45 * (yc - y)))
        winch = "up" if h["L"] > 5.5 else "hold"
        if h["att"]:
            cap = 0.0 if h["L"] > 7.0 else 11.0
            vxd = max(-cap, min(cap, vxd)) + 3.0 * math.sin(h["phi"]) + 0.3 * h["L"] * h["phid"]
            pitch_lim = 6.0
        if h["landed"] >= 0:
            t0 = self.mem.setdefault("land_t", s.t_ms)
            vyd, vxd = (0.0, 0.0) if s.t_ms - t0 < self.DWELL_MS else (2.0, 0.0)
            self.mem["climb_from"] = y
        else:
            self.mem.pop("land_t", None)
            if "climb_from" in self.mem:
                if y - self.mem["climb_from"] < 5.0:
                    vyd, vxd = 2.0, 0.0
                else:
                    del self.mem["climb_from"]
        return vyd, vxd, pitch_lim, winch, final

    def _ay(self, s) -> float:
        """Vertical acceleration: from the rollout memory if present, else the world model's 1-tick prediction under
        'hold' (the prompt shows no history)."""
        vy = s.helis[0]["vy"]
        if "vy" in self.mem and self.mem.get("k") == s.k - SUB:
            return (vy - self.mem["vy"]) / 0.25
        s2 = self.ad.step(self.w, s, {"collective": "hold", "cyclic": s.helis[0]["last"][1], "winch": "hold"})
        return (s2.helis[0]["vy"] - vy) / 0.25

    def decide(self, s) -> dict:
        h = s.helis[0]
        if not h["alive"]:
            return {"collective": "hold", "cyclic": "center", "winch": "hold"}
        vyd, vxd, pitch_lim, winch, final = self.laws(s)
        vy = h["vy"]
        th_d = max(-pitch_lim, min(pitch_lim, LandingPlanner.KV * (vxd - h["vx"])))
        cyc = LandingPlanner._cyclic_for(h, math.radians(th_d))
        r = h["Om"] / rw.OMEGA_N
        p_av = rw.P_AVAIL * V.ramp_at(self.w.sched, s.t_ms // TICK_MS).power_q / 1024
        droop = 100 * r < 96.0 or 100 * (p_av - h["Preq"]) / p_av < 3.0
        H = self.opt.get("mpc", 0)
        if H:                                    # model-predictive collective: the option whose held level tracks vyd
            best, bc = "hold", None
            for name, st_ in COLL_STEPS:
                if droop and st_ > 0:
                    continue
                s2, a = s, {"collective": name, "cyclic": cyc, "winch": "hold"}
                cost = 0.0
                for i in range(H):
                    s2 = self.ad.step(self.w, s2, a)
                    h2 = s2.helis[0]
                    if not h2["alive"]:
                        cost += 1e6 * (H - i)
                        break
                    cost += (h2["vy"] - vyd) ** 2 * (i + 1)
                    a = {"collective": "hold", "cyclic": cyc, "winch": "hold"}
                cost += 0.02 * abs(st_)          # tie-break toward small steps
                if bc is None or cost < bc:
                    best, bc = name, cost
            coll = best
            self.mem["vy"], self.mem["k"] = vy, s.k
        else:
            ay = self._ay(s)
            self.mem["vy"], self.mem["k"] = vy, s.k
            dc = 1.1 * (vyd - vy) - 0.35 * ay
            if droop:
                dc = min(dc, 0.0)
            coll = min(COLL_STEPS, key=lambda kv: abs(kv[1] - dc))[0]
        self.mem["final"] = final
        return {"collective": coll, "cyclic": cyc, "winch": winch}


# ------------------------------------------------------------------------------------------------ the planner


def load_confusion() -> dict:
    """r250's measured action confusion C(executed | a*) on RR (docs/v2_autopsy/dart.json confusion.rr: per control,
    estimated from the H1 DAgger rows, add-0.5 smoothed), the DART pilot's conf noise."""
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "docs/v2_autopsy/dart.json"
    return json.loads(p.read_text())["confusion"]["rr"]["confusion"]


def _draw(rng: random.Random, probs: dict) -> str:
    u, acc = rng.random() * math.fsum(probs.values()), 0.0
    for k, v in probs.items():
        acc += v
        if u < acc:
            return k
    return list(probs)[-1]


def corrupt(a: dict, rng: random.Random, mode: str, rho: float, conf: dict | None = None) -> dict:
    """Imitability check (SPEC secondary): the executed joint given the planner's answer a.
    'conf': w.p. rho the joint is drawn from r250's confusion C(. | a) per control (dart_generate.confusion_joint).
    'nb':   per control (collective, cyclic) w.p. rho the option moves one index up or down (clipped): a model that
            is right on the ordering but off by one step."""
    if mode == "conf":
        if rng.random() >= rho:
            return dict(a)
        return {c: _draw(rng, conf[c][a[c]]) for c in ("collective", "cyclic", "winch")}
    out = dict(a)
    for c, opts in (("collective", COLL_ORDER), ("cyclic", CYC_ORDER)):
        if rng.random() < rho:
            k = opts.index(a[c]) + rng.choice((-1, 1))
            out[c] = opts[max(0, min(len(opts) - 1, k))]
    return out


# Frozen development configuration (chosen on train idx 20000-20099 only; docs/v2_teachers/rr.md §2)
DEFAULTS = {"B": 4, "minor_worlds": 2, "tie_tol": 0.02, "safety_ticks": 8, "search_cyclic": True,
            "extrap": 0.5, "sink": 1.5, "sink_app": 3.0, "decay": True, "anchor": True}


class RRTeacherPlanner:
    """The stronger RR teacher. label(state, p_log, rkey) returns the LabelPlanner record format (q, q_by_d, tables,
    joint, answers, ...); base_answer() is the filtered controller alone (diagnostic policy 'ctl')."""

    def __init__(self, ad, p_hat: dict, markov=None, key: str = "", B: int = 4, safety_ticks: int = 8,
                 search_cyclic: bool = True, tie_tol: float = 0.02, q: bool = True, lag_pred: bool = True,
                 filt_delays=(1, 2), extrap: float = 0.0, fwd_vmax: float = 0.0, mpc: int = 0,
                 v_safe: float = 0.0, a_safe: float = 2.0, sink: float = 2.5, sink_app: float = 4.0,
                 decay: bool = False, minor_worlds: int = 2, anchor: bool = False):
        self.ad, self.p_hat, self.markov, self.key = ad, dict(p_hat), markov, key
        self.B, self.safety_ticks, self.search_cyclic, self.tie_tol = B, safety_ticks, search_cyclic, tie_tol
        self.use_q, self.lag_pred, self.filt_delays = q, lag_pred, tuple(filt_delays)
        self.order = L.joints(ad.CONTROLS, ad.OPTIONS)
        self.extrap, self.decay, self.minor_worlds, self.anchor = extrap, decay, minor_worlds, anchor
        self.copt = {"fwd_vmax": fwd_vmax, "mpc": mpc, "sink": sink, "sink_app": sink_app}
        self.v_safe, self.a_safe = v_safe, a_safe

    def belief(self, state, p_log, n):
        return Belief(self.ad, state, p_log, n, extrap=self.extrap, decay=self.decay)

    # ---------------------------------------------------------------- safety-filtered controller on the mean world
    def _pred(self, w, s, p_log: dict, d: int):
        """The belief state where a reply lands after d ticks: p_log, then the runner's hold rules."""
        acts = dict(p_log)
        for _ in range(d):
            s = self.ad.step(w, s, acts)
            if not s.helis[0]["alive"]:
                return None
            acts = QE._held(self.ad, acts)
        return s

    def _survive(self, w, s, coll: str, cyc: str, final: bool) -> int:
        """Ticks survived (cap safety_ticks): the candidate for one tick, then hold (cyclic held) or, over the deck,
        the braking continuation (sink FLARE m/s relative to the deck), as FastPlanner._rollout."""
        acts = {"collective": coll, "cyclic": cyc, "winch": "hold"}
        co = w.course
        j = self.ad.eng.next_ship(s.helis[0])
        vy_prev = s.helis[0]["vy"]
        for i in range(self.safety_ticks):
            s = self.ad.step(w, s, acts)
            hh = s.helis[0]
            if not hh["alive"]:
                return i
            if hh["landed"] >= 0 and hh["landed"] == j:
                return self.safety_ticks
            if self.v_safe and hh["landed"] < 0:      # touchdown margin: the sink vs the deck must stay arrestable
                dky, dkv, _ = co.deck(j, s.k * DT)
                if abs(hh["x"] - co.ships[j][0]) <= rw.SHIP_HALF:
                    gap = max(0.05, hh["y"] - SKID_H - dky)
                    rel = dkv - hh["vy"]
                    if rel > self.v_safe and (rel * rel - self.v_safe ** 2) / (2 * gap) > self.a_safe:
                        return i
            if final:
                _, dkv, _ = co.deck(j, s.k * DT)
                vy = hh["vy"]
                dc = 1.1 * (dkv - ObsFast.FLARE - vy) - 0.35 * (vy - vy_prev) / 0.25
                vy_prev = vy
                acts = {"collective": min(COLL_STEPS, key=lambda kv: abs(kv[1] - dc))[0], "cyclic": cyc,
                        "winch": "hold"}
            else:
                acts = {"collective": "hold", "cyclic": cyc, "winch": "hold"}
        return self.safety_ticks

    def controller(self, bel: Belief, p_log: dict | None) -> dict:
        w = bel.worlds[0]
        s0 = bel.s
        w.memo.clear()
        w.root, w.s0 = None, None
        preds = {}
        for d in sorted(set((1,) + self.filt_delays)):
            preds[d] = self._pred(w, s0, p_log or {}, d) if (self.lag_pred and p_log) else s0
        sp = preds[1] if preds[1] is not None else s0
        ctl = ObsFast(self.ad, w, opt=self.copt)
        a = ctl.decide(sp)
        final = ctl.mem.get("final", False)
        coll, cyc = a["collective"], a["cyclic"]
        states = [preds[d] for d in self.filt_delays if preds.get(d) is not None] or [s0]

        def score(c, y):
            return min(self._survive(w, st, c, y, final) for st in states)
        self.last_filter = None
        if score(coll, cyc) < self.safety_ticks:
            self.last_filter = (coll, cyc, score(coll, cyc))
            wc, wy = COLL_ORDER.index(coll), CYC_ORDER.index(cyc)
            cands = [(c, y) for c in COLL_ORDER for y in (CYC_ORDER if self.search_cyclic else [cyc])]
            best, bk = (coll, cyc), None
            for c, y in cands:
                t_alive = score(c, y)
                key = (t_alive, -(abs(COLL_ORDER.index(c) - wc) + abs(CYC_ORDER.index(y) - wy)))
                if bk is None or key > bk:
                    best, bk = (c, y), key
            coll, cyc = best
        return {"collective": coll, "cyclic": cyc, "winch": a["winch"]}

    def base_answer(self, state, p_log: dict | None, rkey: str = "") -> dict:
        return self.controller(self.belief(state, p_log, 1), p_log)

    # ---------------------------------------------------------------- labels
    def label(self, state, p_log: dict, rkey: str) -> dict:
        bel = self.belief(state, p_log, self.B + 1 if self.use_q else 1)
        key = bel.key
        base = self.controller(bel, p_log)
        base_t = tuple(base[c] for c in self.ad.CONTROLS)
        if not self.use_q:
            return {"answers": base, "joint": base_t, "base": base_t}
        sb = bel.s
        ws = bel.worlds[1:]
        for w in ws:
            w.memo.clear()
            w.base, w.s0, w.root = base_t, sb, None

        def cont_factory(world, s, k):
            world.root = s
            return ObsFast(self.ad, world, opt=self.copt)
        qd = {}
        for d in sorted(self.p_hat):                 # the minor delay (P-hat < 0.5) on fewer worlds (unbiased MC)
            wd = ws if self.p_hat[d] >= 0.5 else ws[:self.minor_worlds]
            qd.update(QE.q_table(self.ad, sb, p_log, key, len(wd), self.p_hat, delays=(d,), markov=self.markov,
                                 worlds=wd, cont_factory=cont_factory))
        q = L.qbar(qd, self.p_hat)
        deficit = max(q.values()) - q[base_t]
        q_lab = q
        if self.anchor and deficit > 0:    # a* = the filtered controller: its joint is lifted to the best Q value
            q_lab = dict(q)
            q_lab[base_t] = max(q.values())
        a = L.canonical_base(q_lab, self.order, base_t, self.tie_tol)
        tabs = L.slot_tables(self.ad.CONTROLS, self.ad.OPTIONS, q_lab, self.ad.TEMPERATURE, a, self.tie_tol)
        return {"q": q_lab, "q_raw": q, "q_by_d": qd, "tables": tabs, "joint": a,
                "answers": dict(zip(self.ad.CONTROLS, a)), "worlds": ws, "prep": {}, "base": base_t,
                "tie_tol": self.tie_tol, "q_deficit": deficit, "q_disagree": deficit > self.tie_tol}
