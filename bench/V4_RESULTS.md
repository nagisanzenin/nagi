> Update 2026-09-24: Big v3 is now public and the SDK default. The text below
> records the original campaign status. See [release decision](V3_RELEASE.md).

# V4 generalization audit — no model release

One additional training configuration improved diagnostic task-family accuracy
from 68.13% to 80.83%, but that gain did not transfer to different held-out families.
The candidate failed its preregistered release gates. **No v4 model was published;
SDK code and public v0 defaults remain unchanged.** V3 remains private research
staging; this session did not promote it as a fallback after the v4 failure.

| Same-suite macro accuracy | Public Big v0 | V3 | V4 candidate |
|---|---:|---:|---:|
| Unseen policy: 1200 examples, 6 families |40.08%|78.00%|78.33%|
| Language: 800 examples, 4 tasks |54.63%|68.00%|66.63%|
| Historical typed regression: 640 examples |47.81%|82.81%|82.66%|

V4−v3 hierarchical paired bootstrap 95% intervals (resampling families and items):
policy **+0.33pp [−4.33,+4.83]**; language **−1.38pp [−3.75,+0.88]**.
The policy target was at least +5pp with a positive lower bound; language required
noninferiority within −2pp. Neither passed. The language interval includes zero:
this is failure to establish noninferiority, not a statistically conclusive loss.
All models had 100% output coverage. No checkpoint switching after final scores.

The 6 synthetic final families are disjoint from v4 training/development families.
They share elementary primitives and an English renderer; this is not a claim of
arbitrary real-world generalization. Public tasks are ANLI-R2, HellaSwag, WiC and
BoolQ. Known overlapping text was excluded, but pretraining exposure is unknown.
The typed rows were previously used for development and are not independent tests.

A 9B original backbone in native chat mode reached 53.13% policy /81.67% language
on diagnostic data, versus v3's 68.13% /83.13%. This did not justify changing the
backbone under this session's gate. It does not establish that a comparably
fine-tuned 9B model cannot outperform 4B.

The candidate's BF16 merge changed probabilities by up to 0.0476 on 16 nonfinal
probes, despite identical argmax. Unmerged execution preserved exact reload logits
and matched the SDK Nagi readout within 1.44e-7 on 13 probes. Its measured batch1 H100
SDK latency was approximately 96ms p50 /107ms p95, without HTTP. It still failed
quality gates, so no loader/default change was shipped.

No new JEV API evaluation occurred. Do not compare these absolute scores with the
different v3/JEV final suite or claim a JEV win. Full protocol, data hashes,
per-item predictions, safety fault injections and budget accounting are in the
[research campaign](https://github.com/nagisanzenin/nagi-research/tree/main/docs/campaign_v4).
