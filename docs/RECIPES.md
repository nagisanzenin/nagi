# Agent recipes

Nagi is a **decision core**. Keep free-text on an LLM; keep choices/scores/probabilities here.

## 1. Finding verifier (TP / FP)

```python
VERIFY = {
    "verdict": {
        "type": "choice",
        "instructions": (
            "Classify TP only if the evidence directly proves exploitability, else FP. "
            "An execution proof always means TP. Public-by-design content is FP. "
            "Reflected payload without an executing sink is FP. Cross-tenant data is always TP."
        ),
        "criteria": {
            "TP": "The evidence dossier directly proves the vulnerability is exploitable.",
            "FP": "The evidence does not prove exploitability, is a scanner artifact, or is weak/ambiguous.",
        },
    }
}

ans = big.system_one(state=dossier, questions=VERIFY)["answers"]["verdict"]
if ans["probabilities"]["FP"] >= 0.95:        # calibrated suppression dial (τ)
    suppress(dossier)
elif ans["probabilities"]["TP"] >= 0.5:
    mark_verified(dossier, confidence=ans["probabilities"]["TP"])
else:
    keep_unverified(dossier)                  # "cannot prove" ≠ FP
```

τ is a **recall/precision knob**, not a truth threshold. Measure TP-loss vs FP-stay on your labels before shipping.

## 2. Severity (Score)

Map rubric levels to `criteria` in order (index = score). Use the expected level as the report field and the full distribution for confidence:

```python
ans = nagi.system_one(state=finding, questions=SEVERITY)["answers"]["severity"]
report.priority = int(round(ans["score"]))
report.confidence = ans["confidence"]
```

## 3. Agent eval node (CONTINUE / COMPLETE / STOP)

```python
EVAL = {
    "decision": {
        "type": "choice",
        "instructions": (
            "COMPLETE when further actions would repeat explored paths. "
            "CONTINUE when unexplored elements remain. "
            "STOP on errors, expired session, or blank page."
        ),
        "criteria": {
            "CONTINUE": "Unexplored elements/forms/navigation remain.",
            "COMPLETE": "Task accomplished; further actions would repeat.",
            "STOP": "Error/crash, expired session, blank page, or no action possible.",
        },
    }
}
```

A wrong call costs one loop step — bound damage with a max-steps guard.

## 4. Hybrid with an LLM

| Field | Owner |
|---|---|
| choice / score / noul | **Nagi** |
| `reasoning`, `recommendation`, free text | LLM (after the decision) |
| screenshots / multimodal | LLM first → structured state → Nagi |

## 5. When *not* to use Nagi

- Open-ended generation (summaries, exploits, emails)
- Multimodal-only inputs without a text state
- Option sets that are not known at call time (use retrieval first, then Nagi)
