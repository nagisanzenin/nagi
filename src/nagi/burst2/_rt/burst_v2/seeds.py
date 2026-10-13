"""Train seed stream for Burst V2 labels, disjoint from every Arena seed schedule.

Reserved (never trained on): every seed of the Arena v3 schedule of the game's seed key (scripts/arena_v3_registry:
splits dev 72, calib 32, eval 72 = indices 0-71 incl. old records 0-33, fresh eval 34-57, spare 58-71,
variant_sealed 36), for Booster also every seed of booster_gauntlet_arena's own splits (calib, eval, variant_dev,
variant_sealed), and the v3.1 RR calibration seeds (ramp_seed = the v3 registry formula, same set).

Train seed i of seed key g: int(sha256("burst-v2-train|g|i")) mod 2^31, skipping (deterministically) any index whose
seed is reserved. A different prefix means the collision probability per pair is 2^-31; the test enumerates it anyway.
"""
from __future__ import annotations

import hashlib
import sys
from functools import lru_cache
from pathlib import Path

TRAIN_PREFIX = "burst-v2-train"
DAGGER_PREFIX = "burst-v2-dagger"
SEED_GAMES = ("booster_gauntlet", "rotorwash_ramp", "snake")
_ROOT = Path(__file__).resolve().parents[2]


def _registry():
    p = str(_ROOT / "scripts")
    if p not in sys.path:
        sys.path.insert(0, p)
    import arena_v3_registry as R
    return R


@lru_cache(maxsize=None)
def reserved(seed_game: str) -> frozenset:
    """Every schedule seed of this seed key that any Arena split uses (eval, dev, calib, variant splits)."""
    assert seed_game in SEED_GAMES, seed_game
    R = _registry()
    out = {R.seed_for(seed_game, sp, i) for sp, n in R.V3_SPLITS.items() for i in range(n)}
    if seed_game == "booster_gauntlet":
        from nagi.burst2._rt.arena.games import booster_gauntlet_arena as BGA
        out |= {BGA.seed_for(sp, i) for sp in BGA.SPLITS for i in range(max(BGA.N_DEFAULT[sp], 72))}
    elif seed_game == "snake":
        from nagi.burst2._rt.arena.games import snake_rush as SR
        out |= {s for sp in SR.SPLITS for s in SR.seeds(sp, 72)}
    else:
        from nagi.burst2._rt.arena.games.rotorwash_ramp_bots import ramp_seed
        out |= {ramp_seed(sp, i) for sp in ("calib", "dev", "eval", "variant_sealed") for i in range(72)}
    return frozenset(out)


def eval_seed(seed_game: str, i: int) -> int:
    return _registry().seed_for(seed_game, "eval", i)


def _raw(prefix: str, seed_game: str, i: int) -> int:
    return int(hashlib.sha256(f"{prefix}|{seed_game}|{i}".encode()).hexdigest(), 16) % (2 ** 31)


def train_seed(seed_game: str, i: int, prefix: str = TRAIN_PREFIX) -> int:
    """Seed of train index i (i >= 0); raises if it is reserved (callers use train_seeds, which skips)."""
    s = _raw(prefix, seed_game, i)
    if s in reserved(seed_game):
        raise ValueError(f"train index {i} of {seed_game} collides with a reserved Arena seed")
    return s


def train_seeds(seed_game: str, n: int, start: int = 0, prefix: str = TRAIN_PREFIX) -> list[tuple[int, int]]:
    """[(train index, seed)] for n indices from `start`, skipping reserved collisions (none found for i < 100k)."""
    out, i, res = [], start, reserved(seed_game)
    while len(out) < n:
        s = _raw(prefix, seed_game, i)
        if s not in res:
            out.append((i, s))
        i += 1
    return out


def is_train_seed(seed_game: str, seed: int, max_index: int = 100_000) -> bool:
    return seed not in reserved(seed_game) and any(
        _raw(p, seed_game, i) == seed for p in (TRAIN_PREFIX, DAGGER_PREFIX) for i in range(max_index))


def assert_train(seed_game: str, seed: int) -> None:
    """Fail closed: a label / DAgger row may only come from a non-reserved seed."""
    if seed in reserved(seed_game):
        raise ValueError(f"seed {seed} is a reserved Arena seed of {seed_game}; never label it")
