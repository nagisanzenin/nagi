# Public Big v3 release — 2026-09-24

The research promotion gate asked whether V4 improved over V3. That failed.
The product release decision asks whether a validated existing model should replace
public V0. User authorized that separate review after seeing the V4 comparison.
V3 is selected using existing evidence, not a new preregistered untouched test.

V3 scored 78.00/68.00/82.81% versus V0 40.08/54.63/47.81% on V4 policy/language/
historical typed suites. V4 scored78.33/66.63/82.66%; its policy gain over V3 was
inconclusive. V3 also has validated merged execution; V4 required unmerged execution.
This does not establish V3 is statistically better than V4 on every metric.

Public model: https://huggingface.co/nagisanzeninz/nagi-big-v3
Adapter revision: `0357e819836f5f396f7586d8ac04f7c955148f99`.
Base revision: `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`.
Adapter SHA256: `cbade091c3aa84b7fd9d814655f61ce64528bbdc4465851ef23ffc2bf77f585d`.
Temperature:0.8493753016322345. No training or calibration was rerun for this release.

The downloaded private staging artifact was hash-verified before copying unchanged
weights to the public repository. Original checks: exact save/reload logits;
BF16 merge max probability delta0.01548, 100% argmax agreement; SDK/research
probability agreement <1e-7 on13 probes across question types. These are historical
H100 checks of the identical adapter, not newly rerun GPU tests.

SDK defaults now pin weights/base/calibration, and put the merged model in eval mode.
Explicit custom repo/revision and temperature overrides remain supported.
Smol stays unchanged. Old Big remains available via
`load_big(repo="nagisanzeninz/nagi-big-v0", temperature=1.0)`.
See README for honest JEV comparison, limits, and installation from GitHub.
