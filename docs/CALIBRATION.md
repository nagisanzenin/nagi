# Calibration

`probabilities` are trained with soft labels (KL to a teacher distribution). They are usable raw, but **fit a temperature per workload** before gating on `confidence`.

## Temperature scaling

Given logits *z* and gold labels, learn a single scalar *T* > 0:

```python
p = softmax(z / T)
# minimize NLL(p, gold) over T
```

Report ECE **raw** and **T-scaled** (10 bins on max-p vs correctness).

| Model | ECE raw (gold_ltout) |
|---|---:|
| Nagi-Big | 0.047 |
| Nagi-Smol | 0.084 |
| OpenJev | 0.046 |
| Jev | 0.121 |
| Laya* | 0.365 |

\*Laya checkpoint shipped invalid temperatures (`choice:11+` clamped to 0.5) — confidence uncalibrated as published.

## Thresholds

| Use | Rule of thumb |
|---|---|
| Suppress FP in a scanner | P(FP) ≥ 0.95 (tune τ; never below 0.85 on thin evidence) |
| Mark verified | P(TP) ≥ 0.5 and evidence class allows proof |
| Escalate to human | max(p) < 0.6 or entropy > 0.8 |

Prefer **asymmetric** losses: keeping an FP is usually cheaper than killing a TP.

## Monitoring

- Drift: track ECE weekly on live labels; refit T when ECE rises > 0.02.
- Log calibration-by-K (option cardinality). High-K is harder; Smol’s option tower is designed for K ≳ 20.
- Never compare ECE across models on different splits.
