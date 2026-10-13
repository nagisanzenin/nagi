"""Served reply latency of Burst and a runner-exact emulator of it.

P-hat(d) = share of Burst's applied live replies whose age (applied tick - observed tick) is d ticks, measured from the
Burst release realtime records (br_A_s1..s3, enormous_burst/chord, Linux x86_64, H100, micro-batched serving;
`measure()` -> docs/burst_v2/latency_receipt.json). Only d in {1, 2} occurs (4,633/4,633 replies).

Emulator (seat 0, the arena.v3.runner timing; arena.v3.delay.Delayed generalised to a random per-request delay):
at boundary k, in the runner's order: (1) collect the in-flight reply if k - obs_tick >= its delay d; (2) the applied
controls of tick k come from arena.v3.runner._controls itself (frozen hold rules); (3) if nothing is in flight, a new
request observes s_k: the policy sees (s_k, p_log = the controls applied at tick k) and answers, and its delay d is
drawn from P-hat with a seeded RNG. p_log is what the runner applies before the new reply lands; the label conditions
on it (the model cannot see it; with soft-target CE its optimum is E[target | prompt], the average over p_log).
"""
from __future__ import annotations

import glob
import hashlib
import json
import math
import random
from pathlib import Path

from nagi.burst2._rt.arena.v3.runner import EXPIRE_MS, _controls

RECORDS = "/private/tmp/claude-501/arena_audit/burst_release"
RECEIPT = Path(__file__).resolve().parents[2] / "docs/burst_v2/latency_receipt.json"
GAMES = ("booster_gauntlet", "rotorwash_ramp", "snake")

# Frozen from docs/burst_v2/latency_receipt.json (tests assert equality with the receipt).
P_HAT = {
    "booster_gauntlet": {1: 723 / 1834, 2: 1111 / 1834},
    "rotorwash_ramp": {1: 827 / 1986, 2: 1159 / 1986},
    "pooled": {1: 1949 / 4633, 2: 2684 / 4633},
}
P_HAT_BY_SEED_GAME = {"booster_gauntlet": P_HAT["booster_gauntlet"], "rotorwash_ramp": P_HAT["rotorwash_ramp"]}
# Consecutive delays are NOT independent (receipt 'transitions_within_round'): a 1-tick reply is followed by a 2-tick
# reply 706/706 (Booster) and 799/809 (RR) times; after a 2-tick reply, P(1) = 708/1094 and 799/1143. The emulator
# draws delays from this first-order chain (first request of a round: the marginal P-hat), so rollout state
# distributions and continuation timings match serving. Labels still use the marginal P-hat (see labels.py).
TRANSITIONS = {
    "booster_gauntlet": {1: {1: 0, 2: 706}, 2: {1: 708, 2: 386}},
    "rotorwash_ramp": {1: {1: 10, 2: 799}, 2: {1: 799, 2: 344}},
}


def markov_for(seed_game: str) -> dict[int, dict[int, float]]:
    t = TRANSITIONS[seed_game]
    return {a: {b: n / sum(row.values()) for b, n in row.items()} for a, row in t.items()}


# Latency profiles (a config parameter of every label / emulator run; recorded in each row's meta).
#  single_stream (DEFAULT, coordinator decision 2026-09-30): V2 and the Burst V1 re-play are served one game stream
#    per GPU with no filler. Single-stream Burst latency p50 147-151 ms (docs/burst_release/receipts/selection.json
#    LAT.A p50_1stream_ms; coordinator: p50 120-135, p90 <= 143 ms), so almost every reply lands after 1 tick. No
#    per-request single-stream receipt exists (the probe keeps only medians), so P-hat is the documented default
#    d=1 w.p. 0.85, d=2 w.p. 0.15 (a conservative tail), drawn i.i.d. Re-measure from the first V2 canary records and
#    retrain labels if it differs (profiles are data: nothing else changes).
#  release_3stream: the Burst release serving (3 streams + filler), measured per game above, first-order chain.
PROFILES = {
    "single_stream": {"booster_gauntlet": {"p_hat": {1: 0.85, 2: 0.15}, "markov": None},
                      "rotorwash_ramp": {"p_hat": {1: 0.85, 2: 0.15}, "markov": None},
                      "snake": {"p_hat": {1: 0.85, 2: 0.15}, "markov": None}},
    "release_3stream": {g: {"p_hat": P_HAT_BY_SEED_GAME[g], "markov": "chain"} for g in P_HAT_BY_SEED_GAME},
}
DEFAULT_PROFILE = "single_stream"


def profile(name: str, seed_game: str) -> tuple[dict, dict | None]:
    """(P-hat for labels, first-order chain for the emulator or None = i.i.d. P-hat)."""
    pr = PROFILES[name][seed_game]
    return dict(pr["p_hat"]), (markov_for(seed_game) if pr["markov"] == "chain" else None)


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def measure(root: str = RECORDS) -> dict:
    """Latency receipt from the Burst release records (read-only)."""
    out, files = {}, {}
    pooled = {}
    for g in GAMES:
        ages, lat, n_req, lag1 = {}, [], 0, []
        paths = sorted(glob.glob(f"{root}/br_A_s*/enormous_burst__chord/{g}/*.json"))
        files[g] = {p.split("burst_release/")[1]: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
        for p in paths:
            rec = json.loads(Path(p).read_text())
            prev = None
            for q in rec["realtime"]["requests"]:
                n_req += 1
                if not q["applied"]:
                    continue
                d = q["age_ms"] // rec["realtime"]["period_ms"]
                ages[d] = ages.get(d, 0) + 1
                pooled[d] = pooled.get(d, 0) + 1
                lat.append(q["latency_ms"])
                if prev is not None:
                    lag1.append((prev, d))
                prev = d
        n = sum(ages.values())
        lat.sort()
        # serial dependence of consecutive delays (is d i.i.d. per request?): P(d=2 | prev d)
        cond = {pd: (sum(1 for a, b in lag1 if a == pd and b == 2), sum(1 for a, _ in lag1 if a == pd)) for pd in (1, 2)}
        trans = {f"{a}->{b}": sum(1 for x, y in lag1 if (x, y) == (a, b)) for a in (1, 2) for b in (1, 2)}
        out[g] = {"requests": n_req, "applied": n, "age_ticks": {str(k): v for k, v in sorted(ages.items())},
                  "p_hat": {str(k): v / n for k, v in sorted(ages.items())},
                  "p1_wilson95": list(wilson(ages.get(1, 0), n)),
                  "latency_ms_p10_p50_p90": [lat[len(lat) // 10], lat[len(lat) // 2], lat[9 * len(lat) // 10]],
                  "p_d2_given_prev": {str(pd): (a / b if b else None) for pd, (a, b) in cond.items()},
                  "transitions_within_round": trans,
                  "records": len(paths)}
    n = sum(pooled.values())
    out["pooled"] = {"applied": n, "age_ticks": {str(k): v for k, v in sorted(pooled.items())},
                     "p_hat": {str(k): v / n for k, v in sorted(pooled.items())},
                     "p1_wilson95": list(wilson(pooled.get(1, 0), n))}
    return {"source": root, "player": "enormous_burst/chord", "jobs": ["br_A_s1", "br_A_s2", "br_A_s3"],
            "definition": "d = age_ms / period_ms of every applied live reply (applied tick - observed tick)",
            "by_game": out, "record_sha256": files}


def p_hat_for(seed_game: str) -> dict[int, float]:
    return dict(P_HAT_BY_SEED_GAME[seed_game])


class _RoundView:
    def __init__(self, binding):
        self.b = binding
        self.held = {k: binding.default.get(k) for k in binding.controls}
        self.last_applied_k = None
        self.k = 0


class Emulator:
    """Runner-exact seat-0 timing with a random reply delay per request (seeded; no clock)."""

    def __init__(self, binding, p_hat: dict[int, float], key: str, period_ms: int = 250,
                 markov: dict[int, dict[int, float]] | None = None, fixed_delay: int | None = None):
        assert abs(sum(p_hat.values()) - 1) < 1e-9 and all(d >= 1 and d * period_ms <= EXPIRE_MS for d in p_hat)
        self.b, self.p_hat, self.T_ms = binding, dict(sorted(p_hat.items())), period_ms
        self.markov, self.fixed_delay, self._prev_d = markov, fixed_delay, None
        self.rng = random.Random(hashlib.sha256(f"bv2-latency|{key}".encode()).hexdigest())
        self._r = _RoundView(binding)
        self._pending = None          # (obs_tick, delay, answers)
        self.k = 0
        self.requests: list[dict] = []
        self.sources: list[str] = []

    def draw_delay(self) -> int:
        if self.fixed_delay is not None:
            return self.fixed_delay
        dist = self.p_hat if (self.markov is None or self._prev_d is None) else self.markov[self._prev_d]
        u, acc = self.rng.random(), 0.0
        for d, p in sorted(dist.items()):
            acc += p
            if u < acc:
                return d
        return max(self.p_hat)

    def tick(self, game, state, policy, qs=None) -> dict:
        """Controls applied at this tick (call once per tick, before stepping). policy(state, p_log, k) -> answers."""
        qs = game.queries(state, 0, {}) if qs is None else qs
        k = self.k
        self.k += 1
        if not qs:
            return {}
        fresh = None
        if self._pending is not None and k - self._pending[0] >= self._pending[1]:
            fresh = {"choices": self._pending[2]}
            self.requests[-1]["applied_tick"] = k
            self._pending = None
        self._r.k = k
        acts, src = _controls(self._r, fresh, self.T_ms, EXPIRE_MS, qs)
        self.sources.append(src)
        if self._pending is None:
            p_log = dict(acts)
            ans = policy(state, p_log, k)
            d = self.draw_delay()
            self._prev_d = d
            self._pending = (k, d, dict(ans))
            self.requests.append({"obs_tick": k, "delay": d, "p_log": p_log, "answers": dict(ans),
                                  "applied_tick": None})
        return acts


def held_after(binding, acts: dict) -> dict:
    """What the runner applies on a tick with no fresh reply, one tick after `acts` was applied (hold rules)."""
    out = {}
    for k in binding.controls:
        h = binding.hold[k]
        out[k] = acts[k] if h == "persistent" else binding.default[k] if h == "one_shot" else None
    return out


if __name__ == "__main__":
    rec = measure()
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n")
    print(json.dumps({g: v.get("p_hat") for g, v in rec["by_game"].items()}))
