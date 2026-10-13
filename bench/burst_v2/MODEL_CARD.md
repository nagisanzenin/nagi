---
license: apache-2.0
library_name: nagi-decisions
tags:
- decision-making
- planning
- lookahead
- control
- nagi
---

# Nagi Burst V2

Nagi Burst V2 is a small decision core (**3.10M parameters**, numpy, CPU) combined with **exact lookahead
on the rules you give it**. You describe a machine in the Nagi machine language (mz-1 / mz-1x: integer variables, up
to 3 controls with 3 options each, rules, crash conditions and a goal). The SDK reads the rules with an exact parser
and returns a typed decision: a choice per control and its probabilities, within 200 ms per decision on one CPU
thread.

> **What the result means.** On unseen machines, V2G's success comes mainly from exact lookahead on the given rules, which on small machines covers much or all of the reachable state set. We could not show that the learned core adds to the same lookahead on unseen machines: Δ̂+ = -0.003 (p_claim 1.000; Holm not rejected). We therefore do not claim that learning generalizes to unseen machines.

| | |
|---|---|
| Weights | `model.npz` (sha256 `a24e1158b00a59ad1fc103001c301981aa94da033e59fcee7b645ae2deef5624`), 3.10M parameters, numpy only |
| Lookahead | exact search on the parsed rules: 100,000 simulations per decision, horizon up to 40, belief tracking for delayed and hidden variables (config v1b, sha `996c2951…`) |
| How the core is used | inside the search's exact tie set only, when its confidence is ≥ τ = 0.6 (policy `G100000b1b`) |
| Serving hardware for every number below | Apple M2 (cpu-m2-1t), native arm64, 1 thread |
| SDK | `nagi-decisions` 0.7.0, module `nagi.burst2` |
| Preregistration | PREREG_V2G (sha `9691f1e6…`): one frozen evaluation, gates fixed before any data |

## Use

```python
from nagi.burst2 import load_core, operate

core = load_core()  # downloads model.npz from huggingface.co/nagisanzeninz/Nagi-Burst-V2 (pinned revision) and checks its sha256

RULES = """machine mz-1
vars:
  x in [0, 6], start {3}, out of range: clamp
controls:
  @m: DEC -1, KEEP 0, INC 1
random $w: none
rules (in order, each tick):
  1. x := x + @m
crash if any holds:
  1. all(x <= -1)
goal: all(x == 6)
"""

# The released configuration. The SDK applies these values by default; they are shown here so the call is explicit.
FROZEN = {"core": core, "tau": 0.6, "belief": "v1b", "max_sims": 100_000}

out = operate(RULES, {"x": 3}, {**FROZEN, "session": "episode-1", "step": 0})
out["choice"]               # {"m": "inc"}: one option per control
out["probabilities"]        # per-control marginals over dec / keep / inc
out["joint_probabilities"]  # over joint indices: uniform on the search's exact tie set, or the gated core prior inside it
out["stats"]                # sims, depth, gated, total_ms, ...
```

- **Signature.** `operate(rules_text, state, options)` takes the rules text plus a structured state. For mz-1, the
  state is `{var: value}`. For mz-1x, it is `{"obs": [...], "dec": [...]}`, the observation and decision windows.
  `operate(request_text)` takes one served request instead: rules, window and slots in a single text.
  `operate_structured(program, view)` is the same decision without text.
- **Purity.** Every call is self-contained. A decision is a pure function of the request bytes and the options.
- **Replaying a choice.** Inside the exact tie set, the choice is drawn from `probabilities`. Pass `session` and
  increase `step` on every decision to make the draw replayable. Without a session or seed, the draw uses fresh
  entropy and `stats["replayable"]` is `False`.
- **Arena games.** Snake Rush, Rotorwash-Ramp and Booster Gauntlet requests are recognised and routed to their game
  policies.

## Results: one frozen, preregistered evaluation (M4)

Everything below comes from a single look at sealed sets, through the SDK text path, on Apple M2 (cpu-m2-1t), native arm64, 1 thread, with an
independent recount (audit: **MATCH**). Release decision: **RELEASE** (path: parser).

| Gate | Result | Evidence (one look, sealed) |
|---|---|---|
| R (reader, routes the path) | **FAIL** | 23/48 families transition-exact, π̂ 0.479, CP lower 0.333 → path **parser** |
| A Snake vs Nagi Burst V1 | **PASS** | W 1.000, t lower 1.000, p 6.0e-08 |
| A Rotorwash-Ramp vs Nagi Burst V1 | **PASS** | W 1.000, t lower 1.000, p 6.0e-08 |
| A Booster vs Nagi Burst V1 | **PASS** | W 0.979, landings 23/24, p 1.2e-07 |
| G (parser path) | **PASS** | θ̂ 0.854, family lower 0.760, domain lower 0.706, LODO min 0.844 (48 families / 16 domains) |
| L (p95 ≤ 200 ms) | **PASS** | largest p95 upper bound 50.8 ms (Snake Rush); invalid: none |
| I (text = structured) | **PASS** | 0 mismatches / 7,506 |
| Independent audit | **MATCH** | AUDIT_M4.md recount (RUNBOOK_M4 §8) |
| **Decision** | **RELEASE** | PREREG_V2G §9 |

### Unseen machines (Zoo-Unseen-D, gate G)

Zoo-Unseen-D has 48 machine families in 16 domains. No family, domain or rulebook was seen in
training. Each family contributes 2 machines × 16 episodes, each capped at 100 ticks.

| Metric | Value |
|---|---|
| Family-weighted success θ̂ | **0.854** |
| Family t 95% interval | [0.760, 0.948] |
| Lower 97.5% bound (family / domain-cluster) | 0.760 / 0.706 (guard 0.40) |
| Worst leave-one-domain-out mean | 0.844 (without bobsled_run) |

**How much of this is lookahead (C8, mandatory).** The scored machines have 922 reachable states at
the median (min / p25 / median / p75 / max: 72 / 380 / 922 / 2,238 / 25,921). Of them, 52.1% have ≤ 1,000 states
and 95.8% have ≤ 20,000. In 24.9% of 46,966 decisions, the search exhausted
the reachable tree. 48.3% of decisions saw at least half of the machine. On the 14 low-coverage
families, the mean is 0.730 (descriptive).

| Claim (Holm family, α 0.025) | Estimate | p_claim | Holm level | Holm-matched lower (family / domain) | Result |
|---|---|---|---|---|---|
| G+ (learning adds to search, same latency cap) | -0.003 | 1.000 | 0.025 | -0.009 / -0.011 | not rejected (no claim) |
| NS (θ > 0.60) | 0.854 | 0.001 | 0.0125 | 0.746 / 0.681 | rejected (claim holds) |

- We could not show that the learned core adds to the same lookahead on unseen machines: Δ̂+ = -0.003 (p_claim 1.000; Holm not rejected). We therefore do not claim that learning generalizes to unseen machines.
- The Zoo-Unseen-D mean is above 0.60 under the preregistered test (θ̂ = 0.854; Holm-matched lower bounds: family 0.746, domain 0.681). This is not north-star attainment: the lookahead covers much or all of the reachable states of these small machines (C8 coverage).

### Arena games vs Nagi Burst V1, gate A

The games are Snake Rush, Rotorwash-Ramp and Booster Gauntlet. The seed indices are sealed and were never used in
training or selection: 24 per game. Nagi Burst V1 is the released 27B Nagi-ENORMOUS-Burst. It is scored from its
pinned evaluation records.

| Game | n | V2 mean | Nagi Burst V1 mean | wins / ties / losses | W | t lower 97.5% | sign-flip p | gate A |
|---|---|---|---|---|---|---|---|---|
| Snake Rush | 24 | 50.7 s | 12.6 s | 24 / 0 / 0 | 1.000 | 1.000 | 6.0e-08 | **PASS** |
| Rotorwash-Ramp | 24 | 1.05 | 0.35 | 24 / 0 / 0 | 1.000 | 1.000 | 6.0e-08 | **PASS** |
| Booster Gauntlet | 24 | 0.96 | 0.00 | 23 / 1 / 0 | 0.979 | 0.936 | 1.2e-07 | **PASS** |

- Booster: 23/24 seeds landed. V1 never lands on these seeds.
- Every round replays exactly from its recorded controls (72/72). The replays are published with the
  [replay data](https://github.com/nagisanzenin/nagi/blob/main/bench/burst_v2/receipts/arena_v2.json).

### Latency (gate L)

Measured on Apple M2 (cpu-m2-1t), native arm64, 1 thread: one process, one thread, uncached. The timing covers parsing, every core forward, the
search and the draw.

| Population | n | p50 | p95 | p95 upper 95% bound (gate ≤ 200 ms) | p99 (reported) | share > 250 ms |
|---|---|---|---|---|---|---|
| Zoo-Unseen-D | 2000 | 9.6 ms | 41.1 ms | 41.8 ms | 44.5 ms | 0.00% |
| Snake Rush | 2000 | 0.8 ms | 38.0 ms | 50.8 ms | 194.6 ms | 0.05% |
| Rotorwash-Ramp | 2000 | 0.4 ms | 0.5 ms | 0.5 ms | 0.6 ms | 0.00% |
| Booster Gauntlet | 1506 | 0.5 ms | 0.6 ms | 0.7 ms | 0.8 ms | 0.00% |

Gate I: the text path and the structured path gave identical probability vectors and drawn joints on 7,506 requests
(0 mismatches; 95% upper bound on the mismatch rate 0.040%).

## Intended use

- Fast, typed decisions for small discrete machines that you can write down exactly: integer state, ≤ 3 controls
  with DEC / KEEP / INC options, and a crash condition and a goal per machine.
- Research on fast decision models, and a baseline for "lookahead on given rules" vs learned priors.

## Limitations (read before use)

- **Your machine must be expressible in mz-1 / mz-1x.** That means ≤ 10 integer variables (each range ≤ 401
  values), ≤ 3 controls with 3 options each (27 joint actions), ≤ 24 ordered rules, an optional small random input,
  ≤ 8 crash conditions, one goal, and episodes ≤ 100 ticks. mz-1x adds a reply delay of 0–2 ticks, hidden variables
  that history reveals, and a history window ≤ 6. Anything outside this language is out of scope. The parser rejects
  invalid programs instead of guessing. The language is defined in
  [DSL_REFERENCE.md](https://github.com/nagisanzenin/nagi/blob/v0.7.0/docs/DSL_REFERENCE.md), and
  [QUICKSTART_MACHINE.md](https://github.com/nagisanzenin/nagi/blob/v0.7.0/docs/QUICKSTART_MACHINE.md) walks
  through writing a machine.
- **Prose rules are not supported in this release.** The Nagi prose reader translated 23/48 sealed rulebooks
  transition-exactly (π̂ 0.479, CP lower bound 0.333). That is below its gate (≥ 0.95), so V2 ships the
  exact parser and the reader moves to V2.1. Its success on the same machines from prose was not in the frozen RESULT.json (descriptive prose cell; recounted in the audit receipt)
  (descriptive).
- **Lookahead does most of the work on small machines** (C8 above). Large or long-horizon machines get less coverage
  within 100,000 simulations. Do not read the D mean as north-star attainment.
- **Latency holds on the stated hardware only:** Apple M2 (cpu-m2-1t), native arm64, 1 thread, single thread. Other CPUs are not measured. The p99
  is reported, not gated.
- **The three Arena games are seen tasks.** The core was trained on Snake Rush, Rotorwash-Ramp and Booster Gauntlet
  data (teacher labels plus DAgger), so the Arena results measure skill on known games, not generalization. On Snake,
  the released policy is the SDK Snake search pack (20,000 simulations, horizon 12, no learned core). On Rotorwash-Ramp and Booster Gauntlet, the core's game head acts once per
  tick, without lookahead. Arena rounds were played with a 1-tick reply (the decision for tick t applies at t + 1),
  justified by gate L. A Booster round is its first hop, scored by K3 Y.
- **Who wrote the test machines.** The Zoo-Unseen-D families and rulebooks were written by Claude Opus agents that
  were separate from the training authors, then checked by blind reviewers and an exact oracle. Training machines were
  also written by agents (Claude Opus, GPT and a grammar generator). Shared author style is a possible confound,
  disclosed in the report.
- **The only comparator is Nagi Burst V1.** Gate A compares V2 with V1's pinned evaluation records. No other
  system was compared in this release.

## Training (frozen before the evaluation)

- **Data.** One checkpoint, trained on the M3 manifest `bb432765…`: 11,606 machine families and 2.45M rows.
  - Zoo programs, labelled by exact solvers: 664,821 rows from Opus-authored, catalog, grammar, Arena-in-DSL and
    GPT-authored families.
  - The three Arena games, labelled by exact or near-exact teachers plus DAgger rounds: Snake 1.44M, Rotorwash-Ramp
    99k and Booster 245k rows.
- **Run.** 12,000 steps on CPU (2.76 h), seed 0, recipe "separate trunk" (fixed before the run).
- **Architecture.** Structured program encoder: typed tokens, relation-typed attention biases, d = 128, 3 layers.
  Heads give a joint prior over the 27 joints, a success value, and a per-joint optimal-set probability (the
  confidence gate). Each Arena game has its own encoder and trunk copy in the same checkpoint.

## Provenance

Gates, populations, statistics and wording were fixed in PREREG_V2G before any result existed. A failed gate is
never passed retroactively. Full report: https://github.com/nagisanzenin/nagi/blob/main/bench/burst_v2/README.md. SDK:
`python -m pip install "nagi-decisions @ git+https://github.com/nagisanzenin/nagi.git@v0.7.0"` (the import
is `nagi`; the unrelated PyPI package `nagi` is not this project).
