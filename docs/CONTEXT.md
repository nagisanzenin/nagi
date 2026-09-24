# Context limits

SDK v0.4.1 raises the default `load_big()` prompt cap from 768 to **4,096 tokens**. Inputs already fitting the old cap keep the same rendered prompt; a larger cap does not pad them. The renderer still trims state when the requested cap is exceeded and raises if the schema alone cannot fit. This change does not add a decoding loop or change model weights.

```python
from nagi import load_big
model = load_big(max_input_tokens=4096)
```

To reproduce the published Big v3 benchmark from SDK v0.4.0, use `load_big(max_input_tokens=768)` or install that SDK tag. The archived benchmark remains unchanged; it measured the old cap. Experimental high-cardinality/chat-template settings are not covered by this context probe.

A light H100 diagnostic used eight underlying lookup/rule cases, repeated at two lengths and three evidence positions. Big short outputs were identical (0 probability difference); expanded long-context correctness was48/48 versus36/48 at the old cap. These repeated easy tasks do not establish broad long-context generalization. At roughly3k state tokens, observed P95 was276–285ms across positions; the earlier sub250ms short-input figures do not extend to all lengths.

Smol keeps its **512-token default** and64-token options. An opt-in longer state plus dynamic padding is available:

```python
from nagi import load_smol
model = load_smol(max_state_tokens=2048, dynamic_state_padding=True)
```

Dynamic padding avoids computing2048 state positions for short inputs; option tensors keep their fixed64-token shape. The probe's short choices stayed unchanged (maximum probability difference3.28e-6), but expanded long-context accuracy was24/48, with only4/8 short cases correct. Reading more tokens did not establish useful retrieval for this checkpoint. The option is experimental, not a claim of robust long-context reasoning. No training was performed.

[All cases, raw predictions, configs and analysis](https://github.com/nagisanzenin/nagi-research/tree/main/docs/context_probe).
