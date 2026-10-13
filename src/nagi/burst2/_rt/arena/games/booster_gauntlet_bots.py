"""BOOSTER GAUNTLET bot ladder (CPU, deterministic): idle floor, naive, heuristic, planner.

Bots are references, not contestants: they read the full engine state (privileged) through `see(game, state)`.
Portability rule (as Booster v1): bot arithmetic is Python floats with + - * / and math.sqrt only (correctly rounded
IEEE-754, one bytecode at a time: no FMA contraction, no libm transcendental), so ladder anchors are portable. The
engine itself is integer-only.

Ladder (docs/arena_v3/BOOSTER_GAUNTLET.md):
  bg0_idle       all defaults (engine never lit): floor, not a rung.
  bg1_naive      fixed schedule: full thrust below a fixed height, mid/min by sink speed, legs at a fixed height,
                 upright attitude hold; no lateral steering, never reads the rule variant.
  bg2_heuristic  feedback controller that reads the rules: fin-glide steering with the engine-first lift sign,
                 kinematic hoverslam ignition (stopping distance vs height, fixed safety margin), one-step
                 throttle lookahead in the burn, lateral divert under thrust with the thrust sign, legs by
                 time-to-go and q, shutdown + relight when min throttle would stop too high. Reacts to the current
                 wind and deck only (no foresight).
  bg3_planner    CPU planner with exact engine rollouts (the world is a deterministic function of seed and clock):
                 at each drop a shooting search over the heuristic's parameters for this hop, then every tick a
                 one-step lookahead MPC over (throttle, gimbal or fins, legs) held one tick and continued by the
                 planned heuristic to the end of the hop. Objective per hop: land (lexicographic), then touchdown
                 margin, then an earlier landing. Because the heuristic's own action is a candidate, the planner is
                 never worse than its continuation on a hop (policy improvement with exact rollouts).
"""
from __future__ import annotations

import math

from nagi.burst2._rt.arena.games import booster_gauntlet as G
from nagi.burst2._rt.arena.v2.bots import Bot

RAD_PER_BAM = 2.0 * 3.141592653589793 / G.TURN
DEG = 3.141592653589793 / 180.0
GRAV = 9.81
LEVELS = ("off", "min", "mid", "max")
GIM_ORDER = G.GIM_OPTS
GIM_RAD = {"L2": -5.0 * DEG, "L1": -2.0 * DEG, "0": 0.0, "R1": 2.0 * DEG, "R2": 5.0 * DEG}


def clip(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def obs_num(eng: G.BoosterGauntlet, s: G.GState, p: int) -> dict:
    """Privileged numeric view of booster p (floats; basic operations only)."""
    h = s.boosters[p]
    sc = eng.scenario(s.seed)
    kk = min(s.k, G.N_SUB)
    r = eng.rules
    m = (G.M_DRY + h["fuel"]) / 1000.0
    vx, vy = h["vx"] / 1000.0, h["vy"] / 1000.0
    wind = h["wind"] / 1000.0 if h["wind"] else sc.wind[kk] / 1000.0
    vax = vx - wind
    V = math.sqrt(vax * vax + vy * vy)
    S, C = G.isin(h["th"]), G.icos(h["th"])
    bot = G.lowest_point(h["y"], S, C, 1000)  # landing geometry (legs out)
    sy = sc.ship_y[kk]
    return {"t": s.t_ms / 1000.0, "k": s.k, "alt": (bot - sy) / 1000.0, "dx": (sc.ship_x[kk] - h["x"]) / 1000.0,
            "vx": vx, "vy": vy, "vxr": vx - sc.ship_vx[kk] / 1000.0, "vyr": vy - sc.ship_vy[kk] / 1000.0,
            "th": G.wrap_bam(h["th"]) * RAD_PER_BAM, "w": h["w"] * RAD_PER_BAM, "m": m, "V": V, "vax": vax,
            "q": float(h["q"]), "lit": h["lit"], "lvl": h["lvl"], "thr": float(h["thr"]), "relights": h["relights"],
            "fuel": h["fuel"] / 1000.0, "legs": h["legs"], "legs_on": h["legs_on"], "fin": h["fin"],
            "zone": sc.zone[kk] / 1000.0, "pitch": sc.ship_p[kk] * RAD_PER_BAM, "wind": wind,
            "T": {lv: float(r.thrust(lv, h)) for lv in LEVELS}, "rules": r, "hop": h["hop"],
            "age": (s.k - h["hop_k0"]) * 0.05, "status": h["status"]}


# ================================================================== attitude and lateral helpers


def attitude(o: dict, th_des: float, thrusting: bool, wn: float = 1.6, zeta: float = 0.9) -> tuple[str, str]:
    """Pick (gimbal, fins) whose predicted angular acceleration best matches a PD law toward th_des. Small-angle
    model: aero restoring moment -(26*12*fins_out - 6*21.5) q (th - flow), fin moment 26*1.2 q u * fin_sign, gimbal
    14 T sin(d) * gimbal_sign; I = m (11 m)^2. Reads the rule signs."""
    r = o["rules"]
    th, w, q, m = o["th"], o["w"], o["q"], o["m"]
    I = m * 121.0
    e = clip(th_des - th, -0.35, 0.35)
    a_des = wn * wn * e - 2.0 * zeta * wn * w
    flow = -o["vax"] / max(o["V"], 1.0)
    fd = 1.0 if o["fin"] != "stowed" else 0.0
    a_aero = -(312.0 * fd - 129.0) * q * (th - flow) / I if o["V"] > 1.0 else 0.0
    fin_gain = 31.2 * q / I * r.fin_sign
    thrust = o["thr"] if thrusting else 0.0
    best_g, best_f, best = "0", "neutral", None
    for gname in (GIM_ORDER if thrusting else ("0",)):
        ag = 14.0 * thrust * GIM_RAD[gname] / I * r.gimbal_sign
        for fname, u in (("neutral", 0.0), ("left", -1.0), ("right", 1.0)):
            err = a_aero + ag + fin_gain * u - a_des
            cost = err * err + (1e-7 if gname != "0" else 0.0) + (1e-7 if u else 0.0)
            if best is None or cost < best:
                best, best_g, best_f = cost, gname, fname
    return best_g, best_f


def lean_for(o: dict, a_des: float, thrust: float) -> float:
    """Tilt giving lateral acceleration a_des under thrust with the engine-first body lift (small angles)."""
    q, m = o["q"], o["m"]
    flow = -o["vax"] / max(o["V"], 1.0)
    an = q * (21.5 + (12.0 if o["fin"] != "stowed" else 0.0))
    den = thrust - an
    if abs(den) < 0.15 * (thrust + an):
        return flow
    return (m * a_des - an * flow) / den


def accels(o: dict) -> dict:
    """Net upward acceleration per level (thrust upright, weight, current drag), m/s^2."""
    m = o["m"]
    a_d = o["q"] * (10.75 + 1.5 + 6.0 * o["legs"] / 1000.0) / m if o["vy"] < 0.0 else 0.0
    return {lv: o["T"][lv] / m - GRAV + a_d for lv in LEVELS}


# ================================================================== heuristic controller

DEFAULTS = {
    "lb_frac": 0.92,  # ignite when the 2-segment stopping distance >= lb_frac x the usable height
    "vb": 35.0,  # m/s: end of the max-thrust segment
    "lam": 0.45,  # burn: reference deceleration = min + lam (mid - min)
    "td_v": 1.4,  # m/s touchdown sink target
    "l_tgo": 3.2,  # s: deploy legs when time-to-go below this (and q allows)
    "g_k": 0.35,  # 1/s lateral velocity gain (fin glide)
    "g_max": 10.0,  # deg max angle of attack in the glide
    "b_k": 0.8,  # 1/s lateral velocity gain in the burn
    "b_tilt": 9.0,  # deg max lean in the burn
    "aim": 0.0,  # m aim offset relative to the ship centre
    "cut": 12.0,  # m: shut down (and relight later) when min would stop above this height
    "pre": 1.5,  # s: pre-orient for the burn this long before the predicted ignition
    "floor": 40.0,  # m: never shut a lit engine down below this height while descending (no late relights)
    "glide_acc": 0.8,  # m/s^2: min throttle this weak (near hover, g1.1 early hops) enables the glide-in
    "glide_h": 40.0,  # m: glide-in below this height: min holds the sink, mid brakes a sink above the target
    "glide_v": 1.5,  # m/s target sink at the deck in the glide
    "glide_k": 0.4,  # target sink rises 0.4 m/s per m of height
}


def heuristic(o: dict, P: dict, mem: dict) -> dict:
    r: G.Rules = o["rules"]
    a = {}
    m, vy, alt, lit = o["m"], o["vyr"], o["alt"], o["lit"]
    acc = accels(o)
    fall = -vy if vy < -0.5 else 0.5
    if mem.get("hop") != o["hop"]:
        mem.clear()
        mem["hop"] = o["hop"]
    burning = bool(lit) or bool(mem.get("burn"))
    # ---------------- ignition decision (kinematic hoverslam, two segments: max to vb, then mid-ish to td_v)
    t_lag = 0.25 + r.ign_ms / 1000.0 + (0.25 if not lit else 0.0)  # decision period + ignition delay (rule)
    if not lit and vy < 0.0 and o["relights"] > 0:
        d_stop = d_stop_of(o, P, acc, fall)
        usable = alt - fall * t_lag
        if d_stop >= P["lb_frac"] * usable:
            burning = True
            mem["burn"] = 1
    if burning and not lit:
        a_req = fall * fall / (2.0 * max(alt - fall * t_lag, 1.0))
        a["throttle"] = "max" if a_req > 0.7 * acc["mid"] else "mid"
        mem["burn"] = 1
    elif burning:
        a["throttle"] = burn_throttle(o, P, acc)
        if lit and a["throttle"] == "off" and vy < 0.0 and alt < P.get("floor", 0.0):
            a["throttle"] = "min"
        if not lit and a["throttle"] == "off":
            mem["burn"] = 0
        if lit and a["throttle"] == "off":
            mem["burn"] = 0
    else:
        a["throttle"] = "off"
    # ---------------- legs: time to go vs deploy time, only below the tear-off q
    t_go = alt / max(fall, 1.0)
    need = P["l_tgo"] + (r.legs_ms - 2000) / 1000.0
    if (t_go < need or alt < 40.0) and o["q"] < 0.85 * G.Q_LEG or o["legs_on"]:
        a["legs"] = "deploy"
    # ---------------- lateral / attitude
    dx = o["dx"] + P["aim"]
    thrusting = lit and o["thr"] > 50_000.0
    if thrusting:
        tg = max(0.6, 2.0 * max(alt, 0.0) / max(fall, 1.0))
        v_cap = 0.35 * G.limits(r, int(o["t"] * 1000))[1] / 1000.0 + 0.04 * max(0.0, alt)
        vx_des = clip(dx / (tg + 1.0), -v_cap, v_cap)
        a_lat = P["b_k"] * (vx_des - o["vxr"])
        lim = P["b_tilt"] if alt > 30.0 else max(1.0, P["b_tilt"] * alt / 30.0)
        th_des = clip(lean_for(o, a_lat, o["thr"]), -lim * DEG, lim * DEG) + (o["pitch"] if alt < 15.0 else 0.0)
    else:
        th_des = 0.0
        t_ig = (alt - fall * t_lag) / max(fall, 1.0) - d_stop_of(o, P, acc, fall) / max(fall, 1.0)
        if t_ig < P["pre"] and vy < 0.0:  # pre-orient for the burn: the lean the thrust will need
            tg = max(0.6, 2.0 * max(alt, 0.0) / max(fall, 1.0))
            vx_des = clip(dx / (tg + 1.0), -30.0, 30.0)
            th_des = clip(lean_for(o, P["b_k"] * (vx_des - o["vxr"]), o["T"]["max"]), -P["b_tilt"] * DEG,
                          P["b_tilt"] * DEG)
        elif o["q"] > 200.0 and o["V"] > 20.0:
            t_go2 = max(2.0, alt / max(fall, 1.0))
            vx_des = clip(dx / t_go2, -40.0, 40.0)
            a_des = P["g_k"] * (vx_des - o["vxr"])
            lift = o["q"] * 33.5 / m
            alpha = clip(-a_des / max(lift, 1e-6), -P["g_max"] * DEG, P["g_max"] * DEG)
            qa_lim = 0.6 * G.QA_MAX / max(o["q"], 1.0)
            if qa_lim < 1.0:
                alpha = clip(alpha, -qa_lim, qa_lim)
            flow = -o["vax"] / max(o["V"], 1.0)
            th_des = flow + alpha
    a["gimbal"], a["fins"] = attitude(o, th_des, thrusting)
    return a


def d_stop_of(o: dict, P: dict, acc: dict, fall: float) -> float:
    vb = min(P["vb"], fall)
    return (fall * fall - vb * vb) / (2.0 * max(acc["max"], 0.5)) + (vb * vb - P["td_v"] * P["td_v"]) / (
        2.0 * max(0.5 * (acc["mid"] + acc["min"]), 0.3))


def burn_throttle(o: dict, P: dict, acc: dict) -> str:
    """One-step (0.25 s) analytic lookahead over the throttle levels, then a constant-deceleration continuation to
    touchdown (see v1 terminal_throttle): cost = infeasible stop (> max) >> touchdown too fast >> distance of the
    required deceleration from a reference inside [min, mid]; 'off' when even min would stop above `cut` m (a
    relight remains) - a later restart is planned by the ignition rule."""
    r: G.Rules = o["rules"]
    vy, alt, lit, rl = o["vyr"], o["alt"], o["lit"], o["relights"]
    td = P["td_v"]
    v_ok = 0.6 * G.limits(r, int(o["t"] * 1000))[0] / 1000.0
    a_ref = acc["min"] + P["lam"] * (acc["mid"] - acc["min"])
    dt = 0.25
    legs_pen = 0.0 if o["legs"] >= 1000 or o["legs_on"] else 20.0
    if lit and vy < 0.0 and alt > P["cut"] and rl > 0:
        h_stop_min = alt - vy * vy / (2.0 * max(acc["min"], 0.1))
        if h_stop_min > P["cut"] and alt > 25.0:
            return "off"
    if lit and acc["min"] < P.get("glide_acc", -1.0) and alt < P["glide_h"]:
        # glide-in (near-hover min thrust): the sink one period ahead at the CURRENT thrust vs a target that falls
        # with height; mid brakes above target + band, else min (which holds the sink nearly constant)
        a_now = o["thr"] / o["m"] - GRAV + (acc["min"] - (o["T"]["min"] / o["m"] - GRAV))
        fall1 = -vy - a_now * 0.25
        return "mid" if fall1 > P["glide_v"] + P["glide_k"] * alt + P.get("glide_band", 1.0) else "min"
    if vy >= 0.0:
        return "off" if alt > 3.0 else ("min" if lit else "off")
    cands = LEVELS if (lit or rl > 0) else ("off",)
    t_now = o["thr"]
    best, best_c = "off", None
    for lv in cands:
        ignite = not lit and lv != "off"
        if lv == "off":
            t_avg = 0.0
        elif ignite:
            t_avg = 0.0
        else:
            tl = o["T"][lv]
            t_avg = 0.5 * (t_now + tl) if abs(tl - t_now) > 1.0 else tl
        a1 = t_avg / o["m"] - GRAV + (acc["min"] - (o["T"]["min"] / o["m"] - GRAV))
        v1 = vy + a1 * dt
        h1 = alt + vy * dt + 0.5 * a1 * dt * dt
        lit1 = (lit and lv != "off") or ignite
        if h1 <= 0.0:
            vc2 = vy * vy - 2.0 * a1 * alt
            vc = math.sqrt(vc2) if vc2 > 0.0 else 0.0
            cost = 10.0 * max(0.0, vc - v_ok) + legs_pen
        elif lit1:
            if v1 >= 0.0:
                cost = 5.0 + 0.1 * h1
            else:
                a_r = (v1 * v1 - td * td) / (2.0 * h1)
                if a_r > acc["max"]:
                    cost = 100.0 + a_r
                elif a_r >= acc["min"]:
                    cost = abs(a_r - a_ref) / max(a_ref, 1.0)
                else:
                    h_stop = h1 - v1 * v1 / (2.0 * max(acc["min"], 0.1))
                    cost = 1.0 + 0.2 * h_stop
            if ignite:
                cost += 0.3
        else:
            a_r = v1 * v1 / (2.0 * max(h1 - v1 * -0.5, 0.5))
            cost = 100.0 + a_r if a_r > acc["max"] else 0.5 + abs(a_r - a_ref) / max(a_ref, 1.0)
        cost += 0.01 * LEVELS.index(lv)
        if best_c is None or cost < best_c:
            best, best_c = lv, cost
    return best


# ================================================================== naive schedule


def naive(o: dict, mem: dict) -> dict:
    """Fixed schedule: full thrust below 345 m (g1.1; 330 m before, whose first touchdown under the 1-tick delay
    fell at 10.1-10.9 s, a hop-cadence cluster just after the L2 label), then mid below 40 m/s sink, min below
    8 m/s; legs at 150 m; hold
    upright; no lateral steering; ignores the rules text."""
    if mem.get("hop") != o["hop"]:
        mem.clear()
        mem["hop"] = o["hop"]
    a = {"fins": "neutral"}
    vy, alt = o["vy"], o["alt"]
    if alt < 345.0 or mem.get("lb"):
        mem["lb"] = 1
        a["throttle"] = "off" if vy > 0.0 else "max" if vy < -40.0 else "mid" if vy < -8.0 else "min"
    else:
        a["throttle"] = "off"
    th, w = o["th"], o["w"]
    u = 1.2 * (0.0 - th) / DEG - 1.0 * w / DEG
    a["gimbal"] = ("R2" if u > 3.5 else "R1" if u > 1.0 else "L2" if u < -3.5 else "L1" if u < -1.0 else "0") \
        if o["lit"] else "0"
    if alt < 150.0:
        a["legs"] = "deploy"
    return a


# ================================================================== rollouts and the planner

_SOLO: dict = {}


def solo(eng: G.BoosterGauntlet) -> G.BoosterGauntlet:
    key = (eng.rules, eng.decision_period_ms, eng.max_round_ms)
    g = _SOLO.get(key)
    if g is None:
        g = _SOLO[key] = G.BoosterGauntlet(rules=eng.rules, n_players=1, decision_period_ms=eng.decision_period_ms,
                                           max_round_ms=eng.max_round_ms)
    return g


def hop_rollout(eng: G.BoosterGauntlet, s: G.GState, p: int, P: dict, mem: dict, first: dict | None = None,
                hold: int = 1) -> tuple:
    """Play booster p alone from state s until its CURRENT hop ends (touchdown or crash): `first` (a partial action)
    for `hold` ticks, the heuristic P for the rest. Integer engine, exact. Returns the objective tuple."""
    h = dict(s.boosters[p])
    one = solo(eng)
    sc = one.scenario(s.seed)
    st = G.GState(seed=s.seed, k=s.k, t_ms=s.t_ms, boosters=[h])
    mem = dict(mem)
    n = 0
    hop = h["hop"]
    dp = eng.decision_period_ms
    nsub = dp // G.SUB_MS
    while True:
        if st.t_ms >= eng.max_round_ms:
            return (2, 0, 0)  # survives to the cap: as good as a landing
        o = obs_num(one, st, 0)
        act = heuristic(o, P, mem)
        if first is not None and n < hold:
            act = dict(act, **first)
        G.apply_action(h, one.rules, act, None, 0, st.t_ms)
        k = G.integrate(h, sc, st.k, nsub, None, 0)
        n += 1
        if h["status"] == "landed_hop":
            td = h["td"]
            return (1, td["q"] // 20_000, -k)  # quality in 2 % buckets, then earlier landing
        if h["status"] == "crashed":
            td = h["td"]
            if td is not None and h["td"]["hop"] == hop and td["k"] == k:
                zone = sc.zone[min(k, G.N_SUB)]
                r = one.rules
                l_vy, l_vx, _, _ = G.limits(r, k * G.SUB_MS)
                pen = (max(0, abs(td["vyr"]) - l_vy) * 1000 // l_vy
                       + max(0, abs(td["dx"]) - zone) * 1000 // max(zone, 1)
                       + max(0, abs(td["vxr"]) - l_vx) * 1000 // l_vx
                       + (0 if h["legs"] >= 1000 else 500))
                return (0, -min(pen, 10 ** 6), 0)
            return (0, -2 * 10 ** 6 + k, 0)
        st = G.GState(seed=s.seed, k=st.k + nsub, t_ms=st.t_ms + dp, boosters=[h])


def predict(eng: G.BoosterGauntlet, s: G.GState, p: int, acts: dict, n: int):
    """(solo engine, state) of booster p after n ticks of `acts` (what the realtime runner applies before a reply
    sent now lands: arena.v3.delay), exact; None if its hop ends meanwhile (then the planner plans from s)."""
    one = solo(eng)
    st = G.GState(seed=s.seed, k=s.k, t_ms=s.t_ms, boosters=[dict(s.boosters[p])])
    hop = st.boosters[0]["hop"]
    for _ in range(n):
        st, _ = one.step(st, {0: acts}, eng.decision_period_ms)
        h = st.boosters[0]
        if h["status"] != "flying" or h["hop"] != hop or st.t_ms >= eng.max_round_ms:
            return None
    return one, st


class Planner:
    GRID = (
        {},
        {"lb_frac": 0.85}, {"lb_frac": 0.97}, {"lb_frac": 1.0, "vb": 20.0}, {"lb_frac": 0.8, "lam": 0.3},
        {"td_v": 0.9}, {"td_v": 2.0}, {"lam": 0.25}, {"lam": 0.7},
        {"g_k": 0.6, "g_max": 14.0}, {"g_k": 0.2}, {"b_k": 1.3, "b_tilt": 10.0}, {"b_k": 0.5},
        {"aim": -6.0}, {"aim": 6.0}, {"cut": 30.0}, {"cut": 4.0}, {"l_tgo": 4.5},
    )

    def __init__(self):
        self.n_rollouts = 0

    def shoot(self, eng, s, p, mem) -> dict:
        """Best heuristic parameters for the current hop: one pass over GRID, then pairwise combos of the top 3."""
        scored = []
        for ov in self.GRID:
            P = dict(DEFAULTS, **ov)
            scored.append((hop_rollout(eng, s, p, P, mem), -len(scored), ov))
            self.n_rollouts += 1
        scored.sort(reverse=True)
        best_v, _, best_ov = scored[0]
        tops = [x[2] for x in scored[:3]]
        for i in range(len(tops)):
            for j in range(i + 1, len(tops)):
                ov = dict(tops[i], **tops[j])
                v = hop_rollout(eng, s, p, dict(DEFAULTS, **ov), mem)
                self.n_rollouts += 1
                if v > best_v:
                    best_v, best_ov = v, ov
        return dict(DEFAULTS, **best_ov)

    def candidates(self, o: dict, base: dict) -> list[dict]:
        out = [dict(base)]
        legs_opts = ("deploy",) if o["legs_on"] else ("stowed", "deploy")
        if o["lit"]:
            for thr in LEVELS:
                for gm in GIM_ORDER:
                    for lg in legs_opts:
                        out.append({"throttle": thr, "gimbal": gm, "fins": base.get("fins", "neutral"), "legs": lg})
        else:
            thrs = LEVELS if o["relights"] > 0 else ("off",)
            for thr in thrs:
                for fn in ("left", "neutral", "right"):
                    for lg in legs_opts:
                        out.append({"throttle": thr, "gimbal": "0", "fins": fn, "legs": lg})
        return out

    def decide(self, eng, s, p, mem, P) -> dict:
        o = obs_num(eng, s, p)
        base = heuristic(o, P, dict(mem))
        base = {"throttle": base["throttle"], "gimbal": base["gimbal"], "fins": base["fins"],
                "legs": base.get("legs", "deploy" if o["legs_on"] else "stowed")}
        best, best_v = base, None
        for c in self.candidates(o, base):
            v = hop_rollout(eng, s, p, P, mem, c, 1)
            self.n_rollouts += 1
            if best_v is None or v > best_v:
                best, best_v = c, v
        return best


# ================================================================== bot wrapper (arena.v2 Bot API)

LADDER = ("bg1_naive", "bg2_heuristic", "bg3_planner")
ALL_BOTS = ("bg0_idle",) + LADDER


class GauntletBot(Bot):
    lag = None   # set by arena.v3.delay.Delayed: (controls the runner applies before this reply lands, ticks)

    def __init__(self, bot_id: str):
        super().__init__(bot_id)
        assert bot_id in ALL_BOTS, bot_id
        self.planner = Planner() if bot_id == "bg3_planner" else None

    def bind(self, seat, seed):
        super().bind(seat, seed)
        self.mem, self._P, self._P_hop = {}, dict(DEFAULTS), None
        return self

    def see(self, game, state):
        super().see(game, state)
        self._cache = None

    def _decide(self) -> dict:
        g, s, p = self.game.engine, self.state, self.seat
        o = obs_num(g, s, p)
        if self.bot_id == "bg0_idle":
            return {}
        if self.bot_id == "bg1_naive":
            return naive(o, self.mem)
        if self.bot_id == "bg2_heuristic":
            return heuristic(o, DEFAULTS, self.mem)
        if self.lag:                       # delay-aware: plan from where the reply lands (exact prediction)
            pr = predict(g, s, p, self.lag[0], self.lag[1])
            if pr is not None:
                g, s = pr
                p = 0
                o = obs_num(g, s, p)
        if self._P_hop != o["hop"]:
            self.mem = {}
            self._P = self.planner.shoot(g, s, p, self.mem)
            self._P_hop = o["hop"]
        a = self.planner.decide(g, s, p, self.mem, self._P)
        heuristic(o, self._P, self.mem)  # advance the continuation's memory with the observed state
        return a

    def choose(self, q):
        if self._cache is None:
            self._cache = self._decide()
        v = self._cache.get(q.key, q.default)
        return v if v in q.options else q.default

    def act(self, game, state) -> dict:
        """Direct (runner-free) interface: the full action dict for this bot's seat."""
        self.see(game, state)
        a = self._decide()
        self._cache = a
        return a


def make_bot(bot_id: str) -> GauntletBot:
    return GauntletBot(bot_id)


def play_solo(bot_id: str, seed: int, variant: str | None = None, rules: G.Rules | None = None) -> dict:
    """One bot alone, direct loop (no referee): outcome dict + per-hop landing log. Deterministic."""
    g = G.BoosterGauntlet(variant, rules=rules)
    b = make_bot(bot_id).bind(0, seed)
    s = g.reset(seed)
    lands = []
    while not g.done(s):
        a = b.act(g, s)
        s, ev = g.step(s, {0: a}, g.decision_period_ms)
        lands += [e.data for e in ev if e.kind == "landed"]
    out = g.outcome(s, 0)
    out["landings"] = lands
    if b.planner is not None:
        out["rollouts"] = b.planner.n_rollouts
    return out
