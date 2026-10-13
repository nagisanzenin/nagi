"""Nagi-Chord (docs/chord/P0_ARENA.md): MultiQuery, per-player 'kcall' / 'chord' tick modes, the chord Referee.

A chord tick asks ONE request per player for all K controls and applies the K answers in the same tick, with exactly
the K-query path's semantics. This module is additive: the v1 sources (core.py, conformance.py, agents_nagi.py and
the three engines) are frozen evidence (tests/test_arena_v2.py::test_v1_sources_untouched) and are not edited; the
chord adapters of the engines live in arena.games.chord, and GameV2 exposes them with the v2 text rewrite.
"""
from __future__ import annotations

import hashlib
import random
import time
from concurrent.futures import wait
from dataclasses import asdict, dataclass
from typing import Any, Callable, Sequence

from nagi.burst2._rt.arena.core import MAX_OPTIONS, Decision, Game, Referee

TICK_MODES = ("kcall", "chord")


@dataclass(frozen=True)
class MultiQuery:
    """Chord tick: ONE request in which one player sets K controls at once (docs/chord/P0_ARENA.md).

    `controls` is a tuple of (key, options, default) in the game's canonical control order; every slot obeys the
    Query rules (2..26 unique options, default among them). `text` is the shared state text (no per-control
    'Choose ...' line; the controls block is rendered from `controls`). The answers are applied in the same tick with
    exactly the K-query path's semantics (Game.chord_apply resolves cross-slot validity, e.g. Stack's column range
    depends on the chosen rotation)."""

    player: int
    text: str
    controls: tuple[tuple[str, tuple[str, ...], str], ...]

    def __post_init__(self):
        assert 1 <= len(self.controls) <= MAX_OPTIONS, len(self.controls)
        keys = [c[0] for c in self.controls]
        assert len(set(keys)) == len(keys), keys
        for key, options, default in self.controls:
            assert isinstance(options, tuple), (key, type(options))
            assert 2 <= len(options) <= MAX_OPTIONS, (key, len(options))
            assert len(set(options)) == len(options), options
            assert default in options, (key, default, options)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(c[0] for c in self.controls)

    @property
    def defaults(self) -> dict[str, str]:
        return {k: d for k, _, d in self.controls}

    def options_of(self, key: str) -> tuple[str, ...]:
        return next(o for k, o, _ in self.controls if k == key)


class FakeChordAgent:
    """Scripted chord agent: `policy(mq) -> {key: option}` in one call (default: seeded random per slot)."""

    tick_mode = "chord"

    def __init__(self, name: str, policy: Callable[[MultiQuery], dict] | None = None, delay_s: float = 0.0,
                 seed: int = 0):
        self.name, self.delay_s, self.calls = name, delay_s, 0
        self._rng = random.Random(seed)
        self._policy = policy or (lambda mq: {k: self._rng.choice(o) for k, o, _ in mq.controls})

    def choose_multi(self, mq: MultiQuery) -> dict:
        self.calls += 1
        if self.delay_s:
            time.sleep(self.delay_s)
        return self._policy(mq)


def resolve_tick_modes(agents: Sequence, tick_modes: Sequence[str] | None) -> list[str]:
    """Per-player tick mode: explicit `tick_modes`, else each agent's `tick_mode` attribute, else 'kcall'."""
    modes = list(tick_modes) if tick_modes is not None else [getattr(a, "tick_mode", "kcall") for a in agents]
    assert len(modes) == len(agents) and all(m in TICK_MODES for m in modes), modes
    for a, m in zip(agents, modes):
        assert m == "kcall" or callable(getattr(a, "choose_multi", None)), f"{getattr(a, 'name', a)}: no choose_multi"
    return modes


def chord_slots(g: Any, s: Any, mq: MultiQuery, reply: Any, status: str) -> list[tuple[str, Any, str, str]]:
    """(key, reply, applied, status) per slot of one chord reply, with the K-query path's rules: a slot whose
    reply is not one of its options is 'invalid'; an agent error / late reply makes every slot fall back. Fallback
    slots are passed to the game's `chord_apply(s, player, {key: valid reply or None})`, which returns the value the
    K-query path would apply given the other slots (Stack: the default column of the CHOSEN rotation) and may also
    reject a reply that is valid for the slot list but not for the other slots (Stack: column out of range for the
    chosen rotation -> status 'invalid', exactly as an out-of-range reply to the K-path column query). Games without
    `chord_apply` have independent slots: a fallback slot takes its MultiQuery default."""
    is_dict = isinstance(reply, dict)
    out = {}
    for key, options, _ in mq.controls:
        r = reply.get(key) if is_dict else None
        if status != "ok":
            out[key] = [r, None, status]
        elif not is_dict or r not in options:
            out[key] = [r, None, "invalid"]
        else:
            out[key] = [r, r, "ok"]
    apply = chord_apply_fn(g)
    if apply is not None:
        fixed = apply(s, mq.player, {k: v[1] for k, v in out.items()})
        for k, v in out.items():
            if v[1] is not None and fixed[k] != v[1]:
                v[2] = "invalid"
            v[1] = fixed[k]
    else:
        for k, _, default in mq.controls:
            if out[k][1] is None:
                out[k][1] = default
    return [(k, v[0], v[1], v[2]) for k, v in out.items()]


def multi_query(g: Any, s: Any, player: int) -> "MultiQuery | None":
    """The game's chord request: its own multi_query (GameV2) or the arena.games.chord adapter of a v1 engine."""
    fn = getattr(g, "multi_query", None)
    if fn is not None:
        return fn(s, player)
    from nagi.burst2._rt.arena.games.chord import adapter
    return adapter(g).multi_query(g, s, player)


def chord_apply_fn(g: Any):
    """The game's cross-slot rule (Stack), or None for independent slots."""
    fn = getattr(g, "chord_apply", None)
    if fn is not None or hasattr(g, "multi_query"):
        return fn
    from nagi.burst2._rt.arena.games.chord import adapter
    ad = adapter(g)
    return None if ad.chord_apply is None else (lambda s, p, a: ad.chord_apply(g, s, p, a))


def has_chord(g: Any) -> bool:
    if hasattr(g, "multi_query"):
        return True
    from nagi.burst2._rt.arena.games.chord import adapter
    try:
        adapter(g)
        return True
    except KeyError:
        return False


class ChordReferee(Referee):
    """arena.core.Referee with chord support (core.Referee itself is frozen v1 source and stays the K-call path).
    `tick_modes` (per player, 'kcall' | 'chord'; default: each agent's `tick_mode` attribute, else 'kcall') selects
    per player whether a tick is asked as the game's per-control Query stages (K calls, the v1/v2 path) or as ONE
    MultiQuery (one call, all controls applied in the same tick). Players of both modes can share a round: every
    player's first stage and every chord request are issued at the same instant. With all players 'kcall' and no
    explicit `tick_modes` the loop and the record are exactly core.Referee's (v1); otherwise the record also carries
    `tick_modes` and per-tick `tick_stats` (calls and latency per player)."""

    def __init__(self, game: Game, agents: Sequence[Agent], mode: str = "lockstep",
                 deadline_ms: float | None = None, log_text: bool = True, tick_modes: Sequence[str] | None = None):
        super().__init__(game, agents, mode=mode, deadline_ms=deadline_ms, log_text=log_text)
        self.tick_modes = resolve_tick_modes(self.agents, tick_modes)
        self._chord_record = tick_modes is not None or "chord" in self.tick_modes
        if "chord" in self.tick_modes:
            assert has_chord(game), f"{game.id}: no chord (multi_query) support"

    def _submit_chord(self, mqs: list[MultiQuery]) -> list:
        def call(mq: MultiQuery):
            t0 = time.perf_counter()
            try:
                r = self.agents[mq.player].choose_multi(mq)
                return r, (time.perf_counter() - t0) * 1000, None
            except Exception as e:  # an agent error is that agent's defaults, never a crash of the game
                return None, (time.perf_counter() - t0) * 1000, repr(e)[:200]

        return [self._pool.submit(call, mq) for mq in mqs]

    def _collect_chord(self, futs: list, t_issue: float) -> list[tuple[Any, float | None, str]]:
        timeout = None if self.mode == "lockstep" else max(0.0, self.deadline_ms / 1000 - (time.perf_counter() - t_issue))
        wait(futs, timeout=timeout)
        out = []
        for f in futs:
            if not f.done():
                out.append((None, None, "late"))
                continue
            r, lat, err = f.result()
            if err:
                out.append((None, lat, "error"))
            elif self.mode == "realtime" and lat > self.deadline_ms:
                out.append((r, lat, "late"))
            else:
                out.append((r, lat, "ok"))
        return out

    def play(self, seed: int, on_tick: Callable[[dict], None] | None = None) -> dict:
        g = self.game
        s = g.reset(seed)
        t, decisions, events, frames, tick_stats = 0, [], [], [], []
        texts: dict[str, str] = {}
        chord = [p for p in range(g.n_players) if self.tick_modes[p] == "chord"]
        frames.append({"t_ms": 0, "hash": g.state_hash(s), "render": g.render_state(s)})
        while not g.done(s) and t < g.max_round_ms:
            actions: dict[int, dict[str, str]] = {p: {} for p in range(g.n_players)}
            stats = {p: {"calls": 0, "latency_ms": 0.0, "latency_sum_ms": 0.0} for p in range(g.n_players)}
            pending = {p: ([] if p in chord else g.queries(s, p, {})) for p in range(g.n_players)}
            mqs = [mq for mq in (multi_query(g, s, p) for p in chord) if mq is not None]
            chord_futs, t_issue = self._submit_chord(mqs), time.perf_counter()  # same instant as stage 1
            first = True
            while any(pending.values()) or first:  # stages: every player's stage k is asked simultaneously
                qs = [q for p in pending for q in pending[p]]
                rows: dict[int, list] = {}
                stage_max: dict[int, float] = {}
                for q, (reply, lat, status) in zip(qs, self._ask(qs) if qs else []):
                    if status == "ok" and reply not in q.options:
                        status = "invalid"
                    applied = reply if status == "ok" else q.default
                    actions[q.player][q.key] = applied
                    h = hashlib.sha256(q.text.encode()).hexdigest()
                    if self.log_text:
                        texts[h] = q.text
                    rows.setdefault(q.player, []).append(
                        Decision(t, q.player, q.key, q.options, h, reply, applied, q.default, lat, status))
                    stats[q.player]["calls"] += 1
                    stats[q.player]["latency_sum_ms"] += lat or 0.0
                    stage_max[q.player] = max(stage_max.get(q.player, 0.0), lat or 0.0)
                for p, m in stage_max.items():
                    stats[p]["latency_ms"] += m
                if first:
                    for mq, (reply, lat, status) in zip(mqs, self._collect_chord(chord_futs, t_issue)):
                        h = hashlib.sha256(mq.text.encode()).hexdigest()
                        if self.log_text:
                            texts[h] = mq.text
                        defaults = mq.defaults
                        for key, r, applied, st in chord_slots(g, s, mq, reply, status):
                            actions[mq.player][key] = applied
                            rows.setdefault(mq.player, []).append(Decision(
                                t, mq.player, key, mq.options_of(key), h, r, applied, defaults[key], lat, st))
                        stats[mq.player].update(calls=1, latency_ms=lat or 0.0, latency_sum_ms=lat or 0.0)
                    first = False
                for p in sorted(rows):
                    decisions += rows[p]
                pending = {p: ([] if p in chord else g.queries(s, p, actions[p])) for p in range(g.n_players)}
            if self._chord_record:
                tick_stats += [{"t_ms": t, "player": p, "mode": self.tick_modes[p], **{
                    k: (round(v, 3) if isinstance(v, float) else v) for k, v in stats[p].items()}}
                    for p in range(g.n_players) if stats[p]["calls"]]
            s, ev = g.step(s, actions, g.decision_period_ms)
            t += g.decision_period_ms
            events += ev
            frame = {"t_ms": t, "hash": g.state_hash(s), "render": g.render_state(s)}
            frames.append(frame)
            if on_tick:
                on_tick(frame)
        rec = {"game": g.id, "seed": seed, "mode": self.mode, "deadline_ms": self.deadline_ms,
               "agents": [a.name for a in self.agents], "ranking": g.ranking(s), "duration_ms": t,
               "decisions": [asdict(d) for d in decisions], "events": [asdict(e) for e in events],
               "frames": frames, "texts": texts}
        if self._chord_record:
            from nagi.burst2._rt.arena.replay_platform import platform_stamp
            rec["tick_modes"] = list(self.tick_modes)
            rec["tick_stats"] = tick_stats
            rec["platform"] = platform_stamp()  # float games replay bit-exactly on the same platform only
        return rec
