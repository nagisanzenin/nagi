"""View sources: what the client sees at a request boundary, and the teacher's label of it (bv2n lane gamedata).

A view source turns a runner state (+ the controls the runner applies at this tick, p_log, + the episode history)
into the served request text, the parsed view the student reads, and the teacher label. Two implementations:

  * ``legacy``   (interim, until lane 'contract' lands): view = a dict parsed back from the request text ONLY.
                 Snake: text = the K-call observation + an applied-controls line; teacher = sr3_planner on the runner
                 state (lag-aware at the nominal 1-tick reply) -- NOT view-only; must move to the contract wrapper.
                 RR: text = rr_teacher_pilot request rrtp-request-v1; teacher = its strict request-only Teacher
                 (a function of the text only; Linux gate 24/24).
  * ``contract`` (final): text = bv2n.contract.<game>.render(view), view = parse(text) (== the ClientView), teacher =
                 bv2n.teachers.<game> on the view only.

Switching is one line: ``SOURCE`` below (or the ``source=`` argument of ``make``). The student reads only
``view`` (featurized by bv2n.student.features), never the runner state.
"""
from __future__ import annotations

import hashlib
import json
import re

SOURCE = "contract"
GAMES = ("snake", "rr", "booster")
SEED_GAME = {"snake": "snake", "rr": "rotorwash_ramp", "booster": "booster_gauntlet"}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _plog_line(p_log: dict) -> str:
    return "APPLIED THIS TICK: " + json.dumps(dict(sorted(p_log.items())), separators=(",", ":"))


def _split_plog(text: str) -> tuple[str, dict]:
    i = text.rfind("\nAPPLIED THIS TICK: ")
    assert i >= 0, "request text without the applied-controls line"
    return text[:i], json.loads(text[i + len("\nAPPLIED THIS TICK: "):])


# ------------------------------------------------------------------------------------------------ Snake (legacy)
_SN_TIME = re.compile(r"Time ([\d.]+) s \(tick (\d+)\), level (\d+)\. Hunger (\d+) ticks left \(limit (\d+)\)\. (.*?)\.\n")
_SN_LEN = re.compile(r"Length (\d+), growing (\d+), heading (\w+)(?: \(next (\w+)\))?\. Food eaten (\d+)\.")
_SN_FOOD = re.compile(r"\((\d+),(\d+)\): ")
DNAME = ("up", "right", "down", "left")


def parse_snake(text: str) -> dict:
    obs, p_log = _split_plog(text)
    lines = obs.split("\n")
    i = next(n for n, x in enumerate(lines) if x.startswith("Map ("))
    grid = lines[i + 1:i + 13]
    assert len(grid) == 12 and all(len(r) == 12 for r in grid), "snake grid"
    m = _SN_TIME.search(obs + "\n")
    assert m, "snake time line"
    mv = m.group(6)
    if mv.startswith("This move: "):
        cells_now, cells_next = int(mv.split()[2]), int(mv.split()[2])
    else:                                                    # "This tick waits; next move: k cell(s)"
        cells_now, cells_next = 0, int(mv.split("next move: ")[1].split()[0])
    m2 = _SN_LEN.search(obs)
    hm = re.search(r"Head \((\d+),(\d+)\)\. Food (.*)\.", obs)
    food = [[int(a), int(b)] for a, b in _SN_FOOD.findall(hm.group(3))] if "Food (" in hm.group(0) else []
    soon = []
    ws = re.search(r"Walls soon: (.*) ticks\.", obs)
    if ws:
        soon = [[int(a), int(b), int(d)] for a, b, d in re.findall(r"\((\d+),(\d+)\) in (\d+)", ws.group(1))]
    return {"game": "snake", "grid": grid, "t_s": float(m.group(1)), "tick": int(m.group(2)), "level": int(m.group(3)),
            "hunger": int(m.group(4)), "limit": int(m.group(5)), "cells_now": cells_now, "cells_next": cells_next,
            "length": int(m2.group(1)), "growing": int(m2.group(2)), "heading": m2.group(3),
            "next": m2.group(4) or m2.group(3), "eaten": int(m2.group(5)), "head": [int(hm.group(1)), int(hm.group(2))],
            "food": food, "soon": soon, "p_log": p_log}


class _SnakeLegacy:
    game_id, seed_game = "snake", "snake"
    controls = ("move",)

    def __init__(self):
        from nagi.burst2._rt.arena.games import snake_rush as S
        from nagi.burst2._rt.arena.games import snake_rush_bots as SB
        from nagi.burst2._rt.arena.v3 import games
        self.S, self.SB = S, SB
        self.binding = games.get("snake")
        self.game = self.binding.make()
        self.options = {"move": S.DNAME}

    def reset(self, seed):
        return self.game.reset(seed)

    def ctx(self):
        return self.game.ctx()

    def step(self, s, acts):
        return self.game.step(s, {0: acts}, self.S.TICK_MS)[0]

    def done(self, s):
        return self.game.done(s)

    def render(self, s, p_log, hist=None) -> str:
        return self.game.observation(s) + "\n" + _plog_line(p_log)

    parse = staticmethod(parse_snake)

    def teacher(self, s, view: dict, text: str | None = None) -> dict:
        p = view["p_log"].get("move", self.S.DNAME[s.dir])
        return {"move": self.SB.planner(s, self.game, self.game.rules, lag=(self.S.DNAME.index(p), 1))}

    def outcome(self, s) -> dict:
        S = self.S
        sv = S.survival_s(s)
        return {"survival_s": sv, "score": sv, "success": sv >= 30.0, "censored": S.censored(s), "cause": s.cause,
                "eaten": s.eaten, "ticks": s.tick}


# ------------------------------------------------------------------------------------------------ RR (legacy)
def parse_rr(text: str) -> dict:
    from nagi.burst2._rt.burst_v2.rr_teacher import parse_prompt
    from nagi.burst2._rt.rr_teacher_pilot.contract import applied_controls
    o = parse_prompt(text)
    o["wind"] = list(o["wind"])
    return dict(o, game="rr", p_log=applied_controls(text))


class _RRLegacy:
    """RR request = the rr_teacher_pilot request contract rrtp-request-v1 (served observation + explicit applied
    controls line + nominal-delay line); teacher = its strict request-only Teacher (RRTeacherPlanner c2e35a1f,
    DEFAULTS + filt_delays=(1,), lag_pred=True), the configuration that passed the Linux gate 24/24 (teachers-rs)."""
    game_id, seed_game = "rr", "rotorwash_ramp"
    controls = ("collective", "cyclic", "winch")

    def __init__(self):
        from nagi.burst2._rt.burst_v2.rr import RRAdapter
        from nagi.burst2._rt.rr_teacher_pilot import contract as RC
        from nagi.burst2._rt.rr_teacher_pilot import teacher as RTP
        self.RC, self.RTP = RC, RTP
        self.ad = RRAdapter()
        self.binding = self.ad.binding
        self.game = self.ad.real_game()
        self.options = dict(self.ad.OPTIONS)
        self._q = None

    def reset(self, seed):
        return self.ad.reset(seed)

    def ctx(self):
        return self.game.ctx()

    def step(self, s, acts):
        return self.game.step(s, {0: acts}, 250)[0]

    def done(self, s):
        return self.game.done(s)

    def render(self, s, p_log, hist=None) -> str:
        req = self.RC.request(self.binding, self.game, s, p_log)
        self._q = req.questions_json
        return req.state

    parse = staticmethod(parse_rr)

    def teacher(self, s, view: dict, text: str | None = None) -> dict:
        """A function of the request text only (s is unused; kept for the shared signature)."""
        assert text is not None and self._q is not None, "RR teacher needs the request text"
        return dict(self.RTP.Teacher(self.RC.Request(text, self._q)).controller())

    def outcome(self, s) -> dict:
        h = s.helis[0]
        p = self.ad.parts(h)
        return {"k3": p["k3"], "score": p["k3"], "ships": p["ships"], "deliveries": p["deliveries"],
                "success": p["ships"] >= 1, "cause": h["cause"], "t_end": s.t_ms / 1000}


# ------------------------------------------------------------------------------------------------ contract (final)
def view_dict(game: str, v) -> dict:
    """JSON form of a parsed ClientView for featurizing / storage: the ClientView's own fields + the fields parsed
    from its observation text (a deterministic function of the view; nothing from the runner)."""
    if game == "snake":
        from nagi.burst2._rt.arena.games import snake_rush as S
        d = parse_snake(v.obs + "\n" + _plog_line(v.p_log))
        d.update(body=[list(S.xy(c)) for c in v.body], warned=[[*S.xy(c), int(t)] for c, t in v.warned],
                 soon=[[*S.xy(c), int(t)] for c, t in v.warned])        # the complete '+' list (contract)
        return d
    if game == "rr":
        from nagi.burst2._rt.burst_v2.rr_teacher import parse_prompt
        o = parse_prompt(v.obs)
        o["wind"] = list(o["wind"])
        return dict(o, game="rr", p_log=v.p_log, rpm_low=v.rpm_low)
    raise NotImplementedError(game)


class _Contract:
    """bv2n.contract.<game> (ClientView, ViewBuilder, render / parse) + bv2n.teachers.<game> (view-only teacher).
    Text = render(view) (the served chord prompt); the student sees view_dict(parse(text)); the teacher sees
    parse(text) only."""

    def __init__(self, game: str):
        import importlib
        self.game_id, self.seed_game = game, SEED_GAME[game]
        self.C = importlib.import_module(f"nagi.burst2._rt.bv2n.contract.{game}")
        self.T = importlib.import_module(f"nagi.burst2._rt.bv2n.teachers.{game}")
        self.L = _SnakeLegacy() if game == "snake" else _RRLegacy()     # engine side only (reset/step/outcome)
        self.binding, self.game = self.L.binding, self.L.game
        self.controls, self.options = tuple(self.C.CONTROLS), {c: tuple(self.C.OPTIONS[c]) for c in self.C.CONTROLS}
        self.builder = None

    def begin_episode(self):
        self.builder = self.C.ViewBuilder(self.game.rules) if self.game_id == "snake" else self.C.ViewBuilder()

    def reset(self, seed):
        self.begin_episode()
        return self.L.reset(seed)

    def ctx(self):
        return self.L.ctx()

    def step(self, s, acts):
        return self.L.step(s, acts)

    def done(self, s):
        return self.L.done(s)

    def outcome(self, s):
        return self.L.outcome(s)

    def render(self, s, p_log, hist=None) -> str:
        v = self.C.view_from_runner(self.binding, self.game, s, p_log, self.builder)
        return self.C.render(v)

    def parse(self, text: str) -> dict:
        return view_dict(self.game_id, self.C.parse(text))

    def teacher(self, s, view: dict, text: str | None = None) -> dict:
        assert text is not None, "the contract teacher reads the request text only"
        j = self.T.label(self.C.parse(text))["joint"]
        return {c: j[c] for c in self.controls}


def make(game: str, source: str | None = None):
    source = source or SOURCE
    if game == "booster":                                   # lane booster-student: contract only
        from nagi.burst2._rt.bv2n.data.booster_src import BoosterSource
        return BoosterSource()
    if source == "contract":
        return _Contract(game)
    if game == "snake":
        return _SnakeLegacy()
    if game == "rr":
        return _RRLegacy()
    raise NotImplementedError(f"{game}: no {source} view source yet (Booster waits for its teacher)")
