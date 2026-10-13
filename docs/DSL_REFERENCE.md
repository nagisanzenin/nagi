# Nagi machine language (mz-1 / mz-1x): reference

Nagi Burst V2 decides for machines that you describe in a small rule language. You write the rules, Nagi's exact
reader parses them, and the exact lookahead plus the learned core choose a setting for every control on each tick.
This page defines the language completely: its syntax, what one tick does, the limits, the extension for delayed
replies and hidden variables, and how to call `operate()`. All examples were checked by
`scripts/v2g/dsl_doc_check.py`. Each one is parsed by the exact reader and run through `operate()` with the released
configuration, and its text is compared with this page byte for byte.

If you are new to the language, start with [QUICKSTART_MACHINE.md](QUICKSTART_MACHINE.md) (one page).

## 1. What a machine is

| Part | Meaning |
|---|---|
| **vars** | Integer state variables, each with a range, a set of start values and an out-of-range rule. |
| **controls** | Up to 3 controls. Each has up to 3 options, DEC, KEEP and INC, and each option has an integer command value. On every tick you choose one option per control. |
| **random input `$w`** (optional) | One integer drawn each tick from a fixed distribution. |
| **rules** | Ordered assignments, some guarded by a condition, that run once per tick. |
| **crash conditions** | If any of them holds after the rules, the episode ends as a failure. |
| **goal** | If it holds after the rules, and no crash does, the episode ends as a success. |

The objective is the same for every machine. Each tick costs 1, reaching the goal earns 49, and a crash costs 200.
Rewards are discounted by 0.99 per tick, and an episode stops after 100 ticks. Nagi chooses the controls that
maximize the expected discounted total.

## 2. Text layout (exact)

A rulebook has these sections, always in this order. Indented lines use exactly two spaces, and the text ends with
a newline.

```text
machine mz-1
vars:
  <name> in [<lo>, <hi>], start {<v1>, <v2>, ...}, out of range: clamp|crash
controls:
  @<name>: DEC <int>|none, KEEP <int>, INC <int>|none
random $w: none                                  # or the two-part form below
random $w each tick:
  <value> with probability <weight>/<total>
rules (in order, each tick):
  1. <rule>
crash if any holds:                              # or: crash if any holds: none
  1. <predicate>
goal: <predicate>
```

Comments (`# ...`) are shown here only for explanation, and they are not part of a canonical rulebook.

### 2.1 Variables

`<name> in [lo, hi], start {a, b, ...}, out of range: clamp|crash`

- **Names.** A name matches `[a-z][a-z0-9_]{0,15}`. Variables and controls share one namespace, so every name must
  be unique across both.
- **Count.** 1 to 10 variables.
- **Range.** −1000 ≤ lo < hi ≤ 1000, and hi − lo ≤ 400.
- **Start values.** The start values are strictly increasing and inside the range.
- **Start state.** The start state is drawn uniformly from all combinations of start values. There are at most 64
  combinations, and none of them may already satisfy the goal or a crash condition.
- **Out-of-range rule.** It decides what happens when a rule assigns a value outside `[lo, hi]` (§3).

### 2.2 Controls

`@<name>: DEC <int>|none, KEEP <int>, INC <int>|none`

- **Count.** 1 to 3 controls.
- **Options.** KEEP is always an integer. DEC and INC are integers, or `none` when that option does not exist. The
  SDK needs at least 2 options per control.
- **Values.** Command values are in [−10, 10], and the values of one control are distinct.
- **Reading a control.** `@name` in a rule reads the command value chosen *this tick*. There is no memory of past
  commands; use a variable for that.
- **In the API.** The options are called `"dec"`, `"keep"` and `"inc"`. A joint choice of all controls is the
  index j = o₀·9 + o₁·3 + o₂, where o = 0 for DEC, 1 for KEEP and 2 for INC. An absent control counts as KEEP.

### 2.3 Random input

- **Form.** Either `random $w: none`, or `random $w each tick:` followed by 1 to 5 lines
  `<value> with probability <weight>/<total>`.
- **Values.** They are distinct, strictly increasing and in [−10, 10].
- **Weights.** Weights are integers ≥ 1 with a total of at most 1000. Write the total of all weights as the
  denominator on every line.
- **Reading it.** `$w` is the outcome of this tick. With `none`, `$w` may not appear anywhere.

### 2.4 Expressions (EXPR)

An expression is a linear integer expression: terms `[coef*]atom`, plus an integer constant.

- **Atoms.**
  - a variable `x`, `abs(x)`, `sgn(x)` (−1, 0 or +1);
  - a control `@c`, `abs(@c)`;
  - the random input `$w`.

  There is no `sgn(@c)`, no product of atoms and no nesting.
- **Limits.** 0 to 6 terms, |coef| ≤ 10 and |constant| ≤ 1000.
- **Arithmetic.** Exact integer arithmetic.

### 2.5 Predicates (PRED)

- **Form.** `all(item, ...)` is true when every item holds, and `any(item, ...)` when at least one holds.
- **Items.** A predicate has 1 to 6 items. An item is `EXPR op INT` with op in `<= >= == != < >` and |INT| ≤ 1000,
  or a nested `all(...)` / `any(...)`. Nesting goes at most one level deep.
- **Variables only.** Goal and crash predicates may read variables only: `x`, `abs(x)`, `sgn(x)`. They may not read
  `@` or `$w`.
- **Item budget.** Goal and crash together have at most 16 comparison items.

### 2.6 Rules

`<var> := EXPR` or `if PRED: <var> := EXPR`.

- There are 1 to 24 rules, numbered `1.`, `2.`, and so on.
- Rule guards and rule expressions may use every atom.

### 2.7 Canonical form (what `operate()` accepts)

The exact reader accepts a rulebook only if printing the machine it parsed gives back **the same bytes**. This is
what makes the text path and the structured path identical (gate I). The canonical form is:

| Element | Canonical form |
|---|---|
| Term order | Variables in declared order (`x`, then `abs(x)`, then `sgn(x)`), then controls in declared order (`@c`, then `abs(@c)`), then `$w`, then the constant |
| Merging | Equal atoms merged, zero terms dropped |
| Coefficients | Coefficient 1 omitted (`x`, `-x`); other coefficients as `2*x` |
| Spacing | Spaces around `+`, `-`, `:=` and the comparison operator |
| Predicates | Always wrapped in `all(...)` or `any(...)`, items separated by `, ` |
| Comparisons | A single integer on the right: write `x - y >= 0`, not `x >= y` |
| Rest | No comments, no blank lines, a final newline |

You do not have to type the canonical form by hand. Write the rulebook naturally, then canonicalize it once:

```python
from nagi.burst2 import read_rules          # research repo: from v2g.reader import read_rules

canonical = read_rules(my_text, strict=False).rules_text()   # parses, validates, prints the canonical form
```

`read_rules(text)` without `strict=False` raises `ReaderError` on any text that is not canonical. That check is how
you know the text means exactly what you think.

## 3. One tick: exact semantics

Each tick runs these steps in order.

1. **Random draw.** If the machine has a random input, `$w` is drawn once, before anything else.
2. **Commands.** The chosen option of each control sets `@c` to its command value. In mz-1x, the command that is
   *applied* can be one decided earlier (§4).
3. **Rules run top to bottom.**
   - Each rule sees the values that earlier rules assigned in the same tick, while its guard and expression read the
     current values.
   - A guard that is false skips its rule.
   - If the new value is outside the target's range:
     - with `out of range: clamp`, it is clamped to the nearest end;
     - with `out of range: crash`, **the episode crashes at once** and the remaining rules do not run.
4. **Outcome.** After the last rule:
   - if any crash condition holds, the result is a **crash**;
   - otherwise, if the goal holds, the result is **success**;
   - otherwise the episode keeps running.

   **A crash wins over the goal on the same tick.** The goal is never checked at the start.
5. **Reward.** Running −1, crash −200, success +49. The episode stops after 100 ticks (timeout, not success).

## 4. Extension mz-1x: reply delay, hidden variables, history window

The extension is an mz-1 rulebook followed by an `extension mz-1x:` block. The block has one of two forms:

```text
extension mz-1x:
  reply delay: 1 tick (a command decided now is applied that many ticks later; KEEP is in flight at start)
  hidden vars (never displayed): <name>, <name>
  history shown: last <H> displayed observations
```

or, with nothing hidden:

```text
extension mz-1x:
  reply delay: 2 ticks (a command decided now is applied that many ticks later; KEEP is in flight at start)
  hidden vars: none
```

Rules for writing the block:

- **Delay.** `d` is 0, 1 or 2. The parenthesis appears only when d ≥ 1, and the word is `tick` for 1 and `ticks`
  otherwise.
- **Hidden variables.** List them in declared order. At least one variable must stay displayed.
- **Window.** H is 1 to 6. With nothing hidden, the window line is omitted and H = 1.
- **No-op.** With d = 0 and nothing hidden, write no extension at all: the machine is plain mz-1.

What each part does:

- **Delay.** A choice you make at tick t is applied at tick t + d. At the start, `d` KEEP commands are already in
  flight. On each tick, the oldest in-flight command is applied, and your new choice joins the end of the queue.
- **Hidden variables.** Rules, crash conditions and the goal may read hidden variables, but their values are never
  shown. You see the last H observations of the displayed variables, and you have to infer the hidden ones from
  that history. Make H long enough for the history to identify what matters.
- **State you pass to `operate()`:**
  ```python
  {"obs": [obs_{t-H+1}, ..., obs_t],      # H entries, oldest first; obs = {displayed var: value}; None = before start
   "dec": [dec_{t-K}, ..., dec_{t-1}]}    # K = max(H - 1, d) of YOUR past choices, oldest first,
                                          # each {control: "dec"|"keep"|"inc"}; the last d are still in flight;
                                          # at the start they are {c: "keep"}, and entries older than that are None
  ```
- **Size.** Delay multiplies the state space by up to 27^d (3 controls). The training and evaluation machines stayed
  within 60,000 reachable states, or 100,000 counting the in-flight queue. Larger machines still run, but the
  lookahead covers a smaller share of them within its budget.

## 5. Calling `operate()`

```python
from nagi.burst2 import load_core, operate, operate_structured, read_rules

core = load_core()                          # pinned weights, sha256-checked
out = operate(rules_text, state, {"session": "episode-42", "step": t})
```

| Output | Meaning |
|---|---|
| `choice` | `{control: "dec" / "keep" / "inc"}`, the option to apply on this tick |
| `joint` | the joint index of `choice` |
| `probabilities` | per-control marginals over the offered options |
| `joint_probabilities` | `{joint: p}`: uniform over the joints that the exact search cannot tell apart, or the core's prior inside that set when its confidence is ≥ τ |
| `stats` | `sims`, `depth`, `exhausted`, `visited`, `gated`, `total_ms`, `replayable`, … |

- **Released defaults.** τ 0.6, belief v1b, 100,000 simulations and k_max 40.
- **Replayable draws.** Pass a `session` and increase `step` on every decision. Without them, the choice inside the
  tie set uses fresh randomness (`stats["replayable"] == False`).
- **Stateless calls.** Each call is self-contained, so you keep the episode state yourself. For mz-1x, that includes
  the observation window and your past choices.
- **Errors.** Invalid input raises an error and nothing is guessed: a non-canonical rulebook, a state with missing or
  extra variables, wrong window lengths, an unknown option.

## 6. Worked examples (training machines)

All three examples are training machines of Nagi Burst V2: an exact copy of one instance per family, at its recorded
parameters. None of them comes from an evaluation set.

### 6.1 Soft lander: a crash-on-range variable and a two-option control

`opus:lander_soft_touchdown`, machine `bd73b09f32bee094`. A lander falls under gravity. Its engine can only brake,
fuel is limited, and the airframe fails if it falls faster than 6.

<!-- example: bd73b09f32bee094 -->
```text
machine mz-1
vars:
  h in [0, 30], start {16, 18}, out of range: clamp
  v in [-6, 3], start {-3, -2}, out of range: crash
  f in [0, 9], start {9}, out of range: clamp
controls:
  @throttle: DEC none, KEEP 0, INC 1
random $w: none
rules (in order, each tick):
  1. if all(f >= 1): v := v + 2*@throttle - 1
  2. if all(f <= 0): v := v - 1
  3. f := f - @throttle
  4. h := h + v
crash if any holds:
  1. all(h == 0, v < -1)
goal: all(h == 0, v >= -1)
```

**How to read it:**

- **Rule 1.** It runs only while there is fuel: a burning tick brakes by 1, and a coasting tick speeds the fall by 1.
- **Rule 4.** It moves the altitude by the *new* speed, because rules see earlier assignments.
- **Speed limit.** `v` is `out of range: crash`, so falling faster than −6 ends the episode in the middle of the
  tick.
- **Touching down.** At `h == 0`, the crash test (too fast) is checked before the goal (slow enough). Exactly one of
  them holds.
- **Throttle.** `@throttle` has no DEC option. Its options are `keep` (off) and `inc` (burn).

**Verified run.**
- First decision from start state `{"f": 9, "h": 18, "v": -2}` <!-- check: examples.0.first_state = {"f": 9, "h": 18, "v": -2} -->: `operate()` chose `{"throttle": "keep"}` <!-- check: examples.0.first_choice = {"throttle": "keep"} -->.
- One seeded episode: success after 7 ticks (undiscounted return 43) <!-- check: examples.0.episode.outcome = "success" --><!-- check: examples.0.episode.ticks = 7 -->.

### 6.2 Berthing a ship: random input, sgn/abs atoms, guards that read controls

`opus:ship_berth_tide`, machine `6540c4c6b835b763`. A ship approaches a quay against a random tidal set. Its engine
time is limited, and hull drag slows it whenever the engine is idle.

<!-- example: 6540c4c6b835b763 -->
```text
machine mz-1
vars:
  x in [0, 24], start {3, 5}, out of range: clamp
  v in [-1, 4], start {3, 4}, out of range: clamp
  f in [0, 12], start {12}, out of range: clamp
controls:
  @engine: DEC -1, KEEP 0, INC 1
random $w each tick:
  -1 with probability 1/10
  0 with probability 8/10
  1 with probability 1/10
rules (in order, each tick):
  1. if all(@engine != 0, f >= 1): v := v + @engine
  2. if any(@engine == 0, f <= 0): v := v - sgn(v)
  3. f := f - abs(@engine)
  4. v := v + $w
  5. x := x + v
crash if any holds:
  1. all(x >= 20, v >= 3)
goal: all(x >= 20, v <= 2)
```

**How to read it:**

- **Random input.** `$w` is −1, 0 or +1 with probabilities 1/10, 8/10 and 1/10. It is drawn once per tick, before
  the rules.
- **Rules 1 and 2.** Their guards read the control (`@engine`). `v - sgn(v)` takes one unit of speed off toward 0.
- **Rule 3.** `abs(@engine)` charges engine time for ahead and for astern alike.
- **Lookahead.** The search plans over the exact chance distribution, not over one sampled tide.

**Verified run.**
- First decision from start state `{"f": 12, "v": 4, "x": 5}` <!-- check: examples.1.first_state = {"f": 12, "v": 4, "x": 5} -->: `operate()` chose `{"engine": "inc"}` <!-- check: examples.1.first_choice = {"engine": "inc"} -->.
- One seeded episode: success after 9 ticks (undiscounted return 41) <!-- check: examples.1.episode.outcome = "success" --><!-- check: examples.1.episode.ticks = 9 -->.

### 6.3 Courier crossing a pedestrian stream: reply delay, hidden phase, window

`c:courier_stream_gap`, machine `2d581aca3db4b521`. A delivery robot must cross a walkway that pedestrians pass on a
fixed rhythm.

<!-- example: 2d581aca3db4b521 -->
```text
machine mz-1
vars:
  y in [0, 18], start {0, 1}, out of range: clamp
  v in [0, 2], start {0}, out of range: clamp
  o in [0, 1], start {0}, out of range: clamp
  ph in [-1, 5], start {0, 1, 2, 3, 4, 5}, out of range: clamp
controls:
  @acc: DEC -1, KEEP 0, INC 1
random $w: none
rules (in order, each tick):
  1. if all(ph == 5): ph := -1
  2. ph := ph + 1
  3. o := 0
  4. if all(ph <= 2): o := 1
  5. v := v + @acc
  6. y := y + v
crash if any holds:
  1. all(y >= 9, y <= 11, o == 1)
goal: all(y >= 16)
extension mz-1x:
  reply delay: 1 tick (a command decided now is applied that many ticks later; KEEP is in flight at start)
  hidden vars (never displayed): ph
  history shown: last 3 displayed observations
```

**How to read it:**

- **Hidden phase.** The rhythm's phase `ph` is hidden. `y`, `v` and `o` (walkway busy now) are displayed. One frame
  cannot tell a fresh gap from a closing one, but the 3-observation window can.
- **Delay.** Speed commands arrive 1 tick late, so the robot must decide to go before the gap is visible.
- **First state.** At the start, the state passed to `operate()` has `obs` = two `None` entries and the first
  observation, and `dec` = `[None, {"acc": "keep"}]`. That last entry is the KEEP already in flight.

**Verified run.**
- First decision from start state `{"dec": [null, {"acc": "keep"}], "obs": [null, null, {"o": 0, "v": 0, "y": 1}]}` <!-- check: examples.2.first_state = {"dec": [null, {"acc": "keep"}], "obs": [null, null, {"o": 0, "v": 0, "y": 1}]} -->: `operate()` chose `{"acc": "inc"}` <!-- check: examples.2.first_choice = {"acc": "inc"} -->.
- One seeded episode: success after 9 ticks (undiscounted return 41) <!-- check: examples.2.episode.outcome = "success" --><!-- check: examples.2.episode.ticks = 9 -->.

## 7. Common errors

| Symptom | Cause | Fix |
|---|---|---|
| `ReaderError: rulebook does not round-trip` | The text is valid but not canonical (term order, a bare comparison, `x >= y`, a comment) | `read_rules(text, strict=False).rules_text()` |
| `ReaderError: not an exact mz-1 / mz-1x rulebook: … unknown rulebook line` (or `bad var line`, `bad control line`, …) | Indentation is not exactly 2 spaces, or a section is out of order or misspelled | Follow §2 exactly |
| `ReaderError: not an exact mz-1 / mz-1x rulebook: <validation message>` | A limit was exceeded (§2.1–2.6), a start state already satisfies the goal or a crash condition, or `@`/`$w` appears in the goal or a crash condition | Fix the program |
| `state must give exactly the vars …` | An mz-1 state dict is missing a variable or has an extra one | Pass every variable |
| `mz-1x state needs H obs and K dec entries` | The window lengths are wrong | `len(obs) == H`, `len(dec) == max(H - 1, d)` |
