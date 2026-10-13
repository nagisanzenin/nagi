#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Closed-loop episodes on Machine Zoo tasks with common random numbers (the Zoo-Unseen-D evaluation protocol).

    python3 run_episodes.py --tasks tasks.parquet --policy oracle --arm oracle --out rows.csv
    python3 run_episodes.py --tasks d_tasks.jsonl --policy my_module:my_policy --arm mine --out rows.csv

Environment (identical to the research evaluation that produced results/zoo_d/rows.csv):
- simulator: ``nagi.burst2._rt.v2g.machine.Machine(spec)`` and its ``Episode`` (vendored research code, import
  paths rewritten only); the task's machine_id must equal the simulator's;
- for machine m and episode e = 0..E-1 (E = 16), three PCG64 streams seeded from
  sha256(salt|machine_id|e|stream) (first 128 bits, little endian), stream in {reset, env, policy}: ``reset`` draws
  the start state (one ``integers`` call), ``env`` draws one ``random()`` per tick, ``policy`` is handed to the
  policy for its own draws, so every policy sees the same starts and the same disturbance sequence;
- at most 100 ticks; success = the episode ends in the goal; crash and timeout are failures;
- crn_key = sha256(salt|machine_id|e) hex; the salt comes from the task (Zoo-Unseen-D: "v2g-eval-zud-v0").

A policy is ``policy(d) -> joint`` (an int in d.legal; joint = 9*o0 + 3*o1 + o2 with option 0 = DEC, 1 = KEEP,
2 = INC per control slot), where ``d`` has: ``request`` (the served request text, computed on first access),
``view`` (the client view: mz-1 {"state", "vars"}; mz-1x {"obs", "dec"}), ``machine``, ``legal``, ``rng`` (the
episode's policy stream), ``episode``, ``t``, ``task``. Nagi Burst V2 as a policy (needs the downloaded core):

    from nagi.burst2 import load_core, operate
    CORE = load_core()
    def policy(d):
        return int(operate(d.request, None, {"core": CORE, "rng": d.rng})["joint"])

An exception in the policy (or an illegal joint) marks the episode INVALID (valid = False), which the scorer
(score.py) treats as invalid for every arm of that machine; more than 3% invalid machines invalidates the run.
Built-in policies: oracle (lowest-index acceptable joint of the exact teacher: A(z) when fully observed, I(view)
with hidden vars), keep (joint 13), random (uniform legal joint, one ``integers`` call on the policy stream).
Output: rows.csv with arm, policy, family, domain, machine, episode, crn_key, success, valid, outcome, steps, error.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib
import json
import os
import sys
import time

TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TOOL not in sys.path:
    sys.path.insert(0, TOOL)

import numpy as np  # noqa: E402

from famgate import _runtime  # noqa: E402,F401  (engine on the path)
from nagi.burst2._rt.bv2n.zoo_new import xdsl  # noqa: E402
from nagi.burst2._rt.bv2n.zoo_new.xteacher import XTeacher, XView  # noqa: E402
from nagi.burst2._rt.v2g.machine import Machine  # noqa: E402

CAP = 100
E_DEFAULT = 16
KEEP_JOINT = 13
STREAMS = ("reset", "env", "policy")
ROW_FIELDS = ["arm", "policy", "family", "domain", "machine", "episode", "crn_key", "success", "valid", "outcome",
              "steps", "error"]


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def stream_rng(*parts) -> np.random.Generator:
    """PCG64 Generator seeded from sha256('|'.join(parts)) (first 128 bits, little endian)."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return np.random.Generator(np.random.PCG64(int.from_bytes(digest[:16], "little")))


def episode_rngs(salt: str, machine_id: str, e: int) -> dict:
    return {s: stream_rng(salt, machine_id, e, s) for s in STREAMS}


# ------------------------------------------------------------------------------------------------ tasks
def load_tasks(path: str) -> list[dict]:
    """tasks.parquet (family_id, domain, machine_id, salt, program_json) or *.jsonl (family, cluster, machine_id,
    spec, salt) -> [{family, domain, machine_id, salt, spec}]."""
    out = []
    if path.endswith(".parquet"):
        import pyarrow.parquet as pq  # noqa: PLC0415

        for r in pq.read_table(path).to_pylist():
            out.append({"family": r["family_id"], "domain": r["domain"], "machine_id": r["machine_id"],
                        "salt": r["salt"], "spec": json.loads(r["program_json"])})
    else:
        op = gzip.open if path.endswith(".gz") else open
        with op(path, "rt") as f:
            for ln in f:
                if ln.strip():
                    r = json.loads(ln)
                    out.append({"family": r["family"], "domain": r.get("cluster", r.get("domain")),
                                "machine_id": r["machine_id"], "salt": r["salt"], "spec": r["spec"]})
    return out


# ------------------------------------------------------------------------------------------------ policies
class Decision:
    """What a policy may use at one decision (module doc)."""

    def __init__(self, machine: Machine, view: dict, rng, episode: int, t: int, task: dict):
        self.machine, self.view, self.rng, self.episode, self.t, self.task = machine, view, rng, episode, t, task
        self.legal = machine.valid
        self._request = None

    @property
    def request(self) -> str:
        if self._request is None:
            self._request = self.machine.request_text(self.view)
        return self._request


_TEACHERS: dict = {}


def _teacher(m: Machine) -> XTeacher:
    if m.machine_id not in _TEACHERS:
        _TEACHERS.clear()  # one machine at a time
        _TEACHERS[m.machine_id] = XTeacher(m.px if m.px is not None else xdsl.make(m.program))
    return _TEACHERS[m.machine_id]


def oracle(d: Decision) -> int:
    T = _teacher(d.machine)
    v = d.view
    xv = XView((tuple(v["state"]),), ()) if v["kind"] == "mz-1" else d.machine.xview(v)
    return int(T.label(xv)["joint"])


def keep(d: Decision) -> int:
    return KEEP_JOINT


def random_policy(d: Decision) -> int:
    return int(d.legal[d.rng.integers(len(d.legal))])


BUILTIN = {"oracle": oracle, "keep": keep, "random": random_policy}


def resolve_policy(name: str):
    if name in BUILTIN:
        return BUILTIN[name]
    mod, _, fn = name.partition(":")
    if not fn:
        raise SystemExit(f"--policy must be one of {sorted(BUILTIN)} or module:callable, got {name!r}")
    return getattr(importlib.import_module(mod), fn)


# ------------------------------------------------------------------------------------------------ episodes
def run_task(task: dict, policy, arm: str, policy_name: str, E: int = E_DEFAULT, log_decisions=None) -> list[dict]:
    m = Machine(task["spec"])
    if m.machine_id != task["machine_id"]:
        raise ValueError(f"machine_id {m.machine_id} != task {task['machine_id']}")
    rows = []
    for e in range(E):
        rg = episode_rngs(task["salt"], m.machine_id, e)
        ep = m.episode(rg["reset"])
        outcome, err, valid = "timeout", "", True
        for t in range(CAP):
            d = Decision(m, ep.view(), rg["policy"], e, t, task)
            try:
                j = int(policy(d))
                if j not in m.valid:
                    raise ValueError(f"illegal joint {j}")
            except Exception as ex:  # noqa: BLE001 - policy failure -> INVALID episode (module doc)
                outcome, err, valid = "invalid", f"{type(ex).__name__}: {ex}"[:200], False
                break
            if log_decisions is not None:
                log_decisions({"arm": arm, "machine": m.machine_id, "episode": e, "t": t, "joint": j})
            _v, _r, done, oc = ep.step(j, rg["env"])
            if done:
                outcome = oc
                break
        rows.append({"arm": arm, "policy": policy_name, "family": task["family"], "domain": task["domain"],
                     "machine": m.machine_id, "episode": e, "crn_key": sha(f"{task['salt']}|{m.machine_id}|{e}"),
                     "success": int(outcome == "success"), "valid": valid, "outcome": outcome, "steps": ep.t,
                     "error": err})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tasks", required=True, help="tasks.parquet or tasks .jsonl")
    ap.add_argument("--policy", required=True, help=f"{'|'.join(sorted(BUILTIN))} or module:callable")
    ap.add_argument("--arm", default=None, help="arm name in rows.csv (default: the policy name)")
    ap.add_argument("--E", type=int, default=E_DEFAULT, help="episodes per machine (the protocol uses 16)")
    ap.add_argument("--machines", default=None, help="comma-separated machine ids (default: all)")
    ap.add_argument("--out", required=True, help="rows.csv")
    ap.add_argument("--decisions", default=None, help="optional decisions .jsonl.gz (arm, machine, episode, t, joint)")
    a = ap.parse_args(argv)
    tasks = load_tasks(a.tasks)
    if a.machines:
        keep_ids = set(a.machines.split(","))
        tasks = [t for t in tasks if t["machine_id"] in keep_ids]
    policy = resolve_policy(a.policy)
    arm = a.arm or a.policy
    fd = gzip.open(a.decisions, "wt") if a.decisions else None
    log = (lambda r: fd.write(json.dumps(r) + "\n")) if fd else None
    t0 = time.time()
    n_succ = n_rows = 0
    with open(a.out, "w", newline="") as fr:
        w = csv.DictWriter(fr, fieldnames=ROW_FIELDS)
        w.writeheader()
        for k, task in enumerate(tasks, 1):
            rows = run_task(task, policy, arm, a.policy, a.E, log)
            for r in rows:
                w.writerow(r)
            n_rows += len(rows)
            n_succ += sum(r["success"] for r in rows)
            fr.flush()
            print(f"{k}/{len(tasks)} {task['machine_id']} success {sum(r['success'] for r in rows)}/{len(rows)} "
                  f"({time.time() - t0:.0f} s)", flush=True)
    if fd:
        fd.close()
    print(f"{len(tasks)} machines, {n_rows} episodes, success {n_succ}/{n_rows} -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
