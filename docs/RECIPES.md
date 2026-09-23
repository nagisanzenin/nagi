# Agent recipes

This complete example performs a choice, severity score and boolean decision.
It prints predictions; downstream application actions are up to the caller.

```python
from nagi import load_smol

model = load_smol(device="cpu")
dossier = {
    "finding": "Cross-account document access",
    "evidence": "An authenticated test account retrieved a document owned by a different account.",
    "scope": "The owner did not share the document with the test account.",
}
questions = {
    "verdict": {
        "type": "choice",
        "instructions": "TP requires direct evidence of unauthorized access; otherwise FP.",
        "criteria": {"TP": "Unauthorized access is demonstrated.", "FP": "Unauthorized access is not demonstrated."},
    },
    "severity": {
        "type": "score",
        "instructions": "Rate the impact described in the state.",
        "criteria": ["No demonstrated impact", "Limited account impact", "Cross-account data exposure"],
    },
    "review": {"type": "noul", "instructions": "Does the evidence warrant human review?"},
}
answers = model.system_one(state=dossier, questions=questions)["answers"]
print(answers["verdict"])
print(answers["severity"])
print(answers["review"])
```

Score levels are zero-based; the returned score is their expected value, not
necessarily an integer. Confidence is the maximum option probability, not a
certificate that evidence is correct. Choose action thresholds using held-out
labels and the costs of false positives and false negatives.

For an agent control node, define explicit CONTINUE/COMPLETE/STOP criteria and
pass the observed state as text or a JSON-serializable object. Bound the loop's
number of steps in application code. Nagi returns decisions and distributions;
use a separate text-generating model when you need prose explanations or summaries.
