# Nagi-ENORMOUS Burst: release report

Released 27 Sep 2026. Landing page: <https://nagisanzenin.github.io/nagi/burst/>. Preregistration:
[PREREG.md](PREREG.md). Receipts: [receipts/](receipts/), with sha256 below.

**Decision: RELEASE.** The frozen rule `RELEASE = SELECT ∈ {A, B} ∧ V_rt ∧ R-RT` (PREREG §8.1) holds. SELECT = **A**
(canonical order), and every gate of variant A passed: V_off, G1-SDK, G2, G3 and LAT. Variant B failed G1-B and its
latency gate; the frozen selection rule (PREREG §5) therefore picked A, which it does whenever A passes. In real time,
V_rt, R-RT and C1 passed. C2 passed for Booster Gauntlet only.

Headline: on fresh seed indices 10–33 (n = 24 per game, 3 games), Nagi-ENORMOUS Burst survived longer than Jev 1.13.0
in **Θ = 0.674 [0.577, 0.770]** of head-to-heads (95% t CI, df 23). The preregistered superiority test C1 passed
(lower bound > 0.50, sign-flip p = 0.0018). Per game, only Booster Gauntlet is individually significant (Holm).
Snake Rush and Rotorwash-Ramp are **not** individually significant.

## Names

| On the page | In the receipts | What it is |
|---|---|---|
| Nagi-ENORMOUS Burst (release) | `enormous_burst/chord`, label "ENORMOUS Burst" | The step-417 weights served with the Burst readout in the environment's declared control order (variant A) |
| Burst (Board 1 player) | `t_dual/chord`, "T-dual Burst" | The same weights and byte-identical prompts, in the Board 1 v2 run |
| K-call, same weights | `t_dual/kcall`, "T-dual K-call" | The same weights, one forward pass per control |
| Nagi-ENORMOUS (released) | `enormous_old/kcall`, "ENORMOUS-old" | The public adapter `nagisanzeninz/Nagi-ENORMOUS` at revision `2e03ec38…` (step 500); adapter sha256 `b8d307527a04…`, equal to `weights_sha256` in results.json |
| Jev 1.13.0 | `jev/vendor_single` | Commercial API, one request with all controls |

"Chord" was the research name of Burst until 27 Sep 2026; "T-dual" is the research name of the step-417 weights.

## 1. Offline gates (receipt: `selection.json`)

Both variants were measured in one job; each bound is one-sided 97.5% (Bonferroni over the two variants). The decisional
bound is the less favourable of a cluster bootstrap and a t bound (G = number of clusters).

| Gate | Rule | Variant A | Variant B |
|---|---|---|---|
| V_off (validity) | all checks true | PASS | PASS |
| G1-SDK: same served answer for all client orders, 500 states | 500/500 on CPU and in the job | 500/500, PASS | 500/500, PASS |
| φ_A: model-level flips when the order rotates, 500 states (disclosure only) | reported | 0.248 [0.175, 0.322] (two-stage 95% CI) | – |
| G1-B: order residual of B, K = 3, 500 states (G = 13) | upper bound ≤ 0.10 | – | 0.090, upper 0.132, **FAIL** |
| G2: MA1(V) − MA1(K-call), 780 states (G = 13) | lower bound > −0.06 | −0.005, lower −0.045, PASS | −0.008, lower −0.045, PASS |
| G3: Δ_U, share of "up" collective commands vs K-call, 200 Rotorwash-Ramp states (G = 20) | upper bound ≤ 0.15 | −0.015, upper 0.002, PASS | −0.020, upper −0.000, PASS |
| LAT: p50 at 3 streams, H100, filler prompts; Snake / Rotorwash-Ramp / Booster (ms) | upper bound ≤ 300 on every game | 216 / 248 / 196; upper 219 / 269 / 264; PASS | 216 / 774 / 1039; upper 219 / 788 / 1063; **FAIL** |
| B_margin: MA1(B) − MA1(A) | lower bound > −0.02 | – | −0.003, lower −0.028, false |

MA1: A 0.479, B 0.477, K-call 0.485. U (share of "up"): A 0.005, B 0.000, K-call 0.020. K = 4 order flips of A
(descriptive, 200 states): 0.235. LAT at 1 stream (descriptive): A 90 / 148 / 151 ms.

Selection (`selection.json → selection`): A_pass = true, B_pass = false, B_margin = false, **SELECT = A**. The file
was committed on 27 Sep 2026 at 18:13 +07, before any real-time outcome was opened (PREREG §5).

## 2. Real-time confirmation (receipt: `release_decision.json`)

Design (PREREG §6.1): Arena v3 real-time protocol, 4 Hz (250 ms ticks), 60 s cap, 3 streams per H100 for Burst,
3 client-side streams for Jev. Burst played seed indices 0–33 of each game; Jev played the fresh indices 10–33.

| Test | Rule | Result | Verdict |
|---|---|---|---|
| V_rt: replay exact, cells valid, seeds 0–9 equal Board 1 (30 compared), serving path identical across shards, Jev version matches Board 1 | all true | replay 174/174 exact; 0 void rounds in every cell | PASS |
| R-RT (release gate): H0 Θ ≤ 0.35 | t lower 97.5% bound > 0.35 | Θ = 0.674, lower 0.577, upper 0.770 (SE 0.046, t_23) | PASS |
| C1 (claim): H0 Θ ≤ 0.50 | lower bound > 0.50 and sign-flip p ≤ 0.025 | lower 0.577, sign-flip p = 0.0018 | PASS |
| C2 Booster Gauntlet | Holm, α 0.0083 | W = 0.979, lower 0.925, p = 0.00001 | PASS |
| C2 Rotorwash-Ramp | Holm, α 0.0125 | W = 0.583, lower 0.337, p = 0.270 | not significant |
| C2 Snake Rush | Holm, α 0.025 | W = 0.458, lower 0.253, p = 0.736 | not significant |

W and Θ count a tie as ½. The sign-flip p-values use 100,000 Monte Carlo flips; the Booster value is the Monte Carlo
floor. `claims_allowed`: offline non-inferiority, the real-time estimate vs Jev, "outperforms Jev in real-time
head-to-heads", and a per-game claim for Booster Gauntlet only.

### Estimates on fresh indices 10–33 (no hypothesis; PREREG §6.4)

| Game | RMST ≤ 60 s, Burst | RMST ≤ 60 s, Jev | Median level at failure, Burst / Jev | Censored |
|---|---|---|---|---|
| Snake Rush | 9.3 s [7.1, 11.5] | 10.7 s [7.9, 13.4] | 1 / 1 | 0 / 0 |
| Rotorwash-Ramp | 23.1 s [20.7, 25.5] | 21.5 s [17.3, 25.7] | 3 / 2 | 0 / 0 |
| Booster Gauntlet | 22.0 s (every round at the 22 s wall; no interval) | 12.3 s [10.6, 13.9] | 3 / 2 | 0 / 0 |

### In-play latency and freshness (receipt: `results.json`, all requests pooled per player and game)

| Player | Snake Rush | Rotorwash-Ramp | Booster Gauntlet | Rounds |
|---|---|---|---|---|
| Nagi-ENORMOUS Burst, p50 / fresh share | 249 ms / 0.64 | 264 ms / 0.62 | 290 ms / 0.61 | indices 0–33 (102) |
| Jev, p50 / fresh share | 173 ms / 0.90 | 209 ms / 0.79 | 173 ms / 0.92 | Board 1 indices 0–9 plus release indices 10–33 |

Stale replies and expiry resets: 0 for both players on every game. p90 and p99 in play are not in the published
receipts.

### Screen vs the Board 1 v2 players on indices 0–9 (descriptive, never a claim; PREREG §6.5)

"Screen, n = 10, not confirmatory." T-dual Burst was selected as the Board 1 champion on these very indices, so these
numbers carry selection optimism (worst case about 0.076 in win-rate units).

| Burst (release) vs | Θ [95% t CI] | sign-flip p |
|---|---|---|
| Nagi-ENORMOUS (released) | 0.783 [0.624, 0.943] | 0.0013 |
| Burst, Board 1 player (same prompts: a test-retest) | 0.433 [0.263, 0.604] | 0.894 |
| K-call, same weights | 0.550 [0.332, 0.768] | 0.323 |
| SemIf-4B | 0.950 [0.870, 1.030] | 0.00005 |
| ENORMOUS-CL | 0.633 [0.457, 0.809] | 0.069 |
| Jev | 0.867 [0.700, 1.033] | 0.00005 |

The t intervals are not clipped to [0, 1]. The full per-seed survival times, pairwise rates and survival curves are in
[receipts/BURST_REPORT.md](receipts/BURST_REPORT.md) and [receipts/results.json](receipts/results.json).

## 3. Mandatory disclosures (PREREG §8.3)

1. **Order sensitivity.** The first prototype failed its preregistered order gate (Chord P1 REJECT-ORDER, 0.260
   [0.184, 0.343]); that verdict stays failed. For the release (variant A), the SDK renders the controls in the
   environment's declared order, so the served answer does not depend on the order in which a client lists them. The
   model itself changes its answer on 0.248 [0.175, 0.322] of states when the order is rotated. Clients that bypass
   the SDK must present the controls in the canonical order; other orders are unevaluated, and every quality number
   holds for the canonical order only.
2. **Lockstep deficit.** In the research phase, with time frozen and compute matched against K-call's three passes,
   Burst had a Rotorwash score R of −0.101 [−0.165, −0.043], survived 43.1 s less, and crashed into the ceiling in 24/24
   rounds. Its advantage is latency.
3. **Training provenance.** A preregistered pause at update 125 of 417 was overridden by the owner and the run
   continued. Retention against the released Nagi-ENORMOUS: language and policy checks passed, Arena retention was
   inconclusive, and the public benchmark suite was not re-run. Burst's weights were trained on control tasks similar
   to all three games: level O2 (in-domain) on every game, and no game reaches O3 (Arena v3 PROTOCOL §A1.8, audit of
   the same step-417 weights). The release report's in-domain table reads "unaudited" only because that job did not
   load the audit file.
4. **Measurement limits.** Booster Gauntlet has a 22.0 s wall: Burst ended every fresh round at exactly 22.0 s, so its
   Booster "wins" are rounds where Jev failed first, and ties compress the rates among strong players. On Snake Rush
   every model is near the floor; in Board 1 the Burst player's median (10 s) was below the naive reference bot
   (13.75 s).
5. **Real-time conditions.** Real time only, on H100 with merged bf16 weights and fused kernels; no claim for other
   hardware. Jev is a vendor API on unknown hardware, reached over the network from a Modal CPU container; its latency
   includes the network.
6. **Ceiling pathology flag (PREREG §3.3).** 12 of the 24 fresh-seed Rotorwash-Ramp rounds of Burst ended on the cave
   ceiling (collapse 9, terrain 3), which meets the ≥ 50% disclosure threshold. Source: the `score.cause` field of the
   round records (not in the public receipts). G3 passed, but it detects only gross decision-level bias.

Further notes from the run:
- **Jev continuation.** The first Jev job (`br_jev_summary.json`) stopped at its per-job cost guard before
  Rotorwash-Ramp indices 25–33. A second job (`br_jev_c2_summary.json`) played those 9 rounds. Jev's latency probe at
  3 streams gave p50 172 ms in the first job and 297 ms in the second. Both jobs replayed exactly (63/63 and 9/9).
- **Jev is not deterministic.** Jev's answer fingerprint on 8 fixed requests changed between calls, including three
  back-to-back calls from one client, so a fingerprint change does not mean a vendor change. The frozen V_rt check
  compares the vendor version string, which was `jev-1.13.0` in every job, as in Board 1.

## 4. Clips

One clip per game, 1080×1920, 30 fps, rendered from verified replays: Nagi-ENORMOUS Burst's release-run round next
to Jev's and SemIf-4B's Board 1 rounds on the same seed (receipt: `render_clips.json`). Seed rule (Arena v3 PROTOCOL
§A1.5, `pick()`): the index of the lower median of Burst's survival times over its non-void rounds (ties: lowest
index); if a shown player has no round there, the next index in order of Burst's survival time, shortest first.
SemIf-4B played only indices 0–9, so:

| Game | Lower-median index (Burst) | Rendered index | Burst survival there |
|---|---|---|---|
| Snake Rush | 16 and 19 (8.5 s) | 3 | 4.5 s, its shortest round on 0–9 |
| Rotorwash-Ramp | 31 (23.754 s) | 4 | 12.892 s, its shortest round on 0–9 |
| Booster Gauntlet | 0 (all rounds 22.0 s) | 0 | 22.0 s |

The clips therefore show Burst's weaker rounds. Every frame, sampled at 1 fps and read by OCR, shows the label
"ENORMOUS Burst" and never "Chord" or "T-dual".

## 5. What is and is not public

Public: this report, the preregistration, the receipts below, the per-round survival times (in results.json and in
the page's data.json), the SDK (tag `v0.6.0`) and the model (`nagisanzeninz/Nagi-ENORMOUS-Burst`). Not public: the
raw round records (174 rounds of the release run with every decision), the offline gate inputs, and the Arena v3
engine, which lives in the research repository. The sha256 values of the gate inputs are listed in `selection.json →
inputs`.

## 6. Receipts

| File | sha256 | What it is |
|---|---|---|
| [selection.json](receipts/selection.json) | `f569573860e1746a9d2935bad396187d3862e28d0334fb5f0aea4f92c4bb0ae8` | Offline gates for both variants and the variant selection, committed before any real-time outcome was opened |
| [release_decision.json](receipts/release_decision.json) | `e820a29e6596d8dee6d7919bc2d420933fdb6cff9977eb254e81a5da607a47d9` | V_rt, Θ, R-RT, C1, C2, estimates, screen, allowed claims |
| [results.json](receipts/results.json) | `cb4875716db62396419e2675aa6f72183140ce1984869f0edfb2e351196407e4` | Per player and game: survival, latency, freshness; per-round out order for indices 0–33 |
| [replay.json](receipts/replay.json) | `17f1b3b8f421d49eedcbcc8e42c404f1037b4760632820549ba30ee977a4ef32` | Replay verification: 174/174 exact |
| [br_jev_summary.json](receipts/br_jev_summary.json) | `855c10032eb69dd95188fe50876124dfe5e039997609e311886b0facf455744b` | Jev job 1: version, fingerprint, latency probe, replay, stop reason |
| [br_jev_c2_summary.json](receipts/br_jev_c2_summary.json) | `a48e5184ea3a7f480c64cf362eff40621c566e02f535ae97bcc1dbaf77ab8e48` | Jev continuation job (Rotorwash-Ramp 25–33) |
| [BURST_REPORT.md](receipts/BURST_REPORT.md) | `711bae79e77ebeb55b100487be7ec7cd4d1a4115af13f227d58c42360701550d` | The analysis job's own report (research labels) |
| [render_clips.json](receipts/render_clips.json) | `3a04f77b18d178f3c74053c276005a7d0811fa2586a5490471154e8dbb466a8d` | Clip seeds, extracted from the report job's status.json (sha256 `1e721a07e0d7…`, not published because it holds internal output paths) |

Every file except render_clips.json is a byte-identical copy of the release receipt. The analysis job also re-emitted
selection.json (sha256 `4fc7101433a8…`); it differs from the committed file only in the last digits of four t
statistics (floating-point noise), and in all four the decisional bound is the bootstrap one, so no bound or verdict
changes.

Every number on the landing page comes from these files, except two: the 12/24 ceiling count (round records, above) and
the Board 1 numbers, which come from the Arena v3 Board 1 report.
