# Burst: every control in one forward pass

> **Draft for SDK 0.6.0, not released yet.** `BURST_REVISION` in `src/nagi/enormous.py` is unpinned, so
> `load_enormous_burst()` refuses to load until the owner approves the release and the Hugging Face commit is pinned.
> Every `{{...}}` placeholder below must be filled from the frozen release receipts before this page is merged.

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

The slot order changes Burst's answers. In research, rotating the slot order by one changed the joint action on
**26%** of states (Chord P1, 500 states, 95% CI [18%, 34%]); that result failed the preregistered order gate
(REJECT-ORDER) and stays failed. The SDK therefore renders the controls in one **canonical order**, so the same
request always gives the same prompt:

1. `control_order=[...]` if you pass it (it must be a permutation of the question ids);
2. otherwise the order of the state's `CONTROLS (set together each tick): a = ...; b = ...` line, the layout the model
   was trained on;
3. otherwise the order of your `questions` dict.

Put the controls line in your state, or pass `control_order`, in the order your environment defines. Do not reorder
controls between calls.

**Permutation averaging (experimental).** `permutations="cyclic"` (K rotations) or `permutations="all"` (K! orders,
K ≤ 4) averages each control's probabilities over re-rendered slot orders. It removes the order dependence but costs
one forward per order, which gives back most of Burst's latency advantage. It is off by default. Which variant ships
as the recommended setting is decided by the release's frozen selection rule: {{BURST_VARIANT}}.

## What Burst is and is not

- Weights: [`nagisanzeninz/Nagi-ENORMOUS-Burst`](https://huggingface.co/nagisanzeninz/Nagi-ENORMOUS-Burst), a rank 8
  LoRA on `Qwen/Qwen3.8-27B` (revision `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`, Apache-2.0), trained on both the
  K-call and the Burst formats. `mode="burst"` on other Nagi weights warns: they were not trained for it.
- Validated path: CUDA BF16, eager attention, adapter merged in place (`merge=True`, the default), fused
  Gated-DeltaNet kernels installed. `merge=False` can flip near-tie answers relative to the measured path.
- Choice questions with 2–26 options per control; inputs up to 4096 tokens, trained up to 768; no silent truncation.
- Burst is a latency feature for multi-control decisions. It does not make a single decision more accurate.

## Evidence

Filled from the frozen release receipts; see the model card for definitions, denominators and intervals.

| Measure | Burst | K-call (same weights) | Scope |
|---|---|---|---|
| Per-tick latency p50 | {{BURST_P50_MS}} | {{KCALL_P50_MS}} | {{LATENCY_SCOPE}} |
| Offline gates | {{OFFLINE_GATES}} | | {{OFFLINE_SCOPE}} |
| Arena v3 realtime | {{ARENA_RESULT}} | | {{ARENA_SCOPE}} |
