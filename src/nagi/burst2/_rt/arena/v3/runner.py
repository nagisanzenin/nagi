"""Arena v3 realtime runner: one player, 3 stream slots, filler shadow streams (docs/arena_v3/PROTOCOL.md §1.1).

FROZEN PROTOCOL (constants below; the P1 realtime rules generalised to any bound game, arena.v3.games):
  * One SESSION = one player (V3Agent) on one GPU / API client with 3 STREAM SLOTS. Slot g plays game g of the
    session's game list on its own seed queue, in index order, each round on its own clock: tick k of a round at
    wall time round_start + k * T (T = the game's decision period, 250 ms at 4 Hz). Slot clocks are staggered by
    T/3 (slot g starts at t0 + g T/3) so boundaries of different slots do not coincide.
  * At a live boundary k, in order: (1) collect the slot's reply if it finished; (2) if the slot has nothing in
    flight, submit ONE decision request observing the CURRENT state s_k; (3) controls for tick k by the game's hold
    rules; (4) environment bots decide on s_k; (5) physics step. A reply is applied at the first boundary after it
    finished; age = (k - observed tick) * T; age > STALE_MS -> rejected ('stale'); errors are never applied.
    Hold per control: 'one_shot' (default unless fresh), 'persistent' (last applied value; after EXPIRE_MS without
    an applied reply -> the safe default), 'query_default' (the query's own default, i.e. keep the setting).
  * FILLER: a slot without a live round (before its first round, between rounds while a reply is still in flight,
    after its queue is done while another slot still plays) runs a SHADOW STREAM: the same boundary clock and the
    same submit rule (at a boundary, if nothing is in flight, submit) on the next prompt of the frozen filler list
    for (that game, this interface); replies are logged and discarded. A slot starts its next round at the first
    boundary where it has nothing in flight. Hence during play every slot is a stream with the same arrival rule:
    ACTIVE STREAMS = 3 at every boundary (recorded per tick, asserted per cell by `assert_three_streams`).
  * Fast-forward: once the player's craft is done, the remaining environment ticks are simulated at once (no
    decision can matter), then the round is finalised.
  * VOID: a live boundary processed > LAG_LIMIT_MS after its target voids the round (kept, not scored); a
    fail-closed coverage error also voids it. No outcome-conditioned reruns (the operator re-plays a void once).
  * SPEND/DEADLINE (SpendGuard): a round starts only if (a) the job's projected cost stays <= 1.25 x its estimate,
    (b) the campaign projection stays <= the stop line ($11.00, BOARD1_APPROVAL), (c) the worker deadline leaves
    >= 1.5 x the round cap. If the job's running cost exceeds 1.25 x its estimate, the session aborts at once
    (live rounds are void 'aborted'); unplayed rounds are reported 'not_started' for a continuation job.
  * Latency is measured HERE on the serving path: submit (observation snapshot) -> result available, per request
    and per stream; the probe (`latency_probe`) measures 1-stream vs 3-stream inflation on filler prompts.
  * Records: the V2 format (decisions = APPLIED controls of every tick for every seat) so arena.core.replay_actions
    reproduces the round; plus 'realtime' (requests, ticks with lag / source / active streams / in-flight) and the
    platform stamp. `verify_records` replays them (float engines only on their recording platform, R3.23).
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from nagi.burst2._rt.arena.chord import MultiQuery
from nagi.burst2._rt.arena.core import Decision, Query
from nagi.burst2._rt.arena.v3 import PROTOCOL_VERSION
from nagi.burst2._rt.arena.v3.contract import DecisionRequest, DecisionResult

STALE_MS = 1000
EXPIRE_MS = 1000
LAG_LIMIT_MS = 100
N_SLOTS = 3
PROBE_S = (30.0, 30.0)   # 1-stream then 3-stream probe seconds (PROTOCOL §1.1.9)


class FailClosed(RuntimeError):
    pass


class JobStop(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------------- clocks
class FakeClock:
    """Simulated monotonic clock: sleep_until advances time; `work_s` is added per boundary (loop's own work)."""

    def __init__(self, t0: float = 1000.0, work_s: float = 0.002):
        self.t, self.work_s = t0, work_s

    def __call__(self) -> float:
        return self.t

    def sleep_until(self, target: float) -> None:
        self.t = max(self.t, target) + self.work_s


class RealClock:
    def __call__(self) -> float:
        return time.monotonic()

    def sleep_until(self, target: float) -> None:
        d = target - time.monotonic()
        if d > 0:
            time.sleep(d)


# ---------------------------------------------------------------------------------------------- back ends
class _Done:
    def __init__(self, value):
        self.value = value

    def done(self):
        return True

    def result(self):
        return self.value


class ThreadBackend:
    """Real back end: agent.coverage + agent.decide in a pool of N_SLOTS threads (one outstanding request per stream,
    so at most 3 concurrent calls: the V3Agent contract). Returns a future of a dict."""

    def __init__(self, agent, clock: Callable[[], float] = time.monotonic, workers: int = N_SLOTS):
        self.agent, self.clock = agent, clock
        self.pool = ThreadPoolExecutor(max_workers=workers)

    def _job(self, req: DecisionRequest) -> dict:
        t0 = self.clock()
        try:
            cov = self.agent.coverage(req)
            if 'error' in cov or cov.get('truncated') or ('limit' in cov and cov.get('tokens', 0) > cov['limit']):
                return {'fail_closed': f'coverage {cov}', 'finished_s': self.clock()}
            res = self.agent.decide(req)
            return {'result': res, 'finished_s': self.clock(), 'agent_ms': (self.clock() - t0) * 1000}
        except Exception as exc:  # noqa: BLE001  (agent error: logged, never applied)
            return {'error': f'{type(exc).__name__}: {str(exc)[:200]}', 'finished_s': self.clock()}

    def submit(self, req: DecisionRequest, in_flight: int):
        return self.pool.submit(self._job, req)

    def close(self):
        self.pool.shutdown(wait=True)


class SimFuture:
    def __init__(self, clock, finish_s, value):
        self.clock, self.finish_s, self.value = clock, finish_s, value

    def done(self):
        return self.clock() >= self.finish_s

    def result(self):
        return self.value


class SimBackend:
    """Deterministic test back end on a FakeClock: latency_s(req, in_flight, n) seconds (in_flight = other streams'
    requests in flight at submit: a contention model); the agent's decide() gives the choices."""

    def __init__(self, agent, clock, latency_s, error_every: int = 0, fail_closed_every: int = 0):
        self.agent, self.clock, self.latency_s, self.n = agent, clock, latency_s, 0
        self.error_every, self.fail_closed_every = error_every, fail_closed_every

    def submit(self, req, in_flight: int):
        self.n += 1
        fin = self.clock() + self.latency_s(req, in_flight, self.n)
        if self.fail_closed_every and self.n % self.fail_closed_every == 0:
            return SimFuture(self.clock, fin, {'fail_closed': 'coverage (sim)', 'finished_s': fin})
        if self.error_every and self.n % self.error_every == 0:
            return SimFuture(self.clock, fin, {'error': 'SimError', 'finished_s': fin})
        return SimFuture(self.clock, fin, {'result': self.agent.decide(req), 'finished_s': fin})

    def close(self):
        pass


# ---------------------------------------------------------------------------------------------- filler lists
def filler_entry(queries: list[Query], multi: MultiQuery | None) -> dict:
    return {'queries': [{'key': q.key, 'text': q.text, 'options': list(q.options), 'default': q.default}
                        for q in queries],
            'multi': None if multi is None else {'text': multi.text,
                                                 'controls': [[k, list(o), d] for k, o, d in multi.controls]}}


def filler_sha(entries: list[dict]) -> str:
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def filler_request(entry: dict, stream: int, game: str, tick: int) -> DecisionRequest:
    qs = tuple(Query(0, q['key'], q['text'], tuple(q['options']), q['default']) for q in entry['queries'])
    m = entry['multi']
    mq = None if m is None else MultiQuery(0, m['text'], tuple((k, tuple(o), d) for k, o, d in m['controls']))
    return DecisionRequest(stream=stream, game=game, obs_tick=tick, queries=qs, multi=mq)


# ---------------------------------------------------------------------------------------------- spend guard
@dataclass
class SpendGuard:
    """In-job second line of defence (the Modal guard/ledger stays the first; never modified here).
    usd(t) = rate * (t - start); projected job $ = usd(now) + remaining planned seconds * rate."""
    rate_usd_s: float
    job_estimate_usd: float
    campaign_committed_usd: float          # billed + held + remaining planned (high case) of every OTHER job
    stop_line_usd: float = 11.00
    stop_factor: float = 1.25
    deadline_s: float = math.inf           # clock value of the worker deadline
    round_cap_s: float = 92.0              # longest possible round (T_max + margin)
    start_s: float | None = None
    log: list = field(default_factory=list)

    def begin(self, now: float):
        self.start_s = now

    def usd(self, now: float) -> float:
        return 0.0 if self.start_s is None else self.rate_usd_s * (now - self.start_s)

    def may_start_round(self, now: float, remaining_play_s: float) -> tuple[bool, str]:
        run = self.usd(now)
        next_cost = self.rate_usd_s * self.round_cap_s
        if run + next_cost > self.stop_factor * self.job_estimate_usd:
            return False, f'job would exceed {self.stop_factor}x estimate ${self.job_estimate_usd:.2f}'
        proj = self.campaign_committed_usd + run + self.rate_usd_s * remaining_play_s
        if proj > self.stop_line_usd:
            return False, f'campaign projection ${proj:.2f} > stop line ${self.stop_line_usd:.2f}'
        if now + 1.5 * self.round_cap_s > self.deadline_s:
            return False, 'worker deadline: < 1.5 x round cap left'
        return True, ''

    def check_abort(self, now: float) -> str | None:
        if self.usd(now) > self.stop_factor * self.job_estimate_usd:
            return f'job cost ${self.usd(now):.3f} > {self.stop_factor}x estimate ${self.job_estimate_usd:.2f}'
        if self.campaign_committed_usd + self.usd(now) > self.stop_line_usd:
            return f'campaign spend > stop line ${self.stop_line_usd:.2f}'
        if now > self.deadline_s:
            return 'worker deadline passed'
        return None


# ---------------------------------------------------------------------------------------------- slots
class _Req:
    def __init__(self, fut, kind, obs_tick, submit_s, text_sha, in_flight):
        self.fut, self.kind, self.obs_tick, self.submit_s = fut, kind, obs_tick, submit_s
        self.text_sha, self.in_flight = text_sha, in_flight


class _Round:
    def __init__(self, binding, index, seed, start_s):
        self.b, self.index, self.seed, self.start_s = binding, index, seed, start_s
        self.g = binding.make()
        self.s = self.g.reset(seed)
        self.bots = binding.env_bots(seed)
        self.k = 0
        self.held = {k: binding.default.get(k) for k in binding.controls}
        self.last_applied_k = None
        self.decisions, self.events, self.hashes = [], [], [self.g.state_hash(self.s)]
        self.requests, self.ticks, self.texts = [], [], {}
        self.void = None


class Slot:
    def __init__(self, stream: int, binding, seeds: list[tuple[int, int]], filler: list[dict], t0: float, T_s: float):
        self.stream, self.b, self.queue = stream, binding, deque(seeds)
        self.filler, self.fi = filler, 0
        self.mode = 'filler'           # 'live' | 'filler' | 'idle' (probe only)
        self.round: _Round | None = None
        self.pending: _Req | None = None
        self.T_s = T_s
        self.next_t = t0 + stream * T_s / N_SLOTS
        self.tick = 0                  # slot-clock boundary counter (filler ticks)
        self.filler_log: list[dict] = []


# ---------------------------------------------------------------------------------------------- session
@dataclass
class SessionResult:
    session: str
    player_id: str
    records: list[dict]
    not_started: list[dict]
    filler_log: list[dict]
    stop_reason: str | None
    filler_sha: dict
    harness: dict | None = None      # streams harness: per-stream lag / slack stats (arena.v3.streams); not in records


def _req_entry(r: _Req, res: dict, k: int, T_ms: int, start: float) -> dict:
    out = {'seq': None, 'kind': r.kind, 'obs_tick': r.obs_tick, 'submit_s': round(r.submit_s - start, 6),
           'finish_s': round(res.get('finished_s', r.submit_s) - start, 6), 'receive_tick': k,
           'age_ms': (k - r.obs_tick) * T_ms, 'latency_ms': round((res.get('finished_s', r.submit_s) - r.submit_s) * 1000, 3),
           'in_flight_at_submit': r.in_flight, 'text_sha256': r.text_sha}
    if 'result' in res:
        rr: DecisionResult = res['result']
        out.update(choices=rr.choices, probs=rr.probs, calls=rr.calls, prepare_ms=rr.prepare_ms, infer_ms=rr.infer_ms)
    for f in ('error', 'fail_closed'):
        if f in res:
            out[f] = res[f]
    return out


def run_session(agent, bindings: list, seeds: list[list[tuple[int, int]]], filler: list[list[dict]],
                backend, clock, guard: SpendGuard | None = None, stale_ms: int = STALE_MS,
                expire_ms: int = EXPIRE_MS, lag_limit_ms: int = LAG_LIMIT_MS, session: str | None = None,
                platform: dict | None = None) -> SessionResult:
    """Play every seed of every slot for ONE player (see the module docstring). bindings/seeds/filler are per slot
    (len 3). seeds[g] = [(seed_index, seed), ...].

    REFERENCE / SIMULATION LOOP (FakeClock + SimBackend): all 3 slots share this one loop, and a finished craft's
    fast-forward and record build run inline. On a real clock that stalls the other slots' boundaries (Board 1:
    250-630 ms, void rounds; BOARD1_STOP_20260927), so realtime play uses `arena.v3.streams.run_session_mp` (one
    process per stream, same per-tick logic, equal records: tests/test_arena_v3_streams.py)."""
    n_slots = len(bindings)                   # N_SLOTS (Arena v3), or 1 on the explicit single-stream path
    assert n_slots in (1, N_SLOTS) and len(seeds) == len(filler) == n_slots
    session = session or uuid.uuid4().hex[:12]
    if platform is None:
        from nagi.burst2._rt.arena.replay_platform import platform_stamp
        platform = platform_stamp()
    t0 = clock()
    if guard:
        guard.begin(t0)
    slots = [Slot(g, bindings[g], list(seeds[g]), filler[g], t0, bindings[g].make().decision_period_ms / 1000)
             for g in range(n_slots)]
    for sl in slots:
        assert sl.filler, f'slot {sl.stream}: empty filler list'
    records, not_started, stop_reason = [], [], None
    fsha = {bindings[g].id: filler_sha(filler[g]) for g in range(n_slots)}

    def in_flight(exclude=None):
        return sum(1 for s in slots if s.pending is not None and s is not exclude)

    def remaining_play_s():
        return sum(len(s.queue) for s in slots) * (guard.round_cap_s if guard else 0) / n_slots

    def finalize(sl: Slot, reason_void=None):
        r = sl.round
        if reason_void and r.void is None:
            r.void = reason_void
        rec = _record(r, agent, session, platform, fsha[sl.b.id], sl.stream, stale_ms, expire_ms, lag_limit_ms)
        records.append(rec)
        sl.round, sl.mode = None, 'filler'
        if sl.pending is not None and sl.pending.kind == 'live':
            sl.pending.kind = 'orphan'          # stays in flight on this stream; never applied

    while True:
        live_or_queued = any(s.round is not None or s.queue for s in slots)
        if not live_or_queued:
            break
        sl = min(slots, key=lambda s: (s.next_t, s.stream))
        target = sl.next_t
        clock.sleep_until(target)
        now = clock()
        lag_ms = max(0.0, now - target) * 1000
        if guard:
            why = guard.check_abort(now)
            if why:
                stop_reason = why
                for s in slots:
                    if s.round is not None:
                        finalize(s, f'aborted: {why}')
                    not_started += [{'game': s.b.id, 'index': i, 'seed': sd, 'reason': why} for i, sd in s.queue]
                    s.queue.clear()
                break
        active = sum(1 for s in slots if s.mode in ('live', 'filler'))
        # (1) collect whatever finished on this stream
        fresh = None
        if sl.pending is not None and sl.pending.fut.done():
            res = sl.pending.fut.result()
            if sl.pending.kind == 'live' and sl.round is not None:
                r = sl.round
                e = _req_entry(sl.pending, res, r.k, int(round(sl.T_s * 1000)), r.start_s)
                e['seq'] = len(r.requests)
                if 'fail_closed' in res:
                    e.update(applied=False, status='fail_closed')
                    r.void = r.void or f'fail-closed: {res["fail_closed"]}'
                elif 'error' in res:
                    e.update(applied=False, status='error')
                elif e['age_ms'] > stale_ms:
                    e.update(applied=False, status='stale')
                else:
                    e.update(applied=True, status='applied')
                    fresh = e
                r.requests.append(e)
            else:
                sl.filler_log.append({'stream': sl.stream, 'kind': sl.pending.kind,
                                      'latency_ms': round((res.get('finished_s', now) - sl.pending.submit_s) * 1000, 3),
                                      'in_flight_at_submit': sl.pending.in_flight,
                                      'status': 'error' if 'error' in res else ('fail_closed' if 'fail_closed' in res else 'ok')})
            sl.pending = None
        # start the next round at a boundary with nothing in flight
        if sl.round is None and sl.queue and sl.pending is None and sl.mode != 'idle':
            ok, why = guard.may_start_round(now, remaining_play_s()) if guard else (True, '')
            if ok:
                idx, sd = sl.queue.popleft()
                sl.round = _Round(sl.b, idx, sd, target)     # tick 0 on the slot's boundary grid
                sl.mode = 'live'
            else:
                stop_reason = stop_reason or why
                not_started += [{'game': sl.b.id, 'index': i, 'seed': s_, 'reason': why} for i, s_ in sl.queue]
                sl.queue.clear()
        if sl.round is not None:
            _live_tick(sl, backend, clock, fresh, lag_ms, active, in_flight(sl), expire_ms, lag_limit_ms)
            r = sl.round
            if _over(r):
                finalize(sl)
            elif not bool(r.g.queries(r.s, 0, {})):      # craft done, environment still running: fast-forward
                while not _over(r):
                    _env_only_tick(r)
                finalize(sl)
        elif sl.mode == 'filler' and sl.pending is None:
            entry = sl.filler[sl.fi % len(sl.filler)]
            sl.fi += 1
            req = filler_request(entry, sl.stream, sl.b.id, sl.tick)
            text = '\n\n'.join(q.text for q in req.queries)
            sl.pending = _Req(backend.submit(req, in_flight(sl)), 'filler', sl.tick, clock(),
                              hashlib.sha256(text.encode()).hexdigest(), in_flight(sl))
        sl.tick += 1
        sl.next_t = (sl.round.start_s + sl.round.k * sl.T_s) if sl.round is not None else sl.next_t + sl.T_s
    return SessionResult(session, agent.player_id, records, not_started,
                         [x for s in slots for x in s.filler_log], stop_reason, fsha)


def _controls(r: _Round, fresh: dict | None, T_ms: int, expire_ms: int, qs: list[Query]) -> tuple[dict, str]:
    b = r.b
    opts = {q.key: q for q in qs}
    acts = {}
    if fresh is not None:
        valid = {k: v for k, v in (fresh.get('choices') or {}).items() if k in opts and v in opts[k].options}
        for k in b.controls:
            if k in valid:
                acts[k] = valid[k]
            elif b.hold[k] == 'persistent':
                acts[k] = r.held[k]
            elif b.hold[k] == 'one_shot':
                acts[k] = b.default[k]
            else:
                acts[k] = opts[k].default
        fresh['invalid_controls'] = sorted(set(fresh.get('choices') or {}) - set(valid))
        r.last_applied_k = r.k
        src = 'fresh'
    elif r.last_applied_k is not None and (r.k - r.last_applied_k) * T_ms <= expire_ms:
        acts = {k: (r.held[k] if b.hold[k] == 'persistent' else
                    b.default[k] if b.hold[k] == 'one_shot' else opts[k].default) for k in b.controls}
        src = 'held'
    else:
        acts = {k: (b.default[k] if b.hold[k] in ('persistent', 'one_shot') else opts[k].default) for k in b.controls}
        src = 'expired' if r.last_applied_k is not None else 'default'
    for k in b.controls:
        if b.hold[k] == 'persistent':
            r.held[k] = acts[k]
    return acts, src


def _bots_act(r: _Round, decisions: list, T_ms: int) -> dict:
    actions = {}
    for p, bot in r.bots.items():
        bot.see(r.g, r.s)
        ans = {}
        qs = r.g.queries(r.s, p, ans)
        while qs:
            for q in qs:
                a = bot.choose(q)
                a = a if a in q.options else q.default
                ans[q.key] = a
                decisions.append(Decision(r.k * T_ms, p, q.key, q.options, hashlib.sha256(q.text.encode()).hexdigest(),
                                          a, a, q.default, None, 'bot'))
            qs = r.g.queries(r.s, p, ans)
        actions[p] = ans
    return actions


def _step(r: _Round, actions: dict, T_ms: int):
    full = {p: actions.get(p, {}) for p in range(getattr(r.g, 'n_players', 1 + len(r.bots)))}
    r.s, ev = r.g.step(r.s, full, T_ms)
    r.k += 1
    r.events += ev
    r.hashes.append(r.g.state_hash(r.s))


def _live_tick(sl: Slot, backend, clock, fresh, lag_ms, active, others_in_flight, expire_ms, lag_limit_ms):
    r = sl.round
    T_ms = int(round(sl.T_s * 1000))
    qs = r.g.queries(r.s, 0, {})
    alive = bool(qs)
    if alive and lag_ms > lag_limit_ms and r.void is None:
        r.void = f'tick {r.k} processed {lag_ms:.1f} ms late (> {lag_limit_ms} ms)'
    if alive and sl.pending is None:                         # (2) submit on the CURRENT state
        mq = sl.b.multi_query(r.g, r.s)
        req = DecisionRequest(stream=sl.stream, game=sl.b.id, obs_tick=r.k, queries=tuple(qs), multi=mq)
        text = '\n\n'.join(q.text for q in qs)
        h = hashlib.sha256(text.encode()).hexdigest()
        r.texts[h] = text
        sl.pending = _Req(backend.submit(req, others_in_flight), 'live', r.k, clock(), h, others_in_flight)
    src = None
    if alive:                                                # (3) controls
        acts, src = _controls(r, fresh, T_ms, expire_ms, qs)
        for q in qs:
            r.decisions.append(Decision(r.k * T_ms, 0, q.key, q.options,
                                        fresh['text_sha256'] if src == 'fresh' else '',
                                        (fresh.get('choices') or {}).get(q.key) if src == 'fresh' else None,
                                        acts[q.key], q.default, fresh['latency_ms'] if src == 'fresh' else None, src))
    else:
        acts = {}
    actions = {0: acts, **_bots_act(r, r.decisions, T_ms)}  # (4) environment bots on s_k
    r.ticks.append({'k': r.k, 'lag_ms': round(lag_ms, 3), 'source': src, 'active_streams': active,
                    'in_flight': others_in_flight + (1 if sl.pending is not None else 0), 'alive': alive})
    _step(r, actions, T_ms)                                  # (5) physics


def _over(r: _Round) -> bool:
    """Round over: the engine says done, or the round cap in ticks is reached (engines keep their own time)."""
    return r.g.done(r.s) or r.k * r.g.decision_period_ms >= r.g.max_round_ms


def _env_only_tick(r: _Round):
    T_ms = r.g.decision_period_ms
    actions = {0: {}, **_bots_act(r, r.decisions, T_ms)}
    r.ticks.append({'k': r.k, 'lag_ms': None, 'source': None, 'active_streams': None, 'in_flight': None,
                    'alive': False, 'fast_forward': True})
    _step(r, actions, T_ms)


def _record(r: _Round, agent, session, platform, fsha, stream, stale_ms, expire_ms, lag_limit_ms) -> dict:
    g = r.g
    T_ms = g.decision_period_ms
    rec = {'protocol': PROTOCOL_VERSION, 'game': r.b.id, 'rules_id': g.rules_id, 'seed': r.seed,
           'seed_index': r.index, 'mode': 'realtime', 'stream': stream, 'session': session,
           'player_id': agent.player_id, 'agents': [agent.player_id] + [b.name for b in r.bots.values()],
           'duration_ms': r.k * T_ms, 'decisions': [asdict(d) for d in r.decisions],
           'events': [asdict(e) for e in r.events],
           'frames': [{'t_ms': i * T_ms, 'hash': x} for i, x in enumerate(r.hashes)],
           'final': g.render_state(r.s), 'void': r.void, 'platform': platform, 'filler_sha256': fsha,
           'realtime': {'period_ms': T_ms, 'stale_ms': stale_ms, 'expire_ms': expire_ms, 'lag_limit_ms': lag_limit_ms,
                        'requests': r.requests, 'ticks': r.ticks, 'texts': r.texts}}
    rec['score'] = r.b.score(rec) if (r.b.score and r.void is None) else None
    return rec


# ---------------------------------------------------------------------------------------------- probe
def latency_probe(agent_backend, bindings: list, filler: list[list[dict]], clock, seconds=PROBE_S) -> dict:
    """PROTOCOL §1.1.9: filler-only streams, first 1 stream (slots 1-2 idle) for seconds[0], then 3 streams for
    seconds[1]. Returns p50/p90 per phase and the inflation ratio p50(3) / p50(1).
    Single-stream serving path (one binding; docs/burst_v2): the 1-stream phase only (seconds[1] must be 0), and
    inflation_p50 None (there is no multi-stream phase to compare)."""
    n_slots = len(bindings)
    assert n_slots in (1, N_SLOTS), n_slots
    if n_slots == 1:
        assert not seconds[1], 'single-stream probe: no multi-stream phase (probe_s[1] must be 0)'
    out = {}
    phases = ((1, seconds[0]), (N_SLOTS, seconds[1])) if n_slots == N_SLOTS else ((1, seconds[0]),)
    for phase, (n_active, dur) in enumerate(phases):
        t0 = clock()
        slots = [Slot(g, bindings[g], [], filler[g], t0, bindings[g].make().decision_period_ms / 1000)
                 for g in range(n_slots)]
        for s in slots[n_active:]:
            s.mode = 'idle'
        lat = []
        while True:
            sl = min(slots[:n_active], key=lambda s: (s.next_t, s.stream))
            if sl.next_t - t0 > dur:
                break
            clock.sleep_until(sl.next_t)
            if sl.pending is not None and sl.pending.fut.done():
                res = sl.pending.fut.result()
                lat.append((res.get('finished_s', clock()) - sl.pending.submit_s) * 1000)
                sl.pending = None
            if sl.pending is None:
                req = filler_request(sl.filler[sl.fi % len(sl.filler)], sl.stream, sl.b.id, sl.tick)
                sl.fi += 1
                others = sum(1 for s in slots if s.pending is not None and s is not sl)
                sl.pending = _Req(agent_backend.submit(req, others), 'probe', sl.tick, clock(), '', others)
            sl.tick += 1
            sl.next_t += sl.T_s
        lat.sort()
        out[f'streams_{n_active}'] = {'n': len(lat), 'p50_ms': _q(lat, 0.5), 'p90_ms': _q(lat, 0.9)}
    if n_slots == 1:
        out['inflation_p50'] = None
        return out
    a, b = out['streams_1']['p50_ms'], out[f'streams_{N_SLOTS}']['p50_ms']
    out['inflation_p50'] = None if not a or b is None else round(b / a, 4)
    return out


def _q(xs, p):
    if not xs:
        return None
    return round(xs[min(len(xs) - 1, int(p * len(xs)))], 3)


# ---------------------------------------------------------------------------------------------- per-cell checks
def assert_three_streams(records: list[dict]) -> None:
    """PROTOCOL §1.1.9 cell assertion: at every live boundary of every round, 3 streams were active."""
    assert_active_streams(records, N_SLOTS)


def assert_active_streams(records: list[dict], n: int) -> None:
    """Cell assertion for a serving path with `n` streams (N_SLOTS: Arena v3; 1: the explicit single-stream path of
    docs/burst_v2): at every live boundary of every round, exactly n streams were active."""
    for rec in records:
        bad = [t['k'] for t in rec['realtime']['ticks'] if t.get('alive') and t.get('active_streams') != n]
        if bad:
            raise AssertionError(f'{rec["game"]} index {rec["seed_index"]}: active streams != {n} at ticks {bad[:5]}')


def verify_records(records: list[dict], engines: dict) -> dict:
    """Replay every record from its applied actions (arena.core.replay_actions) on this platform; float engines are
    refused off their recording platform (arena.replay_platform)."""
    from nagi.burst2._rt.arena.replay_platform import verify_replay
    ok = sum(bool(verify_replay(engines[r['game']](), r)) for r in records)
    return {'replayed': len(records), 'exact': ok}


def cell_rows(records: list[dict]) -> list[dict]:
    """Registry per-seed rows (scripts/arena_v3_registry.py) for one (player, game) from its records."""
    rows = []
    for r in sorted(records, key=lambda x: x['seed_index']):
        blob = json.dumps(r, sort_keys=True, separators=(',', ':')).encode()
        sc = r.get('score') or {}
        rows.append({'index': r['seed_index'], 'seed': r['seed'], 'score': None if r['void'] else sc.get('score01'),
                     'raw': None if r['void'] else sc.get('raw'), 'void': r['void'] is not None,
                     'survival_s': sc.get('survival_s'), 'record_sha256': hashlib.sha256(blob).hexdigest()})
    return rows


def latency_summary(records: list[dict]) -> dict:
    lat = sorted(e['latency_ms'] for r in records for e in r['realtime']['requests'] if 'latency_ms' in e)
    live = [t for r in records for t in r['realtime']['ticks'] if t.get('alive')]
    return {'latency_ms': {'p50': _q(lat, 0.5), 'p90': _q(lat, 0.9), 'p99': _q(lat, 0.99)} if lat else None,
            'fresh_share': (sum(t['source'] == 'fresh' for t in live) / len(live)) if live else None,
            'requests': sum(len(r['realtime']['requests']) for r in records),
            'stale': sum(e.get('status') == 'stale' for r in records for e in r['realtime']['requests']),
            'errors': sum(e.get('status') in ('error', 'fail_closed') for r in records for e in r['realtime']['requests'])}
