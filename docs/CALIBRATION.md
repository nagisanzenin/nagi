# Calibration

Temperature defaults to 1.0. A model's maximum probability is its `confidence`,
not a guarantee of accuracy or an independently calibrated posterior.

Fit a positive scalar temperature on a separate labeled calibration split by
minimizing negative log-likelihood. With saved probabilities, transform them by
raising each probability to `1 / temperature` and normalizing (use a small epsilon
for zeros). With logits, use softmax(logits / temperature).

Pass the fitted value as `temperature=` to `load_smol` or `load_big`. Preserve the
checkpoint revision, dataset split and fit procedure alongside the value. Do not
fit on test labels. Report both raw and calibrated ECE, Brier and NLL; improving
NLL does not guarantee that ECE improves.

The old gold_ltout calibration table is invalidated by mislabeled examples and
gold-dependent prompts. Current campaign results are in [the benchmark report](../bench/README.md).
The private G-clean candidate's fitted temperature is specific to that checkpoint
and calibration split; do not apply it to public v0 weights without measurement.

Choose action thresholds using the workload's labeled validation set and costs
of errors. Re-evaluate calibration under distribution shift and by question type
and option cardinality. There is no universal safe threshold such as 0.95.
