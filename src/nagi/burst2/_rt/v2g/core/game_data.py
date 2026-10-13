"""Game rows for the multi-domain arm S core (bring-up source until the data lane's game shards land).

Reads the frozen bv2n chunk files READ-ONLY (data lane OK 2026-10-12 16:06): featurized rows (``<chunk>.feat.npz`` /
``<chunk>.featlf.npz``: X float16, Y per-slot targets, sha = request sha256, ep = episode index) plus the chunk's
episode records for the seed check. Row sets = exactly the training sets of the reference students that the core must
match on student_dev (docs/burst_v2_next/lanes/{snake-student,gamedata,booster-student}.md):
    snake    X0   (snake-student): A3 + DNEW + DAgger r3 + r4, lag features (features.snake_lf_x), 386,491 rows
    rr       A2   (gamedata): T + P + DAgger r1 (chunk list from the frozen model receipt), 33,793 rows
    booster  A2   (booster-student): T + P + DAgger r1 (chunk list from the frozen model receipt), 79,254 rows
Union of chunks, dedup by request sha (first wins) = the reference loaders' rule (row counts are checked).
Every episode is checked fail-closed: seed == sha256-stream seed of (stream, index) (bv2n.seeds) and
``bv2n.seeds.assert_trainable`` (train / dagger streams only, never a reserved Arena seed); every row's episode must be
one of its chunk's checked episodes. Sealed sets (Arena eval seeds, teacher_gate, student_dev) are never read.

Snake storage (RAM: 2688 float16 per row would be 2.1 GB for X0): the 5x23x23 egocentric image is stored exactly as
4 bit-packed binary channels (blocked, food, body, tail) + 1 uint8 code channel (wall-soon; code = index into a fixed
LUT of its float16 values {0, 0.5, float16(1 - d/13)}), the 43 scalars stay float16. ``decode`` reproduces the
float16 matrix bit for bit (checked on every chunk at load, fail closed).
"""

from __future__ import annotations

import gzip
import os
import hashlib
import json
from pathlib import Path

import numpy as np

from nagi.burst2._rt.bv2n import seeds as BS
from nagi.burst2._rt.bv2n.data import store as ST
from nagi.burst2._rt.bv2n.data import views as VW

RUNS = Path.home() / "nagi/runs/bv2n"
GAMES = ("snake", "rr", "booster")
HEADS = {"snake": (4,), "rr": (5, 5, 3), "booster": (4, 5, 4, 2)}
DIMS = {"snake": 2688, "rr": 50, "booster": 160}
REF = {  # reference student per game: (chunk dir, model receipt, expected unique rows)
    "snake": (RUNS / "snake-student/snake", RUNS / "snake-student/snake/models/X0_s0.json", 386491),
    "rr": (RUNS / "gamedata/rr", RUNS / "gamedata/rr/models/A2_s0.json", 33793),
    "booster": (RUNS / "booster-student/booster", RUNS / "booster-student/booster/models/A2_s0.json", 79254),
}
SN_W, SN_C = 23, 5
SN_IMG = SN_C * SN_W * SN_W
SN_BIN = (0, 2, 3, 4)
SN_LUT = np.unique(np.array([0.0, 0.5] + [np.float32(1.0) - np.float32(d) / np.float32(13.0) for d in range(-1, 15)],
                            np.float32).astype(np.float16))


def snake_x0_chunks() -> list[str]:
    """X0's chunk list, resolved exactly as scripts/bv2n/snake_student.py (A3 + DNEW + dagger:3 + dagger:4)."""
    cfg = json.loads((Path(__file__).resolve().parents[3] / "docs/burst_v2_next/lanes/snake_student_prereg.json")
                     .read_text())
    rec = json.loads(REF["snake"][1].read_text())
    if rec["spec"]["sets"] != ["A3", "DNEW", "dagger:3", "dagger:4"] or rec["spec"]["feat"] != "lf":
        raise AssertionError("X0 receipt sets/features changed")

    def cn(beh, rnd, off, n):
        return ST.chunk_name(beh, rnd, off, n)

    def chunks(beh, lo, hi, rnd=0, c=50):
        return [cn(beh, rnd, o, min(c, hi - o)) for o in range(lo, hi, c)]

    a3 = (chunks("teacher", 0, 200) + [cn("eps0.1", 0, 0, 50), cn("eps0.1", 0, 50, 20), cn("script0.05", 0, 0, 50),
          cn("script0.05", 0, 50, 20), cn("dart0.2", 0, 0, 50), cn("dart0.2", 0, 50, 20)]
          + chunks("student", 0, 200, 1) + chunks("student", 0, 200, 2))
    dnew = (chunks("teacher", 200, 1200) + chunks("eps0.1", 70, 270) + chunks("script0.05", 70, 270)
            + chunks("dart0.2", 70, 270))
    dag = [n for r in (3, 4) for n in chunks("student", 0, cfg["dagger_eps"][str(r)], r)]
    return a3 + dnew + dag


def chunk_list(game: str) -> list[str]:
    if game == "snake":
        return snake_x0_chunks()
    return list(json.loads(REF[game][1].read_text())["sets"])


def check_episodes(game: str, d: Path, name: str) -> set:
    """Fail-closed provenance check of one chunk; returns the set of its episode indices."""
    sg = VW.SEED_GAME[game]
    eps = set()
    with gzip.open(d / f"{name}.episodes.jsonl.gz", "rt") as f:
        for line in f:
            e = json.loads(line)
            stream, idx, seed = e["stream"], int(e["index"]), int(e["seed"])
            if BS._raw(BS.STREAMS[stream], sg, idx) != seed:
                raise AssertionError(f"{name}: seed of ({stream}, {idx}) does not regenerate")
            BS.assert_trainable(sg, seed, stream)
            eps.add(idx)
    return eps


def snake_encode(X16: np.ndarray) -> dict:
    img = X16[:, :SN_IMG].reshape(len(X16), SN_C, SN_W * SN_W)
    bins = img[:, SN_BIN]
    if not np.isin(bins, np.array([0, 1], np.float16)).all():
        raise AssertionError("snake binary channel holds a non-binary value")
    ch1 = img[:, 1]
    code = np.searchsorted(SN_LUT, ch1).astype(np.uint8)
    if not (SN_LUT[np.minimum(code, len(SN_LUT) - 1)] == ch1).all():
        raise AssertionError("snake wall-soon value outside the LUT")
    return {"bits": np.packbits(bins.astype(np.uint8), axis=-1), "code": code,
            "tail": np.ascontiguousarray(X16[:, SN_IMG:])}


def pack_code4(code: np.ndarray) -> np.ndarray:
    """Two 4-bit LUT codes per byte (exact iff every code < 16; checked)."""
    if code.size and int(code.max()) >= 16:
        raise ValueError("code >= 16 cannot be nibble-packed")
    n, w = code.shape
    c = np.zeros((n, w + (w & 1)), np.uint8)
    c[:, :w] = code
    return (c[:, 0::2] | (c[:, 1::2] << 4)).astype(np.uint8)


def unpack_code4(c4: np.ndarray, w: int = SN_W * SN_W) -> np.ndarray:
    out = np.empty((len(c4), c4.shape[1] * 2), np.uint8)
    out[:, 0::2] = c4 & 0x0F
    out[:, 1::2] = c4 >> 4
    return out[:, :w]


def snake_decode(enc: dict, idx=None) -> np.ndarray:
    """float32 [n, 2688] (bit-exact to the float16 features). ``enc`` holds "code" or nibble-packed "code4"."""
    sel = (lambda a: a) if idx is None else (lambda a: a[idx])
    bits, tail = sel(enc["bits"]), sel(enc["tail"])
    code = sel(enc["code"]) if "code" in enc else unpack_code4(sel(enc["code4"]))
    n = len(code)
    img = np.empty((n, SN_C, SN_W * SN_W), np.float32)
    img[:, list(SN_BIN)] = np.unpackbits(bits, axis=-1, count=SN_W * SN_W).astype(np.float32)
    img[:, 1] = SN_LUT[code].astype(np.float32)
    return np.concatenate([img.reshape(n, SN_IMG), tail.astype(np.float32)], 1)


def load_game(game: str, limit_chunks: int | None = None, log=print) -> dict:
    """{"X" (rr/booster float16 [n, dim]) or "enc" (snake packed), "Y" int64 [n, slots], "sha" [n], "digest", "meta"}."""
    d, _, expect = REF[game]
    names = chunk_list(game)
    if limit_chunks:
        names = names[:limit_chunks]
    key = "featlf" if game == "snake" else "feat"
    seen, parts, ys, shas, dropped = set(), [], [], [], 0
    h = hashlib.sha256()
    for i, nm in enumerate(names):
        eps = check_episodes(game, d, nm)
        zx = np.load(d / f"{nm}.{key}.npz")
        zb = np.load(d / f"{nm}.feat.npz")
        sha = zx["sha"]
        if key != "feat" and not (zb["sha"] == sha).all():
            raise AssertionError(f"{nm}: feat/featlf row order differs")
        if not set(np.unique(zb["ep"]).tolist()) <= eps:
            raise AssertionError(f"{nm}: a row's episode is not a checked episode of the chunk")
        keep = []
        for j, s in enumerate(sha):
            if s in seen:
                dropped += 1
            else:
                seen.add(s)
                keep.append(j)
        keep = np.asarray(keep, np.int64)
        X16 = zx["X"][keep]
        if X16.shape[1] != DIMS[game]:
            raise AssertionError(f"{nm}: feature width {X16.shape[1]} != {DIMS[game]}")
        if game == "snake":
            enc = snake_encode(X16)
            if not np.array_equal(snake_decode(enc).astype(np.float16), X16):
                raise AssertionError(f"{nm}: snake packing is not bit-exact")
            parts.append(enc)
        else:
            parts.append(X16)
        Y = zb["Y"][keep].astype(np.int64)
        ys.append(Y)
        shas.append(sha[keep])
        h.update(nm.encode())
        h.update(hashlib.sha256(np.ascontiguousarray(X16).tobytes()).digest())
        h.update(hashlib.sha256(np.ascontiguousarray(Y).tobytes()).digest())
        if (i + 1) % 50 == 0:
            log(f"  {game}: {i + 1}/{len(names)} chunks, {sum(len(y) for y in ys)} rows")
    Y = np.concatenate(ys)
    if (Y < 0).any() or any((Y[:, s] >= k).any() for s, k in enumerate(HEADS[game])):
        raise AssertionError(f"{game}: target outside the head sizes")
    out = {"Y": Y, "sha": np.concatenate(shas), "digest": h.hexdigest(),
           "meta": {"game": game, "chunks": len(names), "rows": int(len(Y)), "dup_dropped": dropped,
                    "reference_receipt": str(REF[game][1]), "features": key}}
    if game == "snake":
        out["enc"] = {k: np.concatenate([p[k] for p in parts]) for k in ("bits", "code", "tail")}
    else:
        out["X"] = np.concatenate(parts)
    if limit_chunks is None and len(Y) != expect:
        raise AssertionError(f"{game}: {len(Y)} rows != reference student's {expect}")
    return out


def features(data: dict, idx: np.ndarray) -> np.ndarray:
    """float32 features of rows idx."""
    if "enc" in data:
        return snake_decode(data["enc"], idx)
    return data["X"][idx].astype(np.float32)


def moments(data: dict, chunk: int = 4096) -> tuple[np.ndarray, np.ndarray]:
    """Column mean / std (float64 accumulators, population std, std < 1e-6 -> 1) = bv2n.student.model._moments."""
    n = len(data["Y"])
    s1 = None
    for i in range(0, n, chunk):
        x = features(data, np.arange(i, min(n, i + chunk))).astype(np.float64)
        s1 = x.sum(0) if s1 is None else s1 + x.sum(0)
    mu = s1 / n
    s2 = np.zeros_like(mu)
    for i in range(0, n, chunk):
        x = features(data, np.arange(i, min(n, i + chunk))).astype(np.float64)
        s2 += ((x - mu) ** 2).sum(0)
    sd = np.sqrt(s2 / n)
    sd[sd < 1e-6] = 1.0
    return mu.astype(np.float32), sd.astype(np.float32)


# ------------------------------------------------------------------ data-lane game shards (Phase-1 A/B and M3)
VALUE_KEY = {"snake": "censored", "rr": "success", "booster": "landed"}   # value target = P(outcome | s, teacher)


def p1_order(record_ids, salt: str = "v2g-p1-v0") -> np.ndarray:
    """Indices sorting rows by sha256(salt + '|' + row_id) ascending (PREREG_V2G Phase-1 subset rule)."""
    keys = [hashlib.sha256(f"{salt}|{r}".encode()).hexdigest() for r in record_ids]
    return np.argsort(np.asarray(keys), kind="stable")


def load_game_shards(game: str, paths: list[str], n_rows: int | None = None, row_ids: set | None = None,
                     log=print, split: str = "train") -> dict:
    """Rows of the data lane's game shards (record v2g-rec-v0, view_struct {"fmt": "game-<g>", "view": ...}).
    Selection: row_ids (a manifest list) or the first n_rows in Phase-1 order (p1_order) or all rows. Features =
    the reference students' featurizers on the stored view (snake: snake_lf_x). Targets Y = SPEC[game]["y"](view,
    teacher_joint), round-trip checked against SPEC["joint"]. Value label (teacher-policy episodes only, else masked):
    snake: the episode reached the 60 s cap (censored); rr: episode success; booster: landed."""
    import pyarrow.parquet as pq  # noqa: PLC0415

    from nagi.burst2._rt.bv2n.student import features as F  # noqa: PLC0415
    sp = F.SPEC["snake_lf" if game == "snake" else game]
    import pyarrow.compute as pc  # noqa: PLC0415
    cols = ["record_id", "family_id", "split", "view_struct", "label", "t"]
    # Mixed shards (the data lane's materialized A/B subset holds every source in part-*.parquet): only the rows of
    # this game's family are read; pure game shards are unchanged by the filter.
    tabs = [t.filter(pc.equal(t["family_id"], f"game:{game}"))
            for t in (pq.read_table(p, columns=cols) for p in sorted(paths))]
    rids = [r for t in tabs for r in t.column("record_id").to_pylist()]
    if row_ids is not None:
        sel = [i for i, r in enumerate(rids) if r in row_ids]
        if len(sel) != len(row_ids):
            raise AssertionError(f"{game}: {len(row_ids) - len(sel)} manifest rows missing from the shards")
    else:
        sel = p1_order(rids)[:n_rows].tolist() if n_rows else list(range(len(rids)))
    sel = sorted(sel)
    want = set(sel)
    X, Y, V, HV, out_ids = [], [], [], [], []
    i = 0
    h = hashlib.sha256()
    for t in tabs:
        for r in t.to_pylist():
            if i in want:
                if r["family_id"] != f"game:{game}" or r["split"] != split:
                    raise AssertionError(f"{r['record_id']}: not a {split} row of game {game}")
                vs = json.loads(r["view_struct"])
                if vs["fmt"] != f"game-{game}":
                    raise AssertionError(f"{r['record_id']}: view fmt {vs['fmt']}")
                lab = json.loads(r["label"])
                view, tj = vs["view"], lab["teacher_joint"]
                y = sp["y"](view, tj)
                if sp["joint"](view, y) != tj:
                    raise AssertionError(f"{r['record_id']}: target round trip failed")
                X.append(np.asarray(sp["x"](view), np.float32).astype(np.float16))
                Y.append(y)
                ep = lab["episode"]
                HV.append(bool(lab.get("episode_policy_teacher")))
                V.append(float(bool(ep[VALUE_KEY[game]])))
                out_ids.append(r["record_id"])
                h.update(r["record_id"].encode())
                if len(out_ids) % 20000 == 0:
                    log(f"  {game} shards: {len(out_ids)}/{len(sel)} rows featurized")
            i += 1
    X16 = np.stack(X)
    Ya = np.asarray(Y, np.int64)
    out = {"Y": Ya, "sha": np.asarray(out_ids), "value": np.asarray(V, np.float32), "has_value": np.asarray(HV, bool),
           "digest": hashlib.sha256(h.digest() + hashlib.sha256(X16.tobytes()).digest()
                                    + hashlib.sha256(Ya.tobytes()).digest()).hexdigest(),
           "meta": {"game": game, "source": "v2g-data shards", "shards": [os.path.basename(p) for p in sorted(paths)],
                    "rows": len(out_ids), "rows_with_value": int(np.sum(HV)), "selection":
                    "manifest row_ids" if row_ids is not None else (f"first {n_rows} in p1 order" if n_rows else "all"),
                    "value_key": VALUE_KEY[game]}}
    if game == "snake":
        enc = snake_encode(X16)
        if not np.array_equal(snake_decode(enc).astype(np.float16), X16):
            raise AssertionError("snake packing is not bit-exact")
        out["enc"] = enc
    else:
        out["X"] = X16
    return out


# ------------------------------------------------------------------ game row cache (memory: the trainer never parses shards)
def _digest(ids, X16: np.ndarray, Ya: np.ndarray) -> str:
    h = hashlib.sha256()
    for r in ids:
        h.update(str(r).encode())
    return hashlib.sha256(h.digest() + hashlib.sha256(np.ascontiguousarray(X16).tobytes()).digest()
                          + hashlib.sha256(np.ascontiguousarray(Ya).tobytes()).digest()).hexdigest()


def save_game_cache(path: str, d: dict) -> str:
    """Exact arrays of a ``load_game_shards`` result (snake packed). ``load_game_cache`` recomputes the digest."""
    arrays = {"Y": d["Y"], "sha": d["sha"], "value": d["value"], "has_value": d["has_value"],
              "digest": np.array(d["digest"]), "meta": np.array(json.dumps(d["meta"], sort_keys=True))}
    if "enc" in d:
        arrays.update({f"enc_{k}": v for k, v in d["enc"].items()})
    else:
        arrays["X"] = d["X"]
    np.savez_compressed(path, **arrays)   # disk floor (20 GB): compressed; loaded into RAM by load_game_cache
    return d["digest"]


def _digest_chunked(ids, data: dict, rows: int = 32768) -> str:
    """== _digest(ids, X16, Y) without materializing X16 (snake: decoded chunk by chunk)."""
    h = hashlib.sha256()
    for r in ids:
        h.update(str(r).encode())
    hx = hashlib.sha256()
    n = len(data["Y"])
    for s0 in range(0, n, rows):
        idx = np.arange(s0, min(n, s0 + rows))
        x16 = snake_decode(data["enc"], idx).astype(np.float16) if "enc" in data else data["X"][idx]
        hx.update(np.ascontiguousarray(x16).tobytes())
    return hashlib.sha256(h.digest() + hx.digest()
                          + hashlib.sha256(np.ascontiguousarray(data["Y"]).tobytes()).digest()).hexdigest()


def load_game_cache(path: str) -> dict:
    """Inverse of save_game_cache; fail closed unless the recomputed digest equals the stored one."""
    with np.load(path, allow_pickle=False) as z:
        d = {k: z[k] for k in ("Y", "sha", "value", "has_value")}
        d["digest"], d["meta"] = str(z["digest"]), json.loads(str(z["meta"]))
        if "X" in z.files:
            d["X"] = z["X"]
        else:
            d["enc"] = {k[4:]: z[k] for k in z.files if k.startswith("enc_")}
    if _digest_chunked(d["sha"].tolist(), d) != d["digest"]:
        raise AssertionError(f"{path}: game cache digest mismatch")
    d["meta"] = dict(d["meta"], cache=os.path.basename(path))
    return d


def build_game_cache(game: str, paths: list[str], out: str, log=print, split: str = "train",
                     pack_code: bool = True) -> dict:
    """Streaming ``load_game_shards(game, paths)`` (all rows of the game's family, file order) written as a cache:
    features and targets are computed exactly as there, but per parquet file, so X16 is never materialized (snake:
    encoded per file, the LUT code nibble-packed when every code < 16). The digest is the same definition, computed
    incrementally; ``load_game_cache`` re-verifies it."""
    import pyarrow.compute as pc  # noqa: PLC0415
    import pyarrow.parquet as pq  # noqa: PLC0415

    from nagi.burst2._rt.bv2n.student import features as F  # noqa: PLC0415
    sp = F.SPEC["snake_lf" if game == "snake" else game]
    cols = ["record_id", "family_id", "split", "view_struct", "label", "t"]
    hid, hx = hashlib.sha256(), hashlib.sha256()
    Ys, Vs, HVs, ids, Xs, encs = [], [], [], [], [], []
    for p in sorted(paths):
        t = pq.read_table(p, columns=cols)
        t = t.filter(pc.equal(t["family_id"], f"game:{game}"))
        X, Y = [], []
        for r in t.to_pylist():
            if r["split"] != split:
                raise AssertionError(f"{r['record_id']}: not a {split} row of game {game}")
            vs = json.loads(r["view_struct"])
            if vs["fmt"] != f"game-{game}":
                raise AssertionError(f"{r['record_id']}: view fmt {vs['fmt']}")
            lab = json.loads(r["label"])
            view, tj = vs["view"], lab["teacher_joint"]
            y = sp["y"](view, tj)
            if sp["joint"](view, y) != tj:
                raise AssertionError(f"{r['record_id']}: target round trip failed")
            X.append(np.asarray(sp["x"](view), np.float32).astype(np.float16))
            Y.append(y)
            ep = lab["episode"]
            HVs.append(bool(lab.get("episode_policy_teacher")))
            Vs.append(float(bool(ep[VALUE_KEY[game]])))
            ids.append(r["record_id"])
            hid.update(r["record_id"].encode())
        del t
        if not X:
            continue
        X16 = np.stack(X)
        del X
        hx.update(X16.tobytes())
        Ys.append(np.asarray(Y, np.int64))
        if game == "snake":
            e = snake_encode(X16)
            if not np.array_equal(snake_decode(e).astype(np.float16), X16):
                raise AssertionError("snake packing is not bit-exact")
            if pack_code and int(e["code"].max()) < 16:   # nibble-pack per file (memory); exactness re-checked below
                e["code4"] = pack_code4(e.pop("code"))
                if not np.array_equal(snake_decode(e).astype(np.float16), X16):
                    raise AssertionError("snake nibble packing is not bit-exact")
            encs.append(e)
        else:
            Xs.append(X16)
        del X16
        log(f"  {game} cache: {len(ids)} rows after {os.path.basename(p)}")
    Ya = np.concatenate(Ys)
    digest = hashlib.sha256(hid.digest() + hx.digest() + hashlib.sha256(Ya.tobytes()).digest()).hexdigest()
    d = {"Y": Ya, "sha": np.asarray(ids), "value": np.asarray(Vs, np.float32), "has_value": np.asarray(HVs, bool),
         "digest": digest,
         "meta": {"game": game, "source": "v2g-data shards", "shards": [os.path.basename(p) for p in sorted(paths)],
                  "rows": len(ids), "rows_with_value": int(np.sum(HVs)), "selection": "all",
                  "value_key": VALUE_KEY[game], "builder": "build_game_cache (streaming)"}}
    if game == "snake":
        enc = {k: np.concatenate([e[k] for e in encs]) for k in ("bits", "tail")}
        if all("code4" in e for e in encs):
            enc["code4"] = np.concatenate([e["code4"] for e in encs])
        else:
            enc["code"] = np.concatenate([e["code"] if "code" in e else unpack_code4(e["code4"]) for e in encs])
        del encs
        d["enc"] = enc
    else:
        d["X"] = np.concatenate(Xs)
    save_game_cache(out, d)
    return d
