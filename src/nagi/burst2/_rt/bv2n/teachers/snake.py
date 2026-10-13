"""View-only Snake teacher (LANES teacher API): sr3_planner (arena.games.snake_rush_bots.planner, delay-aware) as a
function of a SnakeView only.

Gated teacher (lane teachers-rs: sr3 vs V1 PASS 12-0-0 on dev): RushBot('sr3_planner') through the realtime runner,
i.e. planner(s, game, game.rules, lag=(p_log move, 1)) under the nominal 1-tick contract. The wrapper rebuilds a
RushState from the view (map walls, food, ordered body, every '+' cell with its due tick, clock, hunger, growth,
heading / next direction); fields the planner never reads (seed, draw counter, streak) get fixed placeholders. The
planner is deterministic: `rng` is accepted for the API and ignored.
"""
from __future__ import annotations

from nagi.burst2._rt.arena.games import snake_rush as S
from nagi.burst2._rt.arena.games import snake_rush_bots as SB
from nagi.burst2._rt.bv2n.contract import snake as CS

SOURCE = "arena.games.snake_rush_bots.planner(depth=8, lag=(p_log, 1))"
_GAME = None


def game():
    global _GAME
    if _GAME is None:
        from nagi.burst2._rt.arena.v3.games import FACTORIES
        _GAME = FACTORIES["snake"]().make()
    return _GAME


def state_of(view: CS.SnakeView) -> S.RushState:
    g, o = CS.grid(view.obs), CS.info(view.obs)
    t = o["tick"]
    walls = bytes(1 if ch == "#" else 0 for ch in g)
    food = [c for c, ch in enumerate(g) if ch == "*"]
    poison = [c for c, ch in enumerate(g) if ch == "x"]
    return S.RushState(seed=0, tick=t, body=view.body, heading=o["heading"], grow=o["grow"],
                       food=food[0] if food else -1, poison=poison[0] if poison else -1, walls=walls,
                       sched=tuple(sorted((t + d, c) for c, d in view.warned)), hunger=o["hunger"], alive=True,
                       eaten=o["eaten"], streak=0, last_eat=-1, k=0, died_tick=-1, cause="", dir=o["dir"])


def act(view: CS.SnakeView, rng=None) -> dict:
    gm = game()
    mv = SB.planner(state_of(view), gm, gm.rules, lag=(S.DNAME.index(view.applied[0]), 1))
    return {"move": mv}


def label(view: CS.SnakeView) -> dict:
    j = act(view)
    return {"joint": j, "targets": {"move": {o: float(o == j["move"]) for o in S.DNAME}}}
