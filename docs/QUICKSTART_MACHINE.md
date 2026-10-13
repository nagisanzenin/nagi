# Write your own machine (quickstart)

This takes five minutes. You describe a small machine in Nagi's rule language and get a decision for every tick.
The full definition is in [DSL_REFERENCE.md](DSL_REFERENCE.md).

## 1. Write the rules

The example is a tank with an inflow pump and a drain valve. Sometimes an extra unit of water arrives on its own.
The tank must settle at level 8–9 with the valve shut, and it must never overflow or run dry.

<!-- example: quickstart-loose -->
```text
machine mz-1
vars:
  level in [0, 12], start {2, 3}, out of range: crash
  valve in [0, 2], start {0}, out of range: clamp
controls:
  @pump: DEC none, KEEP 0, INC 1
  @drain: DEC -1, KEEP 0, INC 1
random $w each tick:
  0 with probability 3/4
  1 with probability 1/4
rules (in order, each tick):
  1. valve := @drain + valve
  2. level := level + 2*@pump - valve + $w
crash if any holds:
  1. level >= 12
goal: all(level >= 8, level <= 9, valve == 0)
```

The rulebook says:

- **Variables.** `level` is `out of range: crash`, so overflowing past 12 or draining below 0 ends the episode at
  once. `valve` is clamped to 0–2.
- **Controls.** `@pump` can only stay off or pump +1, because it has no DEC option. `@drain` closes, holds or opens
  the valve by one step.
- **Random input.** Each tick, `$w` adds a unit of water with probability 1/4.
- **Rules.** They run top to bottom: the valve moves first, then the level uses the *new* valve position.
- **Outcome.** The crash condition is checked before the goal. On the same tick, a crash wins.

## 2. Make it canonical (once)

The exact reader accepts only the canonical form, so that the text means exactly one machine. Convert your text
once, and keep the result:

```python
from nagi.burst2 import read_rules

rules = read_rules(open("tank.txt").read(), strict=False).rules_text()
```

<!-- example: quickstart-canonical -->
```text
machine mz-1
vars:
  level in [0, 12], start {2, 3}, out of range: crash
  valve in [0, 2], start {0}, out of range: clamp
controls:
  @pump: DEC none, KEEP 0, INC 1
  @drain: DEC -1, KEEP 0, INC 1
random $w each tick:
  0 with probability 3/4
  1 with probability 1/4
rules (in order, each tick):
  1. valve := valve + @drain
  2. level := level - valve + 2*@pump + $w
crash if any holds:
  1. all(level >= 12)
goal: all(level >= 8, level <= 9, valve == 0)
```

The canonical form differs from the loose text in three ways:

- terms are reordered: variables, then controls, then `$w`, then the constant;
- the bare comparison `level >= 12` becomes `all(level >= 12)`;
- nothing else changes.

If you pass the loose text straight to `operate()`, you get `ReaderError: rulebook does not round-trip` instead of a
silent reinterpretation. Verified: the strict reader rejects the loose text <!-- check: quickstart.strict_rejects_loose = true -->.

## 3. Decide every tick

```python
from nagi.burst2 import load_core, operate

core = load_core()
t = 0
while True:
    state = {"level": tank.level(), "valve": tank.valve()}             # every variable, current values
    out = operate(rules, state, {"session": "tank-run-1", "step": t})  # released defaults apply
    tank.apply(out["choice"])                                          # e.g. {"pump": "inc", "drain": "keep"}
    t += 1
```

- **Probabilities.** `out["probabilities"]` shows how sure the decision is: uniform over the options that the exact
  lookahead cannot tell apart.
- **Replayable draws.** Use one `session` per episode and increase `step`, so every draw can be replayed.
- **Stateless calls.** Each call stands alone, so you keep the episode state yourself.

**Verified:**
- From `{"level": 2, "valve": 0}` the first choice is `{"drain": "dec", "pump": "inc"}` <!-- check: quickstart.first_choice = {"drain": "dec", "pump": "inc"} -->. With the valve shut, `dec` and `keep` do the same thing, so the drain choice is a tie, drawn from `probabilities`.
- In 10 seeded simulated episodes, `operate()` reached the goal in 10 <!-- check: quickstart.episodes.success = 10 --> of them, each in 2–3 ticks.

## 4. Delays and hidden parts (mz-1x)

If your controls act a tick or two late, or part of the state cannot be seen, add an extension block (reference §4).
Then pass the recent history instead of one state:

```python
from collections import deque

H, d = 3, 1                       # window and delay, as declared in the extension block
K = max(H - 1, d)
obs = deque([None] * (H - 1) + [first_observation], maxlen=H)    # displayed vars only
dec = deque([None] * (K - d) + [{"acc": "keep"}] * d, maxlen=K)  # KEEP is in flight at the start
while running:
    out = operate(rules, {"obs": list(obs), "dec": list(dec)}, {"session": "run-1", "step": t})
    send(out["choice"])           # it is applied d ticks from now
    dec.append(out["choice"]); obs.append(read_displayed()); t += 1
```

## 5. Before you rely on it

- **Size.** Keep the machine small. The released numbers were measured on machines with ≤ 60,000 reachable states
  (≤ 100,000 with delay). Larger machines run, but the lookahead sees less of them. `out["stats"]["exhausted"]` and
  `out["stats"]["visited"]` show how much it saw.
- **Latency.** It was measured on one thread of an Apple M2: p95 ≤ 200 ms. Other hardware is not measured.
- **Modelling.** The decision is only as good as the rules. A rule you forgot is a rule Nagi cannot plan for.
- **Prose.** Rules written in plain English are not read in this release, so write the machine language. A prose
  reader is planned for V2.1.
