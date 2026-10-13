"""Booster Gauntlet g1.2 (Arena v3.1, L0) observation contract: BoosterView, view builder, render / parse.

Information set (docs/burst_v2_next/LANES.md "Booster information set"), at a request boundary k:
  frame      the displayed observation of s_k, parsed losslessly from the V1 served state text (every number is the
             DISPLAYED, rounded value as an int in display units: t/age/next in 0.01 s, speeds in 0.1 m/s, angles in
             0.1 deg, q in 0.1 kPa, TWR in 0.01, height/dx/zone m, fuel kg, thrust kN);
  applied    p_log = the controls in force at k after collecting fresh replies (the runner's _controls), i.e. what the
             engine applies to s_k before the reply to THIS request lands (nominal: at k + 1);
  act        actuator states that follow from the client's own commands but are NOT displayed, pre-apply at k:
             ignition delay left (ms; a lit command takes 0.3 s to produce thrust), fin deployment (%; fins take
             1 s to deploy / stow, the display shows only the commanded setting), fin deflection (%, slews
             0.25 s across). They are computed by `Tracker` from the frames and applied controls only (the rules are
             public); tests check them against the engine's hidden values;
  hist       the last H = 8 ticks (every tick, oldest first; None = no request observed at that tick, e.g. under a
             2-tick reply or before the round start): displayed booster kinematics (height, vx, vy, ship dx, tilt,
             rate) and deck / wind state (deck vx, deck vy, deck pitch, wind at the booster). Fields that are exact
             functions of the current frame + applied controls are not repeated. Coordinator decision 2026-10-11: this
             set needs a 1280-token cap for Booster (CAP_TOKENS; V1 sections verbatim).
Privileged (never in the view): exact sub-display state (x, y, speeds, angles), true future gusts, wind sign, ship
surge/heave/pitch periods/phases/amplitudes, the RNG.

Served request = V1 state text verbatim (rules paragraph, STATE lines, Controls block) + new lines:
  "APPLIED now: ...", "ACTUATORS: ...", "HISTORY ..." (10 rows x 8 ticks); in the V1 chord prompt with the canonical questions.
parse(render(v)) == v exactly. Nominal timing (contract constant, not text): the reply to this request lands at k + 1.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, fields

from nagi.burst2._rt.arena.games import booster_gauntlet as G
from nagi.burst2._rt.arena.games import booster_gauntlet_arena as BA
from nagi.burst2._rt.bv2n.contract import common as C

VERSION = "bv2n-booster-view-v2"
CAP_TOKENS = 1280         # coordinator decision 2026-10-11: Booster request cap (hard ceiling 1536)
SEED_GAME = "booster_gauntlet"
GAME_ID = "booster_gauntlet_v31"
CONTROLS = ("throttle", "gimbal", "fins", "legs")
OPTIONS = {"throttle": G.THR_OPTS, "gimbal": G.GIM_OPTS, "fins": G.FIN_OPTS, "legs": G.LEG_OPTS}
H = 8                    # history window: every one of the last 8 ticks
OFFSETS = tuple(range(H, 0, -1))
TICK_CS = G.DECISION_MS // 10


@dataclass(frozen=True)
class Frame:
    """One displayed observation (V1 state lines), display units (see module docstring)."""
    t: int
    level: int
    nxt: int
    hop: int
    landed: int
    age: int
    alt: int
    vx: int
    vy: int
    tilt: int
    rate: int
    dx: int
    zone: int
    dvx: int
    dvy: int
    pitch: int
    wind: int
    eng: str            # 'OFF' or the lit level ('min' / 'mid' / 'max')
    thr: int | None     # displayed thrust kN (None when OFF: not displayed)
    relights: int
    relights0: int
    gim: int
    fuel: int
    fuel0: int
    fins: str           # displayed fin setting, lower case
    legs: str           # 'stowed' | 'deploying' | 'down'
    legs_pct: int | None
    q: int
    twr: tuple          # (min, mid, max) TWR now, 0.01


@dataclass(frozen=True)
class Actuators:
    ign_ms: int         # ignition delay left (ms) before the lit engine produces thrust (0..300, multiple of 50)
    fin_out: int        # fin deployment % (0 stowed .. 100 deployed; moves 5 % per 50 ms substep)
    fin_defl: int       # fin deflection % (-100 left .. +100 right, fin_sign applied; moves 20 % per substep)


@dataclass(frozen=True)
class HistRow:
    """Displayed booster + deck / wind state at one earlier tick (None in `hist` = no request observed at that tick).
    Units as Frame. Fields that are exact functions of the current frame + applied controls (fuel, engine, relights,
    fins, legs, q, clock) are not repeated."""
    alt: int
    vx: int
    vy: int
    dx: int
    tilt: int
    rate: int
    dvx: int
    dvy: int
    pitch: int
    wind: int


@dataclass(frozen=True)
class BoosterView:
    frame: Frame
    applied: tuple      # p_log in CONTROLS order
    act: Actuators
    hist: tuple         # len(OFFSETS) entries, HistRow | None, oldest first: hist[i] = OFFSETS[i] ticks before this one

    @property
    def p_log(self) -> dict:
        return dict(zip(CONTROLS, self.applied))

    @property
    def t_ms(self) -> int:
        return self.frame.t * 10


# ------------------------------------------------------------------ the V1 state text <-> Frame
_GAME = G.BoosterGauntlet(None, True, False, rules_version="g1.2")      # = v31 binding make() (tested)
RULES_TEXT = _GAME.rules_text
_N = r"[+-]?\d+(?:\.\d+)?"
_L1 = re.compile(rf"^STATE t ({_N}) s \| LEVEL (\d+), next in ({_N}) s \| hop (\d+) \(landed (\d+)\), ({_N}) s since drop$")
_L2 = re.compile(rf"^height ({_N}) m above deck \| vx ({_N}) vy ({_N}) m/s \| tilt ({_N}) deg, rate ({_N}) deg/s$")
_L3 = re.compile(rf"^ship dx ({_N}) m, zone \+-({_N}) m \| deck vx ({_N}) vy ({_N}) m/s, pitch ({_N}) deg \| wind "
                 rf"({_N}) m/s$")
_L4 = re.compile(rf"^engine (?:ON (min|mid|max) (\d+) kN|OFF), relights (\d+)/(\d+), gimbal ({_N}) \| fuel (\d+)/(\d+) kg"
                 rf" \| fins (STOWED|LEFT|NEUTRAL|RIGHT) \| legs (STOWED|DOWN|DEPLOYING (\d+)%) \| q ({_N}) kPa$")
_L5 = re.compile(rf"^THROTTLE \(TWR now ({_N})/({_N})/({_N}); starting uses a relight\)$")
_CTRL_TAIL = ("GIMBAL deg: L2 -5, L1 -2, 0, R1 +2, R2 +5 (only while burning)", "FINS (right: top to +x)",
              "LEGS (deploy is one-way per hop)")


def frame_lines(f: Frame) -> list[str]:
    u2 = lambda v: C.fnum(v, 2, False)          # noqa: E731
    s1 = lambda v: C.fnum(v, 1)                 # noqa: E731
    eng = f"ON {f.eng} {f.thr} kN" if f.eng != "OFF" else "OFF"
    legs = f"DEPLOYING {f.legs_pct}%" if f.legs == "deploying" else f.legs.upper()
    return [
        RULES_TEXT,
        f"STATE t {u2(f.t)} s | LEVEL {f.level}, next in {u2(f.nxt)} s | hop {f.hop} (landed {f.landed}), "
        f"{u2(f.age)} s since drop",
        f"height {C.fnum(f.alt, 0)} m above deck | vx {s1(f.vx)} vy {s1(f.vy)} m/s | tilt {s1(f.tilt)} deg, rate "
        f"{s1(f.rate)} deg/s",
        f"ship dx {C.fnum(f.dx, 0)} m, zone +-{C.fnum(f.zone, 0, False)} m | deck vx {s1(f.dvx)} vy {s1(f.dvy)} m/s, "
        f"pitch {s1(f.pitch)} deg | wind {s1(f.wind)} m/s",
        f"engine {eng}, relights {f.relights}/{f.relights0}, gimbal {s1(f.gim)} | fuel {f.fuel}/{f.fuel0} kg | fins "
        f"{f.fins.upper()} | legs {legs} | q {C.fnum(f.q, 1, False)} kPa",
        "Controls:",
        "THROTTLE (TWR now " + "/".join(C.fnum(v, 2, False) for v in f.twr) + "; starting uses a relight)",
        *_CTRL_TAIL,
    ]


def v1_state(f: Frame) -> str:
    """The V1 served state text (game.multi_query text) of a frame, byte-identical (tested)."""
    return "\n".join(frame_lines(f))


def parse_frame(lines: list[str]) -> Frame:
    if len(lines) != 10 or lines[0] != RULES_TEXT or lines[5] != "Controls:" or tuple(lines[7:10]) != _CTRL_TAIL:
        raise ValueError("not a Booster g1.2 L0 V1 state")
    m1, m2, m3, m4, m5 = (r.match(x) for r, x in zip((_L1, _L2, _L3, _L4, _L5), lines[1:5] + [lines[6]]))
    if not all((m1, m2, m3, m4, m5)):
        raise ValueError("unparseable Booster state line")
    p = C.pnum
    lit = m4.group(1) is not None
    legs_raw = m4.group(9)
    f = Frame(t=p(m1[1], 2), level=int(m1[2]), nxt=p(m1[3], 2), hop=int(m1[4]), landed=int(m1[5]), age=p(m1[6], 2),
              alt=p(m2[1], 0), vx=p(m2[2], 1), vy=p(m2[3], 1), tilt=p(m2[4], 1), rate=p(m2[5], 1),
              dx=p(m3[1], 0), zone=p(m3[2], 0), dvx=p(m3[3], 1), dvy=p(m3[4], 1), pitch=p(m3[5], 1), wind=p(m3[6], 1),
              eng=m4[1] if lit else "OFF", thr=int(m4[2]) if lit else None, relights=int(m4[3]),
              relights0=int(m4[4]), gim=p(m4[5], 1), fuel=int(m4[6]), fuel0=int(m4[7]), fins=m4[8].lower(),
              legs="deploying" if legs_raw.startswith("DEPLOYING") else legs_raw.lower(),
              legs_pct=int(m4[10]) if legs_raw.startswith("DEPLOYING") else None, q=p(m4[11], 1),
              twr=(p(m5[1], 2), p(m5[2], 2), p(m5[3], 2)))
    if frame_lines(f) != lines:
        raise ValueError("Booster state does not round-trip")
    return f


# ------------------------------------------------------------------ actuator tracker (client side)
class Tracker:
    """Hidden actuator state from the client's own applied controls + the displayed frames + the public rules.
    Feed every request boundary of a round in order (from the round start or a drop). Ticks without a request (a
    reply still in flight) re-apply the held controls (Booster hold rules: all persistent)."""

    def __init__(self, rules: G.Rules = G.BASE_RULES):
        self.rules = rules
        self.h: dict | None = None
        self.t_ms: int | None = None
        self.held: tuple | None = None

    def _drop(self, f: Frame) -> dict:
        t0 = (f.t - f.age) * 10
        if f.age != 0:
            raise ValueError("Tracker must start at a drop (age 0): actuator history unknown")
        return {"hop_k0": t0 // G.SUB_MS, "lit": 0, "ign": 0, "thr": 0, "thr_cmd": 0, "lvl": "off",
                "relights": f.relights, "fuel": f.fuel * 1000, "tmin": self.rules.t_min_at(t0), "gim": 0, "gim_cmd": 0,
                "gcmd": "0", "fin": "neutral", "fin_dep": 1000, "fin_u": 0, "legs": 0, "legs_on": 0, "nr": 0,
                "last": ("off", "0", "neutral", "stowed")}

    def _substeps(self, n: int) -> None:
        h, r = self.h, self.rules
        fin_ut = G.FIN_U[h["fin"]] * r.fin_sign
        for _ in range(n):                       # = the actuator block of booster_gauntlet.integrate
            if h["lit"]:
                if h["ign"]:
                    h["ign"] -= 1
                elif h["thr"] < h["thr_cmd"]:
                    h["thr"] = min(h["thr_cmd"], h["thr"] + G.THR_UP)
                elif h["thr"] > h["thr_cmd"]:
                    h["thr"] = max(h["thr_cmd"], h["thr"] - G.THR_DN)
            elif h["thr"]:
                h["thr"] = max(0, h["thr"] - G.THR_DN)
            if h["gim"] < h["gim_cmd"]:
                h["gim"] = min(h["gim_cmd"], h["gim"] + G.GIM_RATE)
            elif h["gim"] > h["gim_cmd"]:
                h["gim"] = max(h["gim_cmd"], h["gim"] - G.GIM_RATE)
            if h["fin"] != "stowed":
                if h["fin_dep"] < 1000:
                    h["fin_dep"] = min(1000, h["fin_dep"] + G.FIN_DEP_RATE)
            elif h["fin_dep"]:
                h["fin_dep"] = max(0, h["fin_dep"] - G.FIN_DEP_RATE)
            if h["fin_u"] < fin_ut:
                h["fin_u"] = min(fin_ut, h["fin_u"] + G.FIN_U_RATE)
            elif h["fin_u"] > fin_ut:
                h["fin_u"] = max(fin_ut, h["fin_u"] - G.FIN_U_RATE)
            if h["legs_on"] and h["legs"] < 1000:
                h["legs"] = min(1000, h["legs"] + self.rules.leg_rate)

    def _apply(self, applied: tuple, t_ms: int) -> None:
        G.apply_action(self.h, self.rules, dict(zip(CONTROLS, applied)), None, 0, t_ms)

    def push(self, f: Frame, applied: tuple) -> Actuators:
        t = f.t * 10
        if self.h is None or f.hop != self.h["hop"]:
            self.h = self._drop(f)
            self.h["hop"] = f.hop
        else:
            n_ticks = (t - self.t_ms) // G.DECISION_MS
            assert n_ticks >= 1 and (t - self.t_ms) % G.DECISION_MS == 0, (t, self.t_ms)
            for i in range(n_ticks):
                if i:
                    self._apply(self.held, self.t_ms + i * G.DECISION_MS)
                self._substeps(G.DECISION_MS // G.SUB_MS)
            if f.eng == "OFF" and self.h["lit"]:            # flameout (fuel ran out mid-tick): engine.integrate zeroes
                self.h["lit"], self.h["ign"], self.h["thr"] = 0, 0, 0
        h = self.h
        h["relights"], h["fuel"] = f.relights, f.fuel * 1000            # displayed (exact / floor kg)
        if bool(h["lit"]) != (f.eng != "OFF") or (h["lit"] and (h["lvl"] != f.eng or h["thr"] // 1000 != f.thr)):
            raise ValueError(f"tracker out of sync with the display at t={t}: {h['lit'], h['lvl'], h['thr']} vs "
                             f"{f.eng, f.thr}")
        assert h["fin_dep"] % 10 == 0 and h["fin_u"] % 10 == 0, (h["fin_dep"], h["fin_u"])
        out = Actuators(ign_ms=h["ign"] * G.SUB_MS, fin_out=h["fin_dep"] // 10, fin_defl=h["fin_u"] // 10)
        self._apply(applied, t)
        self.t_ms, self.held = t, tuple(applied)
        return out


# ------------------------------------------------------------------ view builder (runner side)
class ViewBuilder:
    """Per-round client: push(served V1 state text, p_log) at every request boundary -> BoosterView. Its only inputs
    are the served text and the client's own applied controls (information-flow guarantee)."""

    def __init__(self, rules: G.Rules = G.BASE_RULES):
        self.tracker = Tracker(rules)
        self.frames: list[Frame] = []

    def push(self, state_text: str, p_log: dict) -> BoosterView:
        f = parse_frame(state_text.split("\n"))
        applied = normalize(p_log)
        act = self.tracker.push(f, applied)
        seen = {g.t: HistRow(g.alt, g.vx, g.vy, g.dx, g.tilt, g.rate, g.dvx, g.dvy, g.pitch, g.wind)
                for g in self.frames[-H:]}
        hist = tuple(seen.get(f.t - i * TICK_CS) for i in OFFSETS)
        self.frames.append(f)
        return BoosterView(f, applied, act, hist)


def normalize(p_log: dict) -> tuple:
    if set(p_log) != set(CONTROLS) or any(p_log[c] not in OPTIONS[c] for c in CONTROLS):
        raise ValueError(f"p_log must hold every Booster control with a valid option: {p_log}")
    return tuple(p_log[c] for c in CONTROLS)


def served_v1(game, s) -> str:
    """The V1 served state text of s (seat 0): game.multi_query text (= burst_v2.prompt.served_request state)."""
    mq = game.multi_query(s, 0)
    if mq is None:
        raise ValueError("no request: the booster is not flying")
    return mq.text


def view_from_runner(game, s, p_log: dict, builder: ViewBuilder) -> BoosterView:
    """The view at a request boundary of the realtime runner: s = the state the request observes, p_log = the controls
    the runner applies at this boundary (after collecting fresh replies). Call at every request boundary in order."""
    return builder.push(served_v1(game, s), p_log)


# ------------------------------------------------------------------ render / parse
QUESTIONS = {c: {"type": "choice", "instructions": f"Choose the {c}.", "criteria": {o: o for o in OPTIONS[c]}}
             for c in CONTROLS}
_HIST_COLS = ("alt", "vx", "vy", "dx", "tilt", "rate", "dvx", "dvy", "pitch", "wind")
_HIST_NAMES = ("height m", "vx", "vy", "ship dx m", "tilt", "rate", "deck vx", "deck vy", "deck pitch", "wind")
HIST_HEAD = "HISTORY last 8 ticks, oldest first; speeds, angles, rates in 0.1 units (. unseen):"
_ACT_RE = re.compile(r"^ACTUATORS: ignition delay (\d+) ms, fins out (\d+)%, fin deflection ([+-]\d+)%$")


def state_text(v: BoosterView) -> str:
    a = v.act
    lines = frame_lines(v.frame) + [
        C.applied_line(CONTROLS, v.applied),
        f"ACTUATORS: ignition delay {a.ign_ms} ms, fins out {a.fin_out}%, fin deflection {C.fnum(a.fin_defl, 0)}%",
        HIST_HEAD,
    ]
    for col, name in zip(_HIST_COLS, _HIST_NAMES):
        lines.append(name + " " + " ".join("." if r is None else str(getattr(r, col)) for r in v.hist))
    return "\n".join(lines)


def render(v: BoosterView) -> str:
    """The served request (full V1 chord prompt)."""
    return C.chord_prompt(state_text(v), QUESTIONS)


def parse_state(state: str) -> BoosterView:
    lines = state.split("\n")
    f = parse_frame(lines[:10])
    applied = C.parse_applied(lines[10], CONTROLS, OPTIONS)
    m = _ACT_RE.match(lines[11])
    if not m:
        raise ValueError("bad ACTUATORS line")
    act = Actuators(int(m[1]), int(m[2]), int(m[3]))
    rest = lines[12:]
    if len(rest) != 1 + len(_HIST_COLS) or rest[0] != HIST_HEAD:
        raise ValueError("bad HISTORY block")
    cols = []
    for line, name in zip(rest[1:], _HIST_NAMES):
        if not line.startswith(name + " "):
            raise ValueError(f"bad HISTORY row {line!r}")
        vals = line[len(name) + 1:].split(" ")
        if len(vals) != len(OFFSETS):
            raise ValueError("HISTORY row must have one entry per offset")
        cols.append([None if x == "." else int(x) for x in vals])
    hist = []
    for vals in zip(*cols):
        if any(x is None for x in vals) and not all(x is None for x in vals):
            raise ValueError("partially observed HISTORY tick")
        hist.append(None if vals[0] is None else HistRow(*vals))
    hist = tuple(hist)
    v = BoosterView(f, applied, act, hist)
    if state_text(v) != state:
        raise ValueError("Booster request does not round-trip")
    return v


def parse(text: str) -> BoosterView:
    """Inverse of render (also accepts the bare state text)."""
    if text.startswith("TASK DEFINITION:"):
        text = C.split_prompt(text, QUESTIONS)
    return parse_state(text)


def view_fields() -> dict:
    return {cls.__name__: [f.name for f in fields(cls)] for cls in (BoosterView, Frame, Actuators, HistRow)}
