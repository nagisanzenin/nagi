"""Rotorwash Ramp v3.1 (ramp2.1) observation contract: RRView, view builder, render / parse.

Information set at a request boundary k (the rrtp-request-v1 precedent, src/rr_teacher_pilot/contract.py, extended):
  obs        the V1 served state text of s_k verbatim (rules, STATE lines, rays, ship, survivor/load, Controls block);
  applied    p_log = the controls in force at k after collecting fresh replies (the reply to THIS request lands at
             k + 1 under the nominal 1-tick contract). RR controls act at once (collective is an accumulated setting,
             displayed exactly on its 5 % grid; cyclic and winch are re-set every tick): no hidden actuator follows
             from the client's own commands;
  rpm_low    consecutive request boundaries (this one included) whose DISPLAYED rotor RPM is below 85 % (the rules'
             stall threshold: RPM < 85 % for 1 s = crash). Client-derivable from the observation history; the
             engine's stall timer (stall_t) itself is sub-tick physics state and stays privileged. Added by G1: the
             frozen teacher reads the true stall_t (info audit, contract.md).
Privileged: absolute x / y, the course (terrain beyond the rays, bay cells, roof floor gap_min, far ships, heave
harmonics, gust series), engine delivered power Pe, stall_t, score bookkeeping.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from nagi.burst2._rt.arena.games import rotorwash as rw
from nagi.burst2._rt.bv2n.contract import common as C

VERSION = "bv2n-rr-view-v1"
SEED_GAME = "rotorwash_ramp"
CONTROLS = ("collective", "cyclic", "winch")
OPTIONS = {"collective": rw.COLL_OPTS, "cyclic": rw.CYC_OPTS, "winch": rw.WINCH_OPTS}
CAP_TOKENS = C.CAP_TOKENS
QUESTIONS = {
    "collective": {"type": "choice", "instructions": "Choose the collective change.",
                   "criteria": {o: o for o in OPTIONS["collective"]}},
    "cyclic": {"type": "choice", "instructions": "Choose the cyclic input.", "criteria": {o: o for o in OPTIONS["cyclic"]}},
    "winch": {"type": "choice", "instructions": "Choose the winch action.", "criteria": {o: o for o in OPTIONS["winch"]}},
}
_RPM = re.compile(r"^rotor RPM (\d+\.\d)%;", re.M)
_HEAD = "ROTORWASH RAMP (rules ramp2.1)"
_TAIL = "Choose WINCH: up=shorten 2 m/s, hold, down=lengthen 2 m/s."
RPM_LOW = 85.0
_LOW_RE = re.compile(r"^ROTOR: displayed RPM below 85% at the last (\d+) requests?$")


@dataclass(frozen=True)
class RRView:
    obs: str            # the V1 served state text, verbatim
    applied: tuple      # p_log in CONTROLS order
    rpm_low: int

    def __post_init__(self):
        check_obs(self.obs)
        if len(self.applied) != 3 or any(a not in OPTIONS[c] for c, a in zip(CONTROLS, self.applied)):
            raise ValueError(f"bad applied controls {self.applied}")
        if self.rpm_low < 0 or (self.rpm_low > 0) != (rpm(self.obs) < RPM_LOW):
            raise ValueError("rpm_low inconsistent with the displayed RPM")

    @property
    def p_log(self) -> dict:
        return dict(zip(CONTROLS, self.applied))


def check_obs(obs: str) -> None:
    if not obs.startswith(_HEAD) or not obs.endswith(_TAIL) or C.APPLIED_PREFIX in obs or "\nROTOR: " in obs:
        raise ValueError("not an RR ramp2.1 V1 state")


def rpm(obs: str) -> float:
    m = _RPM.findall(obs)
    if len(m) != 1:
        raise ValueError("rotor RPM line not found")
    return float(m[0])


class ViewBuilder:
    """Per-round client: push(served V1 state text, p_log) at every request boundary -> RRView."""

    def __init__(self):
        self.rpm_low = 0

    def push(self, obs: str, p_log: dict) -> RRView:
        self.rpm_low = self.rpm_low + 1 if rpm(obs) < RPM_LOW else 0
        return RRView(obs, normalize(p_log), self.rpm_low)


def normalize(p_log: dict) -> tuple:
    if set(p_log) != set(CONTROLS) or any(p_log[c] not in OPTIONS[c] for c in CONTROLS):
        raise ValueError(f"p_log must hold every RR control with a valid option: {p_log}")
    return tuple(p_log[c] for c in CONTROLS)


def served_v1(binding, game, s) -> str:
    from nagi.burst2._rt.burst_v2 import prompt as PR
    return PR.served_request(binding, game, s, SEED_GAME)[0]


def view_from_runner(binding, game, s, p_log: dict, builder: ViewBuilder) -> RRView:
    return builder.push(served_v1(binding, game, s), p_log)


def state_text(v: RRView) -> str:
    lines = [v.obs, C.applied_line(CONTROLS, v.applied)]
    if v.rpm_low:
        lines.append(f"ROTOR: displayed RPM below 85% at the last {v.rpm_low} request{'s' if v.rpm_low > 1 else ''}")
    return "\n".join(lines)


def render(v: RRView) -> str:
    return C.chord_prompt(state_text(v), QUESTIONS)


def parse_state(state: str) -> RRView:
    head, sep, rest = state.partition("\n" + C.APPLIED_PREFIX)
    if not sep:
        raise ValueError("missing APPLIED line")
    lines = (C.APPLIED_PREFIX + rest).split("\n")
    applied = C.parse_applied(lines[0], CONTROLS, OPTIONS)
    low = 0
    if len(lines) == 2:
        m = _LOW_RE.match(lines[1])
        if not m:
            raise ValueError("bad ROTOR line")
        low = int(m[1])
    elif len(lines) != 1:
        raise ValueError("unexpected lines after APPLIED")
    v = RRView(head, applied, low)
    if state_text(v) != state:
        raise ValueError("RR request does not round-trip")
    return v


def parse(text: str) -> RRView:
    if text.startswith("TASK DEFINITION:"):
        text = C.split_prompt(text, QUESTIONS)
    return parse_state(text)
