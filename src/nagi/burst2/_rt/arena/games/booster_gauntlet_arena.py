"""BOOSTER GAUNTLET on the Arena runners: seeds/splits, fail-first scoring (FAIL_FIRST_BRIEF Amendment 1), the v3 game
binding and the rule-variant flip analysis. docs/arena_v3/BOOSTER_GAUNTLET.md.

Scoring (Amendment 1): per round and player the outcome is the survival time T_fail (s, right-censored at 90 s), the
level at failure (1 + floor(T_fail / 10 s)), the game score (hops landed) and the landing quality. The decisional
metric is the paired per-seed win rate (later failure wins, equal ticks or both censored = 1/2), computed by the
report across players. `score01` (legacy consumers) = the ladder position: T_fail mapped piecewise-linearly through
the frozen ladder MEDIANS (naive -> 0, heuristic -> 0.5, planner -> 1; below the naive median 0, above the planner
median the heuristic->planner slope continued), clipped to [0, 1] (the report may show the [0, 1.2] clip).

Runner compatibility (tests/test_booster_gauntlet_runner.py): arena.core.Referee, arena.chord.ChordReferee and
arena.v2.runner.V2Referee take `BoosterGauntlet(...)` directly; `arena.v3.games` registers it as 'booster_gauntlet'
(persistent controls with the static safe defaults below, score() = `score_record`).
"""
from __future__ import annotations

import hashlib
import math
import time

from nagi.burst2._rt.arena.games import booster_gauntlet as G
from nagi.burst2._rt.arena.games import booster_gauntlet_bots as BB

GAME_ID = G.BoosterGauntlet.id
SEED_PREFIX = "arena-v3|booster_gauntlet"
SPLITS = ("calib", "eval", "variant_dev", "variant_sealed")
N_DEFAULT = {"calib": 32, "eval": 72, "variant_dev": 36, "variant_sealed": 36}
LADDER = BB.LADDER
CONTROLS = ("throttle", "gimbal", "fins", "legs")
HOLD = {k: "persistent" for k in CONTROLS}
SAFE_DEFAULT = {"throttle": "off", "gimbal": "0", "fins": "neutral", "legs": "stowed"}
T_CAP_S = G.MAX_ROUND_MS / 1000

# Frozen ladder medians of T_fail (s) on the calib split, base rules, 1-tick reply delay (play_delayed; docs/arena_v3/
# booster_gauntlet_calibration.json; scripts/booster_gauntlet_calibrate.py). Changing them is a rules-version change.
ANCHORS = {"bg1_naive": 12.525, "bg2_heuristic": 24.625, "bg3_planner": 43.825}   # g1.1, 1-tick-delay ladder (Amendment 3)


def seed_for(split: str, i: int) -> int:
    assert split in SPLITS, split
    return int(hashlib.sha256(f"{SEED_PREFIX}|{split}|{i}".encode()).hexdigest(), 16) % (2 ** 31)


def seeds(split: str, n: int | None = None) -> list[int]:
    return [seed_for(split, i) for i in range(N_DEFAULT[split] if n is None else n)]


def ladder_position(t_fail_s: float, anchors: dict | None = None, hi: float = 1.2) -> float:
    a = anchors or ANCHORS
    x0, x1, x2 = a["bg1_naive"], a["bg2_heuristic"], a["bg3_planner"]
    if t_fail_s <= x0:
        v = 0.0
    elif t_fail_s <= x1:
        v = 0.5 * (t_fail_s - x0) / (x1 - x0)
    else:
        v = 0.5 + 0.5 * (t_fail_s - x1) / (x2 - x1)
    return max(0.0, min(hi, v))


def level_of(t_fail_s: float) -> int:
    return 1 + int(min(t_fail_s, T_CAP_S - 0.001) // 10)


# ---------------------------------------------------------------- per-round outcome from a record


def round_outcome(rec: dict, focal: int = 0) -> dict:
    """Outcome of seat `focal` from a V2-format record (final render state + events)."""
    b = rec["final"]["boosters"][focal]
    censored = b["status"] == "censored" or (b["status"] == "flying" and rec["duration_ms"] >= G.MAX_ROUND_MS)
    surv = G.MAX_ROUND_MS if censored else (b["t_end_ms"] if b["t_end_ms"] is not None else rec["duration_ms"])
    return {"survival_s": surv / 1000, "censored": bool(censored), "level_at_fail": level_of(surv / 1000),
            "hops": b["landed"], "quality": b["quality"], "cause": b["cause"]}


def score_record(rec: dict) -> dict:
    """arena.v3.games Binding.score: {raw, score01, survival_s, censored, level_at_fail, game_score, ...}."""
    o = round_outcome(rec, 0)
    return {"raw": o["survival_s"], "score01": ladder_position(o["survival_s"], hi=1.0),
            "ladder_position": ladder_position(o["survival_s"]), "survival_s": o["survival_s"],
            "censored": o["censored"], "level_at_fail": o["level_at_fail"], "game_score": o["hops"],
            "quality": o["quality"], "cause": o["cause"]}


# ---------------------------------------------------------------- ladder rounds


def play_bot(bot_id: str, seed: int, variant: str | None = None, keep_frames: bool = False) -> dict:
    """One bot-only round through arena.v2.runner.V2Referee (lockstep). Adds 'outcome' and 'wall_s'."""
    from nagi.burst2._rt.arena.v2.runner import V2Referee
    g = G.BoosterGauntlet(variant)
    bot = BB.make_bot(bot_id)
    t0 = time.perf_counter()
    rec = V2Referee(g, [bot]).play(seed, keep_frames=keep_frames)
    rec["wall_s"] = time.perf_counter() - t0
    rec["outcome"] = round_outcome(rec, 0)
    return rec


def play_delayed(bot_id: str, seed: int, variant: str | None = None, delay: int = 1) -> dict:
    """The CALIBRATION round (FAIL_FIRST_BRIEF Amendment 3): the bot alone through the realtime runner's timing with a
    fixed reply delay of `delay` ticks (arena.v3.delay.Delayed; 0 = lockstep). The planner compensates its own delay
    (it plans from the exactly predicted state where its reply lands); naive and heuristic act on the stale
    observation as it is. Returns the outcome + 'n_decisions', 'hash_final', 'wall_s'."""
    from nagi.burst2._rt.arena.v3.delay import Delayed
    g = G.BoosterGauntlet(variant)
    w = Delayed(BB.make_bot(bot_id), v3_binding(), delay, g.decision_period_ms).bind(0, seed)
    t0 = time.perf_counter()
    s = g.reset(seed)
    n = 0
    while not g.done(s):
        w.see(g, s)
        s, _ = g.step(s, {0: dict(w.acts)}, g.decision_period_ms)
        n += 1
    o = g.outcome(s, 0)
    out = {"survival_s": o["survival_ms"] / 1000, "censored": o["censored"],
           "level_at_fail": level_of(o["survival_ms"] / 1000), "hops": o["hops"], "quality": o["quality"],
           "cause": o["cause"]}
    return {"outcome": out, "n_decisions": n, "hash_final": g.state_hash(s), "wall_s": time.perf_counter() - t0}


def win_rate(a: list[float], b: list[float], ca: list[bool] | None = None, cb: list[bool] | None = None) -> float:
    """Paired per-seed win rate of a over b: later failure wins, equal (same tick, or both censored) = 1/2."""
    w = 0.0
    for i, (x, y) in enumerate(zip(a, b)):
        if (ca and cb and ca[i] and cb[i]) or abs(x - y) < 1e-9:
            w += 0.5
        elif x > y:
            w += 1.0
    return w / len(a) if a else float("nan")


# ---------------------------------------------------------------- Arena v3 registry entry (for the integrator)


def v3_binding():
    """The arena.v3.games.Binding for this game. Admission (integrator): add `'booster_gauntlet':
    booster_gauntlet_arena.v3_binding` to arena.v3.games.FACTORIES and `l2_bot()` below to arena.v3.filler.l2_bot,
    then re-pin the harness (those files are hash-pinned, so this branch does not edit them)."""
    from nagi.burst2._rt.arena.v3.games import Binding
    return Binding(GAME_ID, lambda: G.BoosterGauntlet(None, True, False), tuple(CONTROLS), dict(HOLD),
                   dict(SAFE_DEFAULT), score=score_record)


def l2_bot():
    """The L2 (heuristic) rung for arena.v3.filler (filler prompts from dev-split states)."""
    return BB.make_bot("bg2_heuristic")


# ---------------------------------------------------------------- Arena v3 game binding (V3GameBinding spec)


class BoosterGauntletBinding:
    controls = CONTROLS
    hold = HOLD
    default = SAFE_DEFAULT

    def __init__(self, variant: str | None = None, announce: bool = True, sensors: bool = False):
        self.variant, self.announce, self.sensors = variant, announce, sensors
        self._eng = self.make()
        self.id = self._eng.id
        self.rules_id = self._eng.rules_id
        self.decision_period_ms = self._eng.decision_period_ms
        self.max_round_ms = self._eng.max_round_ms
        assert self.decision_period_ms == 250 and self.max_round_ms <= 90_000

    def make(self) -> G.BoosterGauntlet:
        return G.BoosterGauntlet(self.variant, self.announce, self.sensors, n_players=1)

    @property
    def engine(self) -> G.BoosterGauntlet:
        return self._eng

    def env_bots(self, seed: int) -> dict:
        return {}

    def reset(self, seed: int):
        return self._eng.reset(seed)

    def alive(self, s) -> bool:
        return s.boosters[0]["status"] == "flying" and not s.ended

    def queries(self, s):
        return self._eng.queries(s, 0, {})

    def multi_query(self, s):
        return self._eng.multi_query(s, 0)

    def step(self, s, actions: dict, dt_ms: int):
        return self._eng.step(s, actions, dt_ms)

    def done(self, s) -> bool:
        return self._eng.done(s)

    def state_hash(self, s) -> str:
        return self._eng.state_hash(s)

    def render_state(self, s) -> dict:
        return self._eng.render_state(s)

    def raw_score(self, s, seed: int) -> float:
        return self._eng.outcome(s, 0)["survival_ms"] / 1000

    def score01(self, s, seed: int) -> float:
        return ladder_position(self.raw_score(s, seed), hi=1.0)


# ---------------------------------------------------------------- rule variants: planner best-action flips (G5)

OPTIONS = {"throttle": G.THR_OPTS, "gimbal": G.GIM_OPTS, "fins": G.FIN_OPTS, "legs": G.LEG_OPTS}


def transfer(h: dict, src: G.Rules, dst: G.Rules, t_drop_ms: int) -> dict:
    """The same physical booster under other rules: relights USED this hop are kept (so the relights left follow
    the rule's per-hop allowance) and a lit level keeps its name (its thrust follows the rule's min throttle)."""
    h2 = dict(h)
    used = h["relights0"] - h["relights"]
    h2["relights0"] = G.relights_at(t_drop_ms, dst)
    h2["relights"] = max(0, h2["relights0"] - used)
    h2["twr"], h2["tmin"] = dst.twr_at(t_drop_ms), dst.t_min_at(t_drop_ms)
    if h2["lit"]:
        h2["thr_cmd"] = dst.thrust(h2["lvl"], h2)
    return h2


def sample_states(variant: str, seed_list: list[int], every: int = 6, max_t_ms: int = 60_000) -> list[tuple]:
    """States visited by the heuristic under the BASE and the VARIANT rules every `every` ticks (up to max_t_ms):
    [(seed, origin rules, GState(1 booster), heuristic memory)]."""
    out = []
    for seed in seed_list:
        for vid in (None, variant):
            g = G.BoosterGauntlet(vid)
            s, mem, i = g.reset(seed), {}, 0
            while not g.done(s) and s.t_ms < max_t_ms:
                o = BB.obs_num(g, s, 0)
                if i % every == every // 2:
                    out.append((seed, g.rules, G.GState(s.seed, s.k, s.t_ms, [dict(s.boosters[0])]), dict(mem)))
                a = BB.heuristic(o, BB.DEFAULTS, mem)
                s, _ = g.step(s, {0: a}, g.decision_period_ms)
                i += 1
    return out


def option_values(eng: G.BoosterGauntlet, s, mem: dict, control: str, hold: int = 2) -> dict:
    """{option: hop objective} with the option held `hold` ticks (the other controls from the heuristic), then the
    heuristic to the end of the hop (exact rollout)."""
    return {opt: BB.hop_rollout(eng, s, 0, BB.DEFAULTS, mem, {control: opt}, hold) for opt in OPTIONS[control]}


def _near(vals: dict, delta: int) -> set:
    """Near-optimal option set: every option whose objective is lexicographically within delta quality-buckets
    (2 % each) of the best, with the same landing flag."""
    best = max(vals.values())
    return {o for o, v in vals.items() if v[0] == best[0] and v[1] >= best[1] - delta}


def flip_table(variant: str, seed_list: list[int], every: int = 6, hold: int = 2, delta: int = 1,
               max_t_ms: int = 60_000) -> dict:
    """Planner-rollout best-action flips between base and variant rules on the same states: a control flips when its
    near-optimal option sets under the two rule sets are DISJOINT (handbook R2.15 'context-decisive'). Only states
    where both rule sets can still land the hop under some option count as informative for that control."""
    v = G.VARIANTS[variant]
    gb, gv = G.BoosterGauntlet(None), G.BoosterGauntlet(variant)
    rows = []
    for seed, origin, s, mem in sample_states(variant, seed_list, every, max_t_ms):
        h = s.boosters[0]
        t_drop = h["hop_k0"] * G.SUB_MS
        sb = G.GState(s.seed, s.k, s.t_ms, [transfer(h, origin, gb.rules, t_drop)])
        sv = G.GState(s.seed, s.k, s.t_ms, [transfer(h, origin, gv.rules, t_drop)])
        row = {"seed": seed, "t_ms": s.t_ms, "flips": [], "informative": []}
        for c in CONTROLS:
            vb, vv = option_values(gb, sb, mem, c, hold), option_values(gv, sv, mem, c, hold)
            if max(vb.values())[0] < 1 or max(vv.values())[0] < 1:
                continue
            row["informative"].append(c)
            if not (_near(vb, delta) & _near(vv, delta)):
                row["flips"].append(c)
        rows.append(row)
    inf = [r for r in rows if r["informative"]]
    n, k = len(inf), sum(bool(r["flips"]) for r in inf)
    return {"variant": variant, "split": v.split, "control_expected": v.control, "n_states": len(rows),
            "n_informative": n, "n_flip": k, "share": k / n if n else 0.0, "wilson95": wilson(k, n),
            "per_control": {c: sum(c in r["flips"] for r in inf) for c in CONTROLS},
            "per_control_informative": {c: sum(c in r["informative"] for r in inf) for c in CONTROLS},
            "delta_buckets": delta, "hold_ticks": hold, "every_ticks": every, "seeds": list(seed_list)}


def wilson(k: int, n: int, z: float = 1.959963984540054) -> list[float]:
    if n == 0:
        return [0.0, 1.0]
    p = k / n
    den = 1.0 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [max(0.0, c - h), min(1.0, c + h)]
