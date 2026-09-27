#!/usr/bin/env python3
"""Generate site/arena/v3.json (Arena v3 page data) from a Board results.json.

  python3 site/arena/build/make_v3.py --results PATH/TO/results.json [--board "Board 1 · run 2"] [--date 2026-09-27]
      [--confirm PATH/release_decision.json --confirm-results PATH/P2/results.json]

--confirm adds the preregistered Burst fresh-seed confirmation (vs Jev, seed indices 10–33) as its own block;
the Board 1 leaderboard itself stays on seeds 0–9.

Source of truth: the machine-readable report written by the research repo's
scripts/arena_v3_report.py (job b1_lx_01_v2 for Board 1 run 2). The page renders
everything from v3.json; no number on the page is typed by hand except the
frozen ladder anchors below (FAIL_FIRST_BRIEF Amendment 3) and the static prose.

Public naming: the one-forward multi-control readout formerly called "Chord" is
"Burst". Internal ids (t_dual/chord, ...) are kept unchanged; only display labels
change. The script fails loudly if any "Chord" string would reach the page, or
if a headline number disagrees with the per-seed data it can be recomputed from.
"""
import argparse
import hashlib
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
SITE_ARENA = os.path.dirname(HERE)
OUT = os.path.join(SITE_ARENA, "v3.json")

# Internal id -> (public label, one-line description, kind). Order = NAGI order, then externals.
ROSTER = {
    "t_dual/chord": ("T-dual Burst", "27B · Nagi-ENORMOUS Burst (T-dual weights) · Burst readout: one forward pass sets every control", "nagi"),
    "t_dual/kcall": ("T-dual K-call", "27B · same weights as T-dual Burst · one model call per control", "nagi"),
    "enormous_cl/kcall": ("ENORMOUS-CL", "27B · Nagi-ENORMOUS with closed-loop control training · one call per control", "nagi"),
    "enormous_old/kcall": ("ENORMOUS-old", "27B · the released Nagi-ENORMOUS, no in-domain training · one call per control", "nagi"),
    "jev/vendor_single": ("Jev", "Remote API, one request per decision · network time included · 1.1 s client timeout", "external"),
    "semif_4b/kcall": ("SemIf-4B", "OpenJev / SemIf Qwen3.5-4B · self-hosted on the same H100 path · one call per control", "external"),
}
LABEL_FIX = {"T-dual Chord": "T-dual Burst"}  # labels inside out_order strings

GAMES = [
    ("snake", "Snake Rush", "SnakeRush",
     "Keep a growing snake alive. The clock tightens three screws at once: a hunger timer that forces it to the food, "
     "wall cells that appear more and more often, and a speed that rises from 0.5 to 2 cells per tick.",
     "One control (direction), four options."),
    ("rotorwash_ramp", "Rotorwash-Ramp", "RotorwashRamp",
     "Fly a helicopter with a sling load through a cave. A collapse front chases from behind and accelerates, the roof "
     "comes down, the storm grows and engine power fades.",
     "Three simultaneous controls: collective, cyclic, winch. 240 Hz float physics, platform-pinned."),
    ("booster_gauntlet", "Booster Gauntlet", "BoosterGauntlet",
     "Land a rocket booster on a drone ship, again and again. Each touchdown re-drops it; thrust-to-weight rises and "
     "touchdown limits tighten with the clock. Each hop must land within 22 s of its drop.",
     "Multi-control timing: ignition, throttle, divert, legs. The less-seen probe (no-hover hoverslam, relights)."),
]

# Frozen 1-tick-delay ladder anchors: median T_fail (s) and level at failure, calibration split.
# Source: FAIL_FIRST_BRIEF.md Amendment 3 (and the per-game calibration JSONs).
ANCHORS = {
    "snake": {"naive": [13.75, 2], "heuristic": [27.75, 3], "planner": [49.88, 5], "seeds": 48},
    "rotorwash_ramp": {"naive": [11.14, 2], "heuristic": [24.49, 3], "planner": [45.83, 5], "seeds": 32},
    "booster_gauntlet": {"naive": [12.53, 2], "heuristic": [24.63, 3], "planner": [43.83, 5], "seeds": 32},
}

# Deadlines in the rules that many rounds end on exactly (reported, never re-scored).
WALLS = {
    "snake": (10.0, "10.0 s equals the opening hunger limit (40 ticks at 4 Hz)."),
    "booster_gauntlet": (22.0, "22.0 s equals the first hop's landing deadline (a hop must land within 22 s of its drop)."),
}

# Per-round failure causes behind the Booster 22.0 s cluster. Source: `score.cause` in the private round records
# (Board 1 run 2 and Burst P2), tallied 2026-09-27. Static prose, checked against the at-wall counts below.
BOOSTER_CAUSE = {
    "board": ("In Board 1 every round that ended at exactly 22.0 s (25 of 60, including all 10 of T-dual Burst's) was a "
              "hop timeout: the booster was still flying under control but had not landed its first hop. None of them "
              "was a crash.", {"t_dual/chord": 10}, 25),
    "confirm": "All 24 of Burst's rounds were hop timeouts at 22.0 s (still flying, first hop not landed). Jev crashed "
               "before 22.0 s in 23 of 24 rounds (landing without legs, torn legs or breakup) and timed out in 1.",
}

CLIP_DIR = "media/"

# Fresh-seed confirmation (Burst prereg §6.3, P2): V* vs Jev on seed indices 10–33. Shown as its own panel, never
# pooled with the Board 1 leaderboard (seeds 0–9 selected the champion, so pooling would keep winner's-curse bias).
CONFIRM_V = "enormous_burst/chord"   # internal id in the receipt; never written to v3.json
CONFIRM_J = "jev/vendor_single"
CONFIRM_SEEDS = range(10, 34)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def r(x, k=4):
    return None if x is None else round(float(x), k)


def confirmation(dec_path, res_path, games):
    """Copy the preregistered P2 numbers verbatim from release_decision.json (no re-rounding) and cross-check the
    per-game W and the composite against the per-seed out order in the P2 results.json. Fails loudly on any mismatch."""
    dec = json.load(open(dec_path))
    res = json.load(open(res_path))
    fr, c2 = dec["fresh_vs_jev"], dec["C2"]
    assert dec["V_star"] == CONFIRM_V, dec["V_star"]
    assert dec["RELEASE"] is True and dec["V_rt"]["passed"] and dec["R_RT"]["passed"] and dec["C1"]["passed"], "a gate failed"
    by_label = {v["label"]: k for k, v in res["players"].items()}
    at_wall = {}
    for g in games:
        rows = {int(s): {by_label[n]: t for t, n in row} for s, row in res["out_order"][g].items() if int(s) in CONFIRM_SEEDS}
        assert sorted(rows) == list(CONFIRM_SEEDS), (g, sorted(rows))
        w = [1.0 if x[CONFIRM_V] > x[CONFIRM_J] else 0.5 if x[CONFIRM_V] == x[CONFIRM_J] else 0.0 for x in rows.values()]
        assert len(w) == fr["n_by_game"][g] == c2["games"][g]["n"], (g, len(w))
        assert abs(statistics.mean(w) - fr["W"][g]) < 1e-12, (g, statistics.mean(w), fr["W"][g])
        assert abs(fr["W"][g] - c2["games"][g]["W"]) < 1e-15, g
        assert dec["V_rt"]["voids"]["fresh"][g]["void"] == 0 and dec["V_rt"]["voids"]["jev_fresh"][g]["void"] == 0, g
        wall = WALLS.get(g)
        at_wall[g] = None if not wall else {
            who: sum(1 for x in rows.values() if abs(x[pid] - wall[0]) < 1e-9) for who, pid in (("burst", CONFIRM_V), ("jev", CONFIRM_J))}
    assert at_wall["booster_gauntlet"] == {"burst": 24, "jev": 1}, at_wall["booster_gauntlet"]  # BOOSTER_CAUSE["confirm"]
    # no dropped index: Theta = mean over indices of the per-index game mean = mean of the per-game W
    assert abs(statistics.mean(fr["W"][g] for g in games) - fr["theta"]) < 1e-12
    retest = dec["screen_0_9"]["vs"]["t_dual/chord"]
    screen_jev = dec["screen_0_9"]["vs"][CONFIRM_J]
    est = dec["estimates"]
    return {
        "title": "Burst vs Jev on fresh seeds",
        "player": "Nagi-ENORMOUS Burst",
        "same_as": "T-dual Burst",
        "same_note": "The released name of T-dual Burst: the same weights and byte-identical prompts (variant A of the "
                     "preregistration), served on the same pinned H100 path.",
        "opponent": "Jev",
        "seeds": "10–33",
        "n_per_game": fr["n_by_game"],
        "estimand": "Θ = mean over the 3 games of the paired per-seed win rate of Burst against Jev (fail later = 1, "
                    "tie = ½); 95% t interval over the 24 seed indices (t with 23 df on the per-index game mean).",
        "theta": fr["theta"], "lb975": fr["lb975"], "ub975": fr["ub975"], "se": fr["se"], "df": fr["df"],
        "method": fr["method"],
        "gates": {
            "V_rt": {"passed": dec["V_rt"]["passed"], "replay_exact": dec["V_rt"]["replay_exact"],
                     "voids": sum(dec["V_rt"]["voids"][k][g]["void"] for k in ("fresh", "jev_fresh") for g in games),
                     "rule": "records replay exactly, every cell valid, seeds 0–9 equal Board 1, identical serving path"},
            "R_RT": {"passed": dec["R_RT"]["passed"], "H0": dec["R_RT"]["H0"], "lb975": dec["R_RT"]["lb975"],
                     "rule": "lower 97.5% bound > 0.35, i.e. not clearly worse than Jev"},
            "C1": {"passed": dec["C1"]["passed"], "lb975": dec["C1"]["lb975"], "signflip_p": dec["C1"]["signflip_p"],
                   "rule": "lower 97.5% bound > 0.50 and sign-flip p ≤ 0.025"},
        },
        "per_game": {g: {"W": c2["games"][g]["W"], "n": c2["games"][g]["n"], "lb": c2["games"][g]["lb"],
                         "signflip_p": c2["games"][g]["signflip_p"], "holm_alpha": c2["games"][g]["holm_alpha"],
                         "passed": c2["games"][g]["passed"],
                         "rmst": est["V_star_fresh"][g]["rmst60"], "rmst_ci95": est["V_star_fresh"][g]["rmst60_ci95"],
                         "rmst_jev": est["jev_fresh"][g]["rmst60"], "rmst_jev_ci95": est["jev_fresh"][g]["rmst60_ci95"],
                         "at_wall": at_wall[g],
                         "cause": BOOSTER_CAUSE["confirm"] if g == "booster_gauntlet" else None}
                     for g in games},
        "c2_rule": "tested only because C1 passed: Holm over the 3 games at one-sided 0.025, t and sign-flip "
                   "both at the Holm level",
        "screen_0_9": {"vs_jev": {"theta": screen_jev["theta"], "lb975": screen_jev["lb975"], "ub975": screen_jev["ub975"]},
                       "retest_vs_board1": {"theta": retest["theta"], "lb975": retest["lb975"], "ub975": retest["ub975"]},
                       "label": "screen, n = 10, not confirmatory"},
        "decision": "RELEASE",
        "receipts": {"release_decision.json": sha256(dec_path), "results.json": sha256(res_path)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--board", default="Board 1 · run 2")
    ap.add_argument("--date", default="2026-09-27")
    ap.add_argument("--seeds", default="0–9")
    ap.add_argument("--job", default="b1_lx_01_v2")
    ap.add_argument("--confirm", help="Burst P2 release_decision.json (fresh-seed confirmation vs Jev)")
    ap.add_argument("--confirm-results", help="Burst P2 results.json (per-seed cross-check of --confirm)")
    a = ap.parse_args()
    assert bool(a.confirm) == bool(a.confirm_results), "--confirm and --confirm-results go together"

    src = json.load(open(a.results))
    games = [g[0] for g in GAMES]
    assert src["games"] == games, src["games"]
    ids = list(ROSTER)
    assert set(src["players"]) == set(ids), sorted(src["players"])
    label = {i: ROSTER[i][0] for i in ids}
    by_label = {v["label"]: k for k, v in src["players"].items()}

    # out_order with public labels, and recompute every paired win rate from it.
    out_order = {}
    for g in games:
        out_order[g] = {}
        for seed, row in sorted(src["out_order"][g].items(), key=lambda kv: int(kv[0])):
            out_order[g][seed] = [[t, LABEL_FIX.get(n, n)] for t, n in row]
    t_fail = {g: {pid: {} for pid in ids} for g in games}
    for g in games:
        for seed, row in src["out_order"][g].items():
            for t, n in row:
                t_fail[g][by_label[n]][int(seed)] = t

    def pair(g, p, q):
        s = [1.0 if t_fail[g][p][k] > t_fail[g][q][k] else 0.5 if t_fail[g][p][k] == t_fail[g][q][k] else 0.0
             for k in t_fail[g][p] if k in t_fail[g][q]]
        return sum(s) / len(s), len(s)

    pairwise = {}
    for g in games:
        pairwise[g] = {}
        for p in ids:
            pairwise[g][p] = {}
            for q in ids:
                if p == q:
                    continue
                v, n = pair(g, p, q)
                assert abs(v - src["pairwise"][g][p][q]) < 1e-9, (g, p, q, v, src["pairwise"][g][p][q])
                assert n == 10 or a.seeds != "0–9", n
                pairwise[g][p][q] = r(v)

    players = []
    for pid in ids:
        sp = src["players"][pid]
        gs = {}
        for g in games:
            x = sp["games"][g]
            win = statistics.mean(pairwise[g][pid].values())
            assert abs(win - x["win_rate_all"]) < 1e-9, (pid, g, win, x["win_rate_all"])
            wall = WALLS.get(g)
            gs[g] = {
                "n": x["n"], "n_void": x["n_void"], "censored": x["censored"],
                "win": r(x["win_rate_all"]), "median_t": r(x["median_t"], 3), "rmst": r(x["rmst"], 3),
                "median_level": x["median_level"], "ladder": r(x["ladder_mean"], 3),
                "km": [[r(t, 3), r(s, 4)] for t, s in x["km"]],
                "alive_at": {k: r(v, 3) for k, v in x["alive_at"].items()},
                "p50_ms": r(x["latency_p50_ms"], 1), "fresh": r(x["fresh_share"], 3),
                "stale": x["stale"], "expiry": x["expiry_resets"],
                "t_fail": {str(k): t_fail[g][pid][k] for k in sorted(t_fail[g][pid])},
                "at_wall": (sum(1 for t in t_fail[g][pid].values() if abs(t - wall[0]) < 1e-9) if wall else None),
            }
        comp = statistics.mean(gs[g]["win"] for g in games)
        assert abs(comp - sp["composite_all"]) < 1e-9, (pid, comp, sp["composite_all"])
        players.append({
            "id": pid, "label": label[pid], "sub": ROSTER[pid][1], "kind": ROSTER[pid][2],
            "composite": r(sp["composite_all"]), "ci95": [r(c) for c in sp["composite_all_ci"]],
            "inflation_p50": sp.get("inflation_p50"), "in_domain": sp["in_domain"],
            "serving": {k: sp["serving_info"].get(k) for k in ("gpu", "weights_format", "kernels", "concurrency_mode")},
            "games": gs,
        })
    if a.seeds == "0–9":  # the Board 1 cause note is only valid for these records
        cnt = sum(p["games"]["booster_gauntlet"]["at_wall"] for p in players)
        assert cnt == BOOSTER_CAUSE["board"][2], cnt
        for pid, k in BOOSTER_CAUSE["board"][1].items():
            assert next(p for p in players if p["id"] == pid)["games"]["booster_gauntlet"]["at_wall"] == k, pid
    players.sort(key=lambda p: -p["composite"])
    for i, p in enumerate(players, 1):
        p["rank"] = i

    ch = src["champion"]
    champion = {
        "champion": label[ch["champion"]],
        "externals": [label[e] for e in ch["externals"]],
        "rule": "Mean over the 3 games of the paired per-seed win rate against the external competitors only; "
                "ties: sum of RMST ≤ 60 s, then mean level at failure.",
        "table": [{"label": label[t["player"]], "per_game": {g: r(v) for g, v in t["per_game"].items()},
                   "composite": r(t["composite_vs_externals"]), "rmst_sum": r(t["rmst_sum"], 2),
                   "mean_level": r(t["mean_level"], 2), "rank": t["rank"]} for t in ch["table"]],
    }

    # Showcase seed (PROTOCOL §A1.5): lower median of the champion's survival times, ties -> lowest index.
    game_rows = []
    for g, name, slug, what, controls in GAMES:
        tf = t_fail[g][ch["champion"]]
        order = sorted(tf.items(), key=lambda kv: (kv[1], kv[0]))
        lower_median = order[(len(order) - 1) // 2][1]
        seed = min(k for k, t in tf.items() if t == lower_median)
        wall = WALLS.get(g)
        game_rows.append({
            "id": g, "name": name, "what": what, "controls": controls,
            "anchors": ANCHORS[g],
            "wall": ({"t": wall[0], "note": wall[1], "cause": BOOSTER_CAUSE["board"][0] if g == "booster_gauntlet" else None}
                     if wall else None),
            "clip": {"src": f"{CLIP_DIR}v3-{slug}-burst.mp4", "poster": f"{CLIP_DIR}v3-{slug}-burst.jpg",
                     "seed_index": seed, "players": [label[ch["champion"]]] + [label[e] for e in ch["externals"]]},
        })

    out = {
        "meta": {
            "board": a.board, "date": a.date, "seeds": a.seeds,
            "n_per_game": max(p["games"][g]["n"] for p in players for g in games), "job": a.job,
            "suite": "v3.1", "cap_s": 60, "levels": 6, "tick_ms": 250, "stale_ms": 1000, "expire_ms": 1000,
            "void_lag_ms": 100, "voids": sum(p["games"][g]["n_void"] for p in players for g in games),
            "source_sha256": sha256(a.results),
            "generated_by": "site/arena/build/make_v3.py",
        },
        "games": game_rows,
        "players": players,
        "unranked": [{
            "label": "CLM-8B",
            "reason": "Not ranked. It failed its own conformance gate P3 before play (its README example scored outside "
                      "tolerance), so its scores cannot be mapped 1:1 to the option sets (preregistered rule D15). "
                      "The champion rule was therefore computed against the two external competitors that played.",
        }],
        "champion": champion,
        "pairwise": pairwise,
        "out_order": out_order,
    }
    if a.confirm:
        out["confirmation"] = confirmation(a.confirm, a.confirm_results, games)
    text = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    assert "chord" not in text.replace("t_dual/chord", "").lower(), "public label still says Chord"
    open(OUT, "w").write(text + "\n")
    print("wrote", OUT, len(text), "bytes; champion", champion["champion"], "; source", out["meta"]["source_sha256"][:12])


if __name__ == "__main__":
    main()
