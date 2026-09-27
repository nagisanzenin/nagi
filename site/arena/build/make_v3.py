#!/usr/bin/env python3
"""Generate site/arena/v3.json (Arena v3 page data) from a Board results.json.

  python3 site/arena/build/make_v3.py --results PATH/TO/results.json [--board "Board 1 · run 2"] [--date 2026-09-27]

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
    "t_dual/chord": ("T-dual Burst", "27B · Nagi-ENORMOUS line, T-dual weights · Burst readout: one forward pass sets every control", "nagi"),
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

CLIP_DIR = "media/"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def r(x, k=4):
    return None if x is None else round(float(x), k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--board", default="Board 1 · run 2")
    ap.add_argument("--date", default="2026-09-27")
    ap.add_argument("--seeds", default="0–9")
    ap.add_argument("--job", default="b1_lx_01_v2")
    a = ap.parse_args()

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
            "wall": {"t": wall[0], "note": wall[1]} if wall else None,
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
    text = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    assert "chord" not in text.replace("t_dual/chord", "").lower(), "public label still says Chord"
    open(OUT, "w").write(text + "\n")
    print("wrote", OUT, len(text), "bytes; champion", champion["champion"], "; source", out["meta"]["source_sha256"][:12])


if __name__ == "__main__":
    main()
