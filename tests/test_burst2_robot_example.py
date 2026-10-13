"""The delivery-robot example (docs/QUICKSTART_MACHINE.md §6) against its receipt
bench/burst_v2/receipts/robot_example.json (written by scripts/burst2_robot_example.py).

(a) always: the doc's rules / game class / loop blocks, trace table and every quoted number equal the receipt, and the
    core-free facts (canonical text, machine ids, reachable states, goal reachability) re-derive from the reader;
(b) with NAGI_BURST2_CORE=<model.npz>: the documented code is run again and must reproduce the receipt, including the
    goal after 9 ticks and the single charger wait at t = 6.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import burst2_robot_example as R  # noqa: E402


def receipt() -> dict:
    return json.loads(R.RECEIPT.read_text())


def test_doc_matches_receipt():
    bad = R.check_doc(receipt(), R.DOC.read_text())
    assert not bad, bad


def test_receipt_story():
    v = receipt()["values"]
    assert (v["robot.result"], v["robot.goal_ticks"]) == ("goal", 9)
    assert (v["robot.wait_tick"], v["robot.wait_count"]) == (6, 1)
    assert (v["robot.wait_battery_before"], v["robot.wait_battery_after"]) == (4, 8)
    assert v["robot.wall_tick"] == 0
    u = receipt()["unwinnable"]
    assert not u["goal_reachable"] and u["result"] == "running"


def test_rerun_reproduces_receipt():
    p = os.environ.get("NAGI_BURST2_CORE")
    if not p:
        pytest.skip("set NAGI_BURST2_CORE=<model.npz>")
    new = R.run(p, R.DOC.read_text())
    assert new["values"]["robot.goal_ticks"] == 9
    assert new["values"]["robot.wait_tick"] == 6
    bad = R.rerun_diff(receipt(), new)
    assert not bad, bad
