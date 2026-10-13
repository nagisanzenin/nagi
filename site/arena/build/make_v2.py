#!/usr/bin/env python3
"""Generate site/arena/v2.json (Game Arena: Nagi Burst V2 vs V1 vs Jev) from the published receipts.

  python3 site/arena/build/make_v2.py            # write site/arena/v2.json
  python3 site/arena/build/make_v2.py --check    # rebuild in memory; fail if v2.json differs or any check fails

Inputs (all under bench/burst_v2/receipts/, sha256 recorded in the output):
  arena_v2.json          frozen M4 sealed eval: per-seed V2 and V1 scores (out_order) and the receipted gate A
  CANDIDATE.json         the frozen candidate (Snake policy rule and its search budget)
  jev1s_<game>.json      single-stream Jev re-play on the same eval seeds (pinned in PREREG_V2G §3 before V2 played)
  jev_pair_check.json    the M4 V1 comparator check applied to the 72 Jev records (replay, prompts, score)

Metric per game = the M4 gate-A metric (PREREG_V2G §5.3): Snake Rush survival seconds (cap 60), Rotorwash-Ramp
K3-RR2.1 Y, Booster Gauntlet K3 Y. Head-to-head per seed: 1 if higher, 1/2 if equal, 0 if lower; W = mean.
The gate-A form: t_{n-1} lower 97.5% bound of W > 1/2 and exact one-sided sign test P(Bin(k, 1/2) >= wins) <= 0.025.

Claim labels are fixed by the preregistration, not by the data:
  V2 vs V1  -> "gate A" (the preregistered release gate; PASS/FAIL as receipted);
  V2 vs Jev, V1 vs Jev -> "descriptive" (PREREG_V2G §3, §5.6, R3.15: Jev contrasts are descriptive, no claim words).
No number on the page is typed by hand; the page renders everything from v2.json. Standard library only.
"""
import argparse
import hashlib
import json
import math
import os
import sys
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
REC = os.path.join(ROOT, "bench", "burst_v2", "receipts")
OUT = os.path.join(ROOT, "site", "arena", "v2.json")
GH = "https://github.com/nagisanzenin/nagi"

GAMES = [  # page id, label, jev receipt key, metric label, unit, decimals
    ("snake", "Snake Rush", "snake", "survival time (s, capped at 60 s)", "s", 2),
    ("rotorwash_ramp", "Rotorwash-Ramp", "rr", "K3-RR2.1 score Y", "", 3),
    ("booster_gauntlet", "Booster Gauntlet", "booster", "K3 landing score Y (first hop)", "", 3),
]
BLOCKS = {"snake": [range(10, 22), range(22, 34)], "rotorwash_ramp": [range(34, 46), range(46, 58)],
          "booster_gauntlet": [range(34, 46), range(46, 58)]}
V2L, V1L = "Nagi Burst V2", "Nagi Burst V1"
BANNED = ("beats jev", "beat jev", "outperforms jev", "better than jev", "defeats jev")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load(name):
    with open(os.path.join(REC, name), encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- Student t quantile (stdlib; checked vs scipy)
def _betacf(a, b, x):
    tiny, qab, qap, qam = 1e-300, a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d; d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c; c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d; d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c; c = c if abs(c) > tiny else tiny
        de = d * c
        h *= de
        if abs(de - 1.0) < 1e-16:
            break
    return h


def betainc(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbt) * _betacf(b, a, 1.0 - x) / b


def t_cdf(t, df):
    p = 0.5 * betainc(df / 2.0, 0.5, df / (df + t * t))
    return 1.0 - p if t >= 0 else p


def t_ppf(q, df):
    lo, hi = 0.0, 1000.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if t_cdf(mid, df) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ---------------------------------------------------------------- statistics
def mean_ci(xs):
    n = len(xs)
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    h = t_ppf(0.975, n - 1) * sd / math.sqrt(n) if sd > 0 else 0.0
    return {"mean": m, "ci95": [m - h, m + h], "sd": sd, "n": n}


def head_to_head(a, b, blocks):
    """Gate-A form (PREREG_V2G §5.3) on index -> score maps; None = void."""
    idx = sorted(set(a) | set(b))
    valid = [i for i in idx if a.get(i) is not None and b.get(i) is not None]
    dropped = [sum(1 for i in blk if a.get(i) is None or b.get(i) is None) for blk in blocks]
    w = [1.0 if a[i] > b[i] else (0.5 if a[i] == b[i] else 0.0) for i in valid]
    n = len(w)
    wins, ties = w.count(1.0), w.count(0.5)
    losses = n - wins - ties
    W = sum(w) / n
    sd = math.sqrt(sum((x - W) ** 2 for x in w) / (n - 1)) if n > 1 else 0.0
    se = sd / math.sqrt(n)
    tq = t_ppf(0.975, n - 1)
    t_lb = W - tq * se if sd > 0 else W
    k = wins + losses
    p = float(sum(Fraction(math.comb(k, j), 2 ** k) for j in range(wins, k + 1))) if k > 0 else 1.0
    return {"n": n, "W": W, "W_ci95": [max(0.0, W - tq * se), min(1.0, W + tq * se)], "sd": sd, "t_lb": t_lb, "p": p,
            "wins": wins, "ties": ties, "losses": losses, "dropped_per_shard": dropped,
            "gate_A_form": bool(t_lb > 0.5 and p <= 0.025 and all(d <= 1 for d in dropped))}


def overall(pairs):
    """Descriptive composite over the three games: Theta = mean_g W_g, SE^2 = sum_g s_g^2/n_g / 9,
    Welch-Satterthwaite df; lower 97.5% bound (equals Theta when every s_g = 0)."""
    G = len(pairs)
    th = sum(p["W"] for p in pairs) / G
    v = [p["sd"] ** 2 / p["n"] for p in pairs]
    se = math.sqrt(sum(v)) / G
    if se > 0:
        df = sum(v) ** 2 / sum(x * x / (p["n"] - 1) for x, p in zip(v, pairs) if x > 0)
        lb = th - t_ppf(0.975, df) * se
    else:
        df, lb = None, th
    return {"theta": th, "se": se, "df_ws": df, "lb97_5": lb,
            "wins": sum(p["wins"] for p in pairs), "ties": sum(p["ties"] for p in pairs),
            "losses": sum(p["losses"] for p in pairs), "n": sum(p["n"] for p in pairs)}


def booster_note(games):
    g = next(x for x in games if x["game"] == "booster_gauntlet")
    L = g["landings"]
    return (f"Booster Gauntlet: V2 landed the first hop on {L['v2']}/{g['n']} seeds; V1 on {L['v1']}/{g['n']} and Jev on "
            f"{L['jev']}/{g['n']} (K3 = 0), so V1 vs Jev is all ties there. Board 1 below documents V1's Booster pattern: "
            "flying under control until the first hop's landing deadline, without landing.")


def snake_note(cand):
    sn = cand["config_resolved"]["snake"]
    assert cand["snake_policy"] == "sdk_pack" and "does not read the core" in cand["predeclared"]["snake_policy_rule"]["procedure"]
    return (f"Snake Rush: V2 plays the SDK Snake search pack ({sn['max_sims']:,} simulations, horizon {sn['k']}), which does "
            "not read the learned core. A predeclared rule chose it from dev seeds only, before the sealed look.")


def rr_note(games):
    g = next(x for x in games if x["game"] == "rotorwash_ramp")
    p = g["pairing_detail"]
    return (f"Rotorwash-Ramp is a float64 engine. Re-checked here under Rosetta (no AVX/FMA), the Jev records recompute "
            f"the recorded score on {p['score_recomputed_equal']}/{g['n']} seeds but replay state-hash-exactly on only "
            f"{p['replay_exact_local_image']}/{g['n']}. The recording job's own replay check on its x86-64 host "
            f"{'passed on every seed' if p['replay_exact_in_venue'] else 'did not pass'}. The release's V1 Rotorwash-Ramp "
            "check needed a real x86-64 CPU for the same reason.")


# ---------------------------------------------------------------- build
def build():
    pack = load("arena_v2.json")
    pc = load("jev_pair_check.json")
    cand = load("CANDIDATE.json")
    srcs = {n: sha256(os.path.join(REC, n)) for n in
            ["arena_v2.json", "CANDIDATE.json", "jev_pair_check.json", "jev1s_snake.json", "jev1s_rr.json", "jev1s_booster.json"]}
    games, notes = [], []
    pairs_by = {"v2_vs_v1": [], "v2_vs_jev": [], "v1_vs_jev": []}
    for gid, label, jk, metric, unit, dec in GAMES:
        oo = pack["out_order"][gid]
        v2 = {int(i): next(s for s, who in row if who == V2L) for i, row in oo.items()}
        v1 = {int(i): next(s for s, who in row if who == V1L) for i, row in oo.items()}
        jr = load(f"jev1s_{jk}.json")
        assert jr["status"] == "OK" and jr["client_streams"] == 1 and jr["single_stream_asserted"], jk
        assert jr["jev_model_served"] == "jev-1.13.0", jk
        jev = {int(s["index"]): (None if s["void"] else float(s["score"])) for s in jr["per_seed"]}
        jseed = {int(s["index"]): int(s["seed"]) for s in jr["per_seed"]}
        gmeta = next(g for g in pack["games"] if g["id"] == gid)
        assert jr["rules_id"] == gmeta["rules_id"], (gid, jr["rules_id"], gmeta["rules_id"])
        assert sorted(v2) == sorted(v1) == sorted(jev), gid
        # Jev pairing evidence (the M4 V1 comparator check applied to the Jev records)
        chk = pc["result"]["games"][jk]
        m4 = {int(x["index"]): x for x in chk["m4_metric"]}
        assert all(m4[i]["m4_score"] == jev[i] and m4[i]["seed"] == jseed[i] for i in jev), gid
        assert chk["static_ok"] == chk["n"] == chk["score_equal"] == 24 and chk["prompt_mismatch"] == 0, gid
        assert not chk["sha_mismatch"] and chk["n_pinned"] == 24, gid
        job = jr["jobs"][0]
        exact_here = chk["replay_exact"]
        in_venue = bool(job.get("replay_exact_all"))
        paired = in_venue and (exact_here == 24 or (gid == "rotorwash_ramp" and chk["score_equal"] == 24))
        h = {"v2_vs_v1": head_to_head(v2, v1, BLOCKS[gid]), "v2_vs_jev": head_to_head(v2, jev, BLOCKS[gid]),
             "v1_vs_jev": head_to_head(v1, jev, BLOCKS[gid])}
        # the receipted gate A must be reproduced exactly from the per-seed data
        ga = pack["gate_A"][gid]
        r = h["v2_vs_v1"]
        assert (r["wins"], r["ties"], r["losses"]) == (ga["wins"], ga["ties"], ga["losses"]), gid
        for k_ours, k_rec in (("W", "W"), ("t_lb", "t_lower"), ("p", "signflip_p")):
            assert abs(r[k_ours] - ga[k_rec]) < 1e-12, (gid, k_ours, r[k_ours], ga[k_rec])
        assert r["gate_A_form"] == bool(ga["pass"]), gid
        for k in pairs_by:
            pairs_by[k].append(h[k])
        means = {"v2": mean_ci(list(v2.values())), "v1": mean_ci(list(v1.values())),
                 "jev": mean_ci([x for x in jev.values() if x is not None])}
        assert abs(means["v2"]["mean"] - ga["mean_v2g"]) < 1e-12 and abs(means["v1"]["mean"] - ga["mean_v1"]) < 1e-12
        g = {
            "game": gid, "label": label, "metric": metric, "unit": unit, "decimals": dec, "rules_id": gmeta["rules_id"],
            "n": r["n"], "seeds": pack["meta"]["seeds"][gid],
            "means": {a: means[a]["mean"] for a in means}, "ci95": {a: means[a]["ci95"] for a in means},
            "pairing_jev": "PAIRED" if paired else "UNPAIRED",
            "pairing_detail": {
                "same_index_and_seed": sum(1 for i in v2 if jseed[i] == m4[i]["seed"]),
                "rules_id_equal": True, "record_sha256_pinned": chk["n_pinned"],
                "replay_exact_local_image": exact_here, "score_recomputed_equal": chk["score_equal"],
                "prompts_regenerated": chk["prompts"], "prompt_mismatch": chk["prompt_mismatch"],
                "replay_exact_in_venue": in_venue,
            },
            "jev_profile": {"model": jr["jev_model_served"], "client_streams": jr["client_streams"],
                            "one_tick_share": jr["realtime"]["one_tick_share"],
                            "latency_p50_ms": jr["realtime"]["latency_ms"]["p50"],
                            "latency_p95_ms": jr["realtime"]["latency_ms"]["p95"],
                            "nonok_replies": sum(int(s.get("nonok_replies", 0)) for s in jr["per_seed"])},
            "pairs": [
                dict(h["v2_vs_v1"], a="v2", b="v1", a_vs="v1", claim="gate A",
                     result="PASS" if ga["pass"] else "FAIL"),
                dict(h["v2_vs_jev"], a="v2", b="jev", a_vs="jev", claim="descriptive", result=None),
                dict(h["v1_vs_jev"], a="v1", b="jev", a_vs="jev", claim="descriptive", result=None),
            ],
            "per_seed": [{"index": i, "seed": jseed[i], "v2": v2[i], "v1": v1[i], "jev": jev[i]} for i in sorted(v2)],
            "replay": f"{GH}/tree/main/bench/burst_v2/replays/{gid}",
            "video": None, "poster": None,
        }
        if gid == "booster_gauntlet":
            g["landings"] = {a: sum(1 for x in s.values() if x and x > 0) for a, s in (("v2", v2), ("v1", v1), ("jev", jev))}
            assert g["landings"]["v2"] == ga["landings_v2g"]
        games.append(g)
    ov = {k: overall(v) for k, v in pairs_by.items()}
    media = os.path.join(ROOT, "site", "arena", "media")
    for g in games:
        stem = {"snake": "SnakeRush", "rotorwash_ramp": "RotorwashRamp", "booster_gauntlet": "BoosterGauntlet"}[g["game"]]
        for f in sorted(os.listdir(media)):
            if f.startswith(f"v2-{stem}-V2-V1-Jev") and f.endswith(".mp4"):
                g["video"] = f"media/{f}"
                g["video_sha256"] = sha256(os.path.join(media, f))
                jpg = f[:-4] + ".jpg"
                g["poster"] = f"media/{jpg}" if os.path.exists(os.path.join(media, jpg)) else None
                g["video_seed_index"] = int(f[:-4].rsplit("seed", 1)[1]) if "seed" in f else None
    out = {
        "schema": "nagi-arena-v2-update-v1",
        "meta": {
            "title": "Nagi Burst V2, Nagi Burst V1 and Jev on the frozen Arena eval seeds",
            "status": pack["meta"]["status"], "split": pack["meta"]["split"], "tick_ms": pack["meta"]["tick_ms"],
            "v2_reply_profile": pack["meta"]["reply_profile"], "model_sha256": pack["meta"]["model_sha256"],
            "generated_by": "site/arena/build/make_v2.py", "sources_sha256": srcs,
            "replay_pack": {"exact": pack["replay"]["exact"], "replayed": pack["replay"]["replayed"]},
            "jev_pair_check_image": pc["image"], "jev_engine_identity": pc["engine_identity"],
        },
        "players": {
            "v2": {"label": V2L, "sub": pack["players"][0]["sub"]},
            "v1": {"label": V1L, "sub": pack["players"][1]["sub"]},
            "jev": {"label": "Jev", "sub": "jev-1.13.0, vendor API, single-stream re-play (PREREG_V2G §3, descriptive)"},
        },
        "claim_rule": {
            "v2_vs_v1": "Gate A (PREREG_V2G §5.3): PASS iff the t lower 97.5% bound of W > 1/2 and the exact sign test p <= 0.025, per game.",
            "jev": "Descriptive only (PREREG_V2G §3, §5.6, R3.15): Jev contrasts were preregistered as descriptive, on identical seeds, with no claim words. The gate-A numbers are shown for reference; they are not a claim.",
        },
        "games": games,
        "overall": ov,
        "notes": [
            "Seen tasks: the V2 core was trained on these three Arena games. The eval seeds were sealed and played once.",
            "Timing: V2 was played with the nominal 1-tick reply (the decision for tick t applies at t+1), justified by its measured latency gate L. The V1 and Jev numbers come from live realtime records, where a slow reply lands later.",
            snake_note(cand),
            booster_note(games),
            rr_note(games),
            "Not comparable with the Board 1 leaderboard below: different seeds (the release's sealed eval seeds here, Board 1's screen seeds there), Rotorwash-Ramp and Booster Gauntlet are scored by their K3 scores here and by survival time there, and Jev here is the single-stream re-play.",
        ],
    }
    text = json.dumps(out, indent=1, ensure_ascii=False) + "\n"
    low = text.lower()
    bad = [b for b in BANNED if b in low]
    if bad:
        raise SystemExit(f"claim wording not allowed by the preregistration: {bad}")
    return out, text


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    out, text = build()
    try:  # independent check of the stdlib t quantile when scipy is available
        from scipy import stats as ss  # noqa: PLC0415
        for df in (5, 11, 23, 47):
            assert abs(t_ppf(0.975, df) - float(ss.t.ppf(0.975, df))) < 1e-9, df
        tcheck = "scipy"
    except ImportError:
        tcheck = "skipped (no scipy)"
    if a.check:
        with open(OUT, encoding="utf-8") as f:
            cur = f.read()
        if cur != text:
            print("v2.json is stale: re-run site/arena/build/make_v2.py", file=sys.stderr)
            return 1
        print(f"OK: v2.json matches the receipts (t quantile check: {tcheck})")
        return 0
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    for g in out["games"]:
        p = {x["a"] + "_vs_" + x["b"]: f'{x["wins"]}-{x["ties"]}-{x["losses"]} W={x["W"]:.4f} tLB={x["t_lb"]:.4f} p={x["p"]:.3g}' for x in g["pairs"]}
        print(g["game"], g["pairing_jev"], {k: round(v, 4) for k, v in g["means"].items()}, p)
    print("overall", {k: (round(v["theta"], 4), round(v["lb97_5"], 4), f'{v["wins"]}-{v["ties"]}-{v["losses"]}') for k, v in out["overall"].items()})
    print(f"wrote {os.path.relpath(OUT, ROOT)} (t quantile check: {tcheck})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
