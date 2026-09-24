# 0.4.0 — Nagi-HUGE research release

- Adds `load_huge()` for the pinned Gemma4 12B + rank8 LoRA checkpoint, the third model tier alongside Smol and Big.
- Uses the exact one-forward public benchmark readout. Explicit input limits; no silent truncation or chain-of-thought generation.
- Adds a four-system public benchmark, source/coverage audit and interactive GitHub Pages report.
- Preserves Big v3 defaults and the earlier failed synthetic release gate. No universal Jev-superiority claim.

# Changelog

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
