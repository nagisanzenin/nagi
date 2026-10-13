# Nagi Burst V2

## What it is

There are three parts. All are open, numpy-only and CPU-only.

1. **An exact reader for the machine language.** `mz-1` covers integer variables, ≤ 3 controls with DEC / KEEP / INC
   options, ordered rules, an optional random input, crash conditions and a goal. `mz-1x` adds a reply delay of 0–2
   ticks, hidden variables and a history window. The reader parses the text into the exact machine. It rejects
   invalid programs and never guesses.
2. **Exact lookahead.** The search simulates the parsed machine itself: 100,000 simulations per decision, horizon up
   to 40, and belief tracking when variables are hidden or controls are delayed.
3. **The learned core (3.10M parameters).** It reads the program structure and proposes a prior. The core
   is used only inside the set of moves the search cannot tell apart, and only when its confidence is ≥ 0.6.

On unseen machines, V2G's success comes mainly from exact lookahead on the given rules, which on small machines covers much or all of the reachable state set.

## API

`operate(rules_text, state, options) -> {"choice", "joint", "probabilities", "joint_probabilities", "stats"}`

| Argument | Meaning |
|---|---|
| `rules_text` | the machine in mz-1 / mz-1x text, or one full served request (then `state` is omitted) |
| `state` | mz-1: `{var: value}` for every variable. mz-1x: `{"obs": [...], "dec": [...]}`, oldest first, with `None` for padding |
| `options` | `core`, `tau` (0.6), `belief` ("v1b"), `max_sims` (100,000), `k`/`k_max`, `deadline_ms` (reported, never consulted); the draw: `session` + `step`, or `seed`, or `tie="hash"` (audit mode) |

`operate_structured(program, view, options)` gives the same decision from a canonical program without text. Gate I
checked on 7,506 requests that both paths give identical vectors and draws.

**The draw.** The search returns an exact tie set A. The choice is drawn from `probabilities`, which are uniform on A,
or the core prior renormalised inside A when the confidence gate opens. Pass `session` and increase `step` to make the
draw replayable. Without them, the draw uses fresh entropy (`stats["replayable"] == False`). `tie="hash"` gives a
deterministic choice, but that policy can loop on machines whose goal is beyond the horizon.

**Defaults are the released configuration.** τ 0.6, belief v1b, 100,000 simulations, k_max 40, and the pinned core.
Changing them gives a configuration that was not evaluated.

## Limits

- Only machines expressible in mz-1 / mz-1x are in scope. The language reference is [docs/DSL_REFERENCE.md](DSL_REFERENCE.md); start with [docs/QUICKSTART_MACHINE.md](QUICKSTART_MACHINE.md).
- Latency was measured on Apple M2 (cpu-m2-1t), native arm64, 1 thread, single-threaded. The p99 is reported, not gated (D 44.5 ms, Snake
  194.6 ms).
- Snake Rush, Rotorwash-Ramp and Booster Gauntlet were in the training data. On Snake, the released policy is
  the SDK Snake search pack (20,000 simulations, horizon 12, no learned core). On Rotorwash-Ramp and Booster, the core's game head plays without lookahead.
- The prose reader (rules in plain English) scored 23/48 transition-exact rulebooks, below its 0.95 gate. It is
  deferred to V2.1.
- The test machines were written by Claude Opus agents that were separate from the training authors, and checked by
  blind review plus an exact oracle.
