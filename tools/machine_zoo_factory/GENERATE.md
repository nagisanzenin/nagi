# GENERATE: running a family job (people or coding agents)

A **job** is one folder in which any number of authors (people, or coding agents such as Claude Code or Codex) write
machine families in parallel, a validator admits them, and blind reviewers accept them. Claims are atomic
directories, so parallel authors never collide. Below, `<TOOL>` is this folder (`tools/machine_zoo_factory`) and
`<JOB>` is your job folder; keep jobs outside the repository (or in a git-ignored folder).

## 1. Why it works (read once)

Each family is an exact generator: a DSL program (`build(p)`) from which the exact teacher computes optimal labels,
plus a prose rulebook (`prose(p)`) that says the same thing in words. Nobody writes labels by hand, and the gate
rejects machines whose structure a simple policy already solves. The value of a job is many DIVERSE machines: a
family that fails the gate is worthless, and a family that passes by being a re-skin of another is worse.
Correctness and diversity first.

## 2. Set up a job (once, before any family exists)

```bash
mkdir -p <JOB>/BATCHES
python3 <TOOL>/make_batches.py --job <JOB> --domains my_domains.txt --salt my-split-v1 --dev-every 5
```

- `my_domains.txt`: one `domain_id | one-line machine description` per line (see `examples/domains_example.txt`).
  One batch = one domain. Choose domains that are not already in the families you index (V7 checks structure, the
  domain rule checks `domain_id`).
- `--salt` and `--dev-every` decide which domains are DEV (held back: same work and gate, never trained on). Fix
  them before the first family and never change them afterwards; `make_batches.py` refuses to rewrite a split once
  the job has reports.
- Slot plans: by default train batches rotate plans A/B/C (6 slots) and dev batches use plan D (4 slots); each slot
  lists the strata its family must carry (table below; `famgate/jobkit.py` `DEFAULT_PLANS`). Your own plans go in
  `<JOB>/BATCHES/plans.json` as `{"plans": {"P": [["delay"], ["hidden", "long"]]}, "rotation": {"train": ["P"],
  "dev": "P"}}`, written before running `make_batches.py`.
- Optional `<JOB>/forbidden_tokens.txt`: one token per line; a family whose name, title, story or domain contains
  one (case-insensitive substring) fails V0. Use it to keep your evaluation domains out of training families.
  Default: no tokens.
- Optional near-duplicate index: pass `--index-dir DIR` to `validate.py` (repeatable) to check against other
  families, for example a folder holding the published Machine Zoo family files, or another job folder (its PASSED
  families are used). Put the flag in the author instructions so every author uses the same index.

| Plan | slot 1 | slot 2 | slot 3 | slot 4 | slot 5 | slot 6 |
|---|---|---|---|---|---|---|
| A | delay, long | hidden | interlock, long | axes3 | multibudget, delay | hidden, interlock |
| B | hidden, long | delay | axes3, multibudget | interlock | delay, hidden | multibudget, long |
| C | interlock, delay | multibudget | hidden, axes3 | long, delay | interlock, multibudget | hidden, long |
| D (dev) | delay, hidden | long, budget | interlock, delay | hidden, long | | |

## 3. Read first (authors and reviewers; do not modify)

1. `<TOOL>/GATES.md`: the family file format, every check, the strata, the prose rules, design patterns.
2. `<TOOL>/examples/example_dock_cart.py` (interlock + axes3 + multibudget) and `<TOOL>/examples/family_template.py`
   (the smallest passing family, commented line by line).
3. `docs/DSL_REFERENCE.md` §1-§4 (the machine language: syntax, one tick, delay, hidden vars, window).
4. `<JOB>/BATCHES/batches.txt`: your batch line, and the slot plan of its `plan` column.

## 4. Claims (parallel authors)

- Pick a TODO batch: `python3 <TOOL>/status.py --job <JOB> --brief`.
- Claim it atomically: `mkdir <JOB>/CLAIMS/<bid>`. If `mkdir` fails, the batch is taken: pick the next TODO. Then
  `echo "<your id> $(date)" > <JOB>/CLAIMS/<bid>/OWNER`.
- Fill every slot of the batch's plan. Release the claim (`rm -r <JOB>/CLAIMS/<bid>`) only when every slot has a
  full-run PASS or a `<JOB>/GAVE_UP/<bid>.s<slot>.txt` (reason + the last gate summary line).

## 5. Per slot (author loop)

1. Design one machine of the batch domain whose decision structure differs from the other slots of the batch
   (a different mechanism, not different numbers) and that makes the slot's strata load-bearing.
2. Write `<JOB>/FAMILIES/<name>.py` (GATES.md §1). Name = `<short domain word>_<mechanism>`, unique.
   `FAMILY["batch"]` = your batch id, `FAMILY["slot"]` = the slot number, `FAMILY["domain_id"]` = the batch domain.
3. Write `prose(p)` yourself, in words (GATES.md §5), in a style that varies across your families: descriptive
   identifiers (>= 3 chars) written verbatim; the prose ALONE must determine the program; no DSL syntax.
4. Draft gate (fast, skips the blind checker; never counts as PASS):
   `OMP_NUM_THREADS=2 nice -n 10 python3 <TOOL>/validate.py <JOB>/FAMILIES/<name>.py --no-x6`
5. Read the summary line and the failing checks, fix, repeat (cap the rounds, e.g. 8 per slot). Then the full run,
   the only PASS that counts: `OMP_NUM_THREADS=2 nice -n 10 python3 <TOOL>/validate.py <JOB>/FAMILIES/<name>.py`
6. Never edit a family after its PASS without re-running the full validator (the PASS is bound to the file sha256;
   `status.py` shows an edited family as FAIL).

Rules for authors: write only `FAMILIES/`, `CLAIMS/`, `GAVE_UP/` (and `REPORTS/` through the validator). Never edit
the tool, `BATCHES/`, the token file or another author's files; report a check you think is wrong instead of
patching it. Never special-case the gate, the probes or the instance order, and never weaken a family to dodge a
check by making it trivial. CPU only, one validator process at a time per author, `OMP_NUM_THREADS=2`. Labels come
only from the exact teacher.

## 6. Blind review (a different person or agent than the author)

A family is ACCEPTED only with a full-run PASS and a review verdict `OK` on the same module sha256. Per family:

1. **Blind sufficiency.** For the first 2 kept params (`<JOB>/REPORTS/<name>.json` -> `kept`), read ONLY `prose(p)`
   (print it, e.g. `python3 -c "import sys; sys.path.insert(0, '<TOOL>'); import famgate as fg;
   print(fg.load_module('<JOB>/FAMILIES/<name>.py').prose(<params dict>))"`; do not open `build()` yet) and write the
   program it determines in the rulebook text layout (docs/DSL_REFERENCE.md §2, plus the `extension mz-1x:` block
   when there is delay or hidden state), with the identifiers as written. Then run
   `python3 <TOOL>/prose_check.py <JOB>/FAMILIES/<name>.py reading_<k>.txt --params '<json>'`.
   EXACT on both = sufficient. On DIFF, open `build(p)` and list every prose gap (missing rule, wrong order, wrong
   number, failure/goal precedence, delay, hidden, chance): verdict FIX (fix the prose, never the reading).
2. **Text == code.** Title, story and docstring describe what the code does; no hidden value is stated or shown.
3. **Ambiguity.** For each plausible alternative reading of the prose, patch a scratch copy of the family, rebuild
   the 2 kept instances, and report the % of reachable augmented states (views if hidden) whose acceptable action
   set changes (`XTeacher(px).acc`, or `.I` for hidden programs, from `nagi.burst2._rt.bv2n.zoo_new.xteacher`).
   OK only at 0%, or after the prose is fixed so the alternative reading is excluded (then re-validate).
4. **Not a re-skin** of a family you know, and no forbidden token in name / title / story / domain.

Write `<JOB>/REVIEWS/<name>.json`:

```json
{"family": "<name>", "module_sha256": "<sha256 of the file you reviewed>", "verdict": "OK | FIX | REJECT",
 "prose_mismatches": [], "code_mismatches": [], "sufficiency": {"<params json>": "EXACT | DIFF ..."},
 "label_change_pct": {"<alternative reading>": 0.0}, "reviewer": "<id>"}
```

FIX = list the exact fixes; the author (or you) applies them, re-runs the full validator to PASS, and the family is
reviewed again (a review of an older sha256 shows as STALE).

## 7. Progress and output

```bash
python3 <TOOL>/status.py --job <JOB>               # per batch and slot: PASS / FAIL / GAVE_UP / TODO, claims, reviews
python3 <TOOL>/status.py --job <JOB> --manifest     # writes <JOB>/MANIFEST.json (kept instances + prose text)
```

Only `accepted: true` entries with split `train` are meant for training; `dev` families are your held-back check.
Labels for any kept instance come from the exact teacher on `build(p)` (`nagi.burst2._rt.bv2n.zoo_new.xteacher`).

## 8. Plugging in a coding agent

Any agent that can edit files and run a shell works. Give each author agent its own id and one short prompt, run
several in parallel (claims keep them apart), and use different agents for authoring and reviewing.

Author prompt (fill `<…>`):

```
You are a machine-family author. Work only inside <JOB> (absolute paths); the tool is <TOOL>. CPU only, no network,
no git commits. Read <TOOL>/GENERATE.md and follow §3-§5 exactly. Claim ONE TODO batch (mkdir <JOB>/CLAIMS/<bid>;
on failure take the next), write <JOB>/CLAIMS/<bid>/OWNER, and fill every slot of its plan: one family per slot, a
different mechanism per slot, the slot's strata load-bearing, prose(p) in your own words with every identifier
verbatim. Gate loop per family (at most 8 rounds): OMP_NUM_THREADS=2 python3 <TOOL>/validate.py
<JOB>/FAMILIES/<name>.py --no-x6 <index flags>, then the full run without --no-x6; only "FAMILY PASS" counts. After
8 failing rounds write <JOB>/GAVE_UP/<bid>.s<slot>.txt and move on. Never edit the tool, BATCHES/ or other authors'
files. Release the claim when every slot is PASS or GAVE_UP. Final message: batch id; per slot the family name,
rounds and wall minutes, or GAVE_UP + reason; any check you think is wrong.
```

Reviewer prompt:

```
You are a blind reviewer of PASSED families in <JOB>; the tool is <TOOL>. Do not read the authors' messages; use only
the family file, its REPORTS/<name>.json, <TOOL>/GATES.md and docs/DSL_REFERENCE.md. CPU only, no git. For each
family <names, or: every PASS family without REVIEWS/<name>.json>, follow <TOOL>/GENERATE.md §6 (blind sufficiency
with prose_check.py on the first 2 kept params, text == code, quantified ambiguity, re-skin check) and write
<JOB>/REVIEWS/<name>.json. OK requires EXACT on both instances. Final message: one line per family with its verdict.
```

Measure throughput on your first batches (`status.py`, plus the wall minutes the authors report) before you size a
large run.

## 9. Building an evaluation set

If some families are meant to measure a model (not train it), make them a separate job folder with separate authors
and reviewers, use `--profile benchmark` (different instance salt, up to 6 kept instances), list its domains and
mechanism words in the train job's `forbidden_tokens.txt`, never index it from the train job, and keep its files
away from anything that trains. Freeze it before you look at any model's score on it.
