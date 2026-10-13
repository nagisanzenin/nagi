"""Machine Zoo -> Burst text/chord rows (lane zoo-render, docs/burst_v2_next/lanes/zoo-render.md).

split   frozen held-out split (docs/burst_v2_next/zoo_split.json); `assert_trainable` guards every row
render  Zoo machine + state -> Burst chord request text; parser; exact per-slot targets (R2.13 / R1.13)
rows    state sampler + training rows (train families only)
eval    Zoo-Unseen closed-loop evaluator for any text policy callable(request_text) -> joint
"""
