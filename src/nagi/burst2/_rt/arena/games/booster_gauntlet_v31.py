"""BOOSTER GAUNTLET, Arena v3.1: rules g1.2 + the K3 round score (docs/arena_v31/README.md).

Why (docs/research_insights/next_control/C_experiments.md 0 F4/F8, 4.2; BOOSTER_STALL_20260927.md): under the v3
score (later failure wins) a booster that never lands but hovers until the 22 s hop timeout beats every player that
tries to land and crashes. K3 has no time term, so stalling buys nothing.

K3 (per round, focal seat 0):
    Y = hops landed before failure within the 60 s cap + partial credit for the failing hop,
    partial = 0.5 * clip(2 - E, 0, 1),
    E = the max normalised touchdown error of the failing hop ON THE DECK (booster_gauntlet.touchdown_errors: |dx| /
        zone, |vy_rel| / sink limit, |vx_rel| / drift limit, |tilt| / tilt limit, |rate| / rate limit; >= 2 when the
        legs were not fully down), E = inf (partial 0) when there is no deck touchdown: hop_timeout, an in-flight
        failure (max_q, breakup, legs_torn, tumble, flameout-then-anything-in-flight), splashdown, or a censored round.
    So partial is in [0, 0.5]: 0 at E >= 2 (legs not down, or some error at twice its limit); 0.5 at E <= 1 (only at
    rounding edges, since a touchdown within every limit is a landing and counts in hops).
The decisional metric stays the paired per-seed win rate on Y (ties 1/2); the paired mean of Y is reported too.
score01 / ladder_position map Y through the frozen v3.1 anchors (K3 means of naive / heuristic / planner on the calib
split, 1-tick delay; docs/arena_v31/booster_k3_calibration.json) exactly as the v3 score maps T_fail.

Scores are recomputed from records wherever possible: every Booster record replays bit-exactly on any platform
(integer engine; C F1), so `rescore_record` replays the applied controls, checks every recorded frame hash (fail
closed) and scores the replayed final state. A g1.2 record also carries td.err in its final render, so
`score_record_k3` can score it from the record alone (the runner's in-job score) and the replay cross-checks it.
The v3 survival score (booster_gauntlet_arena.score_record) is unchanged and stays the score of v3 (g1.1) records.

Stall bots (C 4.2's gaming check; none reads the rules; attitude from the heuristic's PD helper so they do not
tumble), verbatim from next_control/scripts/booster_scoring_sim.py:
  st_hover   ignite after the release lock, then mid while sinking, min while rising (the T-dual throttle mix);
             legs deploy at 2.5 s.
  st_min     ignite, then min forever.     st_mid   ignite, then mid forever (climbs away).
  st_cut{c}  st_hover until c s after the drop, then engine off: stall-then-crash.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from nagi.burst2._rt.arena.games import booster_gauntlet as G
from nagi.burst2._rt.arena.games import booster_gauntlet_arena as BA
from nagi.burst2._rt.arena.games import booster_gauntlet_bots as BB
from nagi.burst2._rt.arena.v2.bots import Bot

RULES_VERSION = "g1.2"
GAME_ID = "booster_gauntlet_v31"
SCORING = "K3"
ROOT = Path(__file__).resolve().parents[3]
CALIBRATION = ROOT / "docs/arena_v31/booster_k3_calibration.json"

# Frozen K3 anchors (mean Y per rung, calib split n = 32, 1-tick reply delay, g1.2 = g1.1 physics). Written by
# scripts/arena_v31_calibrate.py into CALIBRATION; tests/test_arena_v31.py asserts these equal the JSON. Changing them
# is a rules-version change (as booster_gauntlet_arena.ANCHORS).
ANCHORS_K3 = {"bg0_idle": 0.0, "bg1_naive": 0.1698, "bg2_heuristic": 0.6588, "bg3_planner": 2.5018}

LADDER = ("bg0_idle", "bg1_naive", "bg2_heuristic", "bg3_planner")
STALL_BOTS = ("st_hover", "st_min", "st_mid", "st_cut6", "st_cut9", "st_cut10", "st_cut11")


# ================================================================== K3
def k3_value(hops: int, E: float) -> float:
    """Y = hops + 0.5 * clip(2 - E, 0, 1); E = inf (no deck touchdown) gives no partial credit."""
    pc = 0.0 if not math.isfinite(E) else 0.5 * min(1.0, max(0.0, 2.0 - E))
    return hops + pc


def _failing_E(td_err: dict | None, cause: str | None, censored: bool) -> float:
    if censored or td_err is None or cause not in G.TD_CAUSES:
        return math.inf
    return float(td_err["E"])


def k3_from_state(g: G.BoosterGauntlet, s: G.GState, p: int = 0) -> dict:
    """K3 outcome of booster p from an engine state (any rules version: the physics and td are the same)."""
    h = s.boosters[p]
    o = g.outcome(s, p)
    td = h["td"]
    ftd = td if (td is not None and td["hop"] == h["hop"] and not td["ok"]) else None
    err = None
    if ftd is not None:
        err = G.touchdown_errors(g.rules, ftd, g.scenario(s.seed).zone[min(ftd["k"], G.N_SUB - 1)], h["legs"])
    E = _failing_E(err, o["cause"], o["censored"])
    return _outcome(o["hops"], E, o["survival_ms"] / 1000, o["censored"], o["cause"], o["quality"],
                    ftd is not None, err)


def _outcome(hops, E, survival_s, censored, cause, quality, touchdown, err) -> dict:
    y = k3_value(hops, E)
    return {"k3": y, "hops": hops, "partial": y - hops, "E": E if math.isfinite(E) else None,
            "touchdown": bool(touchdown), "td_err": err, "survival_s": survival_s, "censored": bool(censored),
            "level_at_fail": BA.level_of(survival_s), "cause": cause, "quality": quality}


def k3_from_render(rec: dict, focal: int = 0) -> dict:
    """K3 outcome from a g1.2 record's final render alone (td.err present). Raises ValueError on a record that does
    not carry td.err for a failing deck touchdown (g1.1 records: use rescore_record, which replays)."""
    b = rec["final"]["boosters"][focal]
    o = BA.round_outcome(rec, focal)
    td = b.get("td")
    ftd = td if (td is not None and td["hop"] == b["hop"] and not td["ok"]) else None
    if ftd is not None and "err" not in ftd:
        raise ValueError(f"record {rec.get('rules_id')} has no td.err (rules g1.1?): rescore by replay")
    err = ftd["err"] if ftd is not None else None
    E = _failing_E(err, o["cause"], o["censored"])
    return _outcome(o["hops"], E, o["survival_s"], o["censored"], o["cause"], o["quality"], ftd is not None, err)


def ladder_position_k3(y: float, anchors: dict | None = None, hi: float = 1.2) -> float:
    """Y mapped piecewise-linearly through the frozen K3 anchors: naive -> 0, heuristic -> 0.5, planner -> 1 (below
    naive 0; above planner the heuristic->planner slope continued), clipped to [0, hi] (as the v3 ladder_position)."""
    a = anchors or ANCHORS_K3
    x0, x1, x2 = a["bg1_naive"], a["bg2_heuristic"], a["bg3_planner"]
    if y <= x0:
        v = 0.0
    elif y <= x1:
        v = 0.5 * (y - x0) / (x1 - x0)
    else:
        v = 0.5 + 0.5 * (y - x1) / (x2 - x1)
    return max(0.0, min(hi, v))


def _score_dict(o: dict, source: str) -> dict:
    return {"raw": o["k3"], "score01": ladder_position_k3(o["k3"], hi=1.0), "ladder_position": ladder_position_k3(o["k3"]),
            "k3": o["k3"], "hops": o["hops"], "partial": o["partial"], "E": o["E"], "touchdown": o["touchdown"],
            "survival_s": o["survival_s"], "censored": o["censored"], "level_at_fail": o["level_at_fail"],
            "game_score": o["hops"], "quality": o["quality"], "cause": o["cause"], "scoring": SCORING,
            "source": source}


def score_record_k3(rec: dict) -> dict:
    """arena.v3.games Binding.score for Arena v3.1 (the runner calls it on the finished record). g1.2 records score
    from the record's final render; any other supported record is replayed (rescore_record) and fails closed."""
    if parse_rules_id(rec["rules_id"])["version"] == RULES_VERSION:
        return _score_dict(k3_from_render(rec), "record")
    r = rescore_record(rec)
    if not r["replay_ok"]:
        raise ValueError(f"replay failed: {r['replay']}")
    return r["k3"]


# ================================================================== records: parse, replay, rescore
def parse_rules_id(rid: str) -> dict:
    """'booster_gauntlet:g1.1:base:announced:L0:250ms[:p1]' -> fields."""
    parts = rid.split(":")
    if len(parts) not in (6, 7) or parts[0] != G.BoosterGauntlet.id:
        raise ValueError(f"not a Booster Gauntlet rules_id: {rid!r}")
    return {"game": parts[0], "version": parts[1], "variant": None if parts[2] == "base" else parts[2],
            "announce": parts[3] == "announced", "sensors": parts[4] == "L1", "period_ms": int(parts[5][:-2]),
            "prompt_style": parts[6] if len(parts) == 7 else G.DEFAULT_PROMPT_STYLE}


def engine_for(rid: str) -> G.BoosterGauntlet:
    """The engine that played rules_id `rid` (physics only: the prompt style is text, so replay uses the base text;
    ValueError for a rules version this engine cannot replay, e.g. Board 1 v1 g1.0)."""
    f = parse_rules_id(rid)
    if f["version"] not in G.RULES_VERSIONS:
        raise ValueError(f"rules version {f['version']} is not replayable by this engine ({G.RULES_VERSIONS})")
    return G.BoosterGauntlet(f["variant"], f["announce"], f["sensors"], decision_period_ms=f["period_ms"],
                             rules_version=f["version"])


def replay_record(rec: dict) -> tuple:
    """Replay the applied controls on the integer engine. Every recorded frame hash must match and be reached.
    Returns (engine, final state, {tick: state}, report)."""
    g = engine_for(rec["rules_id"])
    s = g.reset(rec["seed"])
    frames = {f["t_ms"]: f["hash"] for f in rec["frames"]}
    acts: dict = {}
    for d in rec["decisions"]:
        acts.setdefault(d["t_ms"], {})[d["key"]] = d["applied"]
    states, t = {0: s}, 0
    bad = 0 if frames.get(0) == g.state_hash(s) else 1
    while not g.done(s):
        s, _ = g.step(s, {0: acts.get(t, {})}, g.decision_period_ms)
        t += g.decision_period_ms
        states[t // g.decision_period_ms] = s
        if t in frames and frames[t] != g.state_hash(s):
            bad += 1
    reached = {k * g.decision_period_ms for k in states}
    unreached = sum(1 for ft in frames if ft not in reached)
    rep = {"frames": len(frames), "mismatch": bad, "unreached": unreached, "ok": bad == 0 and unreached == 0
           and len(frames) > 0}
    return g, s, states, rep


def rescore_record(rec: dict) -> dict:
    """Replay a record and score it under BOTH rules: the v3 survival score (old) and K3. Fail closed: a void round
    or a replay mismatch gives no score. Cross-checks: the replayed v3 outcome equals the recorded v3 score fields
    when the record carries them; a g1.2 record's render K3 equals the replayed K3."""
    out = {"rules_id": rec["rules_id"], "seed": rec["seed"], "seed_index": rec.get("seed_index"),
           "void": rec.get("void"), "replay_ok": False}
    if rec.get("void"):
        return out
    try:
        g, s, _, rep = replay_record(rec)
    except ValueError as e:
        return dict(out, replay={"error": str(e)})
    out["replay"] = rep
    if not rep["ok"]:
        return out
    o = g.outcome(s, 0)
    old = {"survival_s": o["survival_ms"] / 1000, "censored": o["censored"], "cause": o["cause"], "hops": o["hops"],
           "ladder_position": BA.ladder_position(o["survival_ms"] / 1000)}
    k3 = _score_dict(k3_from_state(g, s, 0), "replay")
    checks = {"final_hash": g.state_hash(s) == rec["frames"][-1]["hash"] if rec["frames"] else False}
    sc = rec.get("score") or {}
    if "survival_s" in sc:
        checks["old_equals_record"] = (abs(sc["survival_s"] - old["survival_s"]) < 1e-9
                                       and sc.get("game_score", old["hops"]) == old["hops"]
                                       and sc.get("cause", old["cause"]) == old["cause"])
    if parse_rules_id(rec["rules_id"])["version"] == RULES_VERSION:
        kr = k3_from_render(rec)
        checks["render_k3_equals_replay"] = kr["k3"] == k3["k3"] and kr["E"] == k3["E"]
    return dict(out, replay_ok=True, old=old, k3=k3, checks=checks, all_checks=all(checks.values()))


def record_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ================================================================== paired statistics
def win(a: float, b: float) -> float:
    return 1.0 if a > b else 0.5 if a == b else 0.0


def paired_w(a: dict, b: dict) -> dict:
    """Paired per-seed win rate of a over b on their common seed indices ({index: Y}), ties 1/2."""
    idx = sorted(set(a) & set(b))
    w = [win(a[i], b[i]) for i in idx]
    return {"n": len(idx), "W": sum(w) / len(w) if w else None, "ties": sum(1 for v in w if v == 0.5),
            "wins": sum(1 for v in w if v == 1.0), "losses": sum(1 for v in w if v == 0.0), "indices": idx}


# ================================================================== stall bots + calibration rounds
class StallBot(Bot):
    """C 4.2 stall bots (verbatim logic of next_control/scripts/booster_scoring_sim.py StallBot)."""

    def __init__(self, bot_id: str):
        super().__init__(bot_id)
        assert bot_id in STALL_BOTS, bot_id
        self.cut = float(bot_id[6:]) if bot_id.startswith("st_cut") else None

    def see(self, game, state):
        super().see(game, state)
        self._a = None

    def _decide(self) -> dict:
        g, s, p = self.game.engine, self.state, self.seat
        o = BB.obs_num(g, s, p)
        age = o["age"]
        a = {"legs": "deploy" if age >= 2.5 else "stowed"}
        mode = self.bot_id
        if mode.startswith("st_cut"):
            mode = "st_hover" if age < self.cut else "off"
        if mode == "off":
            a["throttle"] = "off"
        elif mode == "st_min":
            a["throttle"] = "min"
        elif mode == "st_mid":
            a["throttle"] = "mid"
        else:
            a["throttle"] = "mid" if o["vyr"] < 0.0 else "min"
        a["gimbal"], a["fins"] = BB.attitude(o, 0.0, bool(o["lit"]) and o["thr"] > 50_000.0)
        return a

    def choose(self, q):
        if self._a is None:
            self._a = self._decide()
        v = self._a.get(q.key, q.default)
        return v if v in q.options else q.default


def make_bot(bot_id: str):
    return StallBot(bot_id) if bot_id in STALL_BOTS else BB.make_bot(bot_id)


def play_calib(bot_id: str, seed: int, delay: int = 1, rules_version: str = RULES_VERSION) -> dict:
    """One calibration round (bot alone, realtime runner timing with a fixed reply delay; arena.v3.delay.Delayed, as
    booster_gauntlet_arena.play_delayed and C's scoring sim): the outcome under both scores + the final state hash."""
    from nagi.burst2._rt.arena.v3.delay import Delayed
    g = G.BoosterGauntlet(None, rules_version=rules_version)
    w = Delayed(make_bot(bot_id), BA.v3_binding(), delay, g.decision_period_ms).bind(0, seed)
    s = g.reset(seed)
    while not g.done(s):
        w.see(g, s)
        s, _ = g.step(s, {0: dict(w.acts)}, g.decision_period_ms)
    o = k3_from_state(g, s, 0)
    h = s.boosters[0]
    return {"bot": bot_id, "seed": seed, "delay": delay, "survival_s": o["survival_s"], "censored": o["censored"],
            "cause": o["cause"], "hops": o["hops"], "drop_s": h["hop_k0"] * G.SUB_MS / 1000,
            "touchdown": o["touchdown"], "E": o["E"], "k3": o["k3"], "hash_final": g.state_hash(s)}


def load_calibration(path: Path = CALIBRATION) -> dict:
    return json.loads(Path(path).read_text())


# ================================================================== Arena v3.1 registry entry
def v31_binding():
    """arena.v3.games Binding 'booster_gauntlet_v31': g1.2 engine at L0, the v3 controls / hold / safe defaults, the
    v3 seed schedule (seed_game 'booster_gauntlet': same seeds as every v3 Booster cell, so records pair by index),
    and the K3 score."""
    from nagi.burst2._rt.arena.v3.games import Binding
    return Binding(GAME_ID, lambda: G.BoosterGauntlet(None, True, False, rules_version=RULES_VERSION),
                   tuple(BA.CONTROLS), dict(BA.HOLD), dict(BA.SAFE_DEFAULT), score=score_record_k3,
                   seed_game=BA.GAME_ID)
