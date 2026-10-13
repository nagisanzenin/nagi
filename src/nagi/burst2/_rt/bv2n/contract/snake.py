"""Snake Rush rush-2 observation contract: SnakeView, view builder, render / parse.

Information set at a request boundary (tick t):
  obs      the V1 served state text of s_t verbatim (rules, map, clock/hunger/speed, length/growing/heading, head and
           food, the first 6 'Walls soon' with their ticks);
  applied  p_log = the move in force at t (after collecting fresh replies); the reply to THIS request lands at t + 1;
  body     the ordered body, head first (the map shows only H / o / t: a coiled body is ambiguous on the map). Client-
           derivable: the tracker replays the head trail from the client's own applied moves and the public speed
           schedule (straight moves within a tick, turns at tick boundaries) and checks it against every map;
  warned   every '+' cell with its ticks until due (<= 0 = overdue, waiting under the snake). The V1 text lists only the
           first 6; the rest are client-derivable because a scheduled wall is shown exactly WARN = 12 ticks before it
           is due (first sight -> due = t + 12, or the listed value when the text lists it).
Privileged: the unshown wall schedule, the food RNG (draw counter k), the seed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from nagi.burst2._rt.arena.games import snake_rush as S
from nagi.burst2._rt.bv2n.contract import common as C

VERSION = "bv2n-snake-view-v1"
SEED_GAME = "snake"
CONTROLS = ("move",)
OPTIONS = {"move": S.DNAME}
CAP_TOKENS = C.CAP_TOKENS
QUESTIONS = {"move": {"type": "choice", "instructions": "Choose your move for this tick.",
                      "criteria": {o: o for o in S.DNAME}}}
_HEAD = "SNAKE RUSH (rules rush-2)"
_TICK = re.compile(r"^Time \S+ s \(tick (\d+)\), level \d+\. Hunger (-?\d+) ticks left", re.M)
_LEN = re.compile(r"^Length (\d+), growing (\d+), heading (up|right|down|left)(?: \(next (up|right|down|left)\))?\. "
                  r"Food eaten (\d+)\.$", re.M)
_SOON = re.compile(r"^Walls soon: (.*?)(?: \(\+\d+ more\))? ticks\.$", re.M)
_SOON_ITEM = re.compile(r"\((\d+),(\d+)\) in (\d+)")
_CELL = re.compile(r"\((\d+),(\d+)\)")
BODY_PREFIX = "BODY head to tail: "
WARN_PREFIX = "WALLS SOON, all (ticks left): "


def cell_txt(c: int) -> str:
    x, y = S.xy(c)
    return f"({x},{y})"


def parse_cell(m) -> int:
    return int(m[2]) * S.N + int(m[1])


@dataclass(frozen=True)
class SnakeView:
    obs: str
    applied: tuple      # (move,)
    body: tuple         # cells, head first
    warned: tuple       # ((cell, ticks until due), ...) sorted by cell

    def __post_init__(self):
        check_obs(self.obs)
        if len(self.applied) != 1 or self.applied[0] not in S.DNAME:
            raise ValueError("bad applied move")
        g = grid(self.obs)
        cells = {c for c, ch in enumerate(g) if ch in "Hot"}
        if (not self.body or g[self.body[0]] != "H" or set(self.body) != cells or len(set(self.body)) != len(self.body)
                or len(self.body) != info(self.obs)["length"]):
            raise ValueError("body inconsistent with the map")

    @property
    def p_log(self) -> dict:
        return {"move": self.applied[0]}


def check_obs(obs: str) -> None:
    if not obs.startswith(_HEAD) or C.APPLIED_PREFIX in obs or BODY_PREFIX in obs or WARN_PREFIX in obs:
        raise ValueError("not a Snake rush-2 V1 state")


def grid(obs: str) -> str:
    lines = obs.split("\n")
    i = next(k for k, line in enumerate(lines) if line.startswith("Map ("))
    rows = lines[i + 1:i + 1 + S.N]
    assert all(len(r) == S.N for r in rows), rows
    return "".join(rows)


def info(obs: str) -> dict:
    m, n = _TICK.search(obs), _LEN.search(obs)
    if not m or not n:
        raise ValueError("Snake status lines not found")
    soon = _SOON.search(obs)
    listed = {parse_cell(x): int(x[3]) for x in _SOON_ITEM.finditer(soon[1])} if soon else {}
    heading = S.DNAME.index(n[3])
    return {"tick": int(m[1]), "hunger": int(m[2]), "length": int(n[1]), "grow": int(n[2]), "heading": heading,
            "dir": S.DNAME.index(n[4]) if n[4] else heading, "eaten": int(n[5]), "listed": listed}


def _map_body(g: str) -> tuple:
    """Unique head-to-tail path through the H/o/t cells of the map (round start); ValueError if not unique."""
    cells = {c for c, ch in enumerate(g) if ch in "Hot"}
    head = g.index("H")
    tail = g.index("t") if "t" in g else head
    out = []

    def dfs(path, seen):
        if len(out) > 1:
            return
        if len(path) == len(cells):
            if path[-1] == tail:
                out.append(tuple(path))
            return
        for d in range(4):
            nb = S.NB[False][path[-1]][d]
            if nb in cells and nb not in seen:
                seen.add(nb)
                dfs(path + [nb], seen)
                seen.discard(nb)
    dfs([head], {head})
    if len(out) != 1:
        raise ValueError(f"map body not unique ({len(out)} paths)")
    return out[0]


class ViewBuilder:
    """Per-round client: push(served V1 state text, p_log) at every request boundary -> SnakeView."""

    def __init__(self, rules: S.Rules = S.BASE):
        self.R = rules
        self.trail: tuple | None = None
        self.tick = None
        self.dir = None
        self.heading = None
        self.applied_at: dict = {}
        self.due: dict = {}

    def push(self, obs: str, p_log: dict) -> SnakeView:
        check_obs(obs)
        g, o = grid(obs), info(obs)
        t = o["tick"]
        if self.trail is None:
            if t != 0:
                raise ValueError("the Snake tracker starts at tick 0")
            trail = _map_body(g)
        else:
            trail, d, heading = self.trail, self.dir, self.heading
            for u in range(self.tick, t):
                a = self.applied_at.get(u, S.DNAME[d])          # no request at u: the hold rule (query default)
                d = S.DNAME.index(a) if a in S.legal(heading) else d
                n = self.R.cells(u)
                for _ in range(n):
                    trail = (S.NB[self.R.wrap][trail[0]][d],) + trail
                if n:
                    heading = d
            if heading != o["heading"] or d != o["dir"]:
                raise ValueError("tracker heading/dir out of sync with the display")
        body = trail[:o["length"]]
        self.trail = body
        # warned cells: first sight -> due = t + WARN unless the text lists its ticks; drop built walls
        plus = {c for c, ch in enumerate(g) if ch == "+"}
        for c, dd in o["listed"].items():
            self.due.setdefault(c, t + dd)
        for c in plus:
            self.due.setdefault(c, t + S.WARN)
        for c in [c for c in self.due if g[c] == "#"]:
            del self.due[c]
        warned = tuple(sorted((c, self.due[c] - t) for c in self.due))
        applied = normalize(p_log)
        self.tick, self.dir, self.heading = t, o["dir"], o["heading"]
        self.applied_at[t] = applied[0]
        return SnakeView(obs, applied, body, warned)


def normalize(p_log: dict) -> tuple:
    if set(p_log) != {"move"} or p_log["move"] not in S.DNAME:
        raise ValueError(f"bad Snake p_log {p_log}")
    return (p_log["move"],)


def served_v1(binding, game, s) -> str:
    from nagi.burst2._rt.burst_v2 import prompt as PR
    return PR.served_request(binding, game, s, SEED_GAME)[0]


def view_from_runner(binding, game, s, p_log: dict, builder: ViewBuilder) -> SnakeView:
    return builder.push(served_v1(binding, game, s), p_log)


def state_text(v: SnakeView) -> str:
    warn = ", ".join(f"{cell_txt(c)} {d}" for c, d in v.warned) or "none"
    return "\n".join([v.obs, C.applied_line(CONTROLS, v.applied), BODY_PREFIX + " ".join(cell_txt(c) for c in v.body),
                      WARN_PREFIX + warn])


def render(v: SnakeView) -> str:
    return C.chord_prompt(state_text(v), QUESTIONS)


_WITEM = re.compile(r"\((\d+),(\d+)\) (-?\d+)")


def parse_state(state: str) -> SnakeView:
    lines = state.split("\n")
    if len(lines) < 4 or not lines[-2].startswith(BODY_PREFIX) or not lines[-1].startswith(WARN_PREFIX):
        raise ValueError("bad Snake request tail")
    obs = "\n".join(lines[:-3])
    applied = C.parse_applied(lines[-3], CONTROLS, OPTIONS)
    body = tuple(parse_cell(m) for m in _CELL.finditer(lines[-2][len(BODY_PREFIX):]))
    wtxt = lines[-1][len(WARN_PREFIX):]
    warned = () if wtxt == "none" else tuple((parse_cell(m), int(m[3])) for m in _WITEM.finditer(wtxt))
    v = SnakeView(obs, applied, body, warned)
    if state_text(v) != state:
        raise ValueError("Snake request does not round-trip")
    return v


def parse(text: str) -> SnakeView:
    if text.startswith("TASK DEFINITION:"):
        text = C.split_prompt(text, QUESTIONS)
    return parse_state(text)
