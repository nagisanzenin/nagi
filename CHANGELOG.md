# 0.6.0 — Burst mode (Nagi-ENORMOUS Burst, 2026-09-27)

- **Burst mode:** `system_one(state, questions, mode="burst")` answers every question (control) from ONE forward pass,
  one answer slot per control. Same answer shape as K-call, keyed in your question order, plus `out["burst"]` (slot
  order, its source, forwards). The default `mode="kcall"` is unchanged.
- Adds `load_enormous_burst()` for [`nagisanzeninz/Nagi-ENORMOUS-Burst`](https://huggingface.co/nagisanzeninz/Nagi-ENORMOUS-Burst)
  (Qwen3.8-27B + rank 8 LoRA, T-dual step 417), loaded BF16 with the adapter merged in place (the measured serving
  path; `merge=False` available). It refuses to load until `BURST_REVISION` is pinned, and a missing, private or
  wrongly pinned weights repo now fails fast with a clear message, before the base model is downloaded.
- Canonical control order: `control_order`, else the state's `CONTROLS (set together each tick):` line, else the
  question ids sorted by code point. Through the SDK, answers do not depend on the order in which you list the
  controls. The model itself is **not** order-invariant: rotating the order without canonicalization changes 24.8%
  [17.5%, 32.2%] of joint answers (Chord P1 REJECT-ORDER; not passed). Declare your environment's order and keep it.
- Release results (preregistered gates, H100, merged BF16, fused kernels):
  - decision latency p50 at 3 concurrent streams: 216.3 ms (Snake Rush), 247.7 ms (Rotorwash-Ramp), 196.2 ms
    (Booster Gauntlet); one-sided 97.5% upper bounds 219.5 / 269.0 / 263.6 ms;
  - non-inferior to K-call of the same weights within 0.06 on MA1 (Δ̂ −0.005, one-sided 97.5% bound −0.045);
  - Arena v3 realtime, 24 fresh seeds × 3 games: survived longer than Jev in 67.4% [57.7%, 77.0%] of head-to-heads,
    outperforming Jev overall; per game only on Booster Gauntlet (Rotorwash-Ramp and Snake Rush not significant).
- Limitations: realtime only (a compute-matched lockstep test favoured K-call); up to 4 controls evaluated; half of
  the fresh Rotorwash-Ramp rounds ended in a ceiling crash. Details in [docs/BURST.md](docs/BURST.md), the
  [model card](https://huggingface.co/nagisanzeninz/Nagi-ENORMOUS-Burst) and the
  [Burst benchmark report](bench/burst/README.md) ([page](https://nagisanzenin.github.io/nagi/burst/),
  [Game Arena](https://nagisanzenin.github.io/nagi/arena/)).
- Experimental `permutations="cyclic" | "all"` averages over slot orders at one forward per order; off by default and
  not the released configuration (the permutation-averaged variant failed its latency and order-residual gates).
- Renamed from the research name **Chord**: `mode="chord"`, `encode_chord()`, `render_chord_prompt()` and the
  `CHORD_*` constants remain as deprecated aliases (`DeprecationWarning`). Prompt strings are byte-identical to the
  trained format (golden sha256 test). `mode="burst"` on weights not trained for it (`load_enormous()`) warns.

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
