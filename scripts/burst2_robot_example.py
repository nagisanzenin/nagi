"""The delivery-robot example in docs/QUICKSTART_MACHINE.md §6 ("Example: your own game"): run it, write its receipt,
and check the doc against the receipt.

    PYTHONPATH=src python scripts/burst2_robot_example.py write  --model model.npz   # run + receipt + doc trace table
    PYTHONPATH=src python scripts/burst2_robot_example.py rerun  --model model.npz   # run again, compare to the receipt
    PYTHONPATH=src python scripts/burst2_robot_example.py check                      # doc == receipt (no core needed)

`write` / `rerun` execute the documented code itself: the rules block, the user's game class and the loop are taken
from the doc and run with ``exec``. Only two things are swapped in: ``open("robot.txt")`` returns the rules block, and
``load_core()`` loads ``--model`` through the public ``load_core(path)`` (which refuses any file whose sha256 is not
CORE_SHA256) instead of downloading the same file from Hugging Face. ``operate`` is wrapped only to record each call.
Every tick is also stepped on the canonical machine parsed from the rules, so the user's class must agree with the
rules exactly. The unwinnable variant is the same rules without the charger rule; breadth-first search over the
canonical machine proves that no reachable state is a goal, and the loop is run on it for the same session.

`check` needs no core: the doc's rules / class / loop blocks must hash to the receipt, the trace table must equal the
table rendered from the receipt, every ``<!-- check: robot.KEY = VALUE -->`` must equal the receipt value and follow
the same number in the text, and the core-free facts (canonical text, machine id, reachable states, goal
reachability) are re-derived from the public reader.
"""

from __future__ import annotations

import argparse
import builtins
import contextlib
import hashlib
import io
import json
import math
import re
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "QUICKSTART_MACHINE.md"
RECEIPT = ROOT / "bench" / "burst_v2" / "receipts" / "robot_example.json"
SESSION = "robot-1"
CHARGER_RULE = re.compile(r"^  \d+\. if all\(x == 2, y == 2\): battery := battery \+ 4\n", re.M)
UNWINNABLE_TICKS = 20
TABLE = re.compile(r"(<!-- robot-trace:begin -->\n)(.*?)(<!-- robot-trace:end -->)", re.S)
CHECK = re.compile(r"(\S+) <!-- check: (robot\.[a-z_.]+) = (.+?) -->")


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def blocks(doc: str) -> dict:
    out = {}
    for name, lang in (("rules", "text"), ("game", "python"), ("loop", "python")):
        m = re.search(rf"<!-- robot-example: {name} -->\n```{lang}\n(.*?)```", doc, re.S)
        if not m:
            raise SystemExit(f"doc: block robot-example:{name} not found")
        out[name] = m.group(1)
    return out


def reach(m) -> tuple[bool, int]:
    """Exact BFS over the canonical machine from its start set: (a goal is reachable, number of running states)."""
    starts = sorted({m.initial(i) for i in range(64)})
    seen, q, win = set(starts), deque(starts), False
    while q:
        s = q.popleft()
        for j in m.legal(s):
            n, term, ok = m.step(s, j, u=0.5)  # no random input: u is unused
            if term:
                win |= bool(ok)
            elif n not in seen:
                seen.add(n)
                q.append(n)
    return win, len(seen)


def no_goal_value(depth: int) -> float:
    """Q of surviving `depth` ticks without reaching the goal: -sum_{i<depth} gamma^i (search.py rewards, gamma)."""
    from nagi.burst2._rt.v2g import search as S

    return S.R_RUN * (1 - S.GAMMA ** depth) / (1 - S.GAMMA)


def tick_stats(out: dict) -> dict:
    s = out["stats"]
    return {"n_tied": s["n_acc"], "best_value": round(max(s["qbar"]), 4), "depth": s["depth"],
            "visited": s["visited"], "exhausted": s["exhausted"], "gated": s["gated"]}


def run(model: str, doc: str) -> dict:
    import nagi.burst2 as B
    from nagi.burst2 import _api

    blk = blocks(doc)
    real_load, real_operate, calls = B.load_core, B.operate, []

    def load_core_local(*a, **k):
        assert not a and not k, "the documented loop calls load_core() with no arguments"
        return real_load(model)  # sha256-checked against CORE_SHA256

    def operate_recorded(rules, state, options=None):
        out = real_operate(rules, state, options)
        calls.append((rules, json.loads(json.dumps(state)), dict(options or {}), out))
        return out

    def open_rules(path, *a, **k):
        assert path == "robot.txt", path
        return io.StringIO(blk["rules"])

    ns, buf = {"__name__": "robot_example", "open": open_rules, "__builtins__": builtins}, io.StringIO()
    B.load_core, B.operate = load_core_local, operate_recorded
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(blk["game"], "doc:robot-example:game", "exec"), ns)
            exec(compile(blk["loop"], "doc:robot-example:loop", "exec"), ns)
    finally:
        B.load_core, B.operate = real_load, real_operate
    printed = buf.getvalue().splitlines()

    rules = ns["rules"]
    m = B.read_rules(rules)  # strict: the canonical text the loop used
    s = m.initial(0)
    trace, result = [], None
    for t, (r, state, opts, out) in enumerate(calls):
        assert r == rules and opts == {"core": ns["core"], "session": SESSION, "step": t}
        assert dict(zip(m.var_names, s)) == state, f"t={t}: the user's game state != the canonical machine state"
        s, term, ok = m.step(s, out["joint"], u=0.5)
        trace.append({"t": t, "state": state, "choice": out["choice"], **tick_stats(out)})
        if term:
            result = "goal" if ok else "crash"
    final = ns["game"].state()
    assert final == dict(zip(m.var_names, s)), "final state differs from the canonical machine"
    assert printed[-1] == f"{result} after {len(calls)} ticks", printed[-1]

    # the unwinnable variant: the same rules without the charger rule (strictly canonical as written)
    vtext = CHARGER_RULE.sub("", rules, count=1)
    assert vtext != rules
    vm = B.read_rules(vtext)
    vs, vtrace, vresult = vm.initial(0), [], None
    for t in range(UNWINNABLE_TICKS):
        out = real_operate(vtext, dict(zip(vm.var_names, vs)), {"core": ns["core"], "session": SESSION, "step": t})
        vtrace.append({"t": t, "state": dict(zip(vm.var_names, vs)), "choice": out["choice"], **tick_stats(out)})
        vs, term, ok = vm.step(vs, out["joint"], u=0.5)
        if term:
            vresult = "goal" if ok else "crash"
            break

    core_sha = _api._sha256(Path(model))
    assert core_sha == _api.CORE_SHA256
    base_win, base_states = reach(m)
    v_win, v_states = reach(vm)
    rec = {
        "schema": "nagi-burst2-robot-example-v1",
        "generated_by": "scripts/burst2_robot_example.py",
        "doc": "docs/QUICKSTART_MACHINE.md §6 Example: your own game",
        "sdk_version": _sdk_version(),
        "core_sha256": core_sha,
        "session": SESSION,
        "doc_blocks_sha256": {k: sha(v) for k, v in blk.items()},
        "rules_text": blk["rules"],
        "canonical_text": rules,
        "canonical_sha256": sha(rules),
        "strict_accepts_doc_text": _strict_ok(blk["rules"]),
        "machine_id": m.machine_id,
        "reachable_states": base_states,
        "goal_reachable": base_win,
        "trace": trace,
        "final_state": final,
        "result": result,
        "printed_last": printed[-1],
        "unwinnable": {
            "change": "the charger rule removed",
            "canonical_text": vtext,
            "machine_id": vm.machine_id,
            "reachable_states": v_states,
            "goal_reachable": v_win,
            "ticks_run": len(vtrace),
            "result": vresult or "running",
            "trace": vtrace,
        },
    }
    rec["values"] = values(rec)
    return rec


def _sdk_version() -> str:
    return re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)


def _strict_ok(text: str) -> bool:
    from nagi import burst2

    try:
        burst2.read_rules(text)
        return True
    except burst2.ReaderError:
        return False


def moved(a: dict, b: dict, choice: dict) -> list[str]:
    """Controls whose move was absorbed by the grid edge (choice not keep, coordinate unchanged)."""
    return [c for c, v in (("dx", "x"), ("dy", "y")) if choice[c] != "keep" and a[v] == b[v]]


def values(rec: dict) -> dict:
    """The numbers the doc and the site quote, derived from the trace (never typed)."""
    tr, u = rec["trace"], rec["unwinnable"]
    states = [r["state"] for r in tr] + [rec["final_state"]]
    wall = [r["t"] for r in tr if moved(states[r["t"]], states[r["t"] + 1], r["choice"])]
    wait = [r["t"] for r in tr if (r["state"]["x"], r["state"]["y"]) == (2, 2)
            and r["choice"] == {"dx": "keep", "dy": "keep"}]
    vstates = [r["state"] for r in u["trace"]]
    still = next(r["t"] for r in u["trace"] if all(x["choice"] == {"dx": "keep", "dy": "keep"} for x in u["trace"][r["t"]:]))
    ng = [no_goal_value(r["depth"]) for r in u["trace"]]
    assert all(abs(r["best_value"] - v) < 1e-3 for r, v in zip(u["trace"], ng)), "unwinnable: best value != no-goal value"
    assert all(r["best_value"] > no_goal_value(r["depth"]) for r in tr), "winnable trace: best value not above no-goal value"
    assert not u["goal_reachable"] and u["result"] == "running"
    v = {
        "robot.goal_ticks": len(tr),
        "robot.result": rec["result"],
        "robot.wall_tick": wall[0],
        "robot.wall_tied": tr[wall[0]]["n_tied"],
        "robot.wait_tick": wait[0],
        "robot.wait_count": len(wait),
        "robot.wait_tied": tr[wait[0]]["n_tied"],
        "robot.wait_battery_before": states[wait[0]]["battery"],
        "robot.wait_battery_after": states[wait[0] + 1]["battery"],
        "robot.final_battery": rec["final_state"]["battery"],
        "robot.reachable_states": rec["reachable_states"],
        "robot.best_value_min": round(min(r["best_value"] for r in tr), 1),
        "robot.best_value_max": round(max(r["best_value"] for r in tr), 1),
        "robot.unwinnable.reachable_states": u["reachable_states"],
        "robot.unwinnable.first_tied": u["trace"][0]["n_tied"],
        "robot.unwinnable.best_value": round(u["trace"][0]["best_value"], 1),
        "robot.unwinnable.depth": u["trace"][0]["depth"],
        "robot.unwinnable.still_from": still,
        "robot.unwinnable.still_battery": vstates[still]["battery"],
        "robot.unwinnable.ticks_run": u["ticks_run"],
    }
    return v


def fmt(x) -> str:
    if isinstance(x, float):
        return f"{x:.1f}".replace("-", "−")
    return str(x)


def table(rec: dict) -> str:
    v, tr = rec["values"], rec["trace"]
    states = [r["state"] for r in tr] + [rec["final_state"]]
    rows = ["| t | x, y | battery | parcel | choice dx / dy | moves tied for best | note |",
            "|---|---|---|---|---|---|---|"]
    for r in tr:
        s, n, c = r["state"], states[r["t"] + 1], r["choice"]
        note = []
        if moved(s, n, c):
            note.append(f"steps into the wall ({' and '.join(moved(s, n, c))} has no effect)")
        if n["parcel"] > s["parcel"]:
            note.append("picks up the parcel")
        if (s["x"], s["y"]) == (2, 2) and c == {"dx": "keep", "dy": "keep"}:
            note.append(f"waits on the charger: battery {s['battery']} → {n['battery']}")
        rows.append(f"| {r['t']} | {s['x']}, {s['y']} | {s['battery']} | {s['parcel']} | {c['dx']} / {c['dy']} | "
                    f"{r['n_tied']} | {'; '.join(note)} |")
    f = rec["final_state"]
    rows.append(f"| {len(tr)} | {f['x']}, {f['y']} | {f['battery']} | {f['parcel']} | | | **{rec['result']}** after "
                f"{len(tr)} ticks |")
    return "\n".join(rows) + "\n"


def check_doc(rec: dict, doc: str) -> list[str]:
    from nagi import burst2

    bad = []
    blk = blocks(doc)
    for k, h in rec["doc_blocks_sha256"].items():
        if sha(blk[k]) != h:
            bad.append(f"doc block robot-example:{k} differs from the receipt (re-run `write`)")
    if blk["rules"] != rec["rules_text"]:
        bad.append("rules block != receipt rules_text")
    canon = burst2.read_rules(blk["rules"], strict=False).rules_text()
    m = burst2.read_rules(canon)
    if canon != rec["canonical_text"] or m.machine_id != rec["machine_id"]:
        bad.append("canonical text / machine id differ from the receipt")
    if (reach(m) != (rec["goal_reachable"], rec["reachable_states"])):
        bad.append("reachability of the example differs from the receipt")
    vm = burst2.read_rules(CHARGER_RULE.sub("", canon, count=1))
    u = rec["unwinnable"]
    if vm.rules_text() != u["canonical_text"] or vm.machine_id != u["machine_id"] or \
            reach(vm) != (u["goal_reachable"], u["reachable_states"]):
        bad.append("unwinnable variant differs from the receipt")
    if values(rec) != rec["values"]:
        bad.append("receipt values are not the values derived from its trace")
    mt = TABLE.search(doc)
    if not mt or mt.group(2) != table(rec):
        bad.append("trace table != the table rendered from the receipt (re-run `write`)")
    seen = set()
    for m_ in CHECK.finditer(doc):
        before, key, val = m_.group(1), m_.group(2), m_.group(3)
        seen.add(key)
        want = rec["values"].get(key)
        if want is None:
            bad.append(f"check {key}: not in the receipt")
            continue
        if json.loads(val) != want:
            bad.append(f"check {key}: doc says {val}, receipt says {want}")
        if not before.rstrip(".,;:)*`").endswith(fmt(want)):
            bad.append(f"check {key}: the text before the comment ({before!r}) does not show {fmt(want)}")
    if len(seen) < 8:
        bad.append(f"only {len(seen)} robot checks found in the doc")
    sdk = _sdk_version()
    from nagi.burst2 import _api
    if rec["core_sha256"] != _api.CORE_SHA256 or rec["sdk_version"] != sdk:
        bad.append("receipt core sha / SDK version differ from the package")
    return bad


def rerun_diff(rec: dict, new: dict) -> list[str]:
    bad = []
    for k in ("canonical_text", "machine_id", "result", "final_state", "printed_last", "values", "core_sha256"):
        if rec[k] != new[k]:
            bad.append(f"rerun: {k} differs")
    strip = lambda tr: [(r["t"], r["state"], r["choice"], r["n_tied"], r["depth"], r["visited"]) for r in tr]
    if strip(rec["trace"]) != strip(new["trace"]):
        bad.append("rerun: trace differs")
    if strip(rec["unwinnable"]["trace"]) != strip(new["unwinnable"]["trace"]):
        bad.append("rerun: unwinnable trace differs")
    for a, b in zip(rec["trace"] + rec["unwinnable"]["trace"], new["trace"] + new["unwinnable"]["trace"]):
        if abs(a["best_value"] - b["best_value"]) > 1e-3:
            bad.append(f"rerun: best value at t={a['t']} differs")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=["write", "rerun", "check"])
    ap.add_argument("--model")
    a = ap.parse_args(argv)
    doc = DOC.read_text()
    if a.mode == "check":
        bad = check_doc(json.loads(RECEIPT.read_text()), doc)
    else:
        if not a.model:
            ap.error("--model is required")
        rec = run(a.model, doc)
        if a.mode == "write":
            RECEIPT.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n")
            DOC.write_text(TABLE.sub(lambda m: m.group(1) + table(rec) + m.group(3), doc, count=1))
            bad = check_doc(rec, DOC.read_text())
        else:
            bad = rerun_diff(json.loads(RECEIPT.read_text()), rec)
    print(json.dumps({"ok": not bad, "problems": bad}, indent=1))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
