# Family gate (`famgate`)

Gate version `machine-zoo-factory-v1 (= v2g-famgate-v1 thresholds)`. This is the gate that admitted the published
Machine Zoo families, with the same thresholds, the same instance salts and the same exact engine (see §7 for what
differs). This file, [docs/DSL_REFERENCE.md](../../docs/DSL_REFERENCE.md) (the machine language) and
`examples/` are everything an author needs. The code is `famgate/core.py`.

## 1. A family = one Python file

```python
"""Docstring: what the machine is, which strata it carries and why each one is load-bearing.
Deviations / design notes go here too."""
from machine_zoo import dsl          # the only allowed imports: machine_zoo.dsl, bv2n.zoo_new.xdsl, math, itertools
from bv2n.zoo_new import xdsl

FAMILY = {
    "name": "<file stem>",           # [a-z][a-z0-9_]{2,40}, unique in your index
    "domain_id": "<the batch domain>",
    "batch": "<bid>", "slot": <int>, # the claimed batch and the slot you fill
    "author": "<author or agent id>",
    "title": "...", "story": "...",  # plain words; never state a hidden value
    "strata": [...],                 # tags from: delay hidden long interlock axes3 budget multibudget
    "mode_var": "m",                 # only with interlock
    "budget_vars": ["f", "b"],       # only with budget (>= 1) / multibudget (>= 2)
}
PARAMS = {"p1": [..], "p2": [..]}    # 2..5 int params, grid size 8..64
def build(p: dict) -> dict:          # pure: same p -> same program; never mutate p
    return xdsl.make(dsl.program(...), delay=d, hidden=[...], window=H)
GLOSSARY = {"<identifier>": "<plain-words description>", ...}   # optional, for readers of the code
def prose(p: dict) -> str:           # the natural-language rulebook of THIS instance
    return f"""..."""
```

The two import names are the engine's module names; the factory maps them to the vendored engine under
`src/nagi/burst2/_rt/` (`famgate/_runtime.py`), so family files run unchanged here and in the published dataset.

Identifiers (var and control names) must be descriptive words of >= 3 chars (`fuel`, `battery`, `selector`, not
`f`, `b`, `m`): the prose is scored against the program with the IDENTITY name map, so every identifier must appear
verbatim in the prose.

Program semantics: [docs/DSL_REFERENCE.md](../../docs/DSL_REFERENCE.md) §1-§3 (mz-1: vars, controls, random input,
rules, crash, goal, one tick) and §4 (mz-1x: reply delay d in {0, 1, 2}, hidden vars + history window H). Python
helpers: the docstrings of `dsl.var`, `dsl.control`, `dsl.program` and `xdsl.make`. Forbidden in a family file: any
other import, `open/eval/exec/compile/__import__/globals/locals/vars/hash/id/print/getattr/setattr/delattr/input/
breakpoint`, dunder attributes, randomness, time, I/O.

## 2. Instances

Grid points are ordered by `sha256(salt|name|json(p))`. Profile `train` (default) uses salt `v2g-fam-inst-v0` and
keeps up to 10 instances; profile `benchmark` uses salt `v2g-zud-scan-v0` and keeps up to 6 (both salts are the
research values, so a published family re-validates to the same kept instances). Each grid point is built twice
(V2), checked (§3) and kept if it passes with a new machine_id, until the keep limit.
**Admission: >= 6 kept instances**, X6 blind-checker equivalence on the 2 smallest kept instances, V7 family checks,
then an independent blind review (GENERATE.md §6).

## 3. Checks per instance (all probabilities are exact 100-tick chain values from the uniform start; no sampling)

| Check | Rule |
|---|---|
| frozen mz-1x gates | X0 validity + declared delay/hidden/long consistent with the program; X1 \|S\| <= 60,000, \|S_x\| <= 100,000, views <= 200,000; G2-G8 (G3 every control slot has a minority label share >= 0.05; G4 fully tied visits <= 0.25; G5 keep <= 0.20; G6 greedy bot <= 0.80; G7 oracle mean length >= 5; G8 no dead rule); X3 identifiable; X4d/X4h/X5 below |
| V1 | `xdsl.render_rulebook` -> `parse_rulebook_x` -> identical canonical program and identical text |
| V2 | `build(p)` twice on fresh copies -> byte-identical canonical JSON; `p` unchanged; `prose(p)` twice identical |
| V3 | oracle (exact V-infinity label policy) success >= **0.95** within 100 ticks |
| V4 | keep <= 0.20, greedy (weak) <= 0.80, uniform random <= **0.50**, probe4 <= **0.80** (probe4 = lexicographic exact one-tick + 4-tick look-ahead probe, delay-blind; for hidden programs it is blind: it sees only the current displayed obs + queue) |
| V5 | every declared stratum is verified by execution (§4) |
| V6 | rules <= 24, rulebook text <= 3,200 chars, gate time <= 120 s per instance (plus X1) |
| P1 | prose present, 400..6,000 chars, no DSL syntax (`:=`, `@x`, `$w`, `all(`/`any(`/`abs(`/`sgn(`, the characters `< > =`, `KEEP/DEC/INC`, `out of range:`, numbered `if ...:` lines), word 5-gram Jaccard with the DSL rulebook <= 0.10, and the **exact parser rejects it** (the whole text as an mz-1/mz-1x rulebook, and every line/sentence as a DSL rule or predicate) |
| P2 | completeness checklist (§5), including **every identifier verbatim** (>= 3 chars) |

Family level: **V7** near-duplicates against every INDEXED family: no shared mz-1x signature or base signature, WL
structural similarity < **0.60** (Weisfeiler-Lehman subtree features of the rename/constant-invariant program
graph; on 201 hand-authored families the maximum pair is 0.50 and p99.9 is 0.27; a one-rule edit of a family scores
0.63-0.78, a renaming 1.00), unique name, prose word 5-gram Jaccard with any other family's prose < **0.35** (no
shared template). The index is exactly what `validate.py` is given: your job's PASSED families, the bundled
`examples/`, and every `--index-dir` you pass (for example the published Machine Zoo families). Nothing is indexed
implicitly. A family file edited after its PASS is not counted (and not indexed) until re-validated: the PASS is
bound to the module sha256.

## 4. Strata (what each tag means and how it is verified)

"Load-bearing" always means: a probe that cannot use the feature loses >= 0.20 success or >= 10 mean-return points
against the oracle (the X4 margins).

| Tag | Verified by |
|---|---|
| `delay` | d >= 1 and X4d: the delay-blind probe (plays the d = 0 oracle's action for the true state) is load-bearing-worse |
| `hidden` | hidden vars present, X3 every reachable view identifiable within H, X4h: the memoryless probe (current obs + queue) is load-bearing-worse |
| `long` | X5: oracle median success tick >= 20 |
| `interlock` | `mode_var` m with <= 8 values; >= 2 rules whose guard reads m and that read a control (the mode decides what a control does); m is written by >= 1 rule; >= 3 values of m each get >= 5% of the oracle's visits; the mode-blind probe (true state with m marginalised out) is load-bearing-worse |
| `axes3` | exactly 3 control slots; every slot passes G3 and is decisive on >= 10% of oracle visits |
| `budget` / `multibudget` | >= 1 / >= 2 `budget_vars`; each is consumed on some reachable transition and its budget-blind probe (true state with that var marginalised out) is load-bearing-worse |

## 5. Prose rulebook

Write it the way an operator or engineer would explain the machine to a colleague: sentences, the machine's own
vocabulary, your own style (vary it between families: manual, briefing, logbook, checklist in words, Q&A...). It
must determine the program exactly: a careful reader with no DSL must be able to write the same transitions.
It must state, with the instance's actual numbers (f-strings):

1. every var BY ITS IDENTIFIER, verbatim (e.g. "the battery holds 0 to 3 charges"): range (low and high numbers),
   start values, and if leaving the range is a failure, say so in the same sentence as the identifier;
2. every control BY ITS IDENTIFIER, verbatim: its three positions and their numeric effect;
3. every rule in the order the machine applies them, including every constant and every condition (say that the
   updates happen in that order, each seeing the results of the earlier ones);
4. every failure condition and the goal with their numbers, and in ONE sentence that a failure on the same tick
   beats the goal;
5. delay: "commands take effect d tick(s) later" (in the same sentence: the number and a delay word);
6. hidden vars: say next to the term that it is not shown, and how many recent readings are shown (H);
7. chance: every random outcome with its probability (`w/W`, `w in W`, or a percentage) and its value;
8. out-of-range behaviour for every var: whether a value is held at the limit, or leaving the range is an immediate
   failure (and that the rest of that tick is then skipped);
9. start values: that each var starts uniformly at random over its stated start values, independently of the others
   (or the fixed value, if there is a single one);
10. controls: list the settings in increasing order, say which one is neutral, and that a command acts on this tick
    only (it is not latched);
11. chance: that there is exactly one random draw per tick (shared by every rule that uses it);
12. failure/goal timing: that failure conditions are checked after all updates of the tick;
13. delay: that neutral settings are in flight at the start (the first d ticks apply neutral commands);
14. that there are no rewards or scores other than reaching the goal without failing, and do NOT mention the 100-tick
    evaluation cap (it is not part of the machine).

P2 checks items 1-7 mechanically (every identifier verbatim; every range/start/option/rule/crash/goal number present
as a numeral (0 and 1 may be words); order wording; crash-beats-goal sentence; delay sentence; hidden sentence +
window; chance forms); items 8-14 are for the reviewer. P1 makes sure the exact parser REJECTS the prose (it is not
the DSL in disguise). Neither is proof of sufficiency: a **blind sufficiency reviewer** reads the prose alone,
writes the program it determines, and `python3 prose_check.py <family.py> <reading.txt> --params '<json>'` must print
`EXACT` (transition-exact under the identity name map) on the first 2 kept instances
(`examples/example_dock_cart.reading.txt` shows what an exact reading looks like). Never mention a hidden var's
current value, never paste the DSL, never generate the prose from the program by code.

## 6. Design patterns that pass (general; no family code)

- Decision-irrelevant ignorance: until a hidden value can be read from the window, the best action must not depend
  on it (start far enough away; let the disturbance act only after a few ticks).
- Commit before you can see: a hidden or delayed feature is load-bearing when the client must commit d ticks before
  a moment whose single frame is ambiguous and a wrong commitment is irreversible. Cheap waiting, hovering or a
  strong reactive actuator makes features irrelevant (X4 fails).
- With d = 2 the two in-flight commands can encode a counter; prefer d = 1 for phase-type hidden state.
- Check the goal is reachable in the last ticks (matching a moving target's cell AND speed can be impossible).
- Forced waiting makes all actions tie (G4); add a small idle hazard or forced motion, or shorten the wait.
- Budgets bind when the gauge changes the plan: e.g. a fast action that does nothing at 0 (the blind probe stalls),
  or a resource also needed at the end (spending it early strands the finish).
- Interlocks: one control whose meaning depends on a mode, a crash that only exists in one mode, mode switches that
  cost ticks; visit >= 3 modes.
- 3 control slots: |valid joints| = 27, so with delay keep |S| <= ~3,000 (|S_x| <= 27 |S| <= 100,000).
- Rules that only fire for some parameter values must only be generated for those values (G8 dead rule).
- No start state may satisfy the goal or a crash.

## 7. Identical to the research gate, and what differs

Identical: every threshold of `Profile` (`famgate/core.py`; `tests/` asserts the values), the instance salts and
keep limits, the frozen mz-1x gates (`famgate/xgates.py`), the X6 blind checker (`famgate/blind/`, `famgate/x6.py`)
and the exact engine (`src/nagi/burst2/_rt/`: the research modules with import paths rewritten only). Re-gating
published families with this code reproduces their reports' kept instances, machine ids, signatures, prose hashes
and per-instance results (checked on published families covering all seven strata, X6 included).

Different: the V7 index (only what you pass, §3), the job rules (`validate.py`: optional batch plan, your own
forbidden-token file, default none), the gate version string, and file/report locations (any job folder).
