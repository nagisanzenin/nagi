"""Scalar reference interpreter for mz-1 programs (docs/machine_zoo/SPEC.md §2-§4, §7 goal violation).

Every function takes a program dict (validated on first use and compiled; the compiled form is cached by object
identity, so do not mutate a program after passing it here) or an already compiled ``Prog``.

    start_states(p) / start_set(p)   start set in itertools.product order (SPEC §3)
    rand_outcomes(p)                 [(w, prob)] in listed order; [(0, 1.0)] when rand is null
    draw_w(p, u)                     SPEC §4.1: value of the first outcome i with u*W < c_i (float product)
    decode_joint(j), joint_mask(p), commands(p, j)
    tick(p, state, j, w)             -> (next_state, outcome)   one deterministic tick given the random VALUE w
    step(p, state, j, u)             -> (next_state, reward, done, outcome)   SPEC §4 given the uniform u
    step_dist(p, state, j)           -> [(prob, next_state, reward, outcome)] one entry per rand outcome
    goal_violation(p, state), pred_violation(pred, state, p)   SPEC §7

At an out-of-range crash the returned next_state is x as far as computed: the failing assignment is NOT applied
(AMBIGUITIES A1-2).
"""

from __future__ import annotations

import itertools

import numpy as np

from nagi.burst2._rt.machine_zoo import dsl

N_SLOTS = 3
N_OPT = 3
N_JOINT = 27
KEEP_JOINT = 13
TOL = 1e-6
GAMMA = 0.99
MAX_STEPS = 100
STATE_BUDGET = 60_000
RUNNING, SUCCESS, CRASH = "running", "success", "crash"
OUTCOMES = (RUNNING, SUCCESS, CRASH)
REWARD = {RUNNING: -1.0, CRASH: -200.0, SUCCESS: 49.0}
OPS = dsl.OPS
OP_CODE = {op: i for i, op in enumerate(OPS)}  # 0 <=, 1 >=, 2 ==, 3 !=, 4 <, 5 >


def decode_joint(j: int) -> tuple[int, int, int]:
    j = int(j)
    if not 0 <= j < N_JOINT:
        raise ValueError(f"joint index {j} outside 0..26")
    return (j // 9, (j // 3) % 3, j % 3)


def joint_index(o0: int, o1: int, o2: int) -> int:
    return int(o0) * 9 + int(o1) * 3 + int(o2)


class Prog:
    """Compiled program. EXPR -> (k, ((coef, kind, idx), ...)); PRED -> (is_all, (item, ...)) with
    item = (0, expr, opcode, c) for a comparison or (1, pred) for a nested PRED."""

    def __init__(self, program: dict):
        dsl.validate(program)
        p = dsl.canonicalize(program)
        self.program = p
        self.var_names = [v["name"] for v in p["vars"]]
        self.ctl_names = [c["name"] for c in p["controls"]]
        self.vidx = {n: i for i, n in enumerate(self.var_names)}
        self.cidx = {n: i for i, n in enumerate(self.ctl_names)}
        self.nv, self.nc = len(self.var_names), len(self.ctl_names)
        self.lo = [v["lo"] for v in p["vars"]]
        self.hi = [v["hi"] for v in p["vars"]]
        self.oob_crash = [v["oob"] == "crash" for v in p["vars"]]
        self.start = [tuple(s) for s in itertools.product(*[v["init"] for v in p["vars"]])]
        self.opts = [list(c["opts"]) for c in p["controls"]]
        if p["rand"] is None:
            self.has_rand = False
            self.w_vals, self.w_weights, self.W = [0], [1], 1
        else:
            self.has_rand = True
            self.w_vals = [v for v, _w in p["rand"]]
            self.w_weights = [w for _v, w in p["rand"]]
            self.W = sum(self.w_weights)
        self.cum = list(itertools.accumulate(self.w_weights))
        self.w_probs = [w / self.W for w in self.w_weights]
        self.rules = [
            (self.vidx[r["set"]], self.cexpr(r["to"]), self.cpred(r["if"]) if "if" in r else None) for r in p["rules"]
        ]
        self.crash = [self.cpred(q) for q in p["crash"]]
        self.goal = self.cpred(p["goal"])
        # joints
        mask = np.zeros(N_JOINT, dtype=bool)
        self.cmds: dict[int, tuple] = {}
        for j in range(N_JOINT):
            o = decode_joint(j)
            ok = all(o[s] == 1 for s in range(self.nc, N_SLOTS)) and all(
                self.opts[s][o[s]] is not None for s in range(self.nc)
            )
            if ok:
                mask[j] = True
                self.cmds[j] = tuple(self.opts[s][o[s]] for s in range(self.nc))
        self.joint_mask = mask
        self.valid_joints = [int(j) for j in np.flatnonzero(mask)]

    def catom(self, a: str) -> tuple[int, int]:
        kind, name = dsl.parse_atom(a)
        if kind in (dsl.K_VAR, dsl.K_ABS, dsl.K_SGN):
            return kind, self.vidx[name]
        if kind in (dsl.K_CMD, dsl.K_ABSCMD):
            return kind, self.cidx[name]
        return kind, 0

    def cexpr(self, e: dict):
        return (e["k"], tuple((c,) + self.catom(a) for c, a in e["t"]))

    def cpred(self, p: dict):
        ((kind, items),) = p.items()
        out = []
        for it in items:
            if isinstance(it, dict):
                out.append((1, self.cpred(it)))
            else:
                out.append((0, self.cexpr(it[0]), OP_CODE[it[1]], it[2]))
        return (kind == "all", tuple(out))


_CACHE: dict[int, tuple[dict, Prog]] = {}


def compile_program(program) -> Prog:
    """Compiled form of ``program`` (cached by object identity; at most 256 entries)."""
    if isinstance(program, Prog):
        return program
    hit = _CACHE.get(id(program))
    if hit is not None and hit[0] is program:
        return hit[1]
    prog = Prog(program)
    if len(_CACHE) >= 256:
        _CACHE.clear()
    _CACHE[id(program)] = (program, prog)
    return prog


# ---------------------------------------------------------------------------------------------- evaluation


def _ev(e, x, cmd, w) -> int:
    s, terms = e
    for c, kind, i in terms:
        if kind == 0:
            v = x[i]
        elif kind == 1:
            v = abs(x[i])
        elif kind == 2:
            v = (x[i] > 0) - (x[i] < 0)
        elif kind == 3:
            v = cmd[i]
        elif kind == 4:
            v = abs(cmd[i])
        else:
            v = w
        s += c * v
    return s


def _cmp(v: int, op: int, c: int) -> bool:
    if op == 0:
        return v <= c
    if op == 1:
        return v >= c
    if op == 2:
        return v == c
    if op == 3:
        return v != c
    if op == 4:
        return v < c
    return v > c


def _pt(p, x, cmd, w) -> bool:
    is_all, items = p
    for it in items:
        r = _pt(it[1], x, cmd, w) if it[0] == 1 else _cmp(_ev(it[1], x, cmd, w), it[2], it[3])
        if is_all and not r:
            return False
        if not is_all and r:
            return True
    return is_all


def _viol(p, x) -> int:
    """SPEC §7 goal violation of a compiled PRED on x (var atoms only)."""
    is_all, items = p
    vals = []
    for it in items:
        if it[0] == 1:
            vals.append(_viol(it[1], x))
            continue
        e = _ev(it[1], x, (), 0)
        op, c = it[2], it[3]
        if op == 0:
            v = max(0, e - c)
        elif op == 4:
            v = max(0, e - c + 1)
        elif op == 1:
            v = max(0, c - e)
        elif op == 5:
            v = max(0, c - e + 1)
        elif op == 2:
            v = abs(e - c)
        else:
            v = 1 if e == c else 0
        vals.append(v)
    return sum(vals) if is_all else min(vals)


# ---------------------------------------------------------------------------------------------- public API


def start_states(program) -> list[tuple]:
    """SPEC §3 start set, itertools.product order."""
    return list(compile_program(program).start)


start_set = start_states


def joint_mask(program) -> np.ndarray:
    return compile_program(program).joint_mask.copy()


def valid_joints(program) -> list[int]:
    return list(compile_program(program).valid_joints)


def commands(program, j: int) -> tuple:
    """Command values of joint j (SPEC §4.2); raises ValueError for an invalid joint."""
    prog = compile_program(program)
    j = int(j)
    if j not in prog.cmds:
        raise ValueError(f"invalid joint {j} {decode_joint(j)} for this program")
    return prog.cmds[j]


def rand_outcomes(program) -> list[tuple[int, float]]:
    """[(w, prob)] in listed order; [(0, 1.0)] when rand is null."""
    prog = compile_program(program)
    return list(zip(prog.w_vals, prog.w_probs))


def draw_w(program, u: float) -> int:
    """SPEC §4.1: w = value of the first outcome i with u*W < c_i (IEEE double product; AMBIGUITIES A1-1)."""
    prog = compile_program(program)
    if not prog.has_rand:
        return 0
    uW = u * prog.W
    for v, c in zip(prog.w_vals, prog.cum):
        if uW < c:
            return v
    raise ValueError(f"u = {u!r} outside [0, 1)")


def _tick(prog: Prog, state, cmd, w) -> tuple[tuple, str]:
    x = list(state)
    lo, hi, oc = prog.lo, prog.hi, prog.oob_crash
    for t, e, g in prog.rules:
        if g is None or _pt(g, x, cmd, w):
            val = _ev(e, x, cmd, w)
            if lo[t] <= val <= hi[t]:
                x[t] = val
            elif oc[t]:
                return tuple(x), CRASH
            else:
                x[t] = lo[t] if val < lo[t] else hi[t]
    for q in prog.crash:
        if _pt(q, x, cmd, w):
            return tuple(x), CRASH
    if _pt(prog.goal, x, cmd, w):
        return tuple(x), SUCCESS
    return tuple(x), RUNNING


def _check_state(prog: Prog, state) -> None:
    if len(state) != prog.nv:
        raise ValueError(f"state has {len(state)} values, program has {prog.nv} vars")
    for i, v in enumerate(state):
        if not prog.lo[i] <= v <= prog.hi[i]:
            raise ValueError(f"state value {prog.var_names[i]}={v} outside [{prog.lo[i]}, {prog.hi[i]}]")


def tick(program, state, j: int, w: int) -> tuple[tuple, str]:
    """One deterministic tick (SPEC §4.2-4.4) given the random VALUE w -> (next_state, outcome)."""
    prog = compile_program(program)
    _check_state(prog, state)
    return _tick(prog, state, commands(prog, j), int(w))


def step(program, state, j: int, u: float) -> tuple[tuple, float, bool, str]:
    """SPEC §4 tick given the uniform draw u in [0, 1) -> (next_state, reward, done, outcome)."""
    prog = compile_program(program)
    _check_state(prog, state)
    cmd = commands(prog, j)
    nxt, out = _tick(prog, state, cmd, draw_w(prog, u))
    return nxt, REWARD[out], out != RUNNING, out


def step_dist(program, state, j: int) -> list[tuple[float, tuple, float, str]]:
    """[(prob, next_state, reward, outcome)] one entry per rand outcome in listed order (prob = weight / W);
    one entry with prob 1.0 when rand is null. Terminal entries carry the as-far-as-computed state."""
    prog = compile_program(program)
    _check_state(prog, state)
    cmd = commands(prog, j)
    out = []
    for w, p in zip(prog.w_vals, prog.w_probs):
        nxt, oc = _tick(prog, state, cmd, w)
        out.append((p, nxt, REWARD[oc], oc))
    return out


def goal_violation(program, state) -> int:
    """SPEC §7 goal violation of the goal PRED on ``state``."""
    prog = compile_program(program)
    return _viol(prog.goal, list(state))


def pred_violation(pred: dict, state, program) -> int:
    """SPEC §7 violation of an arbitrary var-only PRED (dict) on ``state`` of ``program``."""
    prog = compile_program(program)
    return _viol(prog.cpred(pred), list(state))
