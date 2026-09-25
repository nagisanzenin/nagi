# Nagi-ENORMOUS research release

> Research release by owner decision (2026-09-25). ENORMOUS **failed** its preregistered rule-reading gate; no generalization claim is made. `2e03ec38270967a95b66bc68208a5a2e1f6ba3db` must be filled with the published adapter commit, and `ENORMOUS_REVISION` pinned in `src/nagi/enormous.py`; until then `load_enormous()` raises instead of loading.

ENORMOUS is a fourth Nagi model tier (Smol, Big, Huge, Enormous). It is the Qwen3.8 27B base ([`Qwen/Qwen3.8-27B`](https://huggingface.co/Qwen/Qwen3.8-27B) at revision `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`, Apache-2.0) plus a rank8 (alpha16) LoRA adapter trained with the HUGE recipe, published as [`nagisanzeninz/Nagi-ENORMOUS`](https://huggingface.co/nagisanzeninz/Nagi-ENORMOUS) at revision `2e03ec38270967a95b66bc68208a5a2e1f6ba3db`. The base is a 64-layer, 27.8B-parameter hybrid: Gated-DeltaNet linear attention with gated full attention in 1 of every 4 layers. It does not replace Big or Huge. `load_big()` still resolves to Big v3 and `load_huge()` is unchanged; use `load_enormous()` explicitly.

The SDK reproduces the validated inference path: unmerged adapter, pinned base, BF16, eager attention, the native Qwen chat template with `enable_thinking=False` (the empty `<think></think>` block is emitted and checked), and a single forward read at the answer-letter slot through a selected output-head projection. No decoding loop is used. Temperature 1.0 is not learned calibration; probabilities can be overconfident on new domains. Inputs over 4096 rendered tokens or outside 2–26 choices fail explicitly instead of being silently truncated. Training prompts were at most 768 tokens, so inputs between 769 and 4096 tokens are accepted but fall outside the trained range and have not been validated.

Choice is the evaluated output type. Score/noul are exposed by the shared renderer, but their quality is not established by the benchmark below. No CPU/MPS/quantized latency claim is made. CUDA BF16 is the validated path. BF16 weights alone are about 56 GB, so an 80 GB GPU (H100 80GB or A100-80G) is required once adapter, activations and loading overhead are added. Smaller GPUs are not supported. CPU FP32 would need well over 110 GB of memory.

## Release evidence

### Preregistered release gate (sealed final set, ENORMOUS − HUGE)

| Gate | Criterion | Result | ENORMOUS | HUGE | Difference [95% CI] |
|---|---|---|---:|---:|---|
| G1 · S_final | ≥ +5 pp and CI lower bound > 0 | **FAIL** | 0.671 | 0.642 | +2.9 pp [−0.6, +6.5] |
| G1b · S_mech_final | ≥ 0 | **FAIL** | 0.453 | 0.463 | −1.0 pp [−10.0, +7.7] |
| G2 · counterfactual pairs | CI lower bound > −3 pp | **FAIL** | 0.219 | 0.223 | −0.3 pp [−3.8, +3.2] |
| G3 · dev_public / fair_public | CI lower bound > −2 pp | PASS | 0.869 / 0.831 | 0.819 / 0.779 | +5.0 [+1.0, +9.6] / +5.1 [+2.0, +8.4] |
| G4 · latency | P50 ≤ 200 ms at 1,024 tokens | PASS | 122 ms | — | — |
| G5 · complete data | every row scored | PASS | — | — | — |

Units: S_final 1,076, S_mech 256, counterfactual 639, dev_public 480, fair_public 4,071 (gate subsample); family-clustered bootstrap. The G4 latency is a merged-adapter, fused-kernel (Gated-DeltaNet) H100 measurement. It is not the SDK path, which keeps the adapter unmerged with eager attention and has no measured native serial latency.

The rule-reading gates failed, so the preregistered outcome was "do not release". ENORMOUS is published anyway as a research artifact by owner decision. **The claim that ENORMOUS reads unseen rules better than HUGE is not made.** Its accuracy on counterfactual rule pairs (about 22%) is the same as HUGE's.

### Public four-system benchmark (full 4,671 / common evidence 4,518)

| System | Common evidence (4,518) | Full operational (4,671) | Option-order flips (320 pairs) |
|---|---:|---:|---:|
| Nagi-ENORMOUS | 82.76% | 83.07% | not measured |
| Jev1.13.0 | 83.95% | 83.92% | 1.25% |
| Nagi-HUGE | 77.49% | 77.92% | 13.12% |
| OpenJev / SemIf | 73.87% | 74.06% | 10.62% |
| Laya | 57.35% | 57.25% | 10.94% |

| Paired comparison (common 4,518) | Difference | 95% CI | Bonferroni 98.33% CI |
|---|---:|---|---|
| ENORMOUS − Jev1.13.0 | −1.20 pp | [−2.70, +0.31] | [−3.06, +0.67] |
| ENORMOUS − HUGE | +5.27 pp | [+3.49, +7.14] | [+2.98, +7.58] |
| ENORMOUS − OpenJev / SemIf | +8.89 pp | [+7.04, +10.78] | [+6.70, +11.29] |
| ENORMOUS − Laya | +25.41 pp | [+22.81, +28.02] | [+22.35, +28.70] |

ENORMOUS and Jev1.13.0 are statistically tied on this suite. ENORMOUS is clearly ahead of HUGE. Per source, ENORMOUS trails Jev most on MMLU-Pro (65.00% vs 82.33%). Common-core calibration: NLL 0.547, Brier 0.291, ECE10 0.070. The option-rotation rows were not in the gate split, so the flip rate is not measured. Scoring reused the original fair_public functions; public subsets/adaptations, not official leaderboard scores; pretraining exposure is unknown. [Per-source results](https://github.com/nagisanzenin/nagi-research/blob/main/docs/fair_public/candidate_Nagi-ENORMOUS.md).

[Public benchmark](https://nagisanzenin.github.io/nagi/) · [HUGE release notes](HUGE_RELEASE.md)
