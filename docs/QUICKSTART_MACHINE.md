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

## 6. Example: your own game

You already have a game; Nagi only needs its rules. A delivery robot drives on a 5 × 5 grid. It starts at (0, 0)
with battery 8 (at most 10). A straight step costs 1 battery and a diagonal step costs 2. It must pick up a parcel
at (4, 0) and deliver it to (0, 4). Each tick it stands on the charger at (2, 2) adds 4 battery. A battery of 0 is a
crash: it is checked after all of the tick's updates, and a crash beats the goal.

**The rules** (`robot.txt`; this text is already canonical):

<!-- robot-example: rules -->
```text
machine mz-1
vars:
  x in [0, 4], start {0}, out of range: clamp
  y in [0, 4], start {0}, out of range: clamp
  battery in [0, 10], start {8}, out of range: clamp
  parcel in [0, 1], start {0}, out of range: clamp
controls:
  @dx: DEC -1, KEEP 0, INC 1
  @dy: DEC -1, KEEP 0, INC 1
random $w: none
rules (in order, each tick):
  1. x := x + @dx
  2. y := y + @dy
  3. battery := battery - abs(@dx) - abs(@dy)
  4. if all(x == 4, y == 0): parcel := 1
  5. if all(x == 2, y == 2): battery := battery + 4
crash if any holds:
  1. all(battery <= 0)
goal: all(parcel == 1, x == 0, y == 4)
```

**Your game, written however you like.** Nagi never sees this class. `state()` reports every variable of the rules,
and you apply the choice yourself:

<!-- robot-example: game -->
```python
class RobotGame:
    def __init__(self):
        self.x, self.y, self.battery, self.parcel = 0, 0, 8, 0

    def state(self):
        return {"x": self.x, "y": self.y, "battery": self.battery, "parcel": self.parcel}

    def apply(self, choice):                       # e.g. {"dx": "inc", "dy": "keep"}
        step = {"dec": -1, "keep": 0, "inc": 1}
        dx, dy = step[choice["dx"]], step[choice["dy"]]
        self.x = min(4, max(0, self.x + dx))
        self.y = min(4, max(0, self.y + dy))
        self.battery = min(10, max(0, self.battery - abs(dx) - abs(dy)))
        if (self.x, self.y) == (4, 0):
            self.parcel = 1
        if (self.x, self.y) == (2, 2):
            self.battery = min(10, self.battery + 4)
        if self.battery <= 0:
            return "crash"
        if self.parcel == 1 and (self.x, self.y) == (0, 4):
            return "goal"
        return None
```

**The loop:**

<!-- robot-example: loop -->
```python
from nagi.burst2 import read_rules, load_core, operate

rules = read_rules(open("robot.txt").read(), strict=False).rules_text()  # canonical form, once
core = load_core()           # the pinned core from Hugging Face (downloaded once, sha256-checked)
game = RobotGame()
for t in range(50):
    state = game.state()
    out = operate(rules, state, {"core": core, "session": "robot-1", "step": t})
    result = game.apply(out["choice"])
    print(t, state, out["choice"], out["stats"]["n_acc"])
    if result:
        print(result, "after", t + 1, "ticks")
        break
```

**What happened.** The run is recorded in
[`bench/burst_v2/receipts/robot_example.json`](../bench/burst_v2/receipts/robot_example.json) (released core, session
`robot-1`). `scripts/burst2_robot_example.py` runs the three blocks above as written, steps every tick on the machine
parsed from the rules as well (so the class must agree with the rules), and writes the table:

<!-- robot-trace:begin -->
| t | x, y | battery | parcel | choice dx / dy | moves tied for best | note |
|---|---|---|---|---|---|---|
| 0 | 0, 0 | 8 | 0 | inc / dec | 3 | steps into the wall (dy has no effect) |
| 1 | 1, 0 | 6 | 0 | inc / keep | 1 |  |
| 2 | 2, 0 | 5 | 0 | inc / keep | 1 |  |
| 3 | 3, 0 | 4 | 0 | inc / keep | 1 | picks up the parcel |
| 4 | 4, 0 | 3 | 1 | dec / inc | 1 |  |
| 5 | 3, 1 | 1 | 1 | dec / inc | 1 |  |
| 6 | 2, 2 | 4 | 1 | keep / keep | 1 | waits on the charger: battery 4 → 8 |
| 7 | 2, 2 | 8 | 1 | dec / inc | 1 |  |
| 8 | 1, 3 | 6 | 1 | dec / inc | 1 |  |
| 9 | 0, 4 | 4 | 1 | | | **goal** after 9 ticks |
<!-- robot-trace:end -->

The robot delivers after 9 <!-- check: robot.goal_ticks = 9 --> ticks, with battery 4 <!-- check: robot.final_battery = 4 --> left. Three things to know:

- **Ties: Nagi plays to reach the goal, not to save battery.** At t = 0 <!-- check: robot.wall_tick = 0 -->, 3 <!-- check: robot.wall_tied = 3 --> moves tie for best, and the draw picked `inc / dec`. At y = 0 the `dec` runs into the wall and
  costs a battery unit for nothing, but the tied moves reach the goal equally soon, and the battery left over is not
  part of the goal. So they tie (`probabilities` shows the tie). If the battery matters to you, put it in the rules,
  for example in the goal.
- **Waiting on the charger was found, not taught.** At t = 6 <!-- check: robot.wait_tick = 6 --> the robot stays on the charger for one tick: battery 4 <!-- check: robot.wait_battery_before = 4 --> → 8 <!-- check: robot.wait_battery_after = 8 -->. No rule says "wait". With 4 battery, every way home costs 4 and ends in a crash, so the lookahead on
  your rules keeps it on the charger. It was the only best move at that tick (tied moves: 1 <!-- check: robot.wait_tied = 1 -->).
- **An unwinnable layout makes it stand still.** Delete rule 5 (the charger) and the robot cannot win: a search over
  the whole machine finds 116 <!-- check: robot.unwinnable.reachable_states = 116 --> reachable states and no goal. Nagi does not crash on purpose. All 9 <!-- check: robot.unwinnable.first_tied = 9 --> joint moves tie at t = 0, it drifts while moving is still safe,
  and from t = 6 <!-- check: robot.unwinnable.still_from = 6 --> (battery 1 <!-- check: robot.unwinnable.still_battery = 1 -->) it stands still for the rest of the run (20 <!-- check: robot.unwinnable.ticks_run = 20 --> ticks). You can see this in
  `out["stats"]`: `n_acc` is the number of joint moves tied for best, and `max(out["stats"]["qbar"])` is the best
  lookahead value. With no reachable goal it is −33.1 <!-- check: robot.unwinnable.best_value = -33.1 -->, exactly the value of surviving the whole lookahead
  of 40 <!-- check: robot.unwinnable.depth = 40 --> ticks without reaching the goal (−1 per tick, discounted by 0.99). On the winnable layout it stayed
  between 37.5 <!-- check: robot.best_value_min = 37.5 --> and 49.0 <!-- check: robot.best_value_max = 49.0 -->.
