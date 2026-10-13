"""ROTORWASH-RAMP (Arena v3 fail-first): the Rotorwash helicopter game with a deterministic difficulty ramp.

Same airframe, cave, wind, rescue task and controls as Rotorwash (`arena.games.rotorwash`, which this module never
edits: the v2 game stays bit-identical, tests/test_rotorwash_ramp_v2_unchanged.py). What changes is that the round
has NO success terminal state: difficulty rises every tick until every helicopter has crashed, or the 90 s cap.
Docs: docs/arena_v3/ROTORWASH_RAMP.md (levers, calibration, limitations).

The ramp (a pure function of the global tick index k; never of any player's position, progress or deliveries):
  * COLLAPSE FRONT: the cave collapses behind the helicopters. The front starts FRONT_X0 m (x = 0) and advances at
    a speed that rises with k; any airframe point behind it (x - REAR < front) is a crash 'collapse'.
  * ROOF SQUEEZE: the cave roof descends by drop(k) metres (never below the floor + a minimum gap, a larger one over
    flooded bays so a ship deck stays landable).
  * STORM: gusts, shear and downdrafts are multiplied by gain(k) >= 1 (the mean wind is unchanged).
  * ENGINE FADE: available engine power is P_AVAIL * power(k) (power <= 1), so the RPM droops at a lower collective.
Every lever is a piecewise-linear interpolation, per tick, between anchor values at t = 0, 10, ..., 90 s (integer
arithmetic in mm, 1/1024 units and mm/s). Levels L = 1 + floor(t / 10 s) (L1..L9, L10 only at the cap) are display
labels: there are no steps in difficulty at level boundaries (owner Amendment 1).

Determinism. Everything NEW in the step path is integer or a single IEEE operation on exactly representable
operands (drop mm / 1000, gain q / 1024, a float compared with an int); no numpy, no libm call is added. The
physics itself is the Rotorwash float64 physics (math.sin/exp/tanh and a course built with np.interp), so replay
is exact on the recording platform only (handbook R3.13; `float_engine=True`, like Rotorwash).

Scoring (per round, focal seat): survival time T_fail (s, capped at 90 s, censored when alive at the cap), level at
failure, game score (metres + 500 per delivery). The v3 binding maps T_fail onto the frozen ladder anchors
(`LADDER_ANCHORS_S`, piecewise linear 0 / 0.5 / 1) for legacy consumers; the decision metric is the paired per-seed
win rate (later failure wins, same tick or both censored = 1/2).
"""
from __future__ import annotations

import contextlib
import hashlib
import math
import threading
from dataclasses import dataclass, field, replace
from functools import lru_cache

from nagi.burst2._rt.arena.core import Event, Query
from nagi.burst2._rt.arena.games import rotorwash as rw
from nagi.burst2._rt.arena.games.rotorwash import (COLL, COLL_OPTS, CYC_OPTS, CYCLIC, DECK_ABOVE_WATER, DT, DX, EXTENT, HUB_H, HZ,
                                   LEG_LEN, POINTS, RAY_ANGLES, RAY_MAX, RAY_NAMES, SKID_H, WINCH, WINCH_OPTS, X_START,
                                   Rotorwash, RWState, _cast, _f, build_course, new_heli, power_required)

RULES_VERSION = "ramp1.0"
GAME_ID = "rotorwash_ramp"
TICK_MS = 250
SUB = HZ * TICK_MS // 1000                 # 60 physics substeps per tick
TICKS_PER_LEVEL = 40                        # 10 s display levels
MAX_ROUND_MS = 60000                        # owner Amendment 2: T_cap = 60 s, 6 levels
N_TICKS = MAX_ROUND_MS // TICK_MS           # 240
N_ANCHORS = N_TICKS // TICKS_PER_LEVEL + 1  # anchors at t = 0, 10, ..., 60 s
N_LEVELS = N_TICKS // TICKS_PER_LEVEL       # 6

REAR = 7.2          # m, tail point behind the CG (rotorwash.POINTS): the front hits the tail first
WARN_ON, WARN_OFF = 15.0, 22.0  # m between front and tail: 'front_warn' event arm / re-arm
FRONT_U_PER_M = 240000          # front position unit: 1/240 mm (one substep of a speed in mm/s)


@dataclass(frozen=True)
class Schedule:
    """Anchor values at t = 10 j seconds (j = 0..6); integers. Per-tick values interpolate linearly (floor)."""
    front_mm_s: tuple = (2500, 6500, 11500, 16500, 21500, 26000, 30000)
    roof_mm: tuple = (0, 2750, 8000, 20000, 34000, 47000, 60000)
    gust_q: tuple = (1024, 1400, 2200, 3300, 4600, 5800, 7000)     # x / 1024
    power_q: tuple = (1024, 990, 950, 900, 850, 800, 760)          # x / 1024 of P_AVAIL
    front_x0_mm: int = 0
    roof_gap_mm: int = 12000        # minimum roof height above the floor (cave cells)
    bay_gap_mm: int = 12000         # minimum roof height above the ship deck's highest point (bay cells)

    def __post_init__(self):
        for a in (self.front_mm_s, self.roof_mm, self.gust_q, self.power_q):
            assert len(a) == N_ANCHORS and all(isinstance(v, int) for v in a), a


BASE = Schedule()


def lerp_anchor(anchors: tuple, k: int) -> int:
    """Integer value at tick k: linear between anchors 40 ticks apart, floor division; constant after the cap."""
    if k >= N_TICKS:
        return anchors[-1]
    j, r = divmod(max(0, k), TICKS_PER_LEVEL)
    a, b = anchors[j], anchors[j + 1]
    return a + ((b - a) * r) // TICKS_PER_LEVEL


def level_of(k: int) -> int:
    """Display level of tick k: 1 + floor(t / 10 s), capped at N_LEVELS (the cap tick itself is still L6)."""
    return min(N_LEVELS, 1 + max(0, k) // TICKS_PER_LEVEL)


@dataclass(frozen=True)
class Ramp:
    k: int
    level: int
    front_mm_s: int
    roof_mm: int
    gust_q: int
    power_q: int


@lru_cache(maxsize=32)
def ramp_at(sched: Schedule, k: int) -> Ramp:
    return Ramp(k, level_of(k), lerp_anchor(sched.front_mm_s, k), lerp_anchor(sched.roof_mm, k),
                lerp_anchor(sched.gust_q, k), lerp_anchor(sched.power_q, k))


@lru_cache(maxsize=16)
def front_table(sched: Schedule) -> tuple:
    """Front position after substep kk (kk = 0 .. N_TICKS*SUB + 8*HZ), in 1/240 mm: integer running sum of the
    per-tick speed (mm/s) once per substep. front metres = value / FRONT_U_PER_M."""
    n = N_TICKS * SUB + 8 * HZ
    out = [sched.front_x0_mm * 240]
    pos = out[0]
    for kk in range(n):
        pos += lerp_anchor(sched.front_mm_s, kk // SUB)
        out.append(pos)
    return tuple(out)


def front_m(sched: Schedule, kk: int) -> float:
    t = front_table(sched)
    return t[min(kk, len(t) - 1)] / FRONT_U_PER_M


@lru_cache(maxsize=64)
def gap_min(seed: int, sched: Schedule) -> tuple:
    """Per course cell: the lowest the roof may come above the floor (m). Bay cells keep room above the deck."""
    co = build_course(seed)
    out = []
    for j in range(co.n):
        if co.BAY[j]:
            leg = min(int(j * DX // LEG_LEN), len(co.ships) - 1)
            a1 = co.ships[leg][2]
            out.append(DECK_ABOVE_WATER + 1.4 * a1 + sched.bay_gap_mm / 1000)
        else:
            out.append(sched.roof_gap_mm / 1000)
    return tuple(out)


class _Roof:
    """Effective ceiling nodes max(C - drop, F + gap_min) as a lazy sequence (same polyline structure as C)."""
    __slots__ = ("C", "F", "G", "drop")

    def __init__(self, C, F, G, drop):
        self.C, self.F, self.G, self.drop = C, F, G, drop

    def __getitem__(self, i):
        c = self.C[i] - self.drop
        f = self.F[i] + self.G[i]
        return c if c > f else f

    def __len__(self):
        return len(self.C)


class RampCourse:
    """Course view with the lowered roof (rays, observation, renderer); everything else delegates to the Course."""

    def __init__(self, co, G, drop: float):
        self.co, self.drop = co, drop
        self.F, self.n, self.ships, self.xmax, self.surv = co.F, co.n, co.ships, co.xmax, co.surv
        self.C = _Roof(co.C, co.F, G, drop)

    def deck(self, j, t):
        return self.co.deck(j, t)

    def floor_at(self, x):
        return self.co.floor_at(x)

    def ceil_at(self, x: float) -> float:
        i = min(max(int(x / DX), 0), self.n - 2)
        f = x / DX - i
        return self.C[i] + (self.C[i + 1] - self.C[i]) * f


def ramp_course(seed: int, sched: Schedule, k: int) -> RampCourse:
    return RampCourse(build_course(seed), gap_min(seed, sched), ramp_at(sched, k).roof_mm / 1000)


RULES = (
    "ROTORWASH RAMP (rules ramp1.0): x forward, y up. Fly a rescue helicopter through a sea cave "
    "that COLLAPSES BEHIND YOU; a decision every 0.25 s, controls hold between. Thrust ~ RPM%^2 x collective along "
    "the rotor axis; pitch + = nose down = pushes forward. Collective beyond engine power droops RPM; RPM < 85% for "
    "1 s = crash. Fast sinking at low airspeed = vortex ring (up to -40% thrust). Crash: front reaches your tail; "
    "touching cave, roof, water or ship hull; fuel out; load swing > 50 deg. Only a ship deck is landable (sink < "
    "2.5 m/s, pitch < 12 deg). Optional rescue +500: hover within 4 m of the survivor, speed < 1 m/s, rope end (winch "
    "5-25 m) <= 2 m above it for 1.5 s; then land on a ship. It gets harder every tick until all crash: faster front, "
    "lower roof, stronger gusts, less power (6 levels of 10 s). Survive longest.")

# ---- variants (rule text that matters; the schedule / constant patches are applied by RampGame)


@dataclass(frozen=True)
class RampVariant:
    id: str
    split: str                      # 'variant_dev' | 'variant_sealed'
    announce_text: str
    patch: dict = field(default_factory=dict)       # rotorwash module constants during every engine call
    schedule: Schedule | None = None                # replaces BASE


def _scaled(a: tuple, num: int, den: int) -> tuple:
    return tuple(a[0] + (v - a[0]) * num // den for v in a)


VARIANTS = {v.id: v for v in (
    RampVariant("rr_power_low", "variant_dev",
                "RULE CHANGE: engine power 12% lower (RPM droops sooner).",
                patch={"P_AVAIL": 290000.0}),
    RampVariant("rr_front_surge", "variant_dev",
                "RULE CHANGE: the front's speed rises 1.5x as fast.",
                schedule=replace(BASE, front_mm_s=_scaled(BASE.front_mm_s, 3, 2))),
    RampVariant("rr_power_fade", "variant_sealed",
                "RULE CHANGE: engine power fades 1.5x as fast.",
                schedule=replace(BASE, power_q=_scaled(BASE.power_q, 3, 2))),
    RampVariant("rr_roof_crush", "variant_sealed",
                "RULE CHANGE: the roof lowers 2x as fast.",
                schedule=replace(BASE, roof_mm=_scaled(BASE.roof_mm, 2, 1))),
)}


# Scored rule-reading variants (integrator 2026-09-27): the two power variants flip only 5.5% / 2.0% of planner actions
# and knowing them is worth nothing measurable (ROTORWASH_RAMP.md §6), so they stay defined (and in the determinism
# chain) but are dropped from the scored variant set.
DROPPED_VARIANTS = ("rr_power_low", "rr_power_fade")
SCORED_VARIANTS = tuple(v for v in VARIANTS if v not in DROPPED_VARIANTS)

# Frozen ladder anchors (median T_fail of naive, heuristic, planner on the 32 calib seeds; receipt:
# docs/arena_v3/rotorwash_ramp_calibration.json 'ladder_anchors_s'; tests assert they match).
LADDER_ANCHORS_S = (11.135, 24.494, 45.825)   # 1-tick-delay ladder (FAIL_FIRST_BRIEF Amendment 3), calib n=32


def ladder_position(t_fail_s: float, anchors: tuple = None) -> float:
    """Amendment 1 item 2: T_fail -> 0 / 0.5 / 1 at the naive / heuristic / planner medians, piecewise linear,
    extrapolated linearly beyond the planner with the heuristic-planner slope, clipped to [0, 1.2]."""
    a0, a1, a2 = anchors or LADDER_ANCHORS_S
    if t_fail_s <= a0:
        v = 0.0
    elif t_fail_s <= a1:
        v = 0.5 * (t_fail_s - a0) / (a1 - a0)
    else:
        v = 0.5 + 0.5 * (t_fail_s - a1) / (a2 - a1)
    return min(1.2, max(0.0, v))


def ranking_key(h: dict) -> int:
    """Later failure ranks higher; alive = cap + 1 ms (censored ties)."""
    return h["t_crash"] if h["t_crash"] is not None else MAX_ROUND_MS + 1


class RotorwashRamp(Rotorwash):
    """Rotorwash engine with the ramp. `schedule` = the ramp anchors; module constants are read from
    arena.games.rotorwash at call time (so RampGame's constant patches apply, like v2 variants)."""
    id = GAME_ID
    max_round_ms = MAX_ROUND_MS

    def __init__(self, schedule: Schedule = BASE, rules_text: str = RULES, n_players: int = 4):
        super().__init__()
        self.sched, self.rules_text = schedule, rules_text
        self.n_players = n_players          # 4 in the Arena (seat 0 + 3 ladder ghosts); the demo video uses 3

    # -------------------------------------------------------------- protocol
    def reset(self, seed: int) -> RWState:
        s = super().reset(seed)
        for h in s.helis:
            h["fw_on"] = False
            h["front_gap"] = round(h["x"] - REAR - front_m(self.sched, 0), 3)
        return s

    def queries(self, s: RWState, player: int, answers: dict[str, str]) -> list[Query]:
        h = s.helis[player]
        if not h["alive"] or s.ended or answers:
            return []
        obs = self.observation(s, player)
        return [
            Query(player, "collective", obs + "\nChoose COLLECTIVE change: down2=-0.10, down1=-0.05, hold, "
                  "up1=+0.05, up2=+0.10.", COLL_OPTS, "hold"),
            Query(player, "cyclic", obs + "\nChoose CYCLIC (held): aft2=-0.6, aft1=-0.3, "
                  "center=0, fwd1=+0.3, fwd2=+0.6 (fwd = nose down).", CYC_OPTS, "center"),
            Query(player, "winch", obs + "\nChoose WINCH: up=shorten 2 m/s, hold, down=lengthen 2 m/s.",
                  WINCH_OPTS, "hold"),
        ]

    def step(self, s: RWState, actions: dict[int, dict[str, str]], dt_ms: int) -> tuple[RWState, list[Event]]:
        co = build_course(s.seed)
        helis = [dict(h) for h in s.helis]
        nsub = int(round(dt_ms * HZ / 1000))
        k_tick = s.t_ms // TICK_MS
        events: list[Event] = []
        if not s.ended:
            rp = ramp_at(self.sched, k_tick)
            for p, h in enumerate(helis):
                if not h["alive"]:
                    continue
                a = actions.get(p, {}) or {}
                ca = a.get("collective", "hold")
                ca = ca if ca in COLL else "hold"
                cy = a.get("cyclic", "center")
                cy = cy if cy in CYCLIC else "center"
                wi = a.get("winch", "hold")
                wi = wi if wi in WINCH else "hold"
                if COLL[ca]:
                    h["c"] = min(1.0, max(0.0, round(h["c"] + rw.C_STEP * COLL[ca], 4)))
                h["u"] = CYCLIC[cy]
                h["Ld"] = WINCH[wi]
                h["last"] = (ca, cy, wi)
                self._integrate_ramp(h, co, s.k, nsub, events, p, rp)
        s2 = RWState(seed=s.seed, k=s.k + nsub, t_ms=s.t_ms + dt_ms, helis=helis, ended=s.ended)
        if not s2.ended:
            k2 = s2.t_ms // TICK_MS
            if k2 < N_TICKS and k2 % TICKS_PER_LEVEL == 0 and level_of(k2) != level_of(k_tick):
                events.append(Event(s2.t_ms, "level_up", None, {"level": level_of(k2)}))
            if not any(h["alive"] for h in helis) or s2.t_ms >= self.max_round_ms:
                s2.ended = True
                events.append(Event(s2.t_ms, "round_end", None, {
                    "scores": [self.score(h) for h in helis],
                    "survival_ms": [ranking_key(h) if h["t_crash"] is not None else None for h in helis]}))
        events.sort(key=lambda e: e.t_ms)
        return s2, events

    def ranking(self, s: RWState) -> list[list[int]]:
        """Fail-first: later crash first; helicopters alive at the end (censored) tie at the top."""
        keys = [ranking_key(h) for h in s.helis]
        return [[p for p in range(self.n_players) if keys[p] == v] for v in sorted(set(keys), reverse=True)]

    def state_hash(self, s: RWState) -> str:
        parts = [repr((RULES_VERSION, self.sched, s.seed, s.k, s.t_ms, s.ended))]
        for h in s.helis:
            parts.append(repr(sorted(h.items())))
        return hashlib.sha256("|".join(parts).encode()).hexdigest()

    # -------------------------------------------------------------- views
    def ramp_state(self, s: RWState) -> dict:
        k = s.t_ms // TICK_MS
        rp = ramp_at(self.sched, k)
        return {"k": k, "level": rp.level, "t_s": round(s.t_ms / 1000, 2), "front_x": round(front_m(self.sched, s.k), 3),
                "front_v": rp.front_mm_s / 1000, "roof_drop": rp.roof_mm / 1000, "gust_gain": rp.gust_q / 1024,
                "power_pct": round(100 * rp.power_q / 1024, 1), "next_level_s": round(
                    (TICKS_PER_LEVEL - k % TICKS_PER_LEVEL) * TICK_MS / 1000, 2) if k < N_TICKS else None}

    def render_state(self, s: RWState) -> dict:
        out = super().render_state(s)
        out["course"]["id"] = self.id
        out["ramp"] = self.ramp_state(s)
        for hs, h in zip(out["helis"], s.helis):
            hs["t_crash"] = h["t_crash"]
            hs["front_gap"] = h.get("front_gap")
        return out

    def observe(self, s: RWState, p: int) -> dict:
        """Rotorwash.observe with the lowered roof in the rays, plus the ramp numbers (scripted bots read this)."""
        co = build_course(s.seed)
        o = super().observe(s, p)
        h = s.helis[p]
        k = s.t_ms // TICK_MS
        rc = ramp_course(s.seed, self.sched, k)
        o["rays"] = self.rays(rc, h["x"], h["y"], s.k * DT)
        rp = ramp_at(self.sched, k)
        o.update(level=rp.level, front_gap=h["x"] - REAR - front_m(self.sched, s.k), front_v=rp.front_mm_s / 1000,
                 roof_drop=rp.roof_mm / 1000, gust_gain=rp.gust_q / 1024, power_pct=100 * rp.power_q / 1024,
                 power_margin=100 * (rw.P_AVAIL * rp.power_q / 1024 - h["Preq"]) / (rw.P_AVAIL * rp.power_q / 1024),
                 k=k)
        del co
        return o

    def observation(self, s: RWState, p: int) -> str:
        o = self.observe(s, p)
        rays = ", ".join(f"{n} {d:.1f}" for n, d in zip(RAY_NAMES, o["rays"]))
        lines = [
            self.rules_text,
            f"STATE t={o['t']:.2f}s LEVEL {o['level']}/{N_LEVELS}; front {o['front_gap']:.1f} m behind tail at "
            f"{o['front_v']:.1f} m/s; roof -{o['roof_drop']:.1f} m; gusts x{o['gust_gain']:.2f}; engine power "
            f"{o['power_pct']:.0f}%",
            f"leg {o['leg']}, delivered {o['deliveries']}{', LANDED' if o['landed'] else ''}, fuel {o['fuel']:.0f}%; "
            f"altitude AGL {o['agl']:.1f} m; "
            f"vx {_f(o['vx'])} m/s; vy {_f(o['vy'])} m/s; pitch {_f(o['pitch'])} deg, rate {_f(o['pitch_rate'])} deg/s",
            f"rotor RPM {o['rpm']:.1f}%; collective {o['collective']:.0f}%; cyclic {_f(o['cyclic'])}; "
            f"power margin {_f(o['power_margin'], 0)}%; wind {_f(o['wind'][0])},{_f(o['wind'][1])} m/s (x,y)",
            f"rays to terrain, m (max {RAY_MAX:.0f}): {rays}",
        ]
        if o["hooked"]:
            lines.append(f"load HOOKED; target ship deck: dx {_f(o['target_dx'])} m, dy {_f(o['target_dy'])} m, deck vy "
                         f"{_f(o['pad_vy'])} m/s; rope {o['rope']:.1f} m; load angle {_f(o['load_angle'])} deg, "
                         f"rate {_f(o['load_rate'])} deg/s")
        else:
            lines.append(f"target survivor: dx {_f(o['target_dx'])} m, dy {_f(o['target_dy'])} m; hook timer "
                         f"{o['hook_timer']:.1f}/1.5 s; rope {o['rope']:.1f} m")
        return "\n".join(lines)

    # -------------------------------------------------------------- physics core (Rotorwash._integrate + ramp)
    def _integrate_ramp(self, h: dict, co, k0: int, nsub: int, events: list, p: int, rp: Ramp) -> None:
        """Copy of Rotorwash._integrate (arena/games/rotorwash.py, unchanged there) with the four ramp levers. Every
        added operation is marked RAMP. Module constants are read from `rw` so constant patches apply."""
        F, C, FH, CL, BAY = co.F, co.C, co.FH, co.CL, co.BAY
        WMX, GSX, GSY, SHA, SHY, DD, SHIPC, GX, GY = co.WMX, co.GSX, co.GSY, co.SHA, co.SHY, co.DD, co.SHIPC, co.GX, co.GY
        GM = gap_min(co.seed, self.sched)                               # RAMP roof floor per cell
        FRONT = front_table(self.sched)                                 # RAMP front position table
        drop = rp.roof_mm / 1000                                        # RAMP roof drop (m), exact / 1000
        gain = rp.gust_q / 1024                                         # RAMP storm gain, exact dyadic
        P_AV = rw.P_AVAIL * rp.power_q / 1024                           # RAMP engine fade
        G_, RHO, A_DISC, K_T, OMEGA_N, K_P, P_0, K_G = rw.G, rw.RHO, rw.A_DISC, rw.K_T, rw.OMEGA_N, rw.K_P, rw.P_0, rw.K_G
        TAU_E, I_ROTOR, M_AIR, M_LOAD, T_REF = rw.TAU_E, rw.I_ROTOR, rw.M_AIR, rw.M_LOAD, rw.T_REF
        K_U, D_W, K_TH, GE_GAIN, R_ROTOR = rw.K_U, rw.D_W, rw.K_TH, rw.GE_GAIN, rw.R_ROTOR
        VRS_ON, STALL_R, STALL_T = rw.VRS_ON, rw.STALL_R, rw.STALL_T
        L_MIN, L_MAX, PHI_MAX, LAND_VY, LAND_TH = rw.L_MIN, rw.L_MAX, rw.PHI_MAX, rw.LAND_VY, rw.LAND_TH
        HOOK_DX, HOOK_V, HOOK_DY, HOOK_T, SHIP_HALF = rw.HOOK_DX, rw.HOOK_V, rw.HOOK_DY, rw.HOOK_T, rw.SHIP_HALF
        vrs_loss = rw.vrs_loss
        nG = len(GX) - 1
        wind_on, hold = self.wind_on, self.hold
        kdx, kdy, kdl = (rw.KDX, rw.KDY, rw.KDL) if self.drag_on else (0.0, 0.0, 0.0)
        sfc = rw.SFC if self.burn_on else 0.0
        x, y, vx, vy, th, w, Om, Pe = h["x"], h["y"], h["vx"], h["vy"], h["th"], h["w"], h["Om"], h["Pe"]
        c, u, fuel, att, L, Ldr = h["c"], h["u"], h["fuel"], h["att"], h["L"], h["Ld"]
        phi, phid, landed, hover_t, stall_t = h["phi"], h["phid"], h["landed"], h["hover_t"], h["stall_t"]
        leg, max_x = h["leg"], h["max_x"]
        vrs_on, droop_on, gust_on, fw_on = h["vrs_on"], h["droop_on"], h["gust_on"], h["fw_on"]
        sin, cos, sqrt, exp, tanh = math.sin, math.cos, math.sqrt, math.exp, math.tanh
        surv, ships, nlast = co.surv, co.ships, len(co.ships) - 1
        xlim = co.xmax - 15.0
        wx = wy = 0.0
        loss = 0.0
        Preq = h["Preq"]
        cause = None
        kk = k0
        for _ in range(nsub):
            kk += 1  # event time = end of this substep
            t = (kk - 1) * DT
            m_h = M_AIR + fuel
            m_tot = m_h + M_LOAD if att else m_h
            i = int(x * 0.2)
            if i < 1:
                i = 1
            elif i > co.n - 3:
                i = co.n - 3
            # wind (RAMP: the turbulent part - gusts, shear, downdraft - times the storm gain)
            if wind_on:
                kg = kk - 1 if kk - 1 < nG else nG
                gxs = GSX[i] * GX[kg] * gain
                gys = GSY[i] * GY[kg] * gain
                wx = WMX[i] + gxs
                if SHA[i]:
                    wx += SHA[i] * gain * tanh((y - SHY[i]) * 0.2)
                wy = gys + DD[i] * gain
                gmag = sqrt(gxs * gxs + gys * gys)
                if not gust_on and gmag > 4.0:
                    gust_on = True
                    events.append(Event(round(kk * 1000 / HZ), "gust", p, {"speed": round(gmag, 2)}))
                elif gust_on and gmag < 3.0:
                    gust_on = False
            st, ct = sin(th), cos(th)
            vrx, vry = vx - wx, vy - wy
            fr = x * 0.2 - i
            surf = F[i] + (F[i + 1] - F[i]) * fr
            sj = SHIPC[i]
            if sj >= 0:
                dky, dkv, dka = co.deck(sj, t)
                if abs(x - ships[sj][0]) <= SHIP_HALF and dky > surf:
                    surf = dky
            hh = y + HUB_H * ct - surf
            ge = 1.0 + GE_GAIN * exp(-hh / R_ROTOR) if hh > 0 else 1.0 + GE_GAIN
            vd = -(vrx * st + vry * ct)
            vh = sqrt(m_tot * G_ / (2.0 * RHO * A_DISC))
            loss = 0.0
            if vd > VRS_ON * vh:
                ve = abs(vrx * ct - vry * st)
                loss = vrs_loss(vd, ve, vh)
            if not vrs_on and loss > 0.05:
                vrs_on = True
                events.append(Event(round(kk * 1000 / HZ), "vortex_ring", p, {"loss": round(loss, 3)}))
            elif vrs_on and loss < 0.01:
                vrs_on = False
            r = Om / OMEGA_N
            Tb = K_T * r * r * c
            T = Tb * (1.0 - loss) * ge
            Preq = K_P * Tb ** 1.5 + P_0 * r * r * r
            Pcmd = Preq + K_G * (1.0 - r) * P_AV                        # RAMP P_AV (was P_AVAIL)
            Pcmd = 0.0 if Pcmd < 0.0 else (P_AV if Pcmd > P_AV else Pcmd)
            Pe += (Pcmd - Pe) * (DT / TAU_E)
            Om += (Pe - Preq) / (I_ROTOR * Om) * DT
            if Om < 1.0:
                Om = 1.0
            fuel -= sfc * Pe * DT
            Ld = Ldr
            L += Ld * DT
            if L < L_MIN:
                L, Ld = L_MIN, 0.0
            elif L > L_MAX:
                L, Ld = L_MAX, 0.0
            if landed >= 0:
                dky, dkv, dka = co.deck(landed, t)
                if T > m_tot * (G_ + dka):
                    landed = -1
                    vy = dkv
                else:
                    y = dky + SKID_H
                    vy = dkv
                    vx = 0.0
                    th = w = 0.0
            if landed < 0:
                sp_air = sqrt(vrx * vrx + vry * vry)
                ahx = (T * st - kdx * sp_air * vrx) / m_h
                ahy = (T * ct - kdy * sp_air * vry) / m_h - G_
                if att:
                    sp_, cp_ = sin(phi), cos(phi)
                    lvx = vx + Ld * sp_ + L * phid * cp_
                    lvy = vy - Ld * cp_ + L * phid * sp_
                    lrx, lry = lvx - wx, lvy - wy
                    lsp = sqrt(lrx * lrx + lry * lry)
                    fdx, fdy = -kdl * lsp * lrx, -kdl * lsp * lry
                    if hold:
                        ahx = ahy = 0.0
                        mu = M_LOAD
                    else:
                        mu = M_LOAD * m_h / (M_LOAD + m_h)
                    phidd = (-G_ * sp_ + (fdx * cp_ + fdy * sp_) / M_LOAD - (ahx * cp_ + ahy * sp_)
                             - 2.0 * Ld * phid) / L
                    Tr = mu * (G_ * cp_ + L * phid * phid + (fdx * sp_ - fdy * cp_) / M_LOAD - (ahx * sp_ - ahy * cp_))
                    if Tr < 0.0:
                        Tr = 0.0
                    ahx += Tr * sp_ / m_h
                    ahy -= Tr * cp_ / m_h
                    phid += phidd * DT
                    phi += phid * DT
                if not hold:
                    alpha = K_U * (T / T_REF) * u - D_W * w - K_TH * th
                    w += alpha * DT
                    th += w * DT
                    vx += ahx * DT
                    vy += ahy * DT
                    x += vx * DT
                    y += vy * DT
            if x > max_x:
                max_x = x
            # ---- failures
            if r < STALL_R:
                stall_t += DT
                if stall_t > STALL_T:
                    cause = "rotor_stall"
            else:
                stall_t = 0.0
            if not droop_on and r < 0.95:
                droop_on = True
                events.append(Event(round(kk * 1000 / HZ), "rpm_droop", p, {"rpm_pct": round(100 * r, 1)}))
            elif droop_on and r > 0.97:
                droop_on = False
            if fuel <= 0.0:
                fuel = 0.0
                cause = cause or "fuel"
            if att and (phi > PHI_MAX or phi < -PHI_MAX):
                cause = cause or "sling_swing"
            # RAMP collapse front (integer position; one float multiply, compared exactly with an int)
            fu = FRONT[kk]
            if cause is None and fu >= (x - REAR) * FRONT_U_PER_M:
                cause = "collapse"
            if not fw_on and fu >= (x - REAR - WARN_ON) * FRONT_U_PER_M:
                fw_on = True
                events.append(Event(round(kk * 1000 / HZ), "front_warn", p, {"gap": round(x - REAR - fu / FRONT_U_PER_M, 2)}))
            elif fw_on and fu < (x - REAR - WARN_OFF) * FRONT_U_PER_M:
                fw_on = False
            # ---- collisions (RAMP: ceiling = max(C - drop, F + GM) at the polyline nodes)
            if cause is None and landed < 0 and not hold:
                if x < 8.0 or x > xlim:
                    cause = "terrain"
                else:
                    i = int(x * 0.2)
                    near_ship = SHIPC[i] >= 0
                    if near_ship or FH[i] > y - EXTENT or CL[i] - drop < y + EXTENT:
                        st, ct = sin(th), cos(th)
                        skid_deck = False
                        if near_ship:
                            sj = SHIPC[i]
                            sx0 = ships[sj][0]
                            dky, dkv, dka = co.deck(sj, kk * DT)
                        for bx, by, kind in POINTS:
                            px = x + bx * ct + by * st
                            py = y - bx * st + by * ct
                            ii = int(px * 0.2)
                            fr = px * 0.2 - ii
                            c0 = C[ii] - drop
                            f0 = F[ii] + GM[ii]
                            if f0 > c0:
                                c0 = f0
                            c1 = C[ii + 1] - drop
                            f1 = F[ii + 1] + GM[ii + 1]
                            if f1 > c1:
                                c1 = f1
                            ce = c0 + (c1 - c0) * fr
                            if py >= ce:
                                cause = "ceiling"
                                break
                            if near_ship and abs(px - sx0) <= SHIP_HALF and py <= dky:
                                if kind == "s":
                                    skid_deck = True
                                    continue
                                cause = "ship_strike"
                                break
                            fl = F[ii] + (F[ii + 1] - F[ii]) * fr
                            if py <= fl:
                                if BAY[ii] or BAY[ii + 1]:
                                    cause = "water"
                                else:
                                    cause = {"r": "rotor_strike", "t": "tail_strike"}.get(kind, "terrain")
                                break
                        if cause is None and skid_deck:
                            if vy - dkv < -LAND_VY:
                                cause = "hard_landing"
                            elif abs(th) >= LAND_TH:
                                cause = "landing_attitude"
                            else:
                                landed = sj
                                y, vy, vx, th, w = dky + SKID_H, dkv, 0.0, 0.0, 0.0
                                if att:
                                    att = False
                                    h["deliveries"] += 1
                                    leg = max(leg, sj + 1)
                                    if leg > nlast:
                                        leg = nlast
                                    phi = phid = 0.0
                                    events.append(Event(round(kk * 1000 / HZ), "delivered", p,
                                                        {"leg": sj, "ship": ships[sj][0]}))
            if cause is not None:
                break
            while leg < nlast and x > ships[leg][0] + 30.0:
                leg += 1
            if not att and landed < 0 and leg >= h["surv_min"]:
                sxv, syv = surv[leg]
                if (abs(x - sxv) <= HOOK_DX and vx * vx + vy * vy < HOOK_V * HOOK_V
                        and y - L - syv <= HOOK_DY):
                    hover_t += DT
                    if hover_t >= HOOK_T:
                        att = True
                        h["surv_min"] = leg + 1
                        hover_t = 0.0
                        dy_ = y - syv
                        if L > dy_:
                            L = max(L_MIN, dy_)
                        phi = phid = 0.0
                        events.append(Event(round(kk * 1000 / HZ), "hooked", p, {"leg": leg}))
                else:
                    hover_t = 0.0
            else:
                hover_t = 0.0
        h.update(x=x, y=y, vx=vx, vy=vy, th=th, w=w, Om=Om, Pe=Pe, fuel=fuel, att=att, L=L, phi=phi, phid=phid,
                 landed=landed, hover_t=hover_t, stall_t=stall_t, leg=leg, max_x=max_x, vrs_on=vrs_on,
                 droop_on=droop_on, gust_on=gust_on, fw_on=fw_on, loss=loss, Preq=Preq, wx=wx, wy=wy,
                 front_gap=round(x - REAR - FRONT[kk] / FRONT_U_PER_M, 3))
        if cause is not None:
            h["alive"] = False
            h["cause"] = cause
            h["t_crash"] = round(kk * 1000 / HZ)
            events.append(Event(h["t_crash"], "crash", p, {"cause": cause, "x": round(x, 2), "y": round(y, 2)}))
        elif not wind_on:
            h["wx"] = h["wy"] = 0.0


# ------------------------------------------------------------------ game wrapper (rules id, variants, lock)

RULES_LOCK = threading.RLock()
PATCHABLE = ("P_AVAIL", "STALL_R", "LAND_VY")
DEFAULTS = {k: getattr(rw, k) for k in PATCHABLE}   # captured at import (the frozen v1 values)


@contextlib.contextmanager
def _patched(values: dict):
    """Set EVERY patchable constant (defaults overlaid with `values`) for the duration, restoring the previous
    values after. Setting the defaults explicitly makes a nested base-rules call inside a variant context see the
    base rules (the planner's 'base reading' for flip shares)."""
    with RULES_LOCK:
        want = {**DEFAULTS, **values}
        old = {k: getattr(rw, k) for k in want}
        try:
            for k, v in want.items():
                setattr(rw, k, v)
            yield
        finally:
            for k, v in old.items():
                setattr(rw, k, v)


class RampGame:
    """Game protocol (arena.core.Game) for Rotorwash-Ramp: rules text + optional variant (announced or not), like
    arena.v2.variants.GameV2 for the v2 games. `engine` is the RotorwashRamp the scripted bots observe."""

    def __init__(self, variant: str | None = None, announce: bool = True, sensors: bool = True, n_players: int = 4):
        self.variant = VARIANTS[variant] if variant else None
        self.announce, self.sensors = announce, sensors
        text = RULES + (" " + self.variant.announce_text if self.variant and announce else "")
        sched = self.variant.schedule if self.variant and self.variant.schedule else BASE
        self.engine = RotorwashRamp(sched, text, n_players)
        self.rules_text = text
        self.id, self.game_id = GAME_ID, GAME_ID
        self.n_players = self.engine.n_players
        self.decision_period_ms = TICK_MS
        self.max_round_ms = MAX_ROUND_MS

    @property
    def rules_id(self) -> str:
        v = self.variant.id if self.variant else "base"
        ann = "announced" if self.announce or not self.variant else "unannounced"
        return f"{GAME_ID}:{RULES_VERSION}:{v}:{ann}:{'L1' if self.sensors else 'L0'}"

    @property
    def schedule(self) -> Schedule:
        return self.engine.sched

    def ctx(self):
        return _patched(self.variant.patch if self.variant else {})

    def reset(self, seed):
        with self.ctx():
            return self.engine.reset(seed)

    def queries(self, s, player, answers):
        with self.ctx():
            return self.engine.queries(s, player, answers)

    def multi_query(self, s, player):
        from nagi.burst2._rt.arena.games.chord import rotorwash_mq
        with self.ctx():
            return rotorwash_mq(self.engine, s, player)

    def step(self, s, actions, dt_ms):
        with self.ctx():
            return self.engine.step(s, actions, dt_ms)

    def done(self, s):
        return self.engine.done(s)

    def ranking(self, s):
        return self.engine.ranking(s)

    def render_state(self, s):
        with self.ctx():
            return self.engine.render_state(s)

    def state_hash(self, s):
        return self.engine.state_hash(s)


# ------------------------------------------------------------------ determinism receipt

def hash_steps(n_steps: int = 1000) -> str:
    """sha256 over the state hashes + seat-0 prompt texts of n_steps ticks: v3 calib seeds 0, 1, ... of this game,
    the planner in seat 0 and the ghosts rw1_creep, rw2_naive, rwP_ramp (the ORIGINAL ladder ids, pinned so the
    engine chain stays comparable with the recorded Linux value after the 2026-09-27 rung change), cycling base and
    every variant (announced), all lockstep. Float engine: compare on the recording platform (the docs give the
    macOS arm64 value)."""
    from nagi.burst2._rt.arena.games.rotorwash_ramp_bots import make_ramp_bot, ramp_seed
    LADDER_IDS = ("rw1_creep", "rw2_naive", "rwP_ramp")
    h, steps, i, order = hashlib.sha256(), 0, 0, [None, *VARIANTS]
    while steps < n_steps:
        g = RampGame(order[i % len(order)])
        seed = ramp_seed("calib", i)
        bots = [make_ramp_bot(b).bind(p, seed) for p, b in enumerate((LADDER_IDS[-1], *LADDER_IDS))]
        s = g.reset(seed)
        h.update(g.state_hash(s).encode())
        with g.ctx():
            while not g.done(s) and steps < n_steps:
                acts = {}
                for p, b in enumerate(bots):
                    qs = g.queries(s, p, {})
                    if qs:
                        b.see(g, s)
                        acts[p] = {q.key: b.choose(q) for q in qs}
                        if p == 0:
                            h.update(qs[0].text.encode())
                s, _ = g.step(s, acts, TICK_MS)
                h.update(g.state_hash(s).encode())
                steps += 1
        i += 1
    return h.hexdigest()
