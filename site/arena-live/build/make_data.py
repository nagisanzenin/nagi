#!/usr/bin/env python3
"""Generate site/arena-live/data.json from the committed Arena Live results.

Source of truth:
  bench/arena_live/results_vendors.json
  bench/arena_live/results_nagi_lines.json
Records hash (commit-reveal) is read from the research repo's .sha256 file
(pass --sha256-file to override); if it is unavailable the last published
value in data.json is kept.

Run from anywhere:  python3 site/arena-live/build/make_data.py
The script fails loudly if a headline claim on the page no longer matches
the results files.
"""
import argparse
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(SITE))
BENCH = os.path.join(REPO, "bench", "arena_live")
OUT = os.path.join(SITE, "data.json")
DEFAULT_SHA = os.path.expanduser(
    "~/Documents/Codex/2026-09-23/nghi/work/nagi-research-arena/docs/arena_live/"
    "records_20260925.tar.gz.sha256")

GAMES = [
    ("rotorwash", "Rotorwash"),
    ("lightcycle", "Lightcycle Royale"),
    ("stack", "Stack Attack"),
]

# Display names, sublabels and colours (colours match the videos).
VENDOR_ROSTER = [
    ("Nagi-ENORMOUS", "Nagi-ENORMOUS", "27B · open weights", "#19C3B0"),
    ("Jev", "Jev", "1.13.0 · API (network included)", "#FF8A3D"),
    ("SemIf", "OpenJev", "SemIf · Qwen3.5-4B", "#FFD23F"),
    ("Laya", "Laya", "Router v0.3.20", "#9B6BFF"),
]
NAGI_ROSTER = [
    ("Nagi-ENORMOUS", "Nagi-ENORMOUS", "27B · open weights", "#B06BFF"),
    ("Nagi-HUGE", "Nagi-HUGE", "12B · Gemma4 12B + rank-8 adapter", "#FF8A3D"),
    ("Nagi-BIG", "Nagi-BIG", "4B · Qwen3.5-4B + adapter", "#19C3B0"),
    ("Nagi-SMOL", "Nagi-SMOL", "0.5B · ModernBERT-large", "#7CDFFF"),
]


def build_run(results, roster):
    models = []
    for key, name, sub, color in roster:
        per_game = {}
        pts = wins = 0
        p50s = []
        replies = {"ok": 0, "late": 0, "invalid": 0, "error": 0}
        for g, _ in GAMES:
            m = results[g]["models"][key]
            pts += m["points"]
            wins += m["wins"]
            p50s.append(m["p50_ms"])
            for s, n in m["status"].items():
                replies[s] = replies.get(s, 0) + n
            entry = {"points": m["points"], "wins": m["wins"],
                     "p50_ms": m["p50_ms"], "p95_ms": m["p95_ms"],
                     "replies_ok": m["status"].get("ok", 0),
                     "replies_bad": sum(v for k, v in m["status"].items() if k != "ok")}
            for extra in ("survival_s", "survival_median_s", "survival_max_s", "score_median", "crashes"):
                if extra in m:
                    entry[extra] = m[extra]
            per_game[g] = entry
        models.append({"key": key, "name": name, "sub": sub, "color": color,
                       "points": pts, "wins": wins,
                       "p50_ms_min": min(p50s), "p50_ms_max": max(p50s),
                       "p50_ms_median_of_games": statistics.median(p50s),
                       "replies": replies, "games": per_game})
    models.sort(key=lambda m: (-m["points"], -m["wins"]))
    paired = {}
    for g, _ in GAMES:
        pv = results[g].get("paired_vs_Nagi-ENORMOUS", {})
        paired[g] = {next(n for k, n, *_ in roster if k == opp): v for opp, v in pv.items()}
    rounds = {g: results[g]["rounds"] for g, _ in GAMES}
    return {"models": models, "paired_vs_enormous": paired, "rounds": rounds}


def check(cond, msg):
    if not cond:
        raise SystemExit("CLAIM MISMATCH: " + msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha256-file", default=DEFAULT_SHA)
    a = ap.parse_args()

    vend = json.load(open(os.path.join(BENCH, "results_vendors.json")))
    lines = json.load(open(os.path.join(BENCH, "results_nagi_lines.json")))

    sha = None
    if os.path.exists(a.sha256_file):
        sha = open(a.sha256_file).read().split()[0]
    elif os.path.exists(OUT):
        sha = json.load(open(OUT)).get("records", {}).get("sha256")
    check(sha and len(sha) == 64, "records sha256 not found")

    data = {
        "date": "2026-09-25",
        "scoring": {"points_per_round": [3, 2, 1, 0], "rounds_per_game": 10,
                    "max_points": 90, "max_wins": 30},
        "games": [{"id": g, "name": n} for g, n in GAMES],
        "records": {"file": "records_20260925.tar.gz", "sha256": sha},
        "sources": ["bench/arena_live/results_vendors.json",
                    "bench/arena_live/results_nagi_lines.json"],
        "vendors": build_run(vend, VENDOR_ROSTER),
        "nagi_lines": build_run(lines, NAGI_ROSTER),
    }

    # Page claims, checked against the source files.
    v = {m["name"]: m for m in data["vendors"]["models"]}
    e = v["Nagi-ENORMOUS"]
    check((e["points"], e["wins"]) == (83, 23), "ENORMOUS vs vendors 83/90, 23 wins")
    check(data["vendors"]["models"][0]["name"] == "Nagi-ENORMOUS", "ENORMOUS ranks first")
    rw_e, rw_j = e["games"]["rotorwash"], v["Jev"]["games"]["rotorwash"]
    check(rw_e["points"] == rw_j["points"] == 25, "Rotorwash 25-25 tie")
    check(data["vendors"]["paired_vs_enormous"]["rotorwash"]["Jev"]["survival_w_l"] == [9, 1], "airborne longer 9/10")
    check((rw_e["survival_median_s"], rw_j["survival_median_s"]) == (35.8, 13.8), "median 35.8 vs 13.8 s")
    for n in ("OpenJev", "Laya"):
        check(v[n]["games"]["rotorwash"]["survival_max_s"] <= 3.0, n + " crashes in ~3 s")
    check(e["games"]["lightcycle"]["wins"] == 8, "Lightcycle 8/10")
    check(data["vendors"]["paired_vs_enormous"]["lightcycle"]["Jev"]["points_w_l_t"] == [10, 0, 0], "beats Jev all 10")
    check(e["games"]["stack"]["wins"] == 10, "Stack 10/10")
    nl = {m["name"]: (m["points"], m["wins"]) for m in data["nagi_lines"]["models"]}
    check(nl == {"Nagi-ENORMOUS": (76, 21), "Nagi-HUGE": (65, 6), "Nagi-BIG": (39, 3), "Nagi-SMOL": (7, 0)},
          "Nagi lines totals")
    for run in ("vendors", "nagi_lines"):
        for m in data[run]["models"]:
            r = m["replies"]
            check(r["late"] == r["invalid"] == r["error"] == 0, run + " zero late/invalid/error")

    with open(OUT, "w") as f:
        json.dump(data, f, indent=1)
        f.write("\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
