# Nagi-HUGE research release

HUGE is the third Nagi model tier (Smol, Big, Huge). It is a Gemma4 12B base plus the exact dev-selected step125 rank8 LoRA adapter. It is not a rename or replacement of Big v3. `load_big()` continues to resolve to Big v3; use `load_huge()` explicitly.

The SDK reproduces the public evaluation's unmerged adapter, pinned base, native Gemma chat template with thinking disabled, and a selected output-head projection. No decoding loop is used. Temperature1.0 is not learned calibration; probabilities can be overconfident on new domains. Inputs over4096 rendered tokens or outside2–26 choices fail explicitly instead of silently truncating.

Choice is the public suite's evaluated output type. Score/noul are exposed by the shared renderer but their quality is not established by the four-way public comparison. No CPU/MPS/quantized latency claim is made. H100 CUDA BF16 is the measured path. The base needs approximately24GB just for BF16 parameter storage, plus adapter, activations and loading overhead; a24GB GPU is not validated. CPU FP32 needs substantially more memory.

## Release evidence

The earlier synthetic publication gate was not met: policy Nagi85.83%, Jev88.33%, paired difference−2.50pp,95%CI[−5.83,+0.67]. This is a research release with that failed gate preserved, not a claim to have passed it. The new public suite is a separate, independently inspectable evaluation, not a replacement score for the old gate.

[Public benchmark](https://nagisanzenin.github.io/nagi/) · [Frozen source suite and receipts](https://github.com/nagisanzenin/nagi-research/tree/main/docs/fair_public) · [Internal gate](https://github.com/nagisanzenin/nagi-research/blob/main/docs/campaign_12b_release/REPORT.vi.md)
