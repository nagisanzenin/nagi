"""Re-run the rule-language doc examples (DSL_REFERENCE.md, QUICKSTART_MACHINE.md) against the PUBLIC nagi.burst2.

    PYTHONPATH=src python scripts/burst2_doc_check.py --receipt tests/fixtures/burst2_dsl_examples_receipt.json \
        --model model.npz [--docs docs/MZ1_LANGUAGE.md ...]

The receipt is the research repo's ``docs/burst_v2_general/release/dsl_examples_receipt.json`` (written by its
``scripts/v2g/dsl_doc_check.py --write-receipt`` with the research runtime). This script repeats every step with the
public API only (``read_rules``, ``operate``, ``operate_structured``, the frozen defaults) and requires identical
results: exact strict read + byte round trip + machine id, the first decision (choice and probabilities, text path ==
structured path), the seeded episode (outcome, ticks, return, first 4 ticks), and the quickstart (strict reader rejects
the loose text, canonical text, first decision, 10 seeded episodes). With --docs, every ``<!-- example: id -->``
fenced block must equal the receipt text byte for byte (same rule as the research checker).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

KEYS = {"opus:lander_soft_touchdown": "lander", "opus:ship_berth_tide": "berth", "c:courier_stream_gap": "courier"}


def user_state(m, view) -> dict:
    from nagi.burst2._rt.v2g import operate as OP

    if view["kind"] == "mz-1":
        return dict(view["vars"])
    names = [m.var_names[c] for c in m.disp_cols]
    obs = [None if o is None else dict(zip(names, o)) for o in view["obs"]]
    dec = [None if j is None else OP._answer_of_joint(m, j) for j in view["dec"]]
    return {"obs": obs, "dec": dec}


def check(receipt: dict, core) -> list[str]:
    import numpy as np

    from nagi import burst2

    bad = []
    for ex in receipt["examples"]:
        key, text = KEYS[ex["family"]], ex["text"]
        m = burst2.read_rules(text)
        if m.rules_text() != text or m.machine_id != ex["machine_id"]:
            bad.append(f"{key}: exact read / machine id")
            continue
        ep = m.episode(np.random.default_rng(7))
        v0 = ep.view()
        st0 = user_state(m, v0)
        o = {"core": core, "session": f"doc-{key}", "step": 0}
        first = burst2.operate(text, st0, o)
        struct = burst2.operate_structured(m.spec, v0, o)
        if first["joint_probabilities"] != struct["joint_probabilities"] or first["joint"] != struct["joint"]:
            bad.append(f"{key}: text path != structured path")
        if st0 != ex["first_state"] or first["choice"] != ex["first_choice"] or \
                first["probabilities"] != ex["first_probabilities"]:
            bad.append(f"{key}: first decision differs from the research receipt")
        env, t, trace = np.random.default_rng(11), 0, []
        while not ep.done and t < 100:
            st = user_state(m, ep.view())
            out = burst2.operate(text, st, {"core": core, "session": f"doc-{key}", "step": t})
            if t < 4:
                trace.append({"t": t, "state": st, "choice": out["choice"]})
            ep.step(out["joint"], env)
            t += 1
        e = ex["episode"]
        if (ep.outcome, t, ep.ret, trace) != (e["outcome"], e["ticks"], e["return"], e["first_ticks"]):
            bad.append(f"{key}: episode differs ({ep.outcome}, {t}, {ep.ret}) vs ({e['outcome']}, {e['ticks']}, "
                       f"{e['return']})")
    q = receipt["quickstart"]
    try:
        burst2.read_rules(q["loose_text"])
        rejects = False
    except burst2.ReaderError:
        rejects = True
    canon = burst2.read_rules(q["loose_text"], strict=False).rules_text()
    if rejects != q["strict_rejects_loose"] or canon != q["canonical_text"]:
        bad.append("quickstart: strict reject / canonical text")
    m = burst2.read_rules(canon)
    out = burst2.operate(canon, {"level": 2, "valve": 0}, {"core": core, "session": "quickstart", "step": 0})
    if out["choice"] != q["first_choice"] or out["probabilities"] != q["first_probabilities"]:
        bad.append("quickstart: first decision")
    wins, ticks = 0, []
    for e in range(10):
        ep = m.episode(np.random.default_rng(100 + e))
        env = np.random.default_rng(200 + e)
        t = 0
        while not ep.done and t < 100:
            o = burst2.operate(canon, dict(ep.view()["vars"]), {"core": core, "session": f"quick-{e}", "step": t})
            ep.step(o["joint"], env)
            t += 1
        wins += ep.outcome == "success"
        ticks.append(t)
    if {"n": 10, "success": wins, "ticks": ticks} != q["episodes"]:
        bad.append(f"quickstart: episodes {wins}/10 {ticks} vs {q['episodes']}")
    return bad


def check_docs(receipt: dict, docs: list[Path]) -> list[str]:
    texts = {e["machine_id"]: e["text"] for e in receipt["examples"]}
    texts["quickstart-canonical"] = receipt["quickstart"]["canonical_text"]
    texts["quickstart-loose"] = receipt["quickstart"]["loose_text"]
    bad = []
    for doc in docs:
        for m in re.finditer(r"<!-- example: (\S+) -->\n```text\n(.*?)```", doc.read_text(), re.S):
            if texts.get(m.group(1)) != m.group(2):
                bad.append(f"{doc.name}: block {m.group(1)} != receipt text")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--receipt", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--docs", nargs="*", default=[])
    a = ap.parse_args(argv)
    from nagi import burst2

    receipt = json.loads(Path(a.receipt).read_text())
    bad = check(receipt, burst2.load_core(a.model)) + check_docs(receipt, [Path(d) for d in a.docs])
    print(json.dumps({"ok": not bad, "problems": bad}, indent=1))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
