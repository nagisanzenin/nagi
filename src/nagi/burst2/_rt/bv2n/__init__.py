"""Burst V2-next (bv2n): one generalized machine-operating model (Machine Zoo++ + disclosed Arena game data).

Spec: docs/burst_v2_next/PLAN.md §6. Shared modules: seeds (frozen seed streams), contract (G1 observation contract),
teachers, data, zoo. Every module that emits training rows must call seeds.assert_trainable before labelling.
"""
