"""Chunked dataset store (bv2n lane gamedata): one chunk = a contiguous index range of one collector / DAgger round,
written by bv2n.data.collect.write_dataset (+ validate) with a feature cache. Training sets are unions of chunks,
deduplicated by request sha256 (first occurrence wins, chunks in the listed order).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from nagi.burst2._rt.bv2n.data import collect as CO
from nagi.burst2._rt.bv2n.data import validate as VA

ROOT = Path.home() / "nagi/runs/bv2n/gamedata"


def chunk_name(behaviour: str, rnd: int, offset: int, n: int) -> str:
    return f"{behaviour.replace(':', '')}_r{rnd}_{offset:05d}_{n}"


def collect_chunk(game: str, behaviour: str, offset: int, n: int, rnd: int = 0, student=None, log=None) -> dict:
    d = ROOT / game
    name = chunk_name(behaviour, rnd, offset, n)
    if (d / f"{name}.validate.json").exists():
        return json.loads((d / f"{name}.manifest.json").read_text())
    rows, eps = CO.collect(game, behaviour, n, rnd, student, offset=offset, log=log)
    man = CO.write_dataset(d, name, rows, eps, {"game": game, "behaviour": behaviour, "round": rnd, "offset": offset,
                                                 "n_episodes": n, "student": getattr(student, "tag", None)})
    v = VA.validate(str(d), name, sample=100)
    if not v["pass"]:
        raise RuntimeError(f"validator FAIL {name}: {v['errors'][:3]}")
    featurize_chunk(game, name, rows)
    return man


def featurize_chunk(game: str, name: str, rows=None):
    from nagi.burst2._rt.bv2n.student import model as M
    p = ROOT / game / f"{name}.feat.npz"
    if p.exists():
        return
    rows = rows if rows is not None else CO.read_jsonl_gz(ROOT / game / f"{name}.rows.jsonl.gz")
    rows, _ = CO.dedup(rows)
    X, Y = M.featurize(game, rows)
    np.savez_compressed(p, X=X, Y=Y, sha=np.asarray([r["text_sha256"] for r in rows]),
                        ep=np.asarray([r["index"] for r in rows]))


def load(game: str, names: list[str], max_rows: int | None = None) -> tuple[np.ndarray, np.ndarray, int]:
    """Union of chunks, dedup by sha; optional prefix of max_rows (in chunk/row order). Returns X, Y, dup_dropped."""
    Xs, Ys, seen, dropped = [], [], set(), 0
    for nm in names:
        z = np.load(ROOT / game / f"{nm}.feat.npz")
        keep = []
        for i, s in enumerate(z["sha"]):
            if s in seen:
                dropped += 1
                continue
            seen.add(s)
            keep.append(i)
        Xs.append(z["X"][keep])
        Ys.append(z["Y"][keep])
    X, Y = np.concatenate(Xs), np.concatenate(Ys)
    if max_rows is not None:
        X, Y = X[:max_rows], Y[:max_rows]
    return X, Y, dropped


def manifest(game: str, name: str) -> dict:
    return json.loads((ROOT / game / f"{name}.manifest.json").read_text())
