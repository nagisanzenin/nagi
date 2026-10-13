"""Golden parity: the vendored nagi.burst2 equals the research runtime on recorded DEV requests (identical joint,
choice and joint-probability vector under the same session / step). Needs the Burst V2 core weights: set
NAGI_BURST2_CORE=<model.npz> (the fixture records the core sha256 it was made with)."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path

import pytest

from nagi import burst2
from nagi.burst2 import _api

FIX = Path(__file__).parent / "fixtures" / "burst2_golden.jsonl.gz"


def _psha(out: dict) -> str:
    probs = json.dumps(sorted((int(k), float(p)) for k, p in out["joint_probabilities"].items()), separators=(",", ":"))
    return hashlib.sha256(probs.encode()).hexdigest()


def _load():
    lines = gzip.open(FIX, "rt").read().splitlines()
    return json.loads(lines[0])["meta"], [json.loads(x) for x in lines[1:]]


@pytest.fixture(scope="module")
def core():
    p = os.environ.get("NAGI_BURST2_CORE")
    if not p:
        pytest.skip("set NAGI_BURST2_CORE=<model.npz> to run the golden parity test")
    meta, _ = _load()
    return burst2.load_core(p, sha256=meta["core_sha256"])


def test_fixture_is_dev_only_and_large_enough():
    meta, rows = _load()
    assert meta["n"] == len(rows) >= 2000
    assert sum(r["route"] == "zoo" for r in rows) >= 2000
    assert {r["route"] for r in rows} == {"zoo", "snake", "rr", "booster"}
    assert all(r["source"].startswith(("dev_t4x/", "dev_lx/", "dev_zoo/", "dev_arena/")) for r in rows)


def test_golden_parity(core, monkeypatch):
    _meta, rows = _load()
    bad = []
    for r in rows:
        if r["route"] == "zoo":
            o = burst2.operate(r["request"], None, {"core": core, "session": "burst2-golden", "step": r["i"]})
        elif r["route"] == "snake":
            o = burst2.operate(r["request"], None, {"core": core})
        else:
            o = burst2.operate(r["request"], None, {"core": core})
        e = r["expect"]
        if (o["joint"], o["choice"], _psha(o)) != (e["joint"], e["choice"], e["probs_sha256"]):
            bad.append(r["i"])
    assert not bad, f"{len(bad)} of {len(rows)} differ, first {bad[:5]}"


def test_snake_core_head_parity(core, monkeypatch):
    _meta, rows = _load()
    monkeypatch.setattr(_api, "SNAKE_POLICY", "core_head")
    snake = [r for r in rows if r["route"] == "snake"]
    assert snake
    for r in snake:
        o = burst2.operate(r["request"], None, {"core": core})
        assert o["choice"] == r["expect"]["core_head_choice"], r["i"]
        assert abs(sum(o["joint_probabilities"].values()) - 1) < 1e-9
