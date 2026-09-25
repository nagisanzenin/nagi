# Nagi-ENORMOUS 27B release

> Released 2026-09-25 on the strength of Arena Live (first place vs Jev, OpenJev, Laya). `2e03ec38270967a95b66bc68208a5a2e1f6ba3db` must be filled with the published adapter commit, and `ENORMOUS_REVISION` pinned in `src/nagi/enormous.py`; until then `load_enormous()` raises instead of loading.

ENORMOUS is a fourth Nagi model tier (Smol, Big, Huge, Enormous). It is the Qwen3.8 27B base ([`Qwen/Qwen3.8-27B`](https://huggingface.co/Qwen/Qwen3.8-27B) at revision `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`, Apache-2.0) plus a rank8 (alpha16) LoRA adapter trained with the HUGE recipe, published as [`nagisanzeninz/Nagi-ENORMOUS`](https://huggingface.co/nagisanzeninz/Nagi-ENORMOUS) at revision `2e03ec38270967a95b66bc68208a5a2e1f6ba3db`. The base is a 64-layer, 27.8B-parameter hybrid: Gated-DeltaNet linear attention with gated full attention in 1 of every 4 layers. It does not replace Big or Huge. `load_big()` still resolves to Big v3 and `load_huge()` is unchanged; use `load_enormous()` explicitly.

The SDK reproduces the validated inference path: unmerged adapter, pinned base, BF16, eager attention, the native Qwen chat template with `enable_thinking=False` (the empty `<think></think>` block is emitted and checked), and a single forward read at the answer-letter slot through a selected output-head projection. No decoding loop is used. Temperature 1.0 is not learned calibration; probabilities can be overconfident on new domains. Inputs over 4096 rendered tokens or outside 2–26 choices fail explicitly instead of being silently truncated. Training prompts were at most 768 tokens, so inputs between 769 and 4096 tokens are accepted but fall outside the trained range and have not been validated.

Choice is the evaluated output type. Score/noul are exposed by the shared renderer, but their quality is not established by the benchmark below. No CPU/MPS/quantized latency claim is made. CUDA BF16 is the validated path. BF16 weights alone are about 56 GB, so an 80 GB GPU (H100 80GB or A100-80G) is required once adapter, activations and loading overhead are added. Smaller GPUs are not supported. CPU FP32 would need well over 110 GB of memory.

## Release evidence

### Internal new-rule reading test

On our sealed internal test of reading brand-new rules, ENORMOUS is on par with HUGE (S_final +2.9 pp [−0.6, +6.5]; counterfactual rule pairs −0.3 pp [−3.8, +3.2]). Public four-system suite: +5.1 pp over HUGE. Decision latency P50 122 ms at 1,024 tokens (H100, fused kernels, merged adapter).
