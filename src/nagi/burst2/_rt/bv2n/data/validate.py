"""Dataset validator (bv2n lane gamedata). Fail closed. Checks, for a rows file + its episodes file + manifest:

  1. sha256 of both files == the manifest's;
  2. seeds: every row's (stream, index) regenerates its seed (bv2n.seeds._raw), the stream is trainable, the seed is
     not a reserved Arena seed (assert_trainable), the index lies in the collector's / DAgger round's range;
  3. rows: text_sha256 == sha256(text), view == parse(text), targets == one-hot(teacher_joint), unique text_sha256;
  4. labels recomputed on a sample: the episode is replayed from its seed with the recorded applied controls (the
     engine is deterministic; RR is a float engine: same platform), the request text at the row's tick must be
     byte-identical and the teacher's joint recomputed on it must equal the stored one.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from nagi.burst2._rt.burst_v2.seeds import reserved
from nagi.burst2._rt.bv2n import seeds as BS
from nagi.burst2._rt.bv2n.data import collect as CO
from nagi.burst2._rt.bv2n.data import views as VW


def _sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def validate(out_dir: str, name: str, sample: int = 200, key: str = "v1") -> dict:
    d = Path(out_dir)
    man = json.loads((d / f"{name}.manifest.json").read_text())
    errs = []
    if _sha_file(d / f"{name}.rows.jsonl.gz") != man["rows_sha256"]:
        errs.append("rows sha mismatch")
    if _sha_file(d / f"{name}.episodes.jsonl.gz") != man["episodes_sha256"]:
        errs.append("episodes sha mismatch")
    rows = CO.read_jsonl_gz(d / f"{name}.rows.jsonl.gz")
    eps = CO.read_jsonl_gz(d / f"{name}.episodes.jsonl.gz")
    vs = VW.make(man["game"])
    res = reserved(vs.seed_game)
    seen = set()
    for r in rows:
        stream, lo, hi = CO.index_range(r["behaviour"], r["round"])
        if r["stream"] != stream or not lo <= r["index"] < hi:
            errs.append(f"{r['id']}: index {r['index']} outside {stream} [{lo},{hi})")
        if BS._raw(BS.STREAMS[r["stream"]], vs.seed_game, r["index"]) != r["seed"] or r["seed"] in res:
            errs.append(f"{r['id']}: seed does not regenerate or is reserved")
        try:
            BS.assert_trainable(vs.seed_game, r["seed"], r["stream"])
        except ValueError as e:
            errs.append(f"{r['id']}: {e}")
        if VW.sha(r["text"]) != r["text_sha256"] or r["text_sha256"] in seen:
            errs.append(f"{r['id']}: text sha wrong or duplicate")
        seen.add(r["text_sha256"])
        if r["targets"] != {c: [1.0 if o == r["teacher_joint"][c] else 0.0 for o in vs.options[c]] for c in vs.controls}:
            errs.append(f"{r['id']}: targets != one-hot(teacher joint)")
        if len(errs) > 20:
            break
    rng = random.Random(f"bv2n-validate|{name}|{key}")
    samp = rng.sample(rows, min(sample, len(rows)))
    for r in samp:
        if json.loads(json.dumps(vs.parse(r["text"]))) != r["view"]:
            errs.append(f"{r['id']}: view != parse(text)")
    by_ep = {}
    for r in samp:
        by_ep.setdefault((r["stream"], r["index"], r["behaviour"], r["round"]), []).append(r)
    ep_of = {(e["stream"], e["index"], e["behaviour"], e["round"]): e for e in eps}
    n_checked = 0
    for k, rs in by_ep.items():
        ep = ep_of.get(k)
        if ep is None:
            errs.append(f"no episode record for {k}")
            continue
        want = {r["tick"]: r for r in rs}
        s = vs.reset(ep["seed"])
        with vs.ctx():
            for t, acts in enumerate(ep["applied"]):
                text = vs.render(s, acts)            # every boundary: contract view builders track history
                if t in want:
                    r = want[t]
                    if VW.sha(text) != r["text_sha256"]:
                        errs.append(f"{r['id']}: replayed request text differs")
                    elif vs.teacher(s, vs.parse(text), text) != r["teacher_joint"]:
                        errs.append(f"{r['id']}: recomputed teacher label differs")
                    n_checked += 1
                if t >= max(want):
                    break
                s = vs.step(s, acts)
    out = {"name": name, "rows": len(rows), "episodes": len(eps), "labels_recomputed": n_checked,
           "errors": errs[:20], "n_errors": len(errs), "pass": not errs}
    (d / f"{name}.validate.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return out
