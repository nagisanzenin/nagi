#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Family gate CLI. A family counts only on a full-run PASS (with X6).

    OMP_NUM_THREADS=2 python3 validate.py <job>/FAMILIES/<name>.py            # full run (the only PASS that counts)
    OMP_NUM_THREADS=2 python3 validate.py <job>/FAMILIES/<name>.py --no-x6    # draft run (skips the blind checker)

Prints one line per instance, a summary line and `FAMILY PASS <name>` / `FAMILY FAIL <name>`; writes
<job>/REPORTS/<name>.json; exit code 0 on PASS. The job folder is the parent of FAMILIES/ (or --job).

Checks: GATES.md (V0-V7 + P1/P2 on top of the frozen mz-1x gates), plus these job rules:
- with <job>/BATCHES/batches.txt: FAMILY['batch'] is a listed batch, FAMILY['domain_id'] is that batch's domain, the
  slot's required strata (slot plan) are declared, and no other PASSED family fills the same slot;
- no forbidden token (<job>/forbidden_tokens.txt or --forbidden-tokens; default: none) in name/title/story/domain;
- V7 near-duplicate index = the job's own PASSED families + the bundled examples/ + every --index-dir you pass
  (for example the published Machine Zoo families). Nothing else is indexed. A family whose domain_id is the domain
  of a family in an --index-dir fails unless --allow-existing-domains.
"""

from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import famgate as fg  # noqa: E402
from famgate import jobkit  # noqa: E402


def build_index(name: str, family_path: str, job: str, prof: fg.Profile, index_dirs=(), examples: bool = True):
    """(job_entries, external_entries): the V7 index split by origin (the domain rule uses external only)."""
    P = jobkit.paths(job)
    own = fg.job_index(P["FAMILIES"], P["REPORTS"], "job", prof.inst_salt, exclude=name)
    ext = []
    if examples:
        ext += fg.dir_index(jobkit.EXAMPLES_DIR, "example", prof.inst_salt, exclude_paths=[family_path])
    for d in index_dirs:
        sub = os.path.join(d, "FAMILIES")
        if os.path.isdir(sub) and os.path.isdir(os.path.join(d, "REPORTS")):  # another job folder: its PASSED families
            ext += fg.job_index(sub, os.path.join(d, "REPORTS"), f"index:{os.path.basename(os.path.abspath(d))}",
                                prof.inst_salt, exclude=None)
        else:
            ext += fg.dir_index(d, f"index:{os.path.basename(os.path.abspath(d))}", prof.inst_salt,
                                exclude_paths=[family_path])
    own_paths = {os.path.realpath(e["path"]) for e in own}
    ext = [e for e in ext if os.path.realpath(e["path"]) not in own_paths
           and os.path.realpath(e["path"]) != os.path.realpath(family_path)]
    return own, ext


def family_rules_factory(name: str, job: str, tokens: list[str], ext_domains: set[str]):
    P = jobkit.paths(job)
    batches = jobkit.parse_batches(P["batches"])
    plans, _rot = jobkit.load_plans(job)

    def rules(F: dict) -> list[str]:
        errs = []
        if batches:
            b = batches.get(F.get("batch"))
            if b is None:
                return [f"batch {F.get('batch')!r} not in BATCHES/batches.txt"]
            if F["domain_id"] != b["domain_id"]:
                errs.append(f"domain_id {F['domain_id']!r} != batch domain {b['domain_id']!r}")
            plan = plans.get(b["plan"])
            slot = F.get("slot")
            if plan is None:
                errs.append(f"batch {b['bid']}: plan {b['plan']!r} not defined")
            elif not (isinstance(slot, int) and 1 <= slot <= len(plan)):
                errs.append(f"slot must be 1..{len(plan)} (plan {b['plan']})")
            else:
                miss = [s for s in plan[slot - 1] if s not in F["strata"]]
                if miss:
                    errs.append(f"slot {slot} of plan {b['plan']} requires strata {plan[slot - 1]}; missing {miss}")
                other = jobkit.slot_taken(P["REPORTS"], F["batch"], slot, name)
                if other:
                    errs.append(f"slot {F['batch']}/{slot} already filled by PASSED family {other!r}")
        d = F["domain_id"]
        if d in ext_domains:
            errs.append(f"domain {d!r} is already a domain of an indexed family (use a new domain, or "
                        f"--allow-existing-domains)")
        hits = fg.token_hits([F["name"], F["title"], F["story"], d], tokens)
        if hits:
            errs.append(f"forbidden tokens in name/title/story/domain: {hits}")
        return errs

    return rules, batches


def run(path: str, *, x6: bool = True, quiet: bool = False, job: str | None = None, profile: str = "train",
        index_dirs=(), examples: bool = True, tokens_file: str | None = None, allow_existing_domains: bool = False,
        write_report: bool = True) -> dict:
    path = os.path.abspath(path)
    name = os.path.splitext(os.path.basename(path))[0]
    job = os.path.abspath(job) if job else jobkit.find_job(path)
    P = jobkit.paths(job)
    prof = fg.PROFILES[profile]
    tokens = jobkit.load_tokens(tokens_file if tokens_file else P["tokens"])
    own, ext = build_index(name, path, job, prof, index_dirs=index_dirs, examples=examples)
    ext_domains = set() if allow_existing_domains else {e["domain_id"] for e in ext if e.get("domain_id")}
    rules, batches = family_rules_factory(name, job, tokens, ext_domains)
    if not quiet:
        bt = "BATCHES/batches.txt" if batches else "none (batch/slot rules off)"
        print(f"job {os.path.basename(job)}: batches {bt}; V7 index {len(own)} job + {len(ext)} other families; "
              f"forbidden tokens {len(tokens)}", flush=True)
    rec = fg.check_family(path, prof, index=own + ext, family_rules=rules, x6=x6,
                          log=None if quiet else (lambda s: print(s, flush=True)))
    if not x6 and rec.get("pass"):
        rec["failed"], rec["pass"] = rec["failed"] + ["X6:skipped(draft --no-x6)"], False
    meta = rec.get("family_meta") or {}
    b = batches.get(meta.get("batch"), {})
    rec["split"] = b.get("split")
    rec["index_sizes"] = {"job": len(own), "other": len(ext)}
    if write_report:
        jobkit.write_json(os.path.join(P["REPORTS"], f"{name}.json"), jobkit.stamp(rec))
    print(fg.summary_line(rec))
    if rec.get("V7") and not rec["V7"]["pass"]:
        v7 = rec["V7"]
        print(f"V7 near-duplicate: signature hits {v7['sig_hits'] + v7['base_sig_hits']}, name clash "
              f"{v7['name_hit']}, max WL similarity {v7['max_wl_sim']} vs {v7['nearest']} (limit {prof.dup_wl_max}), "
              f"prose twin {v7['max_prose_twin']} vs {v7['prose_twin_nearest']} (limit {prof.prose_twin_max})")
    print(f"FAMILY {'PASS' if rec['pass'] else 'FAIL'} {name} failed={rec['failed']} ({rec.get('wall_s')} s)")
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("family", help="<job>/FAMILIES/<name>.py")
    ap.add_argument("--no-x6", action="store_true", help="skip the blind checker (draft runs only; PASS needs X6)")
    ap.add_argument("--job", default=None, help="job folder (default: the parent of the file's FAMILIES/ folder)")
    ap.add_argument("--profile", default="train", choices=sorted(fg.PROFILES))
    ap.add_argument("--index-dir", action="append", default=[],
                    help="extra V7 index: a folder of family .py files, or another job folder (repeatable)")
    ap.add_argument("--no-example-index", action="store_true", help="do not index the bundled examples/")
    ap.add_argument("--forbidden-tokens", default=None, help="token file (default <job>/forbidden_tokens.txt)")
    ap.add_argument("--allow-existing-domains", action="store_true")
    ap.add_argument("--no-report", action="store_true", help="do not write <job>/REPORTS/<name>.json")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    rec = run(a.family, x6=not a.no_x6, quiet=a.quiet, job=a.job, profile=a.profile, index_dirs=a.index_dir,
              examples=not a.no_example_index, tokens_file=a.forbidden_tokens,
              allow_existing_domains=a.allow_existing_domains, write_report=not a.no_report)
    return 0 if rec["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
