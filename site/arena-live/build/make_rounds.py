#!/usr/bin/env python3
"""Derive per-round tables for the Arena Live page (site/arena-live/rounds.json).

Input: the canonical-seat records (private; research repo runs/arena_live/<lineup>_canon/<game>/*.json).
Output: derived aggregates only — placements, points, game outcomes, action frequencies and
latency histograms. No observation texts, no frames, no engine code.

  python3 site/arena-live/build/make_rounds.py [--canon-root PATH]

Fails loudly if the per-round points do not add up to bench/arena_live/results_*.json.
"""
import argparse, collections, glob, json, math, os, statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(SITE))
DEFAULT_ROOT = os.path.expanduser("~/Documents/Codex/2026-09-23/nghi/work/nagi-research-arena/runs/arena_live")
NAME = {"SemIf": "OpenJev"}
GAMES = ("rotorwash", "lightcycle", "stack")
LAT_EDGES = [round(10 * 2 ** (i / 2), 1) for i in range(15)]  # 10 ms .. 1.28 s, half-octave bins


def round_points(ranking):
    pts, place, ahead = {}, {}, 0
    for tier in ranking:
        for p in tier:
            pts[p], place[p] = max(0, 3 - ahead), ahead + 1
        ahead += len(tier)
    return pts, place


def sign_p(w, l):
    n = w + l
    if n == 0:
        return None
    k = min(w, l)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def pct(xs, q):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))], 1)


def lineup(root, lu):
    out = {}
    for g in GAMES:
        recs = [json.load(open(f)) for f in glob.glob(f"{root}/{lu}_canon/{g}/{g}_[0-9]*.json")]
        recs = [r for r in recs if "agents" in r]
        recs.sort(key=lambda r: r["meta"]["round"])
        ag = [NAME.get(a, a) for a in recs[0]["agents"]]
        rounds = []
        lat = collections.defaultdict(list)
        acts = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
        for r in recs:
            pts, place = round_points(r["ranking"])
            row = {"round": r["meta"]["round"], "seed": r["seed"], "duration_s": round(r["duration_ms"] / 1000, 2),
                   "players": {}}
            for p, a in enumerate(ag):
                row["players"][a] = {"place": place[p], "points": pts[p]}
            for d in r["decisions"]:
                a = ag[d["player"]]
                if d["latency_ms"] is not None:
                    lat[a].append(d["latency_ms"])
                acts[a][d["key"]][d["applied"]] += 1
            ev = collections.defaultdict(collections.Counter)
            for e in r["events"]:
                if e.get("player") is not None:
                    ev[e["player"]][e["kind"]] += 1
            if g == "rotorwash":
                hs = r["frames"][-1]["render"]["helis"]
                end = {e["player"]: e for e in r["events"] if e["kind"] == "crash"}
                for p, a in enumerate(ag):
                    c = end.get(p)
                    row["players"][a].update(
                        score_m=round(hs[p]["score"], 1),
                        airborne_s=round((c["t_ms"] if c else r["duration_ms"]) / 1000, 1),
                        end=(c["data"]["cause"] if c else "time cap"),
                        vortex_ring=ev[p]["vortex_ring"], rpm_droop=ev[p]["rpm_droop"])
            elif g == "lightcycle":
                el = {e["player"]: e for e in r["events"] if e["kind"] == "eliminated"}
                for p, a in enumerate(ag):
                    e = el.get(p)
                    cause = e["data"]["cause"] if e else "survived"
                    if cause.startswith("trail_of_"):
                        q = int(cause.rsplit("_", 1)[1])
                        cause = "own trail" if q == p else "rival trail"
                    row["players"][a].update(out_s=round(e["t_ms"] / 1000, 2) if e else None, end=cause,
                                             boosts=ev[p]["boost"], near_misses=ev[p]["near_miss"])
            else:
                fr = r["frames"][-1]["render"]
                for p, a in enumerate(ag):
                    died = fr["died_ms"][p]
                    row["players"][a].update(lines=fr["lines"][p], sent=fr["sent"][p],
                                             out_s=round(died / 1000, 2) if died is not None else None,
                                             pieces=sum(1 for d in r["decisions"] if d["player"] == p and d["key"] == "column"))
            rounds.append(row)
        # per-model summaries
        models = {}
        for a in ag:
            xs = lat[a]
            hist = [0] * (len(LAT_EDGES) + 1)
            for x in xs:
                hist[sum(x >= e for e in LAT_EDGES)] += 1
            models[a] = {"n_decisions": len(xs), "lat_p50": pct(xs, .5), "lat_p90": pct(xs, .9),
                         "lat_p99": pct(xs, .99), "lat_max": round(max(xs), 1), "lat_hist": hist,
                         "actions": {k: dict(v) for k, v in acts[a].items()}}
        # paired sign tests vs ENORMOUS on round points (+ Rotorwash airborne time)
        ref = "Nagi-ENORMOUS"
        tests = {}
        for a in ag:
            if a == ref:
                continue
            w = sum(r["players"][ref]["points"] > r["players"][a]["points"] for r in rounds)
            l = sum(r["players"][ref]["points"] < r["players"][a]["points"] for r in rounds)
            t = {"w": w, "l": l, "t": len(rounds) - w - l, "p": sign_p(w, l)}
            if g == "rotorwash":
                sw = sum(r["players"][ref]["airborne_s"] > r["players"][a]["airborne_s"] for r in rounds)
                sl = sum(r["players"][ref]["airborne_s"] < r["players"][a]["airborne_s"] for r in rounds)
                t["airborne"] = {"w": sw, "l": sl, "p": sign_p(sw, sl)}
            tests[a] = t
        out[g] = {"agents": ag, "rounds": rounds, "models": models, "paired_vs_enormous": tests}
    # Holm–Bonferroni over this lineup's points tests (one family per lineup)
    fam = [(g, a) for g in GAMES for a in out[g]["paired_vs_enormous"]]
    ps = sorted(fam, key=lambda k: out[k[0]]["paired_vs_enormous"][k[1]]["p"])
    m, run = len(ps), 0.0
    for i, (g, a) in enumerate(ps):
        t = out[g]["paired_vs_enormous"][a]
        run = max(run, min(1.0, (m - i) * t["p"]))
        t["p_holm"] = run
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--canon-root", default=DEFAULT_ROOT)
    a = ap.parse_args()
    data = {"lat_edges_ms": LAT_EDGES, "vendors": lineup(a.canon_root, "vendors"),
            "nagi_lines": lineup(a.canon_root, "nagi_lines")}
    # consistency with the published results
    for lu, fn in (("vendors", "results_vendors.json"), ("nagi_lines", "results_nagi_lines.json")):
        res = json.load(open(os.path.join(REPO, "bench", "arena_live", fn)))
        for g in GAMES:
            for key, m in res[g]["models"].items():
                n = NAME.get(key, key) if lu == "vendors" else key
                tot = sum(r["players"][n]["points"] for r in data[lu][g]["rounds"])
                if tot != m["points"]:
                    raise SystemExit(f"MISMATCH {lu}/{g}/{n}: {tot} != {m['points']}")
    json.dump(data, open(os.path.join(SITE, "rounds.json"), "w"), separators=(",", ":"))
    print("wrote rounds.json", os.path.getsize(os.path.join(SITE, "rounds.json")), "bytes")


if __name__ == "__main__":
    main()
