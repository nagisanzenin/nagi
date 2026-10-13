"""Public Burst V2 API over the vendored runtime (``nagi.burst2._rt``). See ``nagi.burst2`` for usage."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

# ---------------------------------------------------------------- FROZEN evaluated configuration (do not edit alone)
# Values marked TO FILL are set at the CANDIDATE freeze; tests/test_burst2_defaults.py checks every value against the
# shipped frozen files (nagi/burst2/frozen/: runtime_search_config_v1b.json sha256 996c2951..., candidate.json).
S_STAR = 100_000            # FROZEN: CANDIDATE.json (sha256 28fe5de6...) candidate_policy G100000b1b
K_MAX = 40                  # runtime_search_config_v1b.json zoo.k_max
BELIEF = "v1b"              # runtime_search_config_v1b.json zoo.belief
TAU = 0.6                   # CANDIDATE.json search_config.tau (core confidence gate)
SNAKE_POLICY = "sdk_pack"   # FROZEN: CANDIDATE.json snake_policy (B3 rule: SDK pack, UCB 86.1 <= 150 ms)
# Zoo (machine-language) requests: these options sit under the user's options. Snake (SDK pack) and RR / Booster
# (core head) requests use their own frozen paths (research m4_arena / m4_li: operate(text) with the core only).
FROZEN_DEFAULTS = {"max_sims": S_STAR, "k_max": K_MAX, "belief": BELIEF, "tau": TAU, "deterministic": True,
                   "core_value": False}
FROZEN_CONFIG_SHA256 = "996c2951614716f1b1a9db4ce8e86e3f33bb2fdab32eb2d1f3831b9179c8b94d"

# ---------------------------------------------------------------- core weights (public repo; no credentials anywhere)
BURST_V2_REPO = "nagisanzeninz/Nagi-Burst-V2"
BURST_V2_REVISION = "803cdcbb384c81c0a7411aa65fe058b933a4545b"
CORE_SHA256 = "a24e1158b00a59ad1fc103001c301981aa94da033e59fcee7b645ae2deef5624"  # FROZEN: CANDIDATE core_weights_sha256
CORE_FILENAME = "model.npz"

_DEFAULT_CORE = None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_core(path: str | os.PathLike | None = None, repo: str = BURST_V2_REPO, revision: str | None = None,
              sha256: str | None = None):
    """The Burst V2 core (numpy). ``path`` = a local model.npz; otherwise the file is fetched from the Hugging Face
    ``repo`` at the pinned ``revision`` (default BURST_V2_REVISION) with ``huggingface_hub`` (public repo, no token).
    The bytes must hash to ``sha256`` (default CORE_SHA256) when one is pinned; a mismatch refuses."""
    from nagi.burst2._rt.v2g.core.multi_core import MultiCore  # noqa: PLC0415

    want = sha256 if sha256 is not None else CORE_SHA256
    if path is None:
        rev = revision or BURST_V2_REVISION
        if rev is None:
            raise RuntimeError("this build pins no Burst V2 revision: pass load_core(path=...) or revision=...")
        from huggingface_hub import hf_hub_download  # noqa: PLC0415

        path = hf_hub_download(repo_id=repo, filename=CORE_FILENAME, revision=rev)
    p = Path(path)
    if want is not None and _sha256(p) != want:
        raise ValueError(f"{p}: sha256 != the pinned Burst V2 core sha256 {want}")
    return MultiCore.load(str(p))


def _core(options: dict):
    global _DEFAULT_CORE
    if "core" in options:
        return options["core"]
    if _DEFAULT_CORE is None:
        _DEFAULT_CORE = load_core()
    return _DEFAULT_CORE


def _route(request: str, state):
    """("zoo" | "snake" | "rr" | "booster", game machine or None)."""
    from nagi.burst2._rt.v2g import games  # noqa: PLC0415

    g = games.match_request(request) if state is None else games.match_rules(request)
    return ("zoo", None) if g is None else (g.game, g)


def _core_head(game: str, view: dict, core, t0: float, read_ms: float = 0.0) -> dict:
    """The core game head, per-slot argmax (= research GamePolicy.act); used for Snake only when
    SNAKE_POLICY == "core_head" (RR / Booster go through the vendored v2g.games.arena_core, the same policy)."""
    import numpy as np  # noqa: PLC0415

    from nagi.burst2._rt.bv2n.student import features as F  # noqa: PLC0415
    from nagi.burst2._rt.v2g.core.multi_core import game_forward, joint_logits  # noqa: PLC0415

    sp = F.SPEC["snake_lf" if game == "snake" else game]
    x = np.asarray(sp["x"](view), np.float32).astype(np.float16).astype(np.float32)[None]
    slot, _v = game_forward(core.params, core.config, game, x)
    cls = [int(lg[0].argmax()) for lg in slot]
    choice = sp["joint"](view, cls)
    joint = 0
    for i, lg in zip(cls, slot):
        joint = joint * int(lg.shape[1]) + i
    J = joint_logits(slot)[0].astype(np.float64)
    e = np.exp(J - J.max())
    pj = e / e.sum()
    probs: dict = {}
    for s, lg in enumerate(slot):  # per-slot softmax, labelled through the game's own joint mapping
        z = lg[0].astype(np.float64)
        q = np.exp(z - z.max())
        q = q / q.sum()
        for k in range(len(q)):
            pick = list(cls)
            pick[s] = k
            d = sp["joint"](view, pick)
            ctl = list(d)[s]
            probs.setdefault(ctl, {})[d[ctl]] = float(q[k])
    return {"choice": dict(choice), "joint": int(joint), "probabilities": probs,
            "joint_probabilities": {int(j): float(p) for j, p in enumerate(pj)},
            "stats": {"game": game, "read_ms": read_ms, "pick": "per-slot argmax (core head)",
                      "total_ms": (time.perf_counter() - t0) * 1e3, "sims": 0, "depth": 0, "gated": False}}


def operate(request: str, state=None, options: dict | None = None) -> dict:
    """Decide one request (module doc). For machine-language requests ``options`` override FROZEN_DEFAULTS."""
    from nagi.burst2._rt.v2g import operate as OP  # noqa: PLC0415

    t0 = time.perf_counter()
    user = dict(options or {})
    kind, g = _route(request, state)
    if kind == "zoo":
        o = dict(FROZEN_DEFAULTS)
        o.update(user)
        o["core"] = _core(user)
        return OP.operate(request, state, o)
    if kind == "snake":
        if SNAKE_POLICY == "core_head":
            tr = time.perf_counter()
            view = g.parse(request) if state is None else state
            return _core_head("snake", view, _core(user), t0, (time.perf_counter() - tr) * 1e3)
        pack = {k: v for k, v in user.items() if k not in ("core", "tau", "belief", "core_value")}
        return OP.operate(request, state, pack)          # the SDK Snake pack (its own frozen budget; no core)
    o = dict(user)
    o["core"] = _core(user)
    return OP.operate(request, state, o)                 # RR / Booster: the core head


def read_rules(text: str, strict: bool = True):
    """Rule text -> Machine (``.rules_text()`` = the exact canonical rulebook, ``.spec``, ``.machine_id``). ``strict``
    (default, the research reader): the text must already be canonical, else ReaderError; ``strict=False``
    canonicalizes it (convert once and keep the result, release QUICKSTART_MACHINE.md §2)."""
    from nagi.burst2._rt.v2g import reader  # noqa: PLC0415

    return reader.read_rules(text, strict=strict)


def operate_structured(spec, view, options: dict | None = None) -> dict:
    """Structured form: a machine program / mz-1x dict + client view, or "rr" / "booster" + the runner's view."""
    from nagi.burst2._rt.v2g import operate as OP  # noqa: PLC0415

    user = dict(options or {})
    if isinstance(spec, str):
        o = dict(user)
        o["core"] = _core(user)
        return OP.operate_structured(spec, view, o)
    o = dict(FROZEN_DEFAULTS)
    o.update(user)
    o["core"] = _core(user)
    return OP.operate_structured(spec, view, o)
