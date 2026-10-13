"""Golden parity fixture for nagi.burst2: the RESEARCH runtime's decisions on recorded DEV requests.

    python scripts/burst2_golden.py --research ~/nagi-wt/v2g-m4 --core M3/model.npz --requests /tmp/v2g/prereg/m4 \
        --out tests/fixtures/burst2_golden.jsonl.gz

Runs in a subprocess with ONLY the research ``src`` on sys.path (the research ``nagi`` package never mixes with the
public one). Per request it records the inputs (request bytes, options) and the research outputs: the joint, the
choice, and sha256 of the joint-probability vector in the M4 interface form (sorted (joint, p) pairs, compact JSON).
Requests: DEV only (T4X, Zoo-Dev-L-X, Zoo dev, Arena dev 48-59; prereg's M4 dry-run receipts); never sealed.
Options (the frozen candidate, research form = m4_zoo_sdk.options_for(G100000b1b, tau 0.6) with session/step draws):
  zoo    {max_sims 100000, belief v1b, tau 0.6, core, session, step}
  snake  {} (the SDK pack); plus the core-head choice (GamePolicy.act) for SNAKE_POLICY = core_head
  rr / booster {core}
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PICK = {"dev_t4x/requests.jsonl.gz": ("zoo", 1000), "dev_lx/requests.jsonl.gz": ("zoo", 600),
        "dev_zoo/requests.jsonl.gz": ("zoo", 400), "dev_arena/requests_snake.jsonl.gz": ("snake", 300),
        "dev_arena/requests_rr.jsonl.gz": ("rr", 300), "dev_arena/requests_booster.jsonl.gz": ("booster", 300)}

RUN = r'''
import gzip, hashlib, json, sys
RES, CORE, REQS = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, RES + "/src")
from v2g import operate as OP, reader
from v2g.core.multi_core import MultiCore, GamePolicy
core = MultiCore.load(CORE)
def psha(out):
    probs = json.dumps(sorted((int(k), float(p)) for k, p in out["joint_probabilities"].items()), separators=(",", ":"))
    return hashlib.sha256(probs.encode()).hexdigest()
for line in open(REQS):
    r = json.loads(line)
    t, route, i = r["request"], r["route"], r["i"]
    if route == "zoo":
        o = OP.operate(t, None, {"max_sims": 100000, "belief": "v1b", "tau": 0.6, "core": core,
                                 "session": "burst2-golden", "step": i})
        extra = {}
    elif route == "snake":
        o = OP.operate(t, None, {})
        extra = {"core_head_choice": GamePolicy(core, "snake").act(reader.read(t).view)}
    else:
        o = OP.operate(t, None, {"core": core})
        rd = reader.read(t)
        os_ = OP.operate_structured(route, rd.view, {"core": core})
        assert psha(os_) == psha(o) and os_["joint"] == o["joint"]
        extra = {}
    print(json.dumps(dict(r, expect={"joint": o["joint"], "choice": o["choice"], "probs_sha256": psha(o), **extra}),
                     sort_keys=True), flush=True)
'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--research", required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--core", required=True)
    ap.add_argument("--requests", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    res = str(Path(a.research).expanduser().resolve())
    rows = []
    for name, (route, n) in PICK.items():
        recs = [json.loads(x) for x in gzip.open(Path(a.requests) / name, "rt")]
        recs = sorted({r["request_sha256"]: r for r in recs}.values(),
                      key=lambda r: hashlib.sha256(("burst2-golden|" + r["request_sha256"]).encode()).hexdigest())[:n]
        rows += [{"route": route, "source": name, "request": r["request"]} for r in recs]
    for i, r in enumerate(rows):
        r["i"] = i
    tmp = Path(a.out).with_suffix(".inputs.jsonl")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows))
    p = subprocess.run([a.python, "-c", RUN, res, a.core, str(tmp)], capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"})
    tmp.unlink()
    if p.returncode:
        raise SystemExit(p.stderr[-3000:])
    out = [json.loads(x) for x in p.stdout.splitlines() if x.startswith("{")]
    assert len(out) == len(rows), (len(out), len(rows))
    core_sha = hashlib.sha256(Path(a.core).read_bytes()).hexdigest()
    commit = subprocess.run(["git", "-C", res, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    head = {"meta": {"research_commit": commit, "core_sha256": core_sha, "n": len(out),
                     "routes": {k: sum(r["route"] == k for r in out) for k in ("zoo", "snake", "rr", "booster")}}}
    body = json.dumps(head, sort_keys=True) + "\n" + "".join(json.dumps(r, sort_keys=True) + "\n" for r in out)
    with open(a.out, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as f:  # byte-reproducible
        f.write(body.encode())
    print(json.dumps(head))


if __name__ == "__main__":
    main()
