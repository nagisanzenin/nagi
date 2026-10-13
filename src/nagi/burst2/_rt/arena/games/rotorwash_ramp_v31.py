"""ROTORWASH-RAMP v3.1: Rotorwash-Ramp without the chasing collapse front, scored by the task (no time term).

Why (owner 2026-09-28): in v3 (rules ramp1.0, `arena.games.rotorwash_ramp`, unchanged by this module) the collapse
front that chases the helicopters catches every player before it reaches a ship, so viewers never see a landing.
v3.1 removes the front. Removing it also removes what ended rounds and what ranked players (later crash wins), so the
score changes too: a survival-time score would now reward hovering in place (the Booster stall lesson,
docs/research_insights/BOOSTER_STALL_20260927.md). Two rules versions (docs/arena_v31/ROTORWASH_RAMP_V31.md):

ramp2.1 (current, K3-RR2.1; reviewer round 2026-09-30): 60 s cap (240 ticks, the v3 slot time), the v3 roof / storm /
    power anchors (rotorwash_ramp.BASE, 0..60 s), and approach credit so a player that makes progress but does not
    touch a deck is not scored as a player that never left the start:
        Y = S + D + q
        S = distinct ships landed on (valid touchdown: skids on the deck, sink vs the heaving deck < 2.5 m/s,
            |pitch| < 12 deg; each ship counts once);  D = deliveries (valid landing with the survivor hooked);
        q = T if the run ENDS by a failing touchdown ('hard_landing' / 'landing_attitude') on a deck not landed on,
            T = 0.6 + 0.3 * clip(2 - E, 0, 1) in [0.6, 0.9], E = max(sink_rel / 2.5 m/s, |pitch| / 12 deg) >= 1;
            otherwise q = A = 0.05 * c, c = checkpoints toward the NEXT ship n (1 + the highest ship landed on, 0
            before any landing): c = floor(10 * (max_x - a_n) / (b_n - a_n)) clipped to [0, 10], a_n = the start x
            (n = 0) or ship n-1's x, b_n = the x where ship n's flooded bay begins (A = 0.5 at the bay).
    So: a helicopter that never passes the first checkpoint (33 m) scores 0 however long it flies; any failing
    touchdown on the next deck (>= 0.6) beats every approach (<= 0.5); a valid landing (>= 1) beats every attempt
    (<= 0.9); Y never decreases during a run and has no time term.
ramp2.0 (superseded, replayable; K3-RR): 90 s cap, a gentler 10-anchor ramp, Y = S + D + P with the Booster partial
    P = 0.5 * clip(2 - E, 0, 1) on a failing touchdown on a new deck and no approach credit.

Common to both: the ROOF comes down (over rock to floor + 12 m, over bays to 12 m above the highest deck point, so
every deck stays landable), the STORM gain multiplies gusts, shear and downdrafts, ENGINE power fades; all indexed by
the global tick only. A helicopter's run ends at a crash; the round ends when every helicopter has crashed or at the
cap. Landing does not end a run: a landed helicopter may lift off and fly on to the next ship.
Pairwise rule (Arena decision metric): on the same seed, higher Y wins, equal Y ties (1/2).

Determinism: new step code is integer (anchors, floor interpolation) or single IEEE operations on exactly representable
operands (mm / 1000, q / 1024), plus the checkpoint floor (ramp2.1); the physics is the Rotorwash float64 physics
(copied from `RotorwashRamp._integrate_ramp` with the front removed and touchdown bookkeeping added), so replay is exact
on the recording platform only (handbook R3.13; `float_engine=True`; reference Linux x86_64, prereg R3.23). ramp2.0
state hashes are unchanged by the ramp2.1 addition (tests pin the 1,000-step hash).
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from functools import lru_cache

from nagi.burst2._rt.arena.core import Event, Query
from nagi.burst2._rt.arena.games import rotorwash as rw
from nagi.burst2._rt.arena.games import rotorwash_ramp as RR
from nagi.burst2._rt.arena.games.rotorwash import (COLL, COLL_OPTS, CYC_OPTS, CYCLIC, DT, EXTENT, HUB_H, HZ, LEG_LEN, POINTS,
                                   RAY_MAX, RAY_NAMES, SKID_H, WINCH, WINCH_OPTS, X_START, Rotorwash, RWState, _f,
                                   build_course)

RULES_VERSION = "ramp2.1"                   # the current v3.1 rules (ramp2.0 stays replayable: RULESETS)
RULES_VERSIONS = ("ramp2.0", "ramp2.1")
GAME_ID = "rotorwash_ramp_v31"
SCORING = "K3-RR2.1"
TICK_MS = 250
SUB = HZ * TICK_MS // 1000                  # 60 physics substeps per tick
TICKS_PER_LEVEL = 40                        # 10 s ramp phases / display levels
MAX_ROUND_MS = 60000                        # ramp2.1: 60 s cap (v3 slot time); ramp2.0 had 90 s
N_TICKS = MAX_ROUND_MS // TICK_MS           # 240
N_LEVELS = N_TICKS // TICKS_PER_LEVEL       # 6
N_ANCHORS = N_LEVELS + 1                    # anchors at t = 0, 10, ..., 60 s
TD_CAUSES = ("hard_landing", "landing_attitude")
N_CHECK = 10                                # ramp2.1 checkpoints toward the next ship (0.05 each, max 0.5)
BAY_OFFSET = 370.0                          # rotorwash.build_course: leg k's flooded bay starts at k * LEG_LEN + 370 m


@dataclass(frozen=True)
class Schedule:
    """Anchor values at t = 10 j seconds, integers; per-tick values interpolate linearly (floor); constant after the
    last anchor. Roof drop in mm, storm gain and engine power in 1/1024. No front (v3.1). The defaults are ramp2.0's
    10 anchors (0..90 s); ramp2.1 uses the v3 anchors (7, 0..60 s): BASE21."""
    roof_mm: tuple = (0, 2000, 5000, 10000, 16000, 23000, 30000, 37000, 44000, 50000)
    gust_q: tuple = (1024, 1200, 1450, 1750, 2100, 2500, 2950, 3450, 4000, 4600)
    power_q: tuple = (1024, 1010, 995, 980, 965, 950, 935, 920, 905, 890)
    roof_gap_mm: int = 12000        # minimum roof height above the floor (cave cells), as v3
    bay_gap_mm: int = 12000         # minimum roof height above the ship deck's highest point (bay cells), as v3

    def __post_init__(self):
        n = len(self.roof_mm)
        for a in (self.roof_mm, self.gust_q, self.power_q):
            assert len(a) == n >= 2 and all(isinstance(v, int) for v in a), a

    @property
    def n_levels(self) -> int:
        return len(self.roof_mm) - 1

    @property
    def n_ticks(self) -> int:
        return self.n_levels * TICKS_PER_LEVEL


BASE20 = Schedule()                                           # ramp2.0 (gentle, 0..90 s)
BASE21 = Schedule(roof_mm=tuple(RR.BASE.roof_mm), gust_q=tuple(RR.BASE.gust_q), power_q=tuple(RR.BASE.power_q),
                  roof_gap_mm=RR.BASE.roof_gap_mm, bay_gap_mm=RR.BASE.bay_gap_mm)   # ramp2.1 = the v3 anchors
BASE = BASE21


def lerp_anchor(anchors: tuple, k: int) -> int:
    """Integer value at tick k: linear between anchors 40 ticks apart, floor division; constant after the last."""
    if k >= (len(anchors) - 1) * TICKS_PER_LEVEL:
        return anchors[-1]
    j, r = divmod(max(0, k), TICKS_PER_LEVEL)
    a, b = anchors[j], anchors[j + 1]
    return a + ((b - a) * r) // TICKS_PER_LEVEL


def level_of(k: int, n_levels: int = N_LEVELS) -> int:
    """Ramp phase (display level) of tick k: 1 + floor(t / 10 s), capped at n_levels."""
    return min(n_levels, 1 + max(0, k) // TICKS_PER_LEVEL)


@dataclass(frozen=True)
class Ramp:
    k: int
    level: int
    roof_mm: int
    gust_q: int
    power_q: int


@lru_cache(maxsize=64)
def ramp_at(sched: Schedule, k: int) -> Ramp:
    return Ramp(k, level_of(k, sched.n_levels), lerp_anchor(sched.roof_mm, k), lerp_anchor(sched.gust_q, k),
                lerp_anchor(sched.power_q, k))


def ramp_course(seed: int, sched: Schedule, k: int) -> RR.RampCourse:
    """Course view with the lowered roof at tick k (rays, observation, bots, renderer)."""
    return RR.RampCourse(build_course(seed), RR.gap_min(seed, sched), ramp_at(sched, k).roof_mm / 1000)


_RULES_COMMON = (
    "x forward, y up. Fly a helicopter through a sea cave and LAND ON SHIP DECKS; "
    "a decision every 0.25 s, controls hold between. Thrust ~ RPM%^2 x collective along the rotor axis; pitch + "
    "= nose down = pushes forward. Collective beyond engine power droops RPM; RPM < 85% for 1 s = crash. Fast sinking "
    "at low airspeed = vortex ring (up to -40% thrust). Crash: touching cave, roof, water or hull; fuel out; load swing "
    "> 50 deg. Landing: skids on a deck, sink vs the heaving deck < 2.5 m/s, pitch < 12 deg. Rescue: hover within 4 m "
    "of the survivor, speed < 1 m/s, rope end (winch 5-25 m) <= 2 m above it for 1.5 s; land with it to deliver. ")
RULES20 = (
    "ROTORWASH RAMP (rules ramp2.0): " + _RULES_COMMON +
    "POINTS: +1 per ship first landed on, +1 per delivery, up to +0.5 for a crash on a new deck within 2x those limits; "
    "none for time. Roof lowers, gusts grow, power fades every tick; 90 s.")
# ramp2.1: the same physics / crash / landing text, a shorter decision and rescue sentence and the new POINTS sentence
# (chord prompt budget: ramp2.0's worst was 890 of 900 tokens; ramp2.1 must not exceed it)
RULES21 = (
    "ROTORWASH RAMP (rules ramp2.1): x forward, y up. Fly a helicopter through a sea cave and LAND ON SHIP DECKS; "
    "decide every 0.25 s, controls hold. Thrust ~ RPM%^2 x collective along the rotor axis; pitch + "
    "= nose down = pushes forward. Collective beyond engine power droops RPM; RPM < 85% for 1 s = crash. Fast sinking "
    "at low airspeed = vortex ring (up to -40% thrust). Crash: touching cave, roof, water or hull; fuel out; load swing "
    "> 50 deg. Landing: skids on a deck, sink vs the heaving deck < 2.5 m/s, pitch < 12 deg. Rescue: 1.5 s within 4 m "
    "of the survivor at < 1 m/s, rope end (winch 5-25 m) <= 2 m above it; land with it to deliver. "
    "POINTS: +1 per new ship landed, +1 per delivery; else up to 0.5 for checkpoints toward the next ship, 0.6-0.9 "
    "for crashing on its deck; none for time. Roof, gusts and power worsen; 60 s.")
RULES = RULES21


@dataclass(frozen=True)
class RuleSet:
    version: str
    cap_ms: int
    schedule: Schedule
    text: str
    scoring: str
    checkpoints: bool            # ramp2.1: approach checkpoints + touchdown credit T; ramp2.0: Booster partial P


RULESETS = {"ramp2.0": RuleSet("ramp2.0", 90000, BASE20, RULES20, "K3-RR", False),
            "ramp2.1": RuleSet("ramp2.1", 60000, BASE21, RULES21, "K3-RR2.1", True)}
assert RULESETS[RULES_VERSION].cap_ms == MAX_ROUND_MS and BASE21.n_ticks == N_TICKS


# ------------------------------------------------------------------ round score (pure functions of a heli dict)

PARTIAL_E_MAX = 2.0    # no extra credit from E >= 2 (twice a limit), as the Booster K3 score; see ROTORWASH_RAMP_V31.md §3
TD_BASE, TD_SPAN = 0.6, 0.3   # ramp2.1 touchdown credit T = 0.6 + 0.3 * clip(2 - E, 0, 1), strictly above A <= 0.5


def _clip01(E: float) -> float:
    return min(1.0, max(0.0, (PARTIAL_E_MAX - E) / (PARTIAL_E_MAX - 1.0)))


def partial_credit(E: float | None) -> float:
    """ramp2.0: 0.5 * clip((E_MAX - E) / (E_MAX - 1), 0, 1) = 0.5 * clip(2 - E, 0, 1) (the Booster K3 formula): 0.5 at
    E <= 1 (reachable only at the limit itself, since E < 1 is a legal landing), falling linearly to 0 at E = 2; no
    touchdown (None / inf) -> 0."""
    if E is None or not math.isfinite(E):
        return 0.0
    return 0.5 * _clip01(E)


def touchdown_credit(E: float | None) -> float:
    """ramp2.1: T = 0.6 + 0.3 * clip(2 - E, 0, 1) in [0.6, 0.9] for a run-ending failing touchdown on a deck not
    landed on (E >= 1); 0 with no such touchdown."""
    if E is None or not math.isfinite(E):
        return 0.0
    return TD_BASE + TD_SPAN * _clip01(E)


def target_ship(ships_landed) -> int:
    """ramp2.1: the ship scored toward next: 1 + the highest ship index landed on (ships are ordered along x), 0
    before any landing; capped at the last ship."""
    return min(max(ships_landed) + 1, rw.N_LEGS - 1) if ships_landed else 0


def checkpoint_span(co, n: int) -> tuple[float, float]:
    """(a_n, b_n): the approach segment toward ship n: from the start x (n = 0) or ship n-1's x to the start of ship
    n's flooded bay. Checkpoint i (1..10) is the gate at x = a_n + i (b_n - a_n) / 10."""
    return (X_START if n == 0 else co.ships[n - 1][0]), n * LEG_LEN + BAY_OFFSET


def checkpoint(co, max_x: float, ships_landed) -> int:
    """ramp2.1: checkpoints passed toward the next ship n: floor(10 (max_x - a_n) / (b_n - a_n)) clipped to [0, 10]."""
    n = target_ship(ships_landed)
    if n in ships_landed:                 # every ship landed on (unreachable in 60 s): full approach credit
        return N_CHECK
    a, b = checkpoint_span(co, n)
    c = math.floor((max_x - a) * N_CHECK / (b - a))
    return 0 if c < 0 else (N_CHECK if c > N_CHECK else c)


def k3_parts(h: dict, version: str | None = None) -> dict:
    """Y of one helicopter from its engine dict or its render dict (both carry the same keys). `version` None: ramp2.1
    if the dict carries the checkpoint count 'ckpt' (only ramp2.1 engines write it), else ramp2.0."""
    if version is None:
        version = "ramp2.1" if "ckpt" in h else "ramp2.0"
    S = len(h["ships_landed"])
    D = int(h["deliveries"])
    E = h.get("td_E") if h.get("cause", h.get("crash_cause")) in TD_CAUSES else None
    P = partial_credit(E)
    if not RULESETS[version].checkpoints:
        return {"k3": S + D + P, "ships": S, "deliveries": D, "partial": P, "E": E, "version": version}
    c = int(h.get("ckpt", 0))
    A = c / 20
    T = touchdown_credit(E)
    q = T if T > A else A
    return {"k3": S + D + q, "ships": S, "deliveries": D, "q": q, "checkpoints": c, "approach": A, "touchdown": T,
            "partial": q, "E": E, "k3_pure": S + D + P, "version": version}


def k3_value(h: dict, version: str | None = None) -> float:
    return k3_parts(h, version)["k3"]


def win(a: float, b: float) -> float:
    """Pairwise rule on the same seed: higher Y wins (1), equal ties (1/2)."""
    return 1.0 if a > b else 0.5 if a == b else 0.0


# ------------------------------------------------------------------ engine

class RotorwashRampV31(Rotorwash):
    """Rotorwash engine with the v3.1 ramp (roof, storm, engine fade; no front) and the round-score bookkeeping of its
    rules version (RULESETS). Module constants are read from arena.games.rotorwash at call time (so RampGame31's
    constant patches apply, like v3)."""
    id = GAME_ID

    def __init__(self, schedule: Schedule | None = None, rules_text: str | None = None, n_players: int = 4,
                 rules_version: str = RULES_VERSION):
        super().__init__()
        self.rs = RULESETS[rules_version]
        self.version = rules_version
        self.sched = schedule if schedule is not None else self.rs.schedule
        self.rules_text = rules_text if rules_text is not None else self.rs.text
        self.n_players = n_players
        self.max_round_ms = self.rs.cap_ms
        self.n_ticks = self.rs.cap_ms // TICK_MS
        self.n_levels = self.n_ticks // TICKS_PER_LEVEL

    # -------------------------------------------------------------- protocol
    def reset(self, seed: int) -> RWState:
        s = super().reset(seed)
        for h in s.helis:
            h.update(ships_landed=(), td_E=None, td_ship=None, t_first_land=None, t_last_point=None)
            if self.rs.checkpoints:
                h["ckpt"] = 0
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
                self._integrate31(h, co, s.k, nsub, events, p, rp)
        s2 = RWState(seed=s.seed, k=s.k + nsub, t_ms=s.t_ms + dt_ms, helis=helis, ended=s.ended)
        if not s2.ended:
            k2 = s2.t_ms // TICK_MS
            nl = self.n_levels
            if k2 < self.n_ticks and k2 % TICKS_PER_LEVEL == 0 and level_of(k2, nl) != level_of(k_tick, nl):
                events.append(Event(s2.t_ms, "level_up", None, {"level": level_of(k2, nl)}))
            if not any(h["alive"] for h in helis) or s2.t_ms >= self.max_round_ms:
                s2.ended = True
                events.append(Event(s2.t_ms, "round_end", None,
                                    {"scores": [k3_value(h, self.version) for h in helis]}))
        events.sort(key=lambda e: e.t_ms)
        return s2, events

    def score(self, h: dict) -> float:
        """The round score Y of this rules version; the v2 'metres + 500 per delivery' is game_metres()."""
        return k3_value(h, self.version)

    @staticmethod
    def game_metres(h: dict) -> float:
        return Rotorwash.score(h)

    def ranking(self, s: RWState) -> list[list[int]]:
        """Higher Y first; equal Y tie (no time or distance tiebreak)."""
        ys = [k3_value(h, self.version) for h in s.helis]
        return [[p for p in range(self.n_players) if ys[p] == v] for v in sorted(set(ys), reverse=True)]

    def state_hash(self, s: RWState) -> str:
        parts = [repr((self.version, self.sched, s.seed, s.k, s.t_ms, s.ended))]
        for h in s.helis:
            parts.append(repr(sorted(h.items())))
        return hashlib.sha256("|".join(parts).encode()).hexdigest()

    # -------------------------------------------------------------- views
    def next_ship(self, h: dict) -> int:
        """Index of the ship the helicopter should land on next. ramp2.1: target_ship (1 + the highest ship landed on,
        the ship the score counts toward). ramp2.0: the active leg's ship, or the first later ship it has not landed on
        yet (capped at the last ship)."""
        if self.rs.checkpoints:
            return target_ship(h["ships_landed"])
        j = h["leg"]
        last = rw.N_LEGS - 1
        while j < last and j in h["ships_landed"]:
            j += 1
        return j

    def ramp_state(self, s: RWState) -> dict:
        k = s.t_ms // TICK_MS
        rp = ramp_at(self.sched, k)
        return {"k": k, "level": rp.level, "t_s": round(s.t_ms / 1000, 2), "roof_drop": rp.roof_mm / 1000,
                "gust_gain": rp.gust_q / 1024, "power_pct": round(100 * rp.power_q / 1024, 1),
                "n_levels": self.n_levels, "cap_s": self.max_round_ms / 1000,
                "next_level_s": round((TICKS_PER_LEVEL - k % TICKS_PER_LEVEL) * TICK_MS / 1000, 2)
                if k < self.n_ticks else None}

    def render_state(self, s: RWState) -> dict:
        out = super().render_state(s)
        out["course"]["id"] = self.id
        out["ramp"] = self.ramp_state(s)
        co = build_course(s.seed) if self.rs.checkpoints else None
        for hs, h in zip(out["helis"], s.helis):
            parts = k3_parts(h, self.version)
            hs.update(t_crash=h["t_crash"], ships_landed=list(h["ships_landed"]), td_E=h["td_E"],
                      td_ship=h["td_ship"], t_first_land=h["t_first_land"], t_last_point=h["t_last_point"],
                      k3=parts["k3"], partial=parts["partial"], metres=round(max(0.0, h["max_x"] - h["x0"]), 3),
                      score=parts["k3"], next_ship=self.next_ship(h))
            if co is not None:                  # ramp2.1: what the score and the renderer's gates need
                n = self.next_ship(h)
                a, b = checkpoint_span(co, n)
                hs.update(ckpt=h["ckpt"], q=parts["q"], touchdown=parts["touchdown"], k3_pure=parts["k3_pure"],
                          ckpt_a=a, ckpt_b=b, max_x=round(h["max_x"], 3))
        return out

    def observe(self, s: RWState, p: int) -> dict:
        """Rotorwash.observe with the lowered roof in the rays, the ramp numbers, the points and the next ship."""
        o = super().observe(s, p)
        co = build_course(s.seed)
        h = s.helis[p]
        k = s.t_ms // TICK_MS
        t = s.k * DT
        rc = ramp_course(s.seed, self.sched, k)
        o["rays"] = self.rays(rc, h["x"], h["y"], t)
        rp = ramp_at(self.sched, k)
        j = self.next_ship(h)
        dky, dkv, _ = co.deck(j, t)
        parts = k3_parts(h, self.version)
        o.update(level=rp.level, roof_drop=rp.roof_mm / 1000, gust_gain=rp.gust_q / 1024,
                 power_pct=100 * rp.power_q / 1024,
                 power_margin=100 * (rw.P_AVAIL * rp.power_q / 1024 - h["Preq"]) / (rw.P_AVAIL * rp.power_q / 1024),
                 k=k, points=parts["k3"], ships_landed=parts["ships"], ship=j, ship_dx=co.ships[j][0] - h["x"],
                 ship_dy=dky - h["y"], ship_vy=dkv, checkpoints=parts.get("checkpoints"))
        return o

    def observation(self, s: RWState, p: int) -> str:
        o = self.observe(s, p)
        rays = ", ".join(f"{n} {d:.1f}" for n, d in zip(RAY_NAMES, o["rays"]))
        if self.rs.checkpoints:                 # ramp2.1: clock vs the cap and the points (approach credit shows in
            # POINTS; the checkpoint count itself is left out of the prompt for the chord budget); no level / leg
            head = [f"STATE t={o['t']:.2f}s of {self.max_round_ms // 1000}; POINTS {o['points']:g}; roof "
                    f"-{o['roof_drop']:.1f} m; gusts x{o['gust_gain']:.2f}; power {o['power_pct']:.0f}%",
                    f"fuel {o['fuel']:.0f}%{', LANDED' if o['landed'] else ''}; altitude AGL {o['agl']:.1f} m; "]
        else:
            head = [f"STATE t={o['t']:.2f}s LEVEL {o['level']}/{self.n_levels}; roof -{o['roof_drop']:.1f} m; gusts "
                    f"x{o['gust_gain']:.2f}; engine power {o['power_pct']:.0f}%; POINTS {o['points']:g}",
                    f"leg {o['leg']}, fuel {o['fuel']:.0f}%{', LANDED' if o['landed'] else ''}; altitude AGL "
                    f"{o['agl']:.1f} m; "]
        lines = [
            self.rules_text,
            head[0],
            head[1] +
            f"vx {_f(o['vx'])} m/s; vy {_f(o['vy'])} m/s; pitch {_f(o['pitch'])} deg, rate {_f(o['pitch_rate'])} deg/s",
            f"rotor RPM {o['rpm']:.1f}%; collective {o['collective']:.0f}%; cyclic {_f(o['cyclic'])}; "
            f"power margin {_f(o['power_margin'], 0)}%; wind {_f(o['wind'][0])},{_f(o['wind'][1])} m/s (x,y)",
            f"rays to terrain, m (max {RAY_MAX:.0f}): {rays}",
            f"next ship {o['ship'] + 1}: deck dx {_f(o['ship_dx'])} m, dy {_f(o['ship_dy'])} m, vy {_f(o['ship_vy'])} m/s",
        ]
        if o["hooked"]:
            lines.append(f"load HOOKED; rope {o['rope']:.1f} m; load angle {_f(o['load_angle'])} deg, "
                         f"rate {_f(o['load_rate'])} deg/s")
        else:
            lines.append(f"survivor: dx {_f(o['target_dx'])} m, dy {_f(o['target_dy'])} m; hook timer "
                         f"{o['hook_timer']:.1f}/1.5 s; rope {o['rope']:.1f} m")
        return "\n".join(lines)

    # -------------------------------------------------------------- physics core
    def _integrate31(self, h: dict, co, k0: int, nsub: int, events: list, p: int, rp: Ramp) -> None:
        """Copy of RotorwashRamp._integrate_ramp (arena/games/rotorwash_ramp.py, unchanged there) with the collapse
        front removed and touchdown bookkeeping added (marked V31). Roof, storm and engine fade are as v3."""
        F, C, FH, CL, BAY = co.F, co.C, co.FH, co.CL, co.BAY
        WMX, GSX, GSY, SHA, SHY, DD, SHIPC, GX, GY = co.WMX, co.GSX, co.GSY, co.SHA, co.SHY, co.DD, co.SHIPC, co.GX, co.GY
        GM = RR.gap_min(co.seed, self.sched)                            # RAMP roof floor per cell
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
        vrs_on, droop_on, gust_on = h["vrs_on"], h["droop_on"], h["gust_on"]
        ships_landed = h["ships_landed"]                                # V31
        sin, cos, sqrt, exp, tanh = math.sin, math.cos, math.sqrt, math.exp, math.tanh
        surv, ships, nlast = co.surv, co.ships, len(co.ships) - 1
        xlim = co.xmax - 15.0
        wx = wy = 0.0
        loss = 0.0
        Preq = h["Preq"]
        cause = None
        td_ev = None                                                    # V31 ramp2.1: touchdown gauges (events only)
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
            Pcmd = Preq + K_G * (1.0 - r) * P_AV
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
                            # V31: the touchdown error E = max(sink_rel / LAND_VY, |pitch| / LAND_TH) of this contact
                            E = max((dkv - vy) / LAND_VY, abs(th) / LAND_TH)
                            if self.rs.checkpoints:             # event payload only (not state, not prompts)
                                td_ev = {"sink": round(dkv - vy, 3), "pitch": round(math.degrees(th), 2),
                                         "E": round(E, 4), "ship": sj}
                            if vy - dkv < -LAND_VY:
                                cause = "hard_landing"
                            elif abs(th) >= LAND_TH:
                                cause = "landing_attitude"
                            if cause is not None:
                                if sj not in ships_landed:                  # V31: partial credit on a new deck only
                                    h["td_E"], h["td_ship"] = E, sj
                            else:
                                landed = sj
                                y, vy, vx, th, w = dky + SKID_H, dkv, 0.0, 0.0, 0.0
                                t_ev = round(kk * 1000 / HZ)
                                new = sj not in ships_landed                 # V31: first landing on this ship
                                if new:
                                    ships_landed = tuple(sorted(ships_landed + (sj,)))
                                    if h["t_first_land"] is None:
                                        h["t_first_land"] = t_ev
                                    h["t_last_point"] = t_ev
                                if att:
                                    att = False
                                    h["deliveries"] += 1
                                    h["t_last_point"] = t_ev
                                    leg = max(leg, sj + 1)
                                    if leg > nlast:
                                        leg = nlast
                                    phi = phid = 0.0
                                    events.append(Event(t_ev, "delivered", p, {"leg": sj, "ship": ships[sj][0]}))
                                if new:                                      # V31: one event per credited ship
                                    ld = {"ship": sj, "new": True, "E": round(E, 4)}
                                    if td_ev is not None:
                                        ld.update(sink=td_ev["sink"], pitch=td_ev["pitch"])
                                    events.append(Event(t_ev, "landed", p, ld))
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
                 droop_on=droop_on, gust_on=gust_on, loss=loss, Preq=Preq, wx=wx, wy=wy, ships_landed=ships_landed)
        if self.rs.checkpoints:                                         # V31 ramp2.1: approach checkpoints
            h["ckpt"] = checkpoint(co, max_x, ships_landed)
        if cause is not None:
            h["alive"] = False
            h["cause"] = cause
            h["t_crash"] = round(kk * 1000 / HZ)
            cd = {"cause": cause, "x": round(x, 2), "y": round(y, 2)}
            if td_ev is not None and cause in TD_CAUSES:                # ramp2.1: the failing touchdown's gauges
                cd.update(td=td_ev, credit=round(k3_parts(h, self.version)["q"], 4))
            events.append(Event(h["t_crash"], "crash", p, cd))
        elif not wind_on:
            h["wx"] = h["wy"] = 0.0


# ------------------------------------------------------------------ game wrapper (rules id, lock)

class RampGame31:
    """Game protocol (arena.core.Game) for Rotorwash-Ramp v3.1: rules text + base schedule of a rules version
    (default ramp2.1; ramp2.0 replays the superseded draft bit-identically). No rule variants are defined yet (v3's
    scored variants were front/roof schedule variants; a v3.1 variant set is a later prereg item). `engine` is the
    RotorwashRampV31 the scripted bots observe."""

    def __init__(self, variant: str | None = None, announce: bool = True, sensors: bool = True, n_players: int = 4,
                 schedule: Schedule | None = None, rules_version: str = RULES_VERSION):
        if variant is not None:
            raise ValueError(f"rules {rules_version} defines no variants yet")
        self.variant, self.announce, self.sensors = None, announce, sensors
        self.rules_version = rules_version
        self.engine = RotorwashRampV31(schedule, None, n_players, rules_version)
        self.rules_text = self.engine.rules_text
        self.id, self.game_id = GAME_ID, GAME_ID
        self.n_players = self.engine.n_players
        self.decision_period_ms = TICK_MS
        self.max_round_ms = self.engine.max_round_ms

    @property
    def rules_id(self) -> str:
        return f"{GAME_ID}:{self.rules_version}:base:announced:{'L1' if self.sensors else 'L0'}"

    @property
    def schedule(self) -> Schedule:
        return self.engine.sched

    def ctx(self):
        return RR._patched({})

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


# ------------------------------------------------------------------ Arena binding

def rules_version_of(rec: dict) -> str:
    """Rules version of a record from its rules_id ('rotorwash_ramp_v31:<version>:...'); ramp2.0 records predate the
    field-free inference and are recognised the same way."""
    rid = rec.get("rules_id") or ""
    parts = rid.split(":")
    return parts[1] if len(parts) > 1 and parts[1] in RULESETS else RULES_VERSION


def score_record(rec: dict) -> dict:
    """Binding.score for Arena v3.1 RR: Y of the focal seat from the record's final render (every input is in the
    render: ships_landed, deliveries, crash_cause, td_E, and ckpt under ramp2.1). `raw` = Y; `survival_s` is
    descriptive only. The anchors are the frozen ones of the record's rules version."""
    v = rules_version_of(rec)
    rs = RULESETS[v]
    h = rec["final"]["helis"][0]
    parts = k3_parts(h, v)
    crash = h.get("t_crash")
    t_ms = crash if crash is not None else rec.get("duration_ms", rs.cap_ms)
    lp = ladder_position(parts["k3"], ANCHORS[v])
    out = {"raw": parts["k3"], "k3": parts["k3"], "ships": parts["ships"], "deliveries": parts["deliveries"],
           "partial": parts["partial"], "E": parts["E"], "survival_s": t_ms / 1000, "censored": crash is None,
           "level_at_end": level_of(t_ms // TICK_MS, rs.schedule.n_levels), "game_score": parts["k3"],
           "metres": h.get("metres"),
           "t_first_land_s": None if h.get("t_first_land") is None else h["t_first_land"] / 1000,
           "ladder_position": lp, "score01": min(1.0, lp), "cause": h.get("crash_cause"), "scoring": rs.scoring,
           "rules_version": v}
    if rs.checkpoints:
        out.update(q=parts["q"], checkpoints=parts["checkpoints"], touchdown=parts["touchdown"],
                   k3_pure=parts["k3_pure"])
    return out


# Frozen v3.1 ladder anchors (mean Y on the 32 calib seeds, 1-tick reply delay, macOS arm64 DESIGN-TIME runs; tests
# assert equality with the receipts). The Linux x86_64 re-run is required before these are used for ranking (prereg
# R3.23; docs/arena_v31/ROTORWASH_RAMP_V31.md §9 has the operator command).
#   ramp2.0: docs/arena_v31/rotorwash_ramp_v31_calibration.json 'anchors_k3' (superseded rules, kept for replay)
#   ramp2.1: docs/arena_v31/rotorwash_ramp_v31_ramp21_calibration.json 'anchors_k3'
ANCHORS_K3_20 = {"naive": 0.2793532663731863, "heuristic": 0.8083656481090572, "planner": 2.0}
ANCHORS_K3_21 = {"idle": 0.0, "naive": 0.334375, "heuristic": 0.6860398541427226, "planner": 1.1265625}
ANCHORS = {"ramp2.0": ANCHORS_K3_20, "ramp2.1": ANCHORS_K3_21}
ANCHORS_K3 = ANCHORS[RULES_VERSION]


def ladder_position(y: float, anchors: dict | None = None, hi: float = 1.2) -> float:
    """Y mapped piecewise-linearly through the frozen anchors: naive -> 0, heuristic -> 0.5, planner -> 1 (below naive
    0; above the planner the heuristic -> planner slope continues), clipped to [0, hi]."""
    a = anchors or ANCHORS[RULES_VERSION]
    x0, x1, x2 = a["naive"], a["heuristic"], a["planner"]
    if y <= x0:
        v = 0.0
    elif y <= x1:
        v = 0.5 * (y - x0) / (x1 - x0)
    else:
        v = 0.5 + 0.5 * (y - x1) / (x2 - x1)
    return max(0.0, min(hi, v))


def v31_binding(rules_version: str = RULES_VERSION):
    """arena.v3.games Binding for 'rotorwash_ramp_v31' at a rules version (default ramp2.1). Registering it in
    arena.v3.games.FACTORIES changes the harness sha that the live NC-R Arena pairing checks (docs/arena_v31/README.md
    §5); see ROTORWASH_RAMP_V31.md §8 for the consequences and the patch. Same controls / hold rules / safe defaults
    as v3 RR; env ghosts (seats 1..3) = the version's naive, heuristic and planner rungs; seed schedule = v3 RR's
    ('rotorwash_ramp'), so a v3.1 round plays the same seed as the v3 round with the same index (the RECORDS do not
    pair across rules versions: different rules and score)."""
    from dataclasses import dataclass as _dc

    from nagi.burst2._rt.arena.games.rotorwash_ramp_v31_bots import GHOSTS, make_bot
    from nagi.burst2._rt.arena.v3.games import Binding

    @_dc
    class _V31Binding(Binding):
        """Env ghosts (seats 1..3) come from arena.games.rotorwash_ramp_v31_bots."""

        def env_bots(self, seed: int):
            bots = {p: make_bot(b) for p, b in enumerate(self.env_bot_ids, start=1)}
            for p, bt in bots.items():
                bt.bind(p, seed)
            return bots

    b = _V31Binding(GAME_ID, lambda: RampGame31(None, True, True, rules_version=rules_version),
                     ("collective", "cyclic", "winch"),
                     {"collective": "one_shot", "cyclic": "persistent", "winch": "persistent"},
                     {"collective": "hold", "cyclic": "center", "winch": "hold"},
                     env_bot_ids=tuple(GHOSTS[rules_version]), float_engine=True, score=score_record,
                     seed_game=RR.GAME_ID)
    return b


def hash_steps(n_steps: int = 1000, rules_version: str = RULES_VERSION) -> str:
    """sha256 over state hashes + seat-0 prompt texts of n_steps ticks: calib seeds 0, 1, ... of rotorwash_ramp, the
    version's planner in seat 0 and its ghosts (naive, heuristic, planner) in seats 1..3, lockstep. Float engine:
    compare on the recording platform. (ramp2.0: the same chain as before ramp2.1 existed.)"""
    from nagi.burst2._rt.arena.games.rotorwash_ramp_bots import ramp_seed
    from nagi.burst2._rt.arena.games.rotorwash_ramp_v31_bots import GHOSTS, make_bot
    ghosts = GHOSTS[rules_version]
    h, steps, i = hashlib.sha256(), 0, 0
    while steps < n_steps:
        g = RampGame31(rules_version=rules_version)
        seed = ramp_seed("calib", i)
        bots = [make_bot(b).bind(p, seed) for p, b in enumerate((ghosts[-1], *ghosts))]
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


__all__ = ["RULES_VERSION", "RULES_VERSIONS", "RULESETS", "GAME_ID", "Schedule", "BASE", "BASE20", "BASE21",
           "RotorwashRampV31", "RampGame31", "k3_parts", "k3_value", "partial_credit", "touchdown_credit",
           "target_ship", "checkpoint", "checkpoint_span", "win", "score_record", "rules_version_of",
           "ladder_position", "ANCHORS", "v31_binding", "hash_steps", "replace"]
