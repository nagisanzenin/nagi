# Benchmark v2

The v0 benchmark is invalidated for comparative claims: QQP used hidden test labels
and 700 rows contained target-dependent demos. Preserve the [historical protocol](HISTORICAL_V0_PROTOCOL.md)
and receipts for audit; do not use its quality or speed headline.

## Protocol

- Development: repaired six-task suite, 2,152 rows; calibration: 537 disjoint rows.
- Final public holdout: RTE 277, WiC 300, CB 56; novel holdout: four executable rule families, 320 rows.
- Additional contracts: 160 score/noul rows; 80 high-K lookup rows at K=32/77.
- All arms receive the same state/questions; no evaluation gold or demos enter inference.
- Full-option distributions are validated. Report coverage and failures-as-wrong accuracy alongside valid-only results.
- Hard-label Brier/NLL, 10-bin ECE, macro/micro accuracy; temperature fit on calibration only.
- Paired bootstrap by item within task and bootstrap by task. Development selects candidates; final does not.
- Final latency uses batch 1, H100 local inference including rendering/tokenization/transfer, and JEV HTTP calls from the same worker.
  Remote JEV latency includes network; server hardware and raw logits are unknown.
- Public data is held out from Nagi finetuning, not guaranteed unseen by either model's pretraining.

## SDK scope

Smol honors the checkpoint's schema renderer setting. Big verifies distinct one-token
symbols and rejects K>26 by default instead of silently dropping options. The optional
K≤78 path is experimental; lookup accuracy does not establish high-K reasoning quality.

Final evaluation completed; results below.

## Completed campaign v2 — 2026-09-23

Selected G-clean before final. **Did not beat JEV.** All listed arms have 100% public/novel coverage.

| Model | Public macro (633) | Novel macro (320) | Public p50 ms |
|---|---:|---:|---:|
| Nagi Big v2 candidate | 76.73% | 63.13% | 40.65 |
| Nagi Big v0 | 73.47% | 48.75% | 43.06 |
| Frozen Qwen native-chat | 75.68% | 45.00% | 43.70 |
| Smol supervised pilot | 50.70% | 41.87% | 16.72 |
| Smol KD pilot | 56.92% | 35.63% | 16.70 |
| Laya | 73.39% | 39.06% | 11.49 |
| JEV 1.13.0 | 81.36% | 99.38% | 370.20 |

Paired macro delta vs JEV: public −4.64 points (95% within-task CI −9.36 to +0.25), novel −36.25 points (−41.56 to −31.25). Public has only three tasks; novel has four rule families. JEV latency includes HTTP/network; local arms use one H100. These are measurement-origin latencies, not equal-hardware kernel comparisons.

Candidate archive is private: https://huggingface.co/nagisanzeninz/nagi-big-v2-g-clean-20260923. Public load defaults still point to v0. SDK/research parity passed on actual GPU weights. High-K extension achieved 95% on 80 lookup contracts, is experimental, and does not establish broad high-K reasoning.

See [v0 versus v2 comparison and trade-offs](V2_COMPARISON.md). The candidate improves novel rules but regresses on the score/noul aggregate.
