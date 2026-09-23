> Update 2026-09-24: Big v3 is now public and the SDK default. The text below
> records the original campaign status. See [release decision](V3_RELEASE.md).

# Campaign v3 — experimental checkpoint, September 23, 2026

The selected v3 checkpoint improves over the G-clean v2 candidate on new final
suites. It **does not beat JEV 1.13.0**. It remains private staging; installing the
SDK does not change its public v0 defaults.

| Fresh final macro accuracy | G-clean | Nagi v3 | JEV |
|---|---:|---:|---:|
| Public: 2,204 examples, four tasks | 69.12% | 75.80% | 91.40% |
| Policy: 1,440 examples, six families | 47.22% | 68.19% | 84.51% |
| Typed policy subset: 960 examples | 40.94% | 60.73% | 79.48% |

Macro averages weight tasks/families equally and count failures as wrong. Nagi
coverage is 100%; JEV policy coverage is 99.72%. The typed set overlaps policy.
These are different tasks from v2 final, so absolute v2/v3 scores cannot be used
as a before/after comparison. G-clean was re-evaluated on the same v3 inputs.

V3 − G-clean paired 95% intervals: public +3.87 to +9.29 percentage points; policy
+18.40 to +23.68 points. V3 − JEV 97.5% intervals are negative on both primary
suites. Gains are not universal: conditional XOR/count accuracy dropped from
15.83% to 11.67%. WSC coreference remains weak at 47.12% vs JEV 87.50%.

Training retained G-clean and extended LoRA to additional projections, using
5,999 public examples and 6,000 balanced executable-oracle examples. A fresh wide
candidate and a frozen-feature residual-head probe were rejected. No new head is
needed by the chosen checkpoint. Actual SDK vs research probabilities matched
within 1e-7 on thirteen nonfinal probes across choice, score and noul; save/reload
and BF16 merge checks passed. This is evidence of implementation parity, not a
guarantee of accuracy or calibration for arbitrary user policies.

Private artifact (requires explicitly granted HF read access):
[nagi-big-v3-warm-balanced-20260923](https://huggingface.co/nagisanzeninz/nagi-big-v3-warm-balanced-20260923),
revision `8d74b34f42e63553a49cc7238feb497cafb3fc2c`.
Use base revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` and temperature
`0.8493753016322345` with the existing `load_big` API, raw renderer, K≤26. The
existing limited read token may need access to the new private repository.

[Research protocol, data hashes and receipts](https://github.com/nagisanzenin/nagi-research/tree/main/docs/campaign_v3)
include the full comparison and limitations. Public pretraining contamination is
not ruled out; only four public tasks and six program families were evaluated.
The v3 final sets are now consumed for subsequent research.
