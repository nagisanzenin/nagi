# Public decision benchmark: Nagi-HUGE, Laya, OpenJev/SemIf, Jev

Nagi−Jev: -6.47 percentage points (95% interval [-8.13, -4.89]) on the common-evidence eight-source macro. The interval supports a Jev advantage on this specific suite. It does not establish universal generalization or a same-hardware latency win.

| System | Same complete evidence (4,518) | Full operational suite (4,671) | Option-order flips (320 pairs) |
|---|---:|---:|---:|
|[Nagi-HUGE](https://huggingface.co/nagisanzeninz/Nagi-HUGE)|77.49%|77.92%|13.12%|
|[Laya](https://huggingface.co/convaiinnovations/laya)|57.35%|57.25%|10.94%|
|[OpenJev / SemIf](https://github.com/TheoLeeCJ/SemIf-OpenJev)|73.87%|74.06%|10.62%|
|[Jev1.13.0](https://typesafe.ai)|83.95%|83.92%|1.25%|

![Accuracy](https://github.com/nagisanzenin/nagi-research/raw/main/docs/fair_public/charts/aggregate_accuracy.png)

## Protocol and coverage

Eight source accuracies receive equal weight1/8. Core4,671 human/expert-labelled examples;320 additional option rotations are excluded from headline accuracy. 19,964 of19,964 planned outputs are valid; missing/failed attempts are retained in denominators. Native tokenization was audited before inference; Jev receives the same complete semantic payload, but its internal tokenization/truncation is not observable. Laya truncates153core rows (150MMLU-Pro,3BoolQ). Primary common-evidence quality uses4,518 upfront-frozen rows. Full operational quality retains each native answer, including valid truncated answers. No prompts, calibration, weights or checkpoint were selected with these scores.

This is a typed-choice adaptation/subset of public sources, **not an official HELM/SuperGLUE/MMLU-Pro leaderboard score** or endorsement. Pretraining exposure is unknown. Exact local campaign train/dev state overlap was audited, not semantic contamination freedom. XNLI uses translated evidence with English criterion/options. Jev hardware is unknown; local inference and network API timing are not a common deployment benchmark.

Nagi's developers ran this comparison. Source data preparation, deterministic IDs/hashes, native source/model revisions, one-attempt raw responses, failures, guarded cloud configs, logs, scoring and budget evidence are published for independent scrutiny. Accuracy always uses the actual returned choice; bounded rounded probabilities are normalized only for calibration. Paired bootstrap2,000 draws stratified bysource/original-example cluster, translations kept together; Bonferroni intervals cover the three preregistered Nagi comparisons. No claim covers training-seed or future-distribution uncertainty.

## Per-source full operational accuracy

| Source | Core n | Nagi-HUGE | Laya | OpenJev/SemIf | Jev |
|---|---:|---:|---:|---:|---:|
|anli|1200|58.92%|40.00%|55.00%|69.50%|
|boolq|1000|90.10%|74.00%|88.30%|90.90%|
|cb|56|82.14%|53.57%|82.14%|82.14%|
|copa|100|98.00%|67.00%|95.00%|100.00%|
|mmlu-pro|600|56.00%|16.67%|44.00%|82.33%|
|rte|277|91.34%|74.73%|88.81%|92.06%|
|wic|638|71.00%|53.92%|63.95%|75.39%|
|xnli|800|75.88%|78.12%|75.25%|79.00%|

## Paired XNLI transfer

| XNLI language (200 aligned IDs each) | Nagi-HUGE | Laya | OpenJev/SemIf | Jev |
|---|---:|---:|---:|---:|
|en|83.50%|86.50%|83.00%|88.50%|
|vi|73.00%|76.50%|75.00%|76.50%|
|de|76.00%|76.00%|74.00%|77.50%|
|zh|71.00%|73.50%|69.00%|73.50%|

## Paired uncertainty

| Primary paired comparison | Difference pp | 95% CI | Bonferroni98.33% CI |
|---|---:|---|---|
|Nagi−Jev|-6.47|[-8.13, -4.89]|[-8.39, -4.49]|
|Nagi−Laya|+20.14|[+17.55, +22.74]|[+17.03, +23.37]|
|Nagi−SemIf|+3.62|[+1.58, +5.68]|[+1.23, +6.23]|

## Probability quality (common core, pooled)

| Model | Common-core NLL | Brier | ECE10 |
|---|---:|---:|---:|
|Nagi-HUGE|0.860|0.418|0.152|
|Laya|1.194|0.626|0.219|
|OpenJev / SemIf|0.848|0.440|0.132|
|Jev1.13.0|0.880|0.297|0.082|

Lower is better. Confidence is probability of the actual returned decision. Jev exposes rounded probabilities; NLL uses a1e−12 floor for zero probabilities and is especially sensitive to that rounding, so small NLL rank differences do not establish superior calibration. Public confidence calibration can differ from the original training distribution.

## Native latency, separately scoped

| Local H100 native SDK | P50 | P95 |
|---|---:|---:|
|Nagi-HUGE|91ms|102ms|
|Laya|13ms|15ms|
|OpenJev / SemIf|51ms|66ms|

**Separate WAN/API measurement:** Jev P50/P95 1086/2962ms, client concurrency4, unknown server hardware. No matched-hardware ranking.

Actual core prompt distribution; local model loading excluded, first forward included. No cache-sharing throughput experiment. Nagi-HUGE also has a separate30-probe1024token H100loopbackHTTP P95145ms; that is not this table.

## Release and reproducibility

Nagi-HUGE is a research release, the third model tier alongside Smol and Big. The earlier synthetic gate failed (85.83%vs88.33%Jev;−2.50ppCI[−5.83,+0.67]); it remains archived unchanged. Bigv3 stays the `load_big()` default. These public scores do not retroactively pass that gate.

[Model](https://huggingface.co/nagisanzeninz/Nagi-HUGE) · [SDK](https://github.com/nagisanzenin/nagi) · [Interactive page](https://nagisanzenin.github.io/nagi/) · [Protocol](https://github.com/nagisanzenin/nagi-research/blob/main/docs/fair_public/PLAN.vi.md) · [Runbook](https://github.com/nagisanzenin/nagi-research/blob/main/docs/fair_public/RUNBOOK.vi.md) · [Analysis](https://github.com/nagisanzenin/nagi-research/blob/main/docs/fair_public/analysis.json) · [Archives](https://github.com/nagisanzenin/nagi-research/tree/main/docs/fair_public/archive) · [Ledger](https://github.com/nagisanzenin/nagi-research/blob/main/docs/fair_public/ledger.json)

## Cost

Completed-hour Modal app usage: public comparison **$1.14**, earlier 12B campaign **$2.38**, combined **$3.52**. Public Jev API list-price estimate **$0.09**, separate from Modal. These are app usage receipts, not a final monthly invoice. All public Modal apps are stopped, outstanding reservations are zero.
