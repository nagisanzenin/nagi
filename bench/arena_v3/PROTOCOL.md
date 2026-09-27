# Arena v3 protocol: realtime product benchmark (public copy)

> **Public copy of the frozen Arena v3 protocol.** Source: `docs/arena_v3/PROTOCOL.md` in Nagi's private research
> repository, at commit `b405f84` (2026-09-27 14:45 +07). That is the last change to the file: Board 1 run 2 was played
> under this text and reported at commit `699a91a`. sha256 of the unredacted source file:
> `5f7bd9dc4cc3a09f646ff50a4825e42e1457ba9d69ac57ab412906e035d6fd1a`.
>
> **Status line of the source:** a draft for the owner's freeze of 2026-09-26 23:45 +07, amended 2026-09-27 for the
> fail-first suite (§A1). §A1 supersedes the game list, the score and composite (§2.1–2.2), the §2.7 champion rule and
> the round caps wherever they conflict. The owner approved Board 1 under this protocol, and the champion rule was
> frozen in code before any Board 1 result existed (§A1.4). The approvals are digested in
> [BOARD1_DECISIONS.md](BOARD1_DECISIONS.md).
>
> **Included, with the original section numbers:** §A1 (all), §0, §1.1 (all), §1.2–1.4, §2.1–2.5, §2.7, §5, §6.2 (a)–(c)
> and §7.
>
> **Omitted:**
> - the owner summary and the file header (internal planning; the parts that still apply are restated in §A1);
> - §2.6, the cost model, which is fitted to internal job receipts;
> - §3, the internal reuse-registry tooling (summarized in one paragraph under its heading);
> - §4, the migration from Arena v2 and the internal cost planning;
> - §6.1, the game admission criteria and per-game admission status, because they describe engine and rule-variant
>   internals of the sealed games;
> - §6.2 (d) and the per-genre audit tables, an internal inventory of training data (the per-player result is §A1.8);
> - §8, the internal pre-flight record, and §9, the private file list.
>
> **Edits inside the included sections:**
> - The joint readout (one request carrying all K controls) is published as **Burst**, and "T-dual Burst" is the public
>   player name. The machine-readable player id stays `t_dual/chord`.
> - Redactions, each marked with square brackets: the seed-derivation formula (§2.3, so the sealed eval seeds stay
>   sealed), the names of excluded rule variants (§A1.1), local paths, internal job ids, the cloud provider's name and
>   its GPU-pinning syntax.
> - Links to private documents became plain text. Links to the owner's authorization record now point to the public
>   digest [BOARD1_DECISIONS.md](BOARD1_DECISIONS.md).
> - Lines starting "Public note" were added for this copy and are not part of the frozen text.
>
> File and code names in code spans (`src/…`, `scripts/…`, `tests/…`, `docs/…`) and document names such as
> BOARD1_PLAN.md, FAIL_FIRST_BRIEF.md or OVERLAP_AUDIT.json refer to the private research repository. They are cited
> for traceability and are not published. Rule ids such as R3.32 or R6.1 cite the private research handbook, and
> "AGENTS" cites the private repository's agent rules. The game engines, seeds and raw records are kept private so the
> benchmark stays sealed.

---

## A1. Amendment v3.1 (2026-09-27): fail-first suite, metrics and champion rule

This section **supersedes** the following wherever they conflict: the game list, §2.1–2.2 (score and composite),
the §2.7 champion rule, the 90 s and 75 s caps in §2.6 and §4.3, and the admission status in §6.1. Everything else
stands: the modes, the registry, the anti-gaming rules, the filler, micro-batching and the contamination rule.

Sources:
- FAIL_FIRST_BRIEF.md, Amendments 1–2;
- BOARD1_APPROVAL.md, sections "Owner go + showcase rule" (digested in [BOARD1_DECISIONS.md](BOARD1_DECISIONS.md));
- suite_manifest.json, `v3.1-draft`;
- the per-game docs SNAKE.md, ROTORWASH_RAMP.md and BOOSTER_GAUNTLET.md.

### A1.1 Suite

Every game uses realtime at 4 Hz and T_max 60 s; the runner's round cap is 62 s, which adds 2 s of grace. Weights are
1/3 each, in the order `SUITE_ORDER = (snake, rotorwash_ramp, booster_gauntlet)`.

| Game | id | Engine | 1,000-step chain (Mac arm64) | Cross-platform gate (preparation job, Linux) | Source |
|---|---|---|---|---|---|
| Snake Rush | `snake` | integer | `f1022ddc2219…` (rush-2) | must match exactly (re-run on Linux: the rush-1 Linux check is superseded) | calib-delay rush-2 (1-tick-delay ladder, FAIL_FIRST_BRIEF Amendment 3) |
| Rotorwash-Ramp | `rotorwash_ramp` | float, platform-pinned | `e35c21102343…` (unchanged by calib-delay) | the Linux chain is recorded and checked for in-process reproducibility, not compared with the Mac chain; verification and renders run on Linux x86_64 | rotorwash-ramp `b3375f1`; [two rule variants, names omitted in the public copy, are excluded from the scored variants] (ROTORWASH_RAMP.md) |
| Booster Gauntlet | `booster_gauntlet` | integer | `b5b5b8280817…` (g1.1) | must match exactly (re-run on Linux: the g1.0 Linux check is superseded) | calib-delay g1.1 (1-tick-delay ladder, Amendment 3) |

- Rotorwash v2 (`rotorwash`) stays registered with `in_suite: false`, so its v2 lockstep diagnostics (§4.1) remain
  interpretable.
- Booster Landing and Snake v1 are retired and have no v3 cells.
- The G3 multi-control exception for Snake (D9) carries over to Snake Rush.

### A1.2 Metrics (frozen before any Board 1 result; `scripts/arena_v3_report.py`)

- **Primary: paired per-seed win rate.** Two players meet on the same seed index of a game.
  - The one who fails later wins (1).
  - The same failure tick, or both censored at 60 s, counts ½.
  - Pairs use only the indices where both players have a non-void round.
  - A player's game score is its mean pairwise rate against the named opponents. The composite is the mean over
    the 3 games.
  - The rate is invariant to any monotone reshaping of a ramp, so no planner reference or floor (§2.1) is needed.
- **Secondary:**
  - the Kaplan-Meier survival curve per player and game;
  - RMST up to 60 s, which handles censoring correctly;
  - the level reached at failure;
  - ladder position: 0, 0.5 and 1 at the naive, heuristic and planner bot medians.
- **Realtime readouts,** unchanged from §1.1: decision latency, 3-vs-1-stream inflation, fresh-action share, stale
  replies and expiry resets.
- **Near-transfer flags** (§6.2, D8) are printed next to every row. They never change a rate or the champion.

### A1.3 Seeds

Seed commitments are per game (`seed_for(game, split, i)`, §2.3). Board 1 uses indices 0–9 for every player
(`seed_range [0, 10)`). Adding or retiring a game never changes another game's key.

### A1.4 Board 1 champion rule (replaces §2.7 steps 1–8)

This is frozen as `champion()` in `scripts/arena_v3_report.py`, with `tests/test_arena_v3_champion.py`. Both were
committed in `5997cf3`, before any Board 1 result existed.

1. **Candidates:** the four Nagi entries. Listed in NAGI order: ENORMOUS-old (K-call), ENORMOUS-CL (K-call),
   T-dual (K-call), T-dual (Burst).
2. **Score:** the mean over the 3 games of the candidate's mean paired per-seed win rate against the **3 external
   competitors only** (Jev, SemIf-4B, CLM-8B). Nagi-vs-Nagi pairs do not enter the score.
3. **Champion:** the highest score. Tie-breaks, in order:
   1. the higher sum over games of RMST ≤ 60 s;
   2. the higher mean level at failure;
   3. NAGI order.
4. **Label:** "Nagi champion (screen, n = 10 per game, not decisive)". The report carries a **best-of-4 caveat**:
   the champion's numbers are optimistic by selection (winner's curse), and two entries share weights. The
   champion-vs-others margins are a screen, and confirmation needs fresh seed indices (10–23 and later).
5. The internal report shows all 7 players with every pairwise rate. The champion table is printed next to it.

Public note: in Board 1 run 2, CLM-8B failed its own conformance gate before play and, under D15, was not ranked. The
rule was therefore applied against the two externals that played, Jev and SemIf-4B, and the report shows 6 players.
See [BOARD1_DECISIONS.md](BOARD1_DECISIONS.md) and [BOARD1_REPORT.md](BOARD1_REPORT.md).

### A1.5 Showcase clips (`scripts/arena_v3_render.py`, [a Linux job])

- **Public clips:** one per game, 1080×1920 at 30 fps, with audio. They show the champion plus Jev, SemIf-4B and
  CLM-8B. The subset is fixed only after results, by `showcase_players(results.json)`.
- **Seed:** a fixed rule, never cherry-picked. Take the index whose champion survival time is the lower median of
  the champion's non-void rounds (ties go to the lowest index), provided every shown player has a non-void round
  there. Otherwise take the next index in that order.
- **Verification:** every record is replayed and verified before drawing. For Rotorwash-Ramp, each seat's crash time
  and score are asserted equal to its source round.
- `--players` renders any other subset, for example an internal all-7 clip.

### A1.6 Power

The §2.5 and §2.7 power numbers were derived for the retired composite C with a planning σ of 0.1155. **They do not
transfer to the win-rate composite and were not recomputed.** Board 1 stays a screen: no "X beats Y" claim is made
from it. A decisive contrast needs a registered confirmation on fresh indices, under the §2.4 design once its σ is
re-planned from Board 1 data.

### A1.7 Cost with 60 s caps (`design_numbers.json` → `cost.board1_plan`, `cost.per_model_per_suite_look1`)

| Quantity | today / expected | mid | all rounds to cap / high |
|---|---|---|---|
| Board 1, 7 players, 3 streams per pinned H100, with gates and canary | $4.42 | $7.69 | $8.02 |
| Per player per suite (one interface, 24 seeds × 3 games, 1 stream) | $2.90 | $6.17 | $6.32 |
| Per round cap at 1 stream | | | $0.077 |

The job table, the wall-clock estimate and the runbook are in BOARD1_PLAN.md §2 and §6.

### A1.8 Contamination (refreshed OVERLAP_AUDIT.json)

| Player | Snake Rush | Rotorwash-Ramp | Booster Gauntlet |
|---|---|---|---|
| T-dual (K-call, Burst) | O2 (CL snake) | O2 (hover, hover2, crane) | O2 (hover, hover2) |
| ENORMOUS-CL | O2 (CL snake) | O2 (hover, hover2, crane) | O2 (hover, hover2) |
| ENORMOUS-old | O0 | O0 | O0 |
| Jev, SemIf-4B, CLM-8B | unaudited | unaudited | unaudited |

No pair reaches O3. The gauntlet-factory scenario `m11_rocket_landing`, which resembles Booster Gauntlet, was
rejected by the factory audit. Its repair output was never produced, and it appears in no training data (a search of
[the private repository's docs, data, configs and source, including every compressed data file]).

---

## 0. Terms

- **Player:** one weight set, one interface and one serving path. For example `t_dual/kcall` on `h100-c3-nagi-v1`.
  Two interfaces of the same weights are two players.
- **Interface:**
  - `kcall`: K sequential choice requests per decision.
  - Burst (interface id `chord`, as in the player id `t_dual/chord`): one request carrying all K controls.
  - `kcall_batched`: K prompts in one batched call.
  - `vendor_single`: one API request with all controls.
  The interface is declared before a player's first round.
- **Game version:** rules_id, a code hash (engine + rules text + prompt renderer) and a ladder hash. The frozen seed
  schedule is committed **per game**.
- **Cell:** the registry unit. It is one player × one game version × one mode × one contiguous range of eval seed
  indices.
- **Block:** 24 seed indices. Look k uses indices 0 to 24k − 1. A screen cell may cover fewer indices, for example
  Board 1's 0–9.
- **Suite version:** the set of admitted games plus the composite weights (`v3.x`). Cells outlive suite versions
  whenever their game entry is unchanged.

## 1. Modes

### 1.1 REALTIME: primary, and the only mode that ranks products

**1.1.1 Pinned serving path.** Every self-hosted player runs on an **H100, pinned [provider-specific syntax omitted]
so that the provider never upgrades it to an H200**; H200 and H100 diverged on 2 of 10 trajectories (R3.13).
- **Nagi players:** base + adapter **merged in place, bf16** (`MergedReloadLoader`). Unmerged LoRA changes near-tie
  argmaxes and adds overhead, so it is refused (R3.24).
- **Kernels:** the fused kernels must pass a preflight. The fallback-kernel path is refused: the P1 training worker
  measured 315/881 ms against 164/313 ms on the serving path.
- **Readout:** greedy argmax.
- **Pins:** SDK commit, image sha and parity ≥ 19/20 before any round.
- **Self-hosted third parties** (SemIf, CLM) use their own documented native stack on the same GPU class (§1.1.8).
- The API vendor (Jev) runs on its own hardware. The client container region is recorded.
- The serving-path id carries **streams per GPU**. Board 1 uses 3 streams for everyone (§1.1.9). Cells served at
  different stream counts are different players.

**1.1.2 Clock.** The period is T = 1000/rate ms, **4 Hz (250 ms)**. This is the native decision period of every v2
game and of the P1 realtime run. It is also the rate at which a ~200 ms model (AGENTS 4b budget) is fresh every tick.
At boundary k (wall time t0 + kT), in this order:
1. collect a reply that finished before the boundary;
2. if the player has nothing in flight, submit one decision request observing the current state s_k (never a state
   computed ahead of the clock);
3. choose the controls for tick k;
4. environment bots decide on s_k;
5. physics step.

The world never pauses for inference.

**1.1.3 Apply, staleness, hold.**
- A reply is applied at the first boundary after it finishes. Its age is (k − observed tick) × T.
- **Stale:** a reply older than 1,000 ms (4 ticks) is rejected and logged. Errors are logged and never applied.
- **Hold:** each game declares, per control, either
  - *persistent* (the last applied value is kept), or
  - *one-shot* (it acts only on the tick of its reply, otherwise neutral). Rotorwash: collective is one-shot; cyclic
    and winch are persistent.
- **Expiry:** after 1,000 ms without an applied reply, persistent controls reset to the game's declared safe default.
- **Before the first reply:** defaults.
- **One decision in flight per stream.** Once the player's craft is done, the remaining environment ticks are
  fast-forwarded with identical physics. These constants are the frozen P1 protocol
  ([the P1 realtime script, private]), unchanged.

**1.1.4 Latency.** Latency is measured on the serving path, end to end: from the observation snapshot to the moment
the harness has the choices. It includes prompt rendering, tokenization, the forward pass(es), the readout and, for
an API, the HTTP round trip.
- Per request, record: observed tick, submit/finish time, `prepare_ms`, `infer_ms`, `latency_ms`, age, status
  (applied/stale/error), choices, probabilities and prompt sha.
- Per tick, record: lag and control source (fresh/held/expired/default).
- Report per player: p50/p90/p99 decision latency, the fresh-action share of live ticks, the distribution of applied
  age, and stale/error counts.
- Latency is **never subtracted or normalized away**. It is part of the product (R3.32).
- Latency measured inside a training worker is never used (R3.32 guard).

**1.1.5 Void-round rule.** A live boundary processed more than **100 ms** after its target voids the round. The
round is kept, not scored.
- A void round is re-played **once**, under a fresh job id, with the same seed. The rule is fixed before any data,
  independent of outcome.
- If it is void again, that seed index is void for the cell. It is dropped from every contrast with that cell, in
  **both** arms (R3.4).
- More than 1 void per 24 rounds (at most 1 in a 10-round screen) invalidates the cell. That is a harness defect: fix
  it and re-run the whole range.
- Void counts are reported per arm. Voids in one arm only are investigated as bias (R3.17).
- **Harness (fix of 2026-09-27, HARNESS_FIX.md).** Board 1's voids were this defect: the one-loop
  runner fast-forwarded a finished Rotorwash-Ramp round (~170 ghost ticks, ~0.5 s of CPU) inline and stalled the other
  slots' boundaries. Realtime play now runs one process per stream slot (`src/arena/v3/streams.py`): round states are
  built before their clock starts, fast-forward / record / GC run only in a stream's slack, and the model or API
  client stays in the job's main process. The rules above are unchanged, and records equal the old loop's
  (`tests/test_arena_v3_streams.py`). The CPU soak (`scripts/arena_v3_soak.py`, 0 voids) runs in [the preparation
  job] before any GPU job.

Public note: "Board 1's voids" above are those of Board 1 run 1, which was stopped for this defect and never pooled
with run 2. Run 2 had 0 void rounds. See [BOARD1_DECISIONS.md](BOARD1_DECISIONS.md).

**1.1.6 Records and replay.** Records use the V2 format. `decisions` holds the **applied** controls of every tick,
so `arena.core.replay_actions` reproduces the round without inference. Every record carries the platform stamp. The
in-job verifier replays every record, and a mismatch marks the round `replay_failed`, which is refused downstream.

**1.1.7 Warm-up and canary.**
- Before the first scored round: parity, reference replay of 4 frozen records, and ≥ 20 warm-up forwards on dev-split
  prompts.
- The canary is one player, one game, 1 round. It runs first. Two canary failures stop the campaign (Board 1 rules).

**1.1.8 Vendors and third-party models.**
- **Jev (API):**
  - pinned `jev-1.13.0`, interface `vendor_single` (one request with all controls, the P1 plan);
  - never run live before, so it needs its own canary round (R3.25, UNVERIFIED);
  - one attempt per request, fixed timeout, failures take the default (R3.16);
  - **API latency counts**, because that is the product reality;
  - **network jitter is recorded, not subtracted:** a TCP-connect RTT probe to the API host every 10 s during play
    (p50/p90/p99 in the cell), the client region, and a **vendor fingerprint** (sha of the answers to 8 fixed dev
    prompts, run at bench time). Before a Jev cell is reused in a new contrast, re-run the fingerprint
    (≈ $0.0005). If ≥ 2 of 8 answers differ, the vendor has changed and the cell is historical.
- **SemIf-4B:** native Qwen3.5-4B, `semif_phase1.direct.score` (private harness code), bf16, 4,096-token
  limit, argmax with ties to the first option. It runs on the pinned H100. Its published path uses eager attention;
  see D14.
- **CLM-8B:** specified in §1.1.10.

**1.1.9 Concurrency: 3 streams per GPU (Board 1, owner decision) and the filler load.**
- A GPU job serves exactly **one player at a time**, with **3 stream slots**.
- Slot g (g = 0, 1, 2) plays game g: 0 = Rotorwash, 1 = Booster, 2 = Snake. It plays the player's rounds on seed
  indices 0, 1, 2, … in order, each round on its own 4 Hz clock.
- When a slot has no live round (between rounds, after the player's craft is done, or after its queue is finished
  while another slot still plays), it runs the **filler**.

The filler is a **shadow realtime stream**:
- It has the same 4 Hz boundary clock and the same submit rule ("at a boundary, if nothing is in flight, submit").
- It uses the same interface: K-call sends 3 sequential requests per decision, Burst sends 1.
- It sends the same kind of prompt: the next entry of a frozen list of **200 filler prompts per (game, interface)**.
  The list is rendered on CPU from **dev-split** states of the L2 ladder bot, its sha256 is committed in the job
  config, and it is cycled in order.
- Filler replies are never applied, never scored and never shown to the player. Filler requests are logged (count,
  latency) as an in-job load record.

So at every instant of live play, every self-hosted player's GPU has exactly **three request streams following the
same arrival rule, the same interface, and prompts from the same frozen distribution.** This holds whether a slot is
live or filler, and it does not depend on how long the player survives.

**Micro-batched serving (owner fairness decision, BOARD1_APPROVAL; see [BOARD1_DECISIONS.md](BOARD1_DECISIONS.md)).**
Under 3 streams a batch-1 server runs the streams' forwards one after another (~3× latency: Nagi ~130 → ~390 ms,
beyond the tick) while vLLM batches them. Every self-hosted player therefore serves its streams with request
micro-batching: one right-padded forward over the requests pending within ≤ 5 ms, per-row readout at each row's own
last/slot positions, deterministic row order (`src/arena/v3/microbatch.py`; SemIf in `competitors_v3`; vLLM natively
for CLM). K-call stays K sequential calls per decision; Burst stays one row. Canary gate, same rule for every player:
argmax agreement ≥ 0.99 vs batch 1 and max |Δlogit| ≤ 2F (F = the BF16 noise floor from +64 right pads); failure means
STOP for the owner, never a 1-stream fallback.

Public note: on 2026-09-27 the owner made this gate tie-aware (disagreements count only on decisive pairs); see
[BOARD1_DECISIONS.md](BOARD1_DECISIONS.md).

**Why the load is identical across players.** The offered load is a function of (slot count, submit rule, interface,
prompt list). All four are frozen and the same for every player of a given interface. Skill cannot change it: when a
craft dies, its slot switches to filler with the same process. What differs between players is only their own
service time, which is the latency being measured.

Guard: the realized number of streams in flight at each submit is recorded, and the analysis asserts that it is 3
throughout play for every self-hosted player.

- **Jev:** the API player runs 3 client-side streams with the same filler rule, so its client-side offered load has the
  same structure. Its server-side load is the vendor's and is disclosed as such.
- **Latency-inflation measurement (every player, every job):** before play, 30 s of one stream (1 slot, 2 idle) is
  followed by 30 s of 3 streams, all on filler prompts. Inflation = p50(3 streams) / p50(1 stream), with a
  request-cluster bootstrap CI. Report it per player next to the in-play p50/p90.

**1.1.10 CLM-8B integration** (`Contrastive-LM/CLM-v0.1-8B`, Apache-2.0: a frozen Qwen3-8B plus projection heads
that score candidate actions and return probabilities; served with vLLM; the vendor claims 16.5–80 ms, UNVERIFIED).

The adapter, `CLMAgent(core.Agent)`, is to be written in `src/arena/agents_vendor.py`; it is not written yet. It maps
one `Query` (a Choice question: text, options, default) to one CLM scoring call:
- context = `query.text` byte-for-byte, the same state and rules text Nagi receives, plus the same per-key instruction
  line (`agents_nagi.INSTRUCTIONS`, as for SemIf/Jev);
- candidates = the option ids in the query's canonical order, each rendered with the same option text Nagi sees;
- reply = argmax of the returned probabilities, ties to the first option (the SemIf convention). `last_probs` is kept.

**Does it map 1:1 to our option sets?** Only if all four conditions below hold. They are to be checked on CPU by
reading the model repo's inference code and config before any GPU job (UNVERIFIED tonight: no network use in this
task).
1. It accepts an arbitrary candidate list of size 2–6 per call (our sets are 2–6 options).
   *If it only scores a fixed action vocabulary, there is no 1:1 map and CLM is excluded (owner).*
2. It returns one score per candidate. If the scores are unnormalized logits or independent pairwise scores, the
   adapter applies a softmax over the given set and records the raw scores.
3. Its context limit is ≥ our longest prompt (K-call ~680, Burst ~909 tokens). **Zero truncation**, fail-closed per
   query (R3.17).
4. Scoring is deterministic: the same input gives bit-identical probabilities on 2 calls.

**Interface.** CLM has no joint (Burst-style) readout, so it plays **K-call**. If one vLLM request can score the K
control queries of one state, it plays `kcall_batched`, declared before play. That is its native efficient path, and
it parallels Nagi's options.

**CLM canary** (inside its first job, before scoring): 20 fixed dev queries with a valid option on 20/20,
probabilities summing to 1 ± 1e-6, bit-determinism on a repeat, tokens under the limit, p50 latency.

Public note: the text above was written before the adapter existed. In Board 1 run 2, CLM-8B failed its own
conformance canary before play and was not ranked (D15); see [BOARD1_DECISIONS.md](BOARD1_DECISIONS.md).

### 1.2 LOCKSTEP: diagnostic, on demand only

The clock pauses during inference, so there is no latency effect. It measures decision quality alone and is used to
localize a realtime gap: decision quality vs latency (R3.32). Records are replayable and deterministic.
- It runs only when an owner ticket names a question, for example "why did X drop in realtime?".
- Its cells are `DIAGNOSTIC` in the registry and never rank.
- Cost per round, from receipts: K-call $0.061–0.082, Burst $0.021 [receipt job ids omitted].

### 1.3 COMPUTE-MATCHED LOCKSTEP: interface comparisons

Plain lockstep favours K-call with 3 forwards per move against Burst's 1 (P1 §9.1b). Compute-matched lockstep gives
every arm exactly **F forwards per tick** (`forwards_per_tick` is in the cell key):
- **F = 1:** Burst (1 forward, all K controls) vs **K-call round-robin** (one control per tick in a fixed rotation;
  the others follow the game's hold rules).
- **F = K:** K-call (K forwards) vs **Burst order-ensemble** (K forwards on K rotated slot orders, mean probability
  per slot). This is also the P2 fix candidate for the 26% order flips.

It is used only for interface decisions (Burst vs K-call; batched readouts). It is deterministic, cells are
`DIAGNOSTIC`, and the cost is lockstep cost × F.

### 1.4 Latency-quality curve at 4 Hz and 8 Hz: not worth its cost by default

- **Cost.** Realtime cost is world-clock seconds, so a second rate is a second full pass. That is **+$2.90 to $8.97
  per player per suite** at 1 stream (§2.6, not in this copy), which doubles the per-player cost.
- **Validity.** Changing the rate changes the game.
  - One-shot controls (Rotorwash collective) get twice the authority per second at 8 Hz.
  - The bots decide twice as often.
  - The 8 Hz version therefore needs its own ladder calibration and its own game version (the rate is in the cell
    key). It would not be a point on the same curve.
- **Information.** Today's players answer in 164 ms (Burst) or 313 ms (K-call), both slower than 125 ms. At 8 Hz both
  are late on every tick, so the curve would mostly re-measure latency the 4 Hz run already records per request.
- **Verdict.** Run 8 Hz **only on demand**:
  - (i) when a player's p90 decision latency is < 125 ms, so 8 Hz becomes reachable; or
  - (ii) when the product decision is itself the tick rate.
- **Cheaper alternative for "how much does latency cost us?":** *delay-injected lockstep*. At 4 Hz, apply at tick k
  the action computed on s_(k−d), for d ∈ {0, 1, 2}. It is deterministic, cross-platform exact for fixed-point games,
  and isolates the latency effect at fixed physics. It costs one lockstep pass per d.

## 2. Estimands, statistics, power, cost

### 2.1 Per-game absolute score (lineup-independent)

Public note: superseded for Board 1 by the paired win rate (§A1.2). Kept because §A1.2 and the design refer to it.

Game g, eval seed i, one round:
- **raw score** y_(g,i) ≥ 0, defined by the game. Rotorwash: metres flown + 500 × deliveries.
- **reference** y^ref_(g,i) = the top ladder level (CPU planner; Rotorwash `rw3_mission`) on the same seed. A game
  may instead freeze its own ladder map into [0, 1] at admission (G2). Snake maps points piecewise-linearly through
  the ladder anchors a1/a2/a3 (`arena.games.snake.score`, SNAKE.md). Bots
  compute synchronously at tick boundaries, so the reference is a zero-latency ideal. This is deliberate: the realtime
  score includes what latency costs.

s_(g,i) = min(1, y_(g,i) / max(y^ref_(g,i), f_g)), with f_g a floor fixed at admission (Rotorwash 100 m, v2 R).

**Estimand:** S_g = E_i[s_(g,i)]. The population is game g's sealed v3 eval seeds, base rules, primary sensors,
realtime 4 Hz and the pinned serving path.

Also reported:
- the uncapped ratio;
- the reference-normalised N_g, with random = 0 and reference = 1 (v2 §2.3);
- the ladder anchors (L1 naive, L2 heuristic) on the same scale.

Ladder bots never interact with the player (admission G1), so the normalisation is post hoc. A ladder change
therefore means rescoring from records, with no GPU needed.

### 2.2 Composite

Public note: superseded for Board 1 by the win-rate composite (§A1.2).

- **C = Σ_g w_g S_g, with w_g = 1/3.** The weights are fixed at suite freeze and never data-driven: each machine
  skill counts equally.
- **Clean composite C_clean (secondary, owner D8):** the same, restricted to the games where the player has no O2
  in-domain flag (§6.2), with weights renormalised. It is a secondary readout; C over all games is the headline.
- The **unit of independence** is the seed index i (the triple of per-game seeds). Contrasts are paired on i:
  d_i = c_(A,i) − c_(B,i), with c_i = Σ_g w_g s_(g,i). Per-game seed lists are independent by construction, so
  Var(Σ w_g d_g) = Σ w_g² σ_g² (A0; corr(dR, dL) = +0.25, p 0.23, was noise in v2).
- Every table prints S_g, survival, latency, fresh share and void counts next to C (R3.28). A composite gain that
  hides a component loss larger than its CI half-width is a trade-off, not a win.

### 2.3 Seeds and looks

- **Seeds:** [the derivation of a seed value from (game, split, index) is omitted in the public copy, so the sealed
  eval seeds stay sealed; it is a fixed, deterministic function of those three inputs, committed before any data].
- **Splits per game:** dev 72 (harness, prompt debugging, filler), calib 32 (ladder), eval 72 (sealed, 3 blocks of
  24), variant_sealed 36.
- The commitment is **per game**, so admitting a new game never changes an existing game's key. Rotorwash:
  `c981d05b…`.
- The seeds are disjoint from all 558 v1/v2 seeds; this is checked by `seeds` and in the tests.
- v2 eval indices 0–23 are opened (dev forever, R3.8), so v3 uses fresh seeds at no extra cost: every player is
  re-run in realtime anyway (§4).
- **Looks** for a registered contrast: n_k = 24, 48, 72, i.e. blocks 1..k of both arms. H = 1 stratum, because
  single-agent games have no opponent-level strata.

### 2.4 Decision contrasts: group-sequential, t-matched

- **Statistic:** T_k = d̄_k / (s_k/√n_k). The first k with |T_k| ≥ c_k^t decides.
  - Classic O'Brien–Fleming, K = 3, two-sided α = 0.05, C_B = 2.00404, gives z bounds 3.4711/2.4544/2.0040.
  - t-matched: c_k^t = t⁻¹_(n_k−1)(Φ(c_k)) = **4.0329 / 2.5495 / 2.0401** (df 23/47/71).
  - The same formula at H = 3 reproduces the handbook's 4.0945/2.5539/2.0411 (a test).
- **Decision sentences cite the repeated CI** d̄_k ± c_k^t s_k/√n_k (simultaneous 95%). A sign-flip p is printed
  beside it (R3.5).

**Simulated α** (200k runs, estimated SE):

| Rule | α |
|---|---|
| t-matched, Gaussian null | **0.0498** (MC-SE 0.0005) |
| normal c with estimated SE (not used) | 0.0560 |
| t-matched, empirical lumpy null from the 5-seed realtime pilot (centred, sign-flipped) | **0.0506** (MC-SE 0.0007), inside 0.05 + 2 MC-SE |

Before a look-2 is opened, re-run this with the block-1 differences of that contrast. If α > 0.0514, switch to the
null-restricted SE with normal c (R3.10).

**Non-binding equivalence stop** (k ≥ 2, when the repeated CI lies inside (−δ, δ)), with a proposed δ = 0.05 on C
(D4):
- feasible at look 2 (n > 34.7), not at look 1 (n > 86.7);
- P(stop for equivalence by look 2 | θ = 0) = 0.35, by look 3 = 0.89;
- E[n | θ = 0] falls from 71.7 to 63.2;
- P(false equivalence | θ = δ) = 0.023.

**Reuse and looks.** A contrast's decision is a deterministic function of the blocks, **evaluated look by look in
order**. Blocks that already exist for other reasons add no extra looks: once a look crosses, later blocks are not
used. Each decision contrast (arms, family, δ, commit) is registered before its look-1 data are opened. Holm applies
within a declared family. Board adjacency and all unregistered contrasts are descriptive (R3.7, R3.8).

### 2.5 MDE and power (80%, two-sided 0.05; `design_numbers.json` → `mde_*`, `screen_n10`)

Public note: these numbers are for the retired composite C and do not transfer to the win rate (§A1.6).

Planning σ_d:
- per game 0.20 (lockstep R contrasts, SE 0.031–0.041 at n = 24);
- composite 0.1155 = 0.20·√3/3;
- sensitivity 0.0955 (realtime pilot σ_R 0.046 plus 0.20 for the two new games);
- sensitivity 0.1486 (v2 A2 σ_d 0.182 spread over 3 games).

| n per game | fixed-n MDE, σ units | OBF stop-by-look MDE, σ units | **C, fixed-n** (σ 0.1155) | C, stop-by-look | C range over σ 0.0955–0.1486 (fixed) | one game, σ 0.20 (fixed) | Rotorwash realtime σ 0.046 (fixed) |
|---|---|---|---|---|---|---|---|
| **10 (Board 1 screen)** | 0.996 | — | **0.115** | — | 0.095–0.148 | 0.199 | 0.046 |
| 24 | 0.598 | 1.014 | **0.069** | 0.117 | 0.057–0.089 | 0.120 | 0.027 |
| 48 | 0.413 | 0.492 | 0.048 | 0.057 | 0.040–0.061 | 0.083 | 0.019 |
| 72 | 0.335 | 0.338 | 0.039 | 0.039 | 0.032–0.050 | 0.067 | 0.015 |

- E[n] with no equivalence stop: 71.7 at θ = 0, 61.2 at θ = MDE_72, 28.8 at θ = MDE_24.
- Re-estimate σ_d at every look. If it is outside the planning range, recompute power before paying (R3.11).
- Effects seen so far, for scale:
  - realtime Burst − K-call ΔR +0.049 (5 seeds);
  - lockstep T-dual − ENORMOUS-old ΔR +0.127;
  - lockstep A2 contrasts within ±0.08.

### 2.6 Cost per player per suite

[Not included in the public copy: the cost model, fitted to internal job receipts.]

### 2.7 Board 1: the champion screen (FROZEN rule; owner roster 2026-09-26)

> **Superseded for Board 1 by §A1.4** (champion rule vs the 3 externals on the paired win rate) and §A1.6 (power).
> The text below is kept as the historical record of the composite-based rule.

**Purpose.** (1) Pick a Nagi champion among the 3 ENORMOUS weight sets. (2) Position Nagi against Jev, SemIf-4B and
CLM-8B.

**Design:**
- 10 seed indices (0–9) per game × 3 games, the same indices for every player;
- realtime 4 Hz;
- 3 streams per pinned H100 with the filler (§1.1.9).

These are screen cells `seed_range [0, 10)`. Completing look 1 later adds `[10, 24)`; the registry forbids
overlapping ranges.

**Power statement (frozen).** At n = 10 paired seed indices per game, composite planning σ_d = 0.1155:
- MDE80 = **0.115** (range 0.095–0.148 over the σ sensitivity);
- the paired 95% CI half-width is **±0.083**;
- power is **0.23 at Δ = 0.05** and 0.69 at Δ = 0.10;
- for one game (σ 0.20): MDE80 0.199, half-width ±0.143.

P(the argmax picks the true best), by the true leader's gap over the others:

| Leader's true gap | 0.02 | 0.05 | 0.10 |
|---|---|---|---|
| P(correct pick), 4 candidates (Board 1) | 0.48 | 0.81 | 0.99 |
| P(correct pick), 3 candidates | 0.57 | 0.85 | 0.99 |

Random picking would give 0.25 with 4 candidates. **Board 1 is a screen, not a decision.** No "X beats Y" claim is
made from it.

**Champion rule (frozen before any Board 1 data):**
1. **Candidates (D12, orchestrator default before any data):** all four Nagi entries: ENORMOUS-old (K-call),
   ENORMOUS-CL (K-call), T-dual (K-call) and T-dual (Burst). Realtime is the product metric and Burst led T-dual's
   realtime probe, so pre-selecting K-call would be unjustified and pre-selecting Burst post hoc. **Best-of-4
   caveat:** the winner is the max of 4 noisy estimates. Its C is optimistic, and two entries share weights, so their
   errors are correlated.
2. Compute C for each candidate over the non-void indices common to all candidates.
3. The leader L is the candidate with the highest C.
4. The contest set T is L plus every candidate j whose paired 95% t CI (df = n − 1) for C_L − C_j contains 0. The
   sign-flip p is printed as well.
5. If T = {L}, L is the champion.
6. Otherwise choose within T, in this order:
   - (a) the candidate whose median decision latency is ≥ 10% below every other member's, with the round-bootstrap
     95% CI of the ratio excluding 1;
   - else (b) the candidate whose serving GPU-s per decision is ≥ 10% below every other member's, by the same rule;
   - else (c) L.
7. **Label:** "Nagi champion (screen, n = 10 per game, not decisive)". State that the champion's C is optimistic by
   selection (winner's curse). It becomes decisive only through a registered confirmation contrast on indices 10–23
   and later blocks (§2.4).
8. Also report C_clean as a secondary readout (§6.2, owner D8). It never changes the champion.

**Positioning:** paired, descriptive contrasts of champion − {Jev, SemIf-4B, CLM-8B}, T-dual Burst − T-dual K-call
and each ENORMOUS pair, with 95% t CIs. Each row carries its near-transfer and exposure flags, its latency and its
latency inflation.

**Cost:** Board 1 is **expected $4.42, mid $7.69, high $10.49** (cloud GPU + Jev API, including the one-round canary,
its replay gate, the micro-batching parity gates, CLM staging and canary; job list in BOARD1_PLAN.md). At 1 stream per
GPU the same board, without the canary, would cost $7.94 / $16.06 / $22.99.

## 3. Reuse registry

[Not included in the public copy: internal registry tooling. Summary: an append-only registry of cells keyed by
player, weights, interface, serving path, game rules/code/ladder, seeds, protocol and mode; a cell whose key no longer
matches is re-run, re-verified by replay, or rescored from records, and is never silently reused.]

## 4. Migration from v2

[Not included in the public copy: migration from Arena v2 and internal cost planning. Every player was re-run in
realtime on the v3 games; no Arena v2 result is pooled with Arena v3.]

## 5. Anti-gaming and fairness rules (binding for every cell)

- **AG1 No Arena game in training.** No state, trajectory, record, rules text, render or seed of any admitted v3 game
  (any split) may enter any of the following:
  - training;
  - data generation;
  - closed-loop or DAgger rollouts;
  - teacher prompts, or prompt or format tuning.
  Generators assert that game markers are absent (the closed-loop precedent, `docs/closed_loop_data/PLAN.md:83`), and
  the batch lists name the Arena games as forbidden (the GLM brief precedent).
- **AG2 In-domain genres** are audited and flagged (informational, owner D8). O3 contamination is forbidden (§6.2).
- **AG3 Sealed eval seeds.**
  - The eval split is used only by board cells. All harness, prompt, filler and render debugging uses dev; the ladder
    uses calib.
  - The per-game schedule sha is committed at freeze.
  - Data tools refuse v3 eval seeds (guard function, to be added with the v3 runner).
  - Optionally, an owner salt, committed by its sha (D7).
- **AG4 Frozen bot ladder.** The ladder is part of the game version (ladder sha). It changes only through the
  extension rule, and then every cell is rescored and both versions are reported. It is never tuned after seeing
  player results.
- **AG5 One frozen prompt renderer per game version, byte-identical for every player.** There is no per-player prompt
  engineering. The interface is declared, with a primary, before the first round.
- **AG6 One attempt per seed.** No outcome-conditioned reruns. The void rule is fixed (§1.1.5). A cell is complete or
  invalid: no partial ranges, and no stopping a range because of its scores.
- **AG7 Pinned serving path** (pinned H100 for every self-hosted player, same streams and filler, same tick rate). The
  API vendor runs on its hardware, with the client region disclosed.
- **AG8 Latency counts as served.** It is never subtracted. Harness overhead is identical for all players, and tick
  lag > 100 ms voids the round.
- **AG9 Deterministic readout** (argmax, temperature 0, fixed tie rule). For a vendor, its deterministic setting, or
  disclosed nondeterminism plus the fingerprint.
- **AG10 Append-only registry.** The analysis refuses rows that are not FRESH cells.
- **AG11 Registered contrasts only for claims.** No "beats Jev" claim without a registered, paired, frozen-suite
  contrast that crosses its boundary (AGENTS; R3.25). Board 1 makes no such claim.
- **AG12 No selection over checkpoints or interfaces on eval seeds.** Checkpoint choice uses dev seeds. The board uses
  the pre-declared primary interface, and a max over interfaces is labelled as a selection.
- **AG13 Exposure declaration** in every cell: training-data manifest sha plus the overlap audit id. Vendors are
  `UNAUDITED`.
- **AG14 No guardrail or harness code change during a run.** Engine or harness edits after freeze go through
  NEEDS_REVERIFY. Any change that alters prompts or tick hashes creates a new game version.

## 6. Game admission criteria (game-agnostic) and the contamination rule

### 6.1 Criteria a game must meet before any cell of it is benched

[Not included in the public copy: the admission criteria and the per-game admission status describe engine and
rule-variant internals of the sealed games. The fail-first suite in §A1.1 is the admitted suite for Board 1.]

### 6.2 Training-overlap and contamination rule

**Overlap levels.** Four facets are scored for each (Arena game, training genre) pair:
- **controls:** same control roles, e.g. thrust / tilt / winch;
- **dynamics:** e.g. gravity + thrust vertical flight;
- **task phases:** e.g. approach → hook → carry → place / land;
- **objective / scoring.**

| Level | Meaning |
|---|---|
| O0 | no facet shared |
| O1 | domain only, or 1 facet |
| **O2 near-transfer** | ≥ 2 facets |
| **O3 same-engine** | the genre uses the Arena engine, a port of it, a re-skin, or states derived from it |

**(a) Audit.** Every admitted game is checked against **every** training genre: [the source list is omitted in the
public copy; it covers the multi-action genres, the closed-loop genres, the Gauntlet genres, every generated-data batch
list, and every future generator].

Method, all CPU, $0:
1. Facet scoring by an agent that did not build the game.
2. A lexical check: 8-gram overlap of the rules texts.
3. Engine provenance: imports, and the "engine origin" column of the CL table.

Output: `docs/arena_v3/OVERLAP_AUDIT.json`, keyed by game code sha and genre version. It is re-run when a game or
genre changes.

**(b) Flag.** A player's exposure on game g is the maximum level over the genres in its training-data manifest, with
row counts.
- Cells carry `overlap_level`, `overlap_genres` and `near_transfer` (O2/O3). The validator enforces consistency.
- The board prints a ⚑ next to every flagged score.
- O3 scores are shown but excluded from C and C_clean, and from ranking on that game.

**(c) Owner decision D8 (2026-09-27): in-domain training is intended.** Nagi's data trains models to operate complex
machines, so similar tasks are the point.
- O2 genres (hover, hover2, crane, closed-loop snake) are **not sealed** from training. The O2 flag is informational.
- The headline C and the champion rule include all games for every player. C_clean is a secondary readout.
- **O3 stays forbidden:** Arena engines, Arena seeds or states, same-engine clones (AG1).
- The report adds an "in-domain training" column per game and player, and calls Booster's new skills (no-hover
  hoverslam, multi-phase descent, relights) the **less-seen probe**.
- A causal claim that a gain is general (not in-domain) still needs a genre-ablation arm.

**(d) Rotorwash record, and the audit result tables.** [Not included in the public copy: an internal inventory of
training data. The per-player, per-game result for the Board 1 suite is §A1.8: no pair reaches O3.]

## 7. Decisions for the owner (recommendation first)

| # | Decision | Recommendation |
|---|---|---|
| D1 | Freeze v3.0 with per-game cells (Rotorwash admitted now; Booster and Snake on admission). The composite is published once all 3 are admitted. | **Yes** (orchestrator default) |
| D2 | Default bench per player after Board 1: one 24-seed block per game; blocks 2–3 only for registered contrasts | Recommend **yes** ($2.90–8.97 per player per suite). Deferred to the owner. |
| D3 | Composite weights: equal 1/3 | **Yes** |
| D4 | Equivalence margin for decision contrasts: δ = 0.05 on C (reachable at look 2) | Recommend **yes**. Deferred to the owner. |
| D5 | 8 Hz curve: on demand only (§1.4) | **Yes** |
| D6 | Primary sensors: **L0** for new games (no option-ranking sensor lines); Rotorwash L0 ≡ L1 | **Yes** (orchestrator default) |
| D7 | Seeds: public derivation + guard (default), or an owner-secret salt committed by sha | **Public + guard** |
| D8 | Seal O2 genres from future training? | **Owner decided (2026-09-27): no.** In-domain training is intended; O2 is informational; O3 stays forbidden |
| D9 | Snake's G3 exception (1 control) | **Confirm**; equal weight |
| D10 | Rotorwash float engine grandfathered, Linux-pinned (not ported) | **Yes**; a port re-benches everything |
| D11 | Jev interface: `vendor_single` (never run live; canary round first) | **Yes** |
| D12 | T-dual's candidate interface in the champion rule | **Orchestrator default: all four Nagi entries compete** (best-of-4 caveat reported) |
| D13 | Board 1 cap $12.00, stop $11.00, 7 GPU slots (BOARD1_APPROVAL; see [BOARD1_DECISIONS.md](BOARD1_DECISIONS.md)) | Already approved |
| D14 | SemIf kernel path: published eager, or sdpa if parity ≥ 19/20 vs eager (best path of every player) | **sdpa if parity passes**, else eager, disclosed (orchestrator default) |
| D15 | CLM excluded if its scorer cannot take our candidate sets 1:1 (§1.1.10) | **Yes**, and the exact reason is reported (orchestrator default) |

Public note on D7: this public copy omits the seed derivation (§2.3) as a precaution, because the game engines are
not published and the eval seeds stay sealed.

## 8. Pre-flight record

[Not included in the public copy: the internal pre-flight record (handbook cards applied, re-derivations and open
items at the time of writing).]

## 9. Files

[Not included in the public copy: the list of private files.]
