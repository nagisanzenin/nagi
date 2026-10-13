"""BOOSTER GAUNTLET (Arena v3, fail-first): an endless chain of short booster landing hops on a drone ship, with a
difficulty ramp driven by the GLOBAL game clock until every player crashes. docs/arena_v3/BOOSTER_GAUNTLET.md.

Engineering spec (the text every model reads is `rules_text(rules)`):

* Frame and units. 2D side view, x right, y up (sea level y = 0), SI units in the text. Engine state is FIXED-POINT
  integers only (mm, mm/s, grams, newtons, binary angle units, BAM = 2^-20 turn): no float, no libm, no numpy in
  reset/step, so the state hash is bit-exact on every platform (GAME_BRIEF req. 3; handbook R3.13 / ch4). The integer
  sin/cos table, round-half-up division and the density table are reused from arena.games.booster (v1, same tests).
* Time. Physics substep 50 ms (semi-implicit Euler). One decision every 250 ms (4 Hz, FIXED: the v3 runner assumes
  it); controls hold between decisions. Round cap 60 s (Amendment 2; levels L1-L6); a booster still flying at the cap is right-censored.
* Round shape (FAIL_FIRST_BRIEF + Amendment 1). The booster is dropped above the ship; after every successful
  touchdown it is immediately re-dropped (legs stowed, engine off, fuel and relights refilled) into the next hop. A
  crash ends the round for that player. There is no success terminal state.
* Difficulty ramp. Every difficulty parameter is a piecewise-LINEAR function of the global clock t (knots every
  10 s, `RAMP`), evaluated per substep, so there are no step walls; levels L = 1 + floor(t / 10 s) are display
  labels only (banner + chime). Environment parameters (wind, gust strength, sea heave / pitch / surge, landing-zone
  half-width) follow the CURRENT clock. Hop parameters (drop height, drop speed, lateral miss and drift, fuel) are
  read from the clock AT THE HOP'S DROP, and the seeded jitter of a drop is keyed by its drop tick, so the schedule
  is a function of the clock only (never of hop count): two players dropping on the same tick get the same hop.
  Relights per hop: 3 before 17 s, 2 before 37 s, 1 after (the only integer steps, placed mid-level).
  Stalling cannot buy easier hops: a later drop only reads a harder point of the ramp, and every hop must touch
  down within HOP_LIMIT_MS = 22 s of its drop ('hop_timeout' otherwise; min thrust > weight, so no hovering).
* Body. Mass m = 25 t dry + fuel. I = m (11 m)^2. Attitude th = tilt of the body from vertical, + = top leans to +x
  (clockwise); omega = d th / dt. CG to engine plane 14 m, to grid fins 26 m, body normal-force centre 6 m below the
  CG (engine-first flight is aerodynamically unstable without fins).
* Engine. Levels off / min / mid / max = 0 / f_min / 560 kN / 980 kN; f_min from the rule twr_min = min thrust /
  weight at M_REF = 28 t (base 1.25 -> 343 kN): thrust > weight at every fuel load (no hover). Mass flow
  T / (282 s g0). An off -> lit command uses one relight (none left: ignored); ignition delay 0.3 s; thrust slews
  2,000 kN/s up, 6,000 kN/s down. Gimbal commands -5, -2, 0, +2, +5 deg, slew 20 deg/s; the thrust vector is the
  body axis rotated by -gimbal, torque 14 m x T x sin(gimbal) (gimbal R -> top toward +x; rule gimbal_sign flips it).
* Atmosphere and wind. rho from the v1 table (1.225 exp(-h / 8.5 km)). Horizontal wind at altitude y and substep k:
  w = (W_mean(t) * s_w + sigma_g(t) * gust_unit(k)) * (1 + min(y, 1 km) / 2 km), s_w = seeded sign; gust_unit is a
  seeded AR(1) series on 1 s knots (phi 0.6, unit variance), linear in between.
* Aerodynamics (v1 model plus broadside crossflow so that low-speed wind matters): f = -v_a/|v_a|, f_ax = f.b,
  crossflow f_c = f - f_ax b, s = |f_c| = sin(alpha):
    axial     q (10.75 m^2 + 1.5 m^2 fins_out + 6 m^2 legs_out) f_ax along b
    normal    q (21.5 m^2 + 150 m^2 s) f_c at 6 m below the CG  +  q 12 m^2 fins_out f_c at 26 m above
    fin ctrl  q 1.2 m^2 fins_out deflection f_ax along (cos th, -sin th) at 26 m (rule fin_sign flips it)
    damping   -40,000 m^4 q / |v_a| omega
* Limits: q > 60 kPa 'max_q'; q sin(alpha) > 6 kPa 'breakup'; legs not stowed at q > 12 kPa 'legs_torn'; fuel out
  = flameout; hop older than 22 s 'hop_timeout'; |tilt| > 90 deg 'tumble'.
* Drone ship (shared by all players; a pure function of the seed and the clock): hull half-width 45 m, deck 8 m above
  the sea; surge x_s = A_s(t) sin, heave y = 8 m + A_h(t) sin, pitch A_p(t) sin (seeded periods and phases). The
  painted landing zone |x - x_s| <= Z(t) shrinks with the clock. Deck velocities are exact integer finite differences
  over one substep.
* Touchdown when the lowest point (engine plane 14 m below the CG; with legs, feet 1.5 m lower and 9 m out) reaches
  the deck surface (hull) or the sea. Success: legs 100 %, inside the zone, |vy_rel| <= 3.0 m/s, |vx_rel| <= 2.0 m/s,
  |tilt - deck pitch| <= 6 deg, |omega| <= 6 deg/s. Else 'splashdown' (sea), 'no_legs', 'hard_landing',
  'tip_over', 'off_zone' (on the deck but outside the zone).
* Scores (per booster): survival t_fail (ms; 60 s censored), level at failure, hops landed (game score), landing
  quality (mean over landings of 1 - max normalised touchdown error, micro-units). Ranking: later failure first, then
  more hops, then quality.
* Queries (4 simultaneous per flying booster, canonical order): throttle (off, min, mid, max), gimbal (L2, L1, 0, R1,
  R2), fins (stowed, left, neutral, right), legs (stowed, deploy). Query defaults = the current command.
* Events: 'drop' {hop, level}, 'ignition' {relights_left}, 'shutdown', 'no_relight', 'flameout', 'legs',
  'low_fuel' {fuel_kg}, 'landed' {hop, level, quality_micro, dx_mm, vy_mms}, 'crash' {cause, x, y (m), level, hops},
  'level' {level}
  (player None), 'round_end' {survival_ms}.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from functools import lru_cache
from math import isqrt

from nagi.burst2._rt.arena.core import Event, Query
from nagi.burst2._rt.arena.games.booster import (ONE, ONE_BITS, TURN, TURN_BITS, TWO_PI_Q40, _fmt_int, bam_to_mdeg, deg_to_bam, icos,
                                 isin, rdiv, rho_at, wrap_bam)

# ================================================================== constants (integers; SI in the comments)
SUB_MS = 50
SUB_HZ = 20
DECISION_MS = 250
MAX_ROUND_MS = 60_000  # FAIL_FIRST_BRIEF Amendment 2: T_cap = 60 s, levels L1-L6
N_LEVELS = 6
LEVEL_MS = 10_000
N_SUB = MAX_ROUND_MS // SUB_MS + 2 * SUB_HZ  # precomputed environment tables (with slack)
RELEASE_MS = 500  # g1.1: engine and legs locked for 0.5 s after each drop (stale commands from the last hop)
HOP_LIMIT_MS = 22_000  # not a multiple of the 10 s level length (no timeouts on level boundaries); g1.1: 18 -> 22 s

G_MM = 9810
M_DRY = 25_000_000  # g
M_REF = 28_000_000  # g: twr_min reference mass (25 t + 3 t)
T_MID, T_MAX = 560_000, 980_000  # N
ISP_G0 = 282 * 980665
THR_UP, THR_DN = 100_000, 300_000  # N per substep (2,000 / 6,000 kN/s)
IGN_SUB = 6  # base ignition delay 0.3 s (rules.ign_ms)
GIM_OPTS = ("L2", "L1", "0", "R1", "R2")
GIM_MDEG = {"L2": -5000, "L1": -2000, "0": 0, "R1": 2000, "R2": 5000}
GIM_RATE = deg_to_bam(20_000) // SUB_HZ
THR_OPTS = ("off", "min", "mid", "max")
FIN_OPTS = ("stowed", "left", "neutral", "right")
FIN_U = {"stowed": 0, "left": -1000, "neutral": 0, "right": 1000}
LEG_OPTS = ("stowed", "deploy")
FIN_DEP_RATE, FIN_U_RATE = 50, 200

L_ENG = 14_000
D_FIN = 26_000
D_BODY = -6_000
R_BODY = 1_850
LEG_DOWN, LEG_SPAN = 1_500, 9_000
K2 = 121
SC_A_BODY, SC_A_FIN, SC_A_LEG = 107_500, 15_000, 60_000  # cm^2
SC_N_BODY, SC_N_FIN, SC_FC, SC_X = 215_000, 120_000, 12_000, 1_500_000  # cm^2 (SC_X: broadside crossflow)
K_DAMP = 40_000
Q_MAX, QA_MAX, Q_LEG = 60_000, 6_000, 12_000
V_AERO = 1_000
TUMBLE = TURN // 4

SHIP_HW, DECK_H = 45_000, 8_000  # mm
DECK_MARGIN = 6_000  # mm: the pitched deck edge stays below deck_y + 6 m (45 m x tan 5 deg = 3.9 m)
LAND_VY, LAND_VX, LAND_TILT, LAND_RATE = 3_000, 2_000, 6, 6
LOW_FUEL_PM = 250  # 'low_fuel' warning below 25 % of the hop's fuel

# ------------------------------------------------------------------ the ramp (knots at t = 0, 10, ..., 60 s)
# Every row is linearly interpolated per substep between knots (continuous; Amendment 1). Units in the names.
RAMP = {
    "h0_m": (780, 700, 620, 545, 470, 410, 360),  # drop height of the engine plane above the deck
    "v0_mps": (58, 76, 98, 120, 146, 168, 185),  # drop sink speed
    "miss_m": (20, 40, 62, 84, 106, 128, 150),  # max |lateral miss| at the drop (seeded in 40-100 %)
    "vx0_mps": (2, 5, 8, 11, 14, 17, 20),  # max |lateral drift| at the drop
    "fuel_kg": (4200, 3780, 3300, 2950, 2550, 2300, 2100),
    "zone_m": (30, 25.5, 20, 15.5, 11, 9, 7),  # landing zone half-width
    "wind_mps": (2, 3.5, 5.5, 7.75, 11, 13.5, 15.5),  # mean wind at the deck (seeded sign)
    "gust_mps": (0.5, 1.25, 2, 2.75, 3.8, 4.6, 5.2),  # gust sigma
    "heave_m": (0.2, 0.65, 1.1, 1.55, 2.0, 2.45, 2.9),
    "pitch_deg": (0.3, 1.05, 1.8, 2.55, 3.3, 4.05, 4.8),
    "surge_m": (1, 2.5, 4, 5.5, 7, 8.5, 10),
    # g1.1 (1-tick-delay ladder): both rows are linear between the knots the rules text states (0, 30, 60 s)
    "twr_min": (0.85, 0.983, 1.117, 1.25, 1.317, 1.383, 1.45),  # min-throttle TWR at 28 t, read at each drop
    "tol": (2.0, 1.667, 1.333, 1.0, 0.95, 0.9, 0.85),  # touchdown limits x this at the touchdown clock
}
RELIGHT_STEPS = ((17_000, 3), (37_000, 2), (10 ** 9, 1))  # relights per hop by drop time (mid-level steps)


def _knots_milli(row) -> tuple:
    return tuple(int(round(v * 1000)) for v in row)


RAMP_MILLI = {k: _knots_milli(v) for k, v in RAMP.items()}


def ramp(name: str, t_ms: int) -> int:
    """Ramp value x 1000 at clock t (integer, linear between 10 s knots, clamped after the last knot)."""
    kn = RAMP_MILLI[name]
    i = t_ms // LEVEL_MS
    if i >= len(kn) - 1:
        return kn[-1]
    a, b = kn[i], kn[i + 1]
    f = t_ms - i * LEVEL_MS
    return a + (b - a) * f // LEVEL_MS


def level_at(t_ms: int) -> int:
    return 1 + t_ms // LEVEL_MS


def relights_at(t_ms: int, rules) -> int:
    n = next(v for lim, v in RELIGHT_STEPS if t_ms < lim)
    return min(n, rules.relights_cap)


# ================================================================== rules and variants


@dataclass(frozen=True)
class Rules:
    twr_add: int = 0  # x100 added to the clock's min-throttle TWR (variants)
    relights_cap: int = 3  # relights per hop never exceed this (base: the ramp decides)
    t_max: int = T_MAX  # N, max throttle
    legs_ms: int = 2000  # leg deploy time
    ign_ms: int = 300  # ignition delay (multiple of 50 ms)
    gimbal_sign: int = 1  # +1: gimbal R turns the top to +x; -1: reversed
    fin_sign: int = 1  # +1: fins right turn the top to +x; -1: reversed
    wind_mult: int = 10  # x10 on mean wind and gusts
    land_vy: int = LAND_VY
    land_vx: int = LAND_VX
    land_tilt: int = LAND_TILT
    land_rate: int = LAND_RATE

    def twr_at(self, t_ms: int) -> int:
        """Min-throttle TWR x1000 at M_REF for a hop dropped at clock t (the ramp row + the variant offset)."""
        return ramp("twr_min", t_ms) + 10 * self.twr_add

    def t_min_at(self, t_ms: int) -> int:
        return rdiv(self.twr_at(t_ms) * M_REF * G_MM, 1000 * 1000 * 1000)

    def thrust(self, lvl: str, h: dict) -> int:
        """Thrust (N) of a lit level for booster h (min = its hop's min thrust, fixed at the drop)."""
        return {"off": 0, "min": h["tmin"], "mid": T_MID, "max": self.t_max}[lvl]

    @property
    def leg_rate(self) -> int:
        assert 1000 * SUB_MS % self.legs_ms == 0, self.legs_ms  # exact: legs_ms in {2000, 2500, 5000, ...}
        return 1000 * SUB_MS // self.legs_ms


BASE_RULES = Rules()


@dataclass(frozen=True)
class Variant:
    id: str
    split: str
    rules: Rules
    announce_text: str
    control: str


VARIANTS = {v.id: v for v in (
    Variant("twr_soft", "variant_dev", replace(BASE_RULES, twr_add=-15),
            "RULE CHANGE: min throttle TWR is 0.15 lower than the schedule.", "throttle"),
    Variant("twr_hard", "variant_sealed", replace(BASE_RULES, twr_add=30),
            "RULE CHANGE: min throttle TWR is 0.30 higher than the schedule.", "throttle"),
    Variant("max_derated", "variant_dev", replace(BASE_RULES, t_max=760_000),
            "RULE CHANGE: max throttle is derated to 760 kN (not 980 kN).", "throttle"),
    Variant("ignition_slow", "variant_sealed", replace(BASE_RULES, ign_ms=1000),
            "RULE CHANGE: engine ignition delay is 1.0 s (not 0.3 s).", "throttle"),
    Variant("legs_slow", "variant_sealed", replace(BASE_RULES, legs_ms=5000),
            "RULE CHANGE: legs take 5 s to deploy (not 2 s).", "legs"),
    Variant("gimbal_reversed", "variant_dev", replace(BASE_RULES, gimbal_sign=-1),
            "RULE CHANGE: gimbal is wired reversed: gimbal R turns the top to -x.", "gimbal"),
    Variant("fins_reversed", "variant_sealed", replace(BASE_RULES, fin_sign=-1),
            "RULE CHANGE: fins are wired reversed: fins right turn the top to -x.", "fins"),
    Variant("wind_calm", "variant_dev", replace(BASE_RULES, wind_mult=0),
            "RULE CHANGE: no wind and no gusts.", "fins"),
    Variant("wind_strong", "variant_sealed", replace(BASE_RULES, wind_mult=20),
            "RULE CHANGE: wind and gusts 2x stronger.", "gimbal"),
    Variant("land_strict", "variant_dev", replace(BASE_RULES, land_vy=1_500, land_vx=1_000, land_tilt=3, land_rate=3),
            "RULE CHANGE: all touchdown limits are halved.", "throttle"),
    Variant("land_lenient", "variant_sealed",
            replace(BASE_RULES, land_vy=6_000, land_vx=4_000, land_tilt=12, land_rate=12),
            "RULE CHANGE: all touchdown limits are doubled.", "throttle"),
)}


def rules_for(variant: str | None) -> Rules:
    return VARIANTS[variant].rules if variant else BASE_RULES


def assert_not_sealed(variant_id: str | None, purpose: str) -> None:
    if variant_id and VARIANTS[variant_id].split == "variant_sealed":
        raise PermissionError(f"variant {variant_id} is SEALED; not allowed for {purpose}")


RULES_VERSION = "g1.1"
# Rules versions the engine can play. The physics, seeds, controls and the rules PARAGRAPH (whose "(rules g1.1)" tag
# names the model-facing text version, unchanged since g1.1) are identical in both; only the L1 sensor and the record
# differ, so an L0 g1.2 prompt is byte-identical to its g1.1 prompt (tests/test_arena_v31.py regenerates the recorded
# release prompt sha256s under g1.2).
#   g1.1  (default; Arena v3, Board 1, Burst release, NC-0): historical and byte-identical, including its L1 sensor,
#         whose stop_heights() divides by a negative deceleration when a lit level cannot stop the fall (TWR <= 1) and
#         prints a bogus height (C_experiments.md F5). Keep it only to replay / regenerate old records.
#   g1.2  (Arena v3.1, docs/arena_v31/README.md): the L1 sensor prints "cannot stop" for such a level and sensor_top
#         no longer falls through to 'off' on the bogus height; render_state() exposes every touchdown's normalised
#         errors (td.err, the failing hop's E for the K3 score, arena.games.booster_gauntlet_v31).
RULES_VERSIONS = ("g1.1", "g1.2")
TD_CAUSES = ("no_legs", "hard_landing", "tip_over", "off_zone")   # crashes ON the deck (a touchdown with an error E)


def rules_text(rules: Rules = BASE_RULES, variant: Variant | None = None, announce: bool = True) -> str:
    b = BASE_RULES

    def knots(row, fmt):
        return ", ".join(f"{fmt(ramp(row, t * 1000))} at {t} s" for t in (0, 30, 60))
    t = (f"BOOSTER GAUNTLET (rules {RULES_VERSION}): 2D, x right, y up, SI. Land the falling booster in the ship's "
         "zone; each landing re-drops it; a crash ends the run (cap 60 s). Each 10 s level: lower, faster drops, "
         "less fuel, more wind and waves, smaller zone. Relights per hop 3, 2 after 17 s, 1 after 37 s. Decide every "
         "0.25 s; controls hold. Tilt + = top to +x; gimbal R and fins right turn the top to +x. Thrust along the "
         "body, max 980 kN; min TWR (28 t) by drop time: "
         + knots("twr_min", lambda v: _fmt_int(v, 1000, 2, False)) + " (above 1 no hover). Starts use a relight, "
         f"0.3 s delay; engine and legs locked {RELEASE_MS / 1000:g} s after a drop. Fins steer only at speed; "
         "stowed fins tumble. Legs take 2 s, tear off above q 12 kPa. Touchdown: legs down, in the zone; vs the "
         f"deck sink <= {_fmt_int(b.land_vy, 1000, 1, False)}, drift <= {_fmt_int(b.land_vx, 1000, 1, False)} m/s, "
         f"tilt <= {b.land_tilt} deg, rate <= {b.land_rate} deg/s, "
         + knots("tol", lambda v: "x" + _fmt_int(v, 1000, 2, False).rstrip("0").rstrip("."))
         + f". Land within {HOP_LIMIT_MS // 1000} s of a drop.")
    if variant is not None and announce:
        t += " " + variant.announce_text
    return t


# ------------------------------------------------------------------ NC-0 prompt styles (docs/nc0/, NC0_PREREG.md)
# Only the model-facing TEXT differs between styles: physics, seeds, controls, options, defaults and scoring are the
# same objects. "g1.1" (default) is the Arena v3 text above, byte-identical. "p1" states the facts precisely (objective,
# timeout = failure, TWR meaning, signs, limits, time left in the hop); "p2" = p1 + derived kinematics (the fixed
# stop-height sensor: "cannot stop" when a level cannot stop the fall, C F5; time to deck level). Facts only: no
# strategy, no suggested option (sensor_top stays hidden: the p styles run at L0). Base rules only (no variants).
PROMPT_STYLES = ("g1.1", "p1", "p2")
DEFAULT_PROMPT_STYLE = "g1.1"


def rules_text_p(rules: Rules = BASE_RULES) -> str:
    """The p1/p2 rules paragraph (base rules; numbers from the engine constants). Same length class as g1.1 (the
    prompt stays inside the served token range and the reply latency does not change the task, C F6): schedules the
    state already gives for the current hop (relights left, TWR now, touchdown limits now) are stated in the state
    lines instead of as clock tables."""
    assert rules == BASE_RULES, "prompt styles p1/p2 support the base rules only"
    return (f"BOOSTER GAUNTLET (rules {RULES_VERSION}): 2D, x right, y up, SI; vy < 0 = falling; tilt, rate + = top to "
            "+x; ship dx = ship x - booster x. Land the falling booster in the ship's zone; each landing re-drops it, "
            f"refuelled. The run ends at the first failure (cap {MAX_ROUND_MS // 1000} s). Failure = a crash, or no "
            f"landing within {HOP_LIMIT_MS // 1000} s of a drop: hovering or climbing until then fails like a crash. "
            "Decide every 0.25 s; "
            "controls hold. Thrust is along the body; gimbal R and fins right turn the top to +x. TWR = thrust / "
            "current weight; min thrust is fixed per hop. Upright, no drag: TWR < 1 = a fall keeps speeding up, "
            "slower than free fall; TWR > 1 = a fall slows, stops, then climbs. Lighting uses a "
            f"relight, {rules.ign_ms / 1000:g} s delay; engine and legs locked {RELEASE_MS / 1000:g} s after a drop. "
            f"Fins steer only at speed; stowed fins tumble. Legs take {rules.legs_ms / 1000:g} s, tear off above q "
            f"{Q_LEG // 1000} kPa. Touchdown: legs down, in the zone, within the limits vs the deck; else a crash.")


# ================================================================== scenario (seeded, integer)


def _h(seed: int, key: str) -> int:
    return int.from_bytes(hashlib.sha256(f"gauntlet|{int(seed)}|{key}".encode()).digest()[:8], "big")


def _u(seed: int, key: str, lo: int, hi: int) -> int:
    return lo + _h(seed, key) % (hi - lo + 1)


GUST_N = MAX_ROUND_MS // 1000 + 14


@dataclass(frozen=True)
class Scenario:
    """Environment tables per substep k (pure function of seed and rules): wind at the deck (mm/s), ship centre x,
    deck y at the centre, pitch (BAM), their velocities (mm/s, BAM/s), zone half-width (mm)."""
    seed: int
    rules: Rules
    wind: tuple
    ship_x: tuple
    ship_y: tuple
    ship_p: tuple
    ship_vx: tuple
    ship_vy: tuple
    ship_pr: tuple
    zone: tuple


def _gust_unit(seed: int) -> tuple:
    """Unit-variance AR(1) series on 1 s knots (milli-units), phi = 0.6."""
    out, g = [], 0
    for j in range(GUST_N):
        e = sum(_u(seed, f"g{j}_{m}", -1000, 1000) for m in range(4))  # sd ~ 1155
        g = (g * 6 + e * 8 * 1000 // 1155) // 10  # AR(1) phi 0.6, innovation 0.8: stationary sd ~ 1000
        out.append(g)
    return tuple(out)


@lru_cache(maxsize=512)
def build_scenario(seed: int, rules: Rules = BASE_RULES) -> Scenario:
    sgn = 1 if _u(seed, "w_sign", 0, 1) else -1
    gu = _gust_unit(seed)
    per = {"s": _u(seed, "surge_T", 12, 18), "h": _u(seed, "heave_T", 6, 9), "p": _u(seed, "pitch_T", 7, 10)}
    ph = {c: _u(seed, f"ph_{c}", 0, TURN - 1) for c in "shp"}
    wind, sx, sy, sp, zone = [], [], [], [], []
    for k in range(N_SUB + 1):
        t = k * SUB_MS
        j = k // SUB_HZ
        g0, g1 = gu[min(j, GUST_N - 1)], gu[min(j + 1, GUST_N - 1)]
        gk = g0 + (g1 - g0) * (k - j * SUB_HZ) // SUB_HZ  # milli-sigma
        w = sgn * ramp("wind_mps", t) + ramp("gust_mps", t) * gk // 1000  # mm/s
        wind.append(w * rules.wind_mult // 10)
        a_s = TURN * k // (per["s"] * SUB_HZ) + ph["s"]
        a_h = TURN * k // (per["h"] * SUB_HZ) + ph["h"]
        a_p = TURN * k // (per["p"] * SUB_HZ) + ph["p"]
        sx.append((ramp("surge_m", t) * isin(a_s)) >> ONE_BITS)
        sy.append(DECK_H + ((ramp("heave_m", t) * isin(a_h)) >> ONE_BITS))
        sp.append((deg_to_bam(ramp("pitch_deg", t)) * isin(a_p)) >> ONE_BITS)
        zone.append(ramp("zone_m", t))
    vx = tuple((sx[k + 1] - sx[k]) * SUB_HZ for k in range(N_SUB)) + (0,)
    vy = tuple((sy[k + 1] - sy[k]) * SUB_HZ for k in range(N_SUB)) + (0,)
    pr = tuple((sp[k + 1] - sp[k]) * SUB_HZ for k in range(N_SUB)) + (0,)
    return Scenario(int(seed), rules, tuple(wind), tuple(sx), tuple(sy), tuple(sp), vx, vy, pr, tuple(zone))


def drop_params(seed: int, k: int, rules: Rules) -> dict:
    """The hop that drops at substep k: ramp values at the clock k * 50 ms plus jitter keyed by the drop TICK."""
    t = k * SUB_MS
    key = f"drop{k}"
    h0 = ramp("h0_m", t) * _u(seed, key + "h", 950, 1050) // 1000
    v0 = ramp("v0_mps", t) * _u(seed, key + "v", 950, 1050) // 1000
    miss = ramp("miss_m", t) * _u(seed, key + "m", 400, 1000) // 1000 * (1 if _u(seed, key + "ms", 0, 1) else -1)
    vx0 = ramp("vx0_mps", t) * _u(seed, key + "vx", -1000, 1000) // 1000
    th0 = deg_to_bam(_u(seed, key + "th", -3000, 3000))
    return {"h0": h0, "v0": v0, "miss": miss, "vx0": vx0, "th0": th0, "fuel": ramp("fuel_kg", t),
            "relights": relights_at(t, rules), "level": level_at(t), "twr": rules.twr_at(t), "tmin": rules.t_min_at(t)}


# ================================================================== state


def drop_booster(h: dict, sc: Scenario, k: int, hop: int) -> dict:
    """(Re)drop booster h at substep k (in place); returns the drop parameters."""
    d = drop_params(sc.seed, k, sc.rules)
    kk = min(k, N_SUB)
    h.update(x=sc.ship_x[kk] + d["miss"], y=sc.ship_y[kk] + L_ENG + d["h0"], vx=d["vx0"], vy=-d["v0"], th=d["th0"],
             w=0, fuel=d["fuel"], fuel0=d["fuel"], lit=0, ign=0, thr=0, thr_cmd=0, lvl="off",
             relights=d["relights"], relights0=d["relights"], gim=0, gim_cmd=0, gcmd="0", fin="neutral", fin_dep=1000,
             fin_u=0, legs=0, legs_on=0, q=0, qa=0, nr=0, hop=hop, hop_k0=k, hop_level=d["level"], low=0,
             twr=d["twr"], tmin=d["tmin"],
             last=("off", "0", "neutral", "stowed"))
    return d


def new_booster(sc: Scenario) -> dict:
    h = {"status": "flying", "cause": None, "t_end": None, "landed": 0, "qsum": 0, "td": None, "wind": 0}
    drop_booster(h, sc, 0, 1)
    return h


@dataclass
class GState:
    seed: int
    k: int
    t_ms: int
    boosters: list
    ended: bool = False


# ================================================================== physics core (integers only)


def lowest_point(y: int, S: int, C: int, legs: int) -> int:
    aS = S if S >= 0 else -S
    return y - ((L_ENG + LEG_DOWN * legs // 1000) * C >> ONE_BITS) - (
        (R_BODY + (LEG_SPAN - R_BODY) * legs // 1000) * aS >> ONE_BITS)


def limits(rules: Rules, t_ms: int) -> tuple[int, int, int, int]:
    """Touchdown limits at clock t: (sink mm/s, drift mm/s, tilt mdeg, rate mdeg/s) = the rule limits x tol(t)."""
    tol = ramp("tol", t_ms)
    return (rules.land_vy * tol // 1000, rules.land_vx * tol // 1000, rules.land_tilt * tol, rules.land_rate * tol)


def touchdown_quality(rules: Rules, dx: int, zone: int, vyr: int, vxr: int, tilt: int, w: int, t_ms: int = 0) -> int:
    """1 - max normalised touchdown error, micro-units (0 at a limit, 1e6 = perfect)."""
    l_vy, l_vx, l_t, l_w = limits(rules, t_ms)
    lim_t, lim_w = deg_to_bam(l_t), deg_to_bam(l_w)
    errs = (abs(dx) * 1000 // max(zone, 1), abs(vyr) * 1000 // l_vy, abs(vxr) * 1000 // l_vx,
            abs(tilt) * 1000 // lim_t, abs(w) * 1000 // lim_w)
    return max(0, 1000 - max(errs)) * 1000


def integrate(h: dict, sc: Scenario, k0: int, nsub: int, events: list | None, p: int) -> int:
    """Advance booster h (in place) by up to nsub substeps from k0. Stops early at a touchdown or a crash (status
    set to 'landed_hop' / 'crashed'). Returns the substep reached."""
    rules = sc.rules
    x, y, vx, vy, th, w = h["x"], h["y"], h["vx"], h["vy"], h["th"], h["w"]
    fuel, lit, ign, thr, thr_cmd = h["fuel"], h["lit"], h["ign"], h["thr"], h["thr_cmd"]
    gim, gim_cmd = h["gim"], h["gim_cmd"]
    fin_on = h["fin"] != "stowed"
    fin_dep, fin_u, fin_ut = h["fin_dep"], h["fin_u"], FIN_U[h["fin"]] * rules.fin_sign
    legs, legs_on, leg_rate = h["legs"], h["legs_on"], rules.leg_rate
    gsgn = rules.gimbal_sign
    q = qa = 0
    wind = h["wind"]
    cause = None
    landed = False
    k = k0
    hop_end = h["hop_k0"] + HOP_LIMIT_MS // SUB_MS
    WT, SX, SY, SP, SVX, SVY, ZN = sc.wind, sc.ship_x, sc.ship_y, sc.ship_p, sc.ship_vx, sc.ship_vy, sc.zone
    for _ in range(nsub):
        kk = k if k < N_SUB else N_SUB - 1
        # ---- actuators
        if lit:
            if ign:
                ign -= 1
            elif thr < thr_cmd:
                thr = min(thr_cmd, thr + THR_UP)
            elif thr > thr_cmd:
                thr = max(thr_cmd, thr - THR_DN)
        elif thr:
            thr = max(0, thr - THR_DN)
        if gim < gim_cmd:
            gim = min(gim_cmd, gim + GIM_RATE)
        elif gim > gim_cmd:
            gim = max(gim_cmd, gim - GIM_RATE)
        if fin_on:
            if fin_dep < 1000:
                fin_dep = min(1000, fin_dep + FIN_DEP_RATE)
        elif fin_dep:
            fin_dep = max(0, fin_dep - FIN_DEP_RATE)
        if fin_u < fin_ut:
            fin_u = min(fin_ut, fin_u + FIN_U_RATE)
        elif fin_u > fin_ut:
            fin_u = max(fin_ut, fin_u - FIN_U_RATE)
        if legs_on and legs < 1000:
            legs = min(1000, legs + leg_rate)
            if legs == 1000 and events is not None:
                events.append(Event((k + 1) * SUB_MS, "legs", p, {}))
        m = M_DRY + fuel
        S = isin(th)
        C = icos(th)
        Fx = Fy = tau = 0
        # ---- engine
        if thr:
            a = th - gim
            Fx += (thr * isin(a)) >> ONE_BITS
            Fy += (thr * icos(a)) >> ONE_BITS
            tau += gsgn * (L_ENG * thr * isin(gim)) // (1000 * ONE)
            fuel -= thr * 100_000_000 // (ISP_G0 * SUB_HZ)
            if fuel <= 0:
                fuel = 0
                if lit and events is not None:
                    events.append(Event((k + 1) * SUB_MS, "flameout", p, {}))
                lit, thr, ign = 0, 0, 0
        # ---- aerodynamics
        yc = y if y < 1_000_000 else 1_000_000
        wind = WT[kk] * (2_000_000 + yc) // 2_000_000
        vax = vx - wind
        v2 = vax * vax + vy * vy
        if v2 > V_AERO * V_AERO:
            V = isqrt(v2)
            rho = rho_at(y)
            q = rho * v2 // 2_000_000_000_000  # Pa
            fx = -vax * ONE // V
            fy = -vy * ONE // V
            fax = (fx * S + fy * C) >> ONE_BITS
            fcx = fx - ((fax * S) >> ONE_BITS)
            fcy = fy - ((fax * C) >> ONE_BITS)
            sa = isqrt(fcx * fcx + fcy * fcy)
            qa = (q * sa) >> ONE_BITS
            area_a = SC_A_BODY + SC_A_FIN * fin_dep // 1000 + SC_A_LEG * legs // 1000
            FA = q * area_a * fax // (10_000 * ONE)
            Fx += (FA * S) >> ONE_BITS
            Fy += (FA * C) >> ONE_BITS
            nb = q * (SC_N_BODY + (SC_X * sa >> ONE_BITS)) // 10_000
            nf = q * SC_N_FIN * fin_dep // 10_000_000
            nbf = nb + nf
            Fx += (nbf * fcx) >> ONE_BITS
            Fy += (nbf * fcy) >> ONE_BITS
            cross = (C * fcx - S * fcy) >> ONE_BITS
            tau += (D_BODY * nb + D_FIN * nf) * cross // (1000 * ONE)
            if fin_u and fin_dep:
                fc = (q * SC_FC * fin_dep // 10_000_000) * fin_u // 1000 * fax // ONE
                Fx += (fc * C) >> ONE_BITS
                Fy -= (fc * S) >> ONE_BITS
                tau += D_FIN * fc // 1000
            tau -= K_DAMP * q * w * TWO_PI_Q40 * 1000 // (V << (40 + TURN_BITS))
        else:
            q = qa = 0
        # ---- integrate (semi-implicit Euler)
        ax = Fx * 1_000_000 // m
        ay = Fy * 1_000_000 // m - G_MM
        alpha = tau * 1000 * TURN * (1 << 40) // (m * K2 * TWO_PI_Q40)
        w += rdiv(alpha, SUB_HZ)
        th += rdiv(w, SUB_HZ)
        vx += rdiv(ax, SUB_HZ)
        vy += rdiv(ay, SUB_HZ)
        x += rdiv(vx, SUB_HZ)
        y += rdiv(vy, SUB_HZ)
        k += 1
        kk = k if k < N_SUB else N_SUB - 1
        # ---- limits
        if q > Q_MAX:
            cause = "max_q"
        elif qa > QA_MAX:
            cause = "breakup"
        elif legs and q > Q_LEG:
            cause = "legs_torn"
        elif not -TUMBLE < wrap_bam(th) < TUMBLE:
            cause = "tumble"
        # ---- touchdown
        S = isin(th)
        C = icos(th)
        bot = lowest_point(y, S, C, legs)
        if cause is None and bot <= SY[kk] + DECK_MARGIN:
            dx = x - SX[kk]
            on_deck = -SHIP_HW <= dx <= SHIP_HW
            ys = SY[kk] + (dx * isin(SP[kk]) // icos(SP[kk]) if SP[kk] else 0) if on_deck else 0
            if bot <= ys:
                vys = SVY[kk] + (dx * sc.ship_pr[kk] * TWO_PI_Q40 >> (40 + TURN_BITS)) if on_deck else 0
                vxs = SVX[kk] if on_deck else 0
                vyr, vxr = vy - vys, vx - vxs
                tilt = wrap_bam(th - (SP[kk] if on_deck else 0))
                l_vy, l_vx, l_t, l_w = limits(rules, k * SUB_MS)
                lim_t, lim_w = deg_to_bam(l_t), deg_to_bam(l_w)
                zone = ZN[kk]
                if not on_deck:
                    cause = "splashdown"
                elif legs < 1000:
                    cause = "no_legs"
                elif vyr < -l_vy or vyr > l_vy:
                    cause = "hard_landing"
                elif not (-l_vx <= vxr <= l_vx and -lim_t <= tilt <= lim_t and -lim_w <= w <= lim_w):
                    cause = "tip_over"
                elif not -zone <= dx <= zone:
                    cause = "off_zone"
                qual = touchdown_quality(rules, dx, zone, vyr, vxr, tilt, w, k * SUB_MS) if cause is None else 0
                h["td"] = {"k": k, "x": x, "y": y + ys - bot, "th": th, "dx": dx, "vyr": vyr, "vxr": vxr,
                           "tilt": tilt, "w": w, "q": qual, "ok": cause is None, "hop": h["hop"]}
                if cause is None:
                    landed = True
                    y = y + ys - bot
                    break
        if cause is None and k >= hop_end:
            cause = "hop_timeout"
        if cause is not None:
            break
    h.update(x=x, y=y, vx=vx, vy=vy, th=th, w=w, fuel=fuel, lit=lit, ign=ign, thr=thr, gim=gim, fin_dep=fin_dep,
             fin_u=fin_u, legs=legs, q=q, qa=qa, wind=wind)
    if events is not None and not h["low"] and fuel * 1000 < LOW_FUEL_PM * h["fuel0"] and cause is None and not landed:
        h["low"] = 1
        events.append(Event(k * SUB_MS, "low_fuel", p, {"fuel_kg": fuel // 1000}))
    if landed:
        h["status"] = "landed_hop"
    elif cause is not None:
        h["status"], h["cause"], h["t_end"] = "crashed", cause, k * SUB_MS
    return k


def apply_action(h: dict, rules: Rules, a: dict, events: list | None, p: int, t_ms: int) -> None:
    """Set the commands of booster h from one decision's answers (invalid/missing -> hold the current command).
    Release (g1.1): for RELEASE_MS after a drop the throttle stays off and the legs stowed (a reply decided before
    the drop, e.g. 'min' or 'deploy' from the landing, must not light the engine or tear the legs)."""
    if t_ms < h["hop_k0"] * SUB_MS + RELEASE_MS:
        a = {k: v for k, v in a.items() if k not in ("throttle", "legs")}
    lvl = a.get("throttle", h["lvl"])
    lvl = lvl if lvl in THR_OPTS else h["lvl"]
    if lvl == "off":
        if h["lit"]:
            h["lit"], h["ign"] = 0, 0
            if events is not None:
                events.append(Event(t_ms, "shutdown", p, {}))
        h["nr"] = 0
    elif not h["lit"]:
        if h["relights"] > 0 and h["fuel"] > 0:
            h["relights"] -= 1
            h["lit"], h["ign"], h["nr"] = 1, rules.ign_ms // SUB_MS, 0
            if events is not None:
                events.append(Event(t_ms, "ignition", p, {"relights_left": h["relights"]}))
        else:
            if events is not None and not h["nr"]:
                events.append(Event(t_ms, "no_relight", p, {}))
            h["nr"] = 1
            lvl = "off"
    h["lvl"] = lvl
    h["thr_cmd"] = rules.thrust(lvl, h) if h["lit"] else 0
    g = a.get("gimbal", h["gcmd"])
    g = g if g in GIM_MDEG else h["gcmd"]
    h["gcmd"], h["gim_cmd"] = g, deg_to_bam(GIM_MDEG[g])
    f = a.get("fins", h["fin"])
    h["fin"] = f if f in FIN_U else h["fin"]
    if a.get("legs") == "deploy":
        h["legs_on"] = 1
    h["last"] = (h["lvl"], h["gcmd"], h["fin"], "deploy" if h["legs_on"] else "stowed")


def advance(h: dict, sc: Scenario, k0: int, nsub: int, events: list | None, p: int) -> int:
    """One decision period for booster h: integrate; on a touchdown record the landing and re-drop at the END of the
    period (the next decision boundary), so every hop starts on a decision tick. Returns the substep reached."""
    k = integrate(h, sc, k0, nsub, events, p)
    k_end = k0 + nsub
    if h["status"] == "landed_hop":
        td = h["td"]
        h["landed"] += 1
        h["qsum"] += td["q"]
        if events is not None:
            events.append(Event(k * SUB_MS, "landed", p, {"hop": h["hop"], "level": level_at(k * SUB_MS),
                                                          "quality_micro": td["q"], "dx_mm": td["dx"],
                                                          "vy_mms": td["vyr"]}))
        h["status"] = "flying"
        d = drop_booster(h, sc, k_end, h["hop"] + 1)
        if events is not None:
            events.append(Event(k_end * SUB_MS, "drop", p, {"hop": h["hop"], "level": d["level"]}))
    elif h["status"] == "crashed" and events is not None:
        events.append(Event(h["t_end"], "crash", p, {"cause": h["cause"], "x": h["x"] // 1000, "y": h["y"] // 1000,
                                                      "level": level_at(h["t_end"]), "hops": h["landed"]}))
    return k_end


# ================================================================== the game


def _mps(v: int, nd: int = 1) -> str:
    return _fmt_int(v, 1000, nd)


def _deg(a: int, nd: int = 1) -> str:
    return _fmt_int(bam_to_mdeg(a), 1000, nd)


def survival_ms(h: dict, t_ms: int) -> int:
    return h["t_end"] if h["t_end"] is not None else t_ms


def quality_micro(h: dict) -> int:
    return h["qsum"] // h["landed"] if h["landed"] else 0


class BoosterGauntlet:
    """Arena v3 fail-first game: n independent same-seed boosters (ghosts: they share the sky, the ship and the
    clock, never interact). Implements the arena.core.Game protocol and the GameV2 surface (ctx, rules_id,
    multi_query, sensor_top) so arena.core.Referee, arena.chord.ChordReferee and arena.v2.runner.V2Referee play it
    unchanged."""

    id = "booster_gauntlet"

    def __init__(self, variant: str | None = None, announce: bool = True, sensors: bool = False, n_players: int = 1,
                 decision_period_ms: int = DECISION_MS, max_round_ms: int = MAX_ROUND_MS, rules: Rules | None = None,
                 prompt_style: str = DEFAULT_PROMPT_STYLE, rules_version: str = RULES_VERSION):
        assert decision_period_ms % SUB_MS == 0 and decision_period_ms > 0, decision_period_ms
        if rules_version not in RULES_VERSIONS:
            raise ValueError(f"rules_version must be one of {RULES_VERSIONS}: {rules_version!r}")
        self.rules_version = rules_version
        assert max_round_ms <= MAX_ROUND_MS
        if prompt_style not in PROMPT_STYLES:
            raise ValueError(f"prompt_style must be one of {PROMPT_STYLES}: {prompt_style!r}")
        self.variant = VARIANTS[variant] if variant else None
        self.rules = rules if rules is not None else rules_for(variant)
        self.announce, self.sensors, self.n_players = announce, sensors, n_players
        self.decision_period_ms, self.max_round_ms = decision_period_ms, max_round_ms
        self.prompt_style = prompt_style
        if prompt_style == DEFAULT_PROMPT_STYLE:
            self.rules_text = rules_text(self.rules, self.variant, announce)
        else:
            if self.variant is not None or sensors or self.rules != BASE_RULES:
                raise ValueError("prompt styles p1/p2 run the base rules at L0 only (no variant, no sensor_top)")
            self.rules_text = rules_text_p(self.rules)
        self.engine = self

    @property
    def rules_id(self) -> str:
        v = self.variant.id if self.variant else "base"
        ann = "announced" if self.announce or not self.variant else "unannounced"
        rid = f"{self.id}:{self.rules_version}:{v}:{ann}:{'L1' if self.sensors else 'L0'}:{self.decision_period_ms}ms"
        return rid if self.prompt_style == DEFAULT_PROMPT_STYLE else f"{rid}:{self.prompt_style}"

    def ctx(self):
        import contextlib
        return contextlib.nullcontext()

    def scenario(self, seed: int) -> Scenario:
        return build_scenario(seed, self.rules)

    # -------------------------------------------------------------- protocol
    def reset(self, seed: int) -> GState:
        sc = self.scenario(seed)
        return GState(seed=int(seed), k=0, t_ms=0, boosters=[new_booster(sc) for _ in range(self.n_players)])

    def queries(self, s: GState, player: int, answers: dict) -> list[Query]:
        h = s.boosters[player]
        if h["status"] != "flying" or s.ended or answers:
            return []
        obs = self.observation(s, player)
        return [Query(player, key, obs + "\nChoose " + line, opts, default)
                for key, line, opts, default in self._controls(h)]

    def _controls(self, h: dict):
        r = self.rules
        m = M_DRY + h["fuel"]
        twr = "/".join(_fmt_int(r.thrust(lv, h) * 100_000 // (m * G_MM // 1000), 100, 2, False) for lv in ("min", "mid", "max"))
        if self.prompt_style != DEFAULT_PROMPT_STYLE:
            tw = twr.split("/")
            return (
                ("throttle", f"THROTTLE (TWR now min {tw[0]}, mid {tw[1]}, max {tw[2]})", THR_OPTS, h["lvl"]),
                ("gimbal", "GIMBAL deg: L2 -5, L1 -2, 0, R1 +2, R2 +5 (acts only while thrusting)", GIM_OPTS, h["gcmd"]),
                ("fins", "FINS (right: top toward +x)", FIN_OPTS, h["fin"]),
                ("legs", "LEGS (deploy is one-way per hop)", LEG_OPTS, "deploy" if h["legs_on"] else "stowed"),
            )
        return (
            ("throttle", f"THROTTLE (TWR now {twr}; starting uses a relight)", THR_OPTS, h["lvl"]),
            ("gimbal", "GIMBAL deg: L2 -5, L1 -2, 0, R1 +2, R2 +5 (only while burning)", GIM_OPTS, h["gcmd"]),
            ("fins", "FINS (right: top to +x)", FIN_OPTS, h["fin"]),
            ("legs", "LEGS (deploy is one-way per hop)", LEG_OPTS, "deploy" if h["legs_on"] else "stowed"),
        )

    def multi_query(self, s: GState, player: int):
        from nagi.burst2._rt.arena.chord import MultiQuery
        h = s.boosters[player]
        if h["status"] != "flying" or s.ended:
            return None
        obs = self.observation(s, player)
        ctl = self._controls(h)
        text = obs + "\nControls:\n" + "\n".join(c[1] for c in ctl)
        return MultiQuery(player, text, tuple((c[0], c[2], c[3]) for c in ctl))

    def step(self, s: GState, actions: dict, dt_ms: int) -> tuple[GState, list[Event]]:
        assert dt_ms % SUB_MS == 0, dt_ms
        sc = self.scenario(s.seed)
        nsub = dt_ms // SUB_MS
        boosters = [dict(h) for h in s.boosters]
        events: list[Event] = []
        t2 = s.t_ms + dt_ms
        if not s.ended:
            for p, h in enumerate(boosters):
                if h["status"] != "flying":
                    continue
                apply_action(h, self.rules, actions.get(p, {}) or {}, events, p, s.t_ms)
                advance(h, sc, s.k, nsub, events, p)
            if level_at(t2) > level_at(s.t_ms) and t2 < self.max_round_ms:
                events.append(Event(t2, "level", None, {"level": level_at(t2)}))
        s2 = GState(seed=s.seed, k=s.k + nsub, t_ms=t2, boosters=boosters, ended=s.ended)
        if not s2.ended:
            if t2 >= self.max_round_ms:
                for h in boosters:
                    if h["status"] == "flying":
                        h["status"] = "censored"
            if all(h["status"] != "flying" for h in boosters):
                s2.ended = True
                events.append(Event(t2, "round_end", None,
                                    {"survival_ms": [survival_ms(h, t2) for h in boosters]}))
        events.sort(key=lambda e: e.t_ms)
        return s2, events

    def done(self, s: GState) -> bool:
        return s.ended or s.t_ms >= self.max_round_ms or all(h["status"] != "flying" for h in s.boosters)

    def outcome(self, s: GState, p: int) -> dict:
        h = s.boosters[p]
        surv = survival_ms(h, s.t_ms)
        return {"survival_ms": surv, "censored": h["status"] == "censored", "level_at_fail": level_at(min(surv, 89_999)),
                "hops": h["landed"], "quality": quality_micro(h) / 1e6, "cause": h["cause"], "status": h["status"]}

    def ranking(self, s: GState) -> list[list[int]]:
        key = [(survival_ms(h, s.t_ms), h["landed"], quality_micro(h)) for h in s.boosters]
        return [[p for p in range(self.n_players) if key[p] == v] for v in sorted(set(key), reverse=True)]

    def state_hash(self, s: GState) -> str:
        parts = [repr((s.seed, s.k, s.t_ms, s.ended))]
        for h in s.boosters:
            parts.append(repr(sorted(h.items())))
        return hashlib.sha256("|".join(parts).encode()).hexdigest()

    # -------------------------------------------------------------- observation
    def stop_heights(self, s: GState, p: int) -> dict:
        """g1.1 (historical, C F5 bug kept byte-identical): per lit level, where the fall would stop (lowest point with
        legs, above the deck centre, mm) if that level were held from now, thrust vertical, no drag; None if already
        rising. BUG: a level with net acceleration a <= 0 (TWR <= 1) cannot stop the fall, but hb - v^2 / (2a) with
        a < 0 is a height ABOVE the booster (e.g. 'min +1899'). g1.2 uses stop_sensor()."""
        h = s.boosters[p]
        sc = self.scenario(s.seed)
        kk = min(s.k, N_SUB)
        m = M_DRY + h["fuel"]
        v = h["vy"] - sc.ship_vy[kk]
        hb = h["y"] - L_ENG - LEG_DOWN - sc.ship_y[kk]
        out = {}
        for lv in ("min", "mid", "max"):
            a = self.rules.thrust(lv, h) * 1_000_000 // m - G_MM
            out[lv] = hb - v * v // (2 * a) if v < 0 else None
        return out

    def stop_sensor(self, s: GState, p: int) -> dict:
        """g1.2 stop-height sensor (the F5 fix). Same geometry as g1.1 (lowest point with legs, above the deck centre,
        mm; relative vertical speed; thrust vertical, no drag, the level's full thrust from now):
          {'falling': False, 'stop': {}}                       when not falling (v >= 0);
          {'falling': True, 'stop': {lv: height mm | None}}    None = lv CANNOT stop the fall (net acceleration a <= 0,
                                                               i.e. TWR <= 1): the fall only slows or keeps speeding up.
        A finite height is hb - v^2 / (2a) with a > 0 (integer, as g1.1)."""
        h = s.boosters[p]
        sc = self.scenario(s.seed)
        kk = min(s.k, N_SUB)
        m = M_DRY + h["fuel"]
        v = h["vy"] - sc.ship_vy[kk]
        hb = h["y"] - L_ENG - LEG_DOWN - sc.ship_y[kk]
        if v >= 0:
            return {"falling": False, "stop": {}}
        out = {}
        for lv in ("min", "mid", "max"):
            a = self.rules.thrust(lv, h) * 1_000_000 // m - G_MM
            out[lv] = hb - v * v // (2 * a) if a > 0 else None
        return {"falling": True, "stop": out}

    def sensor_lines(self, s: GState, p: int) -> list[str]:
        if self.rules_version == "g1.1":
            st = self.stop_heights(s, p)
            parts = [f"{lv} " + ("rising" if v is None else _fmt_int(v, 1000, 0)) for lv, v in st.items()]
            return ["SENSOR stop height m if lit now: " + ", ".join(parts)]
        ss = self.stop_sensor(s, p)
        if not ss["falling"]:
            parts = [f"{lv} rising" for lv in ("min", "mid", "max")]
        else:
            parts = [f"{lv} " + ("cannot stop" if v is None else _fmt_int(v, 1000, 0)) for lv, v in ss["stop"].items()]
        return ["SENSOR stop height m if lit now: " + ", ".join(parts)]

    def kinematics(self, s: GState, p: int) -> dict:
        """Derived vertical kinematics for the p2 text (integers; ideal model: body upright, no drag, the level's full
        thrust from now; relative to the deck at the ship centre).
          alt        lowest point above the deck (mm), exactly the 'height' of the state line;
          v          vertical speed relative to the deck (mm/s);
          stop[lv]   only when falling (v < 0): the height (mm) where the fall stops if lv is held from now, or None
                     when lv cannot stop the fall (net acceleration <= 0). This is the fixed L1 stop-height sensor
                     (C F5: stop_heights() divides by a negative deceleration and prints a bogus height instead);
          t_free_ms  time to reach deck level with the engine off (free fall from v, no drag); 0 at or below it."""
        h = s.boosters[p]
        sc = self.scenario(s.seed)
        kk = min(s.k, N_SUB)
        alt = lowest_point(h["y"], isin(h["th"]), icos(h["th"]), h["legs"]) - sc.ship_y[kk]
        v = h["vy"] - sc.ship_vy[kk]
        m = M_DRY + h["fuel"]
        stop = {}
        if v < 0:
            for lv in ("min", "mid", "max"):
                a = self.rules.thrust(lv, h) * 1_000_000 // m - G_MM
                stop[lv] = alt - v * v // (2 * a) if a > 0 else None
        t_free = (v + isqrt(v * v + 2 * G_MM * alt)) * 1000 // G_MM if alt > 0 else 0
        return {"alt": alt, "v": v, "stop": stop, "t_free_ms": t_free}

    def kinematics_line(self, s: GState, p: int) -> str:
        k = self.kinematics(s, p)
        st = ("stop height if held: " + ", ".join(
            f"{lv} " + ("cannot stop" if x is None else _fmt_int(x, 1000, 0)) for lv, x in k["stop"].items()) + " m"
            if k["stop"] else "not falling")
        return f"DERIVED (upright, no drag, full thrust): {st}; unpowered {_fmt_int(k['t_free_ms'], 1000, 1, False)} s to deck"

    def _observation_p(self, s: GState, p: int) -> str:
        """p1/p2 state lines: the g1.1 lines plus the time left in the hop, the engine's actual thrust, relights LEFT
        and the touchdown limits now; p2 adds kinematics_line()."""
        h = s.boosters[p]
        sc = self.scenario(s.seed)
        kk = min(s.k, N_SUB)
        t = s.t_ms
        nxt = LEVEL_MS - t % LEVEL_MS
        age = t - h["hop_k0"] * SUB_MS
        S, C = isin(h["th"]), icos(h["th"])
        alt = lowest_point(h["y"], S, C, h["legs"]) - sc.ship_y[kk]
        legs = ("DEPLOYING " + str(h["legs"] // 10) + "%") if h["legs_on"] and h["legs"] < 1000 else (
            "DOWN" if h["legs_on"] else "STOWED")
        eng = (f"LIT {h['lvl']}, thrust {h['thr'] // 1000} kN" if h["lit"] else "OFF")
        l_vy, l_vx, l_t, l_w = limits(self.rules, t)
        lines = [
            self.rules_text,
            f"STATE t {_fmt_int(t, 1000, 2, False)} s | LEVEL {level_at(t)}, next in {_fmt_int(nxt, 1000, 2, False)} s"
            f" | hop {h['hop']} (landed {h['landed']}), {_fmt_int(age, 1000, 2, False)} s since drop, "
            f"{_fmt_int(max(0, HOP_LIMIT_MS - age), 1000, 2, False)} s left",
            f"height {_fmt_int(alt, 1000, 0)} m above deck | vx {_mps(h['vx'])} vy {_mps(h['vy'])} m/s | tilt "
            f"{_deg(wrap_bam(h['th']))} deg, rate {_deg(h['w'])} deg/s",
            f"ship dx {_fmt_int(sc.ship_x[kk] - h['x'], 1000, 0)} m, zone +-{_fmt_int(sc.zone[kk], 1000, 0, False)} m"
            f" | deck vx {_mps(sc.ship_vx[kk])} vy {_mps(sc.ship_vy[kk])} m/s, pitch {_deg(sc.ship_p[kk])} deg | wind "
            f"{_mps(h['wind'])} m/s",
            f"engine {eng}, relights left {h['relights']}/{h['relights0']}, gimbal {_deg(h['gim'])} | fuel "
            f"{h['fuel'] // 1000}/{h['fuel0'] // 1000} kg | fins {h['fin'].upper()} | legs {legs} | q "
            f"{_fmt_int(h['q'], 1000, 1, False)} kPa",
            f"touchdown limits now: sink {_fmt_int(l_vy, 1000, 1, False)}, drift "
            f"{_fmt_int(l_vx, 1000, 1, False)} m/s, tilt {_fmt_int(l_t, 1000, 1, False)} deg, rate "
            f"{_fmt_int(l_w, 1000, 1, False)} deg/s",
        ]
        if self.prompt_style == "p2":
            lines.append(self.kinematics_line(s, p))
        return "\n".join(lines)

    def observation(self, s: GState, p: int) -> str:
        if self.prompt_style != DEFAULT_PROMPT_STYLE:
            return self._observation_p(s, p)
        h = s.boosters[p]
        sc = self.scenario(s.seed)
        kk = min(s.k, N_SUB)
        r = self.rules
        t = s.t_ms
        lvl = level_at(t)
        nxt = LEVEL_MS - t % LEVEL_MS
        age = t - h["hop_k0"] * SUB_MS
        S, C = isin(h["th"]), icos(h["th"])
        alt = lowest_point(h["y"], S, C, h["legs"]) - sc.ship_y[kk]
        legs = ("DEPLOYING " + str(h["legs"] // 10) + "%") if h["legs_on"] and h["legs"] < 1000 else (
            "DOWN" if h["legs_on"] else "STOWED")
        eng = (f"ON {h['lvl']} {h['thr'] // 1000} kN" if h["lit"] else "OFF")
        lines = [
            self.rules_text,
            f"STATE t {_fmt_int(t, 1000, 2, False)} s | LEVEL {lvl}, next in {_fmt_int(nxt, 1000, 2, False)} s | hop "
            f"{h['hop']} (landed {h['landed']}), {_fmt_int(age, 1000, 2, False)} s since drop",
            f"height {_fmt_int(alt, 1000, 0)} m above deck | vx {_mps(h['vx'])} vy {_mps(h['vy'])} m/s | tilt "
            f"{_deg(wrap_bam(h['th']))} deg, rate {_deg(h['w'])} deg/s",
            f"ship dx {_fmt_int(sc.ship_x[kk] - h['x'], 1000, 0)} m, zone +-{_fmt_int(sc.zone[kk], 1000, 0, False)} m"
            f" | deck vx {_mps(sc.ship_vx[kk])} vy {_mps(sc.ship_vy[kk])} m/s, pitch {_deg(sc.ship_p[kk])} deg | wind "
            f"{_mps(h['wind'])} m/s",
            f"engine {eng}, relights {h['relights']}/{h['relights0']}, gimbal {_deg(h['gim'])} | fuel "
            f"{h['fuel'] // 1000}/{h['fuel0'] // 1000} kg | fins {h['fin'].upper()} | legs "
            f"{legs} | q {_fmt_int(h['q'], 1000, 1, False)} kPa",
        ]
        if self.sensors:
            lines += self.sensor_lines(s, p)
        return "\n".join(lines)

    def sensor_top(self, s: GState, q: Query, answers: dict) -> str | None:
        """Throttle option the L1 sensor suggests (diagnostic): the lowest lit level stopping in [0, 30 m]."""
        if q.key != "throttle" or not self.sensors:
            return None
        if self.rules_version != "g1.1":
            return self._sensor_top_g12(s, q.player)
        st = self.stop_heights(s, q.player)
        if st["min"] is None or st["min"] > 30_000:
            return "off"
        for lv in ("min", "mid", "max"):
            if 0 <= st[lv] <= 30_000:
                return lv
        return "max"

    def _sensor_top_g12(self, s: GState, p: int) -> str:
        """g1.2: not falling -> 'off' (nothing to stop). Falling: among the levels that CAN stop the fall (weakest
        first), if the weakest would stop above 30 m it is too early to light -> 'off'; else the weakest level stopping
        in [0, 30 m]; else (every stopping level stops below the deck, or no level can stop) -> 'max'. g1.1 instead
        compared min's bogus height (C F5) and so suggested 'off' whenever min had TWR <= 1."""
        ss = self.stop_sensor(s, p)
        if not ss["falling"]:
            return "off"
        can = [(lv, v) for lv, v in ss["stop"].items() if v is not None]
        if can and can[0][1] > 30_000:
            return "off"
        for lv, v in can:
            if 0 <= v <= 30_000:
                return lv
        return "max"

    # -------------------------------------------------------------- render
    def render_state(self, s: GState) -> dict:
        sc = self.scenario(s.seed)
        kk = min(s.k, N_SUB)
        bs = []
        for h in s.boosters:
            td = h["td"]
            bs.append({"x": h["x"] / 1000, "y": h["y"] / 1000, "vx": h["vx"] / 1000, "vy": h["vy"] / 1000,
                       "tilt_deg": bam_to_mdeg(wrap_bam(h["th"])) / 1000, "rate_dps": bam_to_mdeg(h["w"]) / 1000,
                       "thrust_kn": h["thr"] / 1000, "lvl": h["lvl"], "lit": bool(h["lit"]),
                       "gimbal_deg": bam_to_mdeg(h["gim"]) / 1000, "fin": h["fin"], "fin_dep": h["fin_dep"] / 1000,
                       "fin_u": h["fin_u"] / 1000, "legs": h["legs"] / 1000, "legs_on": bool(h["legs_on"]),
                       "fuel_kg": h["fuel"] / 1000, "fuel0_kg": h["fuel0"] / 1000, "relights": h["relights"],
                       "relights0": h["relights0"], "q_kpa": h["q"] / 1000, "wind": h["wind"] / 1000,
                       "status": h["status"], "cause": h["cause"], "t_end_ms": h["t_end"], "hop": h["hop"],
                       "hop_t0_ms": h["hop_k0"] * SUB_MS, "hop_level": h["hop_level"], "landed": h["landed"],
                       "quality": quality_micro(h) / 1e6, "survival_ms": survival_ms(h, s.t_ms),
                       "td": None if td is None else {"t_ms": td["k"] * SUB_MS, "x": td["x"] / 1000,
                                                      "y": td["y"] / 1000, "tilt_deg": bam_to_mdeg(wrap_bam(td["th"])) / 1000,
                                                      "ok": td["ok"], "quality": td["q"] / 1e6, "hop": td["hop"]},
                       "last_action": list(h["last"])})
            if self.rules_version != "g1.1" and td is not None:
                # g1.2: the touchdown's normalised errors (the failing hop's E for K3), recomputable from the raw ints
                failing = td["hop"] == h["hop"] and not td["ok"]
                legs = h["legs"] if failing else 1000     # a landed hop had its legs fully down (success rule)
                bs[-1]["td"]["err"] = touchdown_errors(self.rules, td, sc.zone[min(td["k"], N_SUB - 1)], legs)
        t = s.t_ms
        return {"t_ms": t, "course": {"id": self.id, "seed": s.seed, "rules_id": self.rules_id},
                "level": level_at(t), "level_frac": (t % LEVEL_MS) / LEVEL_MS,
                "ship": {"x": sc.ship_x[kk] / 1000, "deck_y": sc.ship_y[kk] / 1000,
                         "pitch_deg": bam_to_mdeg(sc.ship_p[kk]) / 1000, "zone_hw": sc.zone[kk] / 1000,
                         "hull_hw": SHIP_HW / 1000},
                "env": {"wind": sc.wind[kk] / 1000, "wind_mean": ramp("wind_mps", t) / 1000,
                        "gust": ramp("gust_mps", t) / 1000, "heave": ramp("heave_m", t) / 1000,
                        "pitch_amp": ramp("pitch_deg", t) / 1000},
                "boosters": bs, "ended": s.ended}


# ================================================================== touchdown errors (g1.2 record field; K3 score)


def touchdown_errors(rules: Rules, td: dict, zone_mm: int, legs: int) -> dict:
    """Normalised touchdown errors of engine touchdown `td` (1 = at a limit; C_experiments.md 4.2, the definition
    of booster_scoring_sim.touchdown_error): |dx| / zone, |vy_rel| / sink limit, |vx_rel| / drift limit, |tilt vs deck|
    / tilt limit, |rate| / rate limit, the limits taken x tol at the touchdown clock; E = their max, raised to >= 2 when
    the legs were not fully down. Floats from integer ratios (one correctly rounded IEEE division each: portable).
    Raw integers are kept so E is recomputable from the record alone. E is the K3 error only for a crash ON the deck
    (TD_CAUSES); splashdown / timeout / in-flight failures have no deck touchdown (E = inf in K3)."""
    l_vy, l_vx, l_t, l_w = limits(rules, td["k"] * SUB_MS)
    tilt_mdeg, rate_mdeg = bam_to_mdeg(td["tilt"]), bam_to_mdeg(td["w"])
    comp = {"dx": abs(td["dx"]) / max(zone_mm, 1), "vy": abs(td["vyr"]) / l_vy, "vx": abs(td["vxr"]) / l_vx,
            "tilt": abs(tilt_mdeg) / l_t, "rate": abs(rate_mdeg) / l_w}
    e = max(comp.values())
    if legs < 1000:
        e = max(e, 2.0)
    return {"E": e, **comp, "legs_pm": legs,
            "raw": {"dx_mm": td["dx"], "zone_mm": zone_mm, "vyr_mms": td["vyr"], "vxr_mms": td["vxr"],
                    "tilt_mdeg": tilt_mdeg, "rate_mdeg_s": rate_mdeg, "lim_vy_mms": l_vy, "lim_vx_mms": l_vx,
                    "lim_tilt_mdeg": l_t, "lim_rate_mdeg_s": l_w}}


# ================================================================== determinism probe
HASH_SEED0 = 20260927


def scripted_action(i: int, x: int) -> tuple[dict, int]:
    """Deterministic pseudo-random action from an integer LCG (no floats); burns in bursts so hops and crashes
    both happen."""
    x = (x * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
    r = x >> 33
    burst = (i // 8) % 6
    thr = ("off", "off", "max", "mid", "min", "mid")[burst] if r % 7 else THR_OPTS[r % 4]
    act = {"throttle": thr, "gimbal": GIM_OPTS[(r >> 3) % 5], "fins": FIN_OPTS[1 + (r >> 6) % 3],
           "legs": "deploy" if (r >> 9) % 13 == 0 else "stowed"}
    return act, x


def determinism_chain(steps: int = 1000, seed0: int = HASH_SEED0, variant: str | None = None) -> str:
    """sha256 chain over `steps` decision ticks of scripted play (a new round with seed+1 whenever one ends)."""
    g = BoosterGauntlet(variant)
    seed, s, x = seed0, g.reset(seed0), seed0
    chain = hashlib.sha256(b"").hexdigest()
    for i in range(steps):
        act, x = scripted_action(i, x)
        s, _ = g.step(s, {0: act}, g.decision_period_ms)
        chain = hashlib.sha256((chain + g.state_hash(s)).encode()).hexdigest()
        if g.done(s):
            seed += 1
            s = g.reset(seed)
    return chain


if __name__ == "__main__":
    import platform
    import sys
    print(platform.platform(), sys.version.split()[0])
    print("booster_gauntlet determinism chain (1000 steps):", determinism_chain())
