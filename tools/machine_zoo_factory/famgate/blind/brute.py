# SPDX-License-Identifier: Apache-2.0
"""Independent checker for the base language mz-1: a deliberately simple, literal implementation of the language
definition (docs/DSL_REFERENCE.md §1-§3). It never imports the engine under nagi.burst2._rt; readability and literal
faithfulness come first, speed does not matter.

Value solver: exact policy iteration (sparse direct solve of (I - gamma P_pi) V = R_pi), then Bellman polishing
sweeps from that fixed point until the residual max_s |V(s) - max_j Q(s, j)| is <= 1e-11.

Section marks (§) in comments follow the research language spec this checker was written from.
Vendored from the research test suite unchanged except this docstring and two comments.
"""
from __future__ import annotations

import itertools
import re
from collections import deque
from fractions import Fraction

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

# language constants (re-declared here, never imported from the engine)
N_SLOTS = 3
N_OPT = 3
N_JOINT = 27
KEEP_JOINT = 13
TOL = 1e-6
GAMMA = 0.99
MAX_STEPS = 100

R_RUNNING = -1.0
R_CRASH = -200.0
R_SUCCESS = 49.0

WEAK_CRASH_COST = 10 ** 6
WEAK_SUCCESS_COST = -1
WEAK_TIE = 1e-9

PROGRAM_KEYS = {"dsl", "vars", "controls", "rand", "rules", "crash", "goal"}
VAR_KEYS = {"name", "lo", "hi", "oob", "init"}
CONTROL_KEYS = {"name", "opts"}
OPS = ("<=", ">=", "==", "!=", "<", ">")
NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,15}")


def joint_index(o0: int, o1: int, o2: int) -> int:
    return o0 * 9 + o1 * 3 + o2


def joint_options(j: int) -> tuple[int, int, int]:
    return (j // 9, (j // 3) % 3, j % 3)


def sgn(x: int) -> int:
    return (x > 0) - (x < 0)


def is_int(v) -> bool:
    """A JSON integer: Python int but not bool."""
    return isinstance(v, int) and not isinstance(v, bool)


class InvalidProgram(ValueError):
    pass


# --------------------------------------------------------------------------------------------------------------
# §1 validation
# --------------------------------------------------------------------------------------------------------------

def _need(cond, msg):
    if not cond:
        raise InvalidProgram(msg)


def _atoms_allowed(program: dict, context: str) -> set:
    """Allowed atom strings. context 'rule' (rule EXPRs and guards) or 'state' (goal and crash)."""
    var_names = [v["name"] for v in program["vars"]]
    atoms = set(var_names)
    atoms |= {f"abs({x})" for x in var_names}
    atoms |= {f"sgn({x})" for x in var_names}
    if context == "rule":
        ctl_names = [c["name"] for c in program["controls"]]
        atoms |= {f"@{c}" for c in ctl_names}
        atoms |= {f"abs(@{c})" for c in ctl_names}
        if program["rand"] is not None:
            atoms.add("$w")
    return atoms


def _check_expr(e, atoms: set):
    # Ruling (2026-10-10, applied to both implementations): the §1 rule 5 limits (0..6 terms, coef != 0,
    # |coef| <= 10) apply to the CANONICAL form
    # (equal atoms merged, zero coefficients dropped), so validity never changes under canonicalization. The
    # written terms must still be well-formed: [int coef, allowed atom]. Frozen original: 0 <= len(written t) <= 6
    # and every written coef int, != 0, |coef| <= 10.
    _need(isinstance(e, dict) and set(e.keys()) == {"t", "k"}, "EXPR must be {t, k}")
    t = e["t"]
    _need(isinstance(t, (list, tuple)), "EXPR terms must be a list")
    merged = {}
    for term in t:
        _need(isinstance(term, (list, tuple)) and len(term) == 2, "term = [coef, atom]")
        coef, atom = term
        _need(is_int(coef), "coef int")
        _need(isinstance(atom, str) and atom in atoms, f"atom {atom!r} not allowed here")
        merged[atom] = merged.get(atom, 0) + coef
    canon = {a: c for a, c in merged.items() if c != 0}
    _need(len(canon) <= 6, "EXPR 0..6 terms (canonical form)")
    _need(all(abs(c) <= 10 for c in canon.values()), "|coef| <= 10 (canonical form)")
    _need(is_int(e["k"]) and abs(e["k"]) <= 1000, "|k| <= 1000")


def _check_pred(p, atoms: set, depth: int) -> int:
    """Validate a PRED at nesting depth `depth` (1 = top). Returns the number of comparison items in it."""
    _need(depth <= 2, "PRED nesting depth <= 2")
    _need(isinstance(p, dict) and len(p) == 1 and next(iter(p)) in ("all", "any"), "PRED = {all|any: [...]}")
    items = p[next(iter(p))]
    _need(isinstance(items, (list, tuple)) and 1 <= len(items) <= 6, "PRED has 1..6 items")
    n_cmp = 0
    for it in items:
        if isinstance(it, dict):
            n_cmp += _check_pred(it, atoms, depth + 1)
        else:
            _need(isinstance(it, (list, tuple)) and len(it) == 3, "ITEM = [EXPR, op, int]")
            expr, op, c = it
            _check_expr(expr, atoms)
            _need(op in OPS, f"op {op!r}")
            _need(is_int(c) and abs(c) <= 1000, "comparison int |c| <= 1000")
            n_cmp += 1
    return n_cmp


def validate(program: dict) -> None:
    """Raise InvalidProgram on any violation of SPEC §1 validity rules 1-8."""
    _need(isinstance(program, dict) and set(program.keys()) == PROGRAM_KEYS, "exactly the seven §1 keys")
    _need(program["dsl"] == "mz-1", "dsl must be mz-1")

    vars_ = program["vars"]
    _need(isinstance(vars_, (list, tuple)) and 1 <= len(vars_) <= 10, "1..10 vars")
    controls = program["controls"]
    _need(isinstance(controls, (list, tuple)) and 1 <= len(controls) <= 3, "1..3 controls")

    # rule 1: names
    names = []
    for v in vars_:
        _need(isinstance(v, dict) and set(v.keys()) == VAR_KEYS, "var keys")
        names.append(v["name"])
    for c in controls:
        _need(isinstance(c, dict) and set(c.keys()) == CONTROL_KEYS, "control keys")
        names.append(c["name"])
    for nm in names:
        _need(isinstance(nm, str) and NAME_RE.fullmatch(nm) is not None, f"bad name {nm!r}")
    _need(len(set(names)) == len(names), "names distinct (one namespace)")

    # rule 2: vars
    size_product = 1
    init_product = 1
    for v in vars_:
        lo, hi = v["lo"], v["hi"]
        _need(is_int(lo) and is_int(hi), "lo/hi ints")
        _need(-1000 <= lo < hi <= 1000, "-1000 <= lo < hi <= 1000")
        _need(hi - lo <= 400, "hi - lo <= 400")
        _need(v["oob"] in ("clamp", "crash"), "oob clamp|crash")
        init = v["init"]
        _need(isinstance(init, (list, tuple)) and len(init) >= 1, "init non-empty")
        _need(all(is_int(a) for a in init), "init ints")
        _need(all(init[i] < init[i + 1] for i in range(len(init) - 1)), "init strictly increasing")
        _need(all(lo <= a <= hi for a in init), "init within [lo, hi]")
        size_product *= hi - lo + 1
        init_product *= len(init)
    _need(size_product <= 2 ** 62, "product of ranges <= 2^62")
    _need(init_product <= 64, "product of len(init) <= 64")

    # rule 3: controls
    for c in controls:
        opts = c["opts"]
        _need(isinstance(opts, (list, tuple)) and len(opts) == 3, "opts has exactly 3 entries")
        _need(is_int(opts[1]), "opts[1] is an int")
        for k in (0, 2):
            _need(opts[k] is None or is_int(opts[k]), "opts[0], opts[2] int or null")
        vals = [o for o in opts if o is not None]
        _need(all(-10 <= o <= 10 for o in vals), "option ints in [-10, 10]")
        _need(len(set(vals)) == len(vals), "non-null option values distinct")

    # rule 4: rand
    rand = program["rand"]
    if rand is not None:
        _need(isinstance(rand, (list, tuple)) and 1 <= len(rand) <= 5, "rand 1..5 outcomes")
        for pair in rand:
            _need(isinstance(pair, (list, tuple)) and len(pair) == 2, "rand entry = [value, weight]")
            _need(is_int(pair[0]) and is_int(pair[1]), "rand ints")
            _need(-10 <= pair[0] <= 10, "rand value in [-10, 10]")
            _need(pair[1] >= 1, "rand weight >= 1")
        values = [pair[0] for pair in rand]
        _need(all(values[i] < values[i + 1] for i in range(len(values) - 1)), "rand values strictly increasing")
        _need(sum(pair[1] for pair in rand) <= 1000, "rand total weight <= 1000")

    # rules 5-7: rules, crash, goal
    rule_atoms = _atoms_allowed(program, "rule")
    state_atoms = _atoms_allowed(program, "state")
    var_names = {v["name"] for v in vars_}
    rules = program["rules"]
    _need(isinstance(rules, (list, tuple)) and 1 <= len(rules) <= 24, "1..24 rules")
    for r in rules:
        _need(isinstance(r, dict) and {"set", "to"} <= set(r.keys()) <= {"set", "to", "if"}, "rule keys")
        _need(r["set"] in var_names, "rule target must be a var")
        _check_expr(r["to"], rule_atoms)
        if "if" in r:
            _check_pred(r["if"], rule_atoms, 1)
    crash = program["crash"]
    _need(isinstance(crash, (list, tuple)) and 0 <= len(crash) <= 8, "0..8 crash predicates")
    n_items = 0
    for p in crash:
        n_items += _check_pred(p, state_atoms, 1)
    n_items += _check_pred(program["goal"], state_atoms, 1)
    _need(n_items <= 16, "total comparison items over goal + crash <= 16")

    # rule 8: no start state satisfies the goal or any crash predicate
    env_names = [v["name"] for v in vars_]
    for s in itertools.product(*[v["init"] for v in vars_]):
        env = Env(env_names, list(s), {}, 0)
        _need(not any(pred_true(p, env) for p in crash), f"start state {s} satisfies a crash predicate")
        _need(not pred_true(program["goal"], env), f"start state {s} satisfies the goal")


def is_valid(program) -> bool:
    try:
        validate(program)
    except InvalidProgram:
        return False
    except (KeyError, TypeError, AttributeError, StopIteration):
        # malformed shapes (missing keys inside sub-objects etc.) are invalid programs too
        return False
    return True


# --------------------------------------------------------------------------------------------------------------
# §1 canonicalize
# --------------------------------------------------------------------------------------------------------------

def _canon_expr(e: dict) -> dict:
    coef = {}
    for c, atom in e["t"]:
        coef[atom] = coef.get(atom, 0) + c
    terms = [[coef[a], a] for a in sorted(coef) if coef[a] != 0]
    return {"t": terms, "k": e["k"]}


def _canon_pred(p: dict) -> dict:
    key = next(iter(p))
    out = []
    for it in p[key]:
        if isinstance(it, dict):
            out.append(_canon_pred(it))
        else:
            out.append([_canon_expr(it[0]), it[1], it[2]])
    return {key: out}


def canonicalize(program: dict) -> dict:
    """§1: merge equal atoms, drop zero coefficients, sort terms by atom string; everything else as written."""
    rules = []
    for r in program["rules"]:
        nr = {"set": r["set"], "to": _canon_expr(r["to"])}
        if "if" in r:
            nr["if"] = _canon_pred(r["if"])
        rules.append(nr)
    return {
        "dsl": program["dsl"],
        "vars": [dict(v, init=list(v["init"])) for v in program["vars"]],
        "controls": [dict(c, opts=list(c["opts"])) for c in program["controls"]],
        "rand": None if program["rand"] is None else [list(p) for p in program["rand"]],
        "rules": rules,
        "crash": [_canon_pred(p) for p in program["crash"]],
        "goal": _canon_pred(program["goal"]),
    }


# --------------------------------------------------------------------------------------------------------------
# §2 values
# --------------------------------------------------------------------------------------------------------------

class Env:
    """What an atom can read: CURRENT var values x (mutable list), this tick's commands and this tick's w."""

    def __init__(self, var_names, x, commands, w):
        self.var_index = {nm: i for i, nm in enumerate(var_names)}
        self.x = x
        self.commands = commands  # control name -> command value
        self.w = w

    def atom(self, a: str) -> int:
        if a == "$w":
            return self.w
        if a.startswith("@"):
            return self.commands[a[1:]]
        if a.startswith("abs(") and a.endswith(")"):
            inner = a[4:-1]
            if inner.startswith("@"):
                return abs(self.commands[inner[1:]])
            return abs(self.x[self.var_index[inner]])
        if a.startswith("sgn(") and a.endswith(")"):
            return sgn(self.x[self.var_index[a[4:-1]]])
        return self.x[self.var_index[a]]


def eval_expr(e: dict, env: Env) -> int:
    total = e["k"]
    for coef, atom in e["t"]:
        total += coef * env.atom(atom)
    return total


def compare(a: int, op: str, b: int) -> bool:
    if op == "<=":
        return a <= b
    if op == ">=":
        return a >= b
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    if op == "<":
        return a < b
    if op == ">":
        return a > b
    raise ValueError(op)


def pred_true(p: dict, env: Env) -> bool:
    key = next(iter(p))
    results = []
    for it in p[key]:
        if isinstance(it, dict):
            results.append(pred_true(it, env))
        else:
            expr, op, c = it
            results.append(compare(eval_expr(expr, env), op, c))
    if key == "all":
        return all(results)
    return any(results)


# --------------------------------------------------------------------------------------------------------------
# §7 goal violation
# --------------------------------------------------------------------------------------------------------------

def violation(p: dict, env: Env) -> int:
    key = next(iter(p))
    vals = []
    for it in p[key]:
        if isinstance(it, dict):
            vals.append(violation(it, env))
            continue
        expr, op, c = it
        e = eval_expr(expr, env)
        if op == "<=":
            vals.append(max(0, e - c))
        elif op == "<":
            vals.append(max(0, e - c + 1))
        elif op == ">=":
            vals.append(max(0, c - e))
        elif op == ">":
            vals.append(max(0, c - e + 1))
        elif op == "==":
            vals.append(abs(e - c))
        elif op == "!=":
            vals.append(1 if e == c else 0)
        else:
            raise ValueError(op)
    if key == "all":
        return sum(vals)
    return min(vals)


# --------------------------------------------------------------------------------------------------------------
# The machine (§3 state/reset, §4 tick, §5 teacher, §7 weak bot)
# --------------------------------------------------------------------------------------------------------------

class BruteMachine:
    def __init__(self, program: dict):
        validate(program)
        self.program = program
        self.vars = program["vars"]
        self.var_names = [v["name"] for v in self.vars]
        self.var_index = {nm: i for i, nm in enumerate(self.var_names)}
        self.controls = program["controls"]
        self.rand = program["rand"]
        self.rules = program["rules"]
        self.crash = program["crash"]
        self.goal = program["goal"]
        self.joint_mask = np.array([self.joint_valid(j) for j in range(N_JOINT)], dtype=bool)
        self.valid_joints = [j for j in range(N_JOINT) if self.joint_mask[j]]
        self._solved = None

    # ---- §3 ------------------------------------------------------------------------------------------------
    def start_set(self) -> list[tuple]:
        return [tuple(s) for s in itertools.product(*[v["init"] for v in self.vars])]

    def reset(self, rng) -> tuple:
        starts = self.start_set()
        i = int(rng.integers(len(starts)))
        return starts[i]

    # ---- §4.2 commands -----------------------------------------------------------------------------------------
    def joint_valid(self, j: int) -> bool:
        if not (is_int(j) or isinstance(j, np.integer)) or not 0 <= int(j) < N_JOINT:
            return False
        opts = joint_options(int(j))
        for s in range(N_SLOTS):
            if s < len(self.controls):
                if self.controls[s]["opts"][opts[s]] is None:
                    return False
            elif opts[s] != 1:
                return False
        return True

    def commands(self, j: int) -> dict:
        if not self.joint_valid(j):
            raise ValueError(f"invalid joint {j}")
        opts = joint_options(int(j))
        return {c["name"]: c["opts"][opts[s]] for s, c in enumerate(self.controls)}

    # ---- §4.1 random draw ------------------------------------------------------------------------------------
    def w_of_u(self, u: float) -> int:
        if self.rand is None:
            return 0
        W = sum(weight for _, weight in self.rand)
        c = 0
        for value, weight in self.rand:
            c += weight
            if u * W < c:
                return value
        raise AssertionError(f"u={u!r} gave no outcome (u must be in [0, 1))")

    def outcomes(self) -> list[tuple[int, float]]:
        """[(w, p_w)] in listed order; one entry (0, 1.0) when rand is null."""
        if self.rand is None:
            return [(0, 1.0)]
        W = sum(weight for _, weight in self.rand)
        return [(value, weight / W) for value, weight in self.rand]

    def outcomes_exact(self) -> list[tuple[int, Fraction]]:
        if self.rand is None:
            return [(0, Fraction(1))]
        W = sum(weight for _, weight in self.rand)
        return [(value, Fraction(weight, W)) for value, weight in self.rand]

    # ---- §4.3-4.5 one tick given w -------------------------------------------------------------------------
    def tick_w(self, state: tuple, j: int, w: int) -> tuple[tuple, float, bool, str]:
        cmds = self.commands(j)  # raises on an invalid joint
        x = list(state)
        env = Env(self.var_names, x, cmds, w)
        for r in self.rules:
            if "if" in r and not pred_true(r["if"], env):
                continue
            val = eval_expr(r["to"], env)
            t = self.var_index[r["set"]]
            lo, hi = self.vars[t]["lo"], self.vars[t]["hi"]
            if lo <= val <= hi:
                x[t] = val
            elif self.vars[t]["oob"] == "crash":
                return tuple(x), R_CRASH, True, "crash"   # later rules are not executed; x[t] keeps its old value
            else:
                x[t] = min(max(val, lo), hi)
        if any(pred_true(p, env) for p in self.crash):
            return tuple(x), R_CRASH, True, "crash"
        if pred_true(self.goal, env):
            return tuple(x), R_SUCCESS, True, "success"
        return tuple(x), R_RUNNING, False, "running"

    def step_u(self, state: tuple, j: int, u: float) -> tuple[tuple, float, bool, str]:
        if not self.joint_valid(j):
            raise ValueError(f"invalid joint {j}")
        return self.tick_w(state, j, self.w_of_u(u))

    def step(self, state: tuple, j: int, rng) -> tuple[tuple, float, bool, str]:
        u = rng.random()  # exactly one draw per tick, always first
        return self.step_u(state, j, u)

    def step_dist(self, state: tuple, j: int) -> list[tuple[float, tuple, float, str]]:
        """[(p_w, next_state, reward, outcome)] per rand outcome, listed order (one entry if rand is null)."""
        out = []
        for w, p in self.outcomes():
            nxt, r, _done, outcome = self.tick_w(state, j, w)
            out.append((p, nxt, r, outcome))
        return out

    # ---- §5 teacher --------------------------------------------------------------------------------------------
    def reachable(self) -> list[tuple]:
        """Non-terminal states reachable from the start set (breadth-first, every valid j, every w)."""
        seen = set()
        order = []
        queue = deque()
        for s in self.start_set():
            if s not in seen:
                seen.add(s)
                order.append(s)
                queue.append(s)
        while queue:
            s = queue.popleft()
            for j in self.valid_joints:
                for _p, nxt, _r, outcome in self.step_dist(s, j):
                    if outcome == "running" and nxt not in seen:
                        seen.add(nxt)
                        order.append(nxt)
                        queue.append(nxt)
        return order

    def _build(self):
        S = self.reachable()
        index = {s: i for i, s in enumerate(S)}
        n = len(S)
        P = {}
        R = {}
        for j in self.valid_joints:
            rows, cols, data = [], [], []
            rj = np.zeros(n)
            for i, s in enumerate(S):
                for p, nxt, r, outcome in self.step_dist(s, j):
                    rj[i] += p * r
                    if outcome == "running":
                        rows.append(i)
                        cols.append(index[nxt])
                        data.append(p)
            P[j] = sp.csr_matrix((data, (rows, cols)), shape=(n, n))  # duplicates are summed
            R[j] = rj
        return S, index, P, R

    def solve(self, residual_tol: float = 1e-11, max_pi_iters: int = 500):
        """Exact policy iteration, then Bellman polishing sweeps until the residual <= residual_tol."""
        if self._solved is not None:
            return self._solved
        S, index, P, R = self._build()
        n = len(S)
        J = self.valid_joints

        def q_matrix(V):
            return np.stack([R[j] + GAMMA * (P[j] @ V) for j in J], axis=1)  # n x |J|

        eye = sp.identity(n, format="csc")
        policy = np.zeros(n, dtype=int)  # column index into J
        V = np.zeros(n)
        for _ in range(max_pi_iters):
            # P_pi row i = P[J[policy[i]]] row i; R_pi likewise
            P_pi = sp.csr_matrix((n, n))
            R_pi = np.zeros(n)
            for col, j in enumerate(J):
                sel = (policy == col).astype(float)
                P_pi = P_pi + sp.diags(sel) @ P[j]
                R_pi = R_pi + sel * R[j]
            V = np.atleast_1d(spla.spsolve((eye - GAMMA * P_pi).tocsc(), R_pi))
            Q = q_matrix(V)
            best = Q.max(axis=1)
            current = Q[np.arange(n), policy]
            improve = best > current + 1e-10
            if not improve.any():
                break
            policy = np.where(improve, Q.argmax(axis=1), policy)
        else:
            raise RuntimeError("policy iteration did not converge")
        residual = np.inf
        for _ in range(100000):
            Q = q_matrix(V)
            newV = Q.max(axis=1)
            residual = float(np.max(np.abs(newV - V))) if n else 0.0
            V = newV
            if residual <= residual_tol:
                break
        Q = q_matrix(V)
        residual = float(np.max(np.abs(Q.max(axis=1) - V))) if n else 0.0
        assert residual <= residual_tol * 10, residual
        Qfull = np.full((n, N_JOINT), -np.inf)
        for col, j in enumerate(J):
            Qfull[:, j] = Q[:, col]
        self._solved = {"S": S, "index": index, "V": V, "Q": Qfull, "residual": residual}
        return self._solved

    def states(self) -> list[tuple]:
        return list(self.solve()["S"])

    def value(self, state: tuple) -> float:
        sol = self.solve()
        return float(sol["V"][sol["index"][tuple(state)]])

    def q(self, state: tuple) -> np.ndarray:
        sol = self.solve()
        return sol["Q"][sol["index"][tuple(state)]].copy()

    def acceptable(self, state: tuple) -> list[int]:
        """A(s) = {valid j : Q(s, j) >= max_j Q(s, j) - TOL}, increasing j."""
        q = self.q(state)
        m = max(q[j] for j in self.valid_joints)
        return [j for j in self.valid_joints if q[j] >= m - TOL]

    # ---- §7 weak bot -------------------------------------------------------------------------------------------
    def weak_costs(self, state: tuple) -> dict[int, float]:
        """E_j for every valid j (float, summed over rand outcomes in listed order)."""
        E = {}
        for j in self.valid_joints:
            total = 0.0
            for p, nxt, _r, outcome in self.step_dist(state, j):
                if outcome == "success":
                    cost = WEAK_SUCCESS_COST
                elif outcome == "crash":
                    cost = WEAK_CRASH_COST
                else:
                    cost = violation(self.goal, Env(self.var_names, list(nxt), {}, 0))
                total += p * cost
            E[j] = total
        return E

    def weak_costs_exact(self, state: tuple) -> dict[int, Fraction]:
        """Same as weak_costs with exact rational weights (cross-check only)."""
        E = {}
        for j in self.valid_joints:
            total = Fraction(0)
            for (w, p) in self.outcomes_exact():
                nxt, _r, _d, outcome = self.tick_w(state, j, w)
                if outcome == "success":
                    cost = WEAK_SUCCESS_COST
                elif outcome == "crash":
                    cost = WEAK_CRASH_COST
                else:
                    cost = violation(self.goal, Env(self.var_names, list(nxt), {}, 0))
                total += p * cost
            E[j] = total
        return E

    def weak_candidates(self, state: tuple) -> list[int]:
        E = self.weak_costs(state)
        m = min(E.values())
        return [j for j in self.valid_joints if E[j] <= m + WEAK_TIE]

    def weak_action(self, state: tuple, rng) -> int:
        cands = self.weak_candidates(state)
        return cands[int(rng.integers(len(cands)))]

    def goal_violation(self, state: tuple) -> int:
        return violation(self.goal, Env(self.var_names, list(state), {}, 0))


def value_iteration_plain(m: BruteMachine, tol: float = 1e-12, max_iters: int = 200000) -> dict:
    """Independent cross-check: plain synchronous value iteration from V = 0 using step_dist directly."""
    S = m.reachable()
    index = {s: i for i, s in enumerate(S)}
    table = {(s, j): [(p, index[nxt] if o == "running" else -1, r) for p, nxt, r, o in m.step_dist(s, j)]
             for s in S for j in m.valid_joints}
    V = np.zeros(len(S))
    for _ in range(max_iters):
        newV = np.array([max(sum(p * (r + (GAMMA * V[k] if k >= 0 else 0.0)) for p, k, r in table[(s, j)])
                             for j in m.valid_joints) for s in S])
        diff = float(np.max(np.abs(newV - V))) if len(S) else 0.0
        V = newV
        if diff <= tol:
            break
    return {s: float(V[index[s]]) for s in S}
