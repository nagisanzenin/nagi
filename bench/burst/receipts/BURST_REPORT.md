# Burst release: P2 realtime report (agent reader)

SELECT = **A** (offline receipts only); V* = `enormous_burst/chord`; decision: **RELEASE (owner P3 click still required)**.

| Gate | Value | Rule | Result |
|---|---|---|---|
| V_rt | replay True, cells valid True, seeds {'ok': True, 'compared': 30, 'mismatch': []}, serving True | all true | True |
| R-RT | Θ̂ 0.6736111111111112, LB97.5 0.577429612891048 | LB > 0.35 | True |
| C1 | {'lb975': 0.577429612891048, 'signflip_p': 0.001809981900180998, 'passed': True} | LB > 0.5 and sign-flip p ≤ 0.025 | True |
| C2 | {'tested': True, 'games': {'booster_gauntlet': {'W': 0.9791666666666666, 'n': 24, 'lb': 0.9253746417019976, 'signflip_p': 9.99990000099999e-06, 'holm_alpha': 0.008333333333333333, 'passed': True}, 'rotorwash_ramp': {'W': 0.5833333333333334, 'n': 24, 'lb': 0.3368341926480352, 'signflip_p': 0.2699273007269927, 'holm_alpha': 0.0125, 'passed': False}, 'snake': {'W': 0.4583333333333333, 'n': 24, 'lb': 0.2526263177861815, 'signflip_p': 0.7355126448735513, 'holm_alpha': 0.025, 'passed': False}}} | Holm 3 games | — |

## Estimates on fresh indices 10–33 (95% t CIs; labelled estimates)

```
{
 "V_star_fresh": {
  "snake": {
   "n": 24,
   "rmst60": 9.333333333333334,
   "rmst60_ci95": [
    7.1454563244616836,
    11.521210342204984
   ],
   "ladder_mean": 0.02604166666666667,
   "median_level": 1.0,
   "censored": 0
  },
  "rotorwash_ramp": {
   "n": 24,
   "rmst60": 23.075666666666667,
   "rmst60_ci95": [
    20.679660722339516,
    25.471672610993817
   ],
   "ladder_mean": 0.4313735244847752,
   "median_level": 3.0,
   "censored": 0
  },
  "booster_gauntlet": {
   "n": 24,
   "rmst60": 22.0,
   "rmst60_ci95": null,
   "ladder_mean": 0.3915289256198347,
   "median_level": 3.0,
   "censored": 0
  }
 },
 "jev_fresh": {
  "snake": {
   "n": 24,
   "rmst60": 10.666666666666666,
   "rmst60_ci95": [
    7.929440746042799,
    13.403892587290533
   ],
   "ladder_mean": 0.059895833333333336,
   "median_level": 1.0,
   "censored": 0
  },
  "rotorwash_ramp": {
   "n": 24,
   "rmst60": 21.495083333333337,
   "rmst60_ci95": [
    17.304650223802625,
    25.68551644286405
   ],
   "ladder_mean": 0.343177783597525,
   "median_level": 2.0,
   "censored": 0
  },
  "booster_gauntlet": {
   "n": 24,
   "rmst60": 12.260416666666666,
   "rmst60_ci95": [
    10.640742073405688,
    13.880091259927644
   ],
   "ladder_mean": 0.06379132231404959,
   "median_level": 2.0,
   "censored": 0
  }
 }
}
```

## Screen vs the 6 Board 1 v2 players on 0–9 (not confirmatory)

```
{
 "label": "screen, n = 10, not confirmatory; selection caveat (T-dual chord = Board 1 champion on these indices; worst-case optimism 0.076)",
 "vs": {
  "enormous_old/kcall": {
   "W": {
    "snake": 0.55,
    "rotorwash_ramp": 0.8,
    "booster_gauntlet": 1.0
   },
   "theta": 0.7833333333333333,
   "se": 0.07049209744694178,
   "df": 9,
   "lb975": 0.6238691301730651,
   "ub975": 0.9427975364936015,
   "method": "t_9 on c_i (no dropped index)",
   "n_by_game": {
    "snake": 10,
    "rotorwash_ramp": 10,
    "booster_gauntlet": 10
   },
   "signflip_p": 0.0012999350032498376
  },
  "t_dual/chord": {
   "W": {
    "snake": 0.4,
    "rotorwash_ramp": 0.4,
    "booster_gauntlet": 0.5
   },
   "theta": 0.43333333333333335,
   "se": 0.0753592220347252,
   "df": 9,
   "lb975": 0.26285892942457956,
   "ub975": 0.6038077372420871,
   "method": "t_9 on c_i (no dropped index)",
   "n_by_game": {
    "snake": 10,
    "rotorwash_ramp": 10,
    "booster_gauntlet": 10
   },
   "signflip_p": 0.8940052997350133
  },
  "t_dual/kcall": {
   "W": {
    "snake": 0.4,
    "rotorwash_ramp": 0.7,
    "booster_gauntlet": 0.55
   },
   "theta": 0.55,
   "se": 0.09638528651609708,
   "df": 9,
   "lb975": 0.331961333719254,
   "ub975": 0.7680386662807461,
   "method": "t_9 on c_i (no dropped index)",
   "n_by_game": {
    "snake": 10,
    "rotorwash_ramp": 10,
    "booster_gauntlet": 10
   },
   "signflip_p": 0.32338383080845956
  },
  "semif_4b/kcall": {
   "W": {
    "snake": 0.85,
    "rotorwash_ramp": 1.0,
    "booster_gauntlet": 1.0
   },
   "theta": 0.9500000000000001,
   "se": 0.03557291243018249,
   "df": 9,
   "lb975": 0.8695284813444695,
   "ub975": 1.0304715186555307,
   "method": "t_9 on c_i (no dropped index)",
   "n_by_game": {
    "snake": 10,
    "rotorwash_ramp": 10,
    "booster_gauntlet": 10
   },
   "signflip_p": 4.999750012499375e-05
  },
  "enormous_cl/kcall": {
   "W": {
    "snake": 0.3,
    "rotorwash_ramp": 0.9,
    "booster_gauntlet": 0.7
   },
   "theta": 0.6333333333333333,
   "se": 0.07777777777777779,
   "df": 9,
   "lb975": 0.4573877762268064,
   "ub975": 0.8092788904398602,
   "method": "t_9 on c_i (no dropped index)",
   "n_by_game": {
    "snake": 10,
    "rotorwash_ramp": 10,
    "booster_gauntlet": 10
   },
   "signflip_p": 0.06944652767361632
  },
  "jev/vendor_single": {
   "W": {
    "snake": 0.7,
    "rotorwash_ramp": 0.9,
    "booster_gauntlet": 1.0
   },
   "theta": 0.8666666666666667,
   "se": 0.07370277311900889,
   "df": 9,
   "lb975": 0.6999394105374099,
   "ub975": 1.0333939227959235,
   "method": "t_9 on c_i (no dropped index)",
   "n_by_game": {
    "snake": 10,
    "rotorwash_ramp": 10,
    "booster_gauntlet": 10
   },
   "signflip_p": 4.999750012499375e-05
  }
 }
}
```

## Merged board (all players, arena_v3_report)

## Nagi champion selection (frozen rule, BOARD1_APPROVAL)

Rule: mean over games of the paired per-seed win rate vs the 3 external competitors; ties: sum RMST<=60, then mean level at failure, then NAGI order. Externals: Jev, SemIf-4B.

| Rank | Nagi entry | vs externals: Booster Gauntlet | vs externals: Rotorwash-Ramp | vs externals: Snake Rush | **Composite** | ΣRMST≤60 (s) | mean level |
|---|---|---|---|---|---|---|---|
| 1 | T-dual Burst | 100% | 95% | 82% | **92%** | 56.2 | 2.40 |
| 2 | ENORMOUS-CL | 95% | 85% | 88% | **89%** | 48.9 | 2.17 |
| 3 | T-dual K-call | 100% | 75% | 80% | **85%** | 50.1 | 2.23 |
| 4 | ENORMOUS-old | 45% | 80% | 77% | **68%** | 33.3 | 1.47 |

**Champion: T-dual Burst.** Caveat: best-of-4 selection: the champion's numbers are optimistic (winner's curse); champion-vs-others margins are a screen, not confirmatory; confirmation needs fresh seeds.

## Leaderboard: % of head-to-heads survived longer (all 7 players, same seeds)

| # | Player | Booster Gauntlet | Rotorwash-Ramp | Snake Rush | **All games** |
|---|---|---|---|---|---|
| 1 | T-dual Burst | 79% | 85% | 62% | **76%** |
| 2 | ENORMOUS Burst | 79% | 75% | 50% | **68%** |
| 3 | T-dual K-call | 77% | 50% | 61% | **62%** |
| 4 | ENORMOUS-CL | 63% | 50% | 73% | **62%** |
| 5 | ENORMOUS-old | 15% | 47% | 52% | **38%** |
| 6 | Jev | 34% | 44% | 33% | **37%** |
| 7 | SemIf-4B | 3% | 0% | 18% | **7%** |

## Typical round: survived · level reached (median over seeds)

| Player | Booster Gauntlet | Rotorwash-Ramp | Snake Rush |
|---|---|---|---|
| T-dual Burst | survived 22 s · Level 3/6 | survived 26 s · Level 3/6 | survived 10 s · Level 1/6 |
| ENORMOUS Burst | survived 22 s · Level 3/6 | survived 24 s · Level 3/6 | survived 9 s · Level 1/6 |
| T-dual K-call | survived 22 s · Level 3/6 | survived 18 s · Level 2/6 | survived 10 s · Level 1/6 |
| ENORMOUS-CL | survived 22 s · Level 3/6 | survived 18 s · Level 2/6 | survived 11 s · Level 2/6 |
| ENORMOUS-old | survived 9 s · Level 1/6 | survived 16 s · Level 2/6 | survived 6 s · Level 1/6 |
| Jev | survived 9 s · Level 1/6 | survived 16 s · Level 2/6 | survived 7 s · Level 1/6 |
| SemIf-4B | survived 5 s · Level 1/6 | survived 4 s · Level 1/6 | survived 4 s · Level 1/6 |

## % of rounds still alive vs time (survival curve)

| Player · game | 10 s | 20 s | 30 s | 40 s | 50 s | 60 s |
|---|---|---|---|---|---|---|
| T-dual Burst · Booster Gauntlet | 100% | 100% | 0% | 0% | 0% | 0% |
| T-dual Burst · Rotorwash-Ramp | 100% | 80% | 10% | 0% | 0% | 0% |
| T-dual Burst · Snake Rush | 30% | 0% | 0% | 0% | 0% | 0% |
| ENORMOUS Burst · Booster Gauntlet | 100% | 100% | 0% | 0% | 0% | 0% |
| ENORMOUS Burst · Rotorwash-Ramp | 97% | 74% | 3% | 0% | 0% | 0% |
| ENORMOUS Burst · Snake Rush | 32% | 3% | 0% | 0% | 0% | 0% |
| T-dual K-call · Booster Gauntlet | 100% | 100% | 0% | 0% | 0% | 0% |
| T-dual K-call · Rotorwash-Ramp | 100% | 50% | 0% | 0% | 0% | 0% |
| T-dual K-call · Snake Rush | 20% | 0% | 0% | 0% | 0% | 0% |
| ENORMOUS-CL · Booster Gauntlet | 100% | 60% | 0% | 0% | 0% | 0% |
| ENORMOUS-CL · Rotorwash-Ramp | 100% | 10% | 0% | 0% | 0% | 0% |
| ENORMOUS-CL · Snake Rush | 70% | 10% | 0% | 0% | 0% | 0% |
| ENORMOUS-old · Booster Gauntlet | 0% | 0% | 0% | 0% | 0% | 0% |
| ENORMOUS-old · Rotorwash-Ramp | 100% | 20% | 0% | 0% | 0% | 0% |
| ENORMOUS-old · Snake Rush | 20% | 0% | 0% | 0% | 0% | 0% |
| Jev · Booster Gauntlet | 47% | 3% | 0% | 0% | 0% | 0% |
| Jev · Rotorwash-Ramp | 97% | 35% | 29% | 0% | 0% | 0% |
| Jev · Snake Rush | 38% | 9% | 0% | 0% | 0% | 0% |
| SemIf-4B · Booster Gauntlet | 0% | 0% | 0% | 0% | 0% | 0% |
| SemIf-4B · Rotorwash-Ramp | 0% | 0% | 0% | 0% | 0% | 0% |
| SemIf-4B · Snake Rush | 0% | 0% | 0% | 0% | 0% | 0% |

## OUT order per round (first out → last standing)

**Booster Gauntlet**
- seed 0: ENORMOUS-old (8.8 s) → Jev (8.9 s) → SemIf-4B (9.6 s) → ENORMOUS Burst (22.0 s) → ENORMOUS-CL (22.0 s) → T-dual Burst (22.0 s) → T-dual K-call (22.0 s)
- seed 1: SemIf-4B (4.4 s) → ENORMOUS-old (8.9 s) → Jev (9.0 s) → ENORMOUS Burst (22.0 s) → ENORMOUS-CL (22.0 s) → T-dual Burst (22.0 s) → T-dual K-call (22.0 s)
- seed 2: SemIf-4B (4.7 s) → ENORMOUS-old (8.2 s) → Jev (8.2 s) → ENORMOUS-CL (15.3 s) → ENORMOUS Burst (22.0 s) → T-dual Burst (22.0 s) → T-dual K-call (22.0 s)
- seed 3: SemIf-4B (4.7 s) → ENORMOUS-old (8.8 s) → Jev (8.9 s) → ENORMOUS-CL (19.0 s) → ENORMOUS Burst (22.0 s) → T-dual Burst (22.0 s) → T-dual K-call (22.0 s)
- seed 4: SemIf-4B (4.6 s) → ENORMOUS-old (8.3 s) → Jev (8.4 s) → ENORMOUS Burst (22.0 s) → ENORMOUS-CL (22.0 s) → T-dual Burst (22.0 s) → T-dual K-call (22.0 s)
- seed 5: SemIf-4B (4.7 s) → ENORMOUS-old (8.3 s) → Jev (17.1 s) → ENORMOUS Burst (22.0 s) → ENORMOUS-CL (22.0 s) → T-dual Burst (22.0 s) → T-dual K-call (22.0 s)
- seed 6: SemIf-4B (4.7 s) → ENORMOUS-old (8.5 s) → Jev (12.3 s) → ENORMOUS-CL (17.2 s) → T-dual K-call (20.5 s) → ENORMOUS Burst (22.0 s) → T-dual Burst (22.0 s)
- seed 7: SemIf-4B (4.8 s) → ENORMOUS-old (8.4 s) → Jev (9.1 s) → ENORMOUS Burst (22.0 s) → ENORMOUS-CL (22.0 s) → T-dual Burst (22.0 s) → T-dual K-call (22.0 s)
- seed 8: SemIf-4B (4.7 s) → ENORMOUS-old (9.9 s) → ENORMOUS-CL (14.8 s) → Jev (15.1 s) → ENORMOUS Burst (22.0 s) → T-dual Burst (22.0 s) → T-dual K-call (22.0 s)
- seed 9: SemIf-4B (4.7 s) → ENORMOUS-old (8.6 s) → Jev (8.6 s) → ENORMOUS Burst (22.0 s) → ENORMOUS-CL (22.0 s) → T-dual Burst (22.0 s) → T-dual K-call (22.0 s)
- seed 10: Jev (13.3 s) → ENORMOUS Burst (22.0 s)
- seed 11: Jev (8.3 s) → ENORMOUS Burst (22.0 s)
- seed 12: Jev (14.3 s) → ENORMOUS Burst (22.0 s)
- seed 13: Jev (11.8 s) → ENORMOUS Burst (22.0 s)
- seed 14: Jev (14.1 s) → ENORMOUS Burst (22.0 s)
- seed 15: Jev (8.4 s) → ENORMOUS Burst (22.0 s)
- seed 16: Jev (17.3 s) → ENORMOUS Burst (22.0 s)
- seed 17: Jev (15.3 s) → ENORMOUS Burst (22.0 s)
- seed 18: Jev (8.5 s) → ENORMOUS Burst (22.0 s)
- seed 19: ENORMOUS Burst (22.0 s) → Jev (22.0 s)
- seed 20: Jev (8.8 s) → ENORMOUS Burst (22.0 s)
- seed 21: Jev (8.8 s) → ENORMOUS Burst (22.0 s)
- seed 22: Jev (8.8 s) → ENORMOUS Burst (22.0 s)
- seed 23: Jev (14.6 s) → ENORMOUS Burst (22.0 s)
- seed 24: Jev (16.6 s) → ENORMOUS Burst (22.0 s)
- seed 25: Jev (8.6 s) → ENORMOUS Burst (22.0 s)
- seed 26: Jev (8.7 s) → ENORMOUS Burst (22.0 s)
- seed 27: Jev (14.8 s) → ENORMOUS Burst (22.0 s)
- seed 28: Jev (8.7 s) → ENORMOUS Burst (22.0 s)
- seed 29: Jev (8.8 s) → ENORMOUS Burst (22.0 s)
- seed 30: Jev (14.8 s) → ENORMOUS Burst (22.0 s)
- seed 31: Jev (8.8 s) → ENORMOUS Burst (22.0 s)
- seed 32: Jev (14.1 s) → ENORMOUS Burst (22.0 s)
- seed 33: Jev (16.3 s) → ENORMOUS Burst (22.0 s)

**Rotorwash-Ramp**
- seed 0: SemIf-4B (3.7 s) → ENORMOUS-old (12.9 s) → T-dual K-call (15.4 s) → ENORMOUS-CL (19.5 s) → Jev (20.1 s) → T-dual Burst (24.8 s) → ENORMOUS Burst (28.6 s)
- seed 1: SemIf-4B (3.5 s) → Jev (13.7 s) → ENORMOUS-CL (14.0 s) → ENORMOUS-old (15.2 s) → ENORMOUS Burst (16.4 s) → T-dual K-call (21.2 s) → T-dual Burst (21.3 s)
- seed 2: SemIf-4B (4.2 s) → Jev (10.6 s) → ENORMOUS-CL (12.7 s) → ENORMOUS-old (16.5 s) → ENORMOUS Burst (22.8 s) → T-dual K-call (23.3 s) → T-dual Burst (25.7 s)
- seed 3: SemIf-4B (4.2 s) → ENORMOUS-CL (11.9 s) → ENORMOUS-old (14.0 s) → Jev (19.1 s) → T-dual K-call (23.3 s) → ENORMOUS Burst (25.9 s) → T-dual Burst (26.4 s)
- seed 4: SemIf-4B (3.7 s) → Jev (12.5 s) → ENORMOUS Burst (12.9 s) → ENORMOUS-old (13.0 s) → ENORMOUS-CL (16.5 s) → T-dual K-call (22.2 s) → T-dual Burst (28.9 s)
- seed 5: SemIf-4B (3.8 s) → T-dual K-call (15.0 s) → Jev (15.7 s) → ENORMOUS-CL (18.4 s) → ENORMOUS Burst (20.6 s) → ENORMOUS-old (22.0 s) → T-dual Burst (31.6 s)
- seed 6: SemIf-4B (3.7 s) → Jev (9.4 s) → ENORMOUS-old (12.2 s) → T-dual Burst (13.1 s) → ENORMOUS-CL (19.7 s) → T-dual K-call (26.6 s) → ENORMOUS Burst (28.0 s)
- seed 7: SemIf-4B (4.1 s) → T-dual K-call (11.1 s) → T-dual Burst (12.6 s) → ENORMOUS-old (16.0 s) → ENORMOUS-CL (26.2 s) → ENORMOUS Burst (26.7 s) → Jev (33.8 s)
- seed 8: SemIf-4B (3.9 s) → T-dual K-call (14.2 s) → Jev (14.4 s) → ENORMOUS-CL (18.0 s) → ENORMOUS-old (21.3 s) → T-dual Burst (28.4 s) → ENORMOUS Burst (29.2 s)
- seed 9: SemIf-4B (3.6 s) → T-dual K-call (11.2 s) → ENORMOUS-old (16.8 s) → Jev (17.2 s) → ENORMOUS-CL (17.4 s) → ENORMOUS Burst (27.9 s) → T-dual Burst (29.8 s)
- seed 10: ENORMOUS Burst (23.1 s) → Jev (31.9 s)
- seed 11: Jev (12.4 s) → ENORMOUS Burst (29.8 s)
- seed 12: ENORMOUS Burst (19.1 s) → Jev (35.2 s)
- seed 13: Jev (12.6 s) → ENORMOUS Burst (24.3 s)
- seed 14: Jev (12.8 s) → ENORMOUS Burst (18.2 s)
- seed 15: Jev (14.7 s) → ENORMOUS Burst (15.2 s)
- seed 16: ENORMOUS Burst (17.4 s) → Jev (38.5 s)
- seed 17: ENORMOUS Burst (7.1 s) → Jev (20.8 s)
- seed 18: Jev (16.2 s) → ENORMOUS Burst (29.3 s)
- seed 19: ENORMOUS Burst (26.3 s) → Jev (33.0 s)
- seed 20: ENORMOUS Burst (22.8 s) → Jev (33.5 s)
- seed 21: Jev (10.3 s) → ENORMOUS Burst (29.7 s)
- seed 22: Jev (15.6 s) → ENORMOUS Burst (17.6 s)
- seed 23: ENORMOUS Burst (19.7 s) → Jev (33.3 s)
- seed 24: Jev (17.4 s) → ENORMOUS Burst (30.3 s)
- seed 25: Jev (10.9 s) → ENORMOUS Burst (27.2 s)
- seed 26: ENORMOUS Burst (20.9 s) → Jev (32.3 s)
- seed 27: ENORMOUS Burst (20.5 s) → Jev (31.3 s)
- seed 28: Jev (10.2 s) → ENORMOUS Burst (28.6 s)
- seed 29: Jev (15.6 s) → ENORMOUS Burst (27.3 s)
- seed 30: Jev (14.0 s) → ENORMOUS Burst (24.5 s)
- seed 31: Jev (14.3 s) → ENORMOUS Burst (23.8 s)
- seed 32: ENORMOUS Burst (21.8 s) → Jev (33.3 s)
- seed 33: Jev (15.9 s) → ENORMOUS Burst (29.3 s)

**Snake Rush**
- seed 0: SemIf-4B (6.0 s) → ENORMOUS-old (6.5 s) → T-dual Burst (6.5 s) → T-dual K-call (6.5 s) → Jev (7.0 s) → ENORMOUS-CL (12.5 s) → ENORMOUS Burst (13.5 s)
- seed 1: SemIf-4B (4.5 s) → Jev (7.0 s) → T-dual Burst (10.0 s) → ENORMOUS Burst (12.0 s) → ENORMOUS-CL (12.5 s) → T-dual K-call (12.5 s) → ENORMOUS-old (15.5 s)
- seed 2: ENORMOUS-CL (3.5 s) → SemIf-4B (4.5 s) → ENORMOUS-old (5.5 s) → ENORMOUS Burst (6.5 s) → T-dual Burst (9.5 s) → T-dual K-call (10.0 s) → Jev (24.0 s)
- seed 3: Jev (3.5 s) → ENORMOUS Burst (4.5 s) → SemIf-4B (4.5 s) → T-dual Burst (4.5 s) → ENORMOUS-old (6.0 s) → T-dual K-call (10.0 s) → ENORMOUS-CL (11.0 s)
- seed 4: Jev (2.0 s) → ENORMOUS Burst (6.0 s) → ENORMOUS-CL (7.0 s) → SemIf-4B (7.0 s) → ENORMOUS-old (10.0 s) → T-dual Burst (10.0 s) → T-dual K-call (10.0 s)
- seed 5: Jev (5.0 s) → ENORMOUS-old (5.5 s) → SemIf-4B (5.5 s) → T-dual K-call (9.5 s) → ENORMOUS Burst (10.5 s) → T-dual Burst (10.5 s) → ENORMOUS-CL (11.0 s)
- seed 6: Jev (4.5 s) → ENORMOUS-old (5.0 s) → T-dual K-call (5.5 s) → SemIf-4B (6.5 s) → ENORMOUS Burst (11.0 s) → ENORMOUS-CL (11.0 s) → T-dual Burst (13.0 s)
- seed 7: SemIf-4B (4.5 s) → ENORMOUS Burst (10.0 s) → ENORMOUS-old (10.0 s) → T-dual Burst (10.0 s) → T-dual K-call (10.0 s) → Jev (19.5 s) → ENORMOUS-CL (22.0 s)
- seed 8: Jev (2.5 s) → SemIf-4B (4.5 s) → ENORMOUS-old (6.5 s) → ENORMOUS Burst (10.0 s) → ENORMOUS-CL (10.0 s) → T-dual Burst (10.0 s) → T-dual K-call (10.0 s)
- seed 9: SemIf-4B (4.5 s) → ENORMOUS Burst (10.0 s) → Jev (14.0 s) → T-dual K-call (15.5 s) → ENORMOUS-CL (16.0 s) → ENORMOUS-old (16.0 s) → T-dual Burst (16.0 s)
- seed 10: Jev (6.5 s) → ENORMOUS Burst (10.0 s)
- seed 11: ENORMOUS Burst (4.5 s) → Jev (7.5 s)
- seed 12: ENORMOUS Burst (4.5 s) → Jev (19.0 s)
- seed 13: ENORMOUS Burst (4.0 s) → Jev (7.0 s)
- seed 14: Jev (3.0 s) → ENORMOUS Burst (7.0 s)
- seed 15: ENORMOUS Burst (7.5 s) → Jev (17.5 s)
- seed 16: ENORMOUS Burst (8.5 s) → Jev (10.0 s)
- seed 17: ENORMOUS Burst (15.5 s) → Jev (25.8 s)
- seed 18: Jev (3.0 s) → ENORMOUS Burst (4.0 s)
- seed 19: Jev (4.0 s) → ENORMOUS Burst (8.5 s)
- seed 20: ENORMOUS Burst (16.0 s) → Jev (17.2 s)
- seed 21: ENORMOUS Burst (9.0 s) → Jev (11.5 s)
- seed 22: ENORMOUS Burst (6.5 s) → Jev (6.5 s)
- seed 23: Jev (10.5 s) → ENORMOUS Burst (13.2 s)
- seed 24: Jev (7.0 s) → ENORMOUS Burst (12.5 s)
- seed 25: ENORMOUS Burst (6.5 s) → Jev (6.5 s)
- seed 26: Jev (7.0 s) → ENORMOUS Burst (12.8 s)
- seed 27: ENORMOUS Burst (6.5 s) → Jev (12.5 s)
- seed 28: ENORMOUS Burst (4.5 s) → Jev (5.0 s)
- seed 29: ENORMOUS Burst (6.0 s) → Jev (18.0 s)
- seed 30: ENORMOUS Burst (15.0 s) → Jev (17.0 s)
- seed 31: Jev (22.0 s) → ENORMOUS Burst (26.0 s)
- seed 32: Jev (3.5 s) → ENORMOUS Burst (5.5 s)
- seed 33: Jev (8.5 s) → ENORMOUS Burst (10.0 s)

## Statistics appendix

n = 10 seed indices per game: a screen, not a decision (PROTOCOL §2.7). Win rates count ties as ½; RMST is the area under the Kaplan-Meier curve up to 60 s; rounds alive at 60 s are right-censored.

| Player | composite (all) [95% bootstrap CI over seed indices] | Booster Gauntlet: RMST s / censored / ladder | Rotorwash-Ramp: RMST s / censored / ladder | Snake Rush: RMST s / censored / ladder |
|---|---|---|---|---|
| ENORMOUS-old | 38% [31%, 44%] | 8.7 / 0 / 0.00 | 16.0 / 0 / 0.18 | 8.7 / 0 / 0.01 |
| T-dual Burst | 76% [68%, 82%] | 22.0 / 0 / 0.39 | 24.2 / 0 / 0.46 | 10.0 / 0 / 0.01 |
| T-dual K-call | 62% [53%, 72%] | 21.9 / 0 / 0.39 | 18.3 / 0 / 0.27 | 10.0 / 0 / 0.01 |
| SemIf-4B | 7% [4%, 11%] | 5.1 / 0 / 0.00 | 3.8 / 0 / 0.00 | 5.2 / 0 / 0.00 |
| ENORMOUS-CL | 62% [52%, 70%] | 19.8 / 0 / 0.30 | 17.4 / 0 / 0.23 | 11.6 / 0 / 0.04 |
| Jev | 37% [27%, 47%] | 11.8 / 0 / 0.05 | 20.1 / 0 / 0.30 | 10.1 / 0 / 0.06 |
| ENORMOUS Burst | 68% [59%, 77%] | 22.0 / 0 / 0.39 | 23.3 / 0 / 0.44 | 9.4 / 0 / 0.02 |

| Player | Booster Gauntlet: stale / expiry resets / fresh share / p50 ms | Rotorwash-Ramp: stale / expiry resets / fresh share / p50 ms | Snake Rush: stale / expiry resets / fresh share / p50 ms | inflation 3 vs 1 stream |
|---|---|---|---|---|
| ENORMOUS-old | 11 / 8 / 0.20 / 841 | 0 / 0 / 0.30 / 727 | 0 / 0 / 0.66 / 244 | 2.13× |
| T-dual Burst | 0 / 0 / 0.66 / 249 | 0 / 0 / 0.66 / 242 | 0 / 0 / 0.65 / 227 | 2.27× |
| T-dual K-call | 0 / 0 / 0.28 / 753 | 0 / 0 / 0.33 / 610 | 0 / 0 / 0.76 / 211 | 2.80× |
| SemIf-4B | 0 / 0 / 0.34 / 501 | 0 / 0 / 0.48 / 347 | 0 / 0 / 0.95 / 102 | 1.88× |
| ENORMOUS-CL | 0 / 0 / 0.30 / 702 | 0 / 0 / 0.34 / 599 | 0 / 0 / 0.82 / 209 | 2.86× |
| Jev | 0 / 0 / 0.92 / 173 | 0 / 0 / 0.79 / 209 | 0 / 0 / 0.90 / 173 | 0.99× |
| ENORMOUS Burst | 0 / 0 / 0.61 / 290 | 0 / 0 / 0.62 / 264 | 0 / 0 / 0.64 / 249 | 2.03× |

Expiry reset = the controls fell back to their safe defaults after > 1 s without an applied reply (the frozen rule for every player); it shows where latency cost the round.

| Player | In-domain training: Booster Gauntlet | In-domain training: Rotorwash-Ramp | In-domain training: Snake Rush |
|---|---|---|---|
| ENORMOUS-old | unaudited | unaudited | unaudited |
| T-dual Burst | unaudited | unaudited | unaudited |
| T-dual K-call | unaudited | unaudited | unaudited |
| SemIf-4B | unaudited | unaudited | unaudited |
| ENORMOUS-CL | unaudited | unaudited | unaudited |
| Jev | unaudited | unaudited | unaudited |
| ENORMOUS Burst | unaudited | unaudited | unaudited |

In-domain (O2) training is intended (owner D8) and informational; O3 contamination would exclude a game.
Booster Gauntlet is the less-seen probe (no-hover hoverslam, multi-phase hops, relights).

Pairwise win rates, Booster Gauntlet (row beats column):

| | ENORMOUS Burst | ENORMOUS-CL | ENORMOUS-old | Jev | SemIf-4B | T-dual Burst | T-dual K-call |
|---|---|---|---|---|---|---|---|
| ENORMOUS Burst | · | 70% | 100% | 99% | 100% | 50% | 55% |
| ENORMOUS-CL | 30% | · | 100% | 90% | 100% | 30% | 30% |
| ENORMOUS-old | 0% | 0% | · | 0% | 90% | 0% | 0% |
| Jev | 1% | 10% | 100% | · | 90% | 0% | 0% |
| SemIf-4B | 0% | 0% | 10% | 10% | · | 0% | 0% |
| T-dual Burst | 50% | 70% | 100% | 100% | 100% | · | 55% |
| T-dual K-call | 45% | 70% | 100% | 100% | 100% | 45% | · |

Pairwise win rates, Rotorwash-Ramp (row beats column):

| | ENORMOUS Burst | ENORMOUS-CL | ENORMOUS-old | Jev | SemIf-4B | T-dual Burst | T-dual K-call |
|---|---|---|---|---|---|---|---|
| ENORMOUS Burst | · | 90% | 80% | 68% | 100% | 40% | 70% |
| ENORMOUS-CL | 10% | · | 50% | 70% | 100% | 20% | 50% |
| ENORMOUS-old | 20% | 50% | · | 60% | 100% | 10% | 40% |
| Jev | 32% | 30% | 40% | · | 100% | 10% | 50% |
| SemIf-4B | 0% | 0% | 0% | 0% | · | 0% | 0% |
| T-dual Burst | 60% | 80% | 90% | 90% | 100% | · | 90% |
| T-dual K-call | 30% | 50% | 60% | 50% | 100% | 10% | · |

Pairwise win rates, Snake Rush (row beats column):

| | ENORMOUS Burst | ENORMOUS-CL | ENORMOUS-old | Jev | SemIf-4B | T-dual Burst | T-dual K-call |
|---|---|---|---|---|---|---|---|
| ENORMOUS Burst | · | 30% | 55% | 53% | 85% | 40% | 40% |
| ENORMOUS-CL | 70% | · | 65% | 90% | 85% | 60% | 70% |
| ENORMOUS-old | 45% | 35% | · | 70% | 85% | 40% | 35% |
| Jev | 47% | 10% | 30% | · | 50% | 30% | 30% |
| SemIf-4B | 15% | 15% | 15% | 50% | · | 5% | 10% |
| T-dual Burst | 60% | 40% | 60% | 70% | 95% | · | 50% |
| T-dual K-call | 60% | 30% | 65% | 70% | 90% | 50% | · |


