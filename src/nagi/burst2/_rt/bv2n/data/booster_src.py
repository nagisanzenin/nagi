"""Booster view source for the bv2n data collectors (lane booster-student).

Episode = hop 1 of Booster Gauntlet g1.2 from reset(seed), as the teacher gate (scripts/bv2n/booster_c_eval.py):
the round runs while hop 1 is flying; it ends at the hop-1 landing, crash, or hop timeout. Text = the contract's
render(BoosterView) built by bv2n.contract.booster.ViewBuilder from the runner; the student sees view_dict(parse(text));
the teacher is the gated C1 = bv2n.teachers.booster_c.BoosterC() defaults on parse(text) only (not modified here).
Score = hop-1 legal deck landing (0/1); touchdown error E reported when the booster touched the deck.
"""
from __future__ import annotations

import math

from nagi.burst2._rt.arena.games import booster_gauntlet as G
from nagi.burst2._rt.arena.games import booster_gauntlet_v31 as BV
from nagi.burst2._rt.bv2n.contract import booster as CB
from nagi.burst2._rt.bv2n.teachers import booster_c as BC


def view_dict(v: CB.BoosterView) -> dict:
    """JSON form of a parsed BoosterView (its own fields only)."""
    f = v.frame
    fr = {k: getattr(f, k) for k in CB.view_fields()["Frame"]}
    fr["twr"] = list(f.twr)
    return {"game": "booster", "frame": fr, "applied": list(v.applied),
            "act": {"ign_ms": v.act.ign_ms, "fin_out": v.act.fin_out, "fin_defl": v.act.fin_defl},
            "hist": [None if r is None else [getattr(r, k) for k in CB.view_fields()["HistRow"]] for r in v.hist],
            "p_log": dict(zip(CB.CONTROLS, v.applied))}


class BoosterSource:
    game_id, seed_game = "booster", "booster_gauntlet"
    controls = tuple(CB.CONTROLS)

    def __init__(self):
        self.game = G.BoosterGauntlet(None, True, False, rules_version="g1.2")
        self.binding = BV.v31_binding()
        self.options = {c: tuple(CB.OPTIONS[c]) for c in self.controls}
        self.T = BC.BoosterC()                 # frozen C1 defaults (gate PASS 24/24)
        self.builder = None

    def reset(self, seed):
        self.builder = CB.ViewBuilder()
        return self.game.reset(seed)

    def ctx(self):
        return self.game.ctx()

    def step(self, s, acts):
        return self.game.step(s, {0: acts}, G.DECISION_MS)[0]

    def done(self, s) -> bool:
        h = s.boosters[0]
        return self.game.done(s) or h["hop"] != 1 or h["status"] != "flying"

    def render(self, s, p_log, hist=None) -> str:
        return CB.render(CB.view_from_runner(self.game, s, p_log, self.builder))

    def parse(self, text: str) -> dict:
        return view_dict(CB.parse(text))

    def teacher(self, s, view: dict, text: str | None = None) -> dict:
        assert text is not None, "the contract teacher reads the request text only"
        j = self.T.label(CB.parse(text))["joint"]
        return {c: j[c] for c in self.controls}

    def outcome(self, s) -> dict:
        g = self.game
        h = s.boosters[0]
        o = BV.k3_from_state(g, s, 0)
        landed = bool(o["hops"] >= 1)
        out = {"landed": landed, "score": float(landed), "success": landed, "cause": h["cause"] if not landed else None,
               "t_ms": s.t_ms, "E": None, "touchdown": h["td"] is not None}
        td = h["td"]
        if td is not None:
            err = G.touchdown_errors(g.rules, td, g.scenario(s.seed).zone[min(td["k"], G.N_SUB - 1)],
                                     1000 if landed else h["legs"])
            out["E"] = round(float(err["E"]), 4) if math.isfinite(err["E"]) else None
        if not landed and out["cause"] is None:
            out["cause"] = "hop_timeout" if s.t_ms >= 22_000 else "unknown"
        return out
