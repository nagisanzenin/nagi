# Nagi

**Typed decisions with calibrated probabilities.**  
Choice · Score · Noul — in 11–58 ms, self-hosted.

Nagi is a System One model family: given a state, a question, and a closed option set, it returns a typed decision and a probability distribution over that set. It does not generate text.

```python
from nagi import load_smol

nagi = load_smol()
out = nagi.system_one(state=dossier, questions={
    "verdict": {
        "type": "choice",
        "instructions": "TP only if the evidence proves exploitability.",
        "criteria": {
            "TP": "The dossier proves the vulnerability is exploitable.",
            "FP": "It does not prove exploitability, or is a scanner artifact.",
        },
    }
})
# → {"choice": "TP", "probabilities": {"TP": 0.82, "FP": 0.18}, "confidence": 0.82}
```

---

## Models

| | **Nagi-Smol** | **Nagi-Big** |
|---|---|---|
| | [nagisanzeninz/nagi-smol-v0](https://huggingface.co/nagisanzeninz/nagi-smol-v0) | [nagisanzeninz/nagi-big-v0](https://huggingface.co/nagisanzeninz/nagi-big-v0) |
| Backbone | ModernBERT-large · M2′ dual encoder + option tower | Qwen3.5-4B · PiSSA (r=32) letter-logits |
| Parameters | 421M | 4B (+ LoRA adapter) |
| LTO hard ↑ | 0.425 | **0.750** |
| ECE ↓ | 0.084 | **0.047** |
| p50 latency ↓ | **17 ms** | 58 ms |
| Role | throughput / edge / cost | accuracy on unseen schemas |

Legacy: [nagi-t4-m2p-v0](https://huggingface.co/nagisanzeninz/nagi-t4-m2p-v0) (T4 M2′, LTO 0.48).

---

## Benchmark

Leave-task-out on six real public classification tasks (**gold_ltout**, n = 2700):  
MRPC · DBpedia-14 · Amazon Polarity · CoLA · 20 Newsgroups · QQP.  
Same scorer for every arm · full N · single H100 · 2026-09-23.

| Model | hard ↑ | soft ↑ | Brier ↓ | ECE ↓ | p50 ↓ | p95 |
|---|---:|---:|---:|---:|---:|---:|
| Jev (`jev-latest`, TypeSafe API) | **0.774** | **0.684** | 0.296 | 0.120 | 172 ms | 234 ms |
| **Nagi-Big** | 0.750 | 0.594 | **0.251** | **0.047** | 58 ms | 80 ms |
| OpenJev (SemIf, frozen Qwen-4B) | 0.714 | 0.569 | 0.278 | 0.046 | 72 ms | 103 ms |
| Laya (`convaiinnovations/laya`) | 0.495 | 0.501 | 0.617 | 0.365 | **16 ms** | 18 ms |
| **Nagi-Smol** | 0.425 | 0.376 | 0.481 | 0.084 | 17 ms | 22 ms |

**Reading the table**
- *hard* = argmax match to gold; *soft* = mean 〈p, gold〉; *Brier* = mean ‖p − gold‖².
- *ECE* = expected calibration error on P(argmax), 10 bins (lower is better).
- All five arms, one scorer, full N = 2700, single H100, 2026-09-23T11:33Z. Jev n = 2699 (1 dropped).
- Laya shipped invalid temperatures (`choice:11+` clamped) — its confidence is uncalibrated as published.
- OpenJev = SemIf recipe: frozen Qwen3.5-4B, one forward, softmax over option-letter logits (no finetune).
- Latency is batch-1 CUDA-synced on H100; Jev p50 is remote API (includes network).

**Headline.** Nagi-Big is **−0.024 hard** behind proprietary Jev, with **2.3× lower latency**, **better Brier and ECE**, and public weights. It beats OpenJev on every quality metric and Laya on accuracy by +0.25.

Method, seeds, and re-run commands: [`bench/README.md`](bench/README.md) · [`bench/REPRODUCE.md`](bench/REPRODUCE.md).

---

## Install

```bash
# Python ≥ 3.10
pip install torch transformers peft huggingface_hub pyyaml
pip install "nagi-decisions @ git+https://github.com/nagisanzenin/nagi.git"
```

Or from source:

```bash
git clone https://github.com/nagisanzenin/nagi
cd nagi-public && pip install -e .
```

**Hardware.** Smol runs on CPU (slower) or any GPU. Big wants ≥ 16 GB VRAM (BF16).

```python
from nagi import load_smol, load_big

smol = load_smol()   # 421M, ~17 ms
big  = load_big()    # 4B + PiSSA, ~58 ms
```

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

M2′ (Smol) is a dual encoder: a bidirectional state tower and an independent per-option tower, scored by a bilinear MLP — no cross-option interference, high cardinality (K ≳ 20) stays stable. Nagi-Big is a causal 4B with PiSSA low-rank adaptation and Choice-B full-candidate scoring: options appear in-context; the model reads calibrated letter logits in one forward pass (no decoding loop). Both are trained on soft teacher distributions (KL to q), never hard labels alone. Training mix balances real multi-task public corpora with novel synthetic schemas for leave-task-out transfer.

---

## Documentation

| | |
|---|---|
| [Install & first call](docs/INSTALL.md) | 10-minute setup |
| [Agent recipes](docs/RECIPES.md) | verify TP/FP · severity · eval node |
| [Calibration](docs/CALIBRATION.md) | temperature fit, ECE, thresholds |
| [Benchmark protocol](bench/README.md) | splits, arms, metrics, threats to validity |
| [Reproduce](bench/REPRODUCE.md) | exact commands + seeds + receipt hashes |

---

## License

Code: Apache-2.0.  
Weights: see each model card on Hugging Face.
