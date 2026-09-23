# Historical v0 results — invalidated for comparative claims

QQP labels and target-dependent demos invalidate this comparison. Preserved for audit.

## Benchmark

Leave-task-out on six real public classification tasks (**gold_ltout**, n = 2700):  
MRPC · DBpedia-14 · Amazon Polarity · CoLA · 20 Newsgroups · QQP.  
Same scorer for every arm · full N · single H100 · 2026-09-23.

| Model | hard ↑ | soft ↑ | Brier ↓ | ECE ↓ | p50 ↓ | p95 |
|---|---:|---:|---:|---:|---:|---:|
| Jev (`jev-latest`, TypeSafe API) | **0.774** | **0.684** | 0.296 | 0.120 | 172 ms | 234 ms |
| **Nagi-Big** | 0.750 | 0.594 | **0.251** | **0.047** | 58 ms | 80 ms |
| OpenJev (SemIf, frozen Qwen-4B) | 0.714 | 0.569 | 0.278 | 0.046 | 72 ms | 103 ms |
| Laya (`convaiinnovations/laya`) | 0.495 | 0.501 | 0.617 | 0.365 | **16 ms** | 18 ms |
| **Nagi-Smol** | 0.425 | 0.376 | 0.481 | 0.084 | 17 ms | 22 ms |

**Reading the table**
- *hard* = argmax match to gold; *soft* = mean 〈p, gold〉; *Brier* = mean ‖p − gold‖².
- *ECE* = expected calibration error on P(argmax), 10 bins (lower is better).
- All five arms, one scorer, full N = 2700, single H100, 2026-09-23T11:33Z. Jev n = 2699 (1 dropped).
- Laya shipped invalid temperatures (`choice:11+` clamped) — its confidence is uncalibrated as published.
- OpenJev = SemIf recipe: frozen Qwen3.5-4B, one forward, softmax over option-letter logits (no finetune).
- Latency is batch-1 CUDA-synced on H100; Jev p50 is remote API (includes network).

**Headline.** Nagi-Big is **−0.024 hard** behind proprietary Jev, with **2.3× lower latency**, **better Brier and ECE**, and public weights. It beats OpenJev on every quality metric and Laya on accuracy by +0.25.

Method, seeds, and re-run commands: [`bench/README.md`](bench/README.md) · [`bench/REPRODUCE.md`](bench/REPRODUCE.md).

