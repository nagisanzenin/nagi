# Reproduce the Nagi 5-way benchmark

One command, one GPU, ~12 minutes on an H100 (excluding image build).

## 0. Requirements

- Modal account (or any CUDA box with the pip pins below)
- `TYPESAFE_API_KEY` only for the Jev arm (optional — other four arms run without it)
- Access to HF repos: `nagisanzeninz/nagi-smol-v0`, `nagisanzeninz/nagi-big-v0`, `Qwen/Qwen3.5-4B`, `answerdotai/ModernBERT-large`, `convaiinnovations/laya`
- Modal volume `nagi-results` containing folders `t4s_hail_s_c2/` and `hailg_g1/`  
  *(or edit `modal_bench5.py` to download Smol/Big from HF instead of the volume)*

## 1. Environment pins

```text
torch==2.5.1+cu124
transformers>=4.48
peft>=0.14
accelerate
safetensors
numpy
pyyaml
tqdm
laya==0.3.7
python=3.11
```

## 2. Run

```bash
export TYPESAFE_API_KEY=…          # optional, for Jev
modal run /abs/path/scripts/modal_bench5.py --tag b5
```

Artifacts land in Modal volume `nagi-results/bench5_b5/` and locally in `runs/bench5_b5_result.json`:

| File | Contents |
|---|---|
| `smol.json` `big.json` `openjev.json` `laya.json` `jev.json` | n, hard, soft, Brier, ECE, p50, p95 |
| `summary.json` | all arms |
| `bench5.log` | full stdout |

## 3. Deterministic choices (already fixed in code)

| Knob | Value |
|---|---|
| Split | `data/gold_ltout.jsonl` (sha256 in job manifest when published) |
| n | 2700 (full, no subsample) |
| Device | `cuda` (H100) |
| Dtype | BF16 for Qwen arms, FP32 heads for M2′ |
| max-length | 768 (Qwen prompts), 384/512 state (Smol config) |
| Letter space | `A…Z` first 26 options |
| Temperature | 1.0 raw (no post-hoc T fit in the headline table) |
| Retry (Jev) | 5 attempts, expo backoff, drop on failure |

## 4. Score locally from preds (optional)

If you dump `preds[id][qid] = {key: p}`, the scorer in `modal_bench5.py::score` is reference:

```python
hard  = mean(argmax p == argmax q)
soft  = mean(<p, q>)
brier = mean(||p − q||²)
ece   = 10-bin ECE(max(p), hard_correct)
```

## 5. Expected numbers (2026-09-23 receipt)

| Arm | hard | soft | Brier | ECE | p50 ms |
|---|---:|---:|---:|---:|---:|
| Jev | 0.774 | 0.684 | 0.296 | 0.120 | 172 |
| Nagi-Big | 0.750 | 0.594 | 0.251 | 0.047 | 58 |
| OpenJev | 0.714 | 0.569 | 0.278 | 0.046 | 72 |
| Laya | 0.495 | 0.501 | 0.617 | 0.365 | 16 |
| Nagi-Smol | 0.425 | 0.376 | 0.481 | 0.084 | 17 |

Receipt `2026-09-23T11:33:56Z` · runner SHA256 `d2522362cf64cf733590abb1455de527fb9b6229a9189c1a748c89441de17e92` (`modal_bench5.py`). Full log SHA256 in `bench/results/SHA256SUMS`.

## 6. Receipt hash

After your run:

```bash
shasum -a 256 runs/bench5_receipt/* results/summary.json
```

Record GPU name (`torch.cuda.get_device_name(0)`), driver, and UTC timestamp in the receipt header.

## 7. Known deviations to disclose if you change anything

- Production `system_one` vs harness `use_schema_options` (see bench/README threats).
- Laya temperature clamp on `choice:11+`.
- Jev network latency vs local GPU latency (not a pure compute comparison).
