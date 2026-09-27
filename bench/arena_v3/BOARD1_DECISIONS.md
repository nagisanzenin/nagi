# Arena v3 Board 1: preregistered decisions and stop log

> **Public digest, not a copy.** It summarizes two private records in Nagi's research repository, both at commit
> `699a91a` (2026-09-27 17:11 +07, the Board 1 run 2 report commit):
> - `docs/arena_v3/BOARD1_APPROVAL.md`, the owner's authorization and the decisions made during the run
>   (sha256 `d4e7c6df74d2c17b51ec4228f087dfd1f25109781d4a19def8f55c88292bfc06`);
> - `docs/arena_v3/BOARD1_STOP_20260927.md`, the log of the two stops of run 1
>   (sha256 `3df51593355ba3bef85c8adbe871ede13324fa539cb5fd4369b7f6f3d2690dd7`).
>
> Left out: cloud provider, job and app ids, spend-guard and watchdog internals, account figures, local paths, and
> per-job dollar amounts (one total is given at the end). Owner quotes are paraphrased in English. Players carry their
> public names; the joint-readout entry is **T-dual Burst** (machine-readable id `t_dual/chord`). All times are
> 2026-09-26/27, UTC+7. The rules themselves are in [PROTOCOL.md](PROTOCOL.md) and the results in
> [BOARD1_REPORT.md](BOARD1_REPORT.md).

## Summary

- Board 1 is a **screen**: 10 seed indices (0–9) per game, 3 games, realtime at 4 Hz. It picks a Nagi champion among
  four entries and places it against external competitors. It makes no "X beats Y" claim.
- **Run 1** was stopped twice. First, a serving-parity gate failed on near-ties (fixed by an owner rule change before
  any scored round). Then a harness defect voided many rounds, which invalidated nearly every cell. Run 1 is historical
  and **never pooled** with run 2.
- **Run 2** played 6 players × 3 games × 10 seeds = 180 rounds, with 0 void rounds and exact replay of every record.
  CLM-8B did not play: it failed its own conformance gate before play and, under the preregistered decision D15, is
  not ranked.
- The frozen champion rule selected **T-dual Burst**. Its confirmation on fresh seeds is a separate preregistered
  run: [BURST_PREREG.md](BURST_PREREG.md). It passed: [BURST_CONFIRMATION.md](BURST_CONFIRMATION.md).

## 1. Frozen before any Board 1 result

### 1.1 Scope and roster (owner authorization, 2026-09-26 ~23:25; re-authorized 2026-09-27 ~11:15)

- **Mode:** realtime is primary and the only mode that ranks (PROTOCOL §1.1). A decision every 250 ms; the world never
  pauses for a model.
- **Suite:** the three fail-first games, Snake Rush, Rotorwash-Ramp and Booster Gauntlet. Each round is capped at 60 s
  with six 10-second levels. The first authorization named the earlier games (Rotorwash, Booster Landing, Snake); the
  owner switched to the fail-first suite at 11:15, before Board 1 was dispatched. Legacy Rotorwash v2 is not in
  Board 1.
- **Rounds and seeds:** 10 rounds per game per player, on seed indices 0–9, identical for every player. Seed
  commitments are per game (PROTOCOL §A1.3).
- **Planned roster of 7:** four Nagi entries (ENORMOUS-old, ENORMOUS-CL, T-dual K-call, T-dual Burst) and three external
  competitors (Jev through its API, SemIf-4B and CLM-8B, both self-hosted).
- **Serving:** every self-hosted player on the same pinned H100 class, 3 concurrent game streams per GPU, identical
  offered load via the filler stream (PROTOCOL §1.1.9). Jev's realtime client timeout is 1.1 s, the latest reply that
  can still be used.
- **Owner instruction:** as cost-efficient as possible while keeping the game fair.

### 1.2 Fairness fix: micro-batched serving for every self-hosted player (2026-09-27 ~00:20)

- **Finding:** under 3 concurrent streams, batch-1 players (Nagi, SemIf-4B) run their forwards one after another, about
  3× the latency (Nagi ~130 ms → ~390 ms, beyond the 250 ms tick), while CLM-8B's vLLM server batches them. Uniform 3
  streams was therefore not fair as first implemented.
- **Rule:** every self-hosted player serves its 3 streams with request micro-batching (one padded forward over the
  requests pending within ≤ 5 ms, per-row readout, deterministic row order). This is also the realistic product
  serving mode.
- **Gate:** before play, batched answers must match single-request answers (argmax agreement ≥ 0.99, logit difference
  within the bf16 noise floor). A failure means STOP for the owner, **never a fallback to 1 stream**.
- A batched CLM-8B variant would be diagnostic only, never ranked.

### 1.3 Protocol decisions (PROTOCOL §7)

Made by the orchestrator while the owner was asleep, within the approved scope and with no extra spend. The owner could
overturn them.
- **D1** freeze v3 with per-game results: yes.
- **D6** new games use prompts without sensor hint lines: yes.
- **D12** champion candidates: all four Nagi entries compete, with the best-of-4 caveat reported. Pre-selecting K-call
  would be unjustified because the joint readout led T-dual's realtime probe, and pre-selecting the joint readout would
  be post hoc.
- **D14** SemIf-4B may use the faster sdpa attention path only if it matches the published eager path on ≥ 19/20
  parity checks.
- **D15** CLM-8B is dropped from the ranking if its scorer cannot map 1:1 to our option sets, and the exact reason is
  reported.
- **D2, D4** (future bench size and equivalence margin): deferred to the owner.

### 1.4 Owner decision D8 (2026-09-27 ~00:10): in-domain training is the point

- Nagi's data aims to train models that operate complex machines, so training on similar tasks is intended.
- Near-transfer genres (hover, hover2, crane, closed-loop snake) are **not sealed** from training. The O2 near-transfer
  flag is informational; the headline composite includes every game for every player.
- **Still forbidden (O3, true contamination):** training on the Arena engines, Arena seeds or states, or same-engine
  clones. The audit found no O3 pair (PROTOCOL §A1.8).
- The report shows which players had in-domain training per game, and treats Booster Gauntlet's new skills (hoverslam
  without hover, multi-phase hops, relights) as the less-seen probe.

### 1.5 Champion rule and showcase rule (owner go, 2026-09-27 ~11:20)

Frozen before any Board 1 result was opened, and committed in code before any result existed (PROTOCOL §A1.4).
- **The Nagi entries exist only to select a champion:** ENORMOUS-old, ENORMOUS-CL, T-dual K-call and T-dual Burst.
- **Score:** the mean over the 3 games of the paired per-seed win rate against the **external competitors only**.
  Nagi-vs-Nagi pairs do not count.
- **Tie-breaks:** the sum of RMST up to 60 s, then the mean level at failure, then the fixed NAGI order.
- **Caveat, required in the report:** choosing the best of 4 inflates the champion's own numbers (winner's curse). The
  champion-vs-others margins are a screen, not confirmatory, and confirmation needs fresh seeds.
- **Showcase clips** show only the Nagi champion against the external competitors, on a seed chosen by a fixed rule
  (the lower median of the champion's survival times; PROTOCOL §A1.5), never cherry-picked.

### 1.6 Void rule (PROTOCOL §1.1.5, fixed before any data)

- A live tick processed more than 100 ms late voids the round. A void round is re-played once with the same seed; if
  it is void again, that seed index is dropped for both sides of every pair.
- More than 1 void in a 10-round cell invalidates the cell. That is a harness defect: fix it and re-run the whole
  range. One attempt per seed; no reruns conditioned on outcomes (PROTOCOL §5, AG6).

### 1.7 Unattended-run rules (owner away)

- Spend is bounded on the server side whatever happens to the local machine or the agents: detached jobs, per-job
  timeouts, no retries, and a watchdog that stops every job at a fixed deadline.
- Canary first: one player, one game, one round.
- **STOP** (tear down, verify that nothing is running, write the report) if the canary fails twice, if any job exceeds
  1.25× its cost estimate, if the projected high-case spend reaches the stop line below the hard cap, or on any O3
  contamination hit.
- No roster or protocol changes and no guardrail edits while unattended. Anything outside the approval waits for the
  owner.

## 2. Run 1 and why it was stopped

### 2.1 First stop (2026-09-27 12:11): the micro-batching parity gate

- The canary (ENORMOUS-old, 3 streams, micro-batched) failed the argmax-agreement check: **190/192 = 0.9896**, against
  a rule of ≥ 0.99. The logit check passed: max |Δlogit| **0.125**, against a rule of ≤ 2F = 0.25, where F = 0.125 is
  the noise floor from padding alone (the same row with 64 extra right pads).
- 0.125 is one bf16 ulp at typical logit magnitudes, so batching moved the logits no more than padding alone does. The
  2 flips were near-ties whose top-2 margin was at most 2F.
- The operator stopped, as the rules require. A second canary on the same deterministic inputs would have reproduced
  190/192, so it was not run.
- At the time of this stop, the Linux preparation gate had passed: the Snake Rush and Booster Gauntlet state hashes equal
  the Mac values, and the Rotorwash-Ramp Linux hash was recorded.

**Owner decision (~12:20): tie-aware parity.** Chosen from three options (tie-aware parity; running Nagi at 1 stream,
rejected as unfair because it slows Nagi about 3× in realtime; stopping for the day).
- An argmax disagreement counts only on **decisive** pairs, where the reference top-2 margin exceeds 2F.
- Pass requires decisive agreement ≥ 0.99, max |Δz| ≤ 2F, and decisive pairs ≥ 50% of all pairs.
- The same rule applies to the Nagi and SemIf-4B gates. A failure is still STOP with no 1-stream fallback. The canary
  was re-run under a fresh id.

### 2.2 Second stop (2026-09-27 13:24): harness void rounds invalidated the cells

After the tie-aware canary passed, the parity gates passed and replays were exact.
- **Played, 30/30 rounds each with exact replay:** ENORMOUS-old, T-dual K-call, T-dual Burst, SemIf-4B, Jev.
- **Not played:**
  - ENORMOUS-CL: its job failed closed while swapping models in one GPU job, because 50.16 GiB was still allocated after
    the previous model was freed.
  - CLM-8B: its canary ran out of GPU memory, because the vLLM memory share left no room for the reference encoder.
- **Void rounds** (a live tick processed more than 100 ms late):

  | Player | Booster Gauntlet | Rotorwash-Ramp | Snake Rush |
  |---|---|---|---|
  | ENORMOUS-old | 5/10 | 0/10 | 2/10 |
  | T-dual Burst | 7/10 | 2/10 | 1/10 |
  | T-dual K-call | 7/10 | 0/10 | 2/10 |
  | SemIf-4B | 10/10 | 0/10 | 5/10 |
  | Jev | 5/10 | 7/10 | 3/10 |

- At most 1 void is allowed per 10-round cell, so nearly every cell was invalid. The protocol calls this a harness
  defect: fix it and re-run the whole range.
- **Cause.** Lateness was 250–630 ms. Rotorwash-Ramp voids happened at tick 0 (the course was built inside the live
  clock); Booster and Snake voids happened mid-round. Jev, which uses no GPU, was affected too, so the lag was in the
  CPU harness: 3 realtime streams plus the filler shared one Python process, and one stream's reset or step blocked the
  others.
- **Second defect: ladder calibration.** The bots had been calibrated with zero latency, while models act on
  observations one tick old. Snake Rush killed every model in 1–4 s at Level 1 (the naive bot's median was 9.8 s),
  and that floor effect removed the separation between players.
- **Decision:** the operator stopped under the unattended rules, which forbid harness or protocol fixes without the
  owner. ENORMOUS-CL and CLM-8B were not started, to avoid paying for invalid cells. All Board 1 jobs were stopped.

### 2.3 The fixes

- **Harness:** every game state is built before the round clock starts; each realtime stream runs in its own process,
  with the filler separate; a CPU-only soak (3 streams × 3 games × 10 rounds with a mock 200 ms player) must show
  0 voids before any GPU spend. Records are identical to the old loop's (PROTOCOL §1.1.5; private commit `be698bc`).
- **Calibration:** the bot ladders were re-calibrated with the same 1-tick (250 ms) reply delay the models get
  (private commit `98b01a5`).
- **One Nagi model per GPU job**, replacing the in-job model swap that failed closed.

## 3. Run 2

- **Owner decision (~14:50): re-run Board 1.** The owner approved the fixes and the re-run with a new watchdog
  deadline. Unchanged: the spend cap and stop line, the roster of 7, 10 rounds per game, 3 streams per GPU and the
  tie-aware parity gates. Run 2 uses fresh job ids. **Run 1 records are historical and never pooled with run 2.**
- **Owner decision (~15:05): spend-projection fix.** The spend guard read the wrong field name for reconciled bills,
  so it counted run 1 jobs at their planned high cost instead of their actual bills and over-projected the total. The
  owner approved fixing the guard (with tests) and continuing. The cap and the stop line were unchanged.
- **Owner away (~15:22):** "keep going until done", with no further approvals possible. The unattended STOP rules
  applied, and no new owner decision was assumed.
- **CLM-8B not ranked (~16:25, operator).** CLM-8B failed its own conformance canary (P3: the model's documented
  example fell outside tolerance). Under D15 it is not ranked, and the reason is disclosed. The preregistered fallback
  (a different vLLM version) was not run: it needed a new GPU window that risked the watchdog deadline while the owner
  was away. The champion rule was computed against the externals that played, **Jev and SemIf-4B**.
- **Result:** 180 scored rounds, 0 void, every record replayed exactly. Champion by the frozen rule: **T-dual Burst**
  (screen, n = 10 per game, not decisive). Full tables: [BOARD1_REPORT.md](BOARD1_REPORT.md).
- **Teardown:** after the report, all Board 1 jobs and the watchdog were stopped.

## 4. Open after Board 1

- D2 and D4 (future bench size, equivalence margin) remain with the owner.
- The champion-vs-others margins are a screen. The confirmation of T-dual Burst against Jev on fresh seed indices
  (10–33) is preregistered in [BURST_PREREG.md](BURST_PREREG.md); its result is in
  [BURST_CONFIRMATION.md](BURST_CONFIRMATION.md).

**Cost:** Board 1 (runs 1 and 2 combined) cost about $4.9 in provider bills, against a $12 hard cap.
