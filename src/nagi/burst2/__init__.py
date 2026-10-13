"""Nagi Burst V2: one small Nagi core + built-in lookahead, served from the machine's rule text (numpy only, CPU).

    from nagi import burst2
    core = burst2.load_core()                                   # pinned Hugging Face revision, sha256-checked
    out = burst2.operate(request_text, options={"core": core, "session": "my-run", "step": 0})
    out["choice"], out["probabilities"], out["stats"]

``operate(request)`` takes a served request (mz-1 / mz-1x machine language, or a Snake Rush / Rotorwash-Ramp /
Booster Gauntlet request) and returns {choice, joint, probabilities, joint_probabilities, stats}.
``operate(rules_text, state)`` and ``operate_structured(spec, view)`` are the rules-plus-state and structured forms;
``read_rules(text, strict=True)`` is the exact reader (``.rules_text()`` = the canonical rulebook).

Defaults are the FROZEN evaluated configuration (``FROZEN_DEFAULTS``; the configuration the V2 report measured):
search budget S* one-tick simulations, depth cap 40, belief v1b, core confidence gate tau = 0.6, no core leaf values.
Options you pass override them; anything else is an unevaluated configuration.

The pick inside the search's exact tie set is a draw from ``probabilities``: pass ``session`` (+ ``step``, which you
increment per decision) or ``seed`` for replayable draws; with neither, the draw uses fresh entropy
(``stats["replayable"] = False``). Do not use a fixed seed for every call: a stateless deterministic policy can loop.

The runtime under ``nagi.burst2._rt`` is vendored verbatim from the research repository (see ``_rt/MANIFEST.json``:
commit and per-file sha256), with imports rewritten to this package. It includes the Arena game engines and the
games' reference engines / teachers (``arena``, ``bv2n.teachers``, ``rr_teacher_pilot``, ``burst_v2``) because the
served-request parser imports them: they are reference engines for reproducing the Arena numbers and are never called
to make a decision.
"""

from __future__ import annotations

from nagi.burst2._api import (  # noqa: F401
    BELIEF,
    BURST_V2_REPO,
    BURST_V2_REVISION,
    CORE_FILENAME,
    CORE_SHA256,
    FROZEN_DEFAULTS,
    K_MAX,
    S_STAR,
    SNAKE_POLICY,
    TAU,
    load_core,
    operate,
    operate_structured,
    read_rules,
)
from nagi.burst2._rt.v2g.reader import ReaderError  # noqa: F401,E402

__all__ = ["operate", "operate_structured", "load_core", "read_rules", "ReaderError", "FROZEN_DEFAULTS", "S_STAR", "TAU", "BELIEF", "K_MAX",
           "SNAKE_POLICY", "BURST_V2_REPO", "BURST_V2_REVISION", "CORE_SHA256", "CORE_FILENAME"]
