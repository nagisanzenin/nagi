# SPDX-License-Identifier: Apache-2.0
"""Job plumbing for a family job folder: layout, batch list, slot plans, claims, reports, token lists.

A job folder (any directory you choose) looks like this; every sub-folder is created on demand:

    <job>/BATCHES/domains.txt      your domain list (input of make_batches.py)
    <job>/BATCHES/batches.txt      bid | domain_id | split | plan | description (output of make_batches.py)
    <job>/BATCHES/plans.json       optional: your own slot plans (default: DEFAULT_PLANS below)
    <job>/FAMILIES/<name>.py       family files (one per slot)
    <job>/REPORTS/<name>.json      gate reports (written by validate.py)
    <job>/REVIEWS/<name>.json      blind reviews (written by reviewers)
    <job>/CLAIMS/<bid>/OWNER       atomic batch claims (mkdir)
    <job>/GAVE_UP/<bid>.s<k>.txt   slots an author gave up on (reason + last gate summary line)
    <job>/forbidden_tokens.txt     optional: tokens that must not appear in name / title / story / domain
"""

from __future__ import annotations

import json
import os
import time

from . import core as fg

TOOL_DIR = os.path.dirname(fg.HERE)
EXAMPLES_DIR = os.path.join(TOOL_DIR, "examples")

# Slot plans of the research job (frozen 2026-10-12 before any family existed). Each slot lists the strata the family
# MUST declare (and pass by execution); authors may declare more. A/B/C rotate over train batches (6 slots each);
# D is used for dev batches (4 slots). Over A+B+C: delay 6, hidden 6, long 6, interlock 5, multibudget 5, axes3 3.
DEFAULT_PLANS = {
    "A": [["delay", "long"], ["hidden"], ["interlock", "long"], ["axes3"], ["multibudget", "delay"],
          ["hidden", "interlock"]],
    "B": [["hidden", "long"], ["delay"], ["axes3", "multibudget"], ["interlock"], ["delay", "hidden"],
          ["multibudget", "long"]],
    "C": [["interlock", "delay"], ["multibudget"], ["hidden", "axes3"], ["long", "delay"],
          ["interlock", "multibudget"], ["hidden", "long"]],
    "D": [["delay", "hidden"], ["long", "budget"], ["interlock", "delay"], ["hidden", "long"]],
}
DEFAULT_ROTATION = {"train": ["A", "B", "C"], "dev": "D"}


def paths(job: str) -> dict:
    job = os.path.abspath(job)
    return {"job": job, "FAMILIES": os.path.join(job, "FAMILIES"), "REPORTS": os.path.join(job, "REPORTS"),
            "REVIEWS": os.path.join(job, "REVIEWS"), "CLAIMS": os.path.join(job, "CLAIMS"),
            "GAVE_UP": os.path.join(job, "GAVE_UP"), "BATCHES": os.path.join(job, "BATCHES"),
            "batches": os.path.join(job, "BATCHES", "batches.txt"),
            "domains": os.path.join(job, "BATCHES", "domains.txt"),
            "plans": os.path.join(job, "BATCHES", "plans.json"),
            "tokens": os.path.join(job, "forbidden_tokens.txt")}


def find_job(family_path: str) -> str:
    """The job folder of a family file: the parent of its FAMILIES/ folder, else the file's own folder."""
    d = os.path.dirname(os.path.abspath(family_path))
    return os.path.dirname(d) if os.path.basename(d) == "FAMILIES" else d


def load_plans(job: str) -> tuple[dict, dict]:
    """(plans, rotation). BATCHES/plans.json = {"plans": {plan: [[strata], ...]}, "rotation": {"train": [plans],
    "dev": plan}}; both keys optional."""
    p = paths(job)["plans"]
    if not os.path.exists(p):
        return DEFAULT_PLANS, DEFAULT_ROTATION
    with open(p) as f:
        cfg = json.load(f)
    plans = cfg.get("plans", DEFAULT_PLANS)
    for k, slots in plans.items():
        for s in slots:
            bad = [t for t in s if t not in fg.STRATA]
            if bad:
                raise ValueError(f"plans.json plan {k}: unknown strata {bad} (allowed {fg.STRATA})")
    return plans, cfg.get("rotation", DEFAULT_ROTATION)


def parse_batches(path: str) -> dict:
    """'bid | domain_id | split | plan | description' lines -> {bid: {...}} (comments '#')."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path) as f:
        lines = f.read().splitlines()
    for ln in lines:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        parts = [x.strip() for x in ln.split("|")]
        if len(parts) < 4:
            raise ValueError(f"{path}: bad batch line {ln!r} (need bid | domain_id | split | plan | description)")
        out[parts[0]] = {"bid": parts[0], "domain_id": parts[1], "split": parts[2], "plan": parts[3],
                         "desc": parts[4] if len(parts) > 4 else ""}
    return out


def load_tokens(path: str | None) -> list[str]:
    """One token per line ('#' comments, blank lines ignored); matched case-insensitively as substrings."""
    if not path or not os.path.exists(path):
        return []
    with open(path) as f:
        return [t.strip().lower() for t in f.read().splitlines() if t.strip() and not t.lstrip().startswith("#")]


def slot_taken(report_dir: str, batch: str, slot: int, name: str) -> str | None:
    """Name of another PASSED family that already fills (batch, slot), if any."""
    if not os.path.isdir(report_dir):
        return None
    for fn in sorted(os.listdir(report_dir)):
        if not fn.endswith(".json") or fn[:-5] == name:
            continue
        try:
            with open(os.path.join(report_dir, fn)) as f:
                r = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        meta = r.get("family_meta") or {}
        if r.get("pass") and meta.get("batch") == batch and meta.get("slot") == slot:
            return r.get("family")
    return None


def read_json(path: str):
    with open(path) as f:
        return json.load(f)


def write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + f".tmp{os.getpid()}"
    with open(tmp, "w") as f:
        f.write(fg.dumps(obj))
    os.replace(tmp, path)


def stamp(rec: dict) -> dict:
    rec["validated_at"] = time.strftime("%Y-%m-%d %H:%M:%S %z")
    return rec
