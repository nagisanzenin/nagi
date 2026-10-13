"""Game dataset collectors (bv2n lane gamedata): teacher rollouts, eps / scripted-perturbation rollouts, DART-style
executed-action noise, and DAgger rounds (student rollouts relabelled by the teacher). CPU, $0.

Timing: the nominal 1-tick reply (LANES.md): burst_v2.latency.Emulator with fixed_delay = 1, i.e. the arena.v3.runner
order with every reply landing one tick after its observation. At every request the client sees view(s_k, p_log_k);
the teacher labels THAT view; the behaviour picks the EXECUTED reply:
  teacher      the teacher joint
  eps:<e>      w.p. e a uniformly random joint (all options of every control), else the teacher
  script:<p>   a Burst-like scripted slip (burst_v2 adapters' perturb_script: Snake straight/turn runs, RR slow
               cruise / creeping collective / aft brake / sink / forward rush) starts w.p. p per request and runs its
               length; else the teacher
  dart:<rho>   per control, w.p. rho the executed option is a neighbour of the teacher's (RR: option index +-1;
               Snake: a random other legal turn) — DART (Laskey et al. 2017) for discrete controls
  student      the student's argmax joint (DAgger); the teacher's label is the target
Every visited request is labelled (labels never depend on the behaviour). Seeds come only from bv2n.seeds streams
train (collectors) / dagger (rounds), from fixed per-collector index ranges, and every row calls assert_trainable.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import random
import time
from functools import lru_cache
from pathlib import Path

from nagi.burst2._rt.bv2n import seeds as BS
from nagi.burst2._rt.bv2n.data import views as VW

# train-stream index ranges per collector (disjoint); dagger-stream ranges per round
RANGES = {"teacher": (0, 20_000), "eps": (20_000, 30_000), "script": (30_000, 40_000), "dart": (40_000, 50_000)}
DAGGER_RANGE = {r: ((r - 1) * 10_000, r * 10_000) for r in range(1, 9)}   # r5-r8: lane snake-student (combo rounds)
ROW_VERSION = "bv2n-gamedata-rows-1"


def index_range(behaviour: str, rnd: int) -> tuple[str, int, int]:
    if behaviour.startswith("student"):
        return ("dagger", *DAGGER_RANGE[rnd])
    return ("train", *RANGES[behaviour.split(":")[0]])


def _rng(key: str) -> random.Random:
    return random.Random(hashlib.sha256(f"bv2n-gamedata|{key}".encode()).hexdigest())


@lru_cache(maxsize=None)
def _adapter(game: str):
    from nagi.burst2._rt.burst_v2 import generate as GN
    return GN.adapter_for(game)


class Behaviour:
    def __init__(self, vs, spec: str, key: str, student=None):
        self.vs, self.spec, self.kind = vs, spec, spec.split(":")[0]
        self.p = float(spec.split(":")[1]) if ":" in spec else 0.0
        self.r = _rng(f"behaviour|{key}")
        self.student = student
        self.script = None
        if self.kind == "script":
            self.ad = _adapter(vs.game_id)

    def act(self, s, view: dict, teacher: dict) -> tuple[dict, str]:
        vs, r = self.vs, self.r
        if self.kind == "teacher":
            return dict(teacher), "teacher"
        if self.kind == "student":
            return self.student.act(view), "student"
        if self.kind == "eps":
            if r.random() < self.p:
                return {c: r.choice(vs.options[c]) for c in vs.controls}, "eps"
            return dict(teacher), "teacher"
        if self.kind == "script":
            if self.script is None and r.random() < self.p:
                self.script = self.ad.perturb_script(r, s)
                self.script["left"] = self.script["ticks"]
            if self.script is not None:
                self.script["left"] -= 1
                a, kind = dict(self.script["act"]), self.script["kind"]
                if self.script["left"] <= 0:
                    self.script = None
                return a, f"script:{kind}"
            return dict(teacher), "teacher"
        if self.kind == "dart":
            out, hit = {}, False
            for c in vs.controls:
                opts, a = list(vs.options[c]), teacher[c]
                if r.random() < self.p:
                    hit = True
                    if vs.game_id == "snake":
                        i = opts.index(a)
                        back = opts[(i + 2) % 4] if len(opts) == 4 else None
                        out[c] = r.choice([o for o in opts if o not in (a, back)])
                    else:
                        k = opts.index(a) + r.choice((-1, 1))
                        out[c] = opts[max(0, min(len(opts) - 1, k))]
                else:
                    out[c] = a
            return out, ("dart" if hit else "teacher")
        raise ValueError(self.spec)


def rollout(vs, seed: int, stream: str, idx: int, behaviour: str, rnd: int = 0, student=None,
            with_rows: bool = True, max_ticks: int | None = None) -> tuple[list[dict], dict]:
    """One round from tick 0 under the nominal 1-tick emulator. Returns (rows, episode record incl. the applied
    controls per tick for replay validation)."""
    from nagi.burst2._rt.burst_v2 import latency as LT
    if with_rows:
        BS.assert_trainable(vs.seed_game, seed, stream)
    key = f"{vs.game_id}|{stream}|{idx}|{behaviour}|{rnd}"
    beh = Behaviour(vs, behaviour, key, student)
    emu = LT.Emulator(vs.binding, {1: 1.0}, key, fixed_delay=1)
    s = vs.reset(seed)
    rows, applied, t0, n_teacher_calls = [], [], time.perf_counter(), 0
    hist: list = []

    def policy(state, p_log, k):
        nonlocal n_teacher_calls
        text = vs.render(state, p_log, hist)
        view = vs.parse(text)
        lab = vs.teacher(state, view, text) if (with_rows or beh.kind != "student") else None
        n_teacher_calls += lab is not None
        ex, src = beh.act(state, view, lab) if lab is not None else (student.act(view), "student")
        if with_rows:
            rows.append({"id": f"bv2n_{vs.game_id}_{stream}{idx}_r{rnd}_k{k}", "game": vs.game_id,
                         "seed_game": vs.seed_game, "seed": seed, "stream": stream, "index": idx, "round": rnd,
                         "tick": k, "behaviour": behaviour, "executed_by": src, "text": text, "text_sha256": VW.sha(text),
                         "view": view, "teacher_joint": lab,
                         "targets": {c: [1.0 if o == lab[c] else 0.0 for o in vs.options[c]] for c in vs.controls},
                         "executed_joint": ex, "view_source": VW.SOURCE, "row_version": ROW_VERSION})
        return ex

    with vs.ctx():
        while not vs.done(s) and (max_ticks is None or len(applied) < max_ticks):
            acts = emu.tick(vs.game, s, policy)
            applied.append(acts)
            hist.append((s, acts))
            s = vs.step(s, acts)
    ep = {"game": vs.game_id, "seed": seed, "stream": stream, "index": idx, "round": rnd, "behaviour": behaviour,
          "applied": applied, "requests": len(emu.requests), "rows": len(rows), "sec": time.perf_counter() - t0,
          "teacher_calls": n_teacher_calls, **vs.outcome(s)}
    return rows, ep


def collect(game: str, behaviour: str, n_episodes: int, rnd: int = 0, student=None, offset: int = 0,
            log=None) -> tuple[list[dict], list[dict]]:
    vs = VW.make(game)
    stream, lo, hi = index_range(behaviour, rnd)
    plan = BS.seeds(stream, vs.seed_game, n_episodes, start=lo + offset)
    assert plan[-1][0] < hi, (behaviour, rnd, plan[-1])
    rows, eps = [], []
    for n, (idx, seed) in enumerate(plan):
        r, ep = rollout(vs, seed, stream, idx, behaviour, rnd, student)
        rows += r
        eps.append(ep)
        if log and (n + 1) % 25 == 0:
            log(f"{game} {behaviour} r{rnd}: {n + 1}/{n_episodes} episodes, {len(rows)} rows")
    return rows, eps


def dedup(rows: list[dict]) -> tuple[list[dict], int]:
    seen, out = set(), []
    for r in rows:
        if r["text_sha256"] in seen:
            continue
        seen.add(r["text_sha256"])
        out.append(r)
    return out, len(rows) - len(out)


def write_jsonl_gz(path: Path, items: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = "".join(json.dumps(x, sort_keys=True, separators=(",", ":")) + "\n" for x in items).encode()
    with open(path, "wb") as f:
        with gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="") as gz:
            gz.write(raw)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl_gz(path) -> list[dict]:
    with gzip.open(path, "rt") as f:
        return [json.loads(x) for x in f]


def write_dataset(out_dir: Path, name: str, rows: list[dict], eps: list[dict], meta: dict) -> dict:
    rows, dropped = dedup(rows)
    sha_rows = write_jsonl_gz(out_dir / f"{name}.rows.jsonl.gz", rows)
    sha_eps = write_jsonl_gz(out_dir / f"{name}.episodes.jsonl.gz", eps)
    man = dict(meta, name=name, rows=len(rows), dup_dropped=dropped, episodes=len(eps),
               rows_sha256=sha_rows, episodes_sha256=sha_eps, view_source=VW.SOURCE, row_version=ROW_VERSION,
               index_min=min(e["index"] for e in eps), index_max=max(e["index"] for e in eps),
               streams=sorted({e["stream"] for e in eps}), rounds=sorted({e["round"] for e in eps}),
               teacher_success=sum(bool(e["success"]) for e in eps), mean_score=sum(e["score"] for e in eps) / len(eps),
               executed_by={k: sum(r["executed_by"].split(":")[0] == k for r in rows)
                            for k in sorted({r["executed_by"].split(":")[0] for r in rows})},
               cpu_s=sum(e["sec"] for e in eps), teacher_calls=sum(e["teacher_calls"] for e in eps))
    man["rows_per_s"] = sum(e["rows"] for e in eps) / max(1e-9, man["cpu_s"])
    (out_dir / f"{name}.manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n")
    return man
