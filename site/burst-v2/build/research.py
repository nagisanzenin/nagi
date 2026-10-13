"""Research content blocks for the Nagi Burst V2 page: what we learned, related work, next experiments, method, FAQ,
and the Zoo-Unseen-D oracle reference line (also used by site/arena/).

Loaded by make_page.py: FILES_ADD joins FILES, register(b) adds the rs_* values, blocks(v, vb) returns HTML blocks.
Every number in a block is a registered value (v(key)); the text holds no hand-typed number. Sources:
  bench/burst_v2/RELATED_WORK.md               byte copy of the research-repo review at b958308f (sha in timeline.json)
  bench/burst_v2/receipts/timeline.json        dated commits from the split freeze to publication
  bench/burst_v2/receipts/budget_m4.json       closed cloud ledgers (sha pinned by fill_receipt.json)
  bench/burst_v2/receipts/zoo_d_admission.json the frozen Zoo-Unseen-D admission rule (famgate V3) and domain strata
  site/arena/v2.json                           the Game Arena V2 data (descriptive Jev counts)
plus the receipts make_page.py already reads (RESULT, RESULT_ADDENDUM, CANDIDATE, AUDIT_M4, fill_receipt).
"""
import hashlib
import json
import os
import re
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
REC = "bench/burst_v2/receipts/"
GH_BLOB = "https://github.com/nagisanzenin/nagi/blob/main/"

FILES_ADD = {
    "rs_related": "bench/burst_v2/RELATED_WORK.md",
    "rs_timeline": REC + "timeline.json",
    "rs_budget": REC + "budget_m4.json",
    "rs_admission": REC + "zoo_d_admission.json",
    "rs_arena_page": "site/arena/v2.json",
}
# receipts that make_page.py already registers under these FILES keys (read here, never re-registered)
BASE = {"result": REC + "RESULT.json", "addendum": REC + "RESULT_ADDENDUM.json", "candidate": REC + "CANDIDATE.json",
        "audit": REC + "AUDIT_M4.md", "fill": REC + "fill_receipt.json"}
PATHS = {**BASE, **FILES_ADD}
STRATUM_LABEL = {"rr_like": "Rotorwash-like"}  # the only stratum the text names (structural, no numbers)


def _text(k):
    return open(os.path.join(ROOT, PATHS[k]), encoding="utf-8").read()


def _json(k):
    return json.loads(_text(k))


def _sha(k):
    return hashlib.sha256(open(os.path.join(ROOT, PATHS[k]), "rb").read()).hexdigest()


def _f(x, nd=3):  # same display rule as make_page.f
    s = f"{x:.{nd}f}"
    if float(s) == 0:
        s = s.lstrip("-")
    return s.replace("-", "−") if s.startswith("-") else s


def _when(t):
    return datetime.strptime(t, "%Y-%m-%d %H:%M:%S %z")


def register(b):
    put, req, val = b.put, b.require, b.values
    R, A, C = _json("result"), _json("addendum"), _json("candidate")
    FL, TL, BU, AD, AP = _json("fill"), _json("rs_timeline"), _json("rs_budget"), _json("rs_admission"), _json("rs_arena_page")
    RW = _text("rs_related")
    for k, p in PATHS.items():
        req(b.receipts.get(p) == _sha(k), f"research.py reads {p}, which is not the file the builder hashed")

    # ---------- cross-pins between the new sources and the release receipts ----------
    ev = {e["id"]: (i, e) for i, e in enumerate(TL["events"])}
    pub = ev["published"][1]["content"]
    req(_sha("rs_budget") == FL["inputs"]["budget.json"]["sha256"], "budget_m4.json != the budget file fill_receipt.json rendered")
    req(ev["related_work"][1]["sha256"] == _sha("rs_related"), "RELATED_WORK.md != the reviewed research-repo file")
    req(ev["prereg_frozen"][1]["sha256"] == C["prereg"]["sha256"], "timeline PREREG sha != CANDIDATE.prereg")
    req(ev["candidate_frozen"][1]["sha256"] == _sha("candidate"), "timeline CANDIDATE sha != CANDIDATE.json")
    req(ev["d_addendum_final"][1]["sha256"] == C["predeclared"]["d_addendum"]["sha256"] == AD["d_addendum"]["sha256"],
        "D addendum sha differs across timeline / CANDIDATE / zoo_d_admission")
    req(pub["result_sha256"] == _sha("result"), "publication receipt RESULT sha != RESULT.json")
    req(pub["hf"]["card_commit"] == val["hf_revision"] and pub["sdk"]["tag"] == val["sdk_tag"], "publication receipt != SDK pins")
    req(ev["sdk_release"][1]["commit"] == pub["sdk"]["main"], "timeline SDK commit != publication receipt")
    order = ["splits_frozen", "prereg_frozen", "d_addendum_final", "candidate_frozen", "sdk_release", "published", "related_work", "e1_design"]
    ts = [_when(ev[k][1]["commit_time"]) for k in order]
    req(all(x < y for x, y in zip(ts, ts[1:])), "timeline milestones are not in order")
    offs = {ev[k][1]["commit_time"][-5:] for k in order} | {C["frozen_at"][-5:]}
    req(offs == {"+0700"}, "timeline times are not all in one UTC offset")
    req(AD["d_addendum"]["families"] == R["zoo_d"]["admission"]["G"] and AD["d_addendum"]["domains"] == R["zoo_d"]["admission"]["D"],
        "zoo_d_admission counts != RESULT admission")

    # ---------- timeline (method block) ----------
    i, e = ev["prereg_frozen"]
    put("rs_t_prereg", e["commit_time"][:16], "rs_timeline", ptr=f"events|{i}|commit_time", raw=e["commit_time"], derived="date and minute")
    i, e = ev["published"]
    put("rs_t_pub", e["commit_time"][:16], "rs_timeline", ptr=f"events|{i}|commit_time", raw=e["commit_time"], derived="date and minute")
    put("rs_year", e["commit_time"][:4], "rs_timeline", ptr=f"events|{i}|commit_time", raw=e["commit_time"], derived="year")
    hours = (_when(ev["published"][1]["commit_time"]) - _when(ev["prereg_frozen"][1]["commit_time"])).total_seconds() / 3600
    put("rs_hours", str(round(hours)), "rs_timeline", ptr="events|prereg_frozen,published|commit_time", raw=hours,
        derived="round((published - prereg_frozen) in hours)")
    off = ev["published"][1]["commit_time"][-5:]
    put("rs_tz", f"UTC{off[0]}{int(off[1:3])}" + (f":{off[3:]}" if off[3:] != "00" else ""), "rs_timeline",
        ptr=f"events|{ev['published'][0]}|commit_time", raw=off, derived="UTC offset of the commit times")
    i, e = ev["e1_design"]
    put("rs_e1_commit", e["commit"][:8], "rs_timeline", ptr=f"events|{i}|commit", raw=e["commit"], derived="first 8 hex")
    put("rs_t_e1", e["commit_time"][:10], "rs_timeline", ptr=f"events|{i}|commit_time", raw=e["commit_time"], derived="date")
    i, e = ev["d_addendum_final"]
    put("rs_t_d_final", e["commit_time"][:10], "rs_timeline", ptr=f"events|{i}|commit_time", raw=e["commit_time"], derived="date")
    put("rs_prereg_sha", C["prereg"]["sha256"][:8], "candidate", ptr="prereg|sha256", raw=C["prereg"]["sha256"], derived="first 8 hex")
    put("rs_t_cand", C["frozen_at"][:16], "candidate", ptr="frozen_at", raw=C["frozen_at"], derived="date and minute")
    b.rx("rs_t_sealed", "audit", r"the D parser cell and Arena S/B started at (\d\d:\d\d);")
    b.rx("rs_t_audit", "audit", r"^\*\*Status: FINAL\*\* \(gates \d{4}-\d\d-\d\d (~\d\d:\d\d) \+07;")
    m = re.search(r"^\*\*Status: FINAL\*\* \(gates (\d{4}-\d\d-\d\d) ", _text("audit"), re.M)
    req(bool(m) and m.group(1) == C["frozen_at"][:10] == ev["published"][1]["commit_time"][:10],
        "page text says the sealed run, the recount and publication fell on the candidate-freeze day")
    req(val["rs_t_cand"][11:] < val["rs_t_sealed"] < val["rs_t_audit"].lstrip("~") < val["rs_t_pub"][11:], "same-day times out of order")

    # ---------- errata (AUDIT_M4 §7, CANDIDATE.deviations) ----------
    b.rx("rs_s0_bracket", "audit", r"S0\* deviation \(bracket (\d+\.\d+%) > \d+%")
    b.rx("rs_s0_tol", "audit", r"S0\* deviation \(bracket \d+\.\d+% > (\d+%)")
    b.j("rs_s0_star", "candidate", "search_only_s0_star", lambda x: f"{int(x):,}", C)
    dev = " ".join(d["text"] for d in C["deviations"])
    req(f"bracket is {val['rs_s0_bracket']} wide" in dev and f"{val['rs_s0_tol']} tolerance" in dev and val["rs_s0_star"] in dev,
        "CANDIDATE deviation text != AUDIT_M4 §7 S0* row")
    req(C["search_only_s0_star"] > C["config_resolved"]["candidate"]["max_sims"], "page text says S0* favours the comparator")
    req("The two dated errata change no number" in _text("audit"), "page text says the errata change no number")

    # ---------- budget (closed ledgers) ----------
    led = BU["campaign_ledgers"]
    put("rs_ledgers_n", str(len(led)), "rs_budget", ptr="campaign_ledgers", raw=sorted(led), derived="number of closed ledgers")
    held = sum(x["held_usd"] for x in led.values()) + BU["held_usd"]
    put("rs_held", f"${held:.2f}", "rs_budget", ptr="campaign_ledgers|*|held_usd + held_usd", raw=held, derived="sum of held reservations")
    req(abs(sum(x["total_billed_usd"] for x in led.values()) - BU["campaign_gpu_billed_usd"]) < 1e-9, "ledger bills do not sum to the campaign total")
    req(f"${BU['campaign_gpu_billed_usd']:.2f}" == val["cost_total"], "budget_m4.json campaign total != report §9")
    req(f"${BU['billed_usd']:.2f}" == val["cost_m4"], "budget_m4.json M4 bill != report §9")

    # ---------- the oracle gap (RESULT per-domain, admission rule, strata) ----------
    Z = R["zoo_d"]
    pd = Z["per_domain"]
    fam = sum(d["families"] for d in pd.values())
    so = sum(d["families"] * d["search_only"] for d in pd.values()) / fam
    req(fam == Z["admission"]["G"] and abs(so - (Z["gate_G"]["estimate"] - Z["claims"]["G+"]["estimate"])) < 1e-12,
        "search-only mean != theta_D - delta_plus")
    put("rs_so_theta", _f(so), "result", ptr="zoo_d|per_domain|*|search_only", raw=so, derived="family-weighted mean of search_only")
    b.j("rs_oracle_min", "rs_admission", "oracle_rule|oracle_min", lambda x: f"{x:.2f}", AD)
    omin = AD["oracle_rule"]["oracle_min"]
    req(f"oracle_min: float = {omin}" in AD["oracle_rule"]["lines"]["77"] and AD["oracle_rule"]["profile"] == "v2g-zud"
        and '"v2g-zud"' in AD["oracle_rule"]["used_by"]["text"], "admission excerpt does not state the floor it records")
    req(re.search(r"non-privileged offline policy succeeds ≥ (\d\.\d+)", RW).group(1) == val["rs_oracle_min"], "review floor != admission rule")
    put("rs_gap_lb", _f(omin - Z["gate_G"]["estimate"]), "rs_admission", ptr="oracle_rule|oracle_min", raw=omin - Z["gate_G"]["estimate"],
        derived="oracle_min - RESULT zoo_d.gate_G.estimate")
    t_rule = AD["oracle_rule"]["commit_introduced_time"]
    put("rs_t_oracle_rule", t_rule[:10], "rs_admission", ptr="oracle_rule|commit_introduced_time", raw=t_rule, derived="date")
    req(_when(AD["oracle_rule"]["commit_last_change_time"]) < _when(ev["d_addendum_final"][1]["commit_time"]),
        "page text says the floor was fixed before the test set was final")
    smap = AD["domain_stratum"]["map"]
    req(set(smap) == set(pd), "strata map domains != RESULT domains")
    for s, th in A["theta_per_stratum"].items():
        ds = [d for d in pd if smap[d] == s]
        g = sum(pd[d]["families"] for d in ds)
        req(g == th["G"] and abs(sum(pd[d]["families"] * pd[d]["candidate"] for d in ds) / g - th["mean"]) < 1e-12,
            f"stratum {s}: per-domain means do not reproduce RESULT_ADDENDUM")
    thr = float(val["thr_ns"])
    weak = sorted((d for d in pd if pd[d]["candidate"] < thr), key=lambda d: pd[d]["candidate"])
    put("rs_weak_n", str(len(weak)), "result", ptr="zoo_d|per_domain|*|candidate", raw=weak, derived="number of domains with candidate < thr_ns")
    put("rs_weak_list", " · ".join(f'{d.replace("_", " ")} {_f(pd[d]["candidate"])}' for d in weak), "result",
        ptr="zoo_d|per_domain|*|candidate", raw={d: pd[d]["candidate"] for d in weak}, derived="domains with candidate < thr_ns, ascending")
    fail = {d: pd[d]["families"] * (1 - pd[d]["candidate"]) for d in pd}
    share = sum(fail[d] for d in weak) / sum(fail.values())
    put("rs_weak_share", _f(100 * share, 1) + "%", "result", ptr="zoo_d|per_domain|*", raw=share,
        derived="sum over weak domains of families*(1-candidate) / same sum over all domains")
    req(bool(weak) and all(smap[d] == "rr_like" for d in weak), "page text says every weak domain is Rotorwash-like")
    req(Z["n_invalid_machines"] == 0 and len({d["families"] for d in pd.values()}) == 1,
        "failure share is read as a share of episodes: needs equal episodes per family and no invalid machine")

    # ---------- related work (byte copy of the review) ----------
    b.rx("rs_pl_model", "rs_related", r"Planetarium reports (\S+) at \d+\.\d% parseable")
    b.rx("rs_pl_parse", "rs_related", r"Planetarium reports \S+ at (\d+\.\d%) parseable")
    b.rx("rs_pl_solv", "rs_related", r"parseable, (\d+\.\d%) solvable, but \d+\.\d% semantically correct")
    b.rx("rs_pl_sem", "rs_related", r"solvable, but (\d+\.\d%) semantically correct")
    b.rx("rs_pl_venue", "rs_related", r"\*Planetarium: A Rigorous Benchmark for Translating Text to Structured Planning Languages\.\* (NAACL \d{4})\.")
    b.rx("rs_cwm_venue", "rs_related", r"\*Code World Models for General Game Playing\.\* (ICLR \d{4})\.")
    b.rx("rs_gvgai_ms", "rs_related", r"\*\*(\d+) ms per tick\*\*", lambda s: s + " ms")
    b.rx("rs_reader_size", "rs_related", r"prose → program reader \((\d+\.\d+B) LoRA, failed\)")
    b.rx("rs_e2_states", "rs_related", r"at least (10\^\d+) states", lambda s: "10" + s.split("^")[1].translate(str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")))
    b.rx("rs_e2_lowcov", "rs_related", r"low-coverage share ≥ (\d+%)")
    refs = re.findall(r"^\d+\. \[[vm][^\]]*\] ", RW[RW.index("## References"):], re.M)
    put("rs_rw_refs", str(len(refs)), "rs_related", regex=r"^\d+\. \[[vm][^\]]*\]  (after '## References')", raw=len(refs),
        derived="number of numbered references")
    for kw, url in (("[v] Lehrach", "https://arxiv.org/abs/2510.04542"), ("[v] Zuo", "https://arxiv.org/abs/2407.03321"),
                    ("[v] Perez-Liebana, Liu", "https://arxiv.org/abs/1802.10363"), ("[v] Taitler", "https://arxiv.org/abs/2211.05939"),
                    ("[v] Chen, Thiébaux", "https://arxiv.org/abs/2312.11143"), ("[v] Garg", "https://proceedings.mlr.press/v119/garg20a.html"),
                    ("[v] Kagitha", "https://arxiv.org/abs/2505.14763"), ("[m] Keller", "https://github.com/prost-planner/prost")):
        req(any(kw in ln and url in ln for ln in RW.split("\n")), f"link {url} is not the review's link for {kw}")
    for s in (f"Δ̂+ = {val['gp_est']}", f"rr_like scores {val['st_rr_like']}", f"{val['r_exact']}/{val['r_G']}", f"V2 scores {val['g_theta']}"):
        req(s in RW, f"review text disagrees with the receipts: {s!r} not found")

    # ---------- Game Arena: descriptive V2 vs Jev counts ----------
    o = AP["overall"]["v2_vs_jev"]
    for key, f in (("n", "rs_jev_n"), ("wins", "rs_jev_w"), ("ties", "rs_jev_t"), ("losses", "rs_jev_l")):
        b.j(f, "rs_arena_page", f"overall|v2_vs_jev|{key}", str, AP)
    pj = [p for g in AP["games"] for p in g["pairs"] if (p["a"], p["b"]) == ("v2", "jev")]
    req(len(pj) == len(AP["games"]) and all(p.get("claim") == "descriptive" for p in pj), "a V2-vs-Jev pair is not labelled descriptive")
    req(all(sum(p[k] for p in pj) == o[k] for k in ("n", "wins", "ties", "losses")), "V2-vs-Jev totals != sum over games")
    req(AP["claim_rule"]["jev"].startswith("Descriptive only"), "Arena page no longer labels Jev descriptive")
    req(AP["meta"]["sources_sha256"]["arena_v2.json"] == b.receipts[REC + "arena_v2.json"], "Arena page built from another arena_v2.json")
    req(any("live realtime records" in n and "1-tick reply" in n for n in AP["notes"]), "FAQ timing caveat not in the Arena notes")
    req(C["predeclared"]["snake_policy_rule"]["result"]["policy"] == "sdk_pack" and "core game head" in C["predeclared"]["rr_booster_policy"],
        "FAQ says Snake = search pack, RR/Booster = core game head")


def blocks(v, vb=None):
    B = {}
    rw = f'{GH_BLOB}bench/burst_v2/RELATED_WORK.md'
    rec = lambda name: f'<a href="{GH_BLOB}{REC}{name}"><code>{name}</code></a>'

    B["learned"] = (
        '<h3>Why the learned core could not help</h3>'
        f'<p>The learned core added nothing measurable on unseen machines: Δ̂+ = {v("gp_est")}, so claim G+ is {v("gp_result")}. '
        'By construction that was close to certain. The core may only reorder moves that the exact search already rates as tied '
        'for best. When the tied moves are all truly optimal, the run with the core and the run with search alone both play '
        'optimally and cannot differ; the core matters only where a tie hides a worse move.</p>'
        f'<p>And the test machines are small for the search: the median machine has {v("c8_reach_med")} reachable states and '
        f'the largest {v("c8_reach_max")}, against {v("cfg_sims")} simulations per decision. The search exhausted its tree on '
        f'{v("c8_exhausted")} of decisions, and {v("c8_high")} were high-coverage. The same search with no core (and a slightly '
        f'larger budget) scores '
        f'{v("rs_so_theta")}. So this null answers a narrow question (does a tie-breaking prior help a near-exhaustive search on '
        'small machines?), not whether learning can generalize. That needs machines the search cannot cover: E2 below.</p>'
        '<h3>The prose reader failed, in line with the literature</h3>'
        f'<p>Our small ({v("rs_reader_size")}-parameter) prose reader turned {v("r_exact")} of {v("r_G")} sealed rulebooks into '
        f'exactly the right machine (gate R {v("r_result")}). With it in front, success on unseen machines would be '
        f'{v("prose_G")} instead of {v("g_theta")}, so V2 ships the exact parser. That is in line with published results: strict semantic '
        f'checks are much harsher than "it parses". <a href="https://arxiv.org/abs/2407.03321">Planetarium</a> '
        f'({v("rs_pl_venue")}) reports {v("rs_pl_model")} at {v("rs_pl_parse")} parseable and {v("rs_pl_solv")} solvable, but '
        f'only {v("rs_pl_sem")} semantically correct, and <a href="https://arxiv.org/abs/2505.14763">small open models</a> are '
        'known to be weak formalizers without inference-time scaffolding. Our transition-exact check is a strict test of the '
        'same kind.</p>'
        '<h3>The planner leaves success on the table</h3>'
        '<p>Every Zoo-Unseen-D machine was admitted only if an exact oracle, a policy solved offline from the rules with no '
        f'privileged view of hidden state, succeeds at least {v("rs_oracle_min")} of the time. That floor was fixed in the '
        f'family gate on {v("rs_t_oracle_rule")}, before the test set was final ({v("rs_t_d_final")}). V2 scores {v("g_theta")} '
        f'and the same search with no core {v("rs_so_theta")}: at least {v("rs_gap_lb")} below the oracle\'s mean on the same '
        'machines (V2\'s score is an estimate, the oracle\'s is exact).</p>'
        f'<p>The shortfall is concentrated. The Rotorwash-like stratum scores {v("st_rr_like")}. Of the {v("g_domains")} '
        f'domains, {v("rs_weak_n")} score below {v("thr_ns")} ({v("rs_weak_list")}), all of them Rotorwash-like, and they hold '
        f'{v("rs_weak_share")} of the failed test episodes. The open explanations: V2 cannot plan to gather information (it '
        'averages its lookahead over the possible hidden states), its lookahead is too shallow, or its leaf values are too '
        'crude. E1 is designed to tell them apart.</p>')

    B["oracle"] = (
        '<p class="oracle">Reference: every Zoo-Unseen-D machine was admitted only if an exact oracle succeeds at least '
        f'{v("rs_oracle_min")} of the time ({v("g_families")} families / {v("g_domains")} domains). V2 θ̂ {v("g_theta")}; '
        f'the same search with no core {v("rs_so_theta")}. The gap is the planner\'s: mostly the Rotorwash-like stratum '
        f'({v("st_rr_like")}) and {v("rs_weak_n")} domains below {v("thr_ns")}, which hold {v("rs_weak_share")} of the failed '
        'episodes.</p>')

    B["related"] = (
        '<p>V2 is a model-based planner: it is told the rules and searches them. That family is well studied, and in it '
        'generalization to unseen tasks comes from search on a given model, which is what C8 found for V2. Our own review '
        'says it plainly: every part that produces V2\'s unseen-task success is textbook material, and what is worth showing '
        'is the evaluation method.</p>'
        '<ul class="next">'
        '<li><b>Planning languages and planners.</b> RDDL already expresses everything mz-1x can. PROST, the UCT-based '
        'planner for RDDL (<a href="https://github.com/prost-planner/prost">source</a>), ships with '
        '<a href="https://arxiv.org/abs/2211.05939">pyRDDLGym</a>, the official evaluation system of the planning '
        'competition (IPPC). Fast Downward is a domain-independent planner for classical PDDL. These planners are '
        'domain-independent by construction, so they apply to unseen machine kinds with no learning at all.</li>'
        '<li><b>Hidden state.</b> POMCP and DESPOT are the standard online POMDP solvers, and both can plan to gather '
        'information. V2 averages its lookahead over the possible hidden states (QMDP-style), which cannot.</li>'
        '<li><b>General game playing.</b> GGP players get the full rules as a logic program and play games they have never '
        f'seen, through search. <a href="https://arxiv.org/abs/1802.10363">GVGAI</a> agents play hidden test games with a '
        f'forward model and {v("rs_gvgai_ms")} per tick.</li>'
        '<li><b>Learned planning.</b> ASNets, STRIPS-HGN, <a href="https://arxiv.org/abs/2312.11143">GOOSE</a> and '
        '<a href="https://proceedings.mlr.press/v119/garg20a.html">SymNet</a> learn from the formal description and report '
        'gains where search alone is too expensive, mostly on larger instances. V2\'s core is the same idea, tested where '
        'search is cheap.</li>'
        '<li><b>Closest prior work.</b> <a href="https://arxiv.org/abs/2510.04542">Code World Models for General Game '
        f'Playing</a> ({v("rs_cwm_venue")}): an LLM writes the game model once, from the rules text and example trajectories, then tree search plays. '
        'V2 has the same split (rules, then an exact model, then search), with an exact parser for a small language in place '
        'of the LLM. The external-LLM reader planned for V2.1 would put V2 in the same pattern.</li>'
        '</ul>'
        '<p>What is narrowly ours: the learned prior can only reorder the planner\'s exact ties, so it can never pick a move '
        'the planner proves worse (safe by construction, and the reason it could not help here); the C8 rule that every '
        'unseen-task number carries how much of the state space the search saw; and the protocol below. '
        f'<a href="{rw}">The full review</a> lists {v("rs_rw_refs")} references; on this page, works the review could not re-check '
        'are named without venue or year.</p>')

    B["next"] = (
        '<ul class="next">'
        '<li><b>E1 · Where the planner stands.</b> Run standard planners on the already-opened test set at the same '
        'per-decision CPU budget: the exact oracle as the ceiling, POMCP (and DESPOT if feasible), PROST, a GVGAI-style tree '
        'search, and V2 itself, with every setting fixed on development machines first. Prediction: POMCP beats V2 on machines '
        'with hidden variables, because V2 cannot plan to gather information. If it does not, the gap is depth or leaf value. '
        'Numbers on the opened set are diagnostic only. The design was written down on '
        f'{v("rs_t_e1")} (research commit <code>{v("rs_e1_commit")}</code>) and will be frozen by hash before any run.</li>'
        '<li><b>E2 · Learned guidance on large machines.</b> Fresh sealed machines with at least '
        f'{v("rs_e2_states")} reachable states, far beyond the search budget, and a low-coverage share of at least '
        f'{v("rs_e2_lowcov")} under the C8 rule. The core guides the search with priors and leaf values instead of breaking ties. The test is the '
        'preregistered G+ test again: refuted if core-guided search does not beat the same search alone at equal latency. A '
        'positive result would be the claim V2 could not make: a learned prior that transfers to unseen rules and improves '
        'search.</li>'
        '<li><b>E3 · Unseen Game Arena: agent alone vs agent + Nagi.</b> The same coding agent plays unseen games, with and '
        'without Nagi as its decision tool, against a Jev decision baseline and an exact-oracle ceiling. Prediction: the agent '
        'with Nagi succeeds more often; refuted if it does no better than the agent alone. Planned: the preregistration is in '
        'progress; no results.</li>'
        '</ul>'
        '<p class="note">The Zoo-Unseen benchmark itself will be released with the Nagi Machine Zoo data (coming), so others '
        'can run these comparisons too.</p>'
        '<p class="note">No result is claimed for any of these. Each gets a preregistration with its refutation rule before it '
        'runs.</p>')

    B["method"] = (
        '<p>The release followed one fixed order, and every step left a dated, hashed receipt.</p>'
        '<ul class="lims">'
        f'<li><b class="k">Preregistered · {v("rs_t_prereg")}</b>Gates, test populations, statistics and the wording of every '
        f'claim were frozen in the preregistration (sha256 <code>{v("rs_prereg_sha")}</code>) before any result existed.</li>'
        f'<li><b class="k">Candidate frozen · {v("rs_t_cand")}</b>One model, one search configuration and the evaluation '
        'harness were pinned by hash in CANDIDATE.json.</li>'
        f'<li><b class="k">Sealed single look · {v("rs_t_sealed")}, same day</b>The unseen test machines and the Arena '
        'evaluation seeds were opened once, for that candidate. Every gate and claim number comes from this run.</li>'
        f'<li><b class="k">Independent recount · {v("rs_t_audit")}</b>A separate agent that had seen no result re-implemented '
        'the statistics from the preregistration text and recounted every number from the raw receipts: '
        f'{v("audit_verdict")}.</li>'
        f'<li><b class="k">Published · {v("rs_t_pub")}</b>SDK {v("sdk_tag")} and model revision '
        f'<code>{v("hf_revision_short")}</code>, with the receipts below.</li>'
        '</ul>'
        f'<p>From the preregistration freeze to publication took about {v("rs_hours")} hours (times {v("rs_tz")}). Cloud GPU '
        f'spend for all of V2-general: {v("cost_total")}, billed as finalized provider bills over {v("rs_ledgers_n")} closed '
        f'ledgers, with {v("rs_held")} still reserved; the frozen evaluation itself cost {v("cost_m4")}.</p>'
        '<h3>Dated errata and deviations</h3>'
        '<p>Departures from the plan, each dated in the run book and checked by the independent recount, which found that '
        'the errata change no number and that the deviation favours the comparator:</p>'
        '<ul class="next">'
        f'<li><b>Deviation, comparator budget.</b> The search-only comparator\'s budget bracket was {v("rs_s0_bracket")} wide '
        f'instead of the preregistered {v("rs_s0_tol")}, because the host was never quiet enough for the last timing run. '
        f'Its budget was set to the upper point, {v("rs_s0_star")} simulations, which favours the comparator. No gate uses '
        'it.</li>'
        '<li><b>Erratum, latency harness.</b> One harness file was fixed after the freeze to add the Arena game interface. '
        'Gate L (every population) and gate I on unseen machines ran the pinned file; only gate I on the Arena games used the '
        'fix, which also changes a Rotorwash/Booster timing route that no gate uses. The recount found the diff byte-identical to the dated erratum.</li>'
        '<li><b>Erratum, prose cell (descriptive).</b> On the prose path only, a move the exact machine rejects counts as a '
        'failure, never as a void. The parser path that ships is unchanged.</li>'
        '<li><b>Process note, order of R.</b> The prose-reader run (gate R) ran alongside the sealed policy runs instead of '
        'before them. It reads only the reader\'s outputs, so no policy result could enter it.</li>'
        '<li><b>Plumbing notes.</b> Two earlier run-book notes (the episodes file, an explicit configuration): the recorded '
        'hashes match in every receipt.</li>'
        '</ul>'
        f'<p class="note">Sources: <a href="{GH_BLOB}{REC}AUDIT_M4.md">AUDIT_M4.md</a> (errata and process notes), '
        f'<a href="{GH_BLOB}{REC}CANDIDATE.json">CANDIDATE.json</a> (dated deviation), {rec("timeline.json")} (commit times), '
        f'{rec("budget_m4.json")} (closed ledgers), {rec("zoo_d_admission.json")} (the admission rule above) and '
        f'<a href="{rw}">RELATED_WORK.md</a>.</p>')

    rev = v("hf_revision")
    B["faq"] = (
        '<details><summary>Is this just a planner?</summary><p>On unseen machines, mostly yes, and the release says so in its '
        f'binding sentence: {v("c83")} The learned core only reorders moves the search rates as tied. On '
        f'{v("a_rotorwash_name")} and {v("a_booster_name")} a learned game head acts every tick without lookahead, but those '
        f'games were in its training data. On {v("a_snake_name")}, V2 plays a search pack ({v("cfg_snake_sims")} simulations) '
        'with no learned core.</p></details>'
        '<details><summary>Why does learning add nothing?</summary><p>Because there was little left for it to decide. The '
        'core may only break the search\'s ties, and on machines this small the search covers much or all of the machine: median '
        f'{v("c8_reach_med")} reachable states against {v("cfg_sims")} simulations per decision. Claim G+ is '
        f'{v("gp_result")} (Δ̂+ = {v("gp_est")}). Whether learning helps where search cannot cover is E2.</p></details>'
        '<details><summary>Can it read rules written in English?</summary><p>Not in this release. The prose reader got '
        f'{v("r_exact")} of {v("r_G")} sealed rulebooks exactly right, and success through it would fall to {v("prose_G")}. '
        'V2 ships the exact parser for the Nagi machine language; a better reader and an adapter for external LLM readers are '
        'planned for V2.1.</p></details>'
        '<details><summary>Does it beat Jev?</summary><p>We do not claim that. The release gates compare V2 with Nagi Burst '
        'V1 only. Jev played the same sealed Arena seeds, but that comparison was preregistered as descriptive: no test and '
        f'no claim. Descriptively, on those {v("rs_jev_n")} seeds V2 scored higher on {v("rs_jev_w")}, the same on '
        f'{v("rs_jev_t")} and lower on {v("rs_jev_l")}. Read that with its caveats: V2 was played offline with the nominal '
        'one-tick reply (justified by its latency gate), while Jev\'s scores come from live records through a vendor API, '
        'where a slow reply lands later; and V2\'s core was trained on these games. See the '
        '<a href="../arena/#v2">Game Arena</a>.</p></details>'
        '<details><summary>What can\'t it do?</summary><p>Read plain-English rules (V2.1). Say anything about large '
        f'machines: the sealed set had {v("large_G")} families larger than the search budget. Plan for a rule you left out. '
        'Plan to gather information about hidden variables (it averages over them). Promise its latency on hardware other '
        'than the measured Apple M2. See <a href="#limits">Know the edges</a>.</p></details>'
        '<details><summary>How do I cite it?</summary><pre><code>@misc{nagi_burst_v2,\n'
        '  author  = {{Nagi}},\n'
        '  title   = {Nagi Burst V2: exact lookahead on rules you write},\n'
        f'  year    = {{{v("rs_year")}}},\n'
        f'  version = {{{v("sdk_tag")}}},\n'
        '  url     = {https://github.com/nagisanzenin/nagi},\n'
        f'  note    = {{Model: https://huggingface.co/{v("hf_repo")}, revision {rev}}}\n'
        '}</code></pre></details>')
    return B
