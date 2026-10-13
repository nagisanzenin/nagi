"""Burst V2 showcase labels (lane LABELS): latency-aware, observation-consistent soft-Q chord labels for the Arena v3.1
showcase games (Booster Gauntlet g1.2 / K3, Rotorwash-Ramp v3.1 / K3-RR). CPU only. Spec: docs/burst_v2/LABELS.md.

Modules: seeds (train seed stream, disjoint from every Arena schedule seed), latency (served reply-latency histogram +
runner-exact emulator), labels (Q-bar, tie-aware max-marginal targets), prompt (served Burst chord prompt + encoding),
booster / rr (game adapters: belief sampler, joint Q, planners), generate (rollouts -> rows), validate, dagger.
"""
