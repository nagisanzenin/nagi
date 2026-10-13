
## 1. What was measured (PREREG_V2G, sha `9691f1e6…`)

**Candidate** (`CANDIDATE.json`, status FROZEN):

| Field | Value |
|---|---|
| Core | `a24e1158…`, 3.10M parameters |
| Search config | v1b `996c2951…`, policy `G100000b1b`, τ 0.6 |
| Serving class | `cpu-m2-1t` |
| Snake policy | the SDK Snake search pack (20,000 simulations, horizon 12, no learned core) |
| Comparator S0* | 109375 |
| Harness | `2de02975` |
| Analysis | `5f471618…` |

**Order.** Each step ran once:
1. R;
2. the sealed policy runs;
3. L + I;
4. the analysis;
5. the independent audit.

**Path.** R alone chose the shipped path (§5.8): **parser**. The other path's G (PENDING) is descriptive.

## 2. Gate R: the Nagi prose reader (routes the shipped path)

| Metric | Value |
|---|---|
| Families transition-exact | 23/48 |
| π̂_R (point rule ≥ 0.95) | 0.479 |
| Clopper–Pearson lower 97.5% (rule > 0.85) | 0.333 |
| Machine-level rate | 0.490 |
| Result | **FAIL** |

- G on the prose path: not in the frozen RESULT.json (descriptive prose cell; recounted in the audit receipt) (descriptive).
- Paired prose − parser difference: not in the frozen RESULT.json (descriptive prose cell; recounted in the audit receipt).

## 3. Gate G: Zoo-Unseen-D on the shipped path

| Metric | Value |
|---|---|
| Families / domains admitted | 48 / 16 |
| θ̂_G (family-weighted; G1 ≥ 0.50) | **0.854** |
| Family t interval (95%) | [0.760, 0.948] |
| Lower 97.5%: family t / domain CR1 (G2 > 0.40) | 0.760 / 0.706 |
| Min leave-one-domain-out (G3 ≥ 0.50) | 0.844 (without bobsled_run) |
| Domain ICC | 0.58 |
| Result | **PASS** |

Leak signal (R2.5): not computed (no Zoo-Dev-L input).

## 4. Claims (Holm family {G+, NS}, α = 0.025, parser path; never gates)

| Claim (Holm family, α 0.025) | Estimate | p_claim | Holm level | Holm-matched lower (family / domain) | Result |
|---|---|---|---|---|---|
| G+ (learning adds to search, same latency cap) | -0.003 | 1.000 | 0.025 | -0.009 / -0.011 | not rejected (no claim) |
| NS (θ > 0.60) | 0.854 | 0.001 | 0.0125 | 0.746 / 0.681 | rejected (claim holds) |

- **G+.** We could not show that the learned core adds to the same lookahead on unseen machines: Δ̂+ = -0.003 (p_claim 1.000; Holm not rejected). We therefore do not claim that learning generalizes to unseen machines.
- **NS.** The Zoo-Unseen-D mean is above 0.60 under the preregistered test (θ̂ = 0.854; Holm-matched lower bounds: family 0.746, domain 0.681). This is not north-star attainment: the lookahead covers much or all of the reachable states of these small machines (C8 coverage).
- Nominal 97.5% family lower bounds: G+ -0.009; NS 0.760.

## 5. C8: search coverage (mandatory next to every G, G+ and NS number)

| Statistic | Value |
|---|---|
| Scored machines / decisions | 96 / 46,966 |
| Reachable states, min / p25 / median / p75 / max | 72 / 380 / 922 / 2,238 / 25,921 |
| Share of machines with \|R\| ≤ 1,000 / ≤ 20,000 | 52.1% / 95.8% |
| Decisions where the search exhausted the tree | 24.9% |
| High-coverage decisions (exhausted, or saw ≥ 50% of the machine) | 48.3% |
| Low-coverage families / domains, θ̂ (descriptive) | 14 / 9, 0.730 |

On unseen machines, V2G's success comes mainly from exact lookahead on the given rules, which on small machines covers much or all of the reachable state set.

- "Learning generalizes to unseen machines" is claimed only through G+.
- No full-set number is presented as north-star attainment.
- The serving class is `cpu-m2-1t`, so the 1-core convention is this run itself.

## 6. Gate A: Arena vs Nagi Burst V1 (24 sealed seeds per game; seen tasks)

| Game | n | V2 mean | Nagi Burst V1 mean | wins / ties / losses | W | t lower 97.5% | sign-flip p | gate A |
|---|---|---|---|---|---|---|---|---|
| Snake Rush | 24 | 50.7 s | 12.6 s | 24 / 0 / 0 | 1.000 | 1.000 | 6.0e-08 | **PASS** |
| Rotorwash-Ramp | 24 | 1.05 | 0.35 | 24 / 0 / 0 | 1.000 | 1.000 | 6.0e-08 | **PASS** |
| Booster Gauntlet | 24 | 0.96 | 0.00 | 23 / 1 / 0 | 0.979 | 0.936 | 1.2e-07 | **PASS** |

| Item | Value |
|---|---|
| Booster landings (V1 lands 0; PASS needs ≥ 6) | 23/24 |
| Snake policy | `v2g-sdk:snake` |
| RR policy | `v2g-multi:rr` |
| Booster policy | `v2g-multi:booster` |
| Exact replay from recorded controls | 72/72 (PASS) |

## 7. Gate L (latency) and gate I (interface)

| Population | n | p50 | p95 | p95 upper 95% bound (gate ≤ 200 ms) | p99 (reported) | share > 250 ms |
|---|---|---|---|---|---|---|
| Zoo-Unseen-D | 2000 | 9.6 ms | 41.1 ms | 41.8 ms | 44.5 ms | 0.00% |
| Snake Rush | 2000 | 0.8 ms | 38.0 ms | 50.8 ms | 194.6 ms | 0.05% |
| Rotorwash-Ramp | 2000 | 0.4 ms | 0.5 ms | 0.5 ms | 0.6 ms | 0.00% |
| Booster Gauntlet | 1506 | 0.5 ms | 0.6 ms | 0.7 ms | 0.8 ms | 0.00% |

**Gate L**

| Item | Value |
|---|---|
| Hardware | Apple M2 (cpu-m2-1t), native arm64, 1 thread |
| Load, start → end (≤ 3.0 required) | 2.58 → 2.48 |
| Invalid reasons | none |
| Result | **PASS** |

**Gate I**

| Item | Value |
|---|---|
| Mismatches | 0 of 7,506 requests |
| Round-trip failures | 0 |
| Mismatch rate, 95% upper bound | 0.040% |
| Result | **PASS** |

## 8. What would refute us (PREREG §9), checked

| Refutation | Observed |
|---|---|
| G fails while A passes: the games bought skill without generality | G PASS; A PASS / PASS / PASS |
| Δ̂+ ≤ 0: learning added nothing over search | Δ̂+ = -0.003 |
| R passes but G_prose − G_parser < −0.05 | R FAIL; prose − parser not in the frozen RESULT.json (descriptive prose cell; recounted in the audit receipt) |

## 9. Budget (actual vs reservation, separated)

| Item | Value |
|---|---|
| Billed (finalized provider bills) | $0.20 |
| Reservation still held | $0.00 |
| Cap (cloud authorization #4) | $3.00 |
| All V2-general cloud spend (sum of the closed ledgers, billed) | $25.16 |

## 10. Disclosures carried into every public text

- The C8.3 sentence.
- The core was trained on these 3 Arena games.
- Zoo-Unseen-D was written by Claude Opus agents, separate from the training authors.
- The prose reader is deferred to V2.1, and its R result is reported.
- The only comparator is Nagi Burst V1 (gate A); no other system is compared.
- A Booster round is its first hop.
- Arena play used the nominal 1-tick reply, justified by gate L.
