# Install and first call

## Install from GitHub

Use Python 3.10 or newer and Git. Create an isolated environment so another package
named `nagi` cannot shadow the SDK:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install "nagi-decisions @ git+https://github.com/nagisanzenin/nagi.git"
python -m pip check
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell. The distribution
name is `nagi-decisions`; import it as `nagi`. Dependencies are declared in
`pyproject.toml`; separate unversioned installs are unnecessary. Transformers 4.x
is too old for this SDK's Big backbone; use the declared dependency range.

For development, clone `https://github.com/nagisanzenin/nagi.git`, enter the newly
created `nagi` directory, then run `python -m pip install -e .` inside your environment.

## Complete first call

Smol downloads its public checkpoint and ModernBERT backbone on first use. Allow
network access and several GB of disk and RAM. A Hugging Face token is not needed
for the public defaults; private candidate checkpoints require authorized access.

```python
from nagi import load_smol

model = load_smol(device="cpu")
state = "The package arrived broken. Store policy allows refunds for arrival damage."
questions = {
    "refund": {
        "type": "choice",
        "instructions": "Approve if store policy allows a refund for the described issue.",
        "criteria": {"approve": "Policy allows a refund.", "decline": "Policy does not allow a refund."},
    },
    "severity": {
        "type": "score",
        "instructions": "Rate damage using the listed levels.",
        "criteria": ["No damage", "Cosmetic damage", "Broken or unusable"],
    },
    "damaged": {"type": "noul", "instructions": "Does the state say the package is damaged?"},
}
result = model.system_one(state=state, questions=questions)
print(result["answers"])
```

`choice` is an option key; `score` is the expected zero-based level index; `noul`
is P(true). Each answer also has a full `probabilities` mapping and `confidence`.
Predictions vary; these examples are executable API demonstrations, not quality guarantees.

## Devices and Big

The CPU path is the simplest first call. Set `device="cuda"` for a CUDA-enabled
PyTorch environment. The benchmark used H100; its timings do not apply to CPU.
MPS is not covered by the campaign validation. Big has 4B parameters; allow at
least 16 GB CUDA VRAM for BF16 and extra loading headroom. CPU Big uses FP32 and
needs substantially more memory.

```python
from nagi import load_big

model = load_big(device="cuda")
result = model.system_one(
    state="A shipment arrived two days after its promised delivery date.",
    questions={"late": {"type": "noul", "instructions": "Was delivery late?"}},
)
print(result["answers"]["late"])
```

Big supports at most 26 options by default and raises an error for larger schemas.
The optional `max_options=78` path is experimental. Both public loaders still
select v0 weights. SDK 0.2.1 fixes rendering and validation of option symbols;
it does not silently promote the private G-clean candidate.

## Troubleshooting and reproducibility

- `ModuleNotFoundError` or unexpected imports: run `python -m pip show nagi-decisions`
  and `python -c "import nagi; print(nagi.__file__)"` in the same environment.
- Unknown model architecture or import errors: install the SDK's dependencies,
  run `python -m pip check`, and avoid a pre-existing Transformers 4.x environment.
- HTTP 401/403: check whether the selected repository is private/gated and authenticate
  with an account that has access. Never paste tokens into source code.
- Out of memory: start with Smol on CPU; changing Big to CPU requires more host RAM.
- For reproducibility, use actual immutable commit SHAs for the Git install URL
  (`...nagi.git@<commit>`) and HF `revision=`. Big also accepts `base_revision=`.
  A branch named `main` is not an immutable revision.
- Temperature defaults to 1.0. Fit it on a separate calibration set before using
  confidence thresholds; see [calibration](CALIBRATION.md).
