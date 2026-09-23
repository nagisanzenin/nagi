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
| | [nagisanzeninz/nagi-smol-v0](https://huggingface.co/nagisanzeninz/nagi-smol-v0) | [nagisanzeninz/nagi-big-v0](https://huggingface.co/nagisanzeninz/nagi-big-v0) |
| Backbone | ModernBERT-large · M2′ dual encoder + option tower | Qwen3.5-4B · PiSSA (r=32) letter-logits |
| Parameters | 421M | 4B (+ LoRA adapter) |
| Scope | variable option sets | K≤26 by default; larger sets rejected |

Legacy: [nagi-t4-m2p-v0](https://huggingface.co/nagisanzeninz/nagi-t4-m2p-v0) (T4 M2′, LTO 0.48).

---

## Benchmark

The v0 comparison was invalidated by mislabeled QQP examples and target-dependent
20NG/QQP demos. The previous claims about the gap to JEV, Brier and relative speed
must not be used. Historical tables remain in [the audit archive](bench/HISTORICAL_V0.md).

Campaign v2 rebuilds labeled QQP, removes gold-dependent inputs, stores per-item
predictions/errors and separates development, calibration and untouched final tasks.
Completed v2: the private Big candidate scored 76.73% public macro and 63.13% novel macro; JEV scored 81.36% and 99.38%. It did not pass the beat-JEV gate. See [full protocol and results](bench/README.md). Public model defaults remain v0. [Compared with Big v0](bench/V2_COMPARISON.md), the candidate improves novel rules but regresses on score/noul; it is not an across-the-board upgrade.

Campaign v3 has completed on **different, fresh final suites**: the experimental
checkpoint improves over G-clean, but still does not beat JEV. It remains private
staging; SDK defaults are unchanged. See [v3 results and limitations](bench/V3_RESULTS.md).

Campaign v4 tested transfer to different task families. Its dev gain did not carry
over to the final suite, so **no new model was released and defaults remain v0**.
See [v4 generalization audit](bench/V4_RESULTS.md) for the direct v0/v3/v4 comparison.

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

M2′ (Smol) is a dual encoder: a bidirectional state tower and an independent per-option tower, scored by a bilinear MLP — independent option encoding; high-K accuracy still needs task-specific evaluation. Nagi-Big is a causal 4B with PiSSA low-rank adaptation and Choice-B full-candidate scoring: options appear in-context; the model reads letter logits (temperature defaults to 1.0) in one forward pass (no decoding loop). Both are trained on soft teacher distributions (KL to q), never hard labels alone. Training mix balances real multi-task public corpora with novel synthetic schemas for leave-task-out transfer.

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
