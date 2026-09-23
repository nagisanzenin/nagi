# Research receipt — 5-way typed-decision benchmark

| Field | Value |
|---|---|
| UTC | 2026-09-23T11:33:56Z |
| Runner | `scripts/modal_bench5.py` |
| SHA256(runner) | `d2522362cf64cf733590abb1455de527fb9b6229a9189c1a748c89441de17e92` |
| Split | `gold_ltout` n=2700 (Jev answered 2699) |
| GPU | NVIDIA H100 (Modal app `nagi-bench5`, tag `b5`) |
| Pins | torch 2.5.1+cu124 · transformers≥4.48 · peft≥0.14 · laya 0.3.7 · py3.11 |
| Artifacts | `summary.json` `*.json` `bench5.log` `SHA256SUMS` |

## Verdict (pre-registered axes: accuracy, calibration, latency)

1. **Nagi-Big vs Jev:** hard −0.024 (0.750 vs 0.774) · Brier **better** (0.251 vs 0.296) · ECE **better** (0.047 vs 0.120) · p50 **2.3× faster** (58 vs 172 ms) · weights public vs closed.
2. **Nagi-Big vs OpenJev:** +0.036 hard, +0.025 soft, better Brier, faster — finetune (PiSSA) > frozen letter-logits.
3. **Nagi-Smol vs Laya:** similar latency (17 vs 16 ms); Smol loses hard (0.425 vs 0.495) on this LTO set but wins Brier and ECE by a wide margin (0.481/0.084 vs 0.617/0.365). Laya’s published checkpoint is uncalibrated (invalid temperatures).
4. **Not claimed:** universal superiority; multi-lingual (Laya router untested here); domain-FT numbers (Banking77 0.942) are a separate protocol.

## Deviations (disclosed)

- Production `system_one` (Smol) does not inject the B1 definition+demo block that the training harness used → 0.425 vs 0.462 harness. Number reported = production API.
- Jev latency is remote API (network included).
- Macro-hard for Nagi-Big on the six tasks = 0.709; micro (pooled) = 0.750 (headline).
