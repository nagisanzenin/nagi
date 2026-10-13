"""Arena Live core: the Game protocol, the Referee and the replay log. See docs/arena_live/DESIGN.md.

Every game is a pure, deterministic state machine. Only the Referee touches clocks and agents:
  * all queries of one decision point are issued at the same instant (simultaneous, no move order);
  * a reply later than the deadline (real-time mode), or an invalid reply, applies the query's
    documented default, the same rule for every agent;
  * the replay log records every query text, option list, reply, latency and a per-tick state hash,
    so a run can be re-verified offline without any model.
Two clock modes: 'lockstep' (quality: the game waits for every reply) and 'realtime' (deadline =
the game's decision period unless overridden; replies are awaited in parallel on a wall clock).
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Protocol, Sequence

MAX_OPTIONS = 26
TOKEN_CAP = 768  # Nagi-ENORMOUS trained range (Qwen3.8 tokens); enforced by the conformance kit


@dataclass(frozen=True)
class Query:
    """One closed-choice question to one player. `options` are semantic ids in canonical order."""

    player: int
    key: str  # which control this answers, e.g. 'move', 'collective', 'rotation'
    text: str
    options: tuple[str, ...]
    default: str

    def __post_init__(self):
        assert 2 <= len(self.options) <= MAX_OPTIONS, (self.key, len(self.options))
        assert len(set(self.options)) == len(self.options), self.options
        assert self.default in self.options, (self.default, self.options)


@dataclass(frozen=True)
class Event:
    t_ms: int
    kind: str  # 'eliminated', 'near_miss', 'lines_sent', 'hooked', 'delivered', 'crash', 'round_end', ...
    player: int | None = None
    data: dict = field(default_factory=dict)


class Game(Protocol):
    id: str
    n_players: int
    decision_period_ms: int
    max_round_ms: int

    def reset(self, seed: int) -> Any: ...

    def queries(self, s: Any, player: int, answers: dict[str, str]) -> list[Query]:
        """Queries for `player` at this decision point. Multi-stage games (Stack Attack: rotation then
        column) receive the answers already given in this decision point; return [] when done."""

    def step(self, s: Any, actions: dict[int, dict[str, str]], dt_ms: int) -> tuple[Any, list[Event]]: ...

    def done(self, s: Any) -> bool: ...

    def ranking(self, s: Any) -> list[list[int]]:
        """Best first; players in one inner list are tied."""

    def render_state(self, s: Any) -> dict: ...

    def state_hash(self, s: Any) -> str: ...


class Agent(Protocol):
    name: str

    def choose(self, query: Query) -> str:
        """Return one of query.options (anything else counts as invalid -> default)."""


# ---------------------------------------------------------------- agents for tests and dry runs


class FakeAgent:
    """Deterministic scripted agent: `policy(query) -> option`, optional fixed delay in seconds."""

    def __init__(self, name: str, policy: Callable[[Query], str] | None = None, delay_s: float = 0.0, seed: int = 0):
        self.name, self.delay_s = name, delay_s
        self._rng = random.Random(seed)
        self._policy = policy or (lambda q: self._rng.choice(q.options))

    def choose(self, query: Query) -> str:
        if self.delay_s:
            time.sleep(self.delay_s)
        return self._policy(query)


# ---------------------------------------------------------------- referee


@dataclass
class Decision:
    t_ms: int
    player: int
    key: str
    options: tuple[str, ...]
    text_sha256: str
    reply: str | None
    applied: str
    default: str
    latency_ms: float | None
    status: str  # 'ok' | 'late' | 'invalid' | 'error'


class Referee:
    def __init__(self, game: Game, agents: Sequence[Agent], mode: str = "lockstep",
                 deadline_ms: float | None = None, log_text: bool = True):
        assert mode in ("lockstep", "realtime") and len(agents) == game.n_players
        self.game, self.agents, self.mode, self.log_text = game, list(agents), mode, log_text
        self.deadline_ms = deadline_ms if deadline_ms is not None else game.decision_period_ms
        self._pool = ThreadPoolExecutor(max_workers=max(4, 4 * game.n_players))

    def _ask(self, qs: list[Query]) -> list[tuple[str | None, float | None, str]]:
        def call(q: Query):
            t0 = time.perf_counter()
            try:
                r = self.agents[q.player].choose(q)
                return r, (time.perf_counter() - t0) * 1000, None
            except Exception as e:  # an agent error is that agent's default, never a crash of the game
                return None, (time.perf_counter() - t0) * 1000, repr(e)[:200]

        futs = [self._pool.submit(call, q) for q in qs]  # all issued at the same instant
        timeout = None if self.mode == "lockstep" else self.deadline_ms / 1000
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
        t, decisions, events, frames = 0, [], [], []
        texts: dict[str, str] = {}
        frames.append({"t_ms": 0, "hash": g.state_hash(s), "render": g.render_state(s)})
        while not g.done(s) and t < g.max_round_ms:
            actions: dict[int, dict[str, str]] = {p: {} for p in range(g.n_players)}
            pending = {p: g.queries(s, p, {}) for p in range(g.n_players)}
            while any(pending.values()):  # stages: every player's stage k is asked simultaneously
                qs = [q for p in pending for q in pending[p]]
                for q, (reply, lat, status) in zip(qs, self._ask(qs)):
                    if status == "ok" and reply not in q.options:
                        status = "invalid"
                    applied = reply if status == "ok" else q.default
                    actions[q.player][q.key] = applied
                    h = hashlib.sha256(q.text.encode()).hexdigest()
                    if self.log_text:
                        texts[h] = q.text
                    decisions.append(Decision(t, q.player, q.key, q.options, h, reply, applied, q.default, lat, status))
                pending = {p: g.queries(s, p, actions[p]) for p in range(g.n_players)}
            s, ev = g.step(s, actions, g.decision_period_ms)
            t += g.decision_period_ms
            events += ev
            frame = {"t_ms": t, "hash": g.state_hash(s), "render": g.render_state(s)}
            frames.append(frame)
            if on_tick:
                on_tick(frame)
        return {"game": g.id, "seed": seed, "mode": self.mode, "deadline_ms": self.deadline_ms,
                "agents": [a.name for a in self.agents], "ranking": g.ranking(s), "duration_ms": t,
                "decisions": [asdict(d) for d in decisions], "events": [asdict(e) for e in events],
                "frames": frames, "texts": texts}


def replay_actions(game: Game, record: dict) -> list[str]:
    """Re-run a recorded round from its applied actions only; returns per-tick state hashes."""
    s = game.reset(record["seed"])
    by_t: dict[int, dict[int, dict[str, str]]] = {}
    for d in record["decisions"]:
        by_t.setdefault(d["t_ms"], {}).setdefault(d["player"], {})[d["key"]] = d["applied"]
    hashes, t = [game.state_hash(s)], 0
    while not game.done(s) and t < game.max_round_ms:
        acts = {p: by_t.get(t, {}).get(p, {}) for p in range(game.n_players)}
        s, _ = game.step(s, acts, game.decision_period_ms)
        t += game.decision_period_ms
        hashes.append(game.state_hash(s))
    return hashes


def canonical_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
