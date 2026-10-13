"""BOOSTER LANDING (Arena v3): land a returning rocket first stage on a pad or a drone ship. docs/arena_v3/BOOSTER_LANDING.md.

Exact rules (the text every model reads is `rules_text(rules)`; this docstring is the engineering spec):

* Frame and units. 2D side view, x right (downrange), y up, the target centre at x = 0. SI units in the text; the
  engine state is FIXED-POINT integers only (mm, mm/s, grams, binary angle units): no float, no libm, no numpy in
  reset/step, so a state hash is bit-exact on every platform (GAME_BRIEF hard requirement 3; handbook R3.13/R4.7).
  Angles: 1 turn = 2^20 BAM. sin/cos: a 1025-entry quarter-wave table built at import by integer Taylor series
  (pi by Machin's formula), linear interpolation. Density: integer exp table per 100 m. sqrt: math.isqrt (exact).
* Time. Physics substep 50 ms (semi-implicit Euler: rates, then attitude, then velocity, then position). One
  decision every 250 ms (4 Hz, configurable to any multiple of 50 ms); controls are held between decisions. Round cap
  90 s (Arena v3 G6); a booster still flying at the cap ends 'timeout'.
* Release (seeded, integer): altitude 17.5-20.5 km, vy -330..-420 m/s, vx +-20..90 m/s, tilt +-3 deg, x0 = -12 s * vx0
  + miss, miss +-0.2..1.4 km; fuel 9 t; engine off, 3 relights (rule), fins commanded neutral (deploying, 1 s).
* Body. Mass m = 22 t dry + fuel (9 t at release). Moment of inertia I = m * (11 m)^2. Attitude theta = tilt of the
  body axis from vertical, + = top leans to +x (clockwise); omega = d theta/dt. Body axis b = (sin th, cos th).
  CG to engine plane 14 m, CG to grid fins 26 m, body normal-force centre 6 m BELOW the CG (engine-first flight is
  aerodynamically unstable without fins).
* Engine. Levels (thrust as a multiple of one engine, T1 = 845 kN): off 0, min f_min, mid 1.0, max 3.0 (three
  engines). f_min is set by the rule `twr_min` = min-throttle thrust / weight at the FULL release mass, so the
  thrust-to-weight ratio at min throttle is > 1 at every fuel load: the booster cannot hover. Mass flow = thrust /
  (282 s * 9.80665). An off->lit command uses one relight (none left: the command is ignored); ignition delay 0.3 s;
  thrust slews at 2 T1/s up and 6 T1/s down. Gimbal commands -5, -2, 0, +2, +5 deg, slew 10 deg/s. The thrust vector
  is the body axis rotated by -gimbal, so gimbal R (+) gives a clockwise torque 14 m * T * sin(gimbal).
* Atmosphere and wind. rho = 1.225 exp(-h / 8.5 km). Horizontal wind w(h) = seeded surface wind + seeded jet stream
  (quartic bump around 9-12 km) + a seeded integer OU-like gust w_g(t) (1 s knots, linear in time). Air-relative
  velocity v_a = v - (w, 0); q = 0.5 rho |v_a|^2.
* Aerodynamics (flow unit vector f = -v_a/|v_a|, f_ax = f.b, crossflow f_c = f - f_ax b, sin(alpha) = |f_c|):
    axial force  q * (10.75 m^2 body + 1.5 m^2 fins * deploy + 6 m^2 legs * deploy) * f_ax  along b
    normal force q * (21.5 m^2 body at -6 m + 12 m^2 fins * deploy at +26 m) * f_c
    fin control  q * 1.2 m^2 * deploy * deflection * f_ax  along the body-right normal (cos th, -sin th) at +26 m
    damping      -K_D * q / |v_a| * omega  (K_D = 40000 m^4)
  Torque about the CG of a force F at distance d along the body: tau_cw = d * (cos th F_x - sin th F_y).
  Consequence (stated in the rules text): gliding engine-first the booster drifts toward where its ENGINES point
  (lean the top left to move right); under thrust it moves toward where its TOP points.
* Grid fins: 'stowed' retracts (1 s), any other command deploys (1 s); deflection left/neutral/right = -1/0/+1,
  slews 4/s. Legs: 'deploy' is one-way; 2 s to extend; while not stowed they add drag and tear off above q_leg.
* Heating. heat += isqrt(rho [1e-6 kg/m^3]) * ((V - 260 m/s)^+ [m/s])^3 / 1e6 per substep; limit 600,000 units
  (= 100 %, shown as %). Rule `entry_required`: heat above 100 % destroys the booster ('overheat'), which an entry burn
  prevents by slowing down high up (seeds 0-31: coasting through gives 117-344 %, the heuristic's burn 37-82 %). Failures:
  q > 60 kPa 'max_q'; q * sin(alpha) > 6 kPa 'breakup'; legs not stowed at q > 12 kPa 'legs_torn'; fuel out is a
  flameout (not a crash by itself).
* Touchdown when the lowest point (engine plane, or leg feet 1.5 m lower and 9 m out when deployed) reaches the
  surface. Target 'pad': ground y = 0 everywhere, pad |x| <= 30 m. Targets 'ship' / 'ship_moving': deck |x - x_s| <=
  20 m at 5 m above the sea (y = 0); the moving ship drifts, surges, heaves and pitches (seeded sines); outside the
  deck the surface is the sea. Success: legs fully deployed, on target, |vy_rel| <= land_vy, |vx_rel| <= land_vx,
  |tilt - deck pitch| <= land_tilt, |omega| <= land_rate. Else: 'no_legs', 'hard_landing', 'tip_over',
  'off_target' (ground outside the pad), 'splashdown' (sea).
* Score (per booster, in [0, 1], exact integer micro-units): 0.10 entry (alive below 12 km) + 0.15 glide (at 2.5 km
  altitude alive, |tilt| <= 30 deg, |x - target| <= 1 km) + 0.15 landing burn (lowest point 50 m above the surface
  alive, |vy| <= 20 m/s, |x - target| <= 100 m) + landed * (0.40 + 0.10 * precision + 0.10 * fuel), precision =
  1 - |dx| / half-width, fuel = min(1, fuel left / 4 t). Ranking: higher score first; equal scores tie.
* Queries (4 simultaneous per flying booster, canonical order): throttle (off, min, mid, max), gimbal (L2, L1, 0, R1,
  R2), fins (stowed, left, neutral, right), legs (stowed, deploy). Defaults = the current command (a late or invalid
  reply holds the previous command). A booster that landed or crashed gets no queries.
* Events: 'ignition' {relights_left}, 'shutdown', 'no_relight', 'flameout', 'legs', 'phase' {name}, 'landed'
  {dx_m, vy}, 'crash' {cause, x, y}, 'round_end' {scores}.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from functools import lru_cache
from math import isqrt

from nagi.burst2._rt.arena.core import Event, Query

# ================================================================== fixed-point math (pure integers)
ONE_BITS = 30
ONE = 1 << ONE_BITS
TURN_BITS = 20
TURN = 1 << TURN_BITS  # binary angle units (BAM) per full turn
TMASK = TURN - 1
QTURN = TURN >> 2
_TAB_BITS = 10
_FRAC_BITS = TURN_BITS - 2 - _TAB_BITS  # 8
_FRAC_MASK = (1 << _FRAC_BITS) - 1


def _pi_fixed(bits: int) -> int:
    """pi * 2^bits by Machin's formula, integer arithmetic only."""
    guard = bits + 16
    one = 1 << guard

    def atan_inv(n: int) -> int:
        term = one // n
        total, k, sign, n2 = term, 1, -1, n * n
        while term:
            term //= n2
            k += 2
            total += sign * (term // k)
            sign = -sign
        return total

    return (16 * atan_inv(5) - 4 * atan_inv(239)) >> 16


_P = 96
PI_P = _pi_fixed(_P)


def _round_shift(v: int, s: int) -> int:
    return (v + (1 << (s - 1))) >> s


def _sin_series(x: int) -> int:
    """sin(x) for 0 <= x <= pi/2, x and result scaled by 2^_P."""
    x2 = (x * x) >> _P
    term, total, k = x, x, 1
    while term:
        term = -((term * x2) >> _P) // ((k + 1) * (k + 2))
        total += term
        k += 2
    return total


def _exp_neg_series(x: int) -> int:
    """exp(-x) for 0 <= x <= 1, scaled by 2^_P."""
    term, total, k = 1 << _P, 1 << _P, 0
    while term:
        k += 1
        term = -((term * x) >> _P) // k
        total += term
    return total


_SIN = tuple(_round_shift(_sin_series(i * PI_P // (2 << _TAB_BITS)), _P - ONE_BITS) for i in range((1 << _TAB_BITS) + 1))


def isin(a: int) -> int:
    """sin of a BAM angle, scaled by ONE."""
    a &= TMASK
    q = a >> (TURN_BITS - 2)
    r = a & (QTURN - 1)
    if q & 1:
        r = QTURN - r
    i = r >> _FRAC_BITS
    f = r & _FRAC_MASK
    v = _SIN[i]
    if f:
        v += ((_SIN[i + 1] - v) * f) >> _FRAC_BITS
    return -v if q >= 2 else v


def icos(a: int) -> int:
    return isin(a + QTURN)


def rdiv(a: int, b: int) -> int:
    """Round-half-up integer division for b > 0 (deterministic on every platform)."""
    return (2 * a + b) // (2 * b)


def deg_to_bam(deg_milli: int) -> int:
    """milli-degrees -> BAM (rounded)."""
    return rdiv(deg_milli * TURN, 360_000)


def bam_to_mdeg(a: int) -> int:
    """BAM -> milli-degrees (rounded), a in any range."""
    return rdiv(a * 360_000, TURN)


def wrap_bam(a: int) -> int:
    """BAM angle wrapped to [-TURN/2, TURN/2)."""
    return ((a + (TURN >> 1)) & TMASK) - (TURN >> 1)


# ================================================================== constants (integers; SI in the comments)
SUB_MS = 50  # physics substep
SUB_HZ = 20
DECISION_MS = 250
MAX_ROUND_MS = 90_000  # Arena v3 admission G6: T_max <= 90 s

G_MM = 9810  # mm/s^2
M_DRY = 22_000_000  # g
FUEL0 = 9_000_000  # g
FUEL_REF = 4_000_000  # g: fuel score is min(1, fuel / 4 t)
T1 = 845_000  # N, one engine
ISP_G0 = 282 * 980665  # (s * mm/s^2 * 100): mdot [g/s] = T[N] * 1e8 / ISP_G0 (T/(Isp g0) kg/s)
MID_PM, MAX_PM = 1000, 3000  # thrust permille of T1
THR_UP, THR_DN = 100, 300  # permille per substep (2 T1/s, 6 T1/s)
IGN_SUB = 6  # 0.3 s ignition delay
GIM_OPTS = ("L2", "L1", "0", "R1", "R2")
GIM_MDEG = {"L2": -5000, "L1": -2000, "0": 0, "R1": 2000, "R2": 5000}
GIM_RATE = deg_to_bam(10_000) // SUB_HZ  # 10 deg/s
THR_OPTS = ("off", "min", "mid", "max")
FIN_OPTS = ("stowed", "left", "neutral", "right")
FIN_U = {"stowed": 0, "left": -1000, "neutral": 0, "right": 1000}
LEG_OPTS = ("stowed", "deploy")
FIN_DEP_RATE, FIN_U_RATE, LEG_RATE = 50, 200, 25  # per substep: 1 s deploy, 0.25 s full swing, 2 s legs

L_ENG = 14_000  # mm CG -> engine plane
D_FIN = 26_000  # mm CG -> grid fins (up)
D_BODY = -6_000  # mm CG -> body normal-force centre
R_BODY = 1_850  # mm
LEG_DOWN, LEG_SPAN = 1_500, 9_000  # mm
K2 = 121  # m^2 radius of gyration squared
# aero areas * coefficients, cm^2
SC_A_BODY, SC_A_FIN, SC_A_LEG = 107_500, 15_000, 60_000
SC_N_BODY, SC_N_FIN, SC_FC = 215_000, 120_000, 12_000
K_DAMP = 40_000  # m^4
RHO0_U = 1_225_000  # 1e-6 kg/m^3
H_SCALE = 8_500  # m
Q_MAX, QA_MAX, Q_LEG = 60_000, 6_000, 12_000  # Pa
HEAT_DIV = 10 ** 6  # heat units per substep = isqrt(rho_u) * ((V - 260 m/s)^+ in m/s)^3 // HEAT_DIV
V_HEAT = 260_000  # mm/s: no heating below 260 m/s air speed
HEAT_MAX = 600_000  # heat units (100 %): seeds 0-31: no entry burn 0.70-2.07 M, heuristic burn 0.22-0.49 M
V_AERO = 1_000  # mm/s: aero off below 1 m/s
TWO_PI_Q40 = (2 * PI_P) >> (_P - 40)  # 2 pi * 2^40

H_ENTRY_OK = 12_000_000  # mm
H_GLIDE_OK = 2_500_000
GLIDE_TILT = deg_to_bam(30_000)
GLIDE_DX = 1_000_000
BURN_H, BURN_VY, BURN_DX = 50_000, 20_000, 100_000

PAD_HW, SHIP_HW, DECK_H = 30_000, 20_000, 5_000  # mm

W_ENTRY, W_GLIDE, W_BURN, W_LAND, W_PREC, W_FUEL = 100_000, 150_000, 150_000, 400_000, 100_000, 100_000  # micro


# ================================================================== rules and variants
@dataclass(frozen=True)
class Rules:
    twr_min: int = 115  # x100: min-throttle thrust / weight at the FULL release mass (> 1: no hovering)
    relights: int = 3
    wind: str = "base"  # calm | base | strong
    target: str = "pad"  # pad | ship | ship_moving
    land_vy: int = 3_000  # mm/s
    land_vx: int = 1_500  # mm/s
    land_tilt: int = 5  # deg
    land_rate: int = 5  # deg/s
    entry_required: bool = True  # heating limit active

    @property
    def min_pm(self) -> int:
        """min throttle, thrust permille of T1."""
        return rdiv(self.twr_min * (M_DRY + FUEL0) * G_MM, 100 * T1 * 1000)

    def level_pm(self, lvl: str) -> int:
        return {"off": 0, "min": self.min_pm, "mid": MID_PM, "max": MAX_PM}[lvl]


BASE_RULES = Rules()


@dataclass(frozen=True)
class Variant:
    id: str
    split: str  # 'variant_dev' | 'variant_sealed'
    rules: Rules
    announce_text: str
    control: str  # the control whose planner-best option the variant is expected to move (tests)


VARIANTS = {v.id: v for v in (
    Variant("twr_soft", "variant_dev", replace(BASE_RULES, twr_min=102),
            "RULE CHANGE: min throttle TWR 1.02 at full fuel (not 1.15).", "throttle"),
    Variant("twr_hard", "variant_sealed", replace(BASE_RULES, twr_min=160),
            "RULE CHANGE: min throttle TWR 1.60 at full fuel (not 1.15).",
            "throttle"),
    Variant("relights_2", "variant_dev", replace(BASE_RULES, relights=2),
            "RULE CHANGE: 2 relights (not 3).", "throttle"),
    Variant("wind_calm", "variant_dev", replace(BASE_RULES, wind="calm"),
            "RULE CHANGE: no wind at any altitude.", "fins"),
    Variant("wind_strong", "variant_sealed", replace(BASE_RULES, wind="strong"),
            "RULE CHANGE: strong wind: surface wind and jet stream 2.5x, gusts 2x.", "fins"),
    Variant("target_ship", "variant_dev", replace(BASE_RULES, target="ship"),
            "RULE CHANGE: target is a drone ship at x = 0, deck 40 m wide, 5 m above the sea.",
            "gimbal"),
    Variant("target_ship_moving", "variant_sealed", replace(BASE_RULES, target="ship_moving"),
            "RULE CHANGE: target is a MOVING drone ship (deck 40 m wide, 5 m above sea); limits are deck-relative.", "gimbal"),
    Variant("land_strict", "variant_dev", replace(BASE_RULES, land_vy=1_500, land_vx=800, land_tilt=3, land_rate=3),
            "RULE CHANGE: landing limits sink 1.5, drift 0.8 m/s, tilt 3 deg, rate 3 deg/s.",
            "throttle"),
    Variant("land_lenient", "variant_sealed", replace(BASE_RULES, land_vy=6_000, land_vx=3_000, land_tilt=10,
                                                      land_rate=10),
            "RULE CHANGE: landing limits sink 6, drift 3 m/s, tilt 10 deg, rate 10 deg/s.",
            "throttle"),
    Variant("entry_optional", "variant_dev", replace(BASE_RULES, entry_required=False),
            "RULE CHANGE: no heating limit (entry burn optional).", "throttle"),
)}


def rules_for(variant: str | None) -> Rules:
    return VARIANTS[variant].rules if variant else BASE_RULES


def assert_not_sealed(variant_id: str | None, purpose: str) -> None:
    if variant_id and VARIANTS[variant_id].split == "variant_sealed":
        raise PermissionError(f"variant {variant_id} is SEALED; not allowed for {purpose}")


RULES_VERSION = "v3.0"


def _fmt_int(v: int, scale: int, nd: int, sign: bool = True) -> str:
    """Fixed-point integer v / scale with nd decimals (round half away from zero), integer-only."""
    neg = v < 0
    a = -v if neg else v
    m = 10 ** nd
    r = (2 * a * m + scale) // (2 * scale)
    s = str(r // m) + ("." + str(r % m).zfill(nd) if nd else "")
    if neg and r:
        return "-" + s
    return ("+" + s) if sign else s


def rules_text(rules: Rules = BASE_RULES, variant: Variant | None = None, announce: bool = True) -> str:
    """The rules paragraph (base numbers); an announced variant appends its RULE CHANGE sentence."""
    b = BASE_RULES
    t = (f"BOOSTER LANDING (rules {RULES_VERSION}): 2D, x right, y up, SI units. Land the falling booster "
         "upright on the target at x = 0 (pad 60 m wide). Decide every 0.25 s; controls hold. Tilt + = top toward "
         "+x; gimbal R and fins right turn the top to +x. Thrust along the body: min = 1 engine low, mid = 1 engine, "
         f"max = 3 engines. Min thrust > weight (TWR {_fmt_int(b.twr_min, 100, 2, False)} at full fuel): no hover; "
         f"light the landing burn so speed hits ~0 at touchdown. Each engine start uses 1 of {b.relights} relights, "
         "0.3 s delay. Unpowered in air it drifts toward where its engines "
         "point; under thrust, toward where its top points. Grid fins steer only at speed; stowed in dense air it "
         "tumbles. Lost if heat > 100% (an early burn slows it), q > 60 kPa, q x sin(attack angle) > 6 kPa, or legs "
         f"out at q > 12 kPa (legs take 2 s). Landing: legs out, on target, sink <= "
         f"{_fmt_int(b.land_vy, 1000, 1, False)}, drift <= {_fmt_int(b.land_vx, 1000, 1, False)} m/s, tilt <= "
         f"{b.land_tilt} deg, rate <= {b.land_rate} deg/s. Score: 0.1 below 12 km, 0.15 near target at 2.5 km, "
         "0.15 near and slow at 50 m, landing 0.4 + 0.1 accuracy + 0.1 fuel.")
    if variant is not None and announce:
        t += " " + variant.announce_text
    return t


# ================================================================== scenario (seeded, integer)


def _h(seed: int, key: str) -> int:
    return int.from_bytes(hashlib.sha256(f"booster|{int(seed)}|{key}".encode()).digest()[:8], "big")


def _u(seed: int, key: str, lo: int, hi: int) -> int:
    """Uniform integer in [lo, hi] (portable: sha256)."""
    return lo + _h(seed, key) % (hi - lo + 1)


def _rho_table() -> tuple:
    step = _exp_neg_series((100 << _P) // H_SCALE)  # exp(-100 m / H) at 2^_P
    out, acc = [], 1 << _P
    for _ in range(501):  # 0 .. 50 km every 100 m
        out.append(_round_shift(RHO0_U * acc, _P))
        acc = (acc * step) >> _P
    return tuple(out)


RHO_TAB = _rho_table()


def rho_at(y: int) -> int:
    """air density (1e-6 kg/m^3) at altitude y (mm), linear between 100 m knots."""
    if y <= 0:
        return RHO_TAB[0]
    i = y // 100_000
    if i >= 500:
        return RHO_TAB[500]
    a = RHO_TAB[i]
    return a + (RHO_TAB[i + 1] - a) * (y - i * 100_000) // 100_000


WIND_DZ = 250_000  # mm between wind knots
WIND_N = 161  # 0 .. 40 km
GUST_N = MAX_ROUND_MS // 1000 + 12  # 1 s knots


@dataclass(frozen=True)
class Scenario:
    seed: int
    rules: Rules
    x0: int
    y0: int
    vx0: int
    vy0: int
    th0: int
    wind: tuple  # mm/s per 250 m knot (mean profile)
    gust: tuple  # mm/s per 1 s knot
    ship: tuple  # (drift mm/s, surge amp mm, surge inc BAM/sub, surge ph, heave amp mm, heave inc, heave ph,
    #              pitch amp BAM, pitch inc, pitch ph)

    def wind_at(self, y: int, k: int) -> int:
        """horizontal wind (mm/s) at altitude y (mm) and substep k."""
        if y <= 0:
            w = self.wind[0]
        else:
            i = y // WIND_DZ
            if i >= WIND_N - 1:
                w = self.wind[-1]
            else:
                a = self.wind[i]
                w = a + (self.wind[i + 1] - a) * (y - i * WIND_DZ) // WIND_DZ
        j = k // SUB_HZ
        if j >= GUST_N - 1:
            return w + self.gust[-1]
        g0 = self.gust[j]
        return w + g0 + (self.gust[j + 1] - g0) * (k - j * SUB_HZ) // SUB_HZ

    def target(self, k: int) -> tuple[int, int, int, int, int, int]:
        """(x_centre, deck_y at centre, vx, vy, pitch BAM, pitch rate BAM/s) of the target at substep k."""
        tg = self.rules.target
        if tg == "pad":
            return 0, 0, 0, 0, 0, 0
        if tg == "ship":
            return 0, DECK_H, 0, 0, 0, 0
        dr, sa, si, sp, ha, hi, hp, pa, pi_, pp = self.ship
        a1, a2, a3 = sp + si * k, hp + hi * k, pp + pi_ * k
        # d/dt (A sin(ph0 + inc k)) = A cos(.) * inc * SUB_HZ * 2 pi / TURN
        x = dr * k // SUB_HZ + ((sa * isin(a1)) >> ONE_BITS)
        vx = dr + (((sa * icos(a1)) >> ONE_BITS) * si * SUB_HZ * TWO_PI_Q40 >> (40 + TURN_BITS))
        y = DECK_H + ((ha * isin(a2)) >> ONE_BITS)
        vy = ((ha * icos(a2)) >> ONE_BITS) * hi * SUB_HZ * TWO_PI_Q40 >> (40 + TURN_BITS)
        p = (pa * isin(a3)) >> ONE_BITS
        # pitch rate in BAM/s: A cos(.) * (2 pi inc SUB_HZ / TURN) rad/s per rad -> BAM/s is the same factor
        pr = ((pa * icos(a3)) >> ONE_BITS) * pi_ * SUB_HZ * TWO_PI_Q40 >> (40 + TURN_BITS)
        return x, y, vx, vy, p, pr


def _wind_profile(seed: int, mode: str) -> tuple[tuple, tuple]:
    if mode == "calm":
        return (0,) * WIND_N, (0,) * GUST_N
    mult = 25 if mode == "strong" else 10  # x10
    gmult = 20 if mode == "strong" else 10
    sfc = _u(seed, "w_sfc", -6000, 6000)
    jet = _u(seed, "w_jet", 10_000, 25_000) * (1 if _u(seed, "w_jet_sign", 0, 1) else -1)
    hj = _u(seed, "w_jet_h", 9_000, 12_000) * 1000
    wj = 4_000_000
    prof = []
    for i in range(WIND_N):
        y = i * WIND_DZ
        base = sfc + sfc * min(y, 2_000_000) // 4_000_000  # grows 50 % over the first 2 km
        d = y - hj
        bump = 0
        if -wj < d < wj:
            r = ONE - (d * d // wj) * ONE // wj  # 1 - (d/wj)^2
            bump = jet * ((r * r) >> ONE_BITS) // ONE
        prof.append((base + bump) * mult // 10)
    sig = _u(seed, "g_sig", 800, 2000) * gmult // 10  # mm/s
    gust, g = [], 0
    for j in range(GUST_N):
        e = sum(_u(seed, f"g{j}_{m}", -1000, 1000) for m in range(4))  # ~N(0, 1155^2)
        g = (g * 6 + e * sig * 8 // 1155) // 10  # AR(1) phi = 0.6, innovation 0.8 sig: stationary std ~ sig
        gust.append(g)
    return tuple(prof), tuple(gust)


@lru_cache(maxsize=256)
def build_scenario(seed: int, rules: Rules = BASE_RULES) -> Scenario:
    y0 = _u(seed, "y0", 17_500, 20_500) * 1000
    vy0 = -_u(seed, "vy0", 330, 420) * 1000
    vx0 = _u(seed, "vx0", 20, 90) * 1000 * (1 if _u(seed, "vx_sign", 0, 1) else -1)
    miss = _u(seed, "miss", 200, 1400) * 1000 * (1 if _u(seed, "miss_sign", 0, 1) else -1)
    x0 = -vx0 * 12 + miss  # ~12 s of effective lateral travel at release speed (drag decays vx): seeded miss
    th0 = deg_to_bam(_u(seed, "th0", -3000, 3000))
    wind, gust = _wind_profile(seed, rules.wind)
    ship = (0,) * 10
    if rules.target == "ship_moving":
        ship = (_u(seed, "s_drift", -3000, 3000),  # mm/s
                _u(seed, "s_surge", 3000, 8000), TURN // (SUB_HZ * _u(seed, "s_surge_T", 14, 22)), _u(seed, "s_sp", 0, TMASK),
                _u(seed, "s_heave", 500, 1500), TURN // (SUB_HZ * _u(seed, "s_heave_T", 6, 10)), _u(seed, "s_hp", 0, TMASK),
                deg_to_bam(_u(seed, "s_pitch", 1500, 3500)), TURN // (SUB_HZ * _u(seed, "s_pitch_T", 7, 11)),
                _u(seed, "s_pp", 0, TMASK))
    return Scenario(int(seed), rules, x0, y0, vx0, vy0, th0, wind, gust, ship)


# ================================================================== state


def new_booster(sc: Scenario) -> dict:
    return {"x": sc.x0, "y": sc.y0, "vx": sc.vx0, "vy": sc.vy0, "th": sc.th0, "w": 0,
            "fuel": FUEL0, "lit": 0, "ign": 0, "thr": 0, "thr_cmd": 0, "lvl": "off", "relights": sc.rules.relights,
            "gim": 0, "gim_cmd": 0, "gcmd": "0", "fin": "neutral", "fin_dep": 0, "fin_u": 0,
            "legs": 0, "legs_on": 0, "heat": 0, "q": 0, "qa": 0, "q_peak": 0, "wind": 0,
            "status": "flying", "cause": None, "t_end": None, "ph": 0, "td": None, "nr": 0,
            "last": ("off", "0", "neutral", "stowed")}


@dataclass
class BLState:
    seed: int
    k: int  # substeps elapsed
    t_ms: int
    boosters: list
    ended: bool = False


# ================================================================== physics core (integers only)


def surface_at(sc: Scenario, x: int, k: int) -> tuple[int, int, int, int, int, bool]:
    """(surface y, surface vx, surface vy, surface pitch BAM, target dx, on_target) under x at substep k."""
    tx, ty, tvx, tvy, tp, tpr = sc.target(k)
    dx = x - tx
    tg = sc.rules.target
    if tg == "pad":
        return 0, 0, 0, 0, dx, -PAD_HW <= dx <= PAD_HW
    if -SHIP_HW <= dx <= SHIP_HW:
        ys = ty + dx * isin(tp) // icos(tp) if tp else ty
        vys = tvy + (dx * tpr * TWO_PI_Q40 >> (40 + TURN_BITS)) if tpr else tvy  # + dx * pitch rate (rad/s)
        return ys, tvx, vys, tp, dx, True
    return 0, 0, 0, 0, dx, False


def integrate(h: dict, sc: Scenario, k0: int, nsub: int, events: list | None, p: int) -> int:
    """Advance booster h (in place) by nsub substeps from substep k0. Returns the substep index reached."""
    rules = sc.rules
    x, y, vx, vy, th, w = h["x"], h["y"], h["vx"], h["vy"], h["th"], h["w"]
    fuel, lit, ign, thr, thr_cmd = h["fuel"], h["lit"], h["ign"], h["thr"], h["thr_cmd"]
    gim, gim_cmd = h["gim"], h["gim_cmd"]
    fin_on = h["fin"] != "stowed"
    fin_dep, fin_u, fin_ut = h["fin_dep"], h["fin_u"], FIN_U[h["fin"]]
    legs, legs_on = h["legs"], h["legs_on"]
    heat, q_peak, ph = h["heat"], h["q_peak"], h["ph"]
    heat_on = rules.entry_required
    q = qa = wind = 0
    cause = None
    landed = False
    k = k0
    for _ in range(nsub):
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
            legs = min(1000, legs + LEG_RATE)
            if legs == 1000 and events is not None:
                events.append(Event((k + 1) * SUB_MS, "legs", p, {}))
        m = M_DRY + fuel
        S = isin(th)
        C = icos(th)
        Fx = Fy = tau = 0  # N, N, N*m (clockwise +)
        # ---- engine
        if thr:
            T = T1 * thr // 1000
            a = th - gim
            Fx += (T * isin(a)) >> ONE_BITS
            Fy += (T * icos(a)) >> ONE_BITS
            tau += (L_ENG * T * isin(gim)) // (1000 * ONE)
            fuel -= T * 100_000_000 // (ISP_G0 * SUB_HZ)
            if fuel <= 0:
                fuel = 0
                if lit and events is not None:
                    events.append(Event((k + 1) * SUB_MS, "flameout", p, {}))
                lit, thr, ign = 0, 0, 0
        # ---- aerodynamics
        wind = sc.wind_at(y, k)
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
            nb = q * SC_N_BODY // 10_000
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
            # damping: tau -= K_DAMP * q / V * omega_rad ; omega_rad = w * 2 pi / TURN ; V in m/s = V/1000
            tau -= K_DAMP * q * w * TWO_PI_Q40 * 1000 // (V << (40 + TURN_BITS))
            if heat_on and V > V_HEAT:
                vm = (V - V_HEAT) // 1000
                heat += isqrt(rho) * vm * vm * vm // HEAT_DIV
            if q > q_peak:
                q_peak = q
        else:
            q = qa = 0
        # ---- integrate (semi-implicit Euler)
        ax = Fx * 1_000_000 // m
        ay = Fy * 1_000_000 // m - G_MM
        alpha = tau * 1000 * TURN * (1 << 40) // (m * K2 * TWO_PI_Q40)  # BAM/s^2
        w += rdiv(alpha, SUB_HZ)
        th += rdiv(w, SUB_HZ)
        vx += rdiv(ax, SUB_HZ)
        vy += rdiv(ay, SUB_HZ)
        x += rdiv(vx, SUB_HZ)
        y += rdiv(vy, SUB_HZ)
        k += 1
        # ---- limits
        if heat_on and heat > HEAT_MAX:
            cause = "overheat"
        elif q > Q_MAX:
            cause = "max_q"
        elif qa > QA_MAX:
            cause = "breakup"
        elif legs and q > Q_LEG:
            cause = "legs_torn"
        # ---- phases and touchdown
        S = isin(th)
        C = icos(th)
        aS = S if S >= 0 else -S
        ys, vxs, vys, ps, dx, on_t = surface_at(sc, x, k)
        bot = y - ((L_ENG + LEG_DOWN * legs // 1000) * C >> ONE_BITS) - ((R_BODY + (LEG_SPAN - R_BODY) * legs // 1000) * aS >> ONE_BITS)
        if cause is None:
            if not ph & 1 and y <= H_ENTRY_OK:
                ph |= 1
                if events is not None:
                    events.append(Event(k * SUB_MS, "phase", p, {"name": "entry"}))
            if not ph & 18 and y <= H_GLIDE_OK:
                if -GLIDE_TILT <= wrap_bam(th) <= GLIDE_TILT and -GLIDE_DX <= dx <= GLIDE_DX:
                    ph |= 2
                    if events is not None:
                        events.append(Event(k * SUB_MS, "phase", p, {"name": "glide"}))
                else:
                    ph |= 16  # glide checkpoint passed without credit
            if not ph & 4 and not ph & 32 and bot - ys <= BURN_H:
                if -BURN_VY <= vy - vys <= BURN_VY and -BURN_DX <= dx <= BURN_DX:
                    ph |= 4
                    if events is not None:
                        events.append(Event(k * SUB_MS, "phase", p, {"name": "burn"}))
                else:
                    ph |= 32
            if bot <= ys:
                vyr, vxr = vy - vys, vx - vxs
                tilt = wrap_bam(th - ps)
                lim_t = deg_to_bam(rules.land_tilt * 1000)
                lim_w = deg_to_bam(rules.land_rate * 1000)
                if rules.target != "pad" and not on_t:
                    cause = "splashdown"
                elif legs < 1000:
                    cause = "no_legs"
                elif vyr < -rules.land_vy or vyr > rules.land_vy:
                    cause = "hard_landing"
                elif not (-rules.land_vx <= vxr <= rules.land_vx and -lim_t <= tilt <= lim_t and -lim_w <= w <= lim_w):
                    cause = "tip_over"
                elif not on_t:
                    cause = "off_target"
                h["td"] = (dx, vyr, vxr, tilt, w)
                if cause is None:
                    landed = True
                    y = y + ys - bot
                    lit, thr = 0, 0
                    if events is not None:
                        events.append(Event(k * SUB_MS, "landed", p, {"dx_m": dx // 1000, "vy": vyr}))
                    break
        if cause is not None:
            break
    h.update(x=x, y=y, vx=vx, vy=vy, th=th, w=w, fuel=fuel, lit=lit, ign=ign, thr=thr, gim=gim, fin_dep=fin_dep,
             fin_u=fin_u, legs=legs, heat=heat, q=q, qa=qa, q_peak=q_peak, wind=wind, ph=ph)
    if landed:
        h["status"], h["t_end"] = "landed", k * SUB_MS
    elif cause is not None:
        h["status"], h["cause"], h["t_end"] = "crashed", cause, k * SUB_MS
        if events is not None:
            events.append(Event(k * SUB_MS, "crash", p, {"cause": cause, "x": x // 1000, "y": y // 1000}))
    return k


def apply_action(h: dict, rules: Rules, a: dict, events: list | None, p: int, t_ms: int) -> None:
    """Set the commands of booster h from one decision's answers (invalid/missing -> hold the current command)."""
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
            h["lit"], h["ign"], h["nr"] = 1, IGN_SUB, 0
            if events is not None:
                events.append(Event(t_ms, "ignition", p, {"relights_left": h["relights"]}))
        else:  # no relight left (or no fuel): the start command is ignored
            if events is not None and not h["nr"]:
                events.append(Event(t_ms, "no_relight", p, {}))
            h["nr"] = 1
            lvl = "off"
    h["lvl"] = lvl
    h["thr_cmd"] = rules.level_pm(lvl) if h["lit"] else 0
    g = a.get("gimbal", h["gcmd"])
    g = g if g in GIM_MDEG else h["gcmd"]
    h["gcmd"], h["gim_cmd"] = g, deg_to_bam(GIM_MDEG[g])
    f = a.get("fins", h["fin"])
    h["fin"] = f if f in FIN_U else h["fin"]
    if a.get("legs") == "deploy":
        h["legs_on"] = 1
    h["last"] = (h["lvl"], h["gcmd"], h["fin"], "deploy" if h["legs_on"] else "stowed")


def score_micro(h: dict, rules: Rules) -> int:
    """Score in micro-units (exact integer), in [0, 1_000_000]."""
    ph = h["ph"]
    s = (W_ENTRY if ph & 1 else 0) + (W_GLIDE if ph & 2 else 0) + (W_BURN if ph & 4 else 0)
    if h["status"] == "landed":
        dx = abs(h["td"][0])
        hw = PAD_HW if rules.target == "pad" else SHIP_HW
        s += W_LAND + W_PREC * max(0, hw - dx) // hw + W_FUEL * min(FUEL_REF, h["fuel"]) // FUEL_REF
    return s


# ================================================================== the game


def _mps(v: int, nd: int = 1) -> str:
    return _fmt_int(v, 1000, nd)


def _deg(a: int, nd: int = 1) -> str:
    return _fmt_int(bam_to_mdeg(a), 1000, nd)


PHASE_NAMES = ("COAST", "ENTRY BURN", "GLIDE", "LANDING BURN")


class Booster:
    """Arena v3 game: n independent same-seed boosters (ghosts, no interaction), rules + variant + L0/L1 sensors.

    Implements the arena.core.Game protocol (Referee lockstep/realtime, ChordReferee) and the GameV2 surface the v2
    runner uses (ctx, rules_id, multi_query, sensor_top), so arena.v2.runner.V2Referee plays it unchanged."""

    id = "booster"

    def __init__(self, variant: str | None = None, announce: bool = True, sensors: bool = True, n_players: int = 1,
                 decision_period_ms: int = DECISION_MS, max_round_ms: int = MAX_ROUND_MS, rules: Rules | None = None):
        assert decision_period_ms % SUB_MS == 0 and decision_period_ms > 0, decision_period_ms
        self.variant = VARIANTS[variant] if variant else None
        self.rules = rules if rules is not None else rules_for(variant)
        self.announce, self.sensors, self.n_players = announce, sensors, n_players
        self.decision_period_ms, self.max_round_ms = decision_period_ms, max_round_ms
        self.rules_text = rules_text(self.rules, self.variant, announce)
        self.engine = self  # bots written for GameV2 read game.engine

    @property
    def rules_id(self) -> str:
        v = self.variant.id if self.variant else "base"
        ann = "announced" if self.announce or not self.variant else "unannounced"
        return f"booster:{RULES_VERSION}:{v}:{ann}:{'L1' if self.sensors else 'L0'}:{self.decision_period_ms}ms"

    def ctx(self):
        import contextlib
        return contextlib.nullcontext()

    def scenario(self, seed: int) -> Scenario:
        return build_scenario(seed, self.rules)

    # -------------------------------------------------------------- protocol
    def reset(self, seed: int) -> BLState:
        sc = self.scenario(seed)
        return BLState(seed=int(seed), k=0, t_ms=0, boosters=[new_booster(sc) for _ in range(self.n_players)])

    def queries(self, s: BLState, player: int, answers: dict) -> list[Query]:
        h = s.boosters[player]
        if h["status"] != "flying" or s.ended or answers:
            return []
        obs = self.observation(s, player)
        return [Query(player, key, obs + "\nChoose " + line, opts, default)
                for key, line, opts, default in self._controls(h)]

    def _controls(self, h: dict):
        r = self.rules
        m = M_DRY + h["fuel"]
        twr = "/".join(_fmt_int(r.level_pm(lv) * T1 * 100_000 // (m * G_MM), 100, 2, False) for lv in ("min", "mid", "max"))
        return (
            ("throttle", f"THROTTLE (TWR now {twr}; starting uses a relight)", THR_OPTS, h["lvl"]),
            ("gimbal", "GIMBAL deg: L2 -5, L1 -2, 0, R1 +2, R2 +5 (only while burning)", GIM_OPTS, h["gcmd"]),
            ("fins", "FINS (right: top to +x)", FIN_OPTS, h["fin"]),
            ("legs", "LEGS (deploy is one-way)", LEG_OPTS, "deploy" if h["legs_on"] else "stowed"),
        )

    def multi_query(self, s: BLState, player: int):
        from nagi.burst2._rt.arena.chord import MultiQuery
        h = s.boosters[player]
        if h["status"] != "flying" or s.ended:
            return None
        obs = self.observation(s, player)
        ctl = self._controls(h)
        text = obs + "\nControls:\n" + "\n".join(c[1] for c in ctl)
        return MultiQuery(player, text, tuple((c[0], c[2], c[3]) for c in ctl))

    def step(self, s: BLState, actions: dict, dt_ms: int) -> tuple[BLState, list[Event]]:
        assert dt_ms % SUB_MS == 0, dt_ms
        sc = self.scenario(s.seed)
        nsub = dt_ms // SUB_MS
        boosters = [dict(h) for h in s.boosters]
        events: list[Event] = []
        if not s.ended:
            for p, h in enumerate(boosters):
                if h["status"] != "flying":
                    continue
                apply_action(h, self.rules, actions.get(p, {}) or {}, events, p, s.t_ms)
                integrate(h, sc, s.k, nsub, events, p)
        t2 = s.t_ms + dt_ms
        s2 = BLState(seed=s.seed, k=s.k + nsub, t_ms=t2, boosters=boosters, ended=s.ended)
        if not s2.ended:
            if t2 >= self.max_round_ms:
                for p, h in enumerate(boosters):
                    if h["status"] == "flying":
                        h["status"], h["cause"], h["t_end"] = "timeout", "timeout", t2
                        events.append(Event(t2, "crash", p, {"cause": "timeout", "x": h["x"] // 1000,
                                                              "y": h["y"] // 1000}))
            if all(h["status"] != "flying" for h in boosters):
                s2.ended = True
                events.append(Event(t2, "round_end", None, {"scores": [self.score(h) for h in boosters]}))
        events.sort(key=lambda e: e.t_ms)
        return s2, events

    def done(self, s: BLState) -> bool:
        return s.ended or s.t_ms >= self.max_round_ms or all(h["status"] != "flying" for h in s.boosters)

    def score_micro(self, h: dict) -> int:
        return score_micro(h, self.rules)

    def score(self, h: dict) -> float:
        return self.score_micro(h) / 1_000_000

    def ranking(self, s: BLState) -> list[list[int]]:
        sc = [self.score_micro(h) for h in s.boosters]
        return [[p for p in range(self.n_players) if sc[p] == v] for v in sorted(set(sc), reverse=True)]

    def state_hash(self, s: BLState) -> str:
        parts = [repr((s.seed, s.k, s.t_ms, s.ended))]
        for h in s.boosters:
            parts.append(repr(sorted(h.items())))
        return hashlib.sha256("|".join(parts).encode()).hexdigest()

    # -------------------------------------------------------------- observation
    def phase(self, h: dict) -> str:
        """Display label only (not state): burns by altitude; unpowered = GLIDE once q >= 5 kPa or below 12 km."""
        if h["lit"]:
            return "ENTRY BURN" if h["y"] > 6_000_000 else "LANDING BURN"
        if h["ph"] & 1 or h["y"] <= H_ENTRY_OK or h["q"] >= 5_000:
            return "GLIDE"
        return "COAST"

    def observe(self, s: BLState, p: int) -> dict:
        """The numbers behind the observation text (SI floats, for bots/tests; engine state stays integer)."""
        sc = self.scenario(s.seed)
        h = s.boosters[p]
        ys, vxs, vys, ps, dx, on_t = surface_at(sc, h["x"], s.k)
        tx, ty, tvx, tvy, tp, tpr = sc.target(s.k)
        m = M_DRY + h["fuel"]
        S, C = isin(h["th"]), icos(h["th"])
        aS = abs(S)
        bot = h["y"] - ((L_ENG + LEG_DOWN * h["legs"] // 1000) * C >> ONE_BITS) - (
            (R_BODY + (LEG_SPAN - R_BODY) * h["legs"] // 1000) * aS >> ONE_BITS)
        return {"t": s.t_ms / 1000, "alt": h["y"] / 1000, "agl": (bot - ty) / 1000, "x": h["x"] / 1000,
                "vx": h["vx"] / 1000, "vy": h["vy"] / 1000, "tilt": bam_to_mdeg(wrap_bam(h["th"])) / 1000,
                "rate": bam_to_mdeg(h["w"]) / 1000, "dx": (tx - h["x"]) / 1000, "tvx": tvx / 1000, "tvy": tvy / 1000,
                "tpitch": bam_to_mdeg(tp) / 1000, "wind": h["wind"] / 1000, "lit": bool(h["lit"]),
                "lvl": h["lvl"], "thr": h["thr"] / 1000, "relights": h["relights"], "gimbal": bam_to_mdeg(h["gim"]) / 1000,
                "fuel": h["fuel"] / 1000, "mass": m / 1000, "fins": h["fin"], "fin_dep": h["fin_dep"] / 1000,
                "legs": h["legs"] / 1000, "legs_on": bool(h["legs_on"]), "q": h["q"] / 1000,
                "heat": 100 * h["heat"] / HEAT_MAX if self.rules.entry_required else None, "phase": self.phase(h),
                "score": self.score(h), "twr": [self.rules.level_pm(lv) * T1 / 1000 / (m / 1000 * 9.81)
                                                for lv in ("min", "mid", "max")]}

    def sensor_lines(self, s: BLState, p: int) -> list[str]:
        """L1 shared sensor: per lit throttle level, the height above the target surface where the fall would stop
        if that level were held from now, thrust vertical, no drag (negative = hits first)."""
        h = s.boosters[p]
        sc = self.scenario(s.seed)
        ty = sc.target(s.k)[1]
        m = M_DRY + h["fuel"]
        v = h["vy"]
        hb = h["y"] - L_ENG - LEG_DOWN - ty
        out = []
        for lv in ("min", "mid", "max"):
            a = self.rules.level_pm(lv) * T1 * 1000 // m - G_MM  # mm/s^2 net upward
            out.append(f"{lv} {_fmt_int(hb - v * v // (2 * a), 1000, 0)}" if v < 0 else f"{lv} rising")
        return ["SENSOR stop height (m) if burning from now: " + ", ".join(out)]

    def observation(self, s: BLState, p: int) -> str:
        h = s.boosters[p]
        sc = self.scenario(s.seed)
        tx, ty, tvx, tvy, tp, tpr = sc.target(s.k)
        r = self.rules
        agl = h["y"] - L_ENG - ty
        heat = f"heat {100 * h['heat'] // HEAT_MAX}%" if r.entry_required else "heat no limit"
        tname = {"pad": "PAD", "ship": "SHIP", "ship_moving": "MOVING SHIP"}[r.target]
        legs = ("DEPLOYING " + str(h["legs"] // 10) + "%") if h["legs_on"] and h["legs"] < 1000 else (
            "DOWN" if h["legs_on"] else "STOWED")
        ship = (f", deck vx {_mps(tvx)}, pitch {_deg(tp)}" if r.target == "ship_moving" else "")
        lines = [
            self.rules_text,
            f"STATE t {_fmt_int(s.t_ms, 1000, 2, False)} s {self.phase(h)} | height {_fmt_int(agl, 1000, 0)} m | "
            f"vx {_mps(h['vx'])} vy {_mps(h['vy'])} m/s | tilt {_deg(wrap_bam(h['th']))} deg, rate {_deg(h['w'])} deg/s",
            f"target {tname} dx {_fmt_int(tx - h['x'], 1000, 0)} m{ship} | wind {_mps(h['wind'])} m/s",
            f"engine {('ON ' + h['lvl'] + ' ' + _fmt_int(h['thr'] * T1 // 1000, 1000, 0, False) + ' kN') if h['lit'] else 'OFF'}, "
            f"relights {h['relights']}/{r.relights}, gimbal {_deg(h['gim'])} | fuel {_fmt_int(h['fuel'], 1000, 0, False)} kg | "
            f"fins {h['fin'].upper()} {h['fin_dep'] // 10}% | legs {legs} | q {_fmt_int(h['q'], 1000, 1, False)} kPa | {heat}",
        ]
        if self.sensors:
            lines += self.sensor_lines(s, p)
        return "\n".join(lines)

    def sensor_top(self, s: BLState, q: Query, answers: dict) -> str | None:
        """Throttle option the L1 sensor suggests (diagnostic): the lowest lit level whose stop height is in
        [0, 300 m]; 'off' if even 'min' stops above 300 m or the booster rises; 'max' if all levels hit first."""
        if q.key != "throttle" or not self.sensors:
            return None
        h = s.boosters[q.player]
        sc = self.scenario(s.seed)
        ty = sc.target(s.k)[1]
        m = M_DRY + h["fuel"]
        v = h["vy"]
        if v >= 0:
            return "off"
        hb = h["y"] - L_ENG - LEG_DOWN - ty
        stops = {}
        for lv in ("min", "mid", "max"):
            a = self.rules.level_pm(lv) * T1 * 1000 // m - G_MM
            stops[lv] = hb - v * v // (2 * a)
        if stops["min"] > 300_000:
            return "off"
        for lv in ("min", "mid", "max"):
            if 0 <= stops[lv] <= 300_000:
                return lv
        return "max"

    # -------------------------------------------------------------- render
    def render_state(self, s: BLState) -> dict:
        sc = self.scenario(s.seed)
        tx, ty, tvx, tvy, tp, tpr = sc.target(s.k)
        bs = []
        for h in s.boosters:
            bs.append({"x": h["x"] / 1000, "y": h["y"] / 1000, "vx": h["vx"] / 1000, "vy": h["vy"] / 1000,
                       "tilt_deg": bam_to_mdeg(wrap_bam(h["th"])) / 1000, "rate_dps": bam_to_mdeg(h["w"]) / 1000,
                       "thrust_t1": h["thr"] / 1000, "lvl": h["lvl"], "lit": bool(h["lit"]),
                       "gimbal_deg": bam_to_mdeg(h["gim"]) / 1000, "fin": h["fin"], "fin_dep": h["fin_dep"] / 1000,
                       "fin_u": h["fin_u"] / 1000, "legs": h["legs"] / 1000, "fuel_kg": h["fuel"] / 1000,
                       "relights": h["relights"], "q_kpa": h["q"] / 1000, "q_peak_kpa": h["q_peak"] / 1000,
                       "heat_pct": 100 * h["heat"] / HEAT_MAX, "wind": h["wind"] / 1000, "status": h["status"],
                       "cause": h["cause"], "phase": self.phase(h), "ph": h["ph"], "score": self.score(h),
                       "last_action": list(h["last"])})
        return {"t_ms": s.t_ms, "course": {"id": self.id, "seed": s.seed, "rules_id": self.rules_id},
                "target": {"kind": self.rules.target, "x": tx / 1000, "y": ty / 1000, "pitch_deg": bam_to_mdeg(tp) / 1000,
                           "half_width": (PAD_HW if self.rules.target == "pad" else SHIP_HW) / 1000},
                "boosters": bs, "ended": s.ended}


# ================================================================== determinism probe (admission G4)
HASH_SEED0 = 20260926


def scripted_action(i: int, x: int) -> tuple[dict, int]:
    """Deterministic pseudo-random action for step i from an integer LCG state x (no floats): exercises every control;
    burns in bursts so flights last and relights, legs and fins all change."""
    x = (x * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
    r = x >> 33
    burst = (i // 12) % 5
    thr = ("off", "max", "off", "mid", "min")[burst] if r % 7 else THR_OPTS[r % 4]
    act = {"throttle": thr, "gimbal": GIM_OPTS[(r >> 3) % 5], "fins": FIN_OPTS[(r >> 6) % 4],
           "legs": "deploy" if (r >> 9) % 97 == 0 else "stowed"}
    return act, x


def determinism_chain(steps: int = 1000, seed0: int = HASH_SEED0, variant: str | None = None) -> str:
    """sha256 chain over `steps` decision ticks of scripted play (new round with seed+1 whenever one ends):
    H_0 = sha256(''), H_i = sha256(H_{i-1} + state_hash_i). Equal on every platform iff the engine is bit-exact."""
    g = Booster(variant)
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
    print("booster determinism chain (1000 steps):", determinism_chain())
