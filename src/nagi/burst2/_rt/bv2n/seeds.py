"""Frozen seed streams for Burst V2-next (bv2n). Frozen 2026-10-11 before any bv2n data or teacher run.

Streams (seed key g in burst_v2.seeds.SEED_GAMES; seed of index i = sha256("<prefix>|g|i") mod 2^31, skipping any seed
reserved by an Arena schedule, exactly as burst_v2.seeds):
  teacher_dev   bv2n-teacher-dev   teacher tuning, unlimited looks (selection split)
  teacher_gate  bv2n-teacher-gate  indices 0-23: the frozen teacher gate block, run ONCE per frozen candidate config
  train         bv2n-train         teacher rollouts / eps / perturbed states for training rows
  dagger        bv2n-dagger        learner rollouts relabelled by the teacher (DAgger rounds; round r uses its own range)
  student_dev   bv2n-student-dev   small-student and 27B dev closed-loop checks (never trained on)
Arena schedule seeds (eval, dev 48-59, calib, variant splits) stay reserved: never labelled, never trained on.
Historical blocks 20000-21023 (v2_teachers) and 32000-32011 (rr_teacher_pilot sealed) are other prefixes; untouched.
"""
from __future__ import annotations

import hashlib

from nagi.burst2._rt.burst_v2.seeds import SEED_GAMES, reserved

STREAMS = {
    "teacher_dev": "bv2n-teacher-dev",
    "teacher_gate": "bv2n-teacher-gate",
    "train": "bv2n-train",
    "dagger": "bv2n-dagger",
    "student_dev": "bv2n-student-dev",
}
TRAINABLE = ("train", "dagger")
GATE_BLOCK = 24


def _raw(prefix: str, seed_game: str, i: int) -> int:
    return int(hashlib.sha256(f"{prefix}|{seed_game}|{i}".encode()).hexdigest(), 16) % (2 ** 31)


def seeds(stream: str, seed_game: str, n: int, start: int = 0) -> list[tuple[int, int]]:
    """[(index, seed)] of n non-reserved seeds of a stream from index `start` (reserved collisions are skipped)."""
    assert stream in STREAMS and seed_game in SEED_GAMES, (stream, seed_game)
    if stream == "teacher_gate":
        assert start + n <= GATE_BLOCK, "the teacher gate block is indices 0-23 only"
    out, i, res = [], start, reserved(seed_game)
    while len(out) < n:
        s = _raw(STREAMS[stream], seed_game, i)
        if s not in res:
            out.append((i, s))
        i += 1
    return out


def stream_of(seed_game: str, seed: int, max_index: int = 200_000) -> str | None:
    """Which bv2n stream produced this seed (None if none, e.g. an Arena seed)."""
    for name, p in STREAMS.items():
        if any(_raw(p, seed_game, i) == seed for i in range(max_index)):
            return name
    return None


def assert_trainable(seed_game: str, seed: int, stream: str) -> None:
    """Fail closed: a training row may only come from the train or dagger stream and never from a reserved seed."""
    if seed in reserved(seed_game):
        raise ValueError(f"seed {seed} is a reserved Arena seed of {seed_game}")
    if stream not in TRAINABLE:
        raise ValueError(f"stream {stream} is not trainable")
