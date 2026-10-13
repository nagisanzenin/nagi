"""Vendor the Burst V2 runtime into nagi.burst2._rt (deterministic; B-R2 of the V2 release plan).

    python scripts/build_burst2.py --research ~/nagi-wt/v2g-m4 --core <model.npz> --requests DIR --out src/nagi/burst2/_rt

1. TRACE (subprocess, research src first on sys.path): the research ``v2g.operate.operate`` /
   ``operate_structured`` run on recorded DEV requests of every route (Zoo mz-1 / mz-1x with the frozen options,
   Snake SDK pack, Snake / RR / Booster core head) and the module set loaded from the research ``src/`` is recorded,
   with every file opened under the research tree (data files would be listed and refused: none are expected).
2. COPY each traced module file to ``<out>/<package path>`` (package ``nagi`` of the research repo is renamed
   ``nagi_r`` so it never shadows the public ``nagi`` package), and every traced package ``__init__.py``.
3. REWRITE imports of the vendored top-level packages to ``nagi.burst2._rt.<pkg>`` (``from P...``, ``import P...``,
   and string imports ``import_module("P.`` / ``import_module(f"P.``); refuse any other reference to a vendored
   package name that the rewrite cannot prove safe.
4. Write ``<out>/MANIFEST.json``: research commit, per-file source sha256 and vendored sha256, the traced route list.
Training-only modules are never imported by the traced routes, so nothing torch-dependent is vendored (checked: the
trace refuses if torch or scipy got imported).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PKGS = ("v2g", "bv2n", "machine_zoo", "arena", "burst_v2", "rr_teacher_pilot", "nagi")
RENAME = {"nagi": "nagi_r"}
PREFIX = "nagi.burst2._rt"

TRACE = r'''
import gzip, json, sys
RES, CORE, REQDIR, N = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
sys.path.insert(0, RES + "/src")
opened = set()
def hook(ev, args):
    if ev == "open" and args and isinstance(args[0], str) and args[0].startswith(RES):
        opened.add(args[0])
sys.addaudithook(hook)
import numpy as np
from v2g import operate as OP
from v2g.core.multi_core import MultiCore, GamePolicy
core = MultiCore.load(CORE)
def reqs(name):
    p = REQDIR + "/" + name
    out = []
    with gzip.open(p, "rt") as f:
        for i, line in enumerate(f):
            if i >= N:
                break
            out.append(json.loads(line)["request"])
    return out
routes = []
for name in ("dev_t4x/requests.jsonl.gz", "dev_lx/requests.jsonl.gz", "dev_zoo/requests.jsonl.gz"):
    for t in reqs(name):
        OP.operate(t, None, {"max_sims": 100000, "belief": "v1b", "tau": 0.6, "core": core, "session": "trace", "step": 0})
        OP.operate(t, None, {"max_sims": 100000, "tie": "hash"})
    routes.append(name)
from v2g import reader
for game in ("snake", "rr", "booster"):
    for t in reqs(f"dev_arena/requests_{game}.jsonl.gz"):
        if game == "snake":
            OP.operate(t, None, {})
            rd = reader.read(t)
            GamePolicy(core, "snake").act(rd.view)
        else:
            o = OP.operate(t, None, {"core": core})
            rd = reader.read(t)
            OP.operate_structured(game, rd.view, {"core": core})
    routes.append(game)
# structured zoo path
from v2g.machine import Machine
t = reqs("dev_t4x/requests.jsonl.gz")[0]
rd = reader.read(t)
OP.operate_structured(rd.machine.spec, rd.view, {"max_sims": 20000, "tie": "hash"})
bad = [m for m in ("torch", "scipy") if m in sys.modules]
files = sorted({m.__file__ for m in list(sys.modules.values())
                if getattr(m, "__file__", None) and m.__file__.startswith(RES + "/src/")})
print(json.dumps({"files": files, "opened": sorted(opened), "routes": routes, "heavy": bad}))
'''


def rewrite(src: str, path: str) -> str:
    """Single pass per pattern (a rewritten prefix ``nagi.burst2._rt.`` is never matched again)."""
    alt = "|".join(PKGS)
    q = lambda p: f"{PREFIX}.{RENAME.get(p, p)}"  # noqa: E731
    out = re.sub(rf"^(\s*)from ({alt})(?!\.burst2\b)(\.|\s+import\b)",
                 lambda m: f"{m[1]}from {q(m[2])}{m[3]}", src, flags=re.M)
    out = re.sub(rf"^(\s*)import ({alt})((?:\.\w+)*) as (\w+)",
                 lambda m: f"{m[1]}import {q(m[2])}{m[3]} as {m[4]}", out, flags=re.M)
    out = re.sub(rf"^(\s*)import ({alt})\s*$", lambda m: f"{m[1]}from {PREFIX} import {RENAME.get(m[2], m[2])} as {m[2]}",
                 out, flags=re.M)
    out = re.sub(rf"import_module\((f?)([\"'])({alt})\.", lambda m: f"import_module({m[1]}{m[2]}{q(m[3])}.", out)
    left = [ln for ln in out.splitlines() if re.match(rf"^\s*import ({alt})\.\w", ln) and " as " not in ln]
    if left:
        raise SystemExit(f"{path}: unrewritable bare dotted import: {left[:3]}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--research", required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--core", required=True)
    ap.add_argument("--requests", required=True, help="dir with dev_t4x/, dev_lx/, dev_zoo/, dev_arena/ request files")
    ap.add_argument("--n", type=int, default=60, help="requests per file traced")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    res = str(Path(a.research).expanduser().resolve())
    r = subprocess.run([a.python, "-c", TRACE, res, a.core, a.requests, str(a.n)], capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"})
    if r.returncode:
        raise SystemExit(r.stderr[-3000:])
    tr = json.loads(r.stdout.strip().splitlines()[-1])
    if tr["heavy"]:
        raise SystemExit(f"trace imported {tr['heavy']}")
    data = [p for p in tr["opened"] if not p.endswith((".py", ".pyc")) and "/__pycache__/" not in p
            and not p.endswith("model.npz") and "/runs/" not in p]
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    src_root = Path(res) / "src"
    man = {"research_commit": subprocess.run(["git", "-C", res, "rev-parse", "HEAD"], capture_output=True,
                                             text=True).stdout.strip(),
           "routes": tr["routes"], "data_files_opened": data, "files": {}}
    for f in tr["files"]:
        rel = Path(f).relative_to(src_root)
        parts = list(rel.parts)
        parts[0] = RENAME.get(parts[0], parts[0])
        dst = out.joinpath(*parts)
        dst.parent.mkdir(parents=True, exist_ok=True)
        text = Path(f).read_text()
        new = rewrite(text, str(rel))
        dst.write_text(new)
        man["files"][str(Path(*parts))] = {"source": str(rel), "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
                                           "sha256": hashlib.sha256(new.encode()).hexdigest()}
    # every package dir needs an __init__.py (namespace dirs of the research tree get an empty one)
    for d in [p for p in out.rglob("*") if p.is_dir()] + [out]:
        if not (d / "__init__.py").exists():
            (d / "__init__.py").write_text("")
    (out / "MANIFEST.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"files": len(man["files"]), "data_files_opened": data, "routes": tr["routes"]}))


if __name__ == "__main__":
    main()
