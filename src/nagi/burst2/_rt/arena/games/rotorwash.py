"""G2 ROTORWASH: 2D side-view rescue helicopter in a seeded sea cave, 4 same-seed ghosts (DESIGN.md §1 G2).

Exact rules (the rules text sent to every model is RULES below; it states the same thing in short form):

* Frame and units. SI, float64. x forward (right), y up, y = 0 is an arbitrary datum. Pitch theta is
  positive NOSE-DOWN, so thrust direction n = (sin theta, cos theta) and body-forward f = (cos theta,
  -sin theta). Fixed-step semi-implicit Euler at 240 Hz (velocities first, then positions). Controls
  are zero-order held for the 60 substeps between two decisions (decision period 250 ms). Round cap
  90 s. The four players are independent ghosts: same course, same wind, never interact.
* Mass. Airframe 1200 kg + fuel (starts 200 kg) + 300 kg load while hooked. Fuel burn = SFC * P_engine.
* Thrust. T = K_T * (Omega/Omega_n)^2 * c_eff * GE, along n. c_eff = c * (1 - vrs_loss).
  GE = 1 + 0.25 exp(-h/R), h = rotor-hub height above the surface below (floor, water or ship deck).
  Vortex ring state: v_h = sqrt(W / (2 rho A)) with W the current total weight; vd = descent speed of
  the air-relative velocity along n, ve = |air-relative velocity along f|. loss = 0.4 * S(a) * S(b),
  a = clip((vd/v_h - 0.6)/0.3), b = clip((0.3 - ve/v_h)/0.15), S = smoothstep. So loss > 0 exactly
  when vd > 0.6 v_h and ve < 0.3 v_h, and the full 40 % from vd >= 0.9 v_h and ve <= 0.15 v_h.
* Rotor. P_req = K_P * (K_T r^2 c)^1.5 + P_0 r^3, r = Omega/Omega_n (induced power ~ T^1.5 from the
  collective demand, plus profile power). Governor: P_cmd = clip(P_req + K_G (1 - r) P_avail, 0, P_avail);
  engine power follows it with a first-order lag TAU_E. Rotor: I Omega dOmega/dt = P_eng - P_req.
  Demand above P_avail therefore droops RPM, which cuts thrust by r^2. r < 0.85 for more than 1 s
  (continuously) is a crash 'rotor_stall'.
* Pitch. dw/dt = K_U (T / T_REF) u - D_W w - K_TH theta (cyclic moment ~ T u, aero rate damping and
  aero/SAS pitch stiffness), u in [-1, 1]. Steady pitch at hover thrust is ~ +/-10 deg (u = 0.3) and
  +/-20 deg (u = 0.6).
* Drag and wind. F = -0.5 rho |v_air| (CDA_X v_air_x, CDA_Y v_air_y), v_air = v - wind(x, y, t).
  wind = per-leg mean (smoothed in x) + gust scale(x) * unit OU gust (tau 2.5 s, seeded by course seed,
  a function of time only) + one shear zone per leg: horizontal shear S tanh((y - y_c)/5) and a
  downdraft, both tapered by sin over the 60 m zone. Everything is seeded by the seed only.
* Sling. Massless inextensible rope from the airframe CG to a 300 kg point load; phi is the rope angle
  from vertical (positive = load toward +x). With e = (sin phi, -cos phi), e_phi = (cos phi, sin phi),
  a_h = airframe acceleration from all non-rope forces (incl. gravity):
      phi'' = (-g sin phi + F_load_drag.e_phi / m - a_h.e_phi - 2 L' phi') / L
      tension = mu (g cos phi + L phi'^2 + F_load_drag.e / m - a_h.e),  mu = m M / (m + M), clipped >= 0
  and the airframe gets tension * e. The load feels drag (CDA_LOAD) against the local wind. The winch
  moves L at 2 m/s inside [5, 25] m. |phi| > 50 deg is a crash 'sling_swing'. The load does not collide
  with terrain. Without a load the rope hangs straight down (hook at y - L).
* Crash (causes): 'ceiling' any body point at or above the cave ceiling; 'rotor_strike' a rotor point
  (hub, disc tips) at/below the floor; 'tail_strike' tail point; 'terrain' nose or skid on the cave floor
  or the cave end walls; 'water' any point below the water surface of a bay; 'ship_strike' a non-skid
  point inside the ship hull; skids on the ship deck: relative vertical speed < -2.5 m/s 'hard_landing',
  |theta| >= 12 deg 'landing_attitude', otherwise a valid landing; 'rotor_stall'; 'fuel' (empty).
* Landed. After a valid landing the airframe rides the deck (x fixed, theta = 0, vy = deck vy) until
  the thrust exceeds total weight * (g + deck acceleration) / g, then it lifts off with the deck's vy.
* Course (seed only). Legs of LEG_LEN m. Floor/ceiling polylines at 5 m spacing: a meandering midline
  whose amplitude grows with distance, a gap that narrows from 70 m to 24 m, roughness, stalactites
  and rocks that grow per leg. Leg k: survivor on a flat ledge at ~X_k + 215 m, then a flooded bay
  (X_k + 370 .. X_k + 500) with a ship; deck = water + 7 m + heave (sine + two seeded sines, amplitude
  grows per leg). Gusts, mean wind and shear strength grow per leg.
* Task. Active leg j = first leg whose ship is not yet passed by more than 30 m (and >= the leg after
  the last delivery). Hook: survivor j not yet rescued, no load, |x - x_s| <= 4 m, ground speed
  < 1 m/s and hook end (y - L) at most 2 m above the survivor, all continuously for 1.5 s -> 'hooked'.
  Delivery: a valid landing on any ship deck with the load -> 'delivered', load released, leg j' + 1.
* Score = (max x reached - start x) + 500 * deliveries. Ranking: higher score first, equal scores
  (rounded to 1 mm) tie. The round is done when all four crashed or at the 90 s cap.
* Queries (3 simultaneous per living heli, canonical order, defaults): 'collective' (down2, down1,
  hold, up1, up2) default hold, steps of 0.05, c clipped to [0, 1]; 'cyclic' (aft2, aft1, center, fwd1,
  fwd2) default center, sets u = -0.6, -0.3, 0, 0.3, 0.6; 'winch' (up, hold, down) default hold,
  up = shorten. A crashed heli gets no queries.
* Events: 'hooked' {leg}, 'delivered' {leg, ship}, 'crash' {cause, x, y}, 'vortex_ring' {loss} (loss
  rises above 0.05), 'rpm_droop' {rpm_pct} (r falls below 0.95, re-armed above 0.97), 'gust' {speed}
  (local gust speed rises above 4 m/s, re-armed below 3), 'round_end' {scores}.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from nagi.burst2._rt.arena.core import Event, Query

# ------------------------------------------------------------------ constants (all SI)
HZ = 240
DT = 1.0 / HZ
G = 9.81
RHO = 1.225
R_ROTOR = 5.0
A_DISC = math.pi * R_ROTOR ** 2
M_AIR, M_FUEL0, M_LOAD = 1200.0, 200.0, 300.0
K_T = 30000.0  # N, thrust at c = 1, 100 % RPM, no GE
OMEGA_N = 40.0  # rad/s nominal rotor speed
I_ROTOR = 500.0  # kg m^2 (0.4 MJ stored at 100 %)
FM = 0.7  # figure of merit
K_P = 1.0 / (FM * math.sqrt(2.0 * RHO * A_DISC))  # W per N^1.5
P_0 = 40000.0  # W profile power at 100 %
P_AVAIL = 330000.0  # W engine limit
K_G = 2.0  # governor gain (fraction of P_avail per unit RPM error)
TAU_E = 0.5  # s engine lag
STALL_R, STALL_T = 0.85, 1.0
SFC = 7.5e-6  # kg/J (game-scaled: ~1.5 kg/s in hover)
T_REF = (M_AIR + M_FUEL0) * G
K_U, D_W, K_TH = 5.24, 4.8, 9.0  # pitch: rad/s^2 per u at T_REF, 1/s, 1/s^2
CDA_X, CDA_Y, CDA_LOAD = 10.0, 12.0, 1.0  # m^2 effective drag areas (x incl. rotor H-force)
KDX, KDY, KDL = 0.5 * RHO * CDA_X, 0.5 * RHO * CDA_Y, 0.5 * RHO * CDA_LOAD
L_MIN, L_MAX, WINCH_V = 5.0, 25.0, 2.0
PHI_MAX = math.radians(50.0)
LAND_VY, LAND_TH = 2.5, math.radians(12.0)
HOOK_DX, HOOK_V, HOOK_DY, HOOK_T = 4.0, 1.0, 2.0, 1.5
VRS_ON, VRS_SPAN, VRS_H, VRS_HSPAN, VRS_MAX = 0.6, 0.3, 0.3, 0.15, 0.4
GE_GAIN = 0.25
C_STEP = 0.05
CYCLIC = {"aft2": -0.6, "aft1": -0.3, "center": 0.0, "fwd1": 0.3, "fwd2": 0.6}
COLL = {"down2": -2, "down1": -1, "hold": 0, "up1": 1, "up2": 2}
WINCH = {"up": -WINCH_V, "hold": 0.0, "down": WINCH_V}
COLL_OPTS = ("down2", "down1", "hold", "up1", "up2")
CYC_OPTS = ("aft2", "aft1", "center", "fwd1", "fwd2")
WINCH_OPTS = ("up", "hold", "down")
C0 = 0.45  # start collective (hover needs ~0.458 at start mass)

# airframe geometry in body frame (bx forward, by up), kind: s skid, b body, r rotor, t tail
POINTS = ((1.6, -1.5, "s"), (-1.6, -1.5, "s"), (2.4, -0.3, "b"), (5.0, 1.6, "r"), (-5.0, 1.6, "r"),
          (0.0, 1.6, "r"), (-7.2, 0.5, "t"), (-7.2, 1.4, "t"))
EXTENT = 7.5  # >= max |point| (7.33)
SKID_H = 1.5
HUB_H = 1.6

# course
DX = 5.0
LEG_LEN = 520.0
N_LEGS = 10
X_START = 40.0
GAP0, GAP_SLOPE, GAP_MIN, MIN_CLEAR = 70.0, 10.0, 24.0, 20.0
SHIP_HALF = 13.0  # deck half width (the whole deck is the pad)
DECK_ABOVE_WATER = 7.0
HULL_DEPTH = 6.0
RAY_ANGLES = (90, 45, 15, 0, -15, -45, -90)  # degrees from +x, world frame, from the CG
RAY_NAMES = ("up", "up45", "fwd15up", "fwd", "fwd15dn", "dn45", "down")
RAY_MAX = 80.0

DECISION_MS, MAX_ROUND_MS = 250, 90000
MAX_STEPS = MAX_ROUND_MS * HZ // 1000


# ------------------------------------------------------------------ course


@dataclass(frozen=True)
class Course:
    seed: int
    n: int
    xmax: float
    F: list  # floor at x = i*DX (water surface inside bays)
    C: list  # ceiling
    FH: list  # max floor over cells i-2..i+2 (quick reject)
    CL: list  # min ceiling over cells i-2..i+2
    BAY: list  # 1 if the cell is a flooded bay
    WMX: list  # mean horizontal wind per cell
    GSX: list  # gust scale per cell (horizontal / vertical)
    GSY: list
    SHA: list  # shear amplitude (tapered), 0 outside zones
    SHY: list  # shear centre height
    DD: list  # downdraft (vertical wind, tapered)
    SHIPC: list  # ship index for cells within 25 m of a ship, else -1
    GX: list  # unit OU gusts at 240 Hz (index = substep)
    GY: list
    surv: tuple  # ((x, y), ...) per leg
    ships: tuple  # ((x, base, a1, w1, p1, a2, w2, p2, a3, w3, p3), ...) per leg
    shear: tuple  # ((xa, xb, amplitude, downdraft), ...)
    mean_wind: tuple
    y_start: float

    def deck(self, j: int, t: float) -> tuple[float, float, float]:
        """Deck height, vertical speed, vertical acceleration of ship j at time t."""
        _, b, a1, w1, p1, a2, w2, p2, a3, w3, p3 = self.ships[j]
        s1, s2, s3 = math.sin(w1 * t + p1), math.sin(w2 * t + p2), math.sin(w3 * t + p3)
        y = b + a1 * s1 + a2 * s2 + a3 * s3
        vy = a1 * w1 * math.cos(w1 * t + p1) + a2 * w2 * math.cos(w2 * t + p2) + a3 * w3 * math.cos(w3 * t + p3)
        ay = -(a1 * w1 * w1 * s1 + a2 * w2 * w2 * s2 + a3 * w3 * w3 * s3)
        return y, vy, ay

    def floor_at(self, x: float) -> float:
        i = min(max(int(x / DX), 0), self.n - 2)
        f = x / DX - i
        return self.F[i] + (self.F[i + 1] - self.F[i]) * f

    def ceil_at(self, x: float) -> float:
        i = min(max(int(x / DX), 0), self.n - 2)
        f = x / DX - i
        return self.C[i] + (self.C[i + 1] - self.C[i]) * f

    def wind(self, x: float, y: float, k: int) -> tuple[float, float]:
        i = min(max(int(x / DX), 0), self.n - 1)
        k = min(k, len(self.GX) - 1)
        wx = self.WMX[i] + self.GSX[i] * self.GX[k]
        if self.SHA[i]:
            wx += self.SHA[i] * math.tanh((y - self.SHY[i]) / 5.0)
        return wx, self.GSY[i] * self.GY[k] + self.DD[i]


def _smoothstep(a: float) -> float:
    return a * a * (3.0 - 2.0 * a)


@lru_cache(maxsize=64)
def build_course(seed: int) -> Course:
    rng = np.random.default_rng([int(seed) & 0xFFFFFFFFFFFF, 0x524F544F52])
    xmax = N_LEGS * LEG_LEN
    n = int(xmax / DX) + 1
    xs = np.arange(n) * DX
    d = np.minimum(xs / LEG_LEN, 7.0)  # continuous difficulty
    mid = np.full(n, 60.0)
    for base, lam in ((12.0, 430.0), (5.0, 170.0), (2.0, 70.0)):
        lam = lam * rng.uniform(0.85, 1.15)
        mid += base * (1.0 + 0.45 * d) * np.sin(2 * np.pi * xs / lam + rng.uniform(0, 2 * np.pi))
    gap = np.maximum(GAP_MIN, GAP0 - GAP_SLOPE * d) + 4.0 * np.sin(2 * np.pi * xs / 260.0 + rng.uniform(0, 2 * np.pi))
    kn = np.arange(0, xmax + 20, 10.0)

    def rough():
        return np.abs(np.interp(xs, kn, rng.normal(0, 1, len(kn)))) * (0.8 + 0.3 * d)

    floor = mid - gap / 2 + rough()
    ceil = mid + gap / 2 - rough()
    # stalactites (2) and a rock (1) per leg, away from the survivor ledge and the bay
    for k in range(N_LEGS):
        X = k * LEG_LEN
        for which in ("c", "c", "f"):
            lo, hi = (X + 40, X + 170) if rng.random() < 0.5 else (X + 250, X + 345)
            if k == 0:
                lo, hi = X + 110, X + 170
            xc = rng.uniform(lo, hi)
            hgt = min(3.0 + 2.0 * k, 14.0) * rng.uniform(0.7, 1.0)
            tri = np.maximum(0.0, 1.0 - np.abs(xs - xc) / 8.0) * hgt
            if which == "c":
                ceil = ceil - tri
            else:
                floor = floor + tri
    surv, ships, shear, mean_w = [], [], [], []
    bay = np.zeros(n, dtype=np.int64)
    for k in range(N_LEGS):
        X = k * LEG_LEN
        xs_ = round(X + 215 + rng.uniform(-15, 15), 1)
        zone = np.abs(xs - xs_) <= 16
        ys = float(floor[zone].max())
        floor[zone] = ys
        surv.append((xs_, ys))
        bz = (xs >= X + 370) & (xs <= X + 500)
        yw = float(floor[bz].min()) - 10.0
        floor[bz] = yw
        bay[bz] = 1
        a1 = min(0.5 + 0.6 * k, 3.5)
        per = max(7.0 - 0.3 * k, 5.0) * rng.uniform(0.9, 1.1)
        ship = (round(X + 435 + rng.uniform(-8, 8), 1), yw + DECK_ABOVE_WATER,
                a1, 2 * math.pi / per, rng.uniform(0, 2 * math.pi),
                0.25 * a1, 2 * math.pi / (per * rng.uniform(0.45, 0.6)), rng.uniform(0, 2 * math.pi),
                0.15 * a1, 2 * math.pi / (per * rng.uniform(1.6, 2.2)), rng.uniform(0, 2 * math.pi))
        ships.append(tuple(float(v) for v in ship))
        need = ship[1] + 1.4 * a1 + 28.0  # headroom above the deck for rope work
        ceil[bz] = np.maximum(ceil[bz], need)
        xa = X + (90 if k == 0 else 60) + rng.uniform(0, 50)
        shear.append((float(xa), float(xa + 60), float((2.0 + 1.5 * k) * (1 if rng.random() < 0.5 else -1)),
                      float(-min(0.8 + 0.7 * k, 5.0))))
        mean_w.append(float(rng.uniform(-1, 1) * min(0.5 + 0.7 * k, 4.0)))
    ceil = np.maximum(ceil, floor + MIN_CLEAR)
    # wind fields per cell
    centres = np.arange(N_LEGS) * LEG_LEN + LEG_LEN / 2
    wmx = np.interp(xs, centres, np.array(mean_w))
    gsx = np.minimum(1.0 + 1.0 * d, 6.0)
    gsy = np.minimum(0.4 + 0.35 * d, 2.5)
    sha = np.zeros(n)
    shy = np.zeros(n)
    dd = np.zeros(n)
    for xa, xb, amp, down in shear:
        z = (xs >= xa) & (xs <= xb)
        taper = np.sin(np.pi * (xs[z] - xa) / (xb - xa))
        sha[z] = amp * taper
        shy[z] = mid[z]
        dd[z] = down * taper
    shipc = np.full(n, -1, dtype=np.int64)
    for j, sh in enumerate(ships):
        shipc[np.abs(xs - sh[0]) <= SHIP_HALF + 12.0] = j
    fh = np.array([floor[max(0, i - 2):i + 3].max() for i in range(n)])
    cl = np.array([ceil[max(0, i - 2):i + 3].min() for i in range(n)])
    # unit-variance OU gusts, tau = 2.5 s, generated at 30 Hz and linearly interpolated to 240 Hz
    n30 = MAX_ROUND_MS * 30 // 1000 + 120
    a = math.exp(-1.0 / (30 * 2.5))
    b = math.sqrt(1 - a * a)
    eps = rng.normal(0, 1, (n30, 2))
    ou = np.zeros((n30, 2))
    ou[0] = eps[0]
    for i in range(1, n30):
        ou[i] = a * ou[i - 1] + b * eps[i]
    t240 = np.arange(MAX_STEPS + 8 * HZ) / HZ
    t30 = np.arange(n30) / 30.0
    gx = np.interp(t240, t30, ou[:, 0])
    gy = np.interp(t240, t30, ou[:, 1])
    i0 = int(X_START / DX)
    y_start = float(floor[i0] + 0.45 * (ceil[i0] - floor[i0]))
    return Course(int(seed), n, float(xmax), floor.tolist(), ceil.tolist(), fh.tolist(), cl.tolist(),
                  bay.tolist(), wmx.tolist(), gsx.tolist(), gsy.tolist(), sha.tolist(), shy.tolist(),
                  dd.tolist(), shipc.tolist(), gx.tolist(), gy.tolist(), tuple(surv), tuple(ships),
                  tuple(shear), tuple(mean_w), y_start)


def course(seed: int) -> dict:
    """Static course geometry for the renderer (call once per round; frames only carry course id+seed)."""
    c = build_course(seed)
    return {"id": "rotorwash", "seed": c.seed, "dx": DX, "x0": 0.0, "floor": list(c.F), "ceiling": list(c.C),
            "bay": list(c.BAY), "x_start": X_START, "leg_len": LEG_LEN,
            "survivors": [list(s) for s in c.surv],
            "ships": [{"x": s[0], "deck_base": s[1], "half_width": SHIP_HALF, "hull_depth": HULL_DEPTH,
                       "heave_amp": s[2]} for s in c.ships],
            "shear_zones": [{"x0": s[0], "x1": s[1], "shear": s[2], "downdraft": s[3]} for s in c.shear],
            "mean_wind": list(c.mean_wind)}


# ------------------------------------------------------------------ physics helpers


def vrs_loss(vd: float, ve: float, vh: float) -> float:
    """Vortex-ring thrust loss fraction (0 outside vd > 0.6 v_h and ve < 0.3 v_h; max 0.4)."""
    a = (vd / vh - VRS_ON) / VRS_SPAN
    if a <= 0.0:
        return 0.0
    b = (VRS_H - ve / vh) / VRS_HSPAN
    if b <= 0.0:
        return 0.0
    return VRS_MAX * _smoothstep(min(a, 1.0)) * _smoothstep(min(b, 1.0))


def power_required(c: float, r: float) -> float:
    return K_P * (K_T * r * r * c) ** 1.5 + P_0 * r * r * r


def hover_collective(mass: float, ge: float = 1.0) -> float:
    return mass * G / (K_T * ge)


def new_heli(x: float, y: float, c: float = C0) -> dict:
    h = {"x": x, "y": y, "vx": 0.0, "vy": 0.0, "th": 0.0, "w": 0.0, "Om": OMEGA_N, "Pe": 0.0, "c": c, "u": 0.0,
         "fuel": M_FUEL0, "att": False, "L": 10.0, "Ld": 0.0, "phi": 0.0, "phid": 0.0,
         "alive": True, "cause": None, "t_crash": None, "landed": -1, "hover_t": 0.0, "stall_t": 0.0,
         "leg": 0, "surv_min": 0, "deliveries": 0, "max_x": x, "x0": x,
         "vrs_on": False, "droop_on": False, "gust_on": False,
         "loss": 0.0, "Preq": 0.0, "wx": 0.0, "wy": 0.0, "last": ("hold", "center", "hold")}
    h["Preq"] = h["Pe"] = power_required(c, 1.0)
    return h


@dataclass
class RWState:
    seed: int
    k: int  # substeps elapsed
    t_ms: int
    helis: list
    ended: bool = False
    extra: dict = field(default_factory=dict)


RULES = ("ROTORWASH: 2D side view, x forward, y up, SI units. You fly a rescue helicopter through a sea cave; "
         "one decision every 0.25 s, controls hold in between. Thrust ~ (RPM%)^2 x collective along the rotor axis; "
         "pitch tilts it (pitch + = nose down = pushes forward). Collective beyond engine power droops RPM "
         "(less thrust); RPM < 85% for 1 s = crash. Sinking faster than 0.6 hover-induced velocity with low "
         "airspeed = vortex ring (up to 40% thrust loss). Ground effect adds lift near surfaces. Gusts and "
         "shear zones. Crash: rotor/tail/body touching cave, water or ship hull, ceiling; touchdown faster "
         "than 2.5 m/s or pitch > 12 deg; fuel out; load swing > 50 deg. Task: hover over the survivor "
         "(speed < 1 m/s, rope end within 2 m above it) for 1.5 s to hook a 300 kg load, then land on the "
         "heaving ship deck to deliver. Next leg is harder. Score = metres flown + 500 per delivery.")


def _f(v: float, nd: int = 1) -> str:
    s = f"{v:+.{nd}f}"
    return "+0.0" if s in ("-0.0", "-0.00") else s


class Rotorwash:
    id = "rotorwash"
    n_players = 4
    decision_period_ms = DECISION_MS
    max_round_ms = MAX_ROUND_MS

    def __init__(self, wind: bool = True, drag: bool = True, fuel_burn: bool = True, hold_airframe: bool = False):
        """Flags exist for physics unit tests only; the arena always uses the defaults."""
        self.wind_on, self.drag_on, self.burn_on, self.hold = wind, drag, fuel_burn, hold_airframe

    course = staticmethod(course)

    # -------------------------------------------------------------- protocol
    def reset(self, seed: int) -> RWState:
        co = build_course(seed)
        helis = [new_heli(X_START, co.y_start) for _ in range(self.n_players)]
        s = RWState(seed=int(seed), k=0, t_ms=0, helis=helis)
        for h in helis:
            self._refresh(h, co, 0)
        return s

    def queries(self, s: RWState, player: int, answers: dict[str, str]) -> list[Query]:
        h = s.helis[player]
        if not h["alive"] or s.ended or answers:
            return []
        obs = self.observation(s, player)
        return [
            Query(player, "collective", obs + "\nChoose COLLECTIVE change: down2=-0.10, down1=-0.05, hold, "
                  "up1=+0.05, up2=+0.10.", COLL_OPTS, "hold"),
            Query(player, "cyclic", obs + "\nChoose CYCLIC (held until next decision): aft2=-0.6, aft1=-0.3, "
                  "center=0, fwd1=+0.3, fwd2=+0.6 (fwd = nose down).", CYC_OPTS, "center"),
            Query(player, "winch", obs + "\nChoose WINCH: up=shorten 2 m/s, hold, down=lengthen 2 m/s "
                  "(rope 5-25 m).", WINCH_OPTS, "hold"),
        ]

    def step(self, s: RWState, actions: dict[int, dict[str, str]], dt_ms: int) -> tuple[RWState, list[Event]]:
        co = build_course(s.seed)
        helis = [dict(h) for h in s.helis]
        nsub = int(round(dt_ms * HZ / 1000))
        events: list[Event] = []
        if not s.ended:
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
                    h["c"] = min(1.0, max(0.0, round(h["c"] + C_STEP * COLL[ca], 4)))
                h["u"] = CYCLIC[cy]
                h["Ld"] = WINCH[wi]
                h["last"] = (ca, cy, wi)
                self._integrate(h, co, s.k, nsub, events, p)
        s2 = RWState(seed=s.seed, k=s.k + nsub, t_ms=s.t_ms + dt_ms, helis=helis, ended=s.ended)
        if not s2.ended and (not any(h["alive"] for h in helis) or s2.t_ms >= self.max_round_ms):
            s2.ended = True
            events.append(Event(s2.t_ms, "round_end", None, {"scores": [self.score(h) for h in helis]}))
        events.sort(key=lambda e: e.t_ms)
        return s2, events

    def done(self, s: RWState) -> bool:
        return s.ended or s.t_ms >= self.max_round_ms or not any(h["alive"] for h in s.helis)

    @staticmethod
    def score(h: dict) -> float:
        return round(max(0.0, h["max_x"] - h["x0"]) + 500.0 * h["deliveries"], 3)

    def ranking(self, s: RWState) -> list[list[int]]:
        sc = [self.score(h) for h in s.helis]
        out: list[list[int]] = []
        for v in sorted(set(sc), reverse=True):
            out.append([p for p in range(self.n_players) if sc[p] == v])
        return out

    def state_hash(self, s: RWState) -> str:
        parts = [repr((s.seed, s.k, s.t_ms, s.ended))]
        for h in s.helis:
            parts.append(repr(sorted(h.items())))
        return hashlib.sha256("|".join(parts).encode()).hexdigest()

    def render_state(self, s: RWState) -> dict:
        co = build_course(s.seed)
        t = s.k * DT
        hs = []
        for h in s.helis:
            if h["att"]:
                lx, ly = h["x"] + h["L"] * math.sin(h["phi"]), h["y"] - h["L"] * math.cos(h["phi"])
            else:
                lx, ly = h["x"], h["y"] - h["L"]
            hs.append({"x": round(h["x"], 3), "y": round(h["y"], 3), "pitch_deg": round(math.degrees(h["th"]), 2),
                       "rpm_pct": round(100 * h["Om"] / OMEGA_N, 2), "collective": round(h["c"], 3),
                       "cyclic": h["u"], "rope_len": round(h["L"], 3), "hook": [round(lx, 3), round(ly, 3)],
                       "load_attached": h["att"], "alive": h["alive"], "crash_cause": h["cause"],
                       "landed_on_ship": h["landed"], "score": self.score(h), "leg": h["leg"],
                       "deliveries": h["deliveries"], "fuel_pct": round(100 * h["fuel"] / M_FUEL0, 1),
                       "vrs_loss": round(h["loss"], 3), "last_action": list(h["last"])})
        alive_x = [h["x"] for h in s.helis if h["alive"]] or [h["x"] for h in s.helis]
        cam_x = max(alive_x)
        ships = []
        for j in range(N_LEGS):
            y, vy, _ = co.deck(j, t)
            ships.append({"x": co.ships[j][0], "deck_y": round(y, 3), "deck_vy": round(vy, 3)})
        ks = min(s.k, len(co.GX) - 1)
        samples = []
        for dxs in (-40.0, 0.0, 40.0, 80.0):
            xx = min(max(cam_x + dxs, 0.0), co.xmax - 1)
            for fr in (0.25, 0.5, 0.75):
                yy = co.floor_at(xx) + fr * (co.ceil_at(xx) - co.floor_at(xx))
                wx, wy = co.wind(xx, yy, ks) if self.wind_on else (0.0, 0.0)
                samples.append([round(xx, 1), round(yy, 1), round(wx, 2), round(wy, 2)])
        return {"t_ms": s.t_ms, "course": {"id": self.id, "seed": s.seed}, "camera_x": round(cam_x, 2),
                "helis": hs, "ships": ships, "wind_samples": samples,
                "gust_unit": [round(co.GX[ks], 3), round(co.GY[ks], 3)], "ended": s.ended}

    # -------------------------------------------------------------- observation
    def observe(self, s: RWState, p: int) -> dict:
        """Everything in the observation text, as numbers (used by scripted test controllers)."""
        co = build_course(s.seed)
        h = s.helis[p]
        t = s.k * DT
        x, y = h["x"], h["y"]
        surf = co.floor_at(x)
        j = h["leg"]
        sx = co.ships[j][0]
        dy_, dvy, _ = co.deck(j, t)
        if abs(x - sx) <= SHIP_HALF:
            surf = max(surf, dy_)
        if h["att"]:
            tx, ty, tname = sx, dy_, "ship deck"
        else:
            tx, ty, tname = co.surv[j][0], co.surv[j][1], "survivor"
        r = h["Om"] / OMEGA_N
        return {"t": t, "leg": j + 1, "hooked": h["att"], "landed": h["landed"] >= 0,
                "agl": y - SKID_H - surf, "vx": h["vx"], "vy": h["vy"], "pitch": math.degrees(h["th"]),
                "pitch_rate": math.degrees(h["w"]), "rpm": 100 * r, "collective": 100 * h["c"], "cyclic": h["u"],
                "power_margin": 100 * (P_AVAIL - h["Preq"]) / P_AVAIL, "wind": (h["wx"], h["wy"]),
                "rays": self.rays(co, x, y, t), "target": tname, "target_dx": tx - x, "target_dy": ty - y,
                "pad_vy": dvy, "rope": h["L"], "load_angle": math.degrees(h["phi"]) if h["att"] else 0.0,
                "load_rate": math.degrees(h["phid"]) if h["att"] else 0.0, "fuel": 100 * h["fuel"] / M_FUEL0,
                "hook_timer": h["hover_t"], "deliveries": h["deliveries"], "score": self.score(h)}

    def observation(self, s: RWState, p: int) -> str:
        o = self.observe(s, p)
        rays = ", ".join(f"{n} {d:.1f}" for n, d in zip(RAY_NAMES, o["rays"]))
        lines = [
            RULES,
            f"STATE t={o['t']:.2f}s leg {o['leg']} deliveries {o['deliveries']} score {o['score']:.0f} "
            f"load {'HOOKED' if o['hooked'] else 'none'}{' LANDED' if o['landed'] else ''} fuel {o['fuel']:.0f}%",
            f"altitude AGL {o['agl']:.1f} m; vx {_f(o['vx'])} m/s; vy {_f(o['vy'])} m/s; pitch {_f(o['pitch'])} deg; "
            f"pitch rate {_f(o['pitch_rate'])} deg/s",
            f"rotor RPM {o['rpm']:.1f}%; collective {o['collective']:.0f}%; cyclic {_f(o['cyclic'])}; "
            f"power margin {_f(o['power_margin'], 0)}%; wind {_f(o['wind'][0])},{_f(o['wind'][1])} m/s (x,y)",
            f"terrain rays from heli, m (max {RAY_MAX:.0f}): {rays}",
            f"target {o['target']}: dx {_f(o['target_dx'])} m, dy {_f(o['target_dy'])} m; "
            f"ship deck vertical speed {_f(o['pad_vy'])} m/s; hover-hook timer {o['hook_timer']:.1f}/1.5 s",
            f"rope {o['rope']:.1f} m; load angle {_f(o['load_angle'])} deg, rate {_f(o['load_rate'])} deg/s",
        ]
        return "\n".join(lines)

    @staticmethod
    def rays(co: Course, x: float, y: float, t: float) -> list[float]:
        out = []
        for ang in RAY_ANGLES:
            a = math.radians(ang)
            out.append(_cast(co, x, y, math.cos(a), math.sin(a), t))
        return out

    # -------------------------------------------------------------- physics core
    def _refresh(self, h: dict, co: Course, k: int) -> None:
        """Recompute derived display quantities (wind, power) at the current state."""
        if self.wind_on:
            h["wx"], h["wy"] = co.wind(h["x"], h["y"], k)
        h["Preq"] = power_required(h["c"], h["Om"] / OMEGA_N)

    def _integrate(self, h: dict, co: Course, k0: int, nsub: int, events: list, p: int) -> None:
        F, C, FH, CL, BAY = co.F, co.C, co.FH, co.CL, co.BAY
        WMX, GSX, GSY, SHA, SHY, DD, SHIPC, GX, GY = co.WMX, co.GSX, co.GSY, co.SHA, co.SHY, co.DD, co.SHIPC, co.GX, co.GY
        nG = len(GX) - 1
        wind_on, hold = self.wind_on, self.hold
        kdx, kdy, kdl = (KDX, KDY, KDL) if self.drag_on else (0.0, 0.0, 0.0)
        sfc = SFC if self.burn_on else 0.0
        x, y, vx, vy, th, w, Om, Pe = h["x"], h["y"], h["vx"], h["vy"], h["th"], h["w"], h["Om"], h["Pe"]
        c, u, fuel, att, L, Ldr = h["c"], h["u"], h["fuel"], h["att"], h["L"], h["Ld"]
        phi, phid, landed, hover_t, stall_t = h["phi"], h["phid"], h["landed"], h["hover_t"], h["stall_t"]
        leg, max_x = h["leg"], h["max_x"]
        vrs_on, droop_on, gust_on = h["vrs_on"], h["droop_on"], h["gust_on"]
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
            # wind
            if wind_on:
                kg = kk - 1 if kk - 1 < nG else nG
                gxs = GSX[i] * GX[kg]
                gys = GSY[i] * GY[kg]
                wx = WMX[i] + gxs
                if SHA[i]:
                    wx += SHA[i] * tanh((y - SHY[i]) * 0.2)
                wy = gys + DD[i]
                gmag = sqrt(gxs * gxs + gys * gys)
                if not gust_on and gmag > 4.0:
                    gust_on = True
                    events.append(Event(round(kk * 1000 / HZ), "gust", p, {"speed": round(gmag, 2)}))
                elif gust_on and gmag < 3.0:
                    gust_on = False
            st, ct = sin(th), cos(th)
            vrx, vry = vx - wx, vy - wy
            # surface under the hub (floor/water or ship deck)
            fr = x * 0.2 - i
            surf = F[i] + (F[i + 1] - F[i]) * fr
            sj = SHIPC[i]
            if sj >= 0:
                dky, dkv, dka = co.deck(sj, t)
                if abs(x - ships[sj][0]) <= SHIP_HALF and dky > surf:
                    surf = dky
            hh = y + HUB_H * ct - surf
            ge = 1.0 + GE_GAIN * exp(-hh / R_ROTOR) if hh > 0 else 1.0 + GE_GAIN
            # vortex ring
            vd = -(vrx * st + vry * ct)
            vh = sqrt(m_tot * G / (2.0 * RHO * A_DISC))
            loss = 0.0
            if vd > VRS_ON * vh:
                ve = abs(vrx * ct - vry * st)
                loss = vrs_loss(vd, ve, vh)
            if not vrs_on and loss > 0.05:
                vrs_on = True
                events.append(Event(round(kk * 1000 / HZ), "vortex_ring", p, {"loss": round(loss, 3)}))
            elif vrs_on and loss < 0.01:
                vrs_on = False
            # rotor and engine
            r = Om / OMEGA_N
            Tb = K_T * r * r * c
            T = Tb * (1.0 - loss) * ge
            Preq = K_P * Tb ** 1.5 + P_0 * r * r * r
            Pcmd = Preq + K_G * (1.0 - r) * P_AVAIL
            Pcmd = 0.0 if Pcmd < 0.0 else (P_AVAIL if Pcmd > P_AVAIL else Pcmd)
            Pe += (Pcmd - Pe) * (DT / TAU_E)
            Om += (Pe - Preq) / (I_ROTOR * Om) * DT
            if Om < 1.0:
                Om = 1.0
            fuel -= sfc * Pe * DT
            # winch
            Ld = Ldr
            L += Ld * DT
            if L < L_MIN:
                L, Ld = L_MIN, 0.0
            elif L > L_MAX:
                L, Ld = L_MAX, 0.0
            if landed >= 0:
                dky, dkv, dka = co.deck(landed, t)
                if T > m_tot * (G + dka):  # lift-off
                    landed = -1
                    vy = dkv
                else:
                    y = dky + SKID_H
                    vy = dkv
                    vx = 0.0
                    th = w = 0.0
            if landed < 0:
                # airframe non-rope forces (incl. gravity) as accelerations
                sp_air = sqrt(vrx * vrx + vry * vry)
                ahx = (T * st - kdx * sp_air * vrx) / m_h
                ahy = (T * ct - kdy * sp_air * vry) / m_h - G
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
                    phidd = (-G * sp_ + (fdx * cp_ + fdy * sp_) / M_LOAD - (ahx * cp_ + ahy * sp_)
                             - 2.0 * Ld * phid) / L
                    Tr = mu * (G * cp_ + L * phid * phid + (fdx * sp_ - fdy * cp_) / M_LOAD - (ahx * sp_ - ahy * cp_))
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
            # ---- collisions
            if cause is None and landed < 0 and not hold:
                if x < 8.0 or x > xlim:
                    cause = "terrain"
                else:
                    i = int(x * 0.2)
                    near_ship = SHIPC[i] >= 0
                    if near_ship or FH[i] > y - EXTENT or CL[i] < y + EXTENT:
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
                            ce = C[ii] + (C[ii + 1] - C[ii]) * fr
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
            # ---- task progress
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
                 droop_on=droop_on, gust_on=gust_on, loss=loss, Preq=Preq, wx=wx, wy=wy)
        if cause is not None:
            h["alive"] = False
            h["cause"] = cause
            h["t_crash"] = round(kk * 1000 / HZ)
            events.append(Event(h["t_crash"], "crash", p, {"cause": cause, "x": round(x, 2), "y": round(y, 2)}))
        elif not wind_on:
            h["wx"] = h["wy"] = 0.0


def _cast(co: Course, x: float, y: float, dx: float, dy: float, t: float) -> float:
    """Distance along the unit ray (dx, dy) to the floor/ceiling polylines or a ship hull, capped."""
    best = RAY_MAX
    # ship hulls (axis-aligned boxes: deck top .. water - HULL_DEPTH)
    for j, sh in enumerate(co.ships):
        sx = sh[0]
        if abs(sx - x) > RAY_MAX + SHIP_HALF:
            continue
        top = co.deck(j, t)[0]
        bot = sh[1] - DECK_ABOVE_WATER - HULL_DEPTH
        tmin, tmax = 0.0, best
        ok = True
        for o, d, lo, hi in ((x, dx, sx - SHIP_HALF, sx + SHIP_HALF), (y, dy, bot, top)):
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
    if abs(dx) < 1e-9:  # vertical ray
        if dy > 0:
            return round(min(best, max(0.0, co.ceil_at(x) - y)), 3)
        return round(min(best, max(0.0, y - co.floor_at(x))), 3)
    # walk the 5 m segments the ray crosses; terrain and ray are both linear inside a segment
    x_end = x + dx * best
    i = int(x / DX)
    s_prev = 0.0
    while True:
        xa, xb = i * DX, (i + 1) * DX
        sa = max(s_prev, (xa - x) / dx) if dx > 0 else max(s_prev, (xb - x) / dx)
        sb = (xb - x) / dx if dx > 0 else (xa - x) / dx
        sb = min(sb, best)
        if sa > sb or i < 0 or i >= co.n - 1:
            break
        for arr, sign in ((co.F, 1.0), (co.C, -1.0)):
            def gap(sv):
                px = x + dx * sv
                ty = arr[i] + (arr[i + 1] - arr[i]) * (px / DX - i)
                return sign * ((y + dy * sv) - ty)
            ga, gb = gap(sa), gap(sb)
            if ga <= 0.0:
                best = min(best, sa)
            elif gb <= 0.0:
                best = min(best, sa + (sb - sa) * ga / (ga - gb))
        if (dx > 0 and x_end <= xb) or (dx < 0 and x_end >= xa) or sb >= best:
            break
        s_prev = sb
        i += 1 if dx > 0 else -1
    return round(max(0.0, best), 3)
