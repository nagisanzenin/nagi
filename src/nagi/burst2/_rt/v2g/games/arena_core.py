"""Rotorwash-Ramp (RR) and Booster Gauntlet routes of the SDK ``operate()`` (plumbing for gate I; lanes/runtime.md §6).

There is no search pack for these games (no fast exact forward model on the client view, lanes/runtime.md §6), so the
decision is the frozen candidate policy that the M4 Arena runner already plays (scripts/v2g/m4_arena.py,
RUNBOOK_M4 B2): the core's game head (``v2g.core.multi_core``) on the parsed served request, ONE forward per tick,
per-slot argmax = ``GamePolicy(core, game).act(view)``. This module only routes requests to that policy; it adds no
decision logic and changes no frozen config.

    out = operate(request_text, None, {"core": MultiCore})      # text path (exact parse, fail closed)
    out = operate_structured("rr" | "booster", view, {"core": c})  # structured path (the runner's view dict)

Request match (``match_request``): the served chord prompt's STATE block starts with the game's rules header, and the
text must re-render byte-identically from its parse (``render(parse(text)) == text``), else no match.
Output (same keys as the Zoo / Snake routes):
    choice              {control: option} = GamePolicy.act(view) (per-slot argmax of the head's logits)
    joint               mixed-radix joint id of that choice (first control most significant, the data-lane encoding)
    probabilities       {control: {option: p}}: per-slot softmax of the head (the factorized joint's marginals)
    joint_probabilities {joint id: p}: softmax of the head's factorized joint logits (``multi_core.joint_logits``)
    stats               game, read_ms, total_ms, core_ms, pick = "per-slot argmax" (the choice stream is not used:
                        the frozen policy is deterministic, so text and structured paths draw the same joint for any
                        stream)
"""

from __future__ import annotations

import time

import numpy as np

GAMES = ("rr", "booster")
# literal prechecks (tested equal to the contract constants) so a Zoo request never imports the game engines
_HEAD = {"rr": "\nSTATE:\nROTORWASH RAMP (rules ramp2.1)", "booster": "\nSTATE:\nBOOSTER GAUNTLET (rules "}


def _contract(game: str):
    import importlib  # noqa: PLC0415

    return importlib.import_module(f"nagi.burst2._rt.bv2n.contract.{game}")


def match_request(text: str):
    """CoreGameMachine when ``text`` is an exact served RR / Booster request, else None."""
    for game in GAMES:
        if _HEAD[game] in text:
            C = _contract(game)
            try:
                ok = C.render(C.parse(text)) == text
            except (ValueError, KeyError, IndexError, AssertionError):
                ok = False
            if ok:
                return CoreGameMachine(game)
    return None


class CoreGameMachine:
    kind = "game"

    def __init__(self, game: str):
        if game not in GAMES:
            raise ValueError(f"no core-head route for game {game!r}")
        from nagi.burst2._rt.bv2n.data import views as VW  # noqa: PLC0415
        from nagi.burst2._rt.bv2n.student import features as F  # noqa: PLC0415

        self.game = game
        self.vs = VW.make(game)
        self.sp = F.SPEC[game]
        if game == "rr":
            self.controls = tuple(F.RR_CONTROLS)
            self.options = {c: tuple(F.RR_OPTIONS[c]) for c in self.controls}
        else:
            from nagi.burst2._rt.bv2n.student import booster_features as BF  # noqa: PLC0415

            self.controls = tuple(BF.CONTROLS)
            self.options = {c: tuple(BF.OPTIONS[c]) for c in self.controls}
        self.machine_id = f"game:{game}:core-head"
        self.read_via = "exact"

    def parse(self, text: str) -> dict:
        """Parsed served request -> view dict (the same dict the Arena runner's policy receives)."""
        return self.vs.parse(text)

    def decide(self, view: dict, core) -> tuple[dict, list]:
        """(choice dict, per-slot logits) of the frozen policy. The choice is GamePolicy(core, game).act(view)."""
        from nagi.burst2._rt.v2g.core.multi_core import game_forward  # noqa: PLC0415

        # the two lines of GamePolicy.act (test: equal to it on every checked request)
        x = np.asarray(self.sp["x"](view), np.float32).astype(np.float16).astype(np.float32)[None]  # = training rows
        slot, _v = game_forward(core.params, core.config, self.game, x)
        return self.sp["joint"](view, [int(lg[0].argmax()) for lg in slot]), slot

    def operate(self, view: dict, options: dict, t0: float, read_ms: float = 0.0) -> dict:
        from nagi.burst2._rt.v2g.core.multi_core import joint_logits  # noqa: PLC0415

        core = (options or {}).get("core")
        if core is None or not hasattr(core, "params"):
            raise ValueError(f"{self.game}: operate() needs options['core'] = the MultiCore checkpoint (no search "
                             "pack exists for this game)")
        tc = time.perf_counter()
        choice, slot = self.decide(view, core)
        core_ms = (time.perf_counter() - tc) * 1e3
        sizes = [int(lg.shape[1]) for lg in slot]
        idx = [self.options[c].index(choice[c]) for c in self.controls]
        joint = 0
        for i, n in zip(idx, sizes):
            joint = joint * n + i
        J = joint_logits(slot)[0].astype(np.float64)
        e = np.exp(J - J.max())
        pj = e / e.sum()
        probs = {}
        for c, lg in zip(self.controls, slot):
            z = lg[0].astype(np.float64)
            q = np.exp(z - z.max())
            q = q / q.sum()
            probs[c] = {o: float(p) for o, p in zip(self.options[c], q)}
        stats = {"game": self.game, "read_ms": read_ms, "core_ms": core_ms,
                 "total_ms": (time.perf_counter() - t0) * 1e3, "machine_id": self.machine_id,
                 "read_via": self.read_via, "pick": "per-slot argmax (frozen core-head policy; stream unused)",
                 "sims": 0, "depth": 0, "gated": False}
        return {"choice": dict(choice), "joint": int(joint), "probabilities": probs,
                "joint_probabilities": {int(j): float(p) for j, p in enumerate(pj)}, "stats": stats}

    def operate_request(self, text: str, options: dict, t0: float) -> dict:
        tr = time.perf_counter()
        view = self.parse(text)
        return self.operate(view, options, t0, (time.perf_counter() - tr) * 1e3)

