# 0.5.0 — Nagi-ENORMOUS 27B (2026-09-25)

- Adds `load_enormous()` for the pinned Qwen3.8 27B (hybrid Gated-DeltaNet + gated full attention) + rank8 LoRA checkpoint, a fourth tier alongside Smol, Big and Huge.
- Same one-forward letter-slot readout as HUGE: unmerged adapter, BF16, eager attention, chat template with thinking disabled. Explicit 4096-token cap, no silent truncation; inputs over 768 tokens are outside the trained range.
- Needs an 80 GB GPU (~56 GB BF16 weights). `load_enormous()` refuses to run until `ENORMOUS_REVISION` is pinned to the published adapter commit.
- Public four-system suite: 83.07% full operational / 82.76% common evidence; ENORMOUS−Jev1.13.0 −1.20 pp [−2.70, +0.31] (tied), ENORMOUS−HUGE +5.27 pp [+3.49, +7.14]. Option-order flip rate not measured.
- Released on the strength of Arena Live: first place against Jev, OpenJev and Laya (83/90 points, 23/30 rounds). Limitation: no improvement over HUGE yet on our internal new-rule reading test.
- README now covers all four model lines (SMOL, BIG, HUGE, ENORMOUS) and the Arena Live real-time games.
- `load_big()` and `load_huge()` are unchanged.

# 0.4.0 — Nagi-HUGE research release

- Adds `load_huge()` for the pinned Gemma4 12B + rank8 LoRA checkpoint, the third model tier alongside Smol and Big.
- Uses the exact one-forward public benchmark readout. Explicit input limits; no silent truncation or chain-of-thought generation.
- Adds a four-system public benchmark, source/coverage audit and interactive GitHub Pages report.
- Preserves Big v3 defaults and the earlier failed synthetic release gate. No universal Jev-superiority claim.

# Changelog

## 0.4.1

- Raise Big default prompt cap to4096 and expose `max_input_tokens`; use768 to reproduce the prior benchmark.
- Add Smol opt-in `max_state_tokens` and `dynamic_state_padding`; keep512 default after inconclusive/weak long retrieval results.
- Document224 paired H100 context probes, latency trade-offs and unchanged model weights.


## 0.2.1

- Fix Smol train/serve schema rendering and strictly validate checkpoint weights.
- Preserve Big option schemas when trimming state; reject unsupported option counts
  and verify that output symbols map to distinct single tokens.
- Add explicit base revision, temperature, chat-template and experimental high-K controls.
- Fix installation instructions, clone directory, undefined example variables and
  the documented answer shape. Add complete choice/score/noul examples.
- Require the dependency family used for the current backbones; add isolated install
  validation, executable documentation checks and a unit-test CI workflow.
- Replace invalid historical comparison claims with clean v2 results and trade-offs.

Public model defaults remain v0. The private Big G-clean candidate is a separate
checkpoint, not an automatic model upgrade in SDK 0.2.1.
