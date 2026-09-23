# Big v2 candidate versus Big v0

Both checkpoints were evaluated on the same clean held-out inputs. These are
candidate measurements; public SDK defaults still load v0.

| Metric | Big v0 | G-clean v2 | Change |
|---|---:|---:|---:|
| Public macro, 633 items | 73.47% | 76.73% | +3.25 points |
| Novel-rule macro, 320 items | 48.75% | 63.13% | +14.38 points |
| Score/noul accuracy, 160 items | 63.75% | 58.13% | −5.63 points |

Changes use unrounded measurements. Paired within-task 95% CI for the public
improvement is [−1.41, +7.52] points, so that improvement is not conclusive at
this sample size. Novel improvement has CI [+9.06, +19.69] points. Score/noul
regresses in the measured aggregate; this is not an across-the-board upgrade.

The candidate remains behind JEV on public (81.36%) and novel rules (99.38%).
Smol KD is a separate pilot and did not improve both axes. Neither candidate
was promoted to the public model default. SDK correctness fixes and model
quality claims are separate changes.
