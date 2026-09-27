> **Public copy of the frozen preregistration.** The readout called "chord" in this document is published as "Burst"
> (the player T-dual Burst; machine-readable id `t_dual/chord`). Only private paths were redacted; no rule, number or
> wording was changed.
>
> - Source: `docs/burst_release/PREREG.md` in Nagi's private research repository, frozen at commit `f0d6204`, with
>   Amendment 1 (a pre-data correction) at commit `0c346f5`. The file has not changed since `0c346f5`.
> - sha256 of the unredacted source file: `37b6ba1e662558ed6b1f582eef6dc736c323554f2fbcdabe69eb80e5a08fac38`.
> - Redactions (3): two local paths into the private repository, each replaced by a bracketed description, and one
>   relative link to a private file (`APPROVAL.md`, the owner's authorization record), kept as plain text.
> - Other file names in this document (`docs/…`, `data/…`, `scripts/…`, `multiaction.…`, `arena.v3.…`,
>   `prereg_constants.json`, `selection.json`, RUNLOG, APPROVAL.md) refer to the private research repository and are
>   not published. "PROTOCOL" is the Arena v3 protocol; its public copy is [PROTOCOL.md](PROTOCOL.md). R-numbers (R3.x)
>   and "AGENTS" cite the private research handbook and agent rules.
> - The outcome of this preregistration is reported in [BURST_CONFIRMATION.md](BURST_CONFIRMATION.md).

# Nagi ENORMOUS Burst: preregistration of the fast-path release (P1 offline gates, variant selection, P2 realtime)

Status: **FROZEN when this file and `prereg_constants.json` are committed on branch `burst-prereg`** (frozen `f0d6204`; Amendment 1, a pre-data correction of Booster's canonical order, is at the end). The commit hash
goes into the Burst RUNLOG before the first GPU dispatch. A later change is a dated amendment at the end of this file.
It never applies to data already opened. `prereg_constants.json` is the machine-readable copy. **If the two disagree,
this file decides, and the disagreement is recorded as an amendment.**
Authorization: APPROVAL.md (cap $14.00 / stop $12.00, ≤ 6 H100, Jev $1.00). Written CPU-only, $0.

**Where this goes and why.** This is the closed-loop rung of `docs/VISION.vi.md`: a multi-control machine decided at
System One latency. Chord P1 showed two things:
- One forward pass can decide K controls at the same single-question quality as K calls: MA1 +0.000 [−0.040, +0.040].
- Realtime is where that speed pays: Board 1 v2 put T-dual chord first on its screen.

Chord P1 also REJECTED chord as the SDK default, because the answer flips when the control order changes (26%). This
prereg decides whether the same weights can be **released** as "Nagi ENORMOUS Burst", and under which claims. It
decides this with gates frozen before any Burst data. **The P1 REJECT-ORDER verdict stays failed and is never passed
retroactively (AGENTS.md).**

## 0. Pre-flight record (AGENTS 4c; handbook README)

| Card | How it is applied here |
|---|---|
| R3.1–R3.4 | Every gate and claim below has an estimand line: metric, population, unit, contrast sign. Arms are paired on identical states and seeds, serving path and hardware class. |
| R3.5, R3.6 | Small n / few clusters: each clustered CI has a t_{G−1} cross-check on cluster means. Win-rate claims need t AND sign-flip to agree. G is printed. |
| R3.7 | Per variant, the offline gates are an intersection–union test (no adjustment). Bonferroni over the 2 variants (the rule may release either). P2 uses a fixed sequence then Holm. Everything else is labelled descriptive. |
| R3.8, R3.12 | Margins δ are fixed here before any Burst data, each with a feasibility (power) check. The known prior results that touch a gate are disclosed where they apply (§3.2). |
| R3.11 | MDEs are derived from the Board 1 v2 paired variances (§7; script output reproduced there). |
| R3.13, R3.14, R3.23 | One serving path and hardware class per comparison. Rotorwash-Ramp is played and verified on Linux x86_64 only. Jev and Board 1 records are reused only through the registry/replay gates. |
| R3.17 | Fail closed: void rounds, renderer or parity mismatches make a gate PENDING. They never make it PASS. |
| R3.18 | Every threshold is set against the metric's SE, on a paired contrast with the named comparator and resampling unit. |
| R3.26 | Offline MA is a diagnostic gate and never ranks products. |
| R3.32 | Products are ranked realtime only. Lockstep is not run. P1's lockstep chord deficit is disclosed (§8.3). |

Math re-derived for this file:
- the order-invariance algebra (§3.1);
- the NI power / feasibility of δ (§3.2);
- the design bound on win-rate variance (§7);
- the MDEs, computed with noncentral t (§7);
- the selection carry-over bound (§6.5).

Inputs read:
- `docs/chord/P1_PREREG.md` (Amendments 1–8) and `P1_REPORT.md`;
- `docs/arena_v3/PROTOCOL.md` §1.1, §2.3–2.5 and §A1;
- `FAIL_FIRST_BRIEF.md` Amendments 1–3;
- `docs/experimental_rl/WIDE_REASONING.md` §B;
- the Board 1 v2 `player_summary.json` records (§2);
- the burst-release code agent's pre-flight notes of 2026-09-27 ~17:15 (latency model and invariance algebra). Those
  notes are cited as [notes]; every number taken from them is re-checked or labelled here.

## 1. Candidate and the two variants

| Item | Frozen definition |
|---|---|
| Weights | T-dual step 417: LoRA on Qwen3.8-27B, adapter sha256 `b137a98649457f1dab6c84074255a34a9785bdba1c63df579ab5c0b0a9c3caed` ([private research repo: T-dual training-run record of the step-417 checkpoint]), served merged bf16 with fused kernels on H100, with request micro-batching (PROTOCOL §1.1.9). The serving path is identical for every arm that is scored against another. |
| Canonical control order | MA states: ascending `control_index` (the CONTROLS line order, the P1 tie rule's order). Arena v3 games: the game's declared control order. That is lexicographic qid order in all 3 suite games [notes, M]: Snake `(move,)` K=1; Rotorwash-Ramp `(collective, cyclic, winch)` K=3; Booster Gauntlet `(fins, gimbal, legs, throttle)` K=4. |
| SDK canonicalization (both variants) | The SDK sorts the client's controls into canonical order before rendering. The prompt bytes are then a function of the control **set** only. |
| **Variant A** | One chord forward on the canonical-order prompt. Per-slot argmax, canonical option tie rule (first max in canonical option order). Its prompts equal the Board 1 v2 `t_dual/chord` prompts byte for byte [notes, M]; the job re-asserts this (§4). |
| **Variant B** | Permutation-averaged readout over the **cyclic orbit** anchored at the canonical order: the M = K orders ρ^0, ρ^1, …, ρ^{K−1}, where ρ rotates the slot order by one. M = 1 for Snake, 3 for Rotorwash-Ramp and the MA sets, 4 for Booster. The M prompts are batched in the fixed row order ρ^0..ρ^{K−1}. For each control k, its per-option log-softmax is taken from every order and averaged in that fixed order. Averaging logits gives the same argmax, because per (order, control) they differ from log-softmax by a constant. Then per-control argmax with the canonical option tie rule. K ≥ 5 is **not supported** (never gated): the SDK must refuse B for K ≥ 5 or fall back to A, and say so in the release notes. |
| Why cyclic, not all K! orders | For K = 4, K! = 24 rows per decision × 3 streams is far over the latency budget. Even M = K is predicted at 0.5–1.1 s p50 at 3 streams [notes, a linear fit a + c·rows to the Board 1 v2 probe; E]. The cyclic orbit is the smallest set that puts each control in each slot exactly once (a Latin square, which balances first-order position effects). |

## 2. Frozen inputs

| Input | Pin |
|---|---|
| MA eval rows (P1 v2) | `data/chord_p1_final_v2/eval_ma_chord.jsonl.gz` sha256 `29ca35b40a658a6c4c03fd570897b5be79007504d1f4243a6f766ce5ca516ada`: 1,776 rows, 13 genres, every state K = 3, presented in a per-row uniformly random slot order (checked: the 6 orders occur 283–326 times each). MA1 = the 780 `ma1` decision instances (60 × 13 genres), as P1 §1. |
| P1 order set | `data/chord_p1_final_v2/eval_ma_chord_perm.jsonl.gz` sha256 `ff9ef16b530e6a02f8453735aa464640f1e56783bb28132b34465bd863e7eeb4`: the same 500 states with the slot order rotated by one (`#rot1`), 13 genres, K = 3. |
| Filler (latency and G3) | `docs/arena_v3/filler/` MANIFEST: Snake rush-2 `1468fcc5…`, Rotorwash-Ramp `5dc5f65f690f80c0ff3d5d6c5c2c7b7b9e32b51dfeb012b6b4d30e7f69cb1d75`, Booster g1.1 `dd3f3673e2e05ea080c35a967a1dcf6bacb1b55ed6fda177d7eb2cde0495d713`. Each list: 200 prompts from 20 dev seeds, built by `arena.v3.filler.build`. |
| Board 1 v2 records (seeds 0–9) | [private research repo: Board 1 v2 run records] @ `699a91a`, `player_summary.json` sha256: enormous_old/kcall `61bb139a…`, t_dual/chord `292f8b72…`, t_dual/kcall `74ec0153…`, semif_4b/kcall `017d5b96…`, enormous_cl/kcall `4c4dc272…`, jev/vendor_single `58c59005…`. All 180 rounds: 0 void. |
| Ladder anchors (1-tick delay) | FAIL_FIRST_BRIEF Amendment 3. Median T_fail naive / heuristic / planner: Snake Rush 13.75 / 27.75 / 49.88 s; Booster 12.53 / 24.63 / 43.83 s; Rotorwash-Ramp 11.14 / 24.49 / 45.83 s. |
| P1 references | `docs/chord/p1_offline_results.json` sha256 `ad2c0c74…` (cross-check only, never decisional); P1_REPORT §1, §3, §9. |
| Analysis code | `multiaction.eval_ma` (`paired`, `cluster_boot`, `holm`); `scripts/arena_v3_report.py` (win rate, RMST, ladder position), both at the commit that freezes this file. New gate code (orbit readout, G1–G3, LAT, selection) is committed and CPU-tested before dispatch. Its commit is recorded in the RUNLOG. A diff against it at analysis time voids the decision unless an amendment explains it (R3.8). |

Bootstrap conventions: B = 10,000 with seed 20260925 for MA and order statistics (as in P1); B = 2,000 with seed
20260927 for latency.

## 3. Offline gates (one gates job, both variants; fail-fast order G1 → LAT → G2 → G3)

The **comparator** is T-dual K-call as served by the SDK: canonical control order in each per-control prompt,
re-scored **in the same job on the same serving path** (R3.3, R3.14). P1's K-call predictions came from the training
worker's unmerged, fallback-kernel path, so they are a cross-check only. Every per-state, per-order prediction
(ids, per-option log-probs, joint action) is saved next to the receipt (R3.30).

### 3.1 G1 ORDER

**Algebra (exact; this is why G1 is split).** Write a presented order as a map σ from slot positions to controls.
A readout over a set of relative orders R uses the prompts σ∘ρ, ρ ∈ R, and averages per control.
1. If R = S_K (all K! orders), then {σ∘ρ} = S_K for every σ. The answer does not depend on σ at all: exact invariance,
   given deterministic per-order forwards summed in an order indexed by the absolute order.
2. If R is a subgroup H of S_K, then σ∘h∘H = σ∘H for every h ∈ H. The answer is exactly invariant to the perturbations
   σ → σ∘h. **The P1 perturbation is a rotation by one slot, σ' = σ∘τ with τ ∈ C_K.** So B-cyclic has flip ≡ 0 on the
   P1 rotation set **by construction**. The P1 estimand cannot falsify B.
3. Residual when M < K!. Model the per-order log-probs as z^π = z* + u_π, where z* is the mean over all K! orders and
   u_π is exchangeable order noise (variance v, pairwise correlation ρ_u).
   - Two disjoint order sets of size M differ by noise of variance 2v(1 − ρ_u)/M. A single order vs its rotation
     differs by 2v(1 − ρ_u).
   - So the perturbation of every top-2 margin shrinks by a factor of 1/√M. The flip rate shrinks by roughly the same
     factor while flips are rare (margin density near 0).
   - Prior: φ_B ≈ 0.26/√3 ≈ 0.15 for K = 3 [E]; less reduction if ρ_u varies across order pairs.
   - For R a uniformly random M-subset, E_R[z̄] = z*: invariant **in expectation only**. Every fixed R with M < K! keeps a
     residual, and it is exactly 0 only at M = K! (the finite-population correction 1 − M/K! = 0).
4. **Deployed path.** With SDK canonicalization, the prompt bytes depend only on the control set. So for both variants
   the deployed answer is exactly invariant to the client's order. This is a software property, tested exactly
   (G1-SDK). It is not a statistical claim about the model.

| Gate | Estimand, population, unit | Rule |
|---|---|---|
| **G1-SDK** (A and B) | For each of the 500 frozen P1 states, feed the SDK the state in each of the 6 presented orders. Check that the rendered token ids are identical across all 6 (CPU), and that the served joint action is identical for the presented and the `#rot1` order (in the job). Unit: state. | PASS iff **500/500** states are identical on both checks. Any mismatch is a FAIL of the SDK path (a bug, not noise). |
| **A model-level disclosure** (not a gate) | φ_A = P_s[joint action on the presented order ≠ joint action on its `#rot1`] over the 500 states, **without** canonicalization. This is the P1 estimand, re-measured on the serving path. Two-stage genre→state bootstrap 95% CI, G = 13. | Reported and disclosed in the release notes (§8.3). P1 measured 0.260 [0.184, 0.343]. **This is the P1 REJECT-ORDER quantity. It stays failed and A does not claim to pass it.** |
| **G1-B residual** (B only) | φ_B = P_s[B-readout over the even coset C_3∘σ_c ≠ B-readout over the odd coset C_3∘(σ_c∘r)] on the same 500 frozen states. Here σ_c is the canonical order and r the reversal. The two cosets are disjoint and together are all of S_3. The B readout on the odd coset is exactly what a client presenting an odd permutation without canonicalization would get. Unit: state, clustered by genre (G = 13). The P1 `#rot1` flip for B is also computed, as an implementation check: it must be 0/500. | PASS iff the **one-sided 97.5% upper bound ≤ 0.10**. The bound is the larger of (a) the two-stage genre→state bootstrap 97.5th percentile and (b) the t_{12} bound on the 13 genre means. `#rot1` must be 0/500, else FAIL (implementation). |
| B at K = 4 (descriptive) | The same coset contrast on the 200 Booster filler states: C_4∘σ_c vs C_4∘(σ_c∘(0 1)) (a transposition, outside C_4). | Reported only. The frozen offline sets contain no K = 4 state, so **the K = 4 residual is not gated** (disclosed). |

Most likely outcome [E]: G1-SDK passes for both variants. G1-B fails, because φ_B near 0.15 gives an upper bound above
0.10. Scaling P1's SE (0.040 at φ = 0.26) binomially gives SE ≈ 0.02 at φ ≈ 0.05, so B passes only if
φ̂_B ≲ 0.05–0.06.

### 3.2 G2 multi-control quality: non-inferiority to K-call of the same weights

- **Estimand:** Δ_V = MA1(V) − MA1(K-call), V ∈ {A, B}. MA1 is the mean `acceptable` over the 780 frozen MA1
  decision instances (13 genres × 60).
  - A and K-call are rendered in canonical order. B uses its orbit anchored at canonical.
  - Population: the P1 v2 MA dev states (11 trained and 2 held-out genres, pooled as in P1).
- **Unit:** instance, clustered in genre (G = 13).
- **Statistic:** the paired difference.
  - (a) Two-stage cluster bootstrap (`eval_ma.paired`: genres, then instances within genre), B = 10,000, seed
    20260925. The decisional bound is its 2.5th percentile.
  - (b) A t_{12} one-sided 97.5% lower bound on the 13 genre-mean differences.
  - The decisional bound is L = min(a, b).
  - Within-genre resampling (the fixed-list SE model, R3.18) is reported, not decisional.
- **Rule:** PASS iff **L > −δ, δ = 0.06**. This is one-sided 97.5% per variant = one-sided 95% family-wise over the two
  variants (Bonferroni).
- **Why δ = 0.06:**
  - **SE:** P1's paired chord − K-call CI on MA1 was ±0.040 (half-width), so SE ≈ 0.0204.
  - **Feasibility:** power at Δ = 0 is Φ(δ/SE − z_0.975). That gives 0.84 at δ = 0.06, 0.69 at δ = 0.05, and 0.16 at
    P1's δ = 0.02. P1's A1 failed only because 0.02 is below its own noise (A1 FAIL at Δ̂ = +0.000).
  - **Substance:** T-dual's MA1 gain over ENORMOUS-old is +0.160 [+0.054, +0.272]. δ = 0.06 keeps ≥ 62.5% of it
    (a fraction-retained NI criterion). It is 47 of the 780 instances.
- **Prior knowledge, disclosed.** P1 measured chord − K-call = +0.000 [−0.040, +0.040] on these weights, with random
  presented orders. G2-A is therefore expected to pass. δ was set from SE and retention, not from that interval, and
  A would also pass at δ = 0.05. G2-A is still a new measurement (canonical-order prompts, serving path), not a
  re-read of P1.
- **Also reported:** MA1 for each arm; MA2, MA2b, MA3 and nregret; trained vs held-out genres; per-genre worst drop
  (R3.18); agreement of A's joint actions with P1's chord predictions on the canonical-order rows (descriptive).

### 3.3 G3 collective / ceiling bias

P1 finding: in lockstep Rotorwash v2, all 24 of T-dual chord's rounds ended on the ceiling, vs 4/24 for K-call on the
same weights (P1_REPORT §4). In Board 1 v2 realtime the ceiling pathology was not chord-specific. Rotorwash-Ramp crash
causes were chord ceiling 3 / collapse 6 / terrain 1 and K-call ceiling 9 / terrain 1 [notes, M]. G3 therefore tests
the readout's **decision-level** up-bias against K-call on identical states.

- **Estimand:** Δ_U(V) = U(V) − U(K-call), where U is the share of decisions whose COLLECTIVE choice is in {up1, up2}.
  It is taken over the 200 frozen Rotorwash-Ramp filler states (chord prompts; dev split, 20 dev seeds). The pairing
  is per state.
- **Unit:** the dev seed (G ≤ 20).
  - Seed provenance is recovered on CPU by re-running the deterministic `arena.v3.filler.build` and matching each
    list entry to its source seed by prompt sha.
  - If any entry cannot be matched, G3 is **PENDING** (fail-closed). It is resolved on CPU from the saved per-state
    predictions, without a GPU re-run.
- **Statistic:** t_{G−1} on the per-seed mean differences; one-sided 97.5% upper bound. A state-level paired bootstrap
  is reported, not decisional.
- **Rule:** PASS iff **upper bound ≤ δ3 = 0.15.**
- **Why 0.15:**
  - It is one extra "up" command per ~7 decisions (≈ 1.75 s at 4 Hz). That is a gross, systematic climb bias of the
    kind that ended all 24 P1 lockstep rounds.
  - Feasibility [E]: with ~20% discordant states and a design effect ≤ 2, SE ≈ 0.04–0.055. Power at Δ_U = 0 is then
    ≈ 0.74–0.95, while δ3 = 0.10 would have power ≈ 0.4–0.65.
  - **G3 detects only gross bias** (disclosed).
- **Descriptive:**
  - the near-ceiling stratum (up-ray ≤ 15 m: 11 of 200 states), with its up-share per arm;
  - the mean signed collective change;
  - U for each arm.
- **Realtime pathology flag (disclosure, never a gate):** if the counted variant ends ≥ 50% of its fresh-seed
  Rotorwash-Ramp rounds on the ceiling, the model card must say so.

### 3.4 LAT realtime latency

- **Estimand:** the p50 of end-to-end decision latency at **3 concurrent streams** on the pinned serving path.
  - End to end means from the observation snapshot to the decision being ready. For B this includes all M orders and
    the averaging.
  - Measured on game g's frozen filler prompts, for each g ∈ {Snake Rush, Rotorwash-Ramp, Booster Gauntlet}.
- **Population:** this serving path on H100 only (R3.13). No claim for other hardware.
- **Procedure:** the PROTOCOL §1.1.9 probe, per variant per game.
  - 5 s warm-up (discarded), then ≥ 30 s with all 3 streams on game g's filler and ≥ 120 requests. Then 30 s of 1
    stream, used for inflation (descriptive).
  - The streams-in-flight assertion (= 3) must hold.
- **Statistic:** a moving-block bootstrap of p50 over each stream's request sequence (blocks of 4 requests = 1 s),
  B = 2,000, seed 20260927. One-sided 97.5% upper bound.
- **Rule:** PASS iff the **upper bound ≤ 300 ms on every game** (IUT). For Snake (K = 1), A and B are the same readout
  and share one measurement.
- **Context:**
  - Board 1 v2 T-dual chord: 3-stream probe p50 236 ms; in-play p50 231 / 239 / 271 ms (Snake / RR / Booster).
  - T-dual K-call: 610 / 757 ms on RR / Booster.
  - The predicted B p50 is 0.5–1.1 s [notes, E], so B is predicted to FAIL.
  - A's Booster in-play p50 is within 30 ms of the limit.

## 4. Validity checks for the offline gates (any failure makes the gates PENDING, never FAIL or PASS)

1. **Renderer parity.** The generalized order renderer reproduces the P1 `input_ids` byte-exactly for all 1,776
   presented-order rows and all 500 `#rot1` rows.
2. **Board 1 byte test.** A's rendered Arena prompts equal the Board 1 v2 `t_dual/chord` prompt sha for the same
   (game, seed, tick) on ≥ 1 recorded round per game.
3. **Serving parity.** The tie-aware logit fixture (|Δlogit| ≤ 2F, PROTOCOL §1.1.9) passes for chord, orbit-batched
   chord and K-call.
4. **Completeness.** MA1 n = 780, the order set n = 500, filler n = 200 per list.
5. **Saved outputs.** Per-row predictions are saved.

A PENDING is fixed on CPU and re-evaluated with the same rules. Rules are never changed to fit.

## 5. Frozen variant-selection rule (mechanical; arena outcomes never enter)

```
A_pass   = V_off ∧ G1-SDK(A) ∧ G2(A) ∧ G3(A) ∧ LAT(A)
B_pass   = V_off ∧ G1-SDK(B) ∧ G1-B ∧ G2(B) ∧ G3(B) ∧ LAT(B)
B_margin = one-sided 97.5% lower bound of MA1(B) − MA1(A) (paired, same L = min(bootstrap, t_12) as G2) > −0.02
SELECT   = B     if B_pass ∧ (¬A_pass ∨ B_margin)
         = A     elif A_pass
         = FAIL  otherwise  → no release
```
- **Reading.** A is the default. B is chosen only if it passes every gate, including latency and the ≤ 10% order
  residual that A cannot claim at the model level, and it is not worse than A on MA1 by more than 2 pp. If A fails, a
  passing B is chosen. If neither passes, the result is FAIL.
- **Timing.**
  - The selection is computed by script from the offline receipt only. It is written to
    `docs/burst_release/selection.json` (receipt sha, gate table, SELECT) and committed **before any realtime outcome
    (survival, win, crash cause) is opened**.
  - Operational monitoring (void counts, job health, $) is allowed.
  - Because the rule is a pure function of offline receipts, the realtime data cannot influence it.
- **Operator plan (code agent, ~17:15 +07).** Realtime runs **only variant A**, sharded for speed; the gates job still
  measures B.
  - **SELECT = A:** A's realtime is the counted P2 run.
  - **SELECT = B:** B's realtime is a **follow-up** on the same seeds 0–33, under its own owner ticket within the cap.
    A's realtime data become descriptive (non-counting). No release until B's P2 passes. B's pairs with Jev on 10–33
    reuse this campaign's Jev records only through the registry reuse gates (R3.14): same Jev version fingerprint,
    protocol and seeds.
  - **SELECT = FAIL:** no release. A's realtime is research data, descriptive only.
- **Multiplicity.** The rule may release either variant, so each offline gate uses α = 0.025 one-sided per variant
  (Bonferroni over 2). Within a variant the gates are all-must-pass (IUT, no adjustment). The selection itself uses no
  arena data, so the P2 tests of the selected variant keep their nominal α.

## 6. P2 realtime confirmation (counted variant V*)

### 6.1 Design

| Item | Frozen |
|---|---|
| Arms | **V\*** (A under the operator plan): seed indices **0–33** × {Snake Rush, Rotorwash-Ramp, Booster Gauntlet}. **Jev** (`jev/vendor_single`, the pinned version and fingerprint of Board 1 v2): indices **10–33** × 3 games. |
| Seeds | Arena v3 `seed_for(game, split, i)` with the same split and keys as Board 1 v2. The analysis asserts that V\*'s record `seed` for indices 0–9 equals the Board 1 v2 row `seed` (e.g. snake index 0 = 1709821297). Seed indices 0–33 are opened by this campaign: dev forever for later Arena looks (R3.8). |
| Protocol | PROTOCOL §1.1 realtime at 4 Hz, 250 ms tick, 60 s cap (62 s runner cap), stale > 1,000 ms rejected, frozen hold rules. 3 streams per H100 with filler, micro-batched serving (§1.1.9). Jev: 3 client-side streams with the same filler rule. Linux x86_64 play and verification (Rotorwash-Ramp is platform-pinned). |
| Validity (V_rt) | Replay 100% exact. Streams asserted = 3 at every submit. Parity fixtures pass. Serving path identical across shards (asserted from each record's `serving_info`). |
| **Void rule** | A live boundary processed > 100 ms late voids the round. It is re-played **once** under a fresh job id with the same seed. If it is void again, that index is void for the cell and is dropped from every contrast with that cell, in both arms. **More than 1 void per 24 fresh rounds (10–33), or more than 1 per 10 on 0–9, per (player, game) cell invalidates the cell.** That is a harness defect: fix it and re-run the whole cell under a new ticket; an invalid cell is never scored. Voids in one arm only are investigated as bias (R3.17). |

### 6.2 Estimands (unit = seed index; the games use distinct seeds, so they are independent by construction)

- **Win indicator.** w_{i,g}(X, Y) = 1 if X fails later than Y on game g, seed index i; ½ for the same failure tick or
  both censored at 60 s; 0 otherwise. Only indices where both have a non-void round count.
- **Per-game rate:** W_g = the mean of w over the valid indices.
- **Composite:** Θ = (W_snake + W_rr + W_booster)/3. This is the PROTOCOL §A1.2 primary: invariant to monotone ramp
  shape.
- **Inference.**
  - With no dropped index, c_i = the mean over games of w_{i,g}, and the tests use t_{n−1} on c_i.
  - Otherwise SE² = Σ_g s_g²/(9 n_g), with Welch–Satterthwaite df.
- **Sign-flip test.** Under H0 of exchangeable players, w → 1 − w independently per (i, g). The test is exact by
  enumeration or Monte Carlo (B = 100,000, seed 20260927).

### 6.3 Tests, α and multiplicity (fixed sequence at one-sided α = 0.025; strong FWER control by closed testing)

| Step | Hypothesis (V\* vs Jev, fresh indices 10–33, n = 24 per game) | Decision | Role |
|---|---|---|---|
| 1 **R-RT** (release gate) | H0: Θ ≤ 0.35 (NI margin δ_w = 0.15) | PASS iff the t lower 97.5% bound > 0.35 | Required for release. A sanity floor: V\* is not clearly worse than the reference vendor in realtime. |
| 2 **C1** (headline claim) | H0: Θ ≤ 0.50; tested only if step 1 passes | PASS iff the t lower 97.5% bound > 0.50 **and** the sign-flip one-sided p ≤ 0.025 (R3.5: if they disagree, the claim is not made) | Allows the claim "survives longer than Jev in most head-to-heads". |
| 3 **C2** (per game) | H0_g: W_g ≤ 0.50 for each g; tested only if C1 passes | Holm over the 3 games at 0.025, t_{n_g−1} and sign-flip both at the Holm level | Allows a per-game "beats Jev" claim. |

Why δ_w = 0.15: at the observed σ_c = 0.233 (T-dual chord vs Jev, Board 1 v2), power at a true tie Θ = 0.5 is 0.86
(noncentral t_23; 0.68 at the independence bound σ = 0.289). δ_w = 0.10 would falsely fail a tie 48% of the time. Θ = 0.35 means losing 65/35 of head-to-heads:
a product clearly worse than the vendor.

### 6.4 Estimates the card may quote (no hypothesis, no multiplicity; each with a 95% t CI over n = 24 indices)

- per game:
  - RMST ≤ 60 s (the mean of min(T_fail, 60));
  - ladder position (piecewise-linear on the §2 anchors, clipped to [0, 1.2]);
  - median level at failure;
  - a Kaplan–Meier curve;
- latency p50 / p90 / p99, fresh-action share, stale and error counts (as served, H100);
- Rotorwash-Ramp crash causes (ceiling share);
- the same for Jev.

These are labelled estimates.

### 6.5 Screen vs the 6 Board 1 v2 players on indices 0–9 (descriptive; never a claim)

- **What is reported.** V\* vs each of enormous_old/kcall, t_dual/chord, t_dual/kcall, semif_4b/kcall,
  enormous_cl/kcall and jev: the composite win rate with a t_9 95% CI and a sign-flip p. It is labelled
  **"screen, n = 10, not confirmatory"**.
- **Selection caveat.** T-dual chord was chosen as the Board 1 champion on these very indices (best of 4), and Burst
  exists because of that screen.
  - Selection carry-over [notes, RD]: a new realization keeps only the player×seed part of the selection bias.
  - Worst case (4 equal entries): optimism ≈ E[max of 4 N(0,1)]·SE = 1.029 × 0.074 = **0.076** in win-rate units at
    n = 10.
- **A vs Board 1 `t_dual/chord`** is the **same player** (byte-identical prompts). It is a test-retest of realtime
  realization noise (expected Θ = 0.5). Its spread estimates Var(e), which is reported.
- **Jev on 0–9 vs Jev on 10–33** are different seeds and not paired.

## 7. MDEs (80% power, one-sided α = 0.025, noncentral t; from the Board 1 v2 paired per-seed rates)

Source: CPU script over the 6 `player_summary.json` above (15 pairs, indices 0–9, 0 voids). Planning σ values for the
per-seed composite c_i:
- 0.233: T-dual chord vs Jev;
- 0.203: pooled over the 15 pairs;
- 0.314: the largest pair;
- 0.289: the independence bound (Var c ≤ (1/9)·Σ_g 1/4). The games use distinct seeds, but a job's shared load can
  couple them, so it is not a hard bound: 0.314 exceeds it within n = 10 sampling noise (χ² 95% CI for σ at
  s = 0.289, n = 10: [0.20, 0.53]);
- 0.5: the absolute bound.

MDE is in win-rate units above the null (0.5 for superiority).

| Contrast | σ | MDE n = 24 | MDE n = 10 | n = 10, Holm over 6 | Powered for the expected effect? |
|---|---|---|---|---|---|
| Composite vs Jev (C1) | 0.233 | **0.139** (Θ ≥ 0.64) | 0.232 | 0.320 | yes, if the true Θ ≳ 0.65. The screen estimate is 0.867 on 0–9, optimistic by ≤ 0.076 |
| Composite, pooled σ | 0.203 | 0.121 | 0.202 | 0.278 | |
| Composite, independence bound | 0.289 | 0.172 | 0.287 | 0.396 | |
| Composite, largest pair | 0.314 | 0.188 | 0.313 | 0.431 | |
| Composite, absolute bound | 0.500 | 0.299 | 0.498 | 0.686 | |
| Per game, Snake (σ_w 0.411; C2 Holm-3) | 0.411 | 0.246 (0.290 Holm) | 0.410 | | **underpowered**: needs W ≥ 0.79 |
| Per game, Rotorwash-Ramp | 0.372 | 0.222 (0.262 Holm) | 0.371 | | **underpowered** unless the effect is large |
| Per game, Booster | 0.175 | 0.104 (0.123 Holm) | 0.174 | | the 22 s wall compresses the rates (§10, item 5) |
| R-RT (NI, Θ0 = 0.35), power at Θ = 0.5 / 0.6 | 0.233 (0.289) | 0.86 / 1.00 (0.68 / 0.98) | | | yes |

- **Screen vs the 6 players at n = 10 is underpowered** for anything but a large effect (0.23–0.43).
- **A vs t_dual/chord and B vs A are underpowered** in realtime at n = 10 (interface effects seen so far are ≤ 0.1).

Absolute estimates, 95% half-width at n = 24 (σ from Board 1 v2, T-dual chord / Jev):

| Game | RMST (s) | Ladder position |
|---|---|---|
| Snake | 1.3 / 3.2 | 0.011 / 0.053 (floor: T-dual chord is below the naive anchor) |
| Rotorwash-Ramp | 2.8 / 2.9 | 0.094 / 0.091 |
| Booster | 0.0 / 1.3 | 0.0 / 0.027 (wall at 22.0 s) |

Offline gate power [E]:
- G2: 0.84 at Δ = 0 (SE 0.0204).
- G1-B: passes only if φ̂_B ≲ 0.05; the prior is ≈ 0.15.
- G3: ≈ 0.74–0.95 at Δ_U = 0.
- LAT-A: likely pass (Booster is the closest to the limit). LAT-B: predicted fail.

## 8. Release rule and the model card

### 8.1 Release rule (all must pass; IUT)

```
RELEASE = SELECT ∈ {A, B}  ∧  V_rt(V*)  ∧  R-RT(V*)
```
- Publishing (HF public, nagi-public SDK merge) additionally needs the owner's explicit P3 click (APPROVAL).
- The private pre-upload is not a release.

### 8.2 Claims the model card may make, each tied to its test

| Claim | Allowed iff | Wording |
|---|---|---|
| One forward decides all K controls | design fact | Plain statement. For B, add "M = K orders batched". |
| Decision latency | LAT passed | "p50 X ms at 3 concurrent streams on H100 (merged bf16, fused kernels)", plus the in-play p50/p90/p99 from P2. Never generalized to other hardware. |
| Multi-control quality vs K-call | G2 passed | "Non-inferior to K-call of the same weights within 0.06 on MA1 (Δ̂ [one-sided 97.5% bound])". |
| Order | A: G1-SDK | A: "through the SDK, answers do not depend on the order in which the client lists controls". **The model itself changes its answer on X% [CI] of states when the control order is rotated (Chord P1 REJECT-ORDER; not passed).** |
| Order | B: G1-SDK ∧ G1-B | B: "order residual X% [CI] ≤ 10% for K ≤ 3; K = 4 not gated". |
| Realtime vs Jev: estimate | R-RT passed | "Survived longer than Jev in X% [95% CI] of head-to-heads (24 seed indices × 3 games)". |
| Realtime vs Jev: superiority | C1 passed | "outperforms Jev in realtime head-to-heads". Per-game wording only where C2_g passed. |
| Absolute realtime level | always, as estimates | RMST, ladder position and level, with CIs and the anchor definition. |

**Never allowed:**
- a claim from indices 0–9 beyond "screen";
- a lockstep claim;
- "order-invariant model" for A;
- K ≥ 5, or games outside the suite;
- any inference of Jev's size or hardware from latency (AGENTS);
- any statement that P1 REJECT-ORDER or A1 passed.

### 8.3 Mandatory disclosures (the model card and release notes)

1. **Order sensitivity (both variants).**
   - Chord P1 REJECT-ORDER: 0.260 [0.184, 0.343]. It stays failed.
   - For A: the φ_A re-measured here. Non-SDK clients must present controls in the canonical order (§1) to get the
     evaluated behaviour; other orders are unevaluated and flip ≈ φ_A of answers. Quality numbers are for canonical
     order only.
   - For B: φ_B, and that K = 4 is ungated.
2. **Lockstep deficit.** In P1 lockstep Rotorwash v2 (compute-matched against K-call's 3 forwards), chord had R −0.101
   [−0.165, −0.043], survival −43.1 s, and 24/24 ceiling crashes vs K-call. Burst's advantage is latency.
3. **Training provenance.**
   - The owner overrode the update-125 pause (P1 Amendment 3).
   - Retention vs ENORMOUS-old: recipe-dev language and policy passed; Arena retention was INCONCLUSIVE; the public
     suite was not tested.
   - In-domain O2 flags on all 3 games (PROTOCOL §A1.8).
4. **Measurement limits.**
   - Booster Gauntlet has a 22.0 s wall: T-dual variants and ENORMOUS-CL end many rounds at exactly 22.0 s, so ties
     compress the rates.
   - On Snake Rush, T-dual chord's median (10 s) is below the naive anchor (13.75 s).
5. **Realtime conditions.** Realtime only. Jev's pinned version and region. G3 detects only gross bias, plus the §3.3
   pathology flag if it triggered.

## 9. Outcome → action

| Outcome | Action |
|---|---|
| SELECT = FAIL (neither variant passes the offline gates) | **No release.** Stop the realtime shards not yet started if that saves money. Finished A rounds are research data (descriptive). Report every failed gate. |
| Offline gates PENDING (validity) | Fix on CPU and re-evaluate with the same rules. No GPU re-run unless predictions are missing. |
| SELECT = B | No release until B's follow-up P2 passes (new ticket). A's realtime is descriptive. |
| SELECT ∈ {A, B}, V_rt fails (a cell invalid) | **PENDING**: fix the harness, re-run the invalid cell under a new ticket, and never score it. Not a model failure. |
| SELECT ∈ {A, B}, V_rt ok, R-RT fails | **No release.** A research preview with the failed gate disclosed verbatim is possible **only if the owner explicitly decides** (AGENTS: never retroactively passed, never labelled as passing). |
| RELEASE, C1 fails | Release (after the owner's P3 click) **without** any "better than Jev" wording. The card quotes the Θ estimate and CI. |
| RELEASE, C1 passes | Release with the C1 claim, plus per-game claims only where C2_g passes. |
| Any gate FAIL, before or after | Recorded as FAIL forever. A later fix is a **new candidate with a new prereg**. |

**What would refute "Burst is a releasable fast readout":**
- SELECT = FAIL, or
- the G2 bound ≤ −0.06, or
- the LAT upper bound > 300 ms, or
- Θ's upper 97.5% bound < 0.5 against Jev on fresh seeds.

**Most likely outcome [E]:** SELECT = A (B fails LAT and probably G1-B), R-RT passes, and C1 passes if the Board 1 lead
holds at ≥ 0.64 after the winner's-curse shrinkage.

## 10. Ambiguities and operator/owner decisions (recommendation first)

1. **The realtime release gate is R-RT (NI vs Jev at δ_w = 0.15).** Recommended as a sanity floor. The alternatives
   are no realtime gate (only claims), or superiority as a gate; the latter would block release at a tie with the
   vendor. The owner may change this only by an amendment before P2 data are opened.
2. **G3 needs seed provenance** for the filler (CPU, via `arena.v3.filler.build`). Without it G3 is PENDING, which also
   blocks A. The operator should run the provenance map on CPU now, before the job.
3. **The K = 4 order residual of B is not gated** (the frozen sets are K = 3 only). It is only moot if B is not
   selected.
4. **The Jev fingerprint must match Board 1 v2.** If the vendor changed, the Jev 10–33 cell is a different player. The
   screen vs Jev on 0–9 then compares different versions (descriptive anyway).
5. **Booster's 22.0 s wall** (hop timeout) compresses win rates among the strong players. It is a game-design issue
   for Arena v3, not for this prereg.
6. **The K-call comparator is re-scored in the same job** (decisional). If the job instead reuses P1's K-call
   predictions, that must be an amendment before G2 is opened (the serving path differs).
7. **The B follow-up, if SELECT = B,** needs budget within the $14.00 cap and its own ticket.
8. **Clock note.** APPROVAL.md records relayed owner times of "~17:15" and "~17:25 +07". This file was drafted between
   17:10 and 17:20 +07 by the Mac clock. The relayed times are approximate, and no rule depends on them.

## Amendments

### Amendment 1 (2026-09-27 17:30 +07 by the Mac clock; pre-data correction)

**Data state.** No Burst data existed when this was written: no gates job and no realtime job had been dispatched or
opened. The only facts used are frozen prompt lists and code (below).

**What was wrong.** §1 and `prereg_constants.json` → `candidate.canonical_order` gave Booster Gauntlet's canonical
order as the sorted qids `(fins, gimbal, legs, throttle)`, and called it "lexicographic qid order in all 3 suite
games". That is false for Booster:
- **The declared order is `(throttle, gimbal, fins, legs)`.** That is the game's MultiQuery order, which is also the
  CONTROLS-line order and the order used in training and in the Board 1 v2 prompts.
- **Checked here on the frozen filler** `booster_gauntlet-g1.1.json.gz` (`dd3f3673…`): `queries` keys =
  [throttle, gimbal, fins, legs], and `multi.controls` is in the same order.
- **The other two games were checked the same way and are unchanged:** Rotorwash-Ramp `(collective, cyclic, winch)`,
  Snake `(move,)`.
- **Why it matters:** with the sorted list, validity check §4.2 ("A's Arena prompts equal the Board 1 v2 `t_dual/chord`
  prompt sha") could not pass on Booster, and A would not be the player Board 1 screened.

**Corrected definition (replaces the §1 "Canonical control order" and "SDK canonicalization" rows).**
- **Canonical order = the environment's declared control order.**
  - Offline MA sets: ascending `control_index`, i.e. the order of the state's `controls` list. This is unchanged.
  - Arena v3: the MultiQuery / CONTROLS-line order:
    - Booster Gauntlet `(throttle, gimbal, fins, legs)`;
    - Rotorwash-Ramp `(collective, cyclic, winch)`;
    - Snake Rush `(move,)`.
- **SDK resolution order** (this matches the SDK branch):
  1. an explicit `control_order`;
  2. otherwise, the environment's CONTROLS line;
  3. otherwise, the sorted qids.
- The SDK renders the prompt in the resolved order. For a fixed declared order, the prompt bytes are a function of the
  control **set** only, whatever order the client lists the controls in.

**Consequences, re-checked item by item.**
1. **The invariance scope is narrowed and made explicit.**
   - The deployed answer is invariant to the order in which the client lists controls, **given the declared order**.
   - A client that declares a different `control_order`, or passes its own CONTROLS line, changes the model input. The
     model-level sensitivity (φ_A for A, φ_B for B) then applies.
   - The release notes must state this (§8.2 order rows, §8.3 item 1).
   - If no order is declared, sorted qids give exact invariance.
2. **G1-SDK is restated.**
   - For each of the 500 frozen P1 states, the declared order (ascending `control_index`) is passed as an explicit
     `control_order`, and the controls are listed in each of the 6 orders. The token ids must be identical across all
     6 (CPU), and the served joint action identical for the presented vs the `#rot1` listing (in the job).
   - Also on CPU: with no declared order and no CONTROLS line, the 6 listings must yield identical ids under the
     sorted-qid fallback.
   - Rule unchanged: 500/500 on every check, else FAIL.
3. **Variant B, restated.** The orbit is the cyclic set anchored at the **declared** canonical order σ_c: the orders
   σ_c∘ρ^j, j = 0..K−1, where ρ rotates slots by one. The prompt rows are batched and averaged in the order j = 0..K−1.
   - Booster: σ_c = (throttle, gimbal, fins, legs), giving the rows (throttle, gimbal, fins, legs),
     (gimbal, fins, legs, throttle), (fins, legs, throttle, gimbal) and (legs, throttle, gimbal, fins).
   - Rotorwash-Ramp: σ_c = (collective, cyclic, winch), giving (collective, cyclic, winch), (cyclic, winch, collective)
     and (winch, collective, cyclic).
   - Snake: M = 1.
   - MA sets: σ_c = ascending `control_index`. This is unchanged, so G1-B's estimand on the 500 frozen P1 states (even
     coset C_3∘σ_c vs odd coset C_3∘(σ_c∘reversal)) and its implementation check (`#rot1` flips = 0/500) are unchanged.
   - The K = 4 descriptive contrast becomes C_4∘σ_c vs C_4∘(σ_c∘(0 1)), where (0 1) swaps the first two slots
     (throttle ↔ gimbal) of the declared order. It stays descriptive.
4. **Nothing else depended on the sorted list.**
   - G2 and G3 use the MA and Rotorwash-Ramp orders, which are unchanged.
   - LAT on Booster uses the declared order for A and the restated orbit for B.
   - Validity check §4.2 is now satisfiable as written.
   - The option order within each control and the tie rule are unchanged.
5. **No threshold, α, margin, seed or selection rule changes.**
