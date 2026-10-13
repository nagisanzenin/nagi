"""nagi.burst2 defaults are exactly the frozen evaluated configuration (V2 release plan B-R3)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from nagi import burst2
from nagi.burst2 import _api

FROZEN = Path(burst2.__file__).parent / "frozen"


def test_frozen_search_config_file_is_the_released_one():
    raw = (FROZEN / "runtime_search_config_v1b.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _api.FROZEN_CONFIG_SHA256


def test_defaults_equal_the_frozen_candidate():
    cfg = json.loads((FROZEN / "runtime_search_config_v1b.json").read_text())
    cand = json.loads((FROZEN / "candidate_search.json").read_text())
    assert cand["sha256"] == _api.FROZEN_CONFIG_SHA256
    pol = cand["candidate_policy"]                       # e.g. G100000b1b = core-gated search, S* sims, belief v1b
    assert pol == f"G{burst2.S_STAR}b1b"
    assert burst2.S_STAR == cfg["zoo"]["max_sims"]
    assert burst2.K_MAX == cfg["zoo"]["k_max"] and burst2.BELIEF == cfg["zoo"]["belief"] == "v1b"
    assert burst2.TAU == cand["tau"] == 0.6
    assert cfg["zoo"]["core_value"] is False and cfg["zoo"]["deterministic"] is True
    assert burst2.FROZEN_DEFAULTS == {"max_sims": burst2.S_STAR, "k_max": burst2.K_MAX, "belief": "v1b",
                                      "tau": 0.6, "deterministic": True, "core_value": False}
    assert burst2.SNAKE_POLICY in ("sdk_pack", "core_head")


def test_unpinned_build_refuses_to_download():
    if burst2.BURST_V2_REVISION is not None:
        pytest.skip("revision pinned")
    with pytest.raises(RuntimeError):
        burst2.load_core()


def test_importing_burst2_is_numpy_only():
    code = "import sys; import nagi.burst2; print(sorted(m for m in ('torch', 'transformers', 'scipy') if m in sys.modules))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "[]", out
