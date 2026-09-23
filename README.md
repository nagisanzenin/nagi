# Nagi

**Typed decisions and probability distributions.**

Choice · Score · Noul — self-hosted.

Nagi is a System One model family: given a state, a question, and a closed option set, it returns a typed decision and a probability distribution over that set. It does not generate text.

## Quickstart

Install first (Python 3.10+, Git required):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install "nagi-decisions @ git+https://github.com/nagisanzenin/nagi.git"
```

The distribution is `nagi-decisions`; the Python import is `nagi`. Do not install
an unrelated package named `nagi` from PyPI. The first model load downloads weights
from Hugging Face and needs network access and several GB of free disk/RAM.

This complete example uses the public Smol v0 checkpoint on CPU:

```python
from nagi import load_smol

dossier = {
    "finding": "Possible SQL injection in a login form",
    "evidence": "The test response returned database rows from another account.",
}
nagi = load_smol(device="cpu")
out = nagi.system_one(state=dossier, questions={
    "verdict": {
        "type": "choice",
        "instructions": "TP only if the evidence proves unauthorized data access; otherwise FP.",
        "criteria": {
            "TP": "The evidence proves unauthorized data access.",
            "FP": "The evidence does not prove unauthorized data access.",
        },
    }
})
print(out["answers"]["verdict"])
```

The answer contains `choice`, `probabilities`, and `confidence`. Values depend on
the model and input; this example does not promise a particular prediction.

---

## Models

| | **Nagi-Smol** | **Nagi-Big** |
|---|---|---|
| | [nagisanzeninz/nagi-smol-v0](https://huggingface.co/nagisanzeninz/nagi-smol-v0) | [nagisanzeninz/nagi-big-v3](https://huggingface.co/nagisanzeninz/nagi-big-v3) |
| Backbone | ModernBERT-large · M2′ dual encoder + option tower | Qwen3.5-4B · mixed-rank LoRA letter-logits |
| Parameters | 421M | 4B (+ LoRA adapter) |
| Scope | variable option sets | K≤26 by default; larger sets rejected |

Legacy: [nagi-t4-m2p-v0](https://huggingface.co/nagisanzeninz/nagi-t4-m2p-v0) (T4 M2′, LTO 0.48).

---

## Benchmark

**Big v3 is now the public default** for `load_big()`. It replaces Big v0;
Smol is unchanged. The adapter and base revisions are pinned by the SDK.

Same-suite comparison from campaign V4 (macro accuracy; higher is better):

| What was tested | Big v0 (previous) | **Big v3 (default)** | V4 (not released) |
|---|---:|---:|---:|
| Unseen policy families — 1,200 examples / 6 families |40.08%|**78.00%**|78.33%|
| Language understanding — 800 examples / 4 tasks |54.63%|**68.00%**|66.63%|
| Historical score/yes-no regression — 640 examples |47.81%|**82.81%**|82.66%|

All three had 100% output coverage. V4's policy advantage over v3 was only
+0.33 percentage points, with a 95% interval of −4.33 to +4.83; it did not establish
an improvement. We chose v3 for its balance of quality and validated deployment.
The typed rows are historical development data, not a fresh generalization test.
See [V4 evidence](bench/V4_RESULTS.md) and [release decision](bench/V3_RELEASE.md).

**Latest research: V5** improved policy accuracy by **4.25 percentage points over
a matched answer-only control** (95% family/item interval +0.58 to +7.83), without
extra inference steps. It still failed broad-transfer and language-preservation
release gates, so **v3 remains the default**. [V5 results and costs](bench/V5_RESULTS.md).

**Nagi has not beaten JEV.** On the separate V3 final suites:

| V3 suite (different examples from the table above) | Big v3 | JEV 1.13.0 |
|---|---:|---:|
| Public language — 2,204 examples / 4 tasks |75.80%|91.40%|
| Executable policy — 1,440 examples / 6 families |68.19%|84.51%|

Failures count as wrong; Nagi coverage100%, JEV policy coverage99.72%.
Do not compare scores across the two tables. These finite task suites do not
establish universal generalization; public pretraining exposure is unknown.
[V3 protocol and limitations](bench/V3_RESULTS.md).

V3 SDK latency on 13 probes was **47ms p50 /60ms p95**, batch1 on H100 without HTTP.
This is a small historical deployment check, not a service SLA or a matched-hardware
speed comparison with JEV. No text decoding loop is used.

The original v0/JEV benchmark was invalidated by label and demo leakage; its claims
remain withdrawn. [Audit archive](bench/HISTORICAL_V0.md).

```python
from nagi import load_big

nagi = load_big(device="cuda")  # public v3, pinned weights and calibration
out = nagi.system_one(state={"A": 7, "B": 3}, questions={
    "greater": {"type": "noul", "instructions": "Is A greater than B?"}
})
print(out["answers"]["greater"])
```

---

## Install

The Quickstart installs the SDK and its declared dependencies directly from GitHub.
For a local checkout:

```bash
git clone https://github.com/nagisanzenin/nagi.git
cd nagi
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python examples/verify_tp_fp.py --device cpu
```

**Hardware.** Start with Smol on CPU. CUDA is supported; the benchmark used an H100.
Big is a separate 4B model and needs substantially more memory; CUDA with at least
16 GB VRAM is recommended for BF16, with additional headroom for loading. MPS is
not covered by the campaign validation; use `device="cpu"` on a Mac for the first call.
See [installation and troubleshooting](docs/INSTALL.md).

---

## API

```text
system_one(state, questions) → {
  "answers": {
    "<qid>": {
      "choice": "…"            # type=choice
      "score": 1.23            # type=score (expected level)
      "noul": 0.87             # type=noul (P(true))
      "probabilities": {"…": p},
      "confidence": max p
    }
  }
}
```

| `type` | `criteria` | primitive |
|---|---|---|
| `choice` | `dict[key → description]` | Choice |
| `score` | `list[level description]` | Score |
| `noul` | — | Noul (yes/no probability) |

Closed option sets only — the model cannot invent labels.

---

## Design notes (one paragraph)

Smol uses a dual encoder with an option tower. Big v3 uses a causal 4B backbone
with mixed-rank LoRA and scores option-letter logits in one forward pass.
Its default temperature is 0.8493753016322345, fitted on a separate calibration set;
probabilities are not guaranteed calibrated on every new domain. V3 trained on
public hard labels and executable-oracle tasks, with additional weight on score
questions. Custom Big repositories retain temperature1 unless explicitly set.

---

## Documentation

| | |
|---|---|
| [Install & first call](docs/INSTALL.md) | 10-minute setup |
| [Agent recipes](docs/RECIPES.md) | verify TP/FP · severity · eval node |
| [Calibration](docs/CALIBRATION.md) | temperature fit, ECE, thresholds |
| [Benchmark protocol](bench/README.md) | splits, arms, metrics, threats to validity |
| [Historical reproduction](bench/REPRODUCE.md) | archived v0 commands; not a valid current comparison |

---

## License

Code: Apache-2.0.  
Weights: see each model card on Hugging Face.
