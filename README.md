# Nagi

**Typed decisions in one forward pass. SMOL 0.5B · BIG 4B · HUGE 12B · ENORMOUS 27B.**

Nagi maps a state and a closed option set to a typed decision and a probability distribution. There are four model lines. Nagi-ENORMOUS (27B) is a research release: it failed its preregistered rule-reading gate and is published by owner decision (see [below](#enormous-research-release-gate-not-passed)).

**Context update (SDK v0.4.1):** Big now accepts up to **4,096 tokens** by default; Smol retains 512 with an experimental 2048-token option. [Measured behavior and usage](docs/CONTEXT.md). Archived benchmark numbers below use SDK v0.4.0 defaults.

## Model lines

| | Nagi-SMOL | Nagi-BIG | Nagi-HUGE | Nagi-ENORMOUS |
|---|---|---|---|---|
| Hugging Face | [nagi-smol-v0](https://huggingface.co/nagisanzeninz/nagi-smol-v0) | [nagi-big-v3](https://huggingface.co/nagisanzeninz/nagi-big-v3) | [Nagi-HUGE](https://huggingface.co/nagisanzeninz/Nagi-HUGE) | [Nagi-ENORMOUS](https://huggingface.co/nagisanzeninz/Nagi-ENORMOUS) |
| Base model | ModernBERT-large / M2′ | Qwen3.5-4B | Gemma4 12B | Qwen3.8-27B |
| Params | ~0.5B (480M loaded SDK) | 4B + adapter | 12B + rank8 adapter | 27.8B + rank8 adapter |
| Loader | `load_smol()` | `load_big()` | `load_huge()` | `load_enormous()` |
| Public suite, full operational (4,671) | 38.85% | 76.14% | 77.92% | 83.07% |
| Public suite, common evidence (4,518) | 39.05%¹ | 75.90%¹ | 77.49% | 82.76% |
| Option-order flip rate (320 pairs) | 0.00% | 9.69% | 13.12% | not measured |
| Latency, native serial SDK, H100 P50 / P95 | 17 / 19 ms | 70 / 83 ms | 91 / 102 ms | not measured |
| Latency, merged adapter + fused kernels, H100 P50 at 1,024 tokens² | — | — | — | 122 ms |
| Hardware | CPU-friendly (FP32) | GPU, BF16 | H100 BF16 validated (~24 GB params) | 80 GB GPU, BF16 (~56 GB weights) |

Reference: Jev1.13.0 scores 83.92% full / 83.95% common on the same suite. ENORMOUS−Jev: **−1.20 pp**, 95% interval **[−2.70, +0.31]** (statistically tied on this suite). ENORMOUS−HUGE: **+5.27 pp** [+3.49, +7.14]. Both on the common-evidence eight-source macro.

¹ The 4,518 common-evidence rows were frozen for the four-system comparison. For Smol and Big they are a fixed-population diagnostic only, not guaranteed untruncated; the three-tier untruncated comparison (4,655 rows) is [below](#smol-vs-big-vs-huge-measured-trade-offs).
² A different measurement from the native serial SDK row: merged LoRA, fused Gated-DeltaNet kernels, 1,024-token input. The SDK loads ENORMOUS with an unmerged adapter and eager attention, which is slower; its native serial latency has not been measured.

The tiers are separate models, not renames. Big defaults and pinned calibration stay unchanged; `load_huge()` is unchanged. [Smol vs Big vs HUGE report and logs](https://github.com/nagisanzenin/nagi-research/tree/main/docs/tier_comparison) · [HUGE release details](docs/HUGE_RELEASE.md) · [ENORMOUS release details](docs/ENORMOUS_RELEASE.md).

### ENORMOUS: research release, gate not passed

ENORMOUS was trained to test whether a larger backbone improves reading new rules. It failed that preregistered gate. On the sealed final set, ENORMOUS−HUGE on S_final was **+2.9 pp [−0.6, +6.5]** (required ≥ +5 pp with the lower bound above 0), and on counterfactual rule pairs **−0.3 pp [−3.8, +3.2]**. It passed the public-benchmark non-regression and latency gates. It is released as a research artifact by owner decision. **No claim is made that ENORMOUS generalizes better to unseen rules**; its gains are on the public suite above.

## Public benchmark — four systems, inspectable evidence

[**Explore the interactive benchmark →**](https://nagisanzenin.github.io/nagi/) · [Nagi-HUGE on Hugging Face](https://huggingface.co/nagisanzeninz/Nagi-HUGE) · [Protocol, raw logs and scoring](https://github.com/nagisanzenin/nagi-research/tree/main/docs/fair_public)

| System | Same complete evidence (4,518) | Full operational suite (4,671) | Option-order flips (320 pairs) |
|---|---:|---:|---:|
|[Nagi-ENORMOUS](https://huggingface.co/nagisanzeninz/Nagi-ENORMOUS)|82.76%|83.07%|not measured|
|[Nagi-HUGE](https://huggingface.co/nagisanzeninz/Nagi-HUGE)|77.49%|77.92%|13.12%|
|[Laya](https://huggingface.co/convaiinnovations/laya)|57.35%|57.25%|10.94%|
|[OpenJev / SemIf](https://github.com/TheoLeeCJ/SemIf-OpenJev)|73.87%|74.06%|10.62%|
|[Jev1.13.0](https://typesafe.ai)|83.95%|83.92%|1.25%|

HUGE−Jev: -6.47 percentage points (95% interval [-8.13, -4.89]) on the common-evidence eight-source macro. ENORMOUS−Jev: -1.20 pp [-2.70, +0.31] (Bonferroni 98.33% [-3.06, +0.67]), which includes zero: the two are statistically tied on this suite. ENORMOUS scores higher than Jev on ANLI, XNLI, BoolQ, CB and RTE, and lower on MMLU-Pro (65.00% vs 82.33%), COPA and WiC. None of this establishes universal generalization or a same-hardware latency win. ENORMOUS was scored on the same frozen rows without the 320 option-rotation rows, so its flip rate is not measured. [Per-source ENORMOUS results](https://github.com/nagisanzenin/nagi-research/blob/main/docs/fair_public/candidate_Nagi-ENORMOUS.md).

Eight sources, equal weight per source. ANLI, XNLI, BoolQ, CB, COPA, RTE, WiC and MMLU-Pro; human/expert gold. Common-evidence rows were frozen before inference using local tokenizer audits; Jev receives the same payload, but its internal truncation is unknown. Laya truncates153core examples; full operational results retain native truncated answers. Option flips compare stable semantic choices after a rotation; lower is better. Public subsets/adaptations, **not official leaderboard scores**. Nagi developers ran this evaluation; pretraining exposure is unknown.

| Local H100 native SDK | P50 | P95 |
|---|---:|---:|
|Nagi-HUGE|91ms|102ms|
|Laya|13ms|15ms|
|OpenJev / SemIf|51ms|66ms|

**Separate WAN/API measurement:** Jev P50/P95 1086/2962ms, client concurrency4, unknown server hardware. No matched-hardware ranking.

Native local serial SDK calls on the actual prompt distribution; includes first forward, excludes model loading. Jev timings include network/service and four requests in flight, without connection-pool reuse; hardware is unknown. The separate HUGE1024token loopbackHTTP P95 is145ms, not the same measurement. ENORMOUS has no native serial SDK timing; its only latency figure is the 122 ms fused-kernel, merged-adapter P50 at 1,024 tokens above. [Complete results and limitations](bench/HUGE_PUBLIC.md).

## Install and use

Python3.10+ and Git:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install "nagi-decisions @ git+https://github.com/nagisanzenin/nagi.git"
```

The package is `nagi-decisions`; the import is `nagi`. An unrelated PyPI package named `nagi` is not this project. The first load downloads weights from Hugging Face.

```python
from nagi import load_huge

nagi = load_huge(device="cuda")
dossier = {"A": 7, "B": 3}
out = nagi.system_one(state=dossier, questions={
    "greater": {
        "type": "choice",
        "instructions": "Which value is greater?",
        "criteria": {"A": "A is greater", "B": "B is greater"},
    }
})
print(out["answers"]["greater"])
```

HUGE was validated on an H100 using BF16. Parameter storage alone is approximately24GB; allow additional memory for loading, adapters and activations. A24GB card is not validated. Inputs over4,096 rendered tokens are rejected explicitly, not silently truncated. The model scores2–26 supplied options; it cannot invent a new label. Temperature1.0 is not fitted calibration.

`load_enormous(device="cuda")` has the same interface. It needs an 80 GB GPU (H100 80GB or A100-80G) in BF16; smaller GPUs are not supported. Inputs longer than 768 tokens are accepted up to 4,096 but fall outside the trained range.

For a lightweight CPU start:

```python
from nagi import load_smol

nagi = load_smol(device="cpu")
dossier = {"message": "Please cancel my subscription."}
out = nagi.system_one(state=dossier, questions={
    "route": {
        "type": "choice",
        "instructions": "Select the team that should handle the request.",
        "criteria": {"billing": "Subscriptions and payments", "technical": "Technical issues"},
    }
})
print(out["answers"]["route"])
```

Examples are self-contained and do not promise a particular prediction. [Installation guide](docs/INSTALL.md) · [Recipes](docs/RECIPES.md).

## Release roles

| | Nagi-SMOL | Nagi-BIG | Nagi-HUGE | Nagi-ENORMOUS |
|---|---|---|---|---|
| Release role | Small CPU-friendly model | 4B default | 12B research tier | 27B research release (rule-reading gate not passed) |

Each tier is a separate model, not a rename of another. Big defaults and pinned calibration stay unchanged. HUGE and ENORMOUS ship adapters; the SDK loads the pinned base separately and keeps LoRA unmerged, matching the benchmark. [HUGE release details](docs/HUGE_RELEASE.md) · [ENORMOUS release details](docs/ENORMOUS_RELEASE.md).

## Typed decisions

```text
system_one(state, questions) → {"answers": {"question_id": {
    "choice": "label", "probabilities": {"label": 0.9, "other": 0.1}, "confidence": 0.9
}}}
```

| Question type | Criteria | Returned value |
|---|---|---|
| `choice` | dictionary of label → description | selected label |
| `score` | ordered list of level descriptions | expected level |
| `noul` | omitted | probability of true |

Probabilities are conditional on the supplied options; confident mistakes are possible. The new public comparison evaluates **choice**. It does not establish quality for every score/noul task. HUGE performs one forward pass per question; it does not generate a reasoning trace.

## Earlier evidence remains available

The preceding synthetic gate did **not** establish a Nagi win: HUGE85.83% vs Jev88.33%, paired difference−2.50pp,95%CI[−5.83,+0.67]. HUGE is released as a research artifact with that limitation preserved. [Internal gate report](https://github.com/nagisanzenin/nagi-research/blob/main/docs/campaign_12b_release/REPORT.vi.md).

Big v3 replaced Big v0 after matched evaluation. V4 and V5 did not meet their release gates. The original v0 comparison was invalidated by label/demo leakage, and its claims remain withdrawn. Scores from different historical suites must not be compared as if they used the same examples.

[V3 results](bench/V3_RESULTS.md) · [V4 results](bench/V4_RESULTS.md) · [V5 results](bench/V5_RESULTS.md) · [Historical audit](bench/HISTORICAL_V0.md) · [Calibration](docs/CALIBRATION.md) · [Research repository](https://github.com/nagisanzenin/nagi-research).

## Smol vs Big vs HUGE: measured trade-offs

| Model | Full suite (4,671) | All three untruncated (4655) | Truncated / unsupported core | Option flips | H100 P50 / P95 |
|---|---:|---:|---:|---:|---:|
| Nagi-Smol | 38.85% | 38.89% | 15 / 0 | 0.00% | 17 / 19 ms |
| Nagi-Big | 76.14% | 76.12% | 3 / 5 | 9.69% | 70 / 83 ms |
| Nagi-HUGE | 77.92% | 77.87% | 0 / 0 | 13.12% | 91 / 102 ms |

HUGE−Big v3: **+1.78 percentage points**, 95% interval **[+0.01, +3.70]** on the full operational public suite. Adjusting for three tier comparisons gives [-0.49, +3.93] pp, which includes zero: a decisive HUGE advantage over Big is not established. Native defaults: Smol FP32, Big/HUGE BF16. Public-data exposure is unknown. [Full tier report and raw evidence](https://github.com/nagisanzenin/nagi-research/tree/main/docs/tier_comparison).

ENORMOUS is not part of this three-tier analysis; its comparison with HUGE (+5.27 pp [+3.49, +7.14]) uses the 4,518 common-evidence rows of the four-system benchmark above.

## Arena Live (real-time games)

**Arena Live (videos and page coming soon):** all four Nagi lines play the same real-time games.

| Game | Nagi-ENORMOUS | Nagi-HUGE | Nagi-BIG | Nagi-SMOL |
|---|---:|---:|---:|---:|
| Lightcycle Royale | 21 points, 5 wins | 21 points, 2 wins | 18 points, 3 wins | 0 points |
| Rotorwash helicopter | 10/10 wins, median survival 35.8 s | median survival 4.0 s | median survival 3.0 s | median survival 5.0 s |
| Stack Attack | pending | pending | pending | pending |

These are small deployment pilots of game play, not a general model ranking, and they do not test the rule-reading generalization that ENORMOUS failed. Raw records and engine source go in [bench/arena_live](bench/arena_live/README.md).


### Watch the models play Snake

[Open the AI Arena](https://nagisanzenin.github.io/nagi/arena/) — the stable entry point now opens the latest Nagi-HUGE real-time Bomber replay. Inspect actual decisions, inputs and deployment timings. [Earlier Snake replay and playable mode](https://nagisanzenin.github.io/nagi/snake/) remain archived with their [original protocol and traces](https://github.com/nagisanzenin/nagi-research/tree/main/docs/arena).

[Drone Swarm: Reactor Rescue — source and all 197 decisions](https://github.com/nagisanzenin/nagi-research/tree/main/docs/drone): four models dispatch six drones in three seeded toy simulations. Nagi-BIG completed 3/3 missions, Jev 1/3, Laya and SemIf 0/3. Shared autopilot and explicit sensors; this small pilot is not a general model ranking.

[Bomber Arena — actual AI decisions in one shared arena](https://nagisanzenin.github.io/nagi/bomber/). Three rotated starts on one layout; Jev wins once, SemIf twice. Inspect input/output and latency for every turn. [Protocol, source and raw evidence](https://github.com/nagisanzenin/nagi-research/tree/main/docs/bomber).

[Real-time Bomber Arena](https://nagisanzenin.github.io/nagi/bomber-realtime/) — the world keeps moving while models think. Nagi-BIG won 4/4 rounds in this 285-request deployment pilot. Three local models shared one FIFO H100 queue; Jev used its remote API. Full map plus shared safety hints, four starting rotations over two layouts, and every request/action published. This is not a general model ranking. [Protocol, timing audit and replay evidence](https://github.com/nagisanzenin/nagi-research/tree/main/docs/bomber_realtime).

[HUGE replacement — real-time Bomber](https://nagisanzenin.github.io/nagi/bomber-huge/): identical rules, Nagi-HUGE replaces BIG. HUGE won 2/4 rounds; Jev and Laya won one each. Reply P50: HUGE 129ms vs prior BIG 165ms, while Jev also improved from 328ms to 210ms across runs. These deployment pilots do not isolate model quality or prove a size effect. [Comparison and raw evidence](https://github.com/nagisanzenin/nagi-research/blob/main/docs/bomber_huge/REPORT.md).
