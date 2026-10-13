"""SDK-facing entry point: ``operate(rules_text, state, options) -> {choice, probabilities, stats}`` (PLAN §2).

    out = operate(request_text)                         # text path: one served Zoo request (rules + window + slots)
    out = operate(rules_text, state)                    # rules text + structured state (see _view_from_state)
    out = operate_structured(program_or_px, view)       # structured path (no text), same options

Every call is self-contained: the rules are read (exact reader, v2g.reader), the machine and its search model are
built inside the call and nothing is carried to the next call, so a decision is a pure function of the request bytes
and the options (prereg binding requirement; gate I parity and gate L latency are measured on exactly this path).

Output (Zoo machines):
    choice              {control: option key} (the served slot vocabulary dec / keep / inc, declared control order)
    joint               joint index (o0*9 + o1*3 + o2)
    probabilities       {control: {key: p}}: marginals of the joint distribution below
    joint_probabilities {joint: p}: uniform over the search's acceptable set A (joints the search cannot tell apart);
                        when the core gate opened, the core prior renormalised inside A
    stats               search stats (sims, depth, ms, gated, stop, belief, ...) + read_ms, total_ms, machine_id
Options: max_sims (default search.DEFAULT_MAX_SIMS = S*), k, deadline_ms (serving cap, reported), deterministic
(default True), core (object with .predict, LANES Core), tau, core_value; choice stream: rng | session (+ step) | seed,
tie.

Choice (owner/coordinator decision 2026-10-12 ~16:35, lanes/runtime.md §2.4). The search output (Q, the exact tie set
A, probabilities, sims) is a pure function of the request bytes. The pick inside A is a draw from ``probabilities``:
  * eval harness: ``rng`` = the episode's CRN policy stream (mc-2 rule: one rng.integers(len(A)) when the gate is
    closed) -> replayable from (request bytes, stream);
  * SDK: ``session`` (+ ``step``, which the caller increments per decision) or a ``seed`` the caller varies ->
    replayable; with none of them a fresh OS-entropy draw (stats["replayable"] = False);
  * audit mode: ``tie="hash"`` (deterministic in the request alone). Not the default: a stateless request makes it a
    stationary deterministic policy, which cycles when the goal is beyond the horizon (dev T4: S4 hash − uniform =
    −0.50 success; test_v2g_operate.test_looping_machine_escapes_with_seeded_sampling).
Game packs (Snake) ignore the stream: the Snake request carries the tick, the hybrid's hash tie is its tested rule.
"""

from __future__ import annotations

import time

from nagi.burst2._rt.v2g import reader
from nagi.burst2._rt.v2g import search as VS
from nagi.burst2._rt.v2g.machine import Machine

OPTION_KEYS = ("dec", "keep", "inc")
_SEARCH_OPTS = ("max_sims", "k", "k_max", "deadline_ms", "deterministic", "tie", "rng", "core", "tau", "core_value",
                "budget_frac", "belief")
_STREAM_OPTS = ("seed", "session", "step")


def stream(options: dict):
    """(tie, rng, replayable) for the pick inside the exact tie set A (module doc, "Choice")."""
    import hashlib  # noqa: PLC0415

    import numpy as np  # noqa: PLC0415

    tie, rng = options.get("tie"), options.get("rng")
    if tie in ("hash", "lowest"):
        return tie, None, True
    if rng is None:
        if "session" in options:
            key = f"v2g-operate|{options['session']}|{options.get('step', 0)}"
            rng = np.random.default_rng(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "little"))
        elif "seed" in options:
            sd = options["seed"]
            rng = np.random.default_rng(sd if isinstance(sd, int) else int.from_bytes(
                hashlib.sha256(str(sd).encode()).digest()[:8], "little"))
        else:
            return tie or "sample", np.random.default_rng(), False  # fresh OS entropy: not replayable
    return tie or "sample", rng, True


def _joint_of_answer(m: Machine, a) -> int:
    from nagi.burst2._rt.bv2n.zoo import render as R  # noqa: PLC0415

    if a is None:
        return None
    return R.answer_to_joint(m.program, a)


def _obs_tuple(m: Machine, o) -> tuple | None:
    if o is None:
        return None
    names = [m.var_names[c] for c in m.disp_cols]
    if isinstance(o, dict):
        if set(o) != set(names):
            raise ValueError(f"observation must give exactly the displayed vars {names}")
        return tuple(int(o[n]) for n in names)
    o = tuple(int(x) for x in o)
    if len(o) != len(names):
        raise ValueError(f"observation needs {len(names)} values {names}")
    return o


def _view_from_state(m: Machine, state) -> dict:
    """Structured client state -> view. mz-1: {var: value} over all vars, a list in var order, or a view dict.
    mz-1x: {"obs": [obs | None] * window (oldest first; obs = {displayed var: value} or a list),
            "dec": [answer | None] * K (oldest first; answer = {control: key}, a key list or a joint int)}."""
    if isinstance(state, dict) and state.get("kind") in ("mz-1", "mz-1x"):
        return state
    if m.px is None:
        if isinstance(state, dict):
            if set(state) != set(m.var_names):
                raise ValueError(f"state must give exactly the vars {m.var_names}")
            s = tuple(int(state[n]) for n in m.var_names)
        else:
            s = tuple(int(x) for x in state)
        return m.view(s)
    obs = tuple(_obs_tuple(m, o) for o in state["obs"])
    dec = tuple(_joint_of_answer(m, a) for a in state.get("dec", ()))
    if len(obs) != m.window or len(dec) != m.K:
        raise ValueError(f"mz-1x state needs {m.window} obs and {m.K} dec entries")
    return {"kind": "mz-1x", "obs": obs, "dec": dec}


def _answer_of_joint(m: Machine, j: int) -> dict:
    from nagi.burst2._rt.bv2n.zoo import render as R  # noqa: PLC0415

    return R.joint_to_answer(m.program, int(j))


def _decide(m: Machine, view: dict, options: dict, t0: float, read_ms: float) -> dict:
    options = options or {}
    unknown = set(options) - set(_SEARCH_OPTS) - set(_STREAM_OPTS)
    if unknown:
        raise ValueError(f"unknown options {sorted(unknown)}")
    opts = {k: v for k, v in options.items() if k in _SEARCH_OPTS}
    opts["tie"], opts["rng"], replayable = stream(options)
    j, st = VS.search(m, view, history=None, **opts)
    A = st["acceptable"]
    if st.get("gated") and st.get("core_prior_A") is not None:
        pj = dict(zip(A, st["core_prior_A"]))
    else:
        pj = {a: 1.0 / len(A) for a in A}
    probs = {name: {} for name in m.ctl_names}
    for a, p in pj.items():
        ans = _answer_of_joint(m, a)
        for name, key in ans.items():
            probs[name][key] = probs[name].get(key, 0.0) + p
    from nagi.burst2._rt.bv2n.zoo import render as R  # noqa: PLC0415

    for name, keys, _v in R.control_options(m.program):  # every offered option gets a probability (0 if outside A)
        probs[name] = {k: float(probs[name].get(k, 0.0)) for k in keys}
    st = dict(st)
    st.update({"read_ms": read_ms, "total_ms": (time.perf_counter() - t0) * 1e3, "machine_id": m.machine_id,
               "read_via": getattr(m, "read_via", "structured"), "tie": opts["tie"], "replayable": replayable})
    return {"choice": _answer_of_joint(m, j), "joint": int(j), "probabilities": probs,
            "joint_probabilities": {int(a): float(p) for a, p in sorted(pj.items())}, "stats": st}


def operate(rules_text: str, state=None, options: dict | None = None) -> dict:
    """Text path (module doc). ``rules_text`` = a served request (then ``state`` must be None) or a rulebook text."""
    t0 = time.perf_counter()
    from nagi.burst2._rt.v2g import games  # noqa: PLC0415

    g = games.match_request(rules_text) if state is None else None
    if g is not None:
        return g.operate_request(rules_text, options or {}, t0)
    if "\nSTATE:\nRULES:\n" in rules_text:
        if state is not None:
            raise ValueError("a full request already carries the state")
        rd = reader.read_request(rules_text)
        m, view = rd.machine, rd.view
    else:
        m = reader.read_rules(rules_text)
        if getattr(m, "kind", "zoo") != "zoo":
            return m.operate(state, options or {}, t0)
        if state is None:
            raise ValueError("rules text needs a state")
        view = _view_from_state(m, state)
    read_ms = (time.perf_counter() - t0) * 1e3
    return _decide(m, view, options, t0, read_ms)


def operate_structured(spec, view, options: dict | None = None) -> dict:
    """Structured path: canonical program / mz-1x dict (or a Machine) + client view. Same decision as the text path.
    Arena games without a search pack: ``spec`` = "rr" | "booster" and ``view`` = the runner's structured view dict
    (bv2n view_dict of the ClientView), decided by the core head (v2g.games.arena_core)."""
    t0 = time.perf_counter()
    if isinstance(spec, str):
        from nagi.burst2._rt.v2g.games import arena_core  # noqa: PLC0415

        return arena_core.CoreGameMachine(spec).operate(view, options or {}, t0)
    m = Machine.from_program(spec.spec if isinstance(spec, Machine) else spec)
    m.read_via = "structured"
    read_ms = (time.perf_counter() - t0) * 1e3
    return _decide(m, _view_from_state(m, view), options, t0, read_ms)

