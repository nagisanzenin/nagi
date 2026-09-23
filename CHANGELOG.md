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
