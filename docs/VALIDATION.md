# SDK 0.2.1 validation — 2026-09-23

Verified locally from a fresh, isolated macOS environment:

- Built and installed a non-editable wheel with `python -m pip install . pytest`.
- `python -m pip check`: no broken requirements.
- Seven tests passed: four model/option contract tests and three documentation tests.
- `python examples/verify_tp_fp.py --device cpu`: ran real public Smol inference.
- Executed each Smol Python block from README, INSTALL and RECIPES in a fresh
  namespace with real public weights, including choice, score and noul.
- Confirmed imports resolve to the installed package in site-packages, not the
  source checkout or research repo.

Environment: Python 3.14, torch 2.14.0, transformers 5.17.0, peft 0.21.0,
huggingface_hub 1.32.0. Full CPU example logs are retained with the local task.
Big CUDA inference/SDK parity was separately verified in campaign v2 on H100 with
torch 2.5.1+cu124, transformers 5.17.0 and peft 0.21.0. The Big CUDA documentation
block was not run on this Mac. MPS and Windows were not tested.

Documentation unit tests replace model loading with a lightweight stub solely to
catch missing variables and malformed examples without downloads in CI. They do
not substitute for the real CPU/GPU checks above. The GitHub Actions workflow
covers Python 3.11/3.12; remote CI has not run until these commits are pushed.
