# Nagi

![Nagi — Typed decisions. Visible probabilities.](docs/brand/nagi-banner.png)

**Typed decisions in one forward pass.** Nagi takes a state and a closed set of options and returns a choice with a probability distribution. Four open model lines: SMOL 0.5B · BIG 4B · HUGE 12B · ENORMOUS 27B.

[**Watch Arena Live →**](https://nagisanzenin.github.io/nagi/arena-live/) · [All replays](https://nagisanzenin.github.io/nagi/arena/) · [Models on Hugging Face](https://huggingface.co/nagisanzeninz) · [Full benchmarks](docs/BENCHMARKS.md)

## Arena Live

Three real-time games: a 240 Hz helicopter, four-player Tron and a Tetris battle. 10 rounds each, the same seeds for every model, lockstep play (latency is shown, not scored).

![Arena Live: Nagi-ENORMOUS first with 83/90 points against Jev, OpenJev and Laya](docs/charts/arena_vendors.svg)

![Rotorwash: ENORMOUS stays airborne 35.8 s median vs Jev 13.8 s](docs/charts/rotorwash_airborne.svg)

![The four Nagi lines: 76, 65, 39, 7 points](docs/charts/arena_nagi_lines.svg)

An exhibition, not a universal ranking. It measures skill under known rules; on reading brand-new rules, 27B does not yet beat 12B. [Per-game tables](bench/arena_live) · [Interactive page](https://nagisanzenin.github.io/nagi/arena-live/)

## Public suite

![Public suite: ENORMOUS 82.76% vs Jev 83.95%, statistically tied](docs/charts/public_suite.svg)

[Per-source results, latency and method](docs/BENCHMARKS.md#public-benchmark--four-systems-inspectable-evidence)

## Install

```bash
python -m pip install "nagi-decisions @ git+https://github.com/nagisanzenin/nagi.git"
```

Python 3.10+. The import is `nagi` (the unrelated PyPI package `nagi` is not this project). Weights download from Hugging Face on first load.

```python
from nagi import load_smol          # CPU; load_big / load_huge / load_enormous need a GPU

nagi = load_smol(device="cpu")
out = nagi.system_one(state={"message": "Please cancel my subscription."}, questions={
    "route": {
        "type": "choice",
        "instructions": "Select the team that should handle the request.",
        "criteria": {"billing": "Subscriptions and payments", "technical": "Technical issues"},
    }
})
print(out["answers"]["route"])  # {"choice": ..., "probabilities": {...}, "confidence": ...}
```

| Line | Loader | Base | Runs on |
|---|---|---|---|
| [SMOL 0.5B](https://huggingface.co/nagisanzeninz/nagi-smol-v0) | `load_smol()` | ModernBERT-large | CPU |
| [BIG 4B](https://huggingface.co/nagisanzeninz/nagi-big-v3) | `load_big()` | Qwen3.5-4B | GPU, BF16 |
| [HUGE 12B](https://huggingface.co/nagisanzeninz/Nagi-HUGE) | `load_huge()` | Gemma4 12B + adapter | H100 BF16 (~24 GB params) |
| [ENORMOUS 27B](https://huggingface.co/nagisanzeninz/Nagi-ENORMOUS) | `load_enormous()` | Qwen3.8-27B + adapter | 80 GB GPU, BF16 |
| [ENORMOUS Burst 27B](https://huggingface.co/nagisanzeninz/Nagi-ENORMOUS-Burst) | `load_enormous_burst()` | Qwen3.8-27B + adapter, merged | 80 GB GPU, BF16 |

Question types: `choice` (pick a label), `score` (ordered levels), `noul` (probability of true). 2–26 options per question; context limits differ per line ([details](docs/CONTEXT.md)). Probabilities are conditional on the options you supply, not guarantees.

[Install guide](docs/INSTALL.md) · [Recipes](docs/RECIPES.md) · [Calibration](docs/CALIBRATION.md) · [Burst](docs/BURST.md) · [ENORMOUS release](docs/ENORMOUS_RELEASE.md) · [HUGE release](docs/HUGE_RELEASE.md) · [Brand](docs/brand/brand-guideline.md)

## Burst

**Burst** (`mode="burst"`, ENORMOUS Burst weights) answers several simultaneous controls, such as a gate and a pump in one game tick, in one forward pass instead of one pass per control.

```python
from nagi import load_enormous_burst

nagi = load_enormous_burst()  # 80 GB GPU, BF16, adapter merged in place
state = "tick 3: water 0.4 m\nCONTROLS (set together each tick): gate = closed | open; pump = down | idle | up."
out = nagi.system_one(state, {
    "gate": {"type": "choice", "instructions": "Choose the gate setting.",
             "criteria": {"closed": "gate stays closed", "open": "gate is open"}},
    "pump": {"type": "choice", "instructions": "Choose the pump setting.",
             "criteria": {"down": "pump water out", "idle": "leave pump idle", "up": "pump water in"}},
}, mode="burst")  # one forward for both controls
print({qid: a["choice"] for qid, a in out["answers"].items()})
```

In Arena v3 realtime (24 fresh seeds × 3 games), Burst survived longer than Jev in 67.4% [57.7%, 77.0%] of head-to-heads: better overall, and per game only on Booster Gauntlet. Decision latency p50 is 196–248 ms at 3 concurrent streams on H100. The model is not order-invariant (24.8% of joint answers change when the control order is rotated), so the SDK always renders the declared order: `control_order`, else the `CONTROLS` line, else sorted ids.

[Burst report](bench/burst/README.md) · [Burst page](https://nagisanzenin.github.io/nagi/burst/) · [Game Arena](https://nagisanzenin.github.io/nagi/arena/) · [Usage and limits](docs/BURST.md) · [Model card](https://huggingface.co/nagisanzeninz/Nagi-ENORMOUS-Burst)
