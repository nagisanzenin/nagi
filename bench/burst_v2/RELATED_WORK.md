# Nagi Burst V2: related work, novelty, and whether to publish and promote it

**Status:** review, 2026-10-14. Desk research only: primary papers and official pages, 29 web searches and fetches,
$0. Numbers about V2 come from the frozen receipts (`receipts/m4/RESULT.json`, `RESULT_ADDENDUM.json`,
`AUDIT_M4.md`, `REPORT_M5.md`) and the lane docs cited inline. Nothing here changes a gate or a released number.
Reference markers: **[v]** means the venue and content were checked in this session, and **[m]** means a well-known
paper cited from memory and not re-checked (§7).

## 0. Verdict first

**Where this goes and why.** V2 measured rung 4 of the VISION ladder (operating machine kinds never seen before) and
rung 5 (closed-loop control of the 3 Arena games, which are seen tasks). The owner asked two things. Is V2 a
significant technical or scientific advance? Is it worth publishing and promoting? The answer decides whether V2
gets a paper and outreach, or a quiet tool release plus one cheap experiment that could turn it into a contribution.

1. **No significant scientific advance, as released.**
   - Every component that produces V2's unseen-task success is textbook material:
     - a factored discrete stochastic-dynamics language, a small subset of what RDDL and PPDDL can express;
     - action delay handled by putting the pending-action queue into the state;
     - depth-limited expectimax on the exact simulator;
     - QMDP-style averaging over a set-valued belief.
   - The receipts attribute the unseen-task success to that lookahead, not to learning (C8). The learned core adds
     nothing measurable: Δ̂+ = −0.003, family 95% interval [−0.009, +0.003].
   - The released numbers contain two findings that weaken the headline further (§4.5):
     - **(a)** Every Zoo-Unseen-D machine was admitted only if an exact, non-privileged offline policy succeeds ≥ 0.95
       of the time. V2 scores 0.854, so its own planner leaves at least about 0.10 on the table. The gap is
       concentrated in one stratum: rr_like scores 0.484.
     - **(b)** The only external-looking comparator, V1, is our own weak model. V1 never lands on Booster and lost
       to a naive bot on Snake.
2. **Publish: yes.** It is already public (HF `nagisanzeninz/Nagi-Burst-V2`, SDK v0.7.0). Publish it in three forms:
   - **a tool:** a small, CPU-only, exact decision SDK for small discrete machines;
   - **a short technical report** whose main content is the evaluation method and the negative results;
   - **a candidate benchmark** (Zoo-Unseen with its exact oracles and the transition-exact prose checker).

   Do not publish it as a model or capability paper.
3. **Promote: modestly**, on the honesty and methodology angle and the benchmark, using only the safe claims in
   §5.2.
   - Do not use AGI or "fast decision model" framing.
   - Do not headline "beats a 27B model" without "our own earlier model, on seen tasks".
4. **The smallest experiment that would make it real science is E1** (§5.3, $0, CPU). It is a preregistered
   baseline panel on the already-opened D set, with configs frozen on dev, under equal per-decision CPU budgets:
   - an exact offline solver as the ceiling;
   - POMCP or DESPOT (online POMDP solvers);
   - PROST, through an mz→RDDL exporter;
   - a GVGAI-style open-loop MCTS.

   E1 places V2's planner in the literature in about one day of work. **E2** is the experiment that could support a
   learning claim. It needs fresh sealed machines whose reachable sets are far larger than the search budget, and
   a core used for priors and leaf values instead of tie-breaks. That is V3's question.

## 1. V2 in the literature's own terms

| V2 component (receipts) | Standard name | Closest prior work |
|---|---|---|
| mz-1 / mz-1x DSL: ≤ 10 integer vars, ≤ 3 controls × 3 settings (27 joints), ordered rules, chance input, crash/goal | factored finite MDP described in a declarative action language | RDDL [12] (int-valued fluents, concurrency, stochastic effects, POMDP variant); PPDDL; VGDL [2] and PuzzleScript [8] for games |
| reply delay 0–2 ticks, simulated exactly with a pending queue | constant-delay MDP via state augmentation | Katsikopoulos & Engelbrecht 2003 [16] |
| hidden vars + history window ≤ 6; belief v1b = sound superset of B(x) filtered by one-tick consistency | finite-history POMDP; set-based Bayesian filtering | POMDP online planning survey [18] |
| exact layered expectimax, iterative deepening, k_max 40, ≤ 100k one-tick sims, rewards −1/−200/+49, γ 0.99 | depth-limited expectimax (*-minimax family) on a perfect generative model | Ballard 1983 [17]; THTS/UCT in PROST [13] |
| Q̄ = mean over belief roots | QMDP | Littman, Cassandra & Kaelbling 1995 [19]; known not to value information gathering, which `lanes/runtime.md` §7 item 7 also notes |
| core: 3.1M-param structure-aware transformer over program tokens, heads for a joint prior, a value and P(j ∈ A*) | program/graph-conditioned policy-value network | SymNet [25] (RDDL graphs), ASNets [22], STRIPS-HGN [23], GOOSE [24], Ståhlberg et al. [26] |
| core used only to order the planner's exact tie set when confidence ≥ τ | learned tie-breaking | tie-breaking in heuristic search, Asai & Fukunaga 2017 [27] |
| RR / Booster game heads distilled from exact teachers plus DAgger, acting per tick without lookahead in < 1 ms | amortized planning / imitation of an oracle | DAgger [35]; Expert Iteration [33]; Ruoss et al. 2024 (270M transformer distilled from Stockfish) [34] |
| prose → program reader (0.8B LoRA, failed); Opus probe 33/33 on dev | NL → formal world model ("LLM as formalizer") | LLM+P [37], Guan et al. [38], Planetarium [41], Text2World [42], survey [44] |

## 2. Comparison table

"Needs a model?" asks whether the system must be given the rules or simulator. "Unseen tasks" describes the strongest
held-out claim in the cited paper. Latencies are those reported in, or implied by, the cited setting, not measured
here.

| System (year, venue) | Input formalism | Needs a model? | Learned part | Generalization to unseen tasks | Per-decision latency | Open source |
|---|---|---|---|---|---|---|
| GVGAI planning-track agents (MCTS, RHEA) [1,3] (AAAI 2016; IEEE ToG 2019) | VGDL | yes (black-box forward model) | none in the classic track | hidden test game sets by design; no single agent dominates [3] | **40 ms per tick**, plus 1 s at start [3] | yes (framework) |
| Ludii + MCTS / policy-value transfer [4,5] (ECAI 2020; TMLR 2023) | Ludii ludemes | yes | optional policy-value nets, transferred zero-shot or fine-tuned between games | 1000+ games; zero-shot transfer between games and variants [5] | configurable (typically ≥ 1 s) | yes |
| GGP players: CadiaPlayer, Generalised AlphaZero [6,7,9] (IEEE TCIAIG 2009; AAAI 2020) | GDL / GDL-II | yes (logic program) | none (CadiaPlayer) / AlphaZero trained per game | unseen games at match time, through search | start and play clocks (seconds) | partly |
| OpenSpiel [10] (arXiv 2019) | game API in code | yes | many (AlphaZero, CFR, …) | per game | varies | yes |
| PuzzleScript evaluation, GEBestFS [8] (IEEE CIG 2014) | PuzzleScript | yes | none | any game in the language | offline search | partly |
| Fast Downward [11] (JAIR 2006) | PDDL | yes | none (classic) | domain-independent: any PDDL domain | seconds to minutes per plan | yes |
| PROST [13] (ICAPS 2012), IPPC / pyRDDLGym [14] | RDDL | yes (generative) | none | domain-independent (IPPC benchmarks) | anytime; seconds per step in IPPC settings | yes |
| POMCP [20] (NeurIPS 2010), DESPOT [21] (NeurIPS 2013 / JAIR 2017) | black-box POMDP simulator | yes | none | domain-independent | anytime (ms to s) | yes |
| ASNets, STRIPS-HGN, GOOSE, GNN general policies [22–26] (AAAI 2018 – AAAI/ICAPS 2024) | PDDL (ASNets also PPDDL); SymNet: RDDL | yes | GNN policy or heuristic | larger or unseen instances of a domain; STRIPS-HGN and GOOSE also domain-independent heuristics | one forward pass, or per node inside search | yes |
| AlphaZero [28] / MuZero [29] / EfficientZero [30] (Science 2018; Nature 2020; NeurIPS 2021) | rules (AZ) / none (MuZero, EZ) | AZ yes; MuZero/EZ learn it | policy, value (+ dynamics) per environment | none across environments | hundreds of sims per move on accelerators | AZ/MZ no (pseudocode); EZ yes |
| DreamerV3 [31] (Nature 2025), TD-MPC2 [32] (ICLR 2024) | observations | learned | world model + actor/critic; TD-MPC2 multitask | per task; limited few-shot transfer | ms | yes |
| Decision Transformer [45] (NeurIPS 2021), Gato [46] (TMLR 2022) | trajectories / tokens | no | sequence model | DT per task; Gato 604 tasks, weak on held-out tasks | ms to tens of ms | DT yes, Gato no |
| Amortized chess, Ruoss et al. [34] (NeurIPS 2024) | board | no (at inference) | 270M transformer distilled from Stockfish | one game, unseen positions | one forward pass | yes |
| LLM+P [37], Guan et al. [38], LLM-Modulo [39] (2023–2024) | NL → PDDL via LLM, then a planner | yes (LLM-written) | frozen LLM | as good as the translation | LLM calls (s) + planner | partly |
| Code as Policies [36] (ICRA 2023) | NL → Python policy | no world model | frozen LLM | per prompt | s | yes |
| WorldCoder [40], GIF-MCTS / CWMB [43] (NeurIPS 2024) | NL + interaction → Python world model | LLM-synthesized | LLM | transfer by editing code | planner on code (fast); LLM offline | yes |
| Code World Models for GGP [47] (ICLR 2026) | rules text + trajectories → Python model, inference functions for hidden state, value functions | LLM-synthesized | LLM once, then MCTS | 10 games, 4 of them novel; matches or beats Gemini 2.5 Pro on 9/10 | MCTS budget | not checked |
| XLand-MiniGrid [48] (NeurIPS 2024 D&B), Kinetix [49] (ICLR 2025) | procedurally generated rules / physics | no (agent learns) | meta-RL / generalist RL policy | unseen rulesets (XLand); zero-shot on human-designed levels (Kinetix) | ms | yes |
| ARC-AGI-3 [51] (2026) | rules withheld; interactive | no | — | frontier models < 1% at launch (single secondary source) | — | public games |
| **Nagi Burst V2 (2026, this repo)** | **mz-1 / mz-1x DSL, exact parser** (prose reader failed) | **yes (rules text)** | **3.1M structure-aware transformer, used only to break the planner's exact ties (τ 0.6); game heads for RR/Booster** | **θ̂ 0.854 on 48 unseen families / 16 domains (lower 0.760 / 0.706), but attributable to search: Δ̂+ −0.003; search-only 0.857** | **p95 UCB ≤ 50.8 ms, 1 M2 core (D 41.8 ms)** | **yes (Apache-2.0 weights, SDK)** |

## 3. How each area relates (short)

**3.1 General game playing.**
- GVGAI is the closest analogue to V2's setting: unseen games, a given forward model, and a hard per-decision budget
  (40 ms per tick) [1,3].
- GGP gives the full rules as a logic program and plays games never seen before [6,7]. Ludii and OpenSpiel are the
  current open platforms [4,10]. All of them get generalization to unseen games from search on a given model, which
  is what V2's C8 finding says about V2.
- The learned-across-games line (Generalised AlphaZero [9], Ludii transfer [5]) trains per game, or transfers between
  related games. None of them claims that a learned prior transfers zero-shot to unrelated rule sets and improves
  search. That is the claim V2's G+ tested and could not support.

**3.2 Automated planning.**
- **RDDL [12] and the language.** RDDL already expresses everything in mz-1x. Integer fluents, stochastic effects,
  concurrent actions and partial observability are all in it. A delay can be modelled with queue fluents.
- **PROST and IPPC.** PROST [13] (UCT/THTS) was the IPPC 2011 and 2014 winner [14]. It is the natural baseline for
  "exact lookahead on given rules". It is domain-independent by construction, so it "generalizes to unseen machine
  kinds" without any learning.
- **POMDP solvers.** For hidden variables, POMCP [20] and DESPOT [21] are the standard online solvers. Both handle
  information gathering, which QMDP [19] cannot.
- **V2's planner.** It is a sound but deliberately simple point in this space. Its strength is exactness on tiny
  state spaces and a fixed CPU budget. It is not a new planning algorithm.

**3.3 Learned generalized planning.**
- ASNets [22], STRIPS-HGN [23], GOOSE [24], Ståhlberg–Bonet–Geffner [26] and SymNet [25] learn from the formal
  description and generalize, mostly to larger instances of training domains. GOOSE and STRIPS-HGN also train
  domain-independent heuristics.
- They report positive learning effects in regimes where search alone is too expensive (large instances).
- V2's core is the same idea (a typed, relation-biased encoder over the program), applied across unseen domains. It
  was tested in a regime where search is not too expensive (§4.4), so it could not show the effect.

**3.4 Learned model or policy plus search; generalist decision models.**
- **AlphaZero, MuZero and EfficientZero [28–30].** In these systems the learned prior and value matter because the
  search budget is small relative to the tree. Gumbel MuZero [52] makes the point sharply with very few simulations.
  V2's budget (100k simulations) exceeds the median reachable set (922 states) by about 100×, so a prior has little
  to add.
- **DreamerV3, TD-MPC2, DT and Gato [31,32,45,46].** These learn without given rules and do not claim zero-shot
  transfer to new dynamics. They are not like-for-like comparators. V2 is told the rules.
- **Amortized planning [33–35].** This is the line behind the owner's "System One" vision: a fast network that
  imitates a slow exact planner. In V2 it appears only in the RR and Booster game heads, which act without lookahead
  in < 1 ms. Those games are seen tasks.

**3.5 LLMs plus planners, and NL → formal models.**
- **The established pattern.** The LLM translates and the symbolic engine plans and checks [36–44, 47]. Kambhampati
  et al. argue LLMs cannot plan alone but can help inside LLM-Modulo loops [39].
- **The Opus probe.** Opus at 33/33 transition-exact on dev (Wilson [0.896, 1.000]) is a data point inside this
  pattern. CWM-for-GGP [47] is the same product architecture published at ICLR 2026: an LLM writes the model once,
  then search plays. Curtis et al. [57] do the same for POMDPs with hidden state, the analogue of V2.1's goal.
- **The failed 0.8B reader.** Small open models are known to be weak NL→PDDL formalizers without inference-time
  scaffolding [50]. Strict semantic-equivalence metrics are much lower than "parses" or "solvable" rates:
  Planetarium reports GPT-4o at 96.1% parseable, 94.4% solvable, but 24.8% semantically correct [41].
- **What our reader result adds.** Our 23/48 is consistent with that literature, so it is not a surprising negative.
  Its most useful part is the measured dev→sealed author-style gap (train val 0.89, reader-dev 0.64, sealed 0.48).
- **Confound.** The D families and the dev prose were written by Claude agents, and the 33/33 translator was also
  Claude. A shared-style advantage cannot be excluded.

**3.6 Unseen-rules benchmarks.**
- XLand-MiniGrid [48], Kinetix [49] and RTFM [53] test learned agents on new rules or dynamics. ARC-AGI-3 [51]
  withholds the rules entirely.
- These are harder settings than V2's. In V2 the rules are given exactly, which turns "unseen task" into a planning
  problem that any domain-independent planner already solves in principle.

## 4. Novelty assessment

### 4.1 Well known (not new), specifically
1. **The DSL.** A strict subset of RDDL's expressiveness [12], with a custom concrete syntax. The novelty is in
   product ergonomics (bounded, typed, exact parser that rejects instead of guessing), not in formal power.
2. **Delay handling.** Exact simulation of the pending-action queue is the standard augmentation [16].
3. **Search.** Depth-limited expectimax on the true model, with iterative deepening and fixed budgets [17]. Its
   generalization to unseen machines is inherited from the given model, as for Fast Downward, PROST, POMCP and every
   GGP player.
4. **Belief.** QMDP over a sound superset of the belief [19]. Its known blind spot (no information gathering) is
   listed in `lanes/runtime.md` §7 and is a plausible cause of the rr_like failures (§4.5).
5. **The learned core.** A program-conditioned policy-value net [22–26]. Distilling exact teachers with DAgger for
   the game heads [33–35].
6. **The LLM-as-formalizer route**, including the external-LLM adapter planned in BACKLOG_V3 B2 [37–44, 47].

### 4.2 Narrowly distinctive (true, but small)
1. **Learned prior confined to the exact tie set.** The learned part can only reorder joints the planner already
   rates as tied-optimal, behind a confidence gate. By construction it can never pick an action the planner proves
   worse. It is a clean safety pattern, but it is also why it cannot help (§4.4). We did not find this exact pattern
   in the surveyed papers. Learned tie-breaking in search exists [27].
2. **A bounded, CPU-only, numpy-only SDK.** It has typed, replayable decisions (session and step draws) and gate I
   (text path = structured path, 0 / 7,506 mismatches). It is a solid engineering artifact. It is not a research
   result.
3. **The C8 coverage-disclosure rule.** Every unseen-task number must carry the |R(M)| distribution, the share of
   exhausted searches, and a low-coverage subset. The surveyed GGP and GVGAI evaluations control time or simulation
   budgets but do not report how much of the state space the search covers. This is a reusable reporting practice
   for any "generalization" claim made by an agent that has a model.

### 4.3 Methodology contribution (the strongest part)
- **The protocol.**
  - preregistration with a sha-frozen analysis script;
  - a sealed single look;
  - family- and domain-clustered bounds, leave-one-domain-out, and Holm control of the claims;
  - intersection-union gates;
  - CRN pairing;
  - an independent recount with its own code (MATCH);
  - dated errata;
  - a refutation table checked after the fact.
- **How it compares.** This is well above common practice in RL and planning papers. It follows the
  recommendations of Agarwal et al. [54], Henderson et al. [55] and the NeurIPS pre-registration workshops [56].
- **What it is worth.** It is exemplary process, and worth showing. On its own it is not a scientific finding.
  Reviewers value it most when it backs a non-trivial hypothesis.

### 4.4 What the negative results are worth
**G+ null (Δ̂+ = −0.003, family 95% [−0.009, +0.003], domain [−0.011, +0.005]).**
- It is well powered and honestly reported.
- It was also almost guaranteed by design. The derivation (a sketch, under the planner's own model):
  - Both arms draw only from the planner's tie set A(x): the core arm reorders inside it, and search_only draws
    uniformly from its own A₀(x) at 109,375 simulations.
  - Any policy that always picks from argmax Q* is optimal (a standard result [15]). So if A(x) ⊆ A*(x) and
    A₀(x) ⊆ A*(x) at every reachable decision, both arms have the optimal success probability and Δ+ = 0 exactly.
  - So Δ+ ≠ 0 needs decisions where the planner's tie set contains truly suboptimal joints and the core steers away
    from them. |Δ+| is bounded by the probability of passing through such decisions.
- **What dev measured.** On dev P, 98.5% of decisions were inside A*, with a search − oracle gap of −0.008
  (`lanes/runtime.md` §5.4). On D, the large gaps sit on hidden-variable machines, where the cause is the belief
  (QMDP, horizon) rather than tie choice. A tie-breaker cannot fix that.
- **What the null actually shows.** It is a valid null for "a tie-breaking prior adds to near-exhaustive search on
  small machines". It does not test whether a learned value or prior generalizes across machine kinds. Publish it
  with that scope.

**C8 itself is the most useful finding.**
- On machines with a median of 922 reachable states and 100k simulations, "unseen-task success" measures the planner.
- Unseen-task benchmarks for agents with a model need state spaces far beyond the search budget. Otherwise any
  deep-enough search scores near the oracle.

**Reader failure (23/48, prose path θ 0.469 vs parser 0.854).**
- It is consistent with the small-model formalizer literature [41, 50].
- It is worth a paragraph, not a paper.

### 4.5 Two receipt-level facts that weaken the headline
1. **The planner is about 0.10 below a cheap exact solution on the released benchmark.**
   - Every D machine passed the family gate's V3 check at the `v2g-zud` profile: exact success of the non-privileged
     view-based V∞ label policy ≥ 0.95 (`codex_jobs/v2g_common/famgate.py`, PROFILES and V3).
   - V2 scores 0.854. The failures are concentrated in the rr_like stratum (θ 0.484, 12 families) and in four
     domains:
     - cargo_airdrop 0.146;
     - avalanche_control 0.333;
     - rail_hump_yard 0.458;
     - tower_bell_ringing 0.833.

     The other 12 domains are all at ≥ 0.94.
   - For machines this small (|R| ≤ 25,921 on D; the family gate caps |S| at 60k), an exact offline solve once per
     task is affordable, in the same way the reader is allowed to run once per task. It would beat the shipped
     product. NORTH_STAR's "no exhaustive enumeration" is a benchmark convention, not a user benefit.
   - Product implication: offer an `exact_solve` mode for small machines and keep the search for large ones.
2. **The Arena comparator is weak.**
   - V1 (our 27B) never lands on Booster and lost to a naive bot on Snake (`STORY_AND_PATH.vi.md`, timeline row
     09-27/29).
   - V2's Snake policy is a search pack with no learned core.
   - The 71 wins / 1 tie / 0 losses result is real and replay-exact. Scientifically, it shows that search on an exact
     model, or an oracle-distilled small policy, beats an LLM policy on seen real-time games. The literature already
     expects that [39, 47].

## 5. Recommendation

### 5.1 Publish: yes, as a tool, a report and a benchmark (not as a capability model)
- **Tool (done).** Keep the HF card and SDK. Their wording already follows C8.3 and the G+ disclosure.
- **Technical report (arXiv, cs.AI, about 8 pages).**
  - Suggested framing: "Unseen-task success is lookahead, not learning: a preregistered, sealed evaluation of a tiny
    search-plus-learning decision SDK".
  - Contents: the protocol, C8, the G+ null with the §4.4 derivation, the reader negative, and E1's results if
    available.
  - Without E1 it is a workshop-level negative-results note.
- **Benchmark.** D is opened, so releasing it costs nothing scientifically. Release Zoo-Unseen-D, Zoo-Unseen-C and
  the dev zoo with:
  - per-machine exact oracle success and |R|;
  - prose rulebooks;
  - the transition-exact checker;
  - authorship metadata;
  - an mz → RDDL exporter.

  Its distinct value against Planetarium [41] and Text2World [42] is that it covers stochastic, delayed and
  partially observable control with exact semantic equivalence and exact optimal success. Caveats to state: the
  machines were authored by LLM agents and the state spaces are small.

### 5.2 Promote: where and how; safe vs unsafe claims
- **Where:**
  - the HF card and GitHub README;
  - the arXiv report;
  - one post each on r/reinforcementlearning and the planning community;
  - a workshop submission: ICAPS PRL (planning and RL), ICAPS KEPS (NL → models), the NeurIPS GenPlan workshop, or a
    negative-results venue.
- **How much.** Low effort and proportional. The honest-evaluation angle is the hook.

| Safe (receipt-backed) | Unsafe (do not say) |
|---|---|
| "3.1M-param, numpy-only SDK; exact lookahead on small discrete machines written in a DSL; p95 ≤ 51 ms on one Apple M2 core" | "AGI", "fast decision model that generalizes", "System One generalist" |
| "0.854 success on 48 never-seen families / 16 domains (lower 97.5% 0.760 family, 0.706 domain); this success comes from exact lookahead; the learned core adds nothing measurable (Δ̂+ −0.003)" | "learns to operate unseen machines", "learning generalizes" |
| "preregistered, sealed single-look evaluation with an independent recount and dated errata" | "state of the art", any comparison to systems we did not run (Jev, PROST, LLM agents) |
| "on three seen real-time games, beats our own previous 27B LLM-based release on 71/72 sealed seeds (1 tie)" | "beats a 27B model" without "our own, seen tasks, V1 never lands on Booster" |
| "prose rulebooks: our 0.8B reader was not good enough (23/48), so V2 ships an exact parser" | "reads rules", "understands natural-language rules" |

### 5.3 The smallest experiments that would make it a contribution

**E1 (do first): baseline panel on the opened D set, with configs frozen on dev.** CPU only, $0, about 1 agent-day.
- **Why D is legitimate.** V2's D numbers are frozen. The baselines train on nothing, and their hyperparameters are
  fixed on Zoo-Dev / Zoo-Unseen-Opus before the single D run. That gives a fair paired comparison by family and CRN.
- **Arms:**
  1. the exact offline view-oracle (the ceiling, already in famgate);
  2. V2 as frozen;
  3. V2 search-only;
  4. POMCP [20] (via pomdp_py or our own on `Machine.step_dist`) and DESPOT [21] if time allows;
  5. PROST [13] via an mz → RDDL exporter;
  6. open-loop MCTS in the GVGAI style;
  7. keep / weak bot / random.
- **Budgets.** Each arm runs at an equal p95 per-decision budget on cpu-m2-1t (≈ 50 ms), plus a generous-budget
  descriptive cell.
- **Preregistered predictions (falsifiable):**
  - the oracle is ≥ 0.95;
  - POMCP beats V2 on the rr_like / hidden stratum, because QMDP does not gather information;
  - V2 is within 0.02 of PROST on plain mz-1 families.
- **What would refute us.** POMCP ≤ V2 on hidden families would mean the gap is horizon or leaf, not information.
- **Quality guard.**
  - Baseline configs are frozen before the D run.
  - The mz → RDDL exporter is checked transition-exact on every D machine before use, with the same checker as gate
    R.
  - A failed export is a failure for that arm, not a void.
- **Value.** It turns "0.854" into a position: where V2's planner stands against the standard planners, and how
  large the gap to optimal is.

**E2 (the real scientific question, V3): does learning generalize across machine kinds where search cannot cover?**
- **Population.** Fresh sealed families with |R| ≫ S*, at least 10^6 states, which the DSL allows with ≤ 10 vars ×
  ≤ 401 values.
- **Arms.** Equal-latency search-only vs core-guided search. The core supplies priors for pruning or ordering and
  leaf values (PUCT-style), not tie-breaks.
- **Gate.** The preregistered G+ test as before, with the C8 rule (low-coverage share ≥ 80%).
- **What it means.** A positive result here is a publishable claim: a learned prior or value transfers zero-shot to
  unseen rule sets and improves search. That claim is absent from [5, 9, 22–26], which transfer within domains or
  between related games. A null is still informative.

**E3 (alongside E1): release Zoo-Unseen as a benchmark (§5.1)**, with E1's baselines as the reference table.

## 6. Bottom line for the owner
- **What V2 is.** A well-built, honestly measured tool. Its unseen-task score is a property of exact planning on
  small machines, and it is about 0.10 below a cheap exact solution.
- **What is valuable.** The methodology and the benchmark.
- **The next step.** E1 is a $0 experiment that makes the report credible. E2 is the experiment that could make it
  science, and it belongs to V3.

## 7. Method and limits of this review
- **Searches.** 29 web searches and fetches, primary sources preferred. Venues and claims marked [v] were confirmed in
  this session. Items marked [m] are standard references cited from memory; their bibliographic details should be
  checked before any external text uses them.
- **Not verified:**
  - exact IPPC 2023 rankings;
  - GVGAI per-agent win rates on unseen sets;
  - whether the CWM-for-GGP code is released;
  - ARC-AGI-3 numbers, which rest on one secondary article.
- **What is internal.** The derivation in §4.4 is a sketch under standard MDP facts, not a new theorem. §4.5 item 1
  rests on the famgate `v2g-zud` profile (oracle_min 0.95, exact chain, 100-tick cap) as the D admission rule. The
  oracle's per-machine values on D were not re-read here.

## References
1. [m] Perez-Liebana, Samothrakis, Togelius, Schaul, Lucas. *General Video Game AI: Competition, Challenges and Opportunities.* AAAI 2016.
2. [m] Schaul. *A Video Game Description Language for Model-based or Interactive Learning.* IEEE CIG 2013.
3. [v] Perez-Liebana, Liu, Khalifa, Gaina, Togelius, Lucas. *General Video Game AI: a Multi-Track Framework for Evaluating Agents, Games and Content Generation Algorithms.* IEEE Transactions on Games 2019. https://arxiv.org/abs/1802.10363 (40 ms/tick, 1 s setup, forward model).
4. [m] Piette, Soemers, Stephenson, Sironi, Winands, Browne. *Ludii – The Ludemic General Game System.* ECAI 2020. https://arxiv.org/abs/1905.05013
5. [v] Soemers, Mella, Piette, Stephenson, Browne, Teytaud. *Towards a General Transfer Approach for Policy-Value Networks.* TMLR 2023. https://arxiv.org/abs/2102.12375
6. [m] Genesereth, Love, Pell. *General Game Playing: Overview of the AAAI Competition.* AI Magazine 26(2), 2005.
7. [m] Björnsson, Finnsson. *CadiaPlayer: A Simulation-Based General Game Player.* IEEE TCIAIG 1(1), 2009.
8. [v] Lim, Harrell. *An Approach to General Videogame Evaluation and Automatic Generation using a Description Language.* IEEE CIG 2014. https://people.csail.mit.edu/culim/lim2014approach.pdf
9. [v] Goldwaser, Thielscher. *Deep Reinforcement Learning for General Game Playing.* AAAI 2020. https://ojs.aaai.org/index.php/AAAI/article/view/5533
10. [m] Lanctot et al. *OpenSpiel: A Framework for Reinforcement Learning in Games.* arXiv 2019. https://arxiv.org/abs/1908.09453
11. [m] Helmert. *The Fast Downward Planning System.* JAIR 26, 2006.
12. [m] Sanner. *Relational Dynamic Influence Diagram Language (RDDL): Language Description.* 2010 (IPPC 2011).
13. [m] Keller, Eyerich. *PROST: Probabilistic Planning Based on UCT.* ICAPS 2012. https://github.com/prost-planner/prost
14. [v] Taitler et al. *pyRDDLGym: From RDDL to Gym Environments* (official IPPC 2023 evaluation system; ships PROST). https://arxiv.org/abs/2211.05939
15. [m] Puterman. *Markov Decision Processes: Discrete Stochastic Dynamic Programming.* Wiley 1994.
16. [m] Katsikopoulos, Engelbrecht. *Markov Decision Processes with Delays and Asynchronous Cost Collection.* IEEE TAC 48(4), 2003.
17. [m] Ballard. *The \*-Minimax Search Procedure for Trees Containing Chance Nodes.* Artificial Intelligence 21, 1983.
18. [m] Ross, Pineau, Paquet, Chaib-draa. *Online Planning Algorithms for POMDPs.* JAIR 32, 2008.
19. [m] Littman, Cassandra, Kaelbling. *Learning Policies for Partially Observable Environments: Scaling Up.* ICML 1995 (QMDP).
20. [m] Silver, Veness. *Monte-Carlo Planning in Large POMDPs.* NeurIPS 2010 (POMCP).
21. [m] Somani, Ye, Hsu, Lee. *DESPOT: Online POMDP Planning with Regularization.* NeurIPS 2013; Ye et al., JAIR 2017.
22. [m] Toyer, Trevizan, Thiébaux, Xie. *Action Schema Networks.* AAAI 2018; *ASNets: Deep Learning for Generalised Planning.* JAIR 2020.
23. [m] Shen, Trevizan, Thiébaux. *Learning Domain-Independent Planning Heuristics with Hypergraph Networks.* ICAPS 2020 (STRIPS-HGN).
24. [v] Chen, Thiébaux, Trevizan. *Learning Domain-Independent Heuristics for Grounded and Lifted Planning.* AAAI 2024 (GOOSE). https://arxiv.org/abs/2312.11143 ; also *Return to Tradition…*, ICAPS 2024, https://arxiv.org/abs/2403.16508
25. [v] Garg, Bajpai, Mausam. *Symbolic Network: Generalized Neural Policies for Relational MDPs.* ICML 2020. https://proceedings.mlr.press/v119/garg20a.html (it notes SymNet is not near PROST-optimal).
26. [m] Ståhlberg, Bonet, Geffner. *Learning General Optimal Policies with Graph Neural Networks.* ICAPS 2022.
27. [m] Asai, Fukunaga. *Tie-Breaking Strategies for Cost-Optimal Best First Search.* JAIR 58, 2017.
28. [m] Silver et al. *A General Reinforcement Learning Algorithm that Masters Chess, Shogi, and Go through Self-Play.* Science 2018.
29. [m] Schrittwieser et al. *Mastering Atari, Go, Chess and Shogi by Planning with a Learned Model.* Nature 2020.
30. [m] Ye et al. *Mastering Atari Games with Limited Data* (EfficientZero). NeurIPS 2021.
31. [m] Hafner, Pasukonis, Ba, Lillicrap. *Mastering Diverse Control Tasks through World Models* (DreamerV3). Nature 2025. https://arxiv.org/abs/2301.04104
32. [m] Hansen, Su, Wang. *TD-MPC2: Scalable, Robust World Models for Continuous Control.* ICLR 2024.
33. [m] Anthony, Tian, Barber. *Thinking Fast and Slow with Deep Learning and Tree Search* (ExIt). NeurIPS 2017.
34. [v] Ruoss et al. *Amortized Planning with Large-Scale Transformers: A Case Study on Chess.* NeurIPS 2024. https://arxiv.org/abs/2402.04494
35. [m] Ross, Gordon, Bagnell. *A Reduction of Imitation Learning and Structured Prediction to No-Regret Online Learning* (DAgger). AISTATS 2011.
36. [m] Liang et al. *Code as Policies.* ICRA 2023.
37. [m] Liu et al. *LLM+P: Empowering LLMs with Optimal Planning Proficiency.* arXiv 2023. https://arxiv.org/abs/2304.11477
38. [m] Guan, Valmeekam, Sreedharan, Kambhampati. *Leveraging Pre-trained LLMs to Construct and Utilize World Models for Model-based Task Planning.* NeurIPS 2023.
39. [v] Kambhampati et al. *Position: LLMs Can't Plan, But Can Help Planning in LLM-Modulo Frameworks.* ICML 2024. https://proceedings.mlr.press/v235/kambhampati24a.html
40. [v] Tang, Key, Ellis. *WorldCoder, a Model-Based LLM Agent.* NeurIPS 2024. https://arxiv.org/abs/2402.12275
41. [v] Zuo, Piedrahita Velez, Li, Littman, Bach. *Planetarium: A Rigorous Benchmark for Translating Text to Structured Planning Languages.* NAACL 2025. https://arxiv.org/abs/2407.03321
42. [v] Hu et al. *Text2World: Benchmarking LLMs for Symbolic World Model Generation.* Findings of ACL 2025. https://arxiv.org/abs/2502.13092
43. [v] Dainese, Merler, Alakuijala, Marttinen. *Generating Code World Models with LLMs Guided by MCTS.* NeurIPS 2024. https://arxiv.org/abs/2405.15383
44. [v] Tantakoun, Muise, Zhu. *LLMs as Planning Formalizers: A Survey.* Findings of ACL 2025. https://arxiv.org/abs/2503.18971
45. [m] Chen et al. *Decision Transformer.* NeurIPS 2021.
46. [m] Reed et al. *A Generalist Agent* (Gato). TMLR 2022.
47. [v] Lehrach et al. *Code World Models for General Game Playing.* ICLR 2026. https://arxiv.org/abs/2510.04542
48. [v] Nikulin et al. *XLand-MiniGrid.* NeurIPS 2024 Datasets & Benchmarks. https://arxiv.org/abs/2312.12044
49. [v] Matthews, Beukman, Lu, Foerster. *Kinetix.* ICLR 2025 (oral). https://arxiv.org/abs/2410.23208
50. [v] Kagitha, Zhu, Zhang. *Addressing the Challenges of Planning Language Generation* (v2: *Unifying Inference-Time Planning Language Generation*). arXiv 2025. https://arxiv.org/abs/2505.14763
51. [v, single secondary source] ARC Prize Foundation. *ARC-AGI-3* (launched 2026-03-25). https://www.datacamp.com/blog/arc-agi-3
52. [m] Danihelka, Guez, Schrittwieser, Silver. *Policy Improvement by Planning with Gumbel.* ICLR 2022.
53. [m] Zhong, Rocktäschel, Grefenstette. *RTFM: Generalising to New Environment Dynamics via Reading.* ICLR 2020.
54. [m] Agarwal et al. *Deep RL at the Edge of the Statistical Precipice.* NeurIPS 2021.
55. [m] Henderson et al. *Deep Reinforcement Learning that Matters.* AAAI 2018.
56. [v] Bertinetto, Henriques, Albanie, Paganini, Varol (eds.). *NeurIPS 2020 Workshop on Pre-registration in Machine Learning.* PMLR 148. https://proceedings.mlr.press/v148/
57. [v] Curtis et al. *LLM-Guided Probabilistic Program Induction for POMDP Model Estimation.* CoRL 2025 (PMLR 305). https://arxiv.org/abs/2505.02216 (LLM-written POMDP models plus belief planning: the prose-to-hidden-state analogue of V2.1).
