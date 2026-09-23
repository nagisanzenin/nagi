# Install & first call

## 1. Environment

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # or cu124 for GPU
pip install transformers peft huggingface_hub pyyaml
pip install -e .
```

| Target | Notes |
|---|---|
| CPU | Smol only, ms→s latency |
| CUDA (T4/A100/H100, MPS) | Smol full speed; Big needs ≥16 GB VRAM (BF16) |

## 2. Load

```python
from nagi import load_smol, load_big

smol = load_smol()   # huggingface.co/nagisanzeninz/nagi-smol-v0
big  = load_big()    # huggingface.co/nagisanzeninz/nagi-big-v0
```

First call downloads weights to the HF cache (`~/.cache/huggingface`). Pin a revision in production:

```python
load_smol(revision="main")  # replace with a commit sha
```

## 3. First decision

```python
out = smol.system_one(
    state="Refund request: order #123, 45 days after delivery. Policy window is 30 days. Customer reports a cracked screen on arrival (photo attached).",
    questions={
        "verdict": {
            "type": "choice",
            "instructions": "Is this a valid refund exception?",
            "criteria": {
                "yes": "Documented store/policy exception applies (e.g. arrival damage).",
                "no":  "Outside the window with no documented exception.",
            },
        }
    },
)
print(out["answers"]["verdict"])
# {'choice': 'yes', 'probabilities': {'yes': 0.61, 'no': 0.39}, 'confidence': 0.61}
```

## 4. Score and Noul

```python
out = smol.system_one(state=state, questions={
    "severity": {
        "type": "score",
        "instructions": "Rate severity for an internal corporate portal.",
        "criteria": [
            "LOW: informational or minor hygiene issue",
            "MEDIUM: meaningful issue for a scoped/authenticated user",
            "HIGH: pre-auth or leads to RCE / full compromise",
        ],
    },
    "is_urgent": {"type": "noul", "instructions": "Needs human attention within 1 hour?"},
})
```

## 5. Production notes

- Fail open on transport errors — never silently drop a security-relevant decision.
- Log `{state_hash, qid, probabilities, choice}` for audit.
- Fit a temperature per workload before trusting `confidence` ([CALIBRATION](CALIBRATION.md)).
- Pin `revision=` on both the HF repo and `nagi` package version.
