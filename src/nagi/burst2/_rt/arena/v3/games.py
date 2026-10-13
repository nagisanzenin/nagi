"""Arena v3 game registry: one Binding per game (the GAME contract in arena.v3.contract).

A binding tells the realtime runner, for the focal seat 0: how to build the engine, the controls and their hold
semantics between replies, the environment bots, and how to score a finished record. Rotorwash, Rotorwash-Ramp
(fail-first, 60 s; its own game id, the v2 Rotorwash entry is unchanged) and the test stub are bound now; Booster Landing and Snake bind through the same API when their modules land (imported lazily, so
this file works on branches where they are absent).

Hold semantics (PROTOCOL §1.1.3), per control:
  'persistent'    the last applied value is kept between replies; after EXPIRE_MS without an applied reply it resets
                  to `default[key]` (the safe default) until the next reply.
  'one_shot'      acts only on the tick its reply is applied; otherwise `default[key]` (a neutral 'hold').
  'query_default' between replies the query's own default is applied (the engine's "keep the current setting" /
                  current heading), which the game computes from the state (Snake heading, Booster held settings).
"""
from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

HOLDS = ('persistent', 'one_shot', 'query_default')


@dataclass
class Binding:
    id: str
    make: Callable[[], Any]                      # fresh engine (cheap); the same object serves one round
    controls: tuple[str, ...]
    hold: dict[str, str]
    default: dict[str, str] = field(default_factory=dict)
    env_bot_ids: tuple[str, ...] = ()            # v2 bot ids for seats 1.. (frozen, deterministic)
    float_engine: bool = False                   # True: replay pinned to the recording platform (Rotorwash)
    score: Callable[[dict], dict] | None = None  # record -> {'raw', 'score01', 'survival_s', ...}
    chord_fallback: bool = False                 # engine has no multi_query: build a 1-slot chord from the query
    seed_game: str | None = None                 # seed schedule key when it differs from id (prompt-style arms)

    @property
    def seed_key(self) -> str:
        """The game id whose v3 seed schedule this binding plays (arena_v3_registry.seed_for): its own id, or for a
        text-only arm (docs/nc0: 'booster_gauntlet_p1') the base game's, so every arm plays the SAME seeds."""
        return self.seed_game or self.id

    def __post_init__(self):
        assert set(self.hold) == set(self.controls) and set(self.hold.values()) <= set(HOLDS), self.hold
        for k, h in self.hold.items():
            assert h == 'query_default' or k in self.default, (k, 'needs a safe default')

    def env_bots(self, seed: int) -> dict[int, Any]:
        if not self.env_bot_ids:
            return {}
        from nagi.burst2._rt.arena.v2.bots import make_bot
        bots = {p: make_bot(b) for p, b in enumerate(self.env_bot_ids, start=1)}
        for p, b in bots.items():
            b.bind(p, seed)
        return bots

    def multi_query(self, g, s):
        from nagi.burst2._rt.arena.chord import MultiQuery
        if not self.chord_fallback:
            return g.multi_query(s, 0)
        qs = g.queries(s, 0, {})
        if not qs:
            return None
        assert len(qs) == 1, 'chord fallback is for 1-control games only'
        return MultiQuery(0, qs[0].text, ((qs[0].key, qs[0].options, qs[0].default),))


# ---------------------------------------------------------------------------------------------- scoring
RW_REF_FLOOR = 100.0


def rotorwash_score(rec: dict) -> dict:
    """PROTOCOL §2.1: s = min(1, score / max(score_ref, 100 m)), ref = rw3_mission ghost on the same seed (seat 3)."""
    helis = rec['final']['helis']
    raw, ref = float(helis[0]['score']), float(helis[3]['score'])
    crash = next((e['t_ms'] for e in rec['events'] if e['kind'] == 'crash' and e['player'] == 0), None)
    return {'raw': raw, 'ref': ref, 'score01': min(1.0, raw / max(ref, RW_REF_FLOOR)),
            'survival_s': (crash if crash is not None else rec['duration_ms']) / 1000,
            'cause': helis[0].get('crash_cause'), 'deliveries': helis[0].get('deliveries')}


def stub_score(rec: dict) -> dict:
    from nagi.burst2._rt.arena.v3.stub_game import T_MAX
    raw = float(rec['final']['raw'])
    return {'raw': raw, 'score01': raw / (T_MAX + 10), 'survival_s': rec['final']['k'] * 0.25}


def _engine_score(rec: dict) -> dict:
    """Games whose engine exposes score01 via render_state()['score'] (Booster, Snake) — resolved at admission."""
    fin = rec['final']
    sc = fin.get('score01', fin.get('score'))
    if isinstance(sc, list):
        sc = sc[0]
    return {'raw': fin.get('points', fin.get('raw')), 'score01': None if sc is None else float(sc),
            'survival_s': rec['duration_ms'] / 1000}


# ---------------------------------------------------------------------------------------------- registry
def _rotorwash():
    from nagi.burst2._rt.arena.v2.protocol import LADDER
    from nagi.burst2._rt.arena.v2.variants import GameV2
    return Binding('rotorwash', lambda: GameV2('rotorwash', None, True, True), ('collective', 'cyclic', 'winch'),
                   {'collective': 'one_shot', 'cyclic': 'persistent', 'winch': 'persistent'},
                   {'collective': 'hold', 'cyclic': 'center', 'winch': 'hold'},
                   env_bot_ids=tuple(LADDER['rotorwash'][1:]), float_engine=True, score=rotorwash_score)


def rotorwash_ramp_score(rec: dict) -> dict:
    """Fail-first score (FAIL_FIRST_BRIEF Amendments 1-2) of the focal seat: survival_s (crash time, or the 60 s cap
    when alive = censored), level_at_fail (1..6), game_score (metres + 500 per delivery), ladder_position (T_fail
    mapped piecewise-linearly through the frozen naive / heuristic / planner medians onto 0 / 0.5 / 1, clipped to
    [0, 1.2]) and score01 = ladder_position clipped to [0, 1] (legacy consumers). The decision metric is the paired
    per-seed win rate, computed across players from survival_s and censored."""
    from nagi.burst2._rt.arena.games.rotorwash_ramp import MAX_ROUND_MS, TICK_MS, ladder_position, level_of
    h = rec['final']['helis'][0]
    crash = h.get('t_crash')
    t_ms = crash if crash is not None else MAX_ROUND_MS
    lp = ladder_position(t_ms / 1000)
    return {'raw': t_ms / 1000, 'survival_s': t_ms / 1000, 'censored': crash is None,
            'level_at_fail': level_of(t_ms // TICK_MS), 'game_score': float(h['score']), 'ladder_position': lp,
            'score01': min(1.0, lp), 'cause': h.get('crash_cause'), 'deliveries': h.get('deliveries')}


@dataclass
class _RampBinding(Binding):
    """Rotorwash-Ramp: env ghosts come from arena.games.rotorwash_ramp_bots (v2 bots + the ramp planner)."""

    def env_bots(self, seed: int) -> dict[int, Any]:
        from nagi.burst2._rt.arena.games.rotorwash_ramp_bots import make_ramp_bot
        bots = {p: make_ramp_bot(b) for p, b in enumerate(self.env_bot_ids, start=1)}
        for p, b in bots.items():
            b.bind(p, seed)
        return bots


def _rotorwash_ramp():
    from nagi.burst2._rt.arena.games.rotorwash_ramp import RampGame
    from nagi.burst2._rt.arena.games.rotorwash_ramp_bots import LADDER_IDS
    return _RampBinding('rotorwash_ramp', lambda: RampGame(None, True, True), ('collective', 'cyclic', 'winch'),
                        {'collective': 'one_shot', 'cyclic': 'persistent', 'winch': 'persistent'},
                        {'collective': 'hold', 'cyclic': 'center', 'winch': 'hold'},
                        env_bot_ids=tuple(LADDER_IDS), float_engine=True, score=rotorwash_ramp_score)


def _stub():
    from nagi.burst2._rt.arena.v3.stub_game import StubGame
    return Binding('stub', StubGame, ('thrust', 'steer'), {'thrust': 'one_shot', 'steer': 'persistent'},
                   {'thrust': 'hold', 'steer': 'straight'}, score=stub_score)


def _booster_gauntlet():
    from nagi.burst2._rt.arena.games import booster_gauntlet_arena as BGA   # Booster Gauntlet (fail-first; replaces Booster Landing v1)
    return BGA.v3_binding()


def _booster_gauntlet_prompt(style: str) -> Binding:
    """NC-0 text-only arms (docs/nc0/, NC0_PREREG.md): the Booster Gauntlet binding with the model-facing text of
    prompt style `style` ('p1' clarified facts, 'p2' p1 + derived kinematics). Engine physics, controls, hold
    semantics, safe defaults, scoring and the seed schedule (seed_game) are exactly the base binding's."""
    from nagi.burst2._rt.arena.games import booster_gauntlet as G
    from nagi.burst2._rt.arena.games import booster_gauntlet_arena as BGA
    base = BGA.v3_binding()
    return Binding(f'{base.id}_{style}', lambda: G.BoosterGauntlet(None, True, False, prompt_style=style), base.controls,
                   dict(base.hold), dict(base.default), score=base.score, seed_game=base.id)


def _booster_gauntlet_v31() -> Binding:
    """Arena v3.1 Booster (docs/arena_v31/README.md): rules g1.2 at L0 (L0 prompts byte-identical to g1.1), the K3
    score, the base binding's controls / hold / safe defaults and seed schedule (seed_game 'booster_gauntlet')."""
    from nagi.burst2._rt.arena.games import booster_gauntlet_v31 as BV
    return BV.v31_binding()


def _rotorwash_ramp_v31() -> Binding:
    """Arena v3.1 Rotorwash-Ramp (docs/arena_v31/ROTORWASH_RAMP_V31.md): rules ramp2.1 (no collapse front, 60 s, v3
    roof / storm / power anchors), the K3-RR2.1 score (landings + deliveries + approach checkpoints / touchdown
    credit, no time term), v3 RR's controls / hold / safe defaults and seed schedule (seed_game 'rotorwash_ramp')."""
    from nagi.burst2._rt.arena.games import rotorwash_ramp_v31 as RV
    return RV.v31_binding()


def snake_score(rec: dict) -> dict:
    """SNAKE RUSH fail-first scores (FAIL_FIRST_BRIEF Amendment 1; arena.games.snake_rush_arena.binding_score):
    survival_s, censored, level_at_fail, game_score (food) and score01 = ladder position in [0, 1]."""
    from nagi.burst2._rt.arena.games.snake_rush_arena import binding_score
    return binding_score(rec)


def _snake():
    m = importlib.import_module('nagi.burst2._rt.arena.games.snake_rush')  # Snake Rush (replaces v1 arena.games.snake, 2026-09-27)
    return Binding('snake', lambda: m.SnakeRush(None, True, False), ('move',), {'move': 'query_default'},
                   score=snake_score)


FACTORIES: dict[str, Callable[[], Binding]] = {'rotorwash': _rotorwash, 'stub': _stub,
                                               'booster_gauntlet': _booster_gauntlet,
                                               'snake': _snake, 'rotorwash_ramp': _rotorwash_ramp,
                                               'booster_gauntlet_p1': lambda: _booster_gauntlet_prompt('p1'),
                                               'booster_gauntlet_p2': lambda: _booster_gauntlet_prompt('p2'),
                                               'booster_gauntlet_v31': _booster_gauntlet_v31,
                                               'rotorwash_ramp_v31': _rotorwash_ramp_v31}
# Board 1 suite (owner re-authorization 2026-09-27): the three fail-first games, 60 s cap, 6 levels; stream slot g plays
# SUITE_ORDER[g] (PROTOCOL §1.1.9). Legacy Rotorwash v2 ('rotorwash', 90 s) stays registered, not in the suite; Booster
# Landing v1 ('booster') was rejected by the owner and is no longer registered.
SUITE_ORDER = ('snake', 'rotorwash_ramp', 'booster_gauntlet')


def get(game_id: str) -> Binding:
    return FACTORIES[game_id]()


def available(game_id: str) -> bool:
    try:
        get(game_id)
        return True
    except (ImportError, KeyError):
        return False
