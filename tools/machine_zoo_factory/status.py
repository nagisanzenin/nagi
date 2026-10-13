#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Job progress per batch/slot (PASS / FAIL / GAVE_UP / TODO), claims, reviews, and the family manifest.

    python3 status.py --job myjob [--brief] [--manifest [--out FILE]] [--target-families N --target-domains M]

A slot counts as PASS only if REPORTS/<name>.json says pass AND the family file's sha256 still equals the reported
module_sha256 (an edit after PASS needs a re-run). ACCEPTED = PASS + REVIEWS/<name>.json verdict "OK" on the same
module sha256. --manifest writes MANIFEST.json: family, split, domain, strata, module sha256, review verdict, kept
instances with params / machine id / signature / prose sha256 / prose text. Only `accepted: true` entries with split
'train' are meant for training; 'dev' families are your held-back check.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import famgate as fg  # noqa: E402
from famgate import jobkit  # noqa: E402


def reports(P: dict) -> dict:
    out = {}
    if not os.path.isdir(P["REPORTS"]):
        return out
    for fn in sorted(os.listdir(P["REPORTS"])):
        if fn.endswith(".json"):
            try:
                out[fn[:-5]] = jobkit.read_json(os.path.join(P["REPORTS"], fn))
            except Exception:  # noqa: BLE001
                pass
    return out


def review_of(P: dict, name: str, r: dict) -> str | None:
    p = os.path.join(P["REVIEWS"], f"{name}.json")
    if not os.path.exists(p):
        return None
    try:
        v = jobkit.read_json(p)
    except Exception:  # noqa: BLE001
        return None
    return v.get("verdict") if v.get("module_sha256") == r.get("module_sha256") else "STALE"


def live_pass(P: dict, name: str, r: dict) -> bool:
    p = os.path.join(P["FAMILIES"], f"{name}.py")
    return bool(r.get("pass")) and os.path.exists(p) and fg.file_sha256(p) == r.get("module_sha256")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--job", default=".", help="job folder (default: current directory)")
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--manifest", action="store_true")
    ap.add_argument("--out", default=None, help="manifest path (default <job>/MANIFEST.json)")
    ap.add_argument("--target-families", type=int, default=None)
    ap.add_argument("--target-domains", type=int, default=None)
    a = ap.parse_args(argv)
    P = jobkit.paths(a.job)
    batches = jobkit.parse_batches(P["batches"])
    plans, _rot = jobkit.load_plans(a.job)
    reps = reports(P)
    by_slot: dict = {}
    for name, r in reps.items():
        meta = r.get("family_meta") or {}
        key = (meta.get("batch"), meta.get("slot"))
        st = "PASS" if live_pass(P, name, r) else "FAIL"
        if by_slot.get(key, ("", ""))[0] != "PASS":
            by_slot[key] = (st, name)
    tot, acc, strata = Counter(), Counter(), Counter()
    doms = {"train": set(), "dev": set()}
    fams = {"train": 0, "dev": 0}
    rows = []
    for bid, b in batches.items():
        plan = plans[b["plan"]]
        cells = []
        claim = os.path.join(P["CLAIMS"], bid)
        for s in range(1, len(plan) + 1):
            st, name = by_slot.get((bid, s), ("TODO", ""))
            if st != "PASS" and os.path.exists(os.path.join(P["GAVE_UP"], f"{bid}.s{s}.txt")):
                st = "GAVE_UP"
            tot[st] += 1
            if st == "PASS":
                acc[review_of(P, name, reps[name]) or "unreviewed"] += 1
                doms.setdefault(b["split"], set()).add(b["domain_id"])
                fams[b["split"]] = fams.get(b["split"], 0) + 1
                strata.update(reps[name]["family_meta"]["strata"])
            cells.append(f"s{s}:{st}" + (f"({name})" if name and not a.brief else ""))
        age = ""
        if os.path.isdir(claim):
            age = f" CLAIMED {int((time.time() - os.path.getmtime(claim)) / 60)}m"
        rows.append(f"{bid} {b['split']:5s} {b['plan']} {b['domain_id']:28s}{age} " + " ".join(cells))
    if not batches:
        rows.append("(no BATCHES/batches.txt: run make_batches.py first)")
    print("\n".join(rows))
    print(f"\nslots {dict(tot)}; PASS families train {fams.get('train', 0)} in {len(doms.get('train', ()))} domains, "
          f"dev {fams.get('dev', 0)} in {len(doms.get('dev', ()))} domains; strata {dict(strata)}")
    print(f"reviews of PASS families: {dict(acc)} (ACCEPTED = OK)")
    if a.target_families or a.target_domains:
        print(f"targets: train families {fams.get('train', 0)}/{a.target_families or '-'}, "
              f"train domains {len(doms.get('train', ()))}/{a.target_domains or '-'}")
    if a.manifest:
        man = []
        for name, r in sorted(reps.items()):
            if not live_pass(P, name, r):
                continue
            meta = r["family_meta"]
            mod = fg.load_module(os.path.join(P["FAMILIES"], f"{name}.py"))
            kept = []
            for k in r["kept"]:
                txt = mod.prose(dict(k["params"]))
                sha = hashlib.sha256(txt.encode()).hexdigest()
                if sha != k.get("prose_sha256"):
                    raise SystemExit(f"{name}: prose sha mismatch for {k['params']} (re-validate)")
                kept.append(dict(k, prose_text=txt))
            verdict = review_of(P, name, r)
            man.append({"family": name, "split": r.get("split"), "domain_id": meta["domain_id"],
                        "title": meta["title"], "batch": meta["batch"], "slot": meta["slot"],
                        "strata": meta["strata"], "module_path": f"FAMILIES/{name}.py",
                        "module_sha256": r["module_sha256"], "gate_version": r["gate_version"],
                        "review": verdict, "accepted": verdict == "OK", "kept": kept})
        out = {"job": os.path.basename(P["job"]), "n": len(man), "families": man}
        path = a.out or os.path.join(P["job"], "MANIFEST.json")
        jobkit.write_json(path, out)
        print(f"wrote {os.path.relpath(path)} ({len(man)} families)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
