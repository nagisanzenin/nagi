# Burst fresh-seed confirmation: Nagi-ENORMOUS Burst vs Jev (Arena v3, P2)

Result of the preregistered confirmation in [BURST_PREREG.md](BURST_PREREG.md) (§6.3–§8), run on 2026-09-27.
**Decision: RELEASE. Every preregistered release gate passed.**

## Why this run exists

Board 1 ([BOARD1_REPORT.md](BOARD1_REPORT.md)) ranked six players on seed indices 0–9. The same seeds were used to pick
T-dual Burst as the best of four Nagi entries, so its Board 1 numbers carry winner's-curse bias. This run re-tests one
comparison, fixed before any new data, on **fresh seed indices 10–33** that played no part in the selection. It is
reported separately and never pooled with seeds 0–9, and the Board 1 leaderboard is unchanged.

## What was tested

| Item | Frozen definition |
|---|---|
| Player | **Nagi-ENORMOUS Burst**, the released name of T-dual Burst: the same weights and byte-identical Arena prompts (variant A of the prereg), served on the pinned H100 path (merged bf16, fused kernels, request micro-batching). |
| Variant selection | From offline receipts only, before any real-time outcome was opened: variant A passed its offline gates; variant B did not (it failed the latency gate and the order-residual gate), so A was selected. |
| Opponent | Jev (remote API, vendor version `jev-1.13.0`, the same version as in Board 1). |
| Seeds | Seed indices 10–33 in each of the 3 games: **n = 24 per game**, 72 paired rounds. |
| Estimand | Θ = mean over the 3 games of the paired per-seed win rate of Burst against Jev (fail later = 1, same tick = ½). Unit of independence: the seed index. 95% t interval with 23 df on the per-index game mean. |
| Tests | Fixed sequence at one-sided α = 0.025: (1) release gate R-RT, H0: Θ ≤ 0.35; (2) superiority C1, H0: Θ ≤ 0.50, needing the t bound **and** the sign-flip test to agree; (3) per game C2, only if C1 passes, Holm over the 3 games. |
| Validity | V_rt: records replay exactly, every cell valid (void rule of the protocol), the seeds for indices 0–9 equal Board 1's, identical serving path across shards. Fails closed. |

## Result

| Gate | Value | Rule | Result |
|---|---|---|---|
| V_rt (validity) | 174 of 174 replayed rounds exact; 0 void rounds; seeds 0–9 equal Board 1 (30 compared, 0 mismatches); serving path identical | all true | **PASS** |
| R-RT (release gate) | lower 97.5% bound 0.577 | > 0.35 | **PASS** |
| C1 (superiority) | lower 97.5% bound 0.577; sign-flip p = 0.0018 | > 0.50 and p ≤ 0.025 | **PASS** |

**Θ = 0.674, 95% CI [0.577, 0.770]** (n = 24 seed indices × 3 games). Burst survived longer than Jev in 67.4% of
real-time head-to-heads on fresh seeds, and C1 allows the claim that Burst outperforms Jev in real-time head-to-heads
over the three games.

Per game (C2, Holm over 3 games):

| Game | W: Burst outlasted Jev | n | lower 97.5% bound | sign-flip p | Holm level | Per-game claim |
|---|---|---|---|---|---|---|
| Booster Gauntlet | 0.979 | 24 | 0.925 | 0.00001 | 0.0083 | **significant** |
| Rotorwash-Ramp | 0.583 | 24 | 0.337 | 0.27 | 0.0125 | not significant |
| Snake Rush | 0.458 | 24 | 0.253 | 0.74 | 0.025 | not significant |

**Only Booster Gauntlet is individually significant.** On Rotorwash-Ramp and Snake Rush the per-game rates cannot be
told apart from an even split, and on Snake Rush the point estimate is below 50%. No per-game claim is made for those two
games. (The Booster p-value is the floor of the 100,000-draw Monte Carlo sign-flip test.)

**Why Booster.** All 24 of Burst's Booster rounds ended at exactly 22.0 s as hop timeouts: the booster was still flying
under control but had not landed its first hop by the 22 s landing deadline. Jev crashed before 22.0 s in 23 of 24
rounds (landing without legs, torn legs or breakup) and timed out in 1, which is a tie. So Burst's Booster margin comes
from not crashing, not from landing.

### Estimates (labelled estimates, 95% t CIs over the 24 indices; no test attached)

RMST ≤ 60 s is the mean of min(time of failure, 60 s). No round reached 60 s (0 censored).

| Game | Burst RMST (s) | Jev RMST (s) | Burst median level | Jev median level |
|---|---|---|---|---|
| Snake Rush | 9.33 [7.15, 11.52] | 10.67 [7.93, 13.40] | 1 | 1 |
| Rotorwash-Ramp | 23.08 [20.68, 25.47] | 21.50 [17.30, 25.69] | 3 | 2 |
| Booster Gauntlet | 22.00 (every round at 22.0 s, no interval) | 12.26 [10.64, 13.88] | 3 | 2 |

### Screen on seeds 0–9 (not confirmatory)

- Against the Board 1 Jev records on the selection seeds 0–9, the same pairing read Θ = 0.867 (screen, n = 10). On fresh
  seeds it is 0.674. That drop is what selection bias plus real-time run-to-run noise look like, and it is why only
  the fresh-seed number is the estimate.
- Test-retest: this run of Burst on seeds 0–9 against the Board 1 T-dual Burst records (the same player) scored
  Θ = 0.433, 95% CI [0.263, 0.604]. That is consistent with 50%, and its spread measures run-to-run noise in real-time
  play.

## Notes and limits

- **Jev's answers are not deterministic.** The prereg planned a fingerprint of Jev's answers on 8 fixed requests as a
  pinned-vendor check. Three back-to-back calls from one client gave three different fingerprints, so a fingerprint
  difference does not indicate a vendor change. The frozen validity check (committed before the P2 data) compares the
  vendor version string, which was `jev-1.13.0`, the Board 1 version, in every Jev run. This was disclosed in the
  release report, and no rule was changed.
- **Real time only.** This measures a served product at 4 decisions per second on the stated hardware. Jev's times
  include its network path. Nothing here says anything about Jev's size or hardware.
- **Scope.** The claims cover the three Arena v3 suite games and these players only. Board 1 remains a 10-seed screen.
- **Model-card disclosures.** The release carries the mandatory disclosures of the prereg (§8.3): order sensitivity of
  the model itself (the P1 order-invariance gate stays failed; through the SDK, controls are put in canonical order), the lockstep
  deficit, training provenance and the Booster 22.0 s wall.

## Receipts (verbatim excerpt)

The numbers above are copied from the release receipt; nothing was recomputed. The site generator
(`site/arena/build/make_v3.py --confirm`) re-derives each per-game W and Θ from the per-seed out order and fails if they
disagree with the receipt. Excerpt of `release_decision.json`:

```json
{
 "fresh_vs_jev": {
  "W": {
   "snake": 0.4583333333333333,
   "rotorwash_ramp": 0.5833333333333334,
   "booster_gauntlet": 0.9791666666666666
  },
  "theta": 0.6736111111111112,
  "se": 0.04649464354837324,
  "df": 23,
  "lb975": 0.577429612891048,
  "ub975": 0.7697926093311743,
  "method": "t_23 on c_i (no dropped index)",
  "n_by_game": {
   "snake": 24,
   "rotorwash_ramp": 24,
   "booster_gauntlet": 24
  }
 },
 "R_RT": {
  "H0": "Theta <= 0.35",
  "lb975": 0.577429612891048,
  "passed": true
 },
 "C1": {
  "lb975": 0.577429612891048,
  "signflip_p": 0.001809981900180998,
  "passed": true
 },
 "C2": {
  "tested": true,
  "games": {
   "booster_gauntlet": {
    "W": 0.9791666666666666,
    "n": 24,
    "lb": 0.9253746417019976,
    "signflip_p": 9.99990000099999e-06,
    "holm_alpha": 0.008333333333333333,
    "passed": true
   },
   "rotorwash_ramp": {
    "W": 0.5833333333333334,
    "n": 24,
    "lb": 0.3368341926480352,
    "signflip_p": 0.2699273007269927,
    "holm_alpha": 0.0125,
    "passed": false
   },
   "snake": {
    "W": 0.4583333333333333,
    "n": 24,
    "lb": 0.2526263177861815,
    "signflip_p": 0.7355126448735513,
    "holm_alpha": 0.025,
    "passed": false
   }
  }
 },
 "decision": "RELEASE (owner P3 click still required)"
}
```

The receipts stay in Nagi's private research repository. Their sha256, so they can be checked if they are published
later:

| File | sha256 |
|---|---|
| `release_decision.json` (gates, estimates, decision) | `e820a29e6596d8dee6d7919bc2d420933fdb6cff9977eb254e81a5da607a47d9` |
| `results.json` (per-seed out order, seeds 0–33) | `cb4875716db62396419e2675aa6f72183140ce1984869f0edfb2e351196407e4` |
| `selection.json` (variant selection, offline only) | `4fc7101433a8e67890a7b6d7a89ee2ee97957456dfc98b1c498e082c1884e3ef` |
| `replay.json` (174 of 174 exact) | `17f1b3b8f421d49eedcbcc8e42c404f1037b4760632820549ba30ee977a4ef32` |
| `BURST_REPORT.md` (generated report) | `711bae79e77ebeb55b100487be7ec7cd4d1a4115af13f227d58c42360701550d` |
| `JEV_FINGERPRINT_NOTE.md` (Jev note above) | `31040892a2859257f21b542fe83d3539742b2a786842b713a8304c658c031e60` |
| `PREREG.md` (unredacted frozen prereg) | `37b6ba1e662558ed6b1f582eef6dc736c323554f2fbcdabe69eb80e5a08fac38` |

Board 1 run 2 source receipt: `2173f762133957b8693a49078db7dcae32f79f6337f71435db6095147ab89d76`.
