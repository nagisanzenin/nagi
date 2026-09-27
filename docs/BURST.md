# Burst: every control in one forward pass

> **SDK 0.6.0.** `load_enormous_burst()` refuses to load until `BURST_REVISION` in `src/nagi/enormous.py` is pinned to
> the published Hugging Face commit of the weights. If the weights repo is missing, still private or the revision is
> wrong, it stops with a clear error before downloading the 27B base model.
>
> [Burst benchmark report](../bench/burst/README.md) · [Burst page](https://nagisanzenin.github.io/nagi/burst/) ·
> [Game Arena](https://nagisanzenin.github.io/nagi/arena/) · [Model card](https://huggingface.co/nagisanzeninz/Nagi-ENORMOUS-Burst)

Some decisions come in groups: a game tick sets the pump, the upper gate and the lower gate at the same time. The
default mode (`mode="kcall"`) asks one question per forward pass, so K controls cost K forwards. **Burst**
(`mode="burst"`) renders all K controls into one prompt with one answer slot each, and reads every slot from a single
forward pass. The slots are filled with a fixed blank, so no control sees another control's answer: the choices are
simultaneous.

Burst was called **Chord** during research. `mode="chord"`, `encode_chord()` and `render_chord_prompt()` still work
and emit a `DeprecationWarning`.

## Use

```python
from nagi import load_enormous_burst     # 80 GB GPU (H100), BF16, adapter merged in place

nagi = load_enormous_burst()
state = (
    "RULES: keep the boat level.\n"
    "tick 3: water 0.4 m\n\n"
    "CONTROLS (set together each tick): upper_gate = closed | open; lower_gate = closed | open; pump = down | idle | up."
)
questions = {
    "upper_gate": {"type": "choice", "instructions": "Choose the upper_gate setting.",
                   "criteria": {"closed": "upper gate stays closed this tick", "open": "upper gate is open this tick"}},
    "lower_gate": {"type": "choice", "instructions": "Choose the lower_gate setting.",
                   "criteria": {"closed": "lower gate stays closed this tick", "open": "lower gate is open this tick"}},
    "pump": {"type": "choice", "instructions": "Choose the pump setting.",
             "criteria": {"down": "pump water out", "idle": "leave pump idle", "up": "pump water in"}},
}
out = nagi.system_one(state, questions, mode="burst")
print({qid: a["choice"] for qid, a in out["answers"].items()})
```

The answer for each control has the same shape as in K-call mode (`probabilities`, `confidence`, and `choice`,
`score` or `noul`). Answers come back keyed in your question order. Burst adds `out["burst"]` with the slot order
used, its source, and the number of forwards.

## Control order

The slot order changes the model's answers. Without canonicalization, rotating the control order by one changes the
joint action on **24.8% [17.5%, 32.2%]** of 500 states on the release serving path (research measured 26.0%
[18.4%, 34.3%]; that preregistered order gate, Chord P1 REJECT-ORDER, failed and stays failed). The model is **not**
order-invariant. The SDK therefore renders the controls in one **canonical order**:

1. `control_order=[...]` if you pass it (it must be a permutation of the question ids);
2. otherwise the order of the state's `CONTROLS (set together each tick): a = ...; b = ...` line, the layout the model
   was trained on;
3. otherwise the question ids sorted by code point.

So through the SDK, the answers do not depend on the order in which you list the controls in `questions` (release gate
G1-SDK: 500 / 500 states). They do depend on the order you **declare**: a different `control_order` or CONTROLS line
is a different model input, and orders other than your environment's declared one are unevaluated. Declare the order
your environment defines, keep it fixed, and if you call the model without the SDK, present the controls in that same
canonical order. All published quality numbers are for the canonical order.

**Permutation averaging (experimental, not released).** `permutations="cyclic"` (K rotations) or `permutations="all"`
(K! orders, K ≤ 4) averages each control's probabilities over re-rendered slot orders, at one forward per order. It is
off by default and is not the released configuration: the preregistered permutation-averaged variant failed its release
gates (latency p50 1,039 ms on Booster Gauntlet at 3 streams, above the 300 ms limit; order residual upper bound 13.2%,
above 10%). The released readout is variant A: canonical order, one forward.

## What Burst is and is not

- Weights: [`nagisanzeninz/Nagi-ENORMOUS-Burst`](https://huggingface.co/nagisanzeninz/Nagi-ENORMOUS-Burst), a rank 8
  LoRA on `Qwen/Qwen3.8-27B` (revision `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`, Apache-2.0), trained on both the
  K-call and the Burst formats. `mode="burst"` on other Nagi weights warns: they were not trained for it.
- Validated path: CUDA BF16, eager attention, adapter merged in place (`merge=True`, the default), fused
  Gated-DeltaNet kernels installed. `merge=False` can flip near-tie answers relative to the measured path.
- Choice questions with 2–26 options per control; inputs up to 4096 tokens, trained up to 768; no silent truncation.
- Burst is a latency feature for multi-control decisions. It does not make a single decision more accurate, and in a
  compute-matched lockstep test (no time pressure) it did worse than K-call on the same weights.
- Evaluated for up to 4 controls (K = 3 offline, K = 1, 3, 4 in the Arena v3 games); K ≥ 5 is unevaluated.
- In realtime Rotorwash-Ramp, 12 of 24 fresh rounds ended in a ceiling crash (a preregistered disclosure flag), and on
  Snake Rush the model survives less long than a naive scripted player. See the model card's Limitations.

## Evidence

All gates were preregistered before any Burst data; numbers are from the frozen release receipts. Full definitions,
denominators and limitations: the [model card](https://huggingface.co/nagisanzeninz/Nagi-ENORMOUS-Burst) and the
[Burst benchmark report](../bench/burst/README.md).

| Measure | Result | Scope |
|---|---|---|
| Decision latency p50 at 3 concurrent streams (one-sided 97.5% upper bound) | Snake Rush 216.3 ms (219.5), Rotorwash-Ramp 247.7 ms (269.0), Booster Gauntlet 196.2 ms (263.6); gate: bound ≤ 300 ms, PASS | H100, merged BF16, fused kernels, micro-batched; no claim for other hardware |
| Multi-control quality vs K-call of the same weights (MA1) | Δ̂ −0.005, one-sided 97.5% lower bound −0.045: non-inferior within 0.06, PASS | 780 decision instances, 13 synthetic genres, canonical order |
| Order through the SDK | identical token ids for every client listing order on 500 / 500 states, PASS | declared order fixed |
| Order, model level (no canonicalization) | 24.8% [17.5%, 32.2%] of joint actions change when the order is rotated | disclosed; REJECT-ORDER not passed |
| Arena v3 realtime vs Jev | survived longer than Jev in 67.4% [57.7%, 77.0%] of head-to-heads; outperforms Jev overall (sign-flip p = 0.0018); per game only on Booster Gauntlet (0.979); Rotorwash-Ramp 0.583 and Snake Rush 0.458 not significant | 24 fresh seeds × 3 games, 0 void rounds |
