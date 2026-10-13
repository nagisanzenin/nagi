"""Booster Gauntlet g1.2 teacher, lane booster-c (approach C): a fast deterministic model-based guidance law with a
Smith predictor and a short exact-rollout safety filter. Observation-limited (LANES.md Booster information set).

Information boundary (explicit). The teacher is a function of the contract's `bv2n.contract.booster.BoosterView`
(bv2n-booster-view-v2: current displayed frame, the displayed booster + deck state of the last 8 ticks, p_log, and the
actuators that follow from own commands: ignition delay left, fin deployment / deflection), converted by
`from_contract` into engine units (`BoosterViewC`). Leg fraction and thrust are recovered from the display (legs move
25 permille per substep, so 'DEPLOYING NN%' is exact; thrust is displayed in kN). Nothing else: no true gust series, no
ship periods/phases, no engine-internal state beyond what the display and own commands determine.
The game model (rules text + engine equations) is public; the hidden quantities are estimated from the view:
  * height / ship dx: 1 m display resolution, refined by intersecting the displayed intervals of the last 8 ticks moved
    to now with the displayed velocities (trapezoid), `refine`;
  * ship surge / heave / pitch: per component, the integer period in the engine's range and the phase that best fit the
    displayed deck velocities / pitch of the window (least squares, known amplitude ramp), `fit_component`;
  * wind at the deck: the displayed wind divided by the altitude factor; the gust decays to the known mean wind with
    the AR(1) factor 0.6 per second, the mean's sign is the sign of the window mean, `wind_table`.
The model world built from these is deterministic, so the controller is a deterministic function of the view.

Control (decided on the state one tick ahead: Smith predictor, nominal 1-tick reply):
  guidance  `guide`: hoverslam ignition at the latest tick where a max burn from after the ignition lag still meets
            the descent reference v_ref(h) = sqrt(v_td^2 + 2 a_r (h - h_c)) at or above h_meet; in the burn the
            throttle level whose exact one-tick sink best tracks v_ref (over-speed weighted); lateral: lean for the
            deck-relative drift target, attitude by the PD law of the bg2 helper (`booster_gauntlet_bots.attitude`).
  filter    the guidance joint and a few structured alternatives are rolled out to the end of the hop in the model
            world (exact integer engine, guidance continuation in lockstep = the delayed loop under the Smith
            predictor); the score is 2 - E (E = max normalised touchdown error) for a deck touchdown, negative for any
            other failure. An alternative replaces the guidance joint only when it beats it by more than DELTA.
"""
from __future__ import annotations

import dataclasses
import math
from typing import NamedTuple

from nagi.burst2._rt.arena.games import booster_gauntlet as G
from nagi.burst2._rt.arena.games import booster_gauntlet_bots as BB

H_HIST = 8
CONTROLS = ("throttle", "gimbal", "fins", "legs")
OPTIONS = {"throttle": G.THR_OPTS, "gimbal": G.GIM_OPTS, "fins": G.FIN_OPTS, "legs": G.LEG_OPTS}
RULES = G.BASE_RULES
SUB = G.DECISION_MS // G.SUB_MS        # substeps per decision tick (5)
PERIODS = {"s": (12, 18), "h": (6, 9), "p": (7, 10)}   # engine ranges (booster_gauntlet.build_scenario), public

# ================================================================== internal view (engine units)
class Obs(NamedTuple):
    """One displayed observation (integers, engine units: ms, mm, mm/s, mdeg, mdeg/s, kN, kg, Pa)."""
    t_ms: int
    hop: int
    landed: int
    age_ms: int
    alt: int        # displayed height (lowest point above the deck centre), whole metres -> mm
    vx: int
    vy: int
    tilt: int
    rate: int
    dx: int         # ship x - booster x, whole metres -> mm
    zone: int
    dvx: int
    dvy: int
    pitch: int
    wind: int
    lit: int
    lvl: str
    thr_kn: int
    relights: int
    relights0: int
    gim: int
    fuel_kg: int
    fuel0_kg: int
    fin: str
    legs_state: str
    q: int


class Act(NamedTuple):
    """Actuator state at the START of a tick (before that tick's applied joint), from own commands only."""
    lit: int
    ign: int
    thr: int
    thr_cmd: int
    lvl: str
    gim: int
    gim_cmd: int
    gcmd: str
    fin: str
    fin_dep: int
    fin_u: int
    legs_on: int
    legs: int
    relights: int


@dataclasses.dataclass(frozen=True)
class BoosterViewC:
    """Everything the client legitimately knows at a request boundary (LANES.md Booster information set)."""
    obs: Obs
    hist: tuple          # ((Obs, Act), ...) of the previous <= 8 ticks of this hop, oldest first
    act: Act             # own actuator state now (start of the current tick)
    p_log: tuple         # joint the runner applies at the current tick (throttle, gimbal, fins, legs)


# ================================================================== contract BoosterView (bv2n-booster-view-v2) -> internal
def _legs_from(state: str, pct) -> int:
    """Leg fraction (permille) from the display: deploying NN% = floor(legs / 10); legs move 25 per substep, so the
    multiple of 25 in [10 NN, 10 NN + 9] is unique."""
    if state == "stowed":
        return 0
    if state == "down":
        return 1000
    lo = 10 * pct
    return ((lo + 24) // 25) * 25


def from_contract(v) -> BoosterViewC:
    """Thin glue: the contract's BoosterView (display units) -> the internal view (engine units). Uses only the view's
    fields. Unknown per-tick history fields (fuel, engine, legs) are filled from the current frame / derived: legs one
    tick earlier = legs - 125 while deploying (25 per substep, one-way)."""
    from nagi.burst2._rt.bv2n.contract import booster as CB
    f, a = v.frame, v.act
    legs = _legs_from(f.legs, f.legs_pct)
    lit = int(f.eng != "OFF")
    lvl = f.eng if lit else "off"
    t0 = (f.t - f.age) * 10
    tmin = RULES.t_min_at(t0)
    cmd = {"off": 0, "min": tmin, "mid": G.T_MID, "max": RULES.t_max}[lvl] if lit else 0
    thr = 0
    if lit and f.thr is not None:
        thr = cmd if cmd // 1000 == f.thr else f.thr * 1000 + (0 if f.thr % 100 == 0 else 500)

    def obs(t_cs, alt, vx, vy, dx, tilt, rate, dvx, dvy, pitch, wind) -> Obs:
        return Obs(t_ms=t_cs * 10, hop=f.hop, landed=f.landed, age_ms=f.age * 10 - (f.t - t_cs) * 10, alt=alt * 1000,
                   vx=vx * 100, vy=vy * 100, tilt=tilt * 100, rate=rate * 100, dx=dx * 1000, zone=f.zone * 1000,
                   dvx=dvx * 100, dvy=dvy * 100, pitch=pitch * 100, wind=wind * 100, lit=lit, lvl=lvl, thr_kn=f.thr or 0,
                   relights=f.relights, relights0=f.relights0, gim=f.gim * 100, fuel_kg=f.fuel, fuel0_kg=f.fuel0,
                   fin=f.fins, legs_state=f.legs.upper(), q=f.q * 100)
    cur = obs(f.t, f.alt, f.vx, f.vy, f.dx, f.tilt, f.rate, f.dvx, f.dvy, f.pitch, f.wind)
    act = Act(lit=lit, ign=a.ign_ms // G.SUB_MS, thr=thr, thr_cmd=cmd, lvl=lvl, gim=G.deg_to_bam(f.gim * 100),
              gim_cmd=G.deg_to_bam(G.GIM_MDEG[v.applied[1]]), gcmd=v.applied[1], fin=f.fins, fin_dep=a.fin_out * 10,
              fin_u=a.fin_defl * 10, legs_on=int(f.legs != "stowed"), legs=legs, relights=f.relights)
    hist = []
    for i, row in enumerate(v.hist):
        if row is None:
            continue
        ago = CB.OFFSETS[i] if len(CB.OFFSETS) == len(v.hist) else len(v.hist) - i
        t_cs = f.t - ago * CB.TICK_CS
        if t_cs < t0 // 10:
            continue                                     # before this hop's drop
        lg = 1000 if f.legs == "down" else max(0, legs - 125 * ago) if legs else 0
        hist.append((obs(t_cs, row.alt, row.vx, row.vy, row.dx, row.tilt, row.rate, row.dvx, row.dvy, row.pitch,
                         row.wind), act._replace(legs=lg)))
    return BoosterViewC(obs=cur, hist=tuple(hist), act=act, p_log=tuple(v.applied))


# ================================================================== estimation (view -> model world)
def _geom(tilt_mdeg: int, legs: int) -> int:
    """Lowest point below the CG (mm) at a tilt and leg fraction (booster_gauntlet.lowest_point geometry)."""
    th = G.deg_to_bam(tilt_mdeg)
    S, C = G.isin(th), G.icos(th)
    return G.lowest_point(0, S, C, legs) * -1


def refine(cur: int, cur_terms: tuple, hist: list, half: int = 500, tol_per_tick: int = 20) -> int:
    """Intersect the displayed intervals [d - half, d + half] of the window, each moved to now by the integrated
    displacement (trapezoid of the displayed rates); returns the interval midpoint (or the mean if inconsistent).
    hist: [(displayed value, displacement from that tick to now (mm), ticks ago)]."""
    lo, hi = cur - half, cur + half
    vals = [cur]
    for d, disp, n in hist:
        w = tol_per_tick * n
        lo = max(lo, d + disp - half - w)
        hi = min(hi, d + disp + half + w)
        vals.append(d + disp)
    if lo <= hi:
        return (lo + hi) // 2
    return sum(vals) // len(vals)


def fit_component(samples: list, per: tuple, amp_of, kind: str) -> tuple:
    """Least-squares (period s, phase rad) of value(k) = A(k) * f(2 pi k / (T * 20) + phi) over displayed samples
    [(substep k, value)] (kind 'cos' for a velocity of a sinusoidal position, 'sin' for an angle; A(k) = amp_of(k, T)).
    Returns (T, phi, sse)."""
    best = None
    for T in range(per[0], per[1] + 1):
        w = 2 * math.pi / (T * G.SUB_HZ)
        # value = A (cos th cos phi - sin th sin phi) [cos] or A (sin th cos phi + cos th sin phi) [sin]
        a11 = a12 = a22 = b1 = b2 = 0.0
        rows = []
        for k, v in samples:
            A = amp_of(k, T)
            th = w * k
            if kind == "cos":
                u1, u2 = A * math.cos(th), -A * math.sin(th)
            else:
                u1, u2 = A * math.sin(th), A * math.cos(th)
            rows.append((u1, u2, v))
            a11 += u1 * u1
            a12 += u1 * u2
            a22 += u2 * u2
            b1 += u1 * v
            b2 += u2 * v
        det = a11 * a22 - a12 * a12
        if abs(det) < 1e-9:
            c, s = 1.0, 0.0
        else:
            c, s = (b1 * a22 - b2 * a12) / det, (a11 * b2 - a12 * b1) / det
        nrm = math.sqrt(c * c + s * s)
        if nrm < 1e-12:
            c, s = 1.0, 0.0
        else:
            c, s = c / nrm, s / nrm
        sse = sum((u1 * c + u2 * s - v) ** 2 for u1, u2, v in rows)
        key = (round(sse, 6), T)
        if best is None or key < best[0]:
            best = (key, T, math.atan2(s, c), sse)
    return best[1], best[2], best[3]


class Model:
    """Deterministic model world built from a view: booster engine-state dict at the current tick, a Scenario whose
    tables hold the forecast wind / ship from the current substep on (ship frame: ship x = 0, deck y = DECK_H now)."""

    def __init__(self, view: BoosterViewC, rules: G.Rules = RULES, decay: float = 0.6):
        o, a = view.obs, view.act
        self.view, self.rules = view, rules
        K = o.t_ms // G.SUB_MS
        self.K = K
        hist = list(view.hist)
        # ---------------- height / dx refinement over the window
        seq = [(ho, ha) for ho, ha in hist] + [(o, a)]
        n = len(seq)
        disp_y = [0] * n           # booster CG displacement from seq[i] to now (mm)
        disp_sy = [0] * n          # deck centre displacement
        disp_x = [0] * n
        disp_sx = [0] * n
        dt = G.DECISION_MS
        for i in range(n - 2, -1, -1):
            o0, o1 = seq[i][0], seq[i + 1][0]
            gap = (o1.t_ms - o0.t_ms) // dt
            disp_y[i] = disp_y[i + 1] + (o0.vy + o1.vy) * dt * gap // 2000
            disp_sy[i] = disp_sy[i + 1] + (o0.dvy + o1.dvy) * dt * gap // 2000
            disp_x[i] = disp_x[i + 1] + (o0.vx + o1.vx) * dt * gap // 2000
            disp_sx[i] = disp_sx[i + 1] + (o0.dvx + o1.dvx) * dt * gap // 2000
        g_now = _geom(o.tilt, a.legs)
        alt_h, dx_h = [], []
        for i in range(n - 1):
            oi, ai = seq[i]
            ticks = (o.t_ms - oi.t_ms) // dt
            # alt = y_cg - geom - deck_y  ->  alt_now = alt_i + dy - dsy - (geom_now - geom_i)
            alt_h.append((oi.alt, disp_y[i] - disp_sy[i] - (g_now - _geom(oi.tilt, ai.legs)), ticks))
            dx_h.append((oi.dx, disp_sx[i] - disp_x[i], ticks))
        self.alt = refine(o.alt, (), alt_h)
        self.dx = refine(o.dx, (), dx_h)
        # ---------------- booster state (engine dict)
        th = G.deg_to_bam(o.tilt)
        S, C = G.isin(th), G.icos(th)
        y = G.DECK_H + self.alt + (-G.lowest_point(0, S, C, a.legs))
        t0 = o.t_ms - o.age_ms
        tmin = rules.t_min_at(t0)
        fuel = o.fuel_kg * 1000 + 500
        self.h = {"status": "flying", "cause": None, "t_end": None, "landed": o.landed, "qsum": 0, "td": None,
                  "wind": o.wind, "x": -self.dx, "y": y, "vx": o.vx, "vy": o.vy, "th": th, "w": G.deg_to_bam(o.rate),
                  "fuel": fuel, "fuel0": o.fuel0_kg * 1000, "lit": a.lit, "ign": a.ign, "thr": a.thr,
                  "thr_cmd": a.thr_cmd, "lvl": a.lvl, "relights": a.relights, "relights0": o.relights0,
                  "gim": a.gim, "gim_cmd": a.gim_cmd, "gcmd": a.gcmd, "fin": a.fin, "fin_dep": a.fin_dep,
                  "fin_u": a.fin_u, "legs": a.legs, "legs_on": a.legs_on, "q": o.q, "qa": 0, "nr": 0, "hop": o.hop,
                  "hop_k0": t0 // G.SUB_MS, "hop_level": G.level_at(t0), "low": 1, "twr": rules.twr_at(t0),
                  "tmin": tmin, "last": ("off", "0", "neutral", "stowed")}
        self.sc = self._scenario(o, seq, decay)

    def _scenario(self, o: Obs, seq: list, decay: float) -> G.Scenario:
        K, n_all = self.K, G.N_SUB + 1
        hi = min(n_all, K + G.HOP_LIMIT_MS // G.SUB_MS + 2 * G.SUB_HZ)
        ks = range(K, hi)
        # ---------------- ship components from the window
        obs_k = [(so.t_ms // G.SUB_MS, so) for so, _ in seq]
        two_pi = 2 * math.pi

        def amp(row):
            return lambda k, T: G.ramp(row, k * G.SUB_MS)

        def vamp(row):
            return lambda k, T: G.ramp(row, k * G.SUB_MS) * two_pi / T

        sx = [0] * n_all
        sy = [0] * n_all
        sp = [0] * n_all
        if len(obs_k) >= 3:
            Ts, phs, _ = fit_component([(k, so.dvx) for k, so in obs_k], PERIODS["s"], vamp("surge_m"), "cos")
            Th, phh, _ = fit_component([(k, so.dvy) for k, so in obs_k], PERIODS["h"], vamp("heave_m"), "cos")
            Tp, php, _ = fit_component([(k, so.pitch) for k, so in obs_k], PERIODS["p"], amp("pitch_deg"), "sin")

            def pos(row, T, ph, k):
                return G.ramp(row, k * G.SUB_MS) * math.sin(two_pi * k / (T * G.SUB_HZ) + ph)
            s0, h0 = pos("surge_m", Ts, phs, K), pos("heave_m", Th, phh, K)
            for k in ks:
                sx[k] = int(round(pos("surge_m", Ts, phs, k) - s0))
                sy[k] = G.DECK_H + int(round(pos("heave_m", Th, phh, k) - h0))
                sp[k] = G.deg_to_bam(int(round(pos("pitch_deg", Tp, php, k))))
        else:                                   # too little history: deck moves at its displayed rates
            for k in ks:
                d = (k - K) * G.SUB_MS
                sx[k] = o.dvx * d // 1000
                sy[k] = G.DECK_H + o.dvy * d // 1000
                sp[k] = G.deg_to_bam(o.pitch)
        for k in range(hi, n_all):
            sx[k], sy[k], sp[k] = sx[hi - 1], sy[hi - 1], sp[hi - 1]
        vx = [0] * n_all
        vy = [0] * n_all
        pr = [0] * n_all
        for k in range(K, n_all - 1):
            vx[k] = (sx[k + 1] - sx[k]) * G.SUB_HZ
            vy[k] = (sy[k + 1] - sy[k]) * G.SUB_HZ
            pr[k] = (sp[k + 1] - sp[k]) * G.SUB_HZ
        # ---------------- wind at the deck
        wind = wind_table(o, seq, K, hi, n_all, self.rules, decay)
        zone = [0] * n_all
        for k in range(K, n_all):
            zone[k] = G.ramp("zone_m", k * G.SUB_MS)
        return G.Scenario(0, self.rules, tuple(wind), tuple(sx), tuple(sy), tuple(sp), tuple(vx), tuple(vy),
                          tuple(pr), tuple(zone))


def wind_table(o: Obs, seq: list, K: int, hi: int, n_all: int, rules: G.Rules, decay: float) -> list:
    """Deck-level wind forecast (mm/s per substep). Displayed wind = deck wind x (1 + min(y, 1 km) / 2 km) at the
    booster's altitude (CG y ~ deck + displayed height + 14 m). Sign of the mean wind = sign of the window mean of the
    deck-level estimates; the gust (estimate - signed mean) decays by `decay` per second."""
    def deck_w(so):
        yc = min(G.DECK_H + max(so.alt, 0) + G.L_ENG, 1_000_000)
        return so.wind * 2_000_000 // (2_000_000 + yc)
    ws = [deck_w(so) for so, _ in seq]
    w0 = ws[-1]
    mean = sum(ws) / len(ws)
    sgn = 1 if mean >= 0 else -1
    mult = rules.wind_mult
    g0 = w0 - sgn * G.ramp("wind_mps", o.t_ms) * mult // 10
    out = [0] * n_all
    lam = math.log(decay) / G.SUB_HZ if decay > 0 else -1e9
    for k in range(K, n_all):
        kk = min(k, hi - 1)
        out[k] = sgn * G.ramp("wind_mps", kk * G.SUB_MS) * mult // 10 + int(round(g0 * math.exp(lam * (kk - K))))
    return out


# ================================================================== guidance law
DEFAULTS = {
    "v_td": 1.2,       # m/s sink target at the deck
    "a_r": 4.0,        # m/s^2 reference deceleration of the descent profile
    "h_c": 1.0,        # m: the profile reaches v_td this high
    "h_meet": 50.0,    # m: ignite so that the max burn meets the profile at or below this height
    "t_lag": 0.55,     # s: ignition delay 0.3 s + thrust slew to max (~0.25 s)
    "w_fast": 2.0,     # over-speed weight in the throttle choice
    "legs_q": 9000.0,  # Pa: deploy the legs only below this q
    "legs_alt": 150.0,  # m: deploy at the latest this low (or as soon as lit)
    "kv": 0.8,         # 1/s lateral velocity gain under thrust
    "tau_x": 1.5,      # s: added to the time-to-go of the position loop
    "vcap0": 0.3,      # m/s: drift cap at the deck
    "vcap_k": 0.03,    # m/s per m of height
    "vcap_k2": 0.06, "h_k2": 40.0,   # extra drift allowance high in the burn (m/s per m above h_k2)
    "tilt_max": 9.0,   # deg lean limit in the burn
    "tilt_min": 4.0,   # deg lean limit at the deck
    "h_f": 20.0,       # m: lean limit shrinks below this
    "h_pitch": 15.0,   # m: match the deck pitch below this
    "g_k": 0.35, "g_max": 10.0, "pre": 2.0,   # unlit glide steering / pre-orientation (bg2 law)
    "wn": 1.6, "zeta": 0.9,   # attitude PD (bg2 helper) at speed
    "wn_low": 1.2,     # attitude PD natural frequency below v_low airspeed
    "v_low": 30.0,
    "att_thr": 1,      # attitude law uses this tick's thrust
    "t_lead": 0.5,     # s: lateral lead (current thrust lean acceleration x t_lead added to the drift)
    "lat": "cap",      # lateral law: 'cap' (capped drift target) or 'eg' (E-guidance)
    "tg_min": 2.5, "eg_p": 1.0, "eg_d": 1.0, "a_lat_max": 3.0,
}


def vref(h: float, P: dict) -> float:
    return math.sqrt(P["v_td"] ** 2 + 2.0 * P["a_r"] * max(0.0, h - P["h_c"]))


def _tick_thrust(t_now: float, t_tgt: float, dt: float = 0.25, ign: int = 0) -> float:
    """Mean thrust over one tick slewing from t_now to t_tgt (2,000 kN/s up, 6,000 kN/s down), after `ign` substeps
    of ignition delay (no thrust)."""
    if ign > 0:
        n = min(ign, SUB)
        if n >= SUB:
            return 0.0
        rest = (SUB - n) * G.SUB_MS / 1000.0
        return _tick_thrust(t_now, t_tgt, rest) * rest / dt
    if abs(t_tgt - t_now) < 1.0:
        return t_tgt
    rate = 2.0e6 if t_tgt > t_now else 6.0e6
    ts = abs(t_tgt - t_now) / rate
    if ts >= dt:
        return t_now + math.copysign(rate * dt * 0.5, t_tgt - t_now) * 1.0
    return (0.5 * (t_now + t_tgt) * ts + t_tgt * (dt - ts)) / dt


def throttle_level(o: dict, P: dict) -> str:
    m, vy, alt = o["m"], o["vyr"], o["alt"]
    acc = BB.accels(o)
    drag = acc["min"] - (o["T"]["min"] / m - BB.GRAV)
    best, best_c = "min", None
    for lv in ("min", "mid", "max"):
        T = _tick_thrust(o["thr"], o["T"][lv], ign=o["ign_left"])
        a1 = T / m - BB.GRAV + drag
        v1 = vy + a1 * 0.25
        h1 = alt + 0.5 * (vy + v1) * 0.25
        fall1 = -v1
        ref = vref(max(h1, 0.0), P)
        e = fall1 - ref
        cost = P["w_fast"] * e if e > 0 else -e
        cost += 1e-3 * BB.LEVELS.index(lv)
        if best_c is None or cost < best_c:
            best, best_c = lv, cost
    return best


def ignite_now(o: dict, P: dict) -> bool:
    if o["lit"] or o["vyr"] >= 0.0 or o["relights"] <= 0:
        return False
    acc = BB.accels(o)
    fall, alt, tl = -o["vyr"], o["alt"], P["t_lag"]
    v_l = fall + BB.GRAV * tl
    h_l = alt - fall * tl - 0.5 * BB.GRAV * tl * tl
    amax = max(acc["max"], 0.5)
    ar = P["a_r"]
    # max burn from (h_l, v_l): v^2 = v_l^2 - 2 amax (h_l - h); profile v^2 = v_td^2 + 2 ar (h - h_c)
    hm = (P["v_td"] ** 2 - 2 * ar * P["h_c"] - v_l * v_l + 2 * amax * h_l) / (2 * (amax - ar))
    return hm <= P["h_meet"]


def time_to_ignition(o: dict, P: dict, horizon: float = 4.0) -> float:
    """Seconds until ignite_now fires along the unpowered fall (constant current net acceleration), 0.25 s steps."""
    if o["lit"] or o["vyr"] >= 0.0 or o["relights"] <= 0:
        return 99.0
    a0 = BB.accels(o)["off"]
    q = dict(o)
    t = 0.0
    while t <= horizon:
        if ignite_now(q, P):
            return t
        t += 0.25
        q["vyr"] = o["vyr"] + a0 * t
        q["alt"] = o["alt"] + o["vyr"] * t + 0.5 * a0 * t * t
    return 99.0


def guide(o: dict, P: dict) -> dict:
    """The guidance joint for the model state o (BB.obs_num fields + ign_left)."""
    r = o["rules"]
    alt, vy, lit = o["alt"], o["vyr"], o["lit"]
    fall = -vy if vy < -0.5 else 0.5
    # legs
    legs = "deploy" if (o["legs_on"] or (o["q"] < P["legs_q"] and (lit or alt < P["legs_alt"]))) else "stowed"
    # vertical
    if not lit:
        thr = "max" if ignite_now(o, P) else "off"
    else:
        thr = throttle_level(o, P)
    # lateral / attitude
    thrusting = lit and o["thr"] > 50_000.0
    dx = o["dx"]
    if thrusting:
        if P.get("lat", "cap") == "eg":
            # E-guidance to zero deck-relative position and drift at touchdown along the descent profile
            t_go = (vref(alt, P) - P["v_td"]) / P["a_r"] + min(alt, P["h_c"]) / P["v_td"]
            if fall > vref(alt, P):      # still above the profile (main burn): the profile time is a lower bound
                t_go = max(t_go, 2.0 * max(alt, 0.0) / max(fall + P["v_td"], 1.0))
            tg = max(P["tg_min"], t_go)
            a_lat = P["eg_p"] * 6.0 * dx / (tg * tg) - P["eg_d"] * 4.0 * o["vxr"] / tg
            a_lat = BB.clip(a_lat, -P["a_lat_max"], P["a_lat_max"])
        else:
            tg = max(0.6, 2.0 * max(alt, 0.0) / max(fall, 1.0))
            v_cap = P["vcap0"] + P["vcap_k"] * max(0.0, alt) + P["vcap_k2"] * max(0.0, alt - P["h_k2"])
            vx_des = BB.clip(dx / (tg + P["tau_x"]), -v_cap, v_cap)
            vx_now = o["vxr"]
            if P["t_lead"] > 0:      # lead: the drift the current lean will add before a new lean takes effect
                a_now = o["thr"] / o["m"] * math.sin(o["th"] - o.get("gim_rad", 0.0))
                vx_now += P["t_lead"] * a_now
            a_lat = P["kv"] * (vx_des - vx_now)
        lim = P["tilt_max"] if alt > P["h_f"] else max(P["tilt_min"], P["tilt_max"] * alt / P["h_f"])
        th_des = BB.clip(BB.lean_for(o, a_lat, o["thr"]), -lim * BB.DEG, lim * BB.DEG)
        if alt < P["h_pitch"]:
            th_des += o["pitch"]
    else:
        th_des = 0.0
        t_ig = time_to_ignition(o, P)
        if t_ig < P["pre"] and vy < 0.0:
            tg = max(0.6, 2.0 * max(alt, 0.0) / max(fall, 1.0))
            vx_des = BB.clip(dx / (tg + 1.0), -30.0, 30.0)
            th_des = BB.clip(BB.lean_for(o, P["kv"] * (vx_des - o["vxr"]), o["T"]["max"]), -P["tilt_max"] * BB.DEG,
                             P["tilt_max"] * BB.DEG)
        elif o["q"] > 200.0 and o["V"] > 20.0:
            t_go2 = max(2.0, alt / max(fall, 1.0))
            vx_des = BB.clip(dx / t_go2, -40.0, 40.0)
            a_des = P["g_k"] * (vx_des - o["vxr"])
            lift = o["q"] * 33.5 / o["m"]
            alpha = BB.clip(-a_des / max(lift, 1e-6), -P["g_max"] * BB.DEG, P["g_max"] * BB.DEG)
            qa_lim = 0.6 * G.QA_MAX / max(o["q"], 1.0)
            if qa_lim < 1.0:
                alpha = BB.clip(alpha, -qa_lim, qa_lim)
            th_des = -o["vax"] / max(o["V"], 1.0) + alpha
    if thrusting and P.get("att_thr", 1):
        # the gimbal acts with the thrust of THIS tick (the chosen level, slewing), not the current one
        o = dict(o, thr=_tick_thrust(o["thr"], o["T"][thr] if thr != "off" else 0.0, ign=o["ign_left"]))
    wn = P["wn"] if o["V"] > P["v_low"] else P["wn_low"]
    gim, fins = BB.attitude(o, th_des, thrusting, wn=wn, zeta=P["zeta"])
    return {"throttle": thr, "gimbal": gim, "fins": fins, "legs": legs}


# ================================================================== model rollouts
class _Eng:
    def __init__(self, rules, sc):
        self.rules, self.sc = rules, sc

    def scenario(self, seed):
        return self.sc


def obs_of(eng: _Eng, h: dict, k: int) -> dict:
    st = G.GState(seed=0, k=k, t_ms=k * G.SUB_MS, boosters=[h])
    o = BB.obs_num(eng, st, 0)
    o["ign_left"] = h["ign"]
    o["gim_rad"] = h["gim"] * BB.RAD_PER_BAM
    return o


def step_model(h: dict, sc: G.Scenario, k: int, joint: dict) -> int:
    G.apply_action(h, sc.rules, joint, None, 0, k * G.SUB_MS)
    return G.integrate(h, sc, k, SUB, None, 0) if h["status"] == "flying" else k


def score(h: dict, sc: G.Scenario) -> float:
    st = h["status"]
    td = h["td"]
    if st in ("landed_hop", "crashed") and td is not None and td["hop"] == h["hop"] and (
            st == "landed_hop" or h["cause"] in G.TD_CAUSES):
        legs = 1000 if st == "landed_hop" else h["legs"]
        E = G.touchdown_errors(sc.rules, td, sc.zone[min(td["k"], G.N_SUB - 1)], legs)["E"]
        return 2.0 - min(E, 3.0)
    if st == "crashed" and h["cause"] == "splashdown":
        return -1.0
    if st == "flying":
        return -1.5          # still flying at the horizon (hop timeout ahead)
    return -2.0              # in-flight failure / timeout


def rollout(h0: dict, sc: G.Scenario, k: int, first: dict | None, P: dict, max_ticks: int = 100) -> tuple:
    """Play the model world from (h0, k): `first` for one tick (None = guidance), then the guidance in lockstep, to
    the end of the hop. Returns (score, final h)."""
    h = dict(h0)
    eng = _Eng(sc.rules, sc)
    for n in range(max_ticks):
        if h["status"] != "flying" or k * G.SUB_MS >= G.MAX_ROUND_MS:
            break
        j = first if (n == 0 and first is not None) else guide(obs_of(eng, h, k), P)
        k_new = step_model(h, sc, k, j)
        k = k + SUB if h["status"] == "flying" else k_new
    return score(h, sc), h


# ================================================================== the teacher
@dataclasses.dataclass
class BoosterC:
    """LANES teacher API: act(view, rng) -> joint; label(view) -> {'joint', 'targets'}. Deterministic in the view."""
    P: dict = dataclasses.field(default_factory=lambda: dict(DEFAULTS))
    filt: bool = False       # exact-rollout safety filter (off in the frozen candidate: dev 0-47 it added hop timeouts)
    delta: float = 0.05      # an alternative must beat the guidance joint by more than this (score units)
    decay: float = 0.6
    oracle: object = None    # DIAGNOSTIC ONLY (privileged): callable -> (true booster dict, true scenario, substep)

    def plan(self, view) -> dict:
        if not isinstance(view, BoosterViewC):
            view = from_contract(view)          # the contract's BoosterView (the served request)
        if self.oracle is not None:
            h0, sc, K = self.oracle()
        else:
            M = Model(view, decay=self.decay)
            sc, h0, K = M.sc, M.h, M.K
        # Smith predictor: the state where this reply lands (1 tick under the applied p_log)
        h1 = dict(h0)
        p_log = dict(zip(CONTROLS, view.p_log))
        step_model(h1, sc, K, {c: v for c, v in p_log.items() if v is not None})
        if h1["status"] != "flying":
            h1, K1 = dict(h0), K
        else:
            K1 = K + SUB
        eng = _Eng(sc.rules, sc)
        o1 = obs_of(eng, h1, K1)
        base = guide(o1, self.P)
        info = {"base": dict(base), "filtered": False}
        if not self.filt:
            return {"joint": base, "info": info}
        s_base, hb = rollout(h1, sc, K1, base, self.P)
        best, best_s = base, s_base
        for c in self.candidates(o1, base):
            s, _ = rollout(h1, sc, K1, c, self.P)
            if s > best_s + (self.delta if best is base else 1e-9):
                best, best_s = c, s
        info.update(s_base=s_base, s_best=best_s, filtered=best is not base)
        return {"joint": best, "info": info}

    @staticmethod
    def candidates(o: dict, base: dict) -> list:
        out = []
        if o["lit"]:
            for t in ("min", "mid", "max"):
                if t != base["throttle"]:
                    out.append(dict(base, throttle=t))
            for gm in G.GIM_OPTS:
                if gm != base["gimbal"]:
                    out.append(dict(base, gimbal=gm))
        else:
            for t in ("off", "max"):
                if t != base["throttle"]:
                    out.append(dict(base, throttle=t))
            for f in ("left", "neutral", "right"):
                if f != base["fins"]:
                    out.append(dict(base, fins=f))
        return out

    def act(self, view, rng=None) -> dict:
        return dict(self.plan(view)["joint"])

    def label(self, view: BoosterViewC) -> dict:
        j = self.act(view)
        return {"joint": j, "targets": {c: {o: (1.0 if o == j[c] else 0.0) for o in OPTIONS[c]} for c in CONTROLS}}
