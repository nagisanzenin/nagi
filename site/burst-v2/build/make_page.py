#!/usr/bin/env python3
"""Build and check the Nagi Burst V2 page (site/burst-v2/) from the frozen release receipts.

  python3 site/burst-v2/build/make_page.py          # write data.json and stamp index.html
  python3 site/burst-v2/build/make_page.py check    # rebuild in memory; exit 1 on any mismatch

Every number on the page comes from a receipt under bench/burst_v2/ (or the SDK pin in src/, or pyproject.toml).
`build` writes site/burst-v2/data.json ({values, sources, receipts}: each displayed value with its file, JSON key or
regex, raw value and the file's sha256) and stamps index.html in place:
  - <span data-k="KEY">…</span> (any tag with data-k) gets values[KEY];
  - <!--bv2:NAME-->…<!--/bv2:NAME--> blocks are regenerated (tables, link lists, code from the README).
`check` fails when:
  - a receipt's sha256 disagrees with the sha256 that another receipt records for it (cross-pins below);
  - an independent re-derivation disagrees with a receipt value (W from wins/ties, π̂_R from counts, the
    rule-of-three bound, θ̂_D from the strata, core sha and HF pin across files, ...);
  - data.json or index.html on disk differs from a fresh build (so the page shows exactly the receipt values);
  - a digit appears in the page text outside stamped spans/blocks, code, scripts and an explicit allowlist.
No network. Labels below are prose; no label contains a measured number.
"""
import hashlib
import html
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE_DIR = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(PAGE_DIR))
INDEX = os.path.join(PAGE_DIR, "index.html")
DATA = os.path.join(PAGE_DIR, "data.json")
GH = "https://github.com/nagisanzenin/nagi"
GH_BLOB = GH + "/blob/main/"
HF = "https://huggingface.co/"

REC = "bench/burst_v2/receipts/"
FILES = {
    "result": REC + "RESULT.json",
    "addendum": REC + "RESULT_ADDENDUM.json",
    "candidate": REC + "CANDIDATE.json",
    "audit": REC + "AUDIT_M4.md",
    "fill": REC + "fill_receipt.json",
    "manifest": REC + "MANIFEST.json",
    "replay": REC + "replay.json",
    "arena": REC + "arena_v2.json",
    "robot": REC + "robot_example.json",
    "videos": REC + "arena_v2_videos.json",
    "jev_snake": REC + "jev1s_snake.json",
    "jev_rr": REC + "jev1s_rr.json",
    "jev_booster": REC + "jev1s_booster.json",
    "report": "bench/burst_v2/README.md",
    "guide": "docs/BURST_V2.md",
    "readme": "README.md",
    "api": "src/nagi/burst2/_api.py",
    "pyproject": "pyproject.toml",
}
# optional content modules next to this file (diagrams.py, research.py): FILES_ADD, register(b), blocks
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
MODULES = {}
for _m in ("diagrams", "research"):
    if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), _m + ".py")):
        MODULES[_m] = __import__(_m)
        FILES.update(getattr(MODULES[_m], "FILES_ADD", {}))

# RESULT.json game keys -> arena_v2.json game ids (structural mapping, no numbers)
GAMES = [("snake", "snake"), ("rotorwash", "rotorwash_ramp"), ("booster", "booster_gauntlet")]
LAT_POPS = [("zoo_d", "Zoo-Unseen-D (unseen machines)"), ("snake", None), ("rr", None), ("booster", None)]
STRATA = [("snake_like", "Snake-like"), ("booster_like", "Booster-like"), ("mixed", "Mixed"), ("rr_like", "Rotorwash-like")]
# digits allowed in page text outside stamped content: names, not measurements
ALLOW = [r"\bV[123](?:\.1)?\b", r"\bV2G\b", r"\bmz-1x?\b", r"\bp(?:50|95|99)\b", r"\b0[1-9] / ", r"\bC8\b",
         r"\bG[123]\b", r"\bR[12]\b", r"\bv3\b", r"\bburst2\b", r"\bsha256\b", r"\bM2\b",
         r"\bE[123]\b", r"\b1-tick\b", r"×\d\b", r"\b\d populations\b", r"\bV2\.1\b",
         r"\b[\w.-]+\.(?:json|md|py|mp4|jpg|png)\b", r"\bM[1-5]\b"]


def rel(k):
    return FILES[k]


def path(k):
    return os.path.join(ROOT, FILES[k])


def sha256(k):
    return hashlib.sha256(open(path(k), "rb").read()).hexdigest()


def text(k):
    return open(path(k), encoding="utf-8").read()


def jload(k):
    return json.loads(text(k))


def get(obj, ptr):
    for part in ptr.split("|"):
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


# ---------- number formats (display only; raw values stay in data.json) ----------
def neg(s):
    return s.replace("-", "−") if s.startswith("-") else s


def f(x, nd=3):
    s = f"{x:.{nd}f}"
    if float(s) == 0:
        s = s.lstrip("-")
    return neg(s)


def fs(x, nd=3):  # signed
    s = f(x, nd)
    return s if s.startswith("−") or float(x) == 0 else "+" + s


def pct(x, nd=1):
    return f(100 * x, nd) + "%"


def pval(x):
    if x >= 0.01:
        return f"{x:.3f}"
    if x >= 1e-4:
        return f"{x:.5f}".rstrip("0")
    return f"{x:.1e}"


def ms(x):
    return f"{x:.1f} ms"


def num(x):
    return f"{int(x):,}"


class Build:
    def __init__(self):
        self.values, self.sources, self.blocks = {}, {}, {}
        self.receipts = {FILES[k]: sha256(k) for k in FILES}
        self.errors = []
        self.used = set()

    def put(self, key, display, k, ptr=None, raw=None, regex=None, derived=None):
        if key in self.values:
            raise SystemExit(f"duplicate key {key}")
        self.values[key] = str(display)
        src = {"file": rel(k), "sha256": self.receipts[rel(k)]}
        if ptr is not None:
            src["key"] = ptr
        if regex is not None:
            src["regex"] = regex
        if derived is not None:
            src["derived"] = derived
        if raw is not None:
            src["raw"] = raw
        self.sources[key] = src
        return display

    def j(self, key, k, ptr, fmt, data=None):
        raw = get(data if data is not None else jload(k), ptr)
        return self.put(key, fmt(raw), k, ptr=ptr, raw=raw)

    def rx(self, key, k, pattern, fmt=lambda s: s, group=1):
        m = re.search(pattern, text(k), re.M)
        if not m:
            raise SystemExit(f"{key}: pattern not found in {rel(k)}: {pattern}")
        return self.put(key, fmt(m.group(group)), k, regex=pattern, raw=m.group(group))

    def require(self, ok, msg):
        if not ok:
            self.errors.append(msg)


def build():
    b = Build()
    R, A, C, AR = jload("result"), jload("addendum"), jload("candidate"), jload("arena")
    FL, MF, RP = jload("fill"), jload("manifest"), jload("replay")
    put, req = b.put, b.require

    # ---------- cross-pins: each receipt's sha256 as recorded by another receipt ----------
    sh = b.receipts
    req(FL["inputs"]["RESULT.json"]["sha256"] == sh[rel("result")], "RESULT.json sha != fill_receipt input")
    req(MF["inputs_sha256"]["RESULT.json"] == sh[rel("result")], "RESULT.json sha != MANIFEST input")
    req(FL["inputs"]["CANDIDATE.json"]["sha256"] == sh[rel("candidate")], "CANDIDATE.json sha != fill_receipt input")
    req(R["identity"]["candidate_sha256"] == sh[rel("candidate")], "CANDIDATE.json sha != RESULT.identity")
    req(FL["inputs"]["AUDIT_M4.md"]["sha256"] == sh[rel("audit")], "AUDIT_M4.md sha != fill_receipt input")
    req(MF["outputs_sha256"]["arena_v2.json"] == sh[rel("arena")], "arena_v2.json sha != MANIFEST output")
    req(MF["outputs_sha256"]["replay.json"] == sh[rel("replay")], "replay.json sha != MANIFEST output")
    req(FL["inputs"]["replay.json"]["sha256"] == sh[rel("replay")], "replay.json sha != fill_receipt input")
    m = re.search(r"RESULT_ADDENDUM\.json sha ([0-9a-f]{8})", text("audit"))
    req(bool(m) and sh[rel("addendum")].startswith(m.group(1)), "RESULT_ADDENDUM.json sha != the version AUDIT_M4 §11 audited")
    req(A["identity"]["analysis_sha256"] == R["identity"]["analysis_sha256"], "addendum analysis sha != RESULT analysis sha")

    # ---------- identity: SDK, HF pin, core ----------
    b.rx("sdk_version", "pyproject", r'^version = "([0-9.]+)"')
    put("sdk_tag", "v" + b.values["sdk_version"], "pyproject", regex=r'^version = "([0-9.]+)"', derived='"v" + version')
    b.rx("hf_repo", "api", r'^BURST_V2_REPO = "([^"]+)"')
    b.rx("hf_revision", "api", r'^BURST_V2_REVISION = "([0-9a-f]{40})"')
    put("hf_revision_short", b.values["hf_revision"][:8], "api", regex=r'^BURST_V2_REVISION = "([0-9a-f]{40})"', derived="first 8 hex")
    core_api = re.search(r'^CORE_SHA256 = "([0-9a-f]{64})"', text("api"), re.M).group(1)
    req(core_api == C["core_weights_sha256"] == AR["meta"]["model_sha256"], "core sha differs across src pin / CANDIDATE / arena_v2")
    put("core_sha_short", C["core_weights_sha256"][:8], "candidate", ptr="core_weights_sha256", raw=C["core_weights_sha256"], derived="first 8 hex")
    b.rx("core_params", "report", r"(\d+\.\d+M) parameters")
    b.j("cfg_sims", "candidate", "config_resolved|candidate|max_sims", num, C)
    b.j("cfg_kmax", "candidate", "config_resolved|candidate|k_max", str, C)
    b.j("cfg_tau", "candidate", "config_resolved|candidate|tau", lambda x: f"{x:g}", C)
    b.j("cfg_snake_sims", "candidate", "config_resolved|snake|max_sims", num, C)
    b.j("cfg_snake_k", "candidate", "config_resolved|snake|k", str, C)
    b.j("serving_class", "candidate", "predeclared|serving_class", str, C)
    b.rx("hardware", "report", r"^\| Hardware \| (.+?) \|$")

    # ---------- decision ----------
    b.j("decision", "result", "release|decision", str, R)
    b.j("path", "result", "release|path", str, R)
    req(FL["decision"] == R["release"]["decision"], "fill_receipt decision != RESULT")
    req(FL["audit"] == "MATCH", "fill_receipt audit != MATCH")
    b.rx("audit_verdict", "audit", r"^Verdict: (MATCH)\s*$")
    b.j("alpha", "result", "alpha", lambda x: f"{x:g}", R)
    put("conf", f(100 * (1 - R["alpha"]), 1) + "%", "result", ptr="alpha", raw=R["alpha"], derived="100*(1-alpha) %")

    # ---------- thresholds (the M5 report prints the preregistered rule values) ----------
    b.rx("thr_g1", "report", r"G1 ≥ (\d\.\d+)")
    b.rx("thr_g2", "report", r"G2 > (\d\.\d+)")
    b.rx("thr_g3", "report", r"G3 ≥ (\d\.\d+)")
    b.rx("thr_r1", "report", r"point rule ≥ (\d\.\d+)")
    b.rx("thr_r2", "report", r"\(rule > (\d\.\d+)\)")
    b.rx("thr_l", "report", r"gate ≤ (\d+) ms", lambda s: s + " ms")
    b.rx("thr_ns", "report", r"NS \(θ > (\d\.\d+)\)")
    b.rx("thr_landings", "report", r"PASS needs ≥ (\d+)")

    # ---------- gate G (Zoo-Unseen-D, parser path) ----------
    G = R["zoo_d"]["gate_G"]
    b.j("g_families", "result", "zoo_d|admission|G", str, R)
    b.j("g_domains", "result", "zoo_d|admission|D", str, R)
    b.j("g_theta", "result", "zoo_d|gate_G|estimate", f, R)
    b.j("g_fam_lo", "result", "zoo_d|gate_G|family|lower", f, R)
    b.j("g_fam_hi", "result", "zoo_d|gate_G|family|upper", f, R)
    b.j("g_dom_lo", "result", "zoo_d|gate_G|domain|lower", f, R)
    b.j("g_lodo", "result", "zoo_d|gate_G|lodo_min", f, R)
    b.j("g_lodo_dom", "result", "zoo_d|gate_G|lodo_argmin", lambda s: s.replace("_", " "), R)
    b.j("g_icc", "result", "zoo_d|gate_G|icc_domain", lambda x: f(x, 2), R)
    b.j("g_pass", "result", "release|gates|G", str, R)
    b.j("machines", "result", "coverage_d|machines", str, R)
    req(G["pass"] == (G["G1_point_ge_floor"] and G["G2_bounds_gt_guard"] and G["G3_lodo_ge_floor"]), "G pass != G1 and G2 and G3")
    req(G["estimate"] >= float(b.values["thr_g1"]) and min(G["family"]["lower"], G["domain"]["lower"]) > float(b.values["thr_g2"])
        and G["lodo_min"] >= float(b.values["thr_g3"]), "G rule re-derivation disagrees with the printed thresholds")

    # ---------- gate A (Arena vs Nagi Burst V1) ----------
    names = {g["id"]: g for g in AR["games"]}
    for rk, gid in GAMES:
        a = R["arena"][rk]
        b.put(f"a_{rk}_name", names[gid]["name"], "arena", ptr=f"games|{[g['id'] for g in AR['games']].index(gid)}|name", raw=names[gid]["name"])
        b.j(f"a_{rk}_n", "result", f"arena|{rk}|n", str, R)
        unit = " s" if rk == "snake" else ""
        nd = 1 if rk == "snake" else 2
        b.j(f"a_{rk}_v2", "result", f"arena|{rk}|mean_v2g", lambda x: f(x, nd) + unit, R)
        b.j(f"a_{rk}_v1", "result", f"arena|{rk}|mean_v1", lambda x: f(x, nd) + unit, R)
        put(f"a_{rk}_wtl", f"{a['wins']} / {a['ties']} / {a['losses']}", "result", ptr=f"arena|{rk}|wins,ties,losses",
            raw=[a["wins"], a["ties"], a["losses"]])
        b.j(f"a_{rk}_W", "result", f"arena|{rk}|W", f, R)
        b.j(f"a_{rk}_tlo", "result", f"arena|{rk}|t_lower", f, R)
        b.j(f"a_{rk}_p", "result", f"arena|{rk}|signflip_p", pval, R)
        b.j(f"a_{rk}_pass", "result", f"release|gates|A_{rk}", str, R)
        req(abs(a["W"] - (a["wins"] + 0.5 * a["ties"]) / a["n"]) < 1e-12, f"A {rk}: W != (wins + ties/2)/n")
        req(a["wins"] + a["ties"] + a["losses"] == a["n"], f"A {rk}: wins+ties+losses != n")
        k = a["wins"] + a["losses"]
        p_exact = sum(math.comb(k, i) for i in range(a["wins"], k + 1)) / 2 ** k
        req(abs(p_exact - a["signflip_p"]) < 1e-15, f"A {rk}: sign-flip p != P(Bin(k, 1/2) >= wins)")
        req(a["pass"] == (a["t_lower"] > 0.5 and a["signflip_p"] <= R["alpha"]) and (R["release"]["gates"][f"A_{rk}"] == "PASS") == a["pass"],
            f"A {rk}: pass != (t_lower > 1/2 and p <= alpha)")
    req(all(R["arena"][rk]["losses"] == 0 for rk, _ in GAMES), "page text says V2 lost no pairing; a game has losses")
    req(C["search_only_s0_star"] > C["config_resolved"]["candidate"]["max_sims"], "page text says the comparator budget is larger")
    b.j("a_booster_landings", "result", "arena|booster|landings_v2g", str, R)
    req(R["arena"]["booster"]["landings_v2g"] >= int(b.values["thr_landings"]), "Booster landings below the printed k rule")
    b.j("a_seeds_snake", "arena", "meta|seeds|snake", str, AR)
    b.j("a_seeds_other", "arena", "meta|seeds|rotorwash_ramp", str, AR)
    req(AR["meta"]["seeds"]["rotorwash_ramp"] == AR["meta"]["seeds"]["booster_gauntlet"], "RR and Booster seed ranges differ")
    b.j("tick_ms", "arena", "meta|tick_ms", lambda x: f"{x} ms", AR)
    req(AR["meta"]["tick_ms"] == 250, "tick_ms != 250: the latency column reads share_gt_250")
    b.j("reply_profile", "arena", "meta|reply_profile", str, AR)
    for rk, gid in GAMES:
        b.j(f"metric_{rk}", "arena", f"games|{[g['id'] for g in AR['games']].index(gid)}|metric", str, AR)
    b.j("replay_exact", "replay", "exact", str, RP)
    b.j("replay_n", "replay", "replayed", str, RP)
    req(RP["ok"] and RP["exact"] == RP["replayed"] and not RP["failures"], "replay.json not all exact")

    # ---------- gate L ----------
    lat = R["latency"]["populations"]
    for pk, _ in LAT_POPS:
        p = lat[pk]
        b.j(f"l_{pk}_n", "result", f"latency|populations|{pk}|n", num, R)
        b.j(f"l_{pk}_p50", "result", f"latency|populations|{pk}|p50_ms", ms, R)
        b.j(f"l_{pk}_p95", "result", f"latency|populations|{pk}|p95_ms", ms, R)
        b.j(f"l_{pk}_ucb", "result", f"latency|populations|{pk}|p95_ucb_ms", ms, R)
        b.j(f"l_{pk}_p99", "result", f"latency|populations|{pk}|p99_ms", ms, R)
        b.j(f"l_{pk}_gt250", "result", f"latency|populations|{pk}|share_gt_250", lambda x: pct(x, 2), R)
        req(p["pass"] == (p["p95_ucb_ms"] <= float(b.values["thr_l"].split()[0])), f"L {pk}: pass != (UCB <= threshold)")
        # order statistic u = min{u : P(Bin(n, 0.95) <= u-1) >= 0.95}
        n, cdf, u = p["n"], 0.0, 0
        while cdf < 0.95:
            cdf += math.exp(math.lgamma(n + 1) - math.lgamma(u + 1) - math.lgamma(n - u + 1) + u * math.log(0.95) + (n - u) * math.log(0.05))
            u += 1
        req(u == p["u"], f"L {pk}: order-statistic index u != {u}")
    worst = max(lat, key=lambda k: lat[k]["p95_ucb_ms"])
    put("l_max_ucb", ms(lat[worst]["p95_ucb_ms"]), "result", ptr=f"latency|populations|{worst}|p95_ucb_ms",
        raw=lat[worst]["p95_ucb_ms"], derived="max p95_ucb_ms over the populations")
    b.j("l_pass", "result", "release|gates|L", str, R)

    # ---------- gate I ----------
    I = R["interface"]
    b.j("i_n", "result", "interface|n", num, R)
    b.j("i_mis", "result", "interface|mismatches", str, R)
    b.j("i_rt", "result", "interface|roundtrip_failures", str, R)
    b.j("i_ucb", "result", "interface|mismatch_rate_ucb95", lambda x: pct(x, 3), R)
    b.j("i_pass", "result", "release|gates|I", str, R)
    req(I["mismatches"] == 0 and abs(I["mismatch_rate_ucb95"] - 3 / I["n"]) < 1e-9, "I: UCB != rule of three 3/n")
    req(sum(I["by_population"].values()) == I["n"], "I: populations do not sum to n")

    # ---------- gate R (prose reader) ----------
    GR = R["gate_R"]
    b.j("r_exact", "result", "gate_R|exact_families", str, R)
    b.j("r_G", "result", "gate_R|G", str, R)
    b.j("r_pi", "result", "gate_R|pi_hat", f, R)
    b.j("r_cp", "result", "gate_R|cp_lower_97_5", f, R)
    b.j("r_machine", "result", "gate_R|machine_rate", f, R)
    b.j("r_result", "result", "release|R", str, R)
    req(abs(GR["pi_hat"] - GR["exact_families"] / GR["G"]) < 1e-12, "R: pi_hat != exact/G")
    req(GR["exact_families"] + GR["failing_families"] == GR["G"], "R: exact + failing != G")
    req(GR["pass"] == (GR["pi_hat"] >= float(b.values["thr_r1"]) and GR["cp_lower_97_5"] > float(b.values["thr_r2"])), "R: rule re-derivation")

    # ---------- claims (Holm {G+, NS}) ----------
    for ck, key in (("NS", "ns"), ("G+", "gp")):
        c, h = R["zoo_d"]["claims"][ck], R["zoo_d"]["holm"][ck]
        b.j(f"{key}_est", "result", f"zoo_d|claims|{ck}|estimate", f if ck == "NS" else fs, R)
        b.j(f"{key}_p", "result", f"zoo_d|claims|{ck}|p_claim", pval, R)
        b.j(f"{key}_level", "result", f"zoo_d|holm|{ck}|level", lambda x: f"{x:g}", R)
        b.j(f"{key}_lo_fam", "result", f"zoo_d|holm|{ck}|bounds_at_step|family_lower", f, R)
        b.j(f"{key}_lo_dom", "result", f"zoo_d|holm|{ck}|bounds_at_step|domain_lower", f, R)
        put(f"{key}_result", "shown" if h["reject"] else "not shown", "result", ptr=f"zoo_d|holm|{ck}|reject", raw=h["reject"],
            derived="reject -> 'shown', else 'not shown'")
        req((h["p"] <= h["level"]) == h["reject"], f"Holm {ck}: reject != (p <= level)")
    hs = sorted(R["zoo_d"]["holm"].values(), key=lambda h: h["rank"])
    req(abs(hs[0]["level"] - R["alpha"] / 2) < 1e-12 and abs(hs[1]["level"] - R["alpha"]) < 1e-12, "Holm levels != alpha/2, alpha")
    req(R["zoo_d"]["holm"]["NS"]["reject"] and not R["zoo_d"]["holm"]["G+"]["reject"], "claims changed: expected NS shown, G+ not shown")
    b.j("gp_lodo_ok", "result", "zoo_d|claims|G+|lodo_ok", lambda x: "holds" if x else "fails", R)

    # ---------- C8 coverage ----------
    cov = R["coverage_d"]
    b.j("c8_decisions", "result", "coverage_d|decisions", num, R)
    b.j("c8_reach_min", "result", "coverage_d|reach_min_p25_median_p75_max|0", num, R)
    b.j("c8_reach_med", "result", "coverage_d|reach_min_p25_median_p75_max|2", lambda x: f"{x:,.1f}".rstrip("0").rstrip("."), R)
    b.j("c8_reach_max", "result", "coverage_d|reach_min_p25_median_p75_max|4", num, R)
    b.j("c8_le1000", "result", "coverage_d|share_reach_le_1000", pct, R)
    b.j("c8_le20000", "result", "coverage_d|share_reach_le_20000", pct, R)
    b.j("c8_exhausted", "result", "coverage_d|share_decisions_exhausted", pct, R)
    b.j("c8_high", "result", "coverage_d|share_decisions_high_coverage", pct, R)
    put("c8_lowcov_machines", str(len(cov["low_coverage_machines"])), "result", ptr="coverage_d|low_coverage_machines",
        raw=len(cov["low_coverage_machines"]), derived="len(list)")
    b.j("lc_G", "result", "low_coverage_d|G", str, R)
    b.j("lc_D", "result", "low_coverage_d|D", str, R)
    b.j("lc_theta", "result", "low_coverage_d|theta_hat", f, R)
    b.j("lc_lo_fam", "result", "low_coverage_d|NS_vs_0.60|family|lower", f, R)
    b.j("lc_lo_dom", "result", "low_coverage_d|NS_vs_0.60|domain|lower", f, R)
    b.j("lc_gp", "result", "low_coverage_d|Gplus|family|mean", fs, R)
    b.j("large_G", "result", "large_machines_d|G", str, R)

    # ---------- addendum (descriptive; audited version, AUDIT_M4 §11) ----------
    th = A["theta_per_stratum"]
    for sk, _ in STRATA:
        b.j(f"st_{sk}", "addendum", f"theta_per_stratum|{sk}|mean", f, A)
        b.j(f"st_{sk}_G", "addendum", f"theta_per_stratum|{sk}|G", str, A)
        b.j(f"st_{sk}_dp", "addendum", f"delta_plus_per_stratum|{sk}|mean", fs, A)
    req(min(th[s]["mean"] for s in th) == th["rr_like"]["mean"], "page text says rr_like is the weakest stratum")
    req(min(th[s]["mean"] for s in th if s != "rr_like") >= 0.9, "page text says the other strata are close to the ceiling")
    req(max(abs(A["delta_plus_per_stratum"][s]["mean"]) for s in th) < 0.05, "page text says the core changes success by almost nothing per stratum")
    tot = sum(th[s]["G"] for s in th)
    req(tot == R["zoo_d"]["admission"]["G"], "strata G do not sum to the D families")
    req(abs(sum(th[s]["mean"] * th[s]["G"] for s in th) / tot - G["estimate"]) < 1e-12, "family-weighted strata mean != theta_D")
    b.j("prose_G", "addendum", "prose_path|G_prose_rule_form|estimate", f, A)
    b.j("prose_diff", "addendum", "prose_path|prose_minus_parser|mean", fs, A)
    b.j("prose_diff_lo", "addendum", "prose_path|prose_minus_parser|lower", fs, A)
    b.j("leak_diff", "addendum", "leak_check_zoo_dev_l|leak_check|diff", fs, A)
    b.j("leak_lo", "addendum", "leak_check_zoo_dev_l|leak_check|lower", fs, A)
    b.j("leak_flag", "addendum", "leak_check_zoo_dev_l|leak_check|flag", lambda x: "flag" if x else "no flag", A)
    b.j("zc_G", "addendum", "zoo_unseen_c|G", str, A)
    b.j("zc_D", "addendum", "zoo_unseen_c|D", str, A)
    b.j("zc_theta", "addendum", "zoo_unseen_c|theta_candidate|mean", f, A)
    b.j("zc_dp", "addendum", "zoo_unseen_c|delta_plus|mean", fs, A)
    b.j("zc_dp_lo", "addendum", "zoo_unseen_c|delta_plus|lower", fs, A)

    # ---------- delivery-robot example (docs/QUICKSTART_MACHINE.md §6; receipt by scripts/burst2_robot_example.py) ----------
    RB = jload("robot")
    req(RB["core_sha256"] == core_api, "robot receipt core sha != the SDK pin")
    req(RB["sdk_version"] == b.values["sdk_version"], "robot receipt SDK version != pyproject")
    req(RB["result"] == "goal" and RB["values"]["robot.goal_ticks"] == len(RB["trace"]), "robot receipt: goal ticks != trace length")
    req(not RB["unwinnable"]["goal_reachable"], "robot receipt: the unwinnable variant has a reachable goal")
    for key, rk in (("robot_goal", "robot.goal_ticks"), ("robot_wall_tick", "robot.wall_tick"), ("robot_wall_tied", "robot.wall_tied"),
                    ("robot_wait", "robot.wait_tick"), ("robot_wait_b0", "robot.wait_battery_before"),
                    ("robot_wait_b1", "robot.wait_battery_after"), ("robot_unw_states", "robot.unwinnable.reachable_states"),
                    ("robot_unw_still", "robot.unwinnable.still_from"), ("robot_unw_tied", "robot.unwinnable.first_tied")):
        b.j(key, "robot", f"values|{rk}", str, RB)
    b.j("robot_session", "robot", "session", str, RB)
    b.j("robot_unw_best", "robot", "values|robot.unwinnable.best_value", lambda x: f(x, 1), RB)

    # ---------- budget (M5 report §9) ----------
    b.rx("cost_total", "report", r"All V2-general cloud spend[^|]*\| \$(\d+\.\d\d) \|", lambda s: "$" + s)
    b.rx("cost_m4", "report", r"Billed \(finalized provider bills\) \| \$(\d+\.\d\d) \|", lambda s: "$" + s)

    # ---------- binding wording (C8.3) and the release gates ----------
    c83 = b.rx("c83", "report", r"^(On unseen machines, V2G's success comes mainly from exact lookahead on the given rules, [^\n]+\.)$")
    req(c83 in text("guide") and c83 in text("readme"), "C8.3 sentence differs between the report, docs/BURST_V2.md and README.md")
    gates = R["release"]["gates"]
    req(R["release"]["decision"] == "RELEASE" and all(v == "PASS" for v in gates.values()), "release gates not all PASS")
    req(R["release"]["path"] == "parser" and R["release"]["R"] == "FAIL", "path rule: expected R FAIL -> parser")

    clips(b, AR)
    for mod in MODULES.values():
        mod.register(b)
    b.ctx = (R, A, AR)
    blocks(b, R, A, AR)
    return b


# arena_v2_videos.json game keys and the jev1s receipt per game (structural mapping, no numbers)
CLIP_GAMES = [("snake", "snake", "snake", "jev_snake"), ("rotorwash", "rotorwash_ramp", "rr", "jev_rr"),
              ("booster", "booster_gauntlet", "booster", "jev_booster")]


def clips(b, AR):
    """The three 3-seat Arena clips (shared with site/arena/): seed, per-seat scores and file bytes all checked
    against the render receipt, the sealed per-seed scores (arena_v2.json) and the Jev receipts."""
    VR = jload("videos")
    req = b.require
    req(VR["plays_a_model"] is False and VR["network"] == "none", "video receipt: not a pure replay render")
    b.clip_files = {}
    for rk, gid, vk, jk in CLIP_GAMES:
        g = VR["games"][vk]
        i = g["chosen_index"]
        req(g["all_checks_ok"] is True, f"video receipt: {vk} checks not all ok")
        req(abs(g["margin_v2_minus_jev"] - g["median_margin"]) < 1e-9, f"video receipt: {vk} seed is not at the median margin")
        oo = {who: sc for sc, who in AR["out_order"][gid][str(i)]}
        jev = {x["index"]: x for x in jload(jk)["per_seed"]}[i]
        req(abs(g["scores"]["v2"] - oo["Nagi Burst V2"]) < 1e-9 and abs(g["scores"]["v1"] - oo["Nagi Burst V1"]) < 1e-9,
            f"video receipt: {vk} #{i} V2/V1 scores != arena_v2.json")
        req(abs(g["scores"]["jev"] - jev["score"]) < 1e-9 and g["seed"] == jev["seed"], f"video receipt: {vk} #{i} Jev != jev1s receipt")
        mp4 = [k for k in VR["published_as"] if k.endswith(".mp4") and f"seed{i}." in k and k.startswith("site/arena/media/v2-")
               and {"snake": "SnakeRush", "rotorwash": "RotorwashRamp", "booster": "BoosterGauntlet"}[rk] in k]
        req(len(mp4) == 1, f"video receipt: {vk} published clip not unique")
        for f_ in (mp4[0], mp4[0][:-4] + ".jpg"):
            h = hashlib.sha256(open(os.path.join(ROOT, f_), "rb").read()).hexdigest()
            req(h == VR["published_as"][f_], f"{f_}: bytes != video receipt")
        b.clip_files[rk] = "../arena/" + mp4[0][len("site/arena/"):]
        b.put(f"clip_{rk}_seed", str(i), "videos", ptr=f"games|{vk}|chosen_index", raw=i)
        for arm in ("v2", "v1", "jev"):
            b.put(f"clip_{rk}_{arm}", f(g["scores"][arm], 2), "videos", ptr=f"games|{vk}|scores|{arm}", raw=g["scores"][arm])
    sk = [(vk, x) for _, _, vk, _ in CLIP_GAMES for x in VR["games"][vk].get("skipped", [])]
    b.put("clip_skipped", "; ".join(f'{x["reason"].split(":", 1)[0]} skipped ({x["reason"].split(":", 1)[1].strip()})' for _, x in sk) or "none",
          "videos", ptr="games|*|skipped", raw=[x for _, x in sk])


# ---------- generated HTML blocks ----------
_LINT = False  # True while blocks are rendered for the digit lint: every stamped value becomes a placeholder


def V(b, k):
    if k not in b.values:
        raise SystemExit(f"block uses unknown key {k}")
    b.used.add(k)
    return "◊" if _LINT else html.escape(b.values[k])


def badge(word):
    cls = {"PASS": "ok", "FAIL": "bad", "shown": "ok", "not shown": "bad"}.get(word, "mut")
    return f'<span class="bdg {cls}">{html.escape(word)}</span>'


def blocks(b, R, A, AR):
    v = lambda k: V(b, k)
    vb = lambda k: (b.used.add(k), "◊" if _LINT else b.values[k])[1]  # raw (unescaped) value, marked as used
    B = b.blocks
    B["hero-facts"] = (
        '<dl class="facts">'
        f'<div><dt>Unseen machines</dt><dd>{v("g_theta")}<small>success on Zoo-Unseen-D, {v("g_families")} families / {v("g_domains")} domains · lower bounds {v("g_fam_lo")} family, {v("g_dom_lo")} domain · gate G {v("g_pass")}</small></dd></div>'
        f'<div><dt>Arena vs Nagi Burst V1</dt><dd>{v("a_snake_W")} · {v("a_rotorwash_W")} · {v("a_booster_W")}<small>win share W on Snake Rush · Rotorwash-Ramp · Booster Gauntlet, {v("a_snake_n")} sealed seeds each · gate A {v("a_snake_pass")} ×{len(GAMES)}</small></dd></div>'
        f'<div><dt>Decision latency</dt><dd>≤ {v("l_max_ucb")}<small>largest p95 upper bound over every population, {v("hardware")} · gate L ({v("thr_l")}) {v("l_pass")}</small></dd></div>'
        f'<div><dt>Learned core</dt><dd>{v("core_params")}<small>parameters, numpy only · text path = structured path on {v("i_n")} requests ({v("i_mis")} mismatches) · gate I {v("i_pass")}</small></dd></div>'
        '</dl>')
    B["install"] = (
        '<pre><code># the SDK (module nagi.burst2), pinned to this release\n'
        f'python -m pip install "nagi-decisions @ git+{GH}.git@{v("sdk_tag")}"</code></pre>')
    readme = text("readme")
    sec = readme[readme.index("## Burst V2"):]
    code = re.search(r"```python\n(.*?)```", sec, re.S).group(1)
    b.sources["block:quickstart"] = {"file": rel("readme"), "sha256": b.receipts[rel("readme")],
                                     "regex": "first ```python block after '## Burst V2'"}
    B["quickstart"] = f'<pre><code>{html.escape(code.rstrip())}</code></pre>'
    RB = jload("robot")
    b.sources["block:robot-rules"] = {"file": rel("robot"), "sha256": b.receipts[rel("robot")], "key": "rules_text"}
    B["robot-rules"] = f'<pre><code>{html.escape(RB["rules_text"].rstrip())}</code></pre>'
    rev = vb("hf_revision")
    B["use-links"] = (
        '<div class="links">'
        f'<a href="{GH_BLOB}docs/BURST_V2.md"><b>Burst V2 guide ↗</b><span>What it is, the API, the draw, limits</span></a>'
        f'<a href="{GH_BLOB}docs/QUICKSTART_MACHINE.md"><b>Write your own machine ↗</b><span>Five-minute quickstart: rules, canonical form, one decision per tick</span></a>'
        f'<a href="{GH_BLOB}docs/DSL_REFERENCE.md"><b>Machine language reference ↗</b><span>mz-1 / mz-1x syntax, exact tick semantics, delays and hidden variables, worked examples</span></a>'
        f'<a href="{HF}{v("hf_repo")}/tree/{html.escape(rev)}"><b>Model on Hugging Face ↗</b><span>{v("hf_repo")} at revision <code>{v("hf_revision_short")}</code> (pinned in the SDK) · core sha256 <code>{v("core_sha_short")}</code></span></a>'
        f'<a href="{GH}/tree/{v("sdk_tag")}/src/nagi/burst2"><b>SDK source ↗</b><span>nagi.burst2 at tag {v("sdk_tag")}: reader, search, core, operate()</span></a>'
        f'<a href="{GH_BLOB}CHANGELOG.md"><b>Changelog ↗</b><span>What changed in {v("sdk_tag")}</span></a>'
        '</div>')

    rows = [
        ("A", "Arena vs Nagi Burst V1 (seen games)", f'W {v("a_snake_W")} · {v("a_rotorwash_W")} · {v("a_booster_W")}',
         f't lower {v("a_snake_tlo")} · {v("a_rotorwash_tlo")} · {v("a_booster_tlo")}',
         f't lower bound of W above one half and sign-flip p ≤ {v("alpha")}, per game', v("a_snake_pass") + f" ×{len(GAMES)}"),
        ("G", "Unseen machines, Zoo-Unseen-D", f'θ̂ {v("g_theta")}', f'{v("g_fam_lo")} family · {v("g_dom_lo")} domain · LODO {v("g_lodo")}',
         f'θ̂ ≥ {v("thr_g1")}; both lower bounds &gt; {v("thr_g2")}; leave-one-domain-out ≥ {v("thr_g3")}', v("g_pass")),
        ("L", "Latency, one thread", f'p95 ≤ {v("l_max_ucb")} (upper bound)', f'{len(LAT_POPS)} populations, {v("serving_class")}',
         f'p95 upper bound ≤ {v("thr_l")} in every population', v("l_pass")),
        ("I", "Text path = structured path", f'{v("i_mis")} mismatches / {v("i_n")}', f'rate upper bound {v("i_ucb")}',
         'identical probability vectors and draws', v("i_pass")),
        ("R", "Prose reader (routes the shipped path)", f'{v("r_exact")}/{v("r_G")} families exact', f'π̂ {v("r_pi")} · CP lower {v("r_cp")}',
         f'π̂ ≥ {v("thr_r1")} and CP lower bound &gt; {v("thr_r2")}; FAIL ships the {v("path")} path', v("r_result")),
    ]
    B["gates"] = (
        '<div class="tw"><table class="gates"><caption>Release gates, frozen sealed run (bounds: one-sided '
        f'{v("conf")})</caption><thead><tr><th scope="col">Gate</th><th scope="col">What it tests</th><th scope="col">Estimate</th>'
        '<th scope="col">Lower bounds</th><th scope="col">Rule</th><th scope="col">Result</th></tr></thead><tbody>'
        + "".join(f'<tr><td><b>{g}</b></td><td class="l">{w}</td><td>{e}</td><td class="l">{lo}</td><td class="l">{r}</td><td>{badge(res.split(" ")[0])}{(" " + res.split(" ", 1)[1]) if " " in res else ""}</td></tr>'
                  for g, w, e, lo, r, res in rows)
        + f'</tbody></table></div><p class="note">Decision: <b>{v("decision")}</b> on the {v("path")} path. Independent recount of every number: <b>{v("audit_verdict")}</b>.</p>')

    arow = []
    for rk, _ in GAMES:
        arow.append(f'<tr><td>{v(f"a_{rk}_name")}</td><td class="l">{v(f"metric_{rk}")}</td><td>{v(f"a_{rk}_n")}</td><td>{v(f"a_{rk}_v2")}</td><td>{v(f"a_{rk}_v1")}</td>'
                    f'<td>{v(f"a_{rk}_wtl")}</td><td>{v(f"a_{rk}_W")}</td><td>{v(f"a_{rk}_tlo")}</td><td>{v(f"a_{rk}_p")}</td><td>{badge(vb(f"a_{rk}_pass"))}</td></tr>')
    B["arena-a"] = (
        '<div class="tw"><table><caption>Gate A · V2 vs Nagi Burst V1 on the same sealed seeds (paired)</caption><thead><tr>'
        '<th scope="col">Game</th><th scope="col">Metric</th><th scope="col">n</th><th scope="col">V2 mean</th><th scope="col">V1 mean</th>'
        f'<th scope="col">Wins / ties / losses</th><th scope="col">W</th><th scope="col">t lower {v("conf")}</th><th scope="col">Sign-flip p</th><th scope="col">Gate</th></tr></thead><tbody>'
        + "".join(arow) + '</tbody></table></div>'
        f'<p class="note">Seeds: Snake {v("a_seeds_snake")}, Rotorwash-Ramp and Booster {v("a_seeds_other")}; {v("tick_ms")} ticks; reply profile: {v("reply_profile")}. '
        f'Booster: {v("a_booster_landings")}/{v("a_booster_n")} landed (rule: at least {v("thr_landings")}); V1 landed none, and a Booster round is its first hop. '
        f'Exact replay from the recorded controls: {v("replay_exact")}/{v("replay_n")}.</p>')

    units = {"snake": " s", "rotorwash": "", "booster": ""}
    figs = []
    for rk, gid, vk, jk in CLIP_GAMES:
        src = html.escape(b.clip_files[rk])
        name = v(f"a_{rk}_name")
        sc = " · ".join(f'{lab} {v(f"clip_{rk}_{arm}")}{units[rk]}' for arm, lab in (("v2", "V2"), ("v1", "V1"), ("jev", "Jev")))
        figs.append(
            f'<figure class="clip"><video controls preload="none" playsinline poster="{src[:-4]}.jpg" src="{src}" '
            f'aria-label="{name} replay, median-margin sealed seed {v(f"clip_{rk}_seed")}: Nagi Burst V2, Nagi Burst V1 and Jev side by side"></video>'
            f'<figcaption><b>{name}</b> · median-margin sealed seed #{v(f"clip_{rk}_seed")}<br>{sc} ({v(f"metric_{rk}")})<br>'
            'V2: offline 1-tick replies; V1, Jev: live records</figcaption></figure>')
    B["arena-clips"] = (
        '<div class="clips" id="clips">' + "".join(figs) + '</div>'
        '<p class="note">Each clip replays one sealed round from the recorded controls, three players on the same seed: '
        'Nagi Burst V2, Nagi Burst V1 and, for reference only, Jev (descriptive; the release gates compare with V1 only). '
        'The seed is fixed by rule, not picked: the round at the median V2 − Jev margin for that game '
        f'(skipped when a seat cannot be replayed exactly: {v("clip_skipped")}). Real time, with brief slow motion at eliminations. '
        f'Every on-screen score equals its record; render receipt <a href="{GH_BLOB}bench/burst_v2/receipts/arena_v2_videos.json"><code>arena_v2_videos.json</code></a>.</p>')

    lrow = []
    for pk, label in LAT_POPS:
        name = label or v({"snake": "a_snake_name", "rr": "a_rotorwash_name", "booster": "a_booster_name"}[pk])
        lrow.append(f'<tr><td>{name}</td><td>{v(f"l_{pk}_n")}</td><td>{v(f"l_{pk}_p50")}</td><td>{v(f"l_{pk}_p95")}</td><td><b>{v(f"l_{pk}_ucb")}</b></td>'
                    f'<td>{v(f"l_{pk}_p99")}</td><td>{v(f"l_{pk}_gt250")}</td></tr>')
    B["latency"] = (
        f'<div class="tw"><table><caption>Gate L · {v("hardware")}</caption><thead><tr><th scope="col">Population</th><th scope="col">Requests</th>'
        f'<th scope="col">p50</th><th scope="col">p95</th><th scope="col">p95 upper bound (gate ≤ {v("thr_l")})</th><th scope="col">p99 (reported)</th>'
        f'<th scope="col">Share &gt; {v("tick_ms")}</th></tr></thead><tbody>' + "".join(lrow) + '</tbody></table></div>')

    B["claims"] = (
        f'<div class="tw"><table class="wrap"><caption>Research claims · Holm over {{G+, NS}} at α = {v("alpha")} · never gates</caption><thead><tr>'
        '<th scope="col">Claim</th><th scope="col">Estimate</th><th scope="col">p</th><th scope="col">Holm level</th>'
        '<th scope="col">Lower bounds (family / domain)</th><th scope="col">Result</th></tr></thead><tbody>'
        f'<tr><td class="l"><b>NS</b> · mean success on unseen machines above {v("thr_ns")}</td><td>{v("ns_est")}</td><td>{v("ns_p")}</td><td>{v("ns_level")}</td><td>{v("ns_lo_fam")} / {v("ns_lo_dom")}</td><td>{badge(vb("ns_result"))}</td></tr>'
        f'<tr><td class="l"><b>G+</b> · the learned core adds to the same lookahead at the same latency cap (Δ̂+)</td><td>{v("gp_est")}</td><td>{v("gp_p")}</td><td>{v("gp_level")}</td><td>{v("gp_lo_fam")} / {v("gp_lo_dom")}</td><td>{badge(vb("gp_result"))}</td></tr>'
        '</tbody></table></div>')

    B["coverage"] = (
        '<div class="tw"><table class="wrap"><caption>C8 · how much of each test machine the lookahead saw (candidate run)</caption><tbody>'
        f'<tr><td class="l">Scored machines / decisions</td><td>{v("machines")} / {v("c8_decisions")}</td></tr>'
        f'<tr><td class="l">Reachable states per machine: min / median / max</td><td>{v("c8_reach_min")} / {v("c8_reach_med")} / {v("c8_reach_max")}</td></tr>'
        f'<tr><td class="l">Machines with at most a thousand / twenty thousand reachable states</td><td>{v("c8_le1000")} / {v("c8_le20000")}</td></tr>'
        f'<tr><td class="l">Decisions where the search exhausted the tree</td><td>{v("c8_exhausted")}</td></tr>'
        f'<tr><td class="l">High-coverage decisions (exhausted, or saw at least half the machine)</td><td>{v("c8_high")}</td></tr>'
        f'<tr><td class="l">Low-coverage subset: machines · families / domains · θ̂ (descriptive)</td><td>{v("c8_lowcov_machines")} · {v("lc_G")} / {v("lc_D")} · {v("lc_theta")}</td></tr>'
        f'<tr><td class="l">Low-coverage subset: lower bounds family / domain (NS needs &gt; {v("thr_ns")})</td><td>{v("lc_lo_fam")} / {v("lc_lo_dom")}</td></tr>'
        f'<tr><td class="l">Machines larger than the search budget (policy-free subset)</td><td>{v("large_G")}</td></tr>'
        '</tbody></table></div>')

    srow = "".join(f'<tr{" class=\"me\"" if sk == "rr_like" else ""}><td>{lab}</td><td>{v(f"st_{sk}_G")}</td><td><b>{v(f"st_{sk}")}</b></td><td>{v(f"st_{sk}_dp")}</td></tr>'
                   for sk, lab in STRATA)
    bars = "".join(
        f'<li{" class=\"me\"" if sk == "rr_like" else ""}><span class="lab">{lab}<small>{v(f"st_{sk}_G")} families · Δ̂+ {v(f"st_{sk}_dp")}</small></span>'
        f'<span class="bar" role="img" aria-label="{lab}: success {v(f"st_{sk}")}"><i style="width:{100 * float(b.sources[f"st_{sk}"]["raw"]):.1f}%"></i></span>'
        f'<b>{v(f"st_{sk}")}</b></li>' for sk, lab in STRATA)
    B["strata"] = (
        '<figure class="bars"><figcaption>Zoo-Unseen-D success θ̂ by stratum (descriptive, no test) · Δ̂+ = core minus the same search without it</figcaption>'
        f'<ul>{bars}</ul></figure>')

    B["extras"] = (
        '<ul class="lims">'
        f'<li><b class="k">Leak check · descriptive</b>Zoo-Unseen-D minus the development set Zoo-Dev-L: {v("leak_diff")} (lower bound {v("leak_lo")}) → {v("leak_flag")}, so gate G stands.</li>'
        f'<li><b class="k">Zoo-Unseen-C · descriptive</b>A second unseen set ({v("zc_G")} families / {v("zc_D")} domains): θ̂ {v("zc_theta")}; Δ̂+ {v("zc_dp")} (lower bound {v("zc_dp_lo")}). Learning is not shown there either.</li>'
        f'<li class="fail"><b class="k">Prose path · descriptive</b>With the frozen prose reader in front, G would be {v("prose_G")}: {v("prose_diff")} per family against the exact parser (lower bound {v("prose_diff_lo")}). That is why the reader moves to V2.1.</li>'
        '</ul>')

    if "diagrams" in MODULES:
        B["arch-decision"] = MODULES["diagrams"].svg_decision(v)
        B["arch-core"] = MODULES["diagrams"].svg_core(v)
    if "research" in MODULES:
        B.update(MODULES["research"].blocks(v, vb))

    rec = [
        ("bench/burst_v2/README.md", "M5 report", "Every gate, claim, coverage table, budget and disclosure"),
        (FILES["result"], "RESULT.json", "The frozen analysis output (gates, claims, C8, latency, interface)"),
        (FILES["addendum"], "RESULT_ADDENDUM.json", "Descriptive addendum: strata, prose path, leak check, Zoo-Unseen-C"),
        (FILES["audit"], "AUDIT_M4.md", "Independent recount from raw receipts, item by item"),
        (FILES["candidate"], "CANDIDATE.json", "The candidate frozen before any sealed run"),
        (FILES["arena"], "arena_v2.json", "Arena gate A pack: per-seed scores and replays"),
        (FILES["replay"], "replay.json", "Exact replay from recorded controls"),
        (FILES["robot"], "robot_example.json", "The delivery-robot example: rules, every tick, the unwinnable variant"),
        (FILES["manifest"], "MANIFEST.json", "sha256 of every Arena input and output"),
    ]
    B["receipts"] = (
        '<div class="links">' + "".join(
            f'<a href="{GH_BLOB}{p}"><b>{html.escape(t)} ↗</b><span>{html.escape(d)} · sha256 <code>{b.receipts[p][:8]}</code></span></a>' for p, t, d in rec)
        + '<a href="data.json"><b>data.json</b><span>Every number on this page with its file, JSON key and sha256</span></a>'
        + f'<a href="{GH_BLOB}site/burst-v2/build/make_page.py"><b>make_page.py ↗</b><span>The builder and checker that stamp this page from the receipts</span></a>'
        + '</div>')
    for p, _, _ in rec:
        b.sources.setdefault("block:receipts", {})[p] = b.receipts[p]


# ---------- stamping, lint ----------
SPAN = re.compile(r'(<(\w+)\b[^>]*?\sdata-k="([A-Za-z0-9_+-]+)"[^>]*>)(.*?)(</\2>)', re.S)
BLOCK = re.compile(r'(<!--bv2:([a-z0-9-]+)-->)(.*?)(<!--/bv2:\2-->)', re.S)


def stamp(page, b):
    used_k, used_b = set(), set()

    def sp(m):
        k = m.group(3)
        if k not in b.values:
            raise SystemExit(f"index.html: unknown data-k {k}")
        used_k.add(k)
        return m.group(1) + html.escape(b.values[k]) + m.group(5)

    def bl(m):
        k = m.group(2)
        if k not in b.blocks:
            raise SystemExit(f"index.html: unknown block {k}")
        used_b.add(k)
        return m.group(1) + b.blocks[k] + m.group(4)

    page = BLOCK.sub(bl, page)
    n_attr = len(re.findall(r'\sdata-k=', page))
    page, n_sub = SPAN.subn(sp, page)
    if n_sub != n_attr:
        raise SystemExit(f"index.html: {n_attr} data-k attributes but {n_sub} stamped (malformed key or nesting)")
    missing = set(b.blocks) - used_b
    if missing:
        raise SystemExit(f"index.html: blocks not placed: {sorted(missing)}")
    return page, used_k


def lint(page):
    t = re.sub(r"<!--nx:(\w+)-->.*?<!--/nx:\1-->", "", page, flags=re.S)  # shared chrome (site/build_chrome.py)
    t = BLOCK.sub("", t)
    t = SPAN.sub("", t)
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    for tag in ("script", "style", "pre", "code", "head"):
        t = re.sub(rf"<{tag}\b.*?</{tag}>", "", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    for a in ALLOW:
        t = re.sub(a, "", t)
    bad = []
    for m in re.finditer(r"\d", t):
        bad.append(t[max(0, m.start() - 40):m.end() + 40].replace("\n", " "))
    return bad


def lint_blocks(b):
    """Render every block with each stamped value replaced by a placeholder; any digit left in the visible text
    (outside pre/code and the allowlist) was typed by hand."""
    global _LINT
    keep, used = dict(b.blocks), set(b.used)
    _LINT = True
    try:
        blocks(b, *b.ctx)
        out = {}
        for name, h in b.blocks.items():
            t = re.sub(r"<(pre|code|style|script)\b.*?</\1>", " ", h, flags=re.S)
            t = html.unescape(re.sub(r"<[^>]+>", " ", t))
            for a in ALLOW:
                t = re.sub(a, "", t)
            bad = [t[max(0, m.start() - 30):m.end() + 30].replace("\n", " ") for m in re.finditer(r"\d", t)]
            if bad:
                out[name] = bad
        return out
    finally:
        _LINT = False
        b.blocks, b.used = keep, used


def data_json(b, used):
    out = {
        "schema": "nagi-burst-v2-page-v1",
        "generated_by": "site/burst-v2/build/make_page.py",
        "note": "Every value shown on site/burst-v2/ with its source receipt. raw = the receipt value; values = the page text.",
        "receipts": dict(sorted(b.receipts.items())),
        "values": {k: b.values[k] for k in sorted(b.values)},
        "sources": {k: b.sources[k] for k in sorted(b.sources)},
        "unused_on_page": sorted(set(b.values) - used),
    }
    return json.dumps(out, ensure_ascii=False, indent=1, allow_nan=False) + "\n"


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "build"
    b = build()
    page = open(INDEX, encoding="utf-8").read()
    new_page, used = stamp(page, b)
    used |= b.used  # values referenced inside generated blocks
    dj = data_json(b, used)
    bad = lint(new_page)
    for name, hits in lint_blocks(b).items():
        bad += [f"[block {name}] …{x}…" for x in hits]
    if mode == "build":
        if b.errors:
            sys.exit("re-derivation failed:\n  " + "\n  ".join(b.errors))
        open(INDEX, "w", encoding="utf-8").write(new_page)
        open(DATA, "w", encoding="utf-8").write(dj)
        print(f"stamped {os.path.relpath(INDEX, ROOT)} ({len(used)} values used of {len(b.values)}); wrote {os.path.relpath(DATA, ROOT)}")
        if bad:
            sys.exit("unstamped digits in page text:\n  " + "\n  ".join(bad))
        return 0
    if mode == "check":
        errs = list(b.errors)
        if new_page != page:
            errs.append("index.html differs from the receipt-stamped page (run the builder)")
        if not os.path.exists(DATA) or open(DATA, encoding="utf-8").read() != dj:
            errs.append("data.json differs from a fresh build from the receipts")
        errs += [f"unstamped digit: …{s}…" for s in bad]
        if errs:
            print("FAIL\n  " + "\n  ".join(errs))
            return 1
        print(f"OK: {len(b.values)} values re-derived from {len(b.receipts)} files; page and data.json match; no hand-typed digits")
        return 0
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
