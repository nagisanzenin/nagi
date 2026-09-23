# V5: intermediate supervision helps, but release gates fail

**Big v3 remains the public default. V5 was not published.** This was a matched
experiment: the same V3 initialization, 4,000 training examples, batch order,
seed and 200 optimizer updates. The treatment adds loss on operand/intermediate
values; the control detaches that loss from the backbone. Neither needs extra
reasoning tokens at inference. Development gates selected step100, compared with
control step100; final results did not change that selection.

## New final suites

| Macro accuracy | Public Big v3 | Answer-only control | V5 auxiliary |
|---|---:|---:|---:|
| Policy: 1,200 examples / 12 new compositions |43.667%|54.083%|58.333%|
| Language: 800 fresh examples / 4 tasks |72.250%|70.250%|71.625%|
| Historical typed regression: 640 examples |82.813%|82.656%|84.219%|

These are different examples from the V4 table and the V3/JEV table. Do not compare
absolute percentages across those suites. Coverage was100%; failures count as wrong.
The typed examples are historical development data, not an independent final test.

The useful finding is **+4.25 percentage points over matched control**, with a
hierarchical paired family/item bootstrap95% interval of **[+0.58,+7.83]pp**.
This supports the auxiliary intervention on this suite; one training seed does
not establish reproducibility across training seeds or universal transfer.

The candidate still fails two preregistered release gates:

- Policy gain over V3 is +14.67pp, but the family/item interval is
  **[−2.67,+34.50]pp**. Three families regress by13/28/24pp; gains are uneven.
  The within-fixed-family interval is [+12.00,+17.42]pp. That answers a narrower
  question and cannot replace the registered family-generalization gate.
- Language delta is −0.625pp, interval **[−2.50,+1.25]pp**. This fails the
  −2pp noninferiority bound; it does not establish a statistically conclusive loss.

Export checks passed: exact reload logits, merged BF16 maximum probability delta
0.02091, SDK/research delta5.28e-8 on three choice/score/noul fixtures. In the same
worker on24 length-stratified prompts, warm batch1 readout P95 was62.81ms versus
63.99ms for V3. No HTTP, no deployment SLA, and no claim of a causal speedup.

## Short reasoning diagnostic

On48 development examples, same-prompt forced answer readout after0/16/32/64/128
reasoning tokens achieved41.67/41.67/43.75/41.67/47.92% accuracy. Standalone128-token
P50 was4.44s on12 balanced timing probes. All48 traces hit128 tokens and many spent
the beginning restating the task. Truncating verbose reasoning did not provide a
compelling speed/quality trade-off; this does not test a trained compact scratchpad.
The older512-token result used24 examples and is not part of this matched curve.

## Cost and evidence

Both200-step trainings took about266 seconds combined. All four Modal workers
cost approximately **$1.24 in measured worker compute**, with **$5.56/$6** charged
to the conservative session ledger. Those are different quantities; worker timing
excludes startup/build/storage/guardian/idle. All apps stopped and the session closed.
No new JEV calls; no beat-JEV claim.

[Full plan, source, data hashes, predictions and Vietnamese report](https://github.com/nagisanzenin/nagi-research/tree/main/docs/campaign_v5).
