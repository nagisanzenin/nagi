"""nagi.burst2.read_rules (exact reader export) and the rule-language doc examples re-run on the public package
(scripts/burst2_doc_check.py against the research receipt; needs NAGI_BURST2_CORE=<model.npz> for the decisions)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from nagi import burst2

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = Path(__file__).parent / "fixtures" / "burst2_dsl_examples_receipt.json"


def test_read_rules_exact_and_canonicalizing():
    q = json.loads(RECEIPT.read_text())["quickstart"]
    with pytest.raises(burst2.ReaderError):
        burst2.read_rules(q["loose_text"])                      # strict by default: non-canonical text refused
    m = burst2.read_rules(q["loose_text"], strict=False)
    assert m.rules_text() == q["canonical_text"]
    assert burst2.read_rules(q["canonical_text"]).rules_text() == q["canonical_text"]


def test_doc_examples_match_the_research_receipt():
    p = os.environ.get("NAGI_BURST2_CORE")
    if not p:
        pytest.skip("set NAGI_BURST2_CORE=<model.npz>")
    sys.path.insert(0, str(ROOT / "scripts"))
    import burst2_doc_check as D

    bad = D.check(json.loads(RECEIPT.read_text()), burst2.load_core(p))
    assert not bad, bad
