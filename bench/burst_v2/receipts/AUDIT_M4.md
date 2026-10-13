# AUDIT_M4: independent audit of the frozen M4 evaluation (lane audit-m4)

**Status: FINAL** (gates 2026-10-13 ~23:40 +07; descriptive addendum §11 audited ~23:50 +07, commit ee926c88). Auditor: audit-m4, an
independent sub-agent that saw no dev or sealed result before this audit. Cost: $0, CPU only, one `nice -n 10`
process at a time. During the sealed L timing window (main's pause, 22:50–23:21) the auditor ran only an idle
wait loop (one file-existence test per minute).

**Decision first.** Every gate number and the release decision recompute to exactly the values in `RESULT.json`.
- R: **FAIL**, 23/48 families transition-exact. The shipped path is therefore the **parser path**.
- A×3 / G_parser / L / I: **PASS**.
- Decision: **RELEASE V2 on the parser path**. The reader moves to V2.1.
- Claims: **NS is shown** on the full D set (Holm step 1, p = 0.00117). **G+ is not shown**: Δ̂+ = −0.0033, and the
  LODO sign fails.
- The two dated errata change no number. The S0* deviation is verified and favours the comparator.
- Process notes that are not numeric mismatches are in §9.

**Method.** Every number below is recomputed from the raw receipts with the auditor's own code in
`scripts/v2g/audit_m4/`. That code does not import `scripts/v2g/analysis.py` or any `m4_*` helper. The statistics are
re-implemented from the PREREG text; scipy supplies only the t, beta and binomial quantiles. Nothing under
`~/nagi-sealed/` was read, and nothing under `docs/burst_v2_general/release/`.

## 0. Frozen inputs

| Item | Path | Audit value | Expected | Result |
|---|---|---|---|---|
| PREREG sha256 | docs/burst_v2_general/PREREG_V2G.md | 9691f1e6693a… | 9691f1e6 | MATCH |
| CANDIDATE sha256 (HEAD = commit 59882153 blob) | docs/burst_v2_general/CANDIDATE.json | 28fe5de62675… | 28fe5de6… | MATCH |
| D addendum sha256 | docs/burst_v2_general/SPLITS_V2G_D_ADDENDUM.json | fa30ca277a19… | fa30ca27… | MATCH |
| analysis.py sha256: HEAD = PREREG v0.1 freeze commit 27be92fa = CANDIDATE.analysis_sha256 | scripts/v2g/analysis.py | 5f4716189c79… (no diff since 27be92fa) | 5f471618… | MATCH |
| V1 pins sha256 | docs/burst_v2_next/p3/baseline_pins.json | 6c4956d9f8b5… | 6c4956d9… | MATCH |
| Resolved config, rebuilt from v1b 996c2951 **without** S0 | (own rebuild) | 3f87c2a006e0… | receipts' config_sha256 3f87c2a0 | MATCH |
| Resolved config, rebuilt from v1b 996c2951 **with** S0* = 109,375 | (own rebuild) | ba5d3a822ee1…; dict = CANDIDATE.config_resolved | CANDIDATE.config_sha256 ba5d3a82 | MATCH |
| Core model file sha256 | CANDIDATE.core_model_path | a24e1158b00a… | CANDIDATE.core_weights_sha256 a24e1158 | MATCH |
| Linux image id, local tag bv2n-rr:py31112-np246 | docker image inspect | sha256:bf9b6dae7467… amd64 | CANDIDATE.readiness.image.id bf9b6dae | MATCH |
| Harness at HEAD vs CANDIDATE.harness_sha256 (m4_zoo_sdk, m4_arena, m4_pair_check, m4_sealed_tasks, m4_config, m4_freeze_candidate, operate, search, reader, machine, snake, multi_core, v1b) | files at HEAD | 14/15 equal; m4_li.py = 04b71068 (post-freeze f347e4d1) | pins | MATCH (erratum, §7) |
| No src/ change since the harness commit 2de02975 | git diff 2de02975..HEAD -- src/ | none | — | MATCH |
| zoo_d and zoo_c run.json: code_sha256 (m4_zoo_sdk, operate, search, reader), arms, τ, E | zoo_d/run.json, zoo_c/run.json | = CANDIDATE pins 4/4; candidate=G100000b1b, search_only=N109375b1b; τ 0.6; E 16 | same | MATCH |
| RESULT.identity | RESULT.json | analysis 5f471618, CANDIDATE 28fe5de6, manifest 37b1f708 (= sha of manifest.json), pinned m4_li f2a2d200 | same | MATCH |
| Readiness: B3 Snake rule (dev UCB ≤ 150 ms → SDK pack), S* = 100k (dev UCB ≤ 170 ms), recomputed from the timing CSVs | receipts/prereg/m4_readiness/timing | 86.140 ms → sdk_pack; 92.933 ms → ok; csv and stamp sha256 = CANDIDATE 9/9 | 86.140 / 92.933 | MATCH |
| Readiness: V1 pair_check eval S/B; image recert | m4_readiness/pair_check_eval_sb.json, parity_linux_recert.json | 24/24 + 24/24 ok; all_exact true | CANDIDATE.readiness | MATCH |

## 1. Gate A (Arena; PREREG §5.3)

Every receipt value is from `arena/arena.json` and `rr/arena.json` (`gate_A_form`). "Audit" is the auditor's own
recount from the per-seed CSVs. The V1 scores are re-read from the pinned record files, not from `v1_*.csv`.

| Item | Receipt path | Audit value | Receipt value | Result |
|---|---|---|---|---|
| Snake W, wins-ties-losses | arena/v2g_snake.csv, V1 records ev2_v1_sn_rt_03/04 | 1.000, 24-0-0 | 1.0, 24-0-0 | MATCH |
| Snake t_{23} lower 97.5% bound | arena/v2g_snake.csv | 1.000 (sd 0) | 1.0 | MATCH |
| Snake exact sign-flip p = P(Bin(24, ½) ≥ 24) (also full 2^24 enumeration) | arena/v2g_snake.csv | 5.960e-08 | 5.960e-08 | MATCH |
| Snake means V2G / V1 (survival_s) | arena/*_snake.csv | 50.656 / 12.573 | 50.656 / 12.573 | MATCH |
| Snake PASS_A | — | PASS | pass true | MATCH |
| Booster W, wins-ties-losses | arena/v2g_booster.csv, bv2_v1_bg_rt_01/02 | 0.97917, 23-1-0 (tie at index 52: 0 vs 0) | 0.97917, 23-1-0 | MATCH |
| Booster t_{23} lower 97.5% bound | arena/v2g_booster.csv | 0.936070 | 0.936070 | MATCH |
| Booster exact sign-flip p (k = 23 untied) | arena/v2g_booster.csv | 1.192e-07 | 1.192e-07 | MATCH |
| Booster landings (K3 > 0) and k ≥ 6 rule; V1 all zero | arena/v2g_booster.csv | 23/24, rule holds; V1 = 0 on 24/24 | 23, v1_all_zero true | MATCH |
| Booster PASS_A | — | PASS | pass true | MATCH |
| RR W, wins-ties-losses | rr/v2g_rr.csv, bv2_v1_rr_rt_01/02 | 1.000, 24-0-0 | 1.0, 24-0-0 | MATCH |
| RR t_{23} lower bound / sign-flip p | rr/v2g_rr.csv | 1.000 / 5.960e-08 | 1.0 / 5.960e-08 | MATCH |
| RR means V2G / V1 (K3-RR2.1 raw) | rr/*_rr.csv | 1.04792 / 0.35092 | 1.04792 / 0.35092 | MATCH |
| RR PASS_A | — | PASS | pass true | MATCH |
| Voids and drops per 12-seed shard (all games) | v2g_*.csv, V1 records | 0 voids; drops [0, 0] per game | [0, 0] | MATCH |
| V1 record bytes vs pins (sha256 per record) | baseline_pins.json + record files | 72/72 records; job files 24/24; player summaries 6/6 | pins | MATCH |
| V1 scores (record `score.survival_s` / `score.raw`) = pin values = v1_*.csv | v1_*.csv | 72/72 equal; rules_id = PREREG §3 ids 72/72 | — | MATCH |
| V2G seed = V1 record seed, per index | v2g_*.csv | 72/72 | — | MATCH |
| sha256(json.dumps(applied, sort_keys=True)) = CSV applied_sha256 | episodes_*.jsonl.gz | 72/72 (seed and index equal 72/72) | applied_sha256 | MATCH |
| Snake score = 0.25 s × applied ticks (consistency) | episodes_snake.jsonl.gz | 24/24 | — | MATCH |
| MANIFEST.sha256 (arena/, rr/) | arena/MANIFEST.sha256, rr/MANIFEST.sha256 | all listed files equal | listed | MATCH |
| model_sha256 in both arena.json = CANDIDATE.core_weights_sha256 = file on disk | arena.json, rr/arena.json | a24e1158… | a24e1158… | MATCH |
| config_sha256 in both arena.json = rebuilt resolved config without S0 (§0) | arena.json, rr/arena.json | 3f87c2a0… | 3f87c2a0… | MATCH |
| Snake policy = CANDIDATE `snake_policy` | arena.json | sdk (= sdk_pack) | sdk | MATCH |
| Platform: Snake/Booster Linux x86_64 py3.11.12 np2.4.6 glibc2.36 (Rosetta SSE4.2); RR Linux x86_64 AVX/AVX2/FMA3 (Modal CPU, B1) | arena.json, rr/arena.json | as stated | as stated | MATCH |
| RR in-venue V1 pair_check | rr/pair_check_eval_rr.json | 24/24 replay-exact, 0 prompt mismatches, 24/24 score-equal, ok | ok true | MATCH |
| Spot replay, engine (open loop: recorded actions → engine → score), 2 seeds per game + Booster tie seed 52 | episodes_*.jsonl.gz | Snake 19, 26; Booster 34, 50, 52; RR 44, 48: all scores equal, done exactly at the last action; in image bf9b6dae (amd64) and natively | CSV scores | MATCH |
| Spot replay, policy (closed loop, own loop around `bv2n.data.collect.rollout`, frozen policy from v1b values) | v2g_*.csv | same 6 seeds: applied sha equal 6/6, scores equal (in image bf9b6dae) | applied_sha256 | MATCH |
| **Gate A (A×3)** | — | **PASS** (Snake, Booster, RR) | pass ×3 | MATCH |


## 2. Zoo-Unseen-D, parser path: gate G and claims (PREREG §3, §5.1, §5.6, §8, C8)

Receipt: `zoo_d/` (rows.csv, decisions.jsonl.gz, reach.json, run.json; MANIFEST ok). Unit = family f; s_f = mean over
the family's valid machines of the 16-episode success rate. Recomputed by `audit_zoo.py`.

| Item | Receipt path | Audit value | Receipt value (RESULT.json) | Result |
|---|---|---|---|---|
| Admission: families / domains / per domain | zoo_d/rows.csv vs addendum fa30ca27 | 48 / 16 / 3 each; fid, domain and scored machines = addendum (96/96) | G 48, D 16, 3 each, ok | MATCH |
| Scored machines = the 2 kept with smallest sha256('v2g-zud-inst-v0\|'+machine_id) | addendum | 48/48 families | — | MATCH |
| d_families.json = addendum fids | d_families.json | equal (48) | — | MATCH |
| Validity: 16 episodes per arm, valid, crn_key = sha256(salt\|m\|e), equal across arms | zoo_d/rows.csv | 96 machines, 0 invalid; 3,072 rows | n_invalid_machines 0 | MATCH |
| θ̂_G (candidate) | rows.csv | 0.854167 | 0.854167 | MATCH |
| sd_f; L_fam = θ̂ − t_{.975,47}·sd/√48 | rows.csv | 0.323113; 0.760344 | 0.323113; 0.760344 | MATCH |
| SE_CR1; L_dom = θ̂ − t_{.975,15}·SE_CR1 | rows.csv | 0.069481; 0.706071 | 0.069481; 0.706071 | MATCH |
| LODO min | rows.csv | 0.844444 (without bobsled_run) | 0.844444 (bobsled_run) | MATCH |
| G1 / G2 / G3 → **G_parser** | — | true / true / true → **PASS** | pass true | MATCH |
| Per-domain means, candidate and search_only (16 domains) | rows.csv | 16/16 equal to 1e-12 | per_domain | MATCH |
| θ̂ search_only (N109375b1b) | rows.csv | 0.857422 | (per-domain) | MATCH |
| G+: Δ̂+, p_fam, p_dom | rows.csv | −0.003255, 0.86008, 0.80684 | −0.003255, 0.86008, 0.80684 | MATCH |
| G+: sign-flip p (200,000 draws; auditor seed 777001 vs 20261012) | rows.csv | 0.90627 | 0.90536 (Δ = 0.0009, about 1 MC sd) | MATCH (MC) |
| G+: LODO min ≤ 0 → p_claim = 1 | rows.csv | −0.004861 → 1.0 | −0.004861 → 1.0 | MATCH |
| NS (θ0 = 0.60): p_fam, p_dom, LODO min | rows.csv | 9.057e-07, 0.0011655, 0.8444 | 9.057e-07, 0.0011655, 0.8444 | MATCH |
| NS: sign-flip p | rows.csv | 5.0e-06 (1/200,001) | 1.5e-05 (3/200,001) | MATCH (MC floor) |
| NS: p_claim = max(p_fam, p_dom, p_flip) | — | 0.0011655 | 0.0011655 | MATCH |
| Holm {G+, NS} at 0.025 | — | NS rank 1, level 0.0125, **reject**; G+ level 0.025, **not rejected** | same | MATCH |
| Holm-matched bounds: NS (1 − 0.0125) family / domain; G+ (1 − 0.025) | — | 0.746178 / 0.681167; −0.009245 / −0.011031 | same | MATCH |
| Nominal 97.5% bounds NS family / domain | — | 0.760344 / 0.706071 | same | MATCH |
| C8: \|R(M)\| min / p25 / median / p75 / max | reach.json | 72 / 380.5 / 922.5 / 2,237.75 / 25,921 | same | MATCH |
| C8: share \|R\| ≤ 1,000 / ≤ 20,000 | reach.json | 0.520833 / 0.958333 | same | MATCH |
| C8: candidate decisions exhausted / high-coverage | decisions.jsonl.gz | 0.249329 / 0.482711 (46,966 decisions) | same | MATCH |
| C8: low-coverage machines (h_m < 0.5) | decisions + reach | 26, identical id list | 26 ids | MATCH |
| C8.2: low-coverage subset θ̂, G, D | — | 0.729911, 14, 9 | same | MATCH |
| C8.2: low-cov NS family lower / p; domain lower / p | — | 0.485303 / 0.13595; 0.398484 / 0.19623 | same | MATCH |
| C8.2: low-cov G+ Δ̂, family lower, domain lower | — | −0.006696, −0.028137, −0.034255 | same | MATCH |
| C8.2: policy-free subset \|R(M)\| > S* | reach.json | 0 machines | G 0 | MATCH |
| coverage_d.jsonl = candidate (machine, exhausted, visited) from decisions | coverage_d.jsonl | identical, 46,966 lines | — | MATCH |
| Episode consistency (all 3,072 episodes): t contiguous, steps = #decisions, timeout ⇒ 100 decisions, success ⇔ outcome success, sims ≤ arm budget, search_only never gated | rows + decisions | 3,072/3,072 | — | MATCH |
| CRN check: the t = 0 request sha is equal across arms | decisions | 1,536/1,536 (machine, episode) pairs | — | MATCH |
| 10 spot episodes (auditor hash order) | rows + decisions | 10/10 consistent (5 candidate, 5 search_only; 13–45 steps; max sims ≤ budget) | — | MATCH |

**Not in RESULT (descriptive, PREREG C8.1 / §5.6); auditor values for the report:**
- comparator coverage: search_only exhausted 0.249995, high-coverage 0.480421;
- Δ+ per stratum: booster_like −0.0026, mixed +0.0052, rr_like −0.0130, snake_like −0.0026.

## 3. Gate R (PREREG §5.7, §8 R)

Receipt: `reader/reader.csv` (96 rows, hash ids only). The verdicts themselves cannot be re-derived without the sealed
programs, so this is a recount.

| Item | Receipt path | Audit value | Receipt value | Result |
|---|---|---|---|---|
| Rows, duplicates, coverage of the addendum's 96 scored machines | reader.csv | 96, 0 duplicates, 96/96 present, 0 extra | — | MATCH |
| Machines exact | reader.csv | 47/96 = 0.489583 | machine_rate 0.489583 | MATCH |
| Families exact (both machines exact; missing = not exact) | reader.csv | 23/48, π̂_R 0.479167 | 23, 0.479167 | MATCH |
| R1: failing families ≤ ⌊0.05·48⌋ = 2 | — | 25 → false | false | MATCH |
| R2: Clopper–Pearson one-sided 97.5% lower bound > 0.85 | — | 0.332866 → false | 0.332866, false | MATCH |
| Failures by domain | reader.csv | 25 failures over 15 of 16 domains, max 3 per domain; not clustered | same 15 domains and counts | MATCH |
| R INVALID rule (infrastructure failures > 3% of machines) | reader.csv | 2 missing outputs = 2.1% ≤ 3%, so not INVALID even if both count as infrastructure | status OK | MATCH |
| **Gate R** | — | **FAIL → shipped path = parser** | pass false | MATCH |
| Descriptive: exact up to bijection | reader.csv | 23/48 families, 47/96 machines | — | (descr.) |

Failure categories (descriptive): transitions:rule_content 26, declaration 8, naming 7, declaration+transitions 4,
terminal_condition 2, missing 2.

## 4. Gate L (PREREG §5.4, §6.3, §8 L)

Receipts: `L/<pop>/latency_<pop>.csv` and `stamp.json`. The order statistic is u = min{u : P(Bin(n, 0.95) ≤ u − 1) ≥ 0.95}.

| Population | n | u | Audit x_(u) ms | Receipt p95_ucb_ms | p50 / p95 / p99 / max ms | > 200 / > 250 ms | Stamp (threads, cache, warm-up, load start→end) | Result |
|---|---|---|---|---|---|---|---|---|
| zoo_d | 2000 | 1917 | 41.785 | 41.785 | 9.62 / 41.09 / 44.47 / 48.23 | 0 / 0 | 1, False, 20, 2.05→2.38: VALID | MATCH |
| snake | 2000 | 1917 | 50.809 | 50.809 | 0.77 / 38.00 / 194.59 / 284.95 | 0.8% / 0.05% | 1, False, 20, 2.58→2.48: VALID | MATCH |
| rr | 2000 | 1917 | 0.492 | 0.492 | 0.37 / 0.47 / 0.62 / 0.79 | 0 / 0 | 1, False, 20, 2.48→2.48: VALID | MATCH |
| booster | 1506 | 1445 | 0.670 | 0.670 | 0.51 / 0.64 / 0.78 / 1.19 | 0 / 0 | 1, False, 20, 2.48→2.48: VALID | MATCH |

| Item | Receipt path | Audit value | Receipt value | Result |
|---|---|---|---|---|
| zoo_d same_decision (re-timed probability-vector sha = recorded) | L/zoo_d/latency_zoo_d.csv | 2000/2000 | 1.0 | MATCH |
| zoo_d sims mean / p5 / p50 | same | 33,574 / 72 / 9,967 | same | MATCH |
| Merged stamp (max load, min warm-up) | latency_stamp.json | threads 1, cache False, warm-up 20, load 2.58→2.48: VALID | invalid_reasons [] | MATCH |
| L sample = first 2,000 shipped-path requests in sha256('v2g-L-v0\|'+sha) order (checked on the I file, which uses the same sample) | I/zoo_d/interface.csv vs zoo_d decisions | equal set (2,000 of 13,363 unique candidate requests) | — | MATCH |
| **Gate L** | — | **PASS** (4/4 ≤ 200 ms, all stamps valid) | pass true | MATCH |

## 5. Gate I (PREREG §5.5, §6.4)

| Population | Receipt path | n | Mismatches (joint, support, max\|Δp\| > 1e-9) | Round-trip failures | max\|Δp\| | Result |
|---|---|---|---|---|---|---|
| zoo_d (pinned m4_li) | I/zoo_d/interface.csv | 2000 | 0 | 0 | 0 | MATCH |
| snake (erratum file) | I/arena/interface_snake.csv | 2000 | 0 | 0 | (joint only) | MATCH |
| rr (erratum file) | I/arena/interface_rr.csv | 2000 | 0 | 0 | 0 | MATCH |
| booster (erratum file) | I/arena/interface_booster.csv | 1506 | 0 | 0 | 0 | MATCH |
| Total; rule-of-three 95% bound on the mismatch rate | interface.csv (concatenation: 7,506 rows) | 7506 | 0 | 0 | — | MATCH (RESULT 7506 / 0 / 0, 3.997e-4) |
| **Gate I** | — | **PASS** (n ≥ 2,000, 0 mismatches) | | | | MATCH |

## 6. Zoo-Unseen-C (descriptive; G = 4 domains; not in RESULT.json)

Receipt: `zoo_c/` (MANIFEST ok; run.json arms and code = CANDIDATE; salt bv2n-eval-c_unseen-v0).
- **Population:** 16 families, 4 domains, 32 machines, 0 invalid.
- **Episode consistency:** 1,024/1,024. The t = 0 request sha is equal across arms 512/512.
- **θ̂:** candidate 0.892578, search_only 0.880859, so Δ+ = +0.011719. LODO min of Δ is 0.0, so G+ would not be shown.
- **C8:** |R| median 4,351 (max 67,788). Candidate high-coverage 0.392, exhausted 0.207. 14 low-coverage machines;
  the low-coverage subset has θ̂ 0.789 over 8 families.

The comparison above is descriptive only, with no receipt to compare against. It is listed so that the M5 report can
cite an independent number.

## 7. Errata and deviations (PREREG §12.3–§12.4; RUNBOOK §11)

| Item | Evidence | Audit finding | Result |
|---|---|---|---|
| ERRATUM m4_li: L (4 populations) and I on D use the pinned file; only Arena I uses f347e4d1 | I/erratum/*, RUNBOOK §11, RESULT.identity | The erratum diff is byte-identical to `git diff 2de02975 f347e4d1 -- scripts/v2g/m4_li.py`. The pinned file `/tmp/v2g/prereg/m4/m4_li_pinned.py` has sha f2a2d200 (= CANDIDATE), and the auditor saw that file running at 22:25. The change adds `game_interface` and alters only the RR/Booster *timing* route, which the gate does not use. Dev proof: pinned vs new D interface output is byte-identical (1,966 rows, sha 5254ca18), and the RR / Booster choice is the same on 2,701 / 755 dev requests. `operate.py` is the pinned 5bd76f1b. | MATCH (erratum) |
| ERRATUM prose cell (descriptive): a joint the canonical machine rejects = product failure, on the prose path only | zoo_d_prose/erratum/* | The diff vs the pinned m4_zoo_sdk.py (dbbfdb56) is byte-identical to the receipt diff. The copy's sha is 55765287. The parser branch is unchanged. This matches PREREG §5.8 / §8 (a product failure is success 0, never a void). | MATCH (erratum) |
| S0* deviation (bracket 2.9% > 2%; S0* = upper point 109,375) | CANDIDATE.deviations, readiness timing CSVs | All 9 timing CSVs and stamps match their CANDIDATE sha. UCBs are reproduced exactly. CANDIDATE's p95 is the order statistic x_(1900); with the numpy-linear p95 the bracket is the same (106,250: 88.85 ≤ 91.70; 109,375: 93.38 > 91.70). Width 3,125/106,250 = 2.94%. Choosing the upper point gives the comparator the larger budget. No gate uses S0*. | MATCH (deviation verified) |
| Earlier §11 plumbing notes (episodes file; explicit config) | arena receipts | sha(applied) = CSV 72/72; config_sha256 in every receipt = 3f87c2a0 | MATCH |

## 8. Release decision, recomputed (PREREG §5.8, §8, §9)

1. **R** = FAIL (and not INVALID). Shipped path = **parser**, and G := G_parser. G_prose is descriptive.
2. **Parser-path gates:**
   - A_snake PASS, A_rotorwash PASS, A_booster PASS;
   - G_parser PASS;
   - L PASS (valid);
   - I PASS.
3. Nothing is INVALID or PENDING among the gates, and nothing FAILs → **RELEASE V2 on the parser path**. The reader
   moves to V2.1.

| Item | Receipt path | Audit value | Receipt value | Result |
|---|---|---|---|---|
| release.path / R | RESULT.json | parser / FAIL | parser / FAIL | MATCH |
| release.gates | RESULT.json | A×3, G, L, I all PASS | same | MATCH |
| release.decision | RESULT.json | RELEASE | RELEASE | MATCH |

## 9. Process notes (no recomputed number disagrees; for disclosure)

1. **Order of R vs the policy runs.** PREREG §6.1 says R (step 3) runs before the sealed policy runs (step 4). In fact:
   - the D parser cell and Arena S/B started at 22:08;
   - the R translation job was dispatched at 22:10:11 (config sha e5c4face, frozen commit a20f9945, adapter
     1b70b944);
   - R verdicts were committed at 22:24, after the D receipts (22:23).

   RUNBOOK §7 had planned R and the policy runs in parallel. R uses only the frozen reader's outputs and `check.py`,
   so no policy outcome can enter it, and the path rule is unaffected. **Resolved:** a dated RUNBOOK §11 line was
   added (23:4x).
2. **Erratum text vs stamps.** The m4_li erratum says the pinned sha is "recorded in each stamp", but the four
   `stamp.json` files do not carry it. The provenance is established otherwise: the auditor saw the process run, the
   file sha matches, and the sha appears in RESULT.identity and PROGRESS.log. **Resolved:** RUNBOOK §11 now carries
   the corrected wording, and the sidecar `L/harness_sha256.json` maps f2a2d200 to L ×4 + I/zoo_d and 04b71068 to
   I/arena.
3. **PREREG §13 label.** It calls 0.096 / 0.077 the "V1 RR eval mean Y", but those are the records' `score01` means.
   The gate metric raw = K3-RR2.1 has means 0.358 / 0.344. Gate A uses raw, as §3 requires.
4. **Gaps in RESULT.json.** It omits these PREREG descriptive items:
   - comparator-arm C8 statistics;
   - Δ+ per stratum;
   - Zoo-Unseen-C;
   - the C8.2 decision-level line (share of drawn joints in A*(s)).

   §2 and §6 supply the first three. The A* line needs the exact oracle and cannot be computed from receipts.
5. **What the auditor could not replay.**
   - D episodes could not be re-played, because the sealed task files are off-limits; internal consistency was
     checked instead (§2).
   - The Booster L/I population (n = 1,506 < 2,000, "all if fewer") cannot be recounted, because
     `requests_<game>.jsonl.gz` is not among the receipts.
   - `L_descriptive_sdk_route/` is empty.
6. **C8.3 wording binds the release text.**
   - NS is shown on the full set, but 48% of D decisions are high-coverage and the median |R(M)| is 922.5.
   - On the low-coverage subset NS is **not** shown: θ̂ 0.730, family lower bound 0.485, domain lower bound 0.398.
   - The full-set NS must not be presented as north-star attainment. "Learning generalizes" is not supported
     (G+ not shown, Δ̂+ = −0.0033).

## 10. Pending items

None. The prose cell and the leak check landed and are audited in §11.

## 11. Addendum (descriptive; commit ee926c88; RESULT_ADDENDUM.json sha cf618f3f)

| Item | Receipt path | Audit value | Receipt value | Result |
|---|---|---|---|---|
| Leak signal (PREREG §5.6 R2.5). Inputs: D s_f (48) vs Zoo-Dev-L s_f (44 families, 11 domains, 88 machines, 0 invalid, CRN salt v2g-eval-ldev-v0) | zoo_devl/rows.csv, zoo_d/rows.csv | θ̂_D 0.854167, θ̂_DevL 0.885653 | 0.854167, 0.885653 | MATCH |
| Welch diff / se / df / lower 97.5% bound / flag | zoo_devl/leak_check.json, RESULT_ADDENDUM | −0.031487 / 0.062466 / 89.56 / −0.155595 / **no flag** | same | MATCH |
| Zoo-Dev-L episode consistency; MANIFEST; run.json code shas = pins | zoo_devl/ | 1,408/1,408; ok; 4/4 | — | MATCH |
| Prose cell validity and admission (candidate, reader programs, canonical env) | zoo_d_prose/rows.csv | 96 machines, 0 invalid; fid/domain/machines = addendum; outcomes: success 721, crash 357, product_fail 323 (= 244 operate errors + 47 env-rejected joints + 32 missing programs = 2 machines × 16), timeout 135 | — | MATCH |
| G_prose θ̂ / L_fam / L_dom / LODO min (rule form: FAIL; descriptive because R FAILED) | zoo_d_prose/rows.csv | 0.469401 / 0.330009 / 0.311629 / 0.434028 | 0.469401 / 0.330009 / 0.311629 / 0.434028, pass false | MATCH |
| Paired prose − parser per family: mean / sd / lower 97.5% | zoo_d_prose + zoo_d | −0.384766 / 0.455881 / −0.517140 | −0.384766 / 0.455881 / −0.517140 | MATCH |
| Prose episode consistency; MANIFEST | zoo_d_prose/ | 1,536/1,536; ok | — | MATCH |
| Comparator C8 (search_only): exhausted / high-coverage | zoo_d/decisions | 0.249995 / 0.480421 | 0.249995 / 0.480421 | MATCH |
| Δ+ per stratum (booster_like / mixed / rr_like / snake_like) | zoo_d/rows.csv | −0.0026 / +0.0052 / −0.0130 / −0.0026 | same | MATCH |
| Zoo-Unseen-C: θ̂ cand / family lower / domain lower; θ̂ search_only; Δ+ / family lower | zoo_c/ | 0.892578 / 0.736373 / 0.558950; 0.880859; +0.011719 / −0.013259 | same | MATCH |
| Prose ERRATUM proof: parser path unchanged on a dev subset | zoo_d_prose/erratum/proof_parser_path_identical.json | not re-run by the auditor (dev runner); the receipt claims 786 decisions, rows and reach byte-identical | — | (receipt only) |

**Provenance note.** `zoo_d_prose/run.json` → `code_sha256` lists the repo m4_zoo_sdk.py (dbbfdb56). The copy hashes
`ROOT / scripts/...`, so it records the repo file, not the erratum copy that actually ran (55765287). The copy's sha
is recorded in `zoo_d_prose/erratum/sha256.txt`. This is descriptive and changes no number.

**Reading.**
- On the prose path the frozen S-v1 reader loses 0.385 of success per family against the parser path.
- 323/1,536 episodes are product failures: wrong or missing programs.
- This is consistent with R = 23/48. The reader moving to V2.1 is the right call.
- No leak flag was raised, so G_parser stands as final.

Verdict: MATCH
