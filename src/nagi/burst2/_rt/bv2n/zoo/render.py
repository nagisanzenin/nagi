"""Zoo machine + state -> Burst chord request text (bv2n-zoo-request-v0); parser; exact per-slot targets.

REQUEST (served bytes = nagi.render.render_chord_prompt, the Burst V1 chord layout, docs/chord/INTERFACE.md):
    state text  = "RULES:\\n<machine_zoo.dsl.render(program)>\\nTICK: <fixed tick-semantics line>\\n"
                  "OBJECTIVE: <fixed objective line>\\n\\n"
                  "OBSERVATION:\\n<var> = <int>, ...\\n\\n"
                  "CONTROLS (set together each tick): <c1> = dec | keep | inc; <c2> = ...."
                  (the CONTROLS line is the released Burst `state_controls_line`; nagi.burst reads the declared
                  control order from it; options listed = the control's non-null options in DEC, KEEP, INC order)
    questions   = {control: {"type": "choice", "instructions": "Choose the <control> setting.",
                             "criteria": {"dec": "@c = v", "keep": "@c = v", "inc": "@c = v"}}}  (non-null only)
    slot order  = the program's declared control order (canonical; Burst variant A); `order` may permute it.
Joint mapping: control i of the program is SPEC digit o_i (0 DEC, 1 KEEP, 2 INC); absent digits are KEEP;
joint j = o0*9 + o1*3 + o2 (machine_zoo.interp.joint_index).

The step counter is NOT rendered: the teacher label (V-infinity, discounted) is a function of (program, state) only,
so the request text determines the label exactly (contract rule: teacher = function of the client view).

TARGETS (handbook R2.13 / R1.13 / R1.21; derivation in docs/burst_v2_next/lanes/zoo-render.md §2):
    Q(j) exact (teacher.solve; -inf at invalid joints), best = max Q, X* = {j : Q(j) >= best - TOL}, TOL = 1e-6.
    a* = the lowest-index joint of X* = the first optimal joint in (control, option) product order with options in
         semantic order DEC < KEEP < INC (= machine_zoo.evaluate "oracle").
    M_k(o) = max{Q(j) : digit_k(j) = o}                      raw max-marginal of slot k
    top_k  = {o : M_k(o) >= best - TOL} = projection of X* on slot k (Lemma: o in top_k iff o is in some optimal joint)
    tie-broken  M~_k(o) = best - T*ln(RHO) for o in top_k, o != a*_k; else M_k(o)
    target_k = softmax(M~_k / T) (0 at -inf)                  PRIMARY training target
    target_maxmarginal_k = softmax(M_k / T)                    raw (no tie rule)
    target_hard_k = one-hot(a*_k);  target_summarg_k = marginal of the uniform distribution on X*  (diagnostic only:
    a sum-marginal can put its mode on a non-optimal combination when X* is not a product set, R2.13).
    Per-slot argmax of target_k composes to a* (optimal) on every state, whether X* is a product set or not.
"""
from __future__ import annotations

import math
import re

import numpy as np

from nagi.burst2._rt.nagi_r.render import render_chord_prompt

VERSION = "bv2n-zoo-request-v1"   # v1 = v0 + the TICK line (ZOO_NEW_SPEC.md Amendment 1, 2026-10-11; labels unchanged)
OPTION_KEYS = ("dec", "keep", "inc")          # SPEC digit 0, 1, 2
INSTRUCTION = "Choose the {c} setting."       # = longcommit.rows.INSTRUCTION (released Burst chord layout)
OBJECTIVE = ("OBJECTIVE: every tick costs 1; reaching the goal ends the episode and earns 49; a crash ends it and "
             "costs 200; rewards are discounted by 0.99 per tick. Choose the controls that maximize the expected "
             "discounted total.")
TICK = ("TICK: the rules run top to bottom, each reading the results of the rules above it; a var that leaves a "
        "range marked 'out of range: crash' crashes at once; then the crash conditions are checked before the goal "
        "(a crash wins over the goal on the same tick).")   # mz-1 SPEC §4.3-4.4 stated in the served text (Amendment 1)
CONTROLS_PREFIX = "CONTROLS (set together each tick): "
N_JOINT = 27
TOL = 1e-6
TEMPERATURE = 0.25     # value units (reward points); one extra tick of delay ~ 0.8-1.5 points -> weight e^-3..e^-6
RHO = 4.0              # tie ratio: demoted tied optimum = best - T ln 4; TOL << T ln RHO = 0.347
MAX_TOKENS = 1024      # serving / training chord cap (burst_v2.prompt.CHORD_CAP)


# ----------------------------------------------------------------------------- joints

def joint_of_digits(d) -> int:
    d = list(d) + [1] * (3 - len(d))
    return int(d[0]) * 9 + int(d[1]) * 3 + int(d[2])


def digits_of_joint(j: int) -> tuple[int, int, int]:
    j = int(j)
    if not 0 <= j < N_JOINT:
        raise ValueError(f"joint {j} outside 0..26")
    return (j // 9, (j // 3) % 3, j % 3)


def control_options(program) -> list[tuple[str, list[str], dict]]:
    """[(control name, option keys (non-null, DEC/KEEP/INC order), {key: command value})] in declared order."""
    out = []
    for c in program["controls"]:
        keys = [k for k, v in zip(OPTION_KEYS, c["opts"]) if v is not None]
        if len(keys) < 2:
            raise ValueError(f"control {c['name']} has < 2 options (Burst slots need 2..26)")
        out.append((c["name"], keys, {k: v for k, v in zip(OPTION_KEYS, c["opts"]) if v is not None}))
    return out


def joint_to_answer(program, j: int) -> dict:
    """joint index -> {control: option key} (declared order)."""
    d = digits_of_joint(j)
    ctl = control_options(program)
    for i in range(len(ctl), 3):
        if d[i] != 1:
            raise ValueError(f"joint {j} moves an absent control")
    out = {}
    for i, (name, keys, _v) in enumerate(ctl):
        k = OPTION_KEYS[d[i]]
        if k not in keys:
            raise ValueError(f"joint {j}: option {k} is not available for {name}")
        out[name] = k
    return out


def answer_to_joint(program, answer) -> int:
    """{control: key} | [key per declared control] | int joint -> joint index (validated)."""
    ctl = control_options(program)
    if isinstance(answer, (int, np.integer)):
        joint_to_answer(program, int(answer))
        return int(answer)
    if isinstance(answer, dict):
        if set(answer) != {n for n, _k, _v in ctl}:
            raise ValueError(f"answer must name exactly the controls {[n for n, _k, _v in ctl]}")
        keys = [answer[n] for n, _k, _v in ctl]
    else:
        keys = list(answer)
        if len(keys) != len(ctl):
            raise ValueError("answer list length != number of controls")
    d = []
    for (name, opts, _v), k in zip(ctl, keys):
        if k not in opts:
            raise ValueError(f"{name}: invalid option {k!r}")
        d.append(OPTION_KEYS.index(k))
    return joint_of_digits(d)


# ----------------------------------------------------------------------------- render / parse

def observation_text(program, state) -> str:
    names = [v["name"] for v in program["vars"]]
    if len(state) != len(names):
        raise ValueError("state length != number of vars")
    return ", ".join(f"{n} = {int(x)}" for n, x in zip(names, state))


def controls_line(program) -> str:
    return CONTROLS_PREFIX + "; ".join(f"{n} = {' | '.join(k)}" for n, k, _v in control_options(program)) + "."


def questions(program) -> dict:
    return {n: {"type": "choice", "instructions": INSTRUCTION.format(c=n),
                "criteria": {k: f"@{n} = {v[k]}" for k in keys}} for n, keys, v in control_options(program)}


def state_text(program, state, rules_text: str | None = None, observation: str | None = None) -> str:
    """STATE block. `rules_text` / `observation` override the mz-1 defaults (extension hook for lane zoo-new:
    mz-1x families pass their own rulebook text and observation/history text; both must be blank-marker free)."""
    from nagi.burst2._rt.machine_zoo import dsl  # noqa: PLC0415
    rules = dsl.render(program) if rules_text is None else rules_text
    obs = observation_text(program, state) if observation is None else observation
    return f"RULES:\n{rules.rstrip(chr(10))}\n{TICK}\n{OBJECTIVE}\n\nOBSERVATION:\n{obs}\n\n{controls_line(program)}"


def render_request(program, state, order: list[str] | None = None, rules_text: str | None = None,
                   observation: str | None = None) -> str:
    """The served request text (chord prompt) for one decision. Deterministic bytes."""
    qs = questions(program)
    prompt, _slots = render_chord_prompt({"state": state_text(program, state, rules_text, observation),
                                          "questions": qs}, order)
    return prompt


def request_parts(program, state, order=None, rules_text=None, observation=None) -> tuple[str, dict, list]:
    """(state text, questions, slots) = the inputs nagi.chord.sdk_encode_chord / system_one(mode='chord') take."""
    st = state_text(program, state, rules_text, observation)
    qs = questions(program)
    if order is not None:
        qs = {q: qs[q] for q in order}
    _p, slots = render_chord_prompt({"state": st, "questions": qs})
    return st, qs, slots


_STATE_RE = re.compile(r"\nSTATE:\nRULES:\n(.*?)\n" + re.escape(TICK) + r"\n" + re.escape(OBJECTIVE) + r"\n\nOBSERVATION:\n(.*?)\n\n"
                       + re.escape(CONTROLS_PREFIX) + r"[^\n]*\n\n" + re.escape("CONTROLS (choose all at the same time):")
                       + r"\n(.*?)\n\nANSWER:\n", re.S)
_SLOT_RE = re.compile(r"^\[(\d+)\] ([a-z][a-z0-9_]*): ", re.M)


def parse_request(text: str) -> tuple[dict, tuple, list[str]]:
    """request text -> (canonical program, state tuple, slot order). Raises unless render(parse(text)) == text."""
    from nagi.burst2._rt.machine_zoo import dsl  # noqa: PLC0415
    m = _STATE_RE.search(text)
    if m is None:
        raise ValueError("not a bv2n Zoo request")
    program = dsl.parse(m.group(1) + "\n")
    names = [v["name"] for v in program["vars"]]
    vals = {}
    for part in m.group(2).split(", "):
        k, v = part.split(" = ")
        vals[k] = int(v)
    if list(vals) != names:
        raise ValueError("observation vars != rulebook vars")
    state = tuple(vals[n] for n in names)
    order = [g for _i, g in _SLOT_RE.findall(m.group(3))]
    if render_request(program, state, order) != text:
        raise ValueError("request does not round-trip")
    return program, state, order


# ----------------------------------------------------------------------------- exact targets

def _softmax(vals: list[float], best: float, temperature: float) -> list[float]:
    w = [0.0 if v == -math.inf else math.exp((v - best) / temperature) for v in vals]
    z = math.fsum(w)
    return [x / z for x in w]


def slot_targets(program, q, temperature: float = TEMPERATURE, rho: float = RHO, tol: float = TOL) -> dict:
    """Exact per-slot labels from the 27-vector Q (−inf at invalid joints). See module doc."""
    q = np.asarray(q, dtype=np.float64)
    ctl = control_options(program)
    valid = np.isfinite(q)
    best = float(q[valid].max())
    acc = [j for j in range(N_JOINT) if valid[j] and q[j] >= best - tol]
    a_star = acc[0]
    da = digits_of_joint(a_star)
    slots = []
    product = 1
    for k, (name, keys, _v) in enumerate(ctl):
        m = []
        for key in keys:
            o = OPTION_KEYS.index(key)
            vs = [q[j] for j in range(N_JOINT) if valid[j] and digits_of_joint(j)[k] == o]
            m.append(float(max(vs)) if vs else -math.inf)
        top = [key for key, v in zip(keys, m) if v >= best - tol]
        tb = [best - temperature * math.log(rho) if (key in top and key != OPTION_KEYS[da[k]]) else v
              for key, v in zip(keys, m)]
        cnt = [sum(digits_of_joint(j)[k] == OPTION_KEYS.index(key) for j in acc) for key in keys]
        product *= len(top)
        slots.append({
            "qid": name, "keys": list(keys), "canonical": OPTION_KEYS[da[k]],
            "gold": keys.index(OPTION_KEYS[da[k]]),
            "target": _softmax(tb, best, temperature),
            "target_maxmarginal": _softmax(m, best, temperature),
            "target_hard": [float(key == OPTION_KEYS[da[k]]) for key in keys],
            "target_summarg": [c / len(acc) for c in cnt],
            "values": [None if v == -math.inf else v for v in m],
            "acceptable": top, "tie_broken": len(top) > 1,
        })
    nonacc = [float(q[j]) for j in range(N_JOINT) if valid[j] and q[j] < best - tol]
    summarg_joint = joint_of_digits([OPTION_KEYS.index(s["keys"][int(np.argmax(s["target_summarg"]))])
                                     for s in slots])
    return {
        "a_star": a_star, "a_star_answer": joint_to_answer(program, a_star),
        "acceptable_joints": acc, "best": best, "slots": slots,
        "n_valid": int(valid.sum()), "n_acceptable": len(acc),
        "gap": (best - max(nonacc)) if nonacc else None,          # regret of the best non-optimal joint
        "worst_regret": (best - min(nonacc)) if nonacc else 0.0,
        "product_set": product == len(acc),                       # X* = product of the per-slot top sets
        "summarg_argmax_optimal": summarg_joint in acc,           # diagnostic: lowest-index sum-marginal argmax
        "temperature": temperature, "rho": rho, "tol": tol,
    }


def targets_from_joint_set(program, joints) -> dict:
    """Labels when only an optimal joint SET is known (no Q): Q := 0 on the set, −inf elsewhere (raw max-marginals
    then equal 0 on each slot's projection). Same a* / tie rule; soft weights for non-optimal options are 0."""
    q = np.full(N_JOINT, -math.inf)
    for j in joints:
        q[int(j)] = 0.0
    return slot_targets(program, q)
