"""Arena v3 contracts: the PLAYER (agent) interface and the GAME binding interface (docs/arena_v3/PROTOCOL.md §1.1).

Every Arena v3 player (Nagi K-call / Chord, SemIf-4B, CLM-8B, Jev) plugs into the realtime runner
(`arena.v3.runner`) ONLY through `V3Agent` below. `check_agent()` is the conformance test every adapter must pass on
CPU with mocks before any GPU/API job (the adapters live in ~/nagi-wt/arena-v3-agents; they import this module and
must not change it).

=== PLAYER CONTRACT (V3Agent) =====================================================================================

Identity / serving (read once per cell, copied into the registry cell, scripts/arena_v3_registry.py):
  player_id      '<weights>/<interface>', e.g. 'enormous_old/kcall', 't_dual/chord', 'clm_8b/kcall_batched',
                 'jev/vendor_single'. Lower-case [a-z0-9_.-]/[a-z0-9_].
  kind           'nagi' (our weights) | 'selfhosted' (third-party weights we serve on H100!) | 'api' (vendor API).
  interface      'kcall'         answer req.queries in order, ONE model call per query (K sequential calls);
                 'chord'         ONE model call on req.multi answering all K controls;
                 'kcall_batched' ONE batched model call scoring all K queries (K prompts in one batch/request);
                 'vendor_single' ONE API request carrying all K controls.
                 Declared before play; never switched inside a cell.
  serving_info() dict with at least: gpu ('H100' or None for api), weights_format ('merged-bf16' | 'bf16' | None),
                 kernels ('fused' | 'sdpa' | 'eager' | 'vllm' | None), sdk (package@commit or version), weights_sha256
                 (64-hex or None for api), vendor ({'name', 'version'} or None for nagi), image_sha256 (or None
                 until pinned), client_region (api only), concurrency_mode ('serial' = one forward at a time behind
                 a lock | 'batched' = concurrent requests batched by the server | 'remote' = vendor API).

The call the runner makes (from up to `max_concurrency` = 3 stream threads AT THE SAME TIME):
  coverage(req) -> {'tokens': int, 'limit': int, 'truncated': False}   (fail-closed pre-check, timed as part of the
                 decision; any truncation or error -> the runner voids the round, PROTOCOL R3.17)
  decide(req)   -> DecisionResult. MUST be thread-safe. MUST be deterministic for identical requests (greedy argmax /
                 temperature 0 / the vendor's deterministic setting; ties -> the FIRST option in the query's
                 canonical order). MUST answer every key of req.queries with one of that query's options (a missing
                 or invalid key gets the query default and is logged 'invalid'). On failure RAISE (one attempt, no
                 retries inside the agent, fixed timeout for APIs): the runner logs the error and applies nothing.
  warmup(reqs)  -> None. Called before the latency probe; >= 20 decisions on dev-split requests. Not recorded as play.
  fingerprint() -> 64-hex sha of the answers to 8 fixed dev requests (api players; others may return None).
  close()       -> None.

What the agent sees (DecisionRequest) is ONLY the observation: stream slot, game id, observed tick, the K control
queries and (if the game supports chord) the MultiQuery of the same state. It is NEVER told whether a request is a
live round or a filler request, nor the seed index, nor the wall clock: the runner keeps those. An agent must not
infer or branch on them (PROTOCOL AG5/AG8; filler and live requests are drawn from the same distribution).

Latency is measured by the RUNNER on the serving path (submit -> result available), per stream; the agent's own
prepare_ms / infer_ms are informational. KV-prefix caching or continuous batching are allowed only if declared in
serving_info and identical for live and filler requests.

=== GAME CONTRACT (V3GameBinding, arena.v3.games) ================================================================

A game is registered by a binding that exposes, for the focal seat 0:
  id, rules_id, decision_period_ms, max_round_ms, controls (canonical order), hold[key] in {'persistent',
  'one_shot'}, default[key] (the safe default), make() -> engine, env_bots(seed) -> {seat: bot} (frozen, deterministic,
  never reacting to the model is preferred), alive(s), queries(s) (all K independent queries of seat 0 at once),
  multi_query(s) (or None), step(s, actions, dt_ms), done(s), state_hash(s), render_state(s), raw_score(s, seed) and
  score01(s, seed) in [0, 1] (the game's frozen ladder normalisation, PROTOCOL §2.1 / G2).
Engines keep the v2 Game API (arena.core.Game): reset / queries / step / done / ranking / render_state / state_hash.
"""
from __future__ import annotations

import concurrent.futures as cf
import dataclasses
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable

from nagi.burst2._rt.arena.chord import MultiQuery
from nagi.burst2._rt.arena.core import Query

CONTRACT_VERSION = 'arena-v3-agent-1'
KINDS = ('nagi', 'selfhosted', 'api')
INTERFACES = ('kcall', 'chord', 'kcall_batched', 'vendor_single')
KERNELS = ('fused', 'sdpa', 'eager', 'vllm', None)
CONCURRENCY_MODES = ('serial', 'batched', 'remote')
PLAYER_ID = re.compile(r'^[a-z0-9_.-]+/[a-z0-9_]+$')
HEX64 = re.compile(r'^[0-9a-f]{64}$')


@dataclass(frozen=True)
class DecisionRequest:
    """One decision of one stream: the K control queries of ONE state (and its chord form)."""
    stream: int                              # stream slot 0..2 (slot g plays game g of the suite order)
    game: str                                # game id, e.g. 'rotorwash'
    obs_tick: int                            # tick index of the observed state (per stream clock)
    queries: tuple[Query, ...]               # seat-0 control queries, canonical control order, all independent
    multi: MultiQuery | None = None          # the same state as ONE chord request (None if the game has no chord)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(q.key for q in self.queries)


@dataclass
class DecisionResult:
    choices: dict[str, str]                                    # key -> option
    probs: dict[str, dict[str, float]] | None = None           # key -> {option: p} (sums to 1 per key) or None
    prepare_ms: float | None = None                            # agent-side: render / tokenize / coverage
    infer_ms: float | None = None                              # agent-side: model call(s) / HTTP round trip
    calls: int = 1                                             # forwards or API requests used for this decision
    meta: dict = field(default_factory=dict)                   # e.g. input_tokens, server_ms, http_status


@runtime_checkable
class V3Agent(Protocol):
    player_id: str
    kind: str
    interface: str
    max_concurrency: int

    def serving_info(self) -> dict: ...

    def coverage(self, req: DecisionRequest) -> dict: ...

    def decide(self, req: DecisionRequest) -> DecisionResult: ...

    def warmup(self, reqs: Sequence[DecisionRequest]) -> None: ...

    def fingerprint(self) -> str | None: ...

    def close(self) -> None: ...


class ContractError(AssertionError):
    pass


def validate_result(req: DecisionRequest, res: DecisionResult) -> list[str]:
    """Problems with one result (empty = valid). The runner applies the default for an invalid key."""
    errs = []
    if not isinstance(res, DecisionResult):
        return [f'decide() must return DecisionResult, got {type(res).__name__}']
    opts = {q.key: q.options for q in req.queries}
    for k in opts:
        if k not in res.choices:
            errs.append(f'missing choice for {k!r}')
        elif res.choices[k] not in opts[k]:
            errs.append(f'{k!r}: {res.choices[k]!r} not in {opts[k]}')
    extra = set(res.choices) - set(opts)
    if extra:
        errs.append(f'unknown keys {sorted(extra)}')
    if res.probs is not None:
        for k, p in res.probs.items():
            if k not in opts or set(p) != set(opts[k]) or abs(sum(p.values()) - 1) > 1e-5:
                errs.append(f'{k!r}: probabilities must cover exactly the options and sum to 1')
    return errs


def check_agent(agent: Any, requests: Sequence[DecisionRequest], concurrency: int = 3) -> dict:
    """CPU conformance test for an adapter (run it with a mock model). Raises ContractError on the first failure;
    returns a small summary on success."""
    def need(cond, msg):
        if not cond:
            raise ContractError(msg)
    need(isinstance(agent, V3Agent), 'agent does not implement V3Agent (attributes/methods)')
    need(PLAYER_ID.match(str(agent.player_id)) is not None, f'player_id {agent.player_id!r}')
    need(agent.kind in KINDS, f'kind {agent.kind!r} not in {KINDS}')
    need(agent.interface in INTERFACES, f'interface {agent.interface!r} not in {INTERFACES}')
    need(agent.player_id.split('/')[1] == agent.interface, 'player_id suffix must equal the interface')
    need(isinstance(agent.max_concurrency, int) and agent.max_concurrency >= concurrency,
         f'max_concurrency must be >= {concurrency}')
    info = agent.serving_info()
    for f in ('gpu', 'weights_format', 'kernels', 'sdk', 'weights_sha256', 'vendor', 'image_sha256',
              'client_region', 'concurrency_mode'):
        need(f in info, f'serving_info missing {f!r}')
    need(info['concurrency_mode'] in CONCURRENCY_MODES, f'concurrency_mode {info["concurrency_mode"]!r}')
    need(info['kernels'] in KERNELS, f'kernels {info["kernels"]!r}')
    if agent.kind == 'nagi':
        need(info['vendor'] is None and HEX64.match(str(info['weights_sha256'] or '')), 'nagi: weights sha, no vendor')
    if agent.kind == 'selfhosted':
        need(isinstance(info['vendor'], dict) and HEX64.match(str(info['weights_sha256'] or '')),
             'selfhosted: vendor {name, version} + weights sha')
    if agent.kind == 'api':
        need(isinstance(info['vendor'], dict) and info['weights_sha256'] is None and info['client_region'],
             'api: vendor {name, version}, no weights sha, client_region')
    if agent.interface == 'chord':
        need(all(r.multi is not None for r in requests), 'chord agent needs requests with multi')
    agent.warmup(list(requests[:2]))
    first = []
    for r in requests:
        cov = agent.coverage(r)
        need(isinstance(cov, dict) and ('error' in cov or not cov.get('truncated', True)),
             f'coverage must report truncated False or an error: {cov}')
        res = agent.decide(r)
        e = validate_result(r, res)
        need(not e, f'invalid result: {e}')
        first.append(res.choices)
    again = [agent.decide(r).choices for r in requests]
    need(again == first, 'decide() is not deterministic for identical requests')
    with cf.ThreadPoolExecutor(max_workers=concurrency) as ex:          # thread-safety smoke test
        conc = list(ex.map(lambda r: agent.decide(r).choices, list(requests) * concurrency))
    need(conc == first * concurrency, 'decide() gives different answers under concurrent calls')
    fp = agent.fingerprint()
    if agent.kind == 'api':
        need(fp is not None and HEX64.match(fp), 'api players must return a 64-hex fingerprint')
    return {'contract': CONTRACT_VERSION, 'player_id': agent.player_id, 'n_requests': len(requests),
            'serving_info': dataclasses.asdict(info) if dataclasses.is_dataclass(info) else dict(info)}


class MockAgent:
    """Reference implementation for tests: a deterministic policy + a simulated service time. `latency_s(req, n)`
    returns seconds; with a FakeClock the runner advances time itself (see arena.v3.runner.SimBackend)."""

    def __init__(self, player_id='mock/kcall', kind='nagi', policy=None, info=None):
        self.player_id, self.kind = player_id, kind
        self.interface = player_id.split('/')[1]
        self.max_concurrency = 3
        self.policy = policy or (lambda q: q.options[0])
        self.info = info or {'gpu': 'H100', 'weights_format': 'merged-bf16', 'kernels': 'fused', 'sdk': 'mock@0',
                             'weights_sha256': '0' * 64, 'vendor': None, 'image_sha256': None,
                             'client_region': None, 'concurrency_mode': 'serial'}

    def serving_info(self):
        return dict(self.info)

    def coverage(self, req):
        return {'tokens': sum(len(q.text) // 4 for q in req.queries), 'limit': 4096, 'truncated': False}

    def decide(self, req):
        ch = {q.key: self.policy(q) for q in req.queries}
        calls = {'kcall': len(req.queries)}.get(self.interface, 1)
        return DecisionResult(choices=ch, probs=None, prepare_ms=0.0, infer_ms=0.0, calls=calls)

    def warmup(self, reqs):
        for r in reqs:
            self.decide(r)

    def fingerprint(self):
        return None if self.kind != 'api' else '1' * 64

    def close(self):
        pass
