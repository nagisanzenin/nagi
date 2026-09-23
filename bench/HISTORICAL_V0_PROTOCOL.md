> **Benchmark correction — 2026-09-23:** The v0.2 table is historical and does not establish comparative generalist performance. The original split includes mislabeled QQP test examples and target-dependent 20NG/QQP demos passed to only some arms. A corrected evaluation is in progress in nagi-research (campaign v2). Big currently supports K≤26; larger schemas are rejected explicitly.

# Benchmark protocol

**Claim under test.** On leave-task-out typed decisions, Nagi-Smol and Nagi-Big match or beat open System One baselines (Laya, OpenJev) on accuracy and calibration while remaining in the 10–60 ms band; Nagi-Big approaches proprietary Jev.

## Split — `gold_ltout`

| Task | n | family id |
|---|---:|---|
| MRPC (paraphrase) | 500 | `ltout_mrpc` |
| DBpedia-14 (topic) | 500 | `ltout_dbpedia` |
| Amazon Polarity (sentiment) | 500 | `ltout_amazon` |
| CoLA (acceptability) | 500 | `ltout_cola` |
| 20 Newsgroups (topic) | 400 | `ltout_20ng` |
| QQP (paraphrase) | 300 | `ltout_qqp` |
| **Total** | **2700** | |

- Public NLP tasks recast as typed `choice` questions (criteria = class names).
- **Never in training** for the models evaluated here (hard leave-task-out).
- Soft targets from a teacher ensemble where available; scoring uses gold probabilities.

## Arms

| Arm | Artifact | Inference |
|---|---|---|
| Nagi-Smol | `nagisanzeninz/nagi-smol-v0` | M2′ `system_one` |
| Nagi-Big | `nagisanzeninz/nagi-big-v0` | Qwen3.5-4B + PiSSA, letter-logit softmax |
| Laya | `convaiinnovations/laya` (PyPI `laya==0.3.7`) | `agent.predict` |
| OpenJev | SemIf recipe, frozen `Qwen/Qwen3.5-4B` | letter-logit softmax, no FT |
| Jev | TypeSafe `jev-latest` | `POST /v1/systemone` |

OpenJev is *not* a single product name in the literature; we fix it to the SemIf (ex-openjev) recipe because it is the closest open, non-finetuned, closed-option baseline to Nagi-Big.

## Metrics

For each question with gold distribution *q* and prediction *p* (both normalized over the option keys):

| Name | Formula |
|---|---|
| hard | 1[argmax p = argmax q] |
| soft | ⟨p, q⟩ |
| Brier | ‖p − q‖² |
| ECE | 10-bin ECE of max(p) vs hard correctness |
| latency | wall-clock per query, batch 1, CUDA-synced |

Macro-hard (mean over the six tasks) for Nagi-Big = **0.709**; micro-hard (pooled) = **0.750**. The headline table reports micro.

## Environment

- Modal `nagi-bench5`, **NVIDIA H100**, torch 2.5.1+cu124, transformers ≥ 4.48, peft ≥ 0.14, laya 0.3.7.
- Single GPU, sequential arms (no concurrent kernels), seed 42 where sampling occurs (none in eval).
- Jev: remote API, p50 over 2698/2700 answered (2 timeouts dropped).

## Threats to validity

1. **Prompt / renderer parity.** Laya and Jev use their native question schemas; Nagi/OpenJev share `render_nagi_prompt` (definition + ≤2 demos + state + options). Gold rows have no forced demos — renderer adds a task card from `family` + instructions.
2. **Smol inference path.** `Nagi.system_one` (production API) scores 0.425 hard; the training-time harness (`DecisionDataset` + `use_schema_options`) scores 0.462 on the same weights. Gap = production path does not yet inject the B1 definition+demo block. We report the **production API** number.
3. **Jev is closed-weights and remote.** Latency includes network. Accuracy is first-party measured, not vendor-claimed.
4. **Laya calibration warning.** The `convaiinnovations/laya` checkpoint clamps invalid temperatures; ECE 0.365 is an upper bound on true miscalibration for a properly temperature-scaled Laya.
5. **Single seed / single day.** No bootstrap CIs yet; paired bootstrap is listed in REPRODUCE as future work.

## Receipts

| File | What |
|---|---|
| `results/summary.json` | all arm metrics |
| `results/*.json` | per-arm detail |
| `results/bench5.log` | full Modal job log (timestamped) |
| `scripts/modal_bench5.py` | exact runner |
