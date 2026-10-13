# Make your own machine families

This folder is the factory that produced the Machine Zoo families used to train and test Nagi Burst V2: the family
gate, the independent blind checker, the review tool and the job workflow that lets many authors (people or coding
agents) work in parallel. With it you can build your own machines with **exact** optimal labels, for training data
or for an evaluation set of your own.

## What a family is

A family is one Python file with:

- `FAMILY`: name, domain, title, story, and the **strata** it claims (`delay`, `hidden`, `long`, `interlock`,
  `axes3`, `budget`, `multibudget`);
- `PARAMS`: a small integer grid (2-5 parameters, 8-64 points); each grid point is one machine instance;
- `build(p)`: returns the instance as a program in the Nagi machine language (mz-1 / mz-1x,
  [docs/DSL_REFERENCE.md](../../docs/DSL_REFERENCE.md));
- `prose(p)`: the same rules written in plain words, the way an operator would explain the machine.

Start from [`examples/family_template.py`](examples/family_template.py) (the smallest passing family, commented)
and [`examples/example_dock_cart.py`](examples/example_dock_cart.py) (a mode selector, three controls, two
budgets).

## How labels stay exact

Labels are never written by hand or sampled. For every instance the exact teacher (the engine under
`src/nagi/burst2/_rt/`) enumerates the reachable state set (including the reply-delay queue and, for hidden
variables, every view of the last H observations), solves the values exactly (policy iteration with sparse direct
solves) and returns the acceptable actions of every state. The gate checks the teacher against an independently
written blind checker (X6) and measures every success rate as an exact 100-tick probability, with no Monte Carlo.

## The gate

`validate.py` runs these checks on each instance in a fixed order and admits the family when at least 6 instances
pass with distinct machines. Full definitions and the prose rules are in [GATES.md](GATES.md).

| Check | What it guarantees |
|---|---|
| V0 | Safe module: allowed imports only, no I/O or dynamic code, valid `FAMILY` / `PARAMS` |
| X0, X1, G2-G8, X3-X5 | Frozen mz-1x gates: valid program, size limits, every control matters, no dead rules, hidden state identifiable |
| V1, V2 | The rulebook text round-trips exactly; `build` and `prose` are deterministic |
| V3 | The exact oracle succeeds >= 0.95 |
| V4 | Not trivial: doing nothing <= 0.20, greedy <= 0.80, random <= 0.50, 4-tick look-ahead probe <= 0.80 |
| V5 | Every claimed stratum is load-bearing, verified by execution (a probe blind to it loses >= 0.20 success or >= 10 return) |
| V6 | <= 24 rules, rulebook <= 3,200 chars, <= 120 s per instance |
| P1, P2 | Prose is not the DSL in disguise (the exact parser rejects it) and states every identifier and number |
| X6 | The exact teacher equals the blind checker on states, values, action sets, beliefs and oracle success |
| V7 | Not a near-duplicate of any indexed family (signature, structural WL similarity < 0.60, prose 5-gram twin < 0.35) |

Thresholds, instance salts and the engine are identical to the research gate (`v2g-famgate-v1`); the gate version
string is `machine-zoo-factory-v1 (= v2g-famgate-v1 thresholds)`. The near-duplicate index contains only what you
give it: your job's passed families, the bundled `examples/`, and any `--index-dir` (for example the published
Machine Zoo family files). The last step is human, or an agent other than the author: a blind reviewer rebuilds the
program from the prose alone and `prose_check.py` must print `EXACT`.

## Quickstart

Requirements: Python >= 3.10, `numpy`, `scipy` (and `pytest` for the tests). Run from a clone of this repository;
the tool puts `src/` on the path itself and never imports torch. CPU only.

```bash
cd tools/machine_zoo_factory
export OMP_NUM_THREADS=2

# 1. the example passes the full gate (writes /tmp/mzf-demo/REPORTS/example_dock_cart.json)
python3 validate.py examples/example_dock_cart.py --job /tmp/mzf-demo
#    ... kept 10 (need 6); instance failures {}; X6 True; V7 sig_hits=0 max_wl_sim=0.1053 max_prose_twin=0.029
#    FAMILY PASS example_dock_cart failed=[] (...)

# 2. a reviewer's reading of the prose is transition-exact
python3 prose_check.py examples/example_dock_cart.py examples/example_dock_cart.reading.txt
#    EXACT params={"dock": 9, "lowb": 0, "near": 2}

# 3. a job of your own
python3 make_batches.py --job ~/mzf-job --domains examples/domains_example.txt --salt my-split-v1   # + FAMILIES/
cp examples/family_template.py ~/mzf-job/FAMILIES/<your_name>.py   # then replace the machine (see GENERATE.md)
python3 validate.py ~/mzf-job/FAMILIES/<your_name>.py --no-x6      # draft run
python3 validate.py ~/mzf-job/FAMILIES/<your_name>.py              # full run: the only PASS that counts
python3 status.py --job ~/mzf-job                                   # progress; --manifest writes MANIFEST.json

# tests (offline, under a minute on one CPU)
python3 -m pytest -q tests
```

[GENERATE.md](GENERATE.md) is the job manual: slot plans, atomic claims, the draft and full gate loop, the blind
review and its receipt, and copy-paste prompts for running coding agents (Claude Code, Codex, or any agent with a
shell) as parallel authors and reviewers.

## Files

| Path | Role |
|---|---|
| `validate.py` | gate CLI: one family -> `REPORTS/<name>.json`, exit 0 on PASS |
| `prose_check.py` | blind sufficiency check: reviewer's reading vs the family program |
| `make_batches.py` | domain list -> `BATCHES/batches.txt` (train / dev split, slot plans) |
| `status.py` | job progress, claims, reviews, manifest |
| `famgate/core.py` | the gate (V0-V7, P1, P2) |
| `famgate/xgates.py`, `famgate/x6.py`, `famgate/blind/` | frozen mz-1x gates, X6, the independent blind checkers |
| `famgate/_runtime.py`, `famgate/jobkit.py` | engine wiring, job folder layout |
| `examples/` | example family, template, an exact reading, an example domain list |
| `tests/` | offline tests |

## License

Apache-2.0, like the rest of this repository (see [LICENSE](../../LICENSE)).

NOTICE: Nagi Machine Zoo family factory. Copyright 2026 Nagisanzenin. Licensed under the Apache
License, Version 2.0. It uses the Nagi Burst V2 runtime vendored under `src/nagi/burst2/_rt/` (same license).
