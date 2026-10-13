"""ProgramStudent tokenizer for mz-1 programs (pure numpy; docs/machine_zoo/SPEC.md is authoritative).

A program + a batch of its states becomes a SET of typed tokens plus relation counts between tokens. The student never
sees names (they are used only to resolve references), family/domain/title/story text or any id.

Token layout (fixed positions, T_MAX = 54 = the DSL caps, so no program is ever truncated):

    VAR   0..9    one per var (SPEC: 1..10 vars)                 static F_VS + dynamic F_VD features
    RULE  10..33  one per rule, in program order (1..24 rules)   static F_RS + dynamic F_RD
    ITEM  34..49  one per goal/crash comparison item (<= 16)     static F_AS + dynamic F_AD
    CTRL  50..52  one per control slot (1..3)                    static F_CS + dynamic F_CD (one-step probes)
    GLOB  53      one                                            static F_GS + dynamic F_GD
    plus a per-JOINT probe table jp[27, F_JP] read by the output head (not a token).

Why these types: rules are the program (ordered: index features + adjacency relations carry the order; vars are a
SET, so var tokens carry no positional feature and permuting the var order permutes VAR tokens and nothing else —
tested); comparison items make goal/crash readable item by item (slack, satisfied, violation); controls carry the
exact one-step consequences of each option; the global token carries program-level counts and the current goal
violation. Worst case 54 tokens (DSL caps 10+24+16+3+1); typical programs use ~20-30, padded tokens are masked
keys (the numpy path may drop them: identical result).

Dynamic features are exact functions of (program, state) computed by an in-module vectorized one-tick executor
(``exec_tick``) that follows SPEC §4 literally; ``tests/test_machine_zoo_student.py`` checks it against lane A's
``machine_zoo.interp.step_dist`` transition by transition (lane B fixtures + every family module), and the greedy
flag against ``machine_zoo.weak.weak_scores_scalar``. Probes (test-time compute, uses
only the program + state): for every valid joint j, the exact distribution over the random draw w gives P(crash),
P(success), expected relative goal violation, expected crash proximity, the SPEC §7 greedy-bot candidate flag, and a
short deterministic look-ahead (j, then KEEP for ROLLOUT_H - 1 ticks, modal w).

Definitions (SPEC §7 goal violation ``viol``; all integers):
    viol(goal, x) >= 1 on every non-goal state, 0 iff the goal holds.
    cprox(x) = min( viol(c, x) over crash PREDs c ; min(v - lo, hi - v) + 1 over oob="crash" vars ), capped at
               CPROX_CAP (= CPROX_CAP when the program has neither) — integer distance to the nearest crash.
    slog(z) = sign(z) * log1p(|z|).
All features are rounded through float16 (rows are stored as float16; inference rounds identically, so the served
features are bit-identical to the trained ones).

Relations (``rel`` uint8[N_REL, 54, 54], count of relation t from query token q to key token k; static per program):
    0/1 rule writes var (q=rule,k=var) / reverse          2/3 rule EXPR reads var (count of terms) / reverse
    4/5 rule guard reads var / reverse                    6/7 rule reads control (EXPR or guard) / reverse
    8/9 item reads var / reverse                          10/11 later rule reads a var written earlier this tick / rev.
    12/13 rule reads a var written by itself or a later rule (value from the previous tick) / reverse
    14 previous rule (k = q-1)   15 next rule (k = q+1)   16 items of the same top-level PRED (q != k)
    17/18 var q is written by a rule reading var k / reverse   19/20 control q drives var k (a rule writing k reads
    the control) / reverse.
"""

from __future__ import annotations

import math

import numpy as np

N_JOINT = 27
KEEP_JOINT = 13
MAX_VARS, MAX_RULES, MAX_ITEMS, MAX_CTRL = 10, 24, 16, 3
OFF_VAR, OFF_RULE, OFF_ITEM, OFF_CTRL = 0, MAX_VARS, MAX_VARS + MAX_RULES, MAX_VARS + MAX_RULES + MAX_ITEMS
OFF_GLOB = OFF_CTRL + MAX_CTRL
T_MAX = OFF_GLOB + 1  # 54
N_REL = 21
CPROX_CAP = 1000
ROLLOUT_H = 4
OPS = ("<=", ">=", "==", "!=", "<", ">")
CRASH_COST = 10 ** 6

VAR_STATIC = ("lo", "hi", "width", "log_width", "oob_crash", "zero_in_range", "init_n", "init_min_norm",
              "init_max_norm", "n_write", "n_read_expr", "n_read_guard", "n_goal_items", "n_crash_items",
              "self_integrator", "uncond_write", "ctrl_driven", "rand_driven")
VAR_DYN = ("value", "value_norm", "room_lo", "room_hi", "log_room_lo", "log_room_hi", "at_lo", "at_hi",
           "goal_grad_up", "goal_grad_dn", "cprox_grad_up", "cprox_grad_dn")
RULE_STATIC = ("index", "index_norm", "index_from_end", "has_guard", "n_terms", "k_slog", "k_norm", "self_coef",
               "n_var_atoms", "n_ctrl_atoms", "has_w", "n_abs", "n_sgn", "sum_abs_coef", "max_abs_coef",
               "guard_n_items", "guard_any", "guard_nested", "guard_reads_ctrl", "guard_reads_w",
               "g_op_le", "g_op_ge", "g_op_eq", "g_op_ne", "g_op_lt", "g_op_gt",
               "target_oob_crash", "last_writer", "first_writer", "rhs_below_norm", "rhs_above_norm")
RULE_DYN = ("fires_keep", "delta_keep_slog", "delta_keep_norm", "oob_crash_keep", "clamped_keep", "fires_any",
            "delta_range_norm")
ITEM_STATIC = ("is_goal", "is_crash", "op_le", "op_ge", "op_eq", "op_ne", "op_lt", "op_gt", "thr_slog", "thr_norm",
               "parent_any", "nested", "top_any", "n_terms", "n_var_atoms", "has_abs", "has_sgn", "pred_n_items",
               "k_slog")
ITEM_DYN = ("lhs_slog", "lhs_norm", "slack_norm", "satisfied", "viol_slog", "viol_norm")
CTRL_STATIC = ("opt0", "opt1", "opt2", "valid0", "valid2", "n_read_expr", "n_read_guard", "n_vars_driven", "spread",
               "abs_read")
CTRL_DYN = tuple(f"{k}_o{o}" for o in range(3) for k in ("pc_keep", "ps_keep", "rv_keep", "pc_min", "ps_max",
                                                         "rv_min"))
GLOB_STATIC = ("n_vars", "n_rules", "n_goal_items", "n_crash_preds", "n_crash_items", "n_ctrl", "n_valid_joints",
               "has_rand", "n_rand", "rand_entropy", "rand_min", "rand_max", "rand_mean", "goal_any",
               "log_n_start", "log_state_space", "n_oob_crash_vars", "has_cprox")
GLOB_DYN = ("goal_viol_slog", "cprox_slog", "keep_p_crash", "keep_p_succ", "keep_rel_viol", "min_p_crash",
            "max_p_succ", "min_rel_viol")
JOINT_PROBE = ("p_crash", "p_succ", "rel_viol", "dviol_slog", "rel_cprox", "weak_cand", "ro_crash", "ro_succ",
               "ro_min_rel_viol", "ro_final_rel_viol", "is_keep", "n_nonkeep")
F_VS, F_VD, F_RS, F_RD = len(VAR_STATIC), len(VAR_DYN), len(RULE_STATIC), len(RULE_DYN)
F_AS, F_AD, F_CS, F_CD = len(ITEM_STATIC), len(ITEM_DYN), len(CTRL_STATIC), len(CTRL_DYN)
F_GS, F_GD, F_JP = len(GLOB_STATIC), len(GLOB_DYN), len(JOINT_PROBE)
# model input widths per token type (static | dynamic)
F_VAR, F_RULE, F_ITEM, F_CTRL, F_GLOB = F_VS + F_VD, F_RS + F_RD, F_AS + F_AD, F_CS + F_CD, F_GS + F_GD
TYPES = ("var", "rule", "item", "ctrl", "glob")
TYPE_CAP = {"var": MAX_VARS, "rule": MAX_RULES, "item": MAX_ITEMS, "ctrl": MAX_CTRL}
TYPE_WIDTH = {"var": F_VAR, "rule": F_RULE, "item": F_ITEM, "ctrl": F_CTRL, "glob": F_GLOB, "jp": F_JP}
ROWS_FORMAT = "mz-rows-v1"

K_VAR, K_CTRL, K_W, K_ABSV, K_SGNV, K_ABSC = range(6)


def r16(x) -> np.ndarray:
    """Round through float16 (the storage dtype), return float32."""
    return np.asarray(x, np.float32).astype(np.float16).astype(np.float32)


def slog(x):
    x = np.asarray(x, np.float64)
    return np.sign(x) * np.log1p(np.abs(x))


# ================================================================================ program compilation
def _canon_terms(e: dict) -> list:
    """SPEC canonicalize for one EXPR: merge equal atoms, drop zero coefficients, sort by atom string."""
    acc: dict = {}
    for coef, atom in e.get("t", []):
        acc[atom] = acc.get(atom, 0) + int(coef)
    return [(c, a) for a, c in sorted(acc.items()) if c != 0]


class _Expr:
    __slots__ = ("k", "terms")

    def __init__(self, e: dict, vcol: dict, ccol: dict):
        self.k = int(e.get("k", 0))
        self.terms = []
        for coef, atom in _canon_terms(e):
            if atom == "$w":
                kind, idx = K_W, -1
            elif atom.startswith("abs(@") and atom.endswith(")"):
                kind, idx = K_ABSC, ccol[atom[5:-1]]
            elif atom.startswith("abs(") and atom.endswith(")"):
                kind, idx = K_ABSV, vcol[atom[4:-1]]
            elif atom.startswith("sgn(") and atom.endswith(")"):
                kind, idx = K_SGNV, vcol[atom[4:-1]]
            elif atom.startswith("@"):
                kind, idx = K_CTRL, ccol[atom[1:]]
            else:
                kind, idx = K_VAR, vcol[atom]
            self.terms.append((int(coef), kind, idx))

    def vars_read(self) -> list:
        return [i for _c, kd, i in self.terms if kd in (K_VAR, K_ABSV, K_SGNV)]

    def ctrls_read(self) -> list:
        return [i for _c, kd, i in self.terms if kd in (K_CTRL, K_ABSC)]

    def eval(self, X, C, W) -> np.ndarray:
        out = np.full(X.shape[0], self.k, dtype=np.int64)
        for coef, kd, i in self.terms:
            if kd == K_VAR:
                v = X[:, i]
            elif kd == K_CTRL:
                v = C[:, i]
            elif kd == K_W:
                v = W
            elif kd == K_ABSV:
                v = np.abs(X[:, i])
            elif kd == K_SGNV:
                v = np.sign(X[:, i])
            else:
                v = np.abs(C[:, i])
            out += coef * v
        return out


class _Pred:
    """PRED tree: ``mode`` in {all, any}; items = list of ("cmp", _Expr, op, c) or ("pred", _Pred)."""

    def __init__(self, p: dict, vcol: dict, ccol: dict):
        if ("all" in p) == ("any" in p):
            raise ValueError("PRED must have exactly one of all/any")
        self.mode = "all" if "all" in p else "any"
        self.items = []
        for it in p[self.mode]:
            if isinstance(it, dict):
                self.items.append(("pred", _Pred(it, vcol, ccol)))
            else:
                e, op, c = it
                if op not in OPS:
                    raise ValueError(f"bad op {op!r}")
                self.items.append(("cmp", _Expr(e, vcol, ccol), op, int(c)))

    def leaves(self, top_any: bool, depth: int = 0):
        """Yield (expr, op, c, parent_any, nested, top_any) for every comparison item in written order
        (parent_any = the PRED directly containing the item is ``any``; nested = inside a nested PRED)."""
        for it in self.items:
            if it[0] == "cmp":
                yield it[1], it[2], it[3], (self.mode == "any"), depth > 0, top_any
            else:
                yield from it[1].leaves(top_any, depth + 1)

    def exprs(self):
        for it in self.items:
            if it[0] == "cmp":
                yield it[1]
            else:
                yield from it[1].exprs()

    def ops(self):
        for it in self.items:
            if it[0] == "cmp":
                yield it[2]
            else:
                yield from it[1].ops()

    def n_items(self) -> int:
        return sum(1 if it[0] == "cmp" else it[1].n_items() for it in self.items)

    def nested(self) -> bool:
        return any(it[0] == "pred" for it in self.items)

    def eval(self, X, C, W) -> np.ndarray:
        res = []
        for it in self.items:
            if it[0] == "pred":
                res.append(it[1].eval(X, C, W))
            else:
                e = it[1].eval(X, C, W)
                op, c = it[2], it[3]
                res.append({"<=": e <= c, ">=": e >= c, "==": e == c, "!=": e != c, "<": e < c, ">": e > c}[op])
        r = np.stack(res, 0)
        return r.all(0) if self.mode == "all" else r.any(0)

    def viol(self, X) -> np.ndarray:
        """SPEC §7 goal violation (var atoms only)."""
        res = []
        for it in self.items:
            if it[0] == "pred":
                res.append(it[1].viol(X))
            else:
                res.append(item_violation(it[1].eval(X, None, None), it[2], it[3]))
        r = np.stack(res, 0)
        return r.sum(0) if self.mode == "all" else r.min(0)


def item_violation(e: np.ndarray, op: str, c: int) -> np.ndarray:
    if op == "<=":
        return np.maximum(0, e - c)
    if op == "<":
        return np.maximum(0, e - c + 1)
    if op == ">=":
        return np.maximum(0, c - e)
    if op == ">":
        return np.maximum(0, c - e + 1)
    if op == "==":
        return np.abs(e - c)
    return (e == c).astype(np.int64)


class Compiled:
    """Program compiled for vectorized evaluation (names are used only here, to resolve references)."""

    def __init__(self, program: dict):
        V, Cs = program["vars"], program["controls"]
        if not (1 <= len(V) <= MAX_VARS and 1 <= len(Cs) <= MAX_CTRL and 1 <= len(program["rules"]) <= MAX_RULES):
            raise ValueError("program exceeds the mz-1 caps")
        self.vcol = {v["name"]: i for i, v in enumerate(V)}
        self.ccol = {c["name"]: i for i, c in enumerate(Cs)}
        self.nv, self.nc, self.nr = len(V), len(Cs), len(program["rules"])
        self.lo = np.array([int(v["lo"]) for v in V], np.int64)
        self.hi = np.array([int(v["hi"]) for v in V], np.int64)
        self.oob_crash = np.array([v["oob"] == "crash" for v in V], bool)
        self.init = [list(map(int, v["init"])) for v in V]
        self.opts = [list(c["opts"]) for c in Cs]
        rand = program.get("rand")
        if rand:
            self.w_vals = np.array([int(v) for v, _ in rand], np.int64)
            self.w_wts = np.array([int(wt) for _, wt in rand], np.int64)
        else:
            self.w_vals, self.w_wts = np.zeros(1, np.int64), np.ones(1, np.int64)
        self.w_p = self.w_wts / self.w_wts.sum()
        self.w_modal = int(self.w_vals[int(np.argmax(self.w_wts))])  # ties -> first listed
        self.has_rand = bool(rand)
        self.rules = []
        for r in program["rules"]:
            self.rules.append((self.vcol[r["set"]], _Expr(r["to"], self.vcol, self.ccol),
                               _Pred(r["if"], self.vcol, self.ccol) if r.get("if") else None))
        self.crash = [_Pred(p, self.vcol, self.ccol) for p in program.get("crash", [])]
        self.goal = _Pred(program["goal"], self.vcol, self.ccol)
        # items: goal leaves first, then crash leaves, written order; (expr, op, c, parent_any, nested, top_any,
        # is_goal, pred_id, pred_n_items)
        self.items = []
        for pid, p in enumerate([self.goal] + self.crash):
            for e, op, c, pa, nested, ta in p.leaves(p.mode == "any"):
                self.items.append((e, op, c, pa, nested, ta, pid == 0, pid, p.n_items()))
        if len(self.items) > MAX_ITEMS:
            raise ValueError(f"{len(self.items)} goal/crash items > {MAX_ITEMS}")
        # valid joints and their command values
        om = np.zeros((3, 3), bool)
        om[:, 1] = True
        for s, o in enumerate(self.opts):
            om[s, 0], om[s, 2] = o[0] is not None, o[2] is not None
        self.opt_mask = om
        self.jmask = (om[0][:, None, None] & om[1][None, :, None] & om[2][None, None, :]).reshape(N_JOINT)
        self.valid_joints = np.flatnonzero(self.jmask)
        cmd = np.zeros((N_JOINT, max(1, self.nc)), np.int64)
        for j in range(N_JOINT):
            oj = (j // 9, (j // 3) % 3, j % 3)
            for s in range(self.nc):
                v = self.opts[s][oj[s]]
                cmd[j, s] = 0 if v is None else int(v)
        self.cmd = cmd
        self.has_cprox = bool(self.crash) or bool(self.oob_crash.any())

    # ---------------------------------------------------------------- one tick (SPEC §4 steps 3-4), vectorized
    def exec_tick(self, X: np.ndarray, C: np.ndarray, W: np.ndarray, trace: bool = False):
        """X int64[K, nv] states, C int64[K, nc] command values, W int64[K] random outcomes.
        Returns (Xn, crash bool[K], success bool[K], trace dict or None). Crash includes out-of-range crashes."""
        X = np.array(X, dtype=np.int64, copy=True)
        K = X.shape[0]
        alive = np.ones(K, bool)
        tr = None
        if trace:
            tr = {"fired": np.zeros((K, self.nr), bool), "delta": np.zeros((K, self.nr), np.int64),
                  "clamped": np.zeros((K, self.nr), bool), "oob": np.zeros((K, self.nr), bool)}
        for r, (t, expr, guard) in enumerate(self.rules):
            g = alive.copy() if guard is None else (alive & guard.eval(X, C, W))
            if not g.any():
                continue
            val = expr.eval(X, C, W)
            lo, hi = self.lo[t], self.hi[t]
            inr = (val >= lo) & (val <= hi)
            old = X[:, t]
            if self.oob_crash[t]:
                crash_here = g & ~inr
                alive &= ~crash_here
                newv = np.where(g & inr, val, old)
                if trace:
                    tr["oob"][:, r] = crash_here
            else:
                newv = np.where(g, np.clip(val, lo, hi), old)
                if trace:
                    tr["clamped"][:, r] = g & ~inr
            if trace:
                tr["fired"][:, r] = g
                tr["delta"][:, r] = newv - old
            X[:, t] = newv
        crash = ~alive
        for p in self.crash:
            crash |= alive & p.eval(X, None, None)
        succ = ~crash & self.goal.eval(X, None, None)
        return X, crash, succ, tr

    def viol(self, X) -> np.ndarray:
        return self.goal.viol(np.asarray(X, np.int64))

    def cprox(self, X) -> np.ndarray:
        X = np.asarray(X, np.int64)
        out = np.full(X.shape[0], CPROX_CAP, np.int64)
        for p in self.crash:
            out = np.minimum(out, p.viol(X))
        for i in np.flatnonzero(self.oob_crash):
            out = np.minimum(out, np.minimum(X[:, i] - self.lo[i], self.hi[i] - X[:, i]) + 1)
        return np.minimum(out, CPROX_CAP)


# ================================================================================ interval helpers (static)
def _atom_range(cp: Compiled, kd: int, i: int) -> tuple[int, int]:
    if kd == K_VAR:
        return int(cp.lo[i]), int(cp.hi[i])
    if kd == K_ABSV:
        lo, hi = int(cp.lo[i]), int(cp.hi[i])
        return (0 if lo <= 0 <= hi else min(abs(lo), abs(hi))), max(abs(lo), abs(hi))
    if kd == K_SGNV:
        return int(np.sign(cp.lo[i])), int(np.sign(cp.hi[i]))
    if kd in (K_CTRL, K_ABSC):
        vals = [v for v in cp.opts[i] if v is not None]
        if kd == K_ABSC:
            vals = [abs(v) for v in vals]
        return min(vals), max(vals)
    return int(cp.w_vals.min()), int(cp.w_vals.max())


def _expr_range(cp: Compiled, e: _Expr) -> tuple[int, int]:
    lo = hi = e.k
    for coef, kd, i in e.terms:
        a, b = _atom_range(cp, kd, i)
        lo += min(coef * a, coef * b)
        hi += max(coef * a, coef * b)
    return lo, hi


# ================================================================================ static tokens + relations
def machine_static(program: dict, cp: Compiled | None = None) -> dict:
    """Per-program arrays: var_s, rule_s, item_s, ctrl_s, glob_s (float32, float16-rounded), tokmask bool[54],
    rel uint8[N_REL, 54, 54], jmask bool[27]."""
    cp = cp or Compiled(program)
    nv, nr, nc = cp.nv, cp.nr, cp.nc
    width = (cp.hi - cp.lo).astype(np.float64)
    var_s = np.zeros((MAX_VARS, F_VS))
    rule_s = np.zeros((MAX_RULES, F_RS))
    item_s = np.zeros((MAX_ITEMS, F_AS))
    ctrl_s = np.zeros((MAX_CTRL, F_CS))
    glob_s = np.zeros(F_GS)
    rel = np.zeros((N_REL, T_MAX, T_MAX), np.int64)
    V, R, A, Cq = (lambda i: OFF_VAR + i), (lambda i: OFF_RULE + i), (lambda i: OFF_ITEM + i), (lambda i: OFF_CTRL + i)

    writers = [[r for r, (t, _e, _g) in enumerate(cp.rules) if t == i] for i in range(nv)]
    # ---- rules
    for r, (t, e, g) in enumerate(cp.rules):
        rv = e.vars_read()
        gv = [i for ge in (g.exprs() if g else []) for i in ge.vars_read()]
        gc = [i for ge in (g.exprs() if g else []) for i in ge.ctrls_read()]
        ec = e.ctrls_read()
        self_coef = sum(c for c, kd, i in e.terms if kd == K_VAR and i == t)
        ops = list(g.ops()) if g else []
        rlo, rhi = _expr_range(cp, e)
        W_t = max(1.0, width[t])
        rule_s[r] = [r, r / max(1, nr - 1), nr - 1 - r, g is not None, len(e.terms), slog(e.k), e.k / W_t, self_coef,
                     sum(1 for _c, kd, i in e.terms if kd in (K_VAR, K_ABSV, K_SGNV) and i != t), len(ec),
                     any(kd == K_W for _c, kd, _i in e.terms),
                     sum(1 for _c, kd, _i in e.terms if kd in (K_ABSV, K_ABSC)),
                     sum(1 for _c, kd, _i in e.terms if kd == K_SGNV),
                     sum(abs(c) for c, _k, _i in e.terms), max([abs(c) for c, _k, _i in e.terms], default=0),
                     g.n_items() if g else 0, (g.mode == "any") if g else 0, g.nested() if g else 0, len(gc) > 0,
                     any(kd == K_W for ge in (g.exprs() if g else []) for _c, kd, _i in ge.terms),
                     *[ops.count(o) for o in OPS], cp.oob_crash[t], writers[t][-1] == r, writers[t][0] == r,
                     max(0, cp.lo[t] - rlo) / W_t, max(0, rhi - cp.hi[t]) / W_t]
        rel[0, R(r), V(t)] += 1
        rel[1, V(t), R(r)] += 1
        for i in rv:
            rel[2, R(r), V(i)] += 1
            rel[3, V(i), R(r)] += 1
        for i in gv:
            rel[4, R(r), V(i)] += 1
            rel[5, V(i), R(r)] += 1
        for c in ec + gc:
            rel[6, R(r), Cq(c)] += 1
            rel[7, Cq(c), R(r)] += 1
        for i in set(rv) | set(gv):
            for r2 in writers[i]:
                if r2 < r:
                    rel[10, R(r), R(r2)] += 1
                    rel[11, R(r2), R(r)] += 1
                else:
                    rel[12, R(r), R(r2)] += 1
                    rel[13, R(r2), R(r)] += 1
            rel[17, V(t), V(i)] += 1
            rel[18, V(i), V(t)] += 1
        for c in set(ec) | set(gc):
            rel[19, Cq(c), V(t)] += 1
            rel[20, V(t), Cq(c)] += 1
        if r > 0:
            rel[14, R(r), R(r - 1)] += 1
        if r < nr - 1:
            rel[15, R(r), R(r + 1)] += 1
    # ---- items
    goal_items = [0] * nv
    crash_items = [0] * nv
    for a, (e, op, c, pa, nested, ta, is_goal, pid, pn) in enumerate(cp.items):
        lo_e, hi_e = _expr_range(cp, e)
        S_e = max(1, hi_e - lo_e)
        item_s[a] = [is_goal, not is_goal, *[op == o for o in OPS], slog(c), (c - lo_e) / S_e, pa, nested, ta,
                     len(e.terms), len(e.vars_read()), any(kd == K_ABSV for _c, kd, _i in e.terms),
                     any(kd == K_SGNV for _c, kd, _i in e.terms), pn, slog(e.k)]
        for i in e.vars_read():
            rel[8, A(a), V(i)] += 1
            rel[9, V(i), A(a)] += 1
            (goal_items if is_goal else crash_items)[i] += 1
        for a2, it2 in enumerate(cp.items):
            if a2 != a and it2[7] == pid:
                rel[16, A(a), A(a2)] += 1
    # ---- vars
    for i in range(nv):
        ws = writers[i]
        reads_e = sum(1 for (_t, e, _g) in cp.rules for j in e.vars_read() if j == i)
        reads_g = sum(1 for (_t, _e, g) in cp.rules if g for ge in g.exprs() for j in ge.vars_read() if j == i)
        W_i = max(1.0, width[i])
        ini = cp.init[i]
        var_s[i] = [cp.lo[i], cp.hi[i], width[i], math.log1p(width[i]), cp.oob_crash[i], cp.lo[i] <= 0 <= cp.hi[i],
                    len(ini), (min(ini) - cp.lo[i]) / W_i, (max(ini) - cp.lo[i]) / W_i, len(ws), reads_e, reads_g,
                    goal_items[i], crash_items[i],
                    any(i in cp.rules[r][1].vars_read() for r in ws),
                    any(cp.rules[r][2] is None for r in ws),
                    any(cp.rules[r][1].ctrls_read() or (cp.rules[r][2] and any(
                        ge.ctrls_read() for ge in cp.rules[r][2].exprs())) for r in ws),
                    any(kd == K_W for r in ws for _c, kd, _j in cp.rules[r][1].terms)]
    # ---- controls
    for s in range(nc):
        o = cp.opts[s]
        vals = [v for v in o if v is not None]
        n_e = sum(1 for (_t, e, _g) in cp.rules for c in e.ctrls_read() if c == s)
        n_g = sum(1 for (_t, _e, g) in cp.rules if g for ge in g.exprs() for c in ge.ctrls_read() if c == s)
        abs_read = any(kd == K_ABSC and i == s for (_t, e, g) in cp.rules
                       for ex in [e] + (list(g.exprs()) if g else []) for _c, kd, i in ex.terms)
        ctrl_s[s] = [o[0] or 0, o[1], o[2] or 0, o[0] is not None, o[2] is not None, n_e, n_g,
                     int((rel[19, Cq(s)] > 0).sum()), max(vals) - min(vals), abs_read]
    # ---- global
    p = cp.w_p
    glob_s[:] = [nv, nr, sum(1 for it in cp.items if it[6]), len(cp.crash), sum(1 for it in cp.items if not it[6]),
                 nc, int(cp.jmask.sum()), cp.has_rand, len(cp.w_vals) if cp.has_rand else 0,
                 float(-(p * np.log(p)).sum()), cp.w_vals.min(), cp.w_vals.max(), float((p * cp.w_vals).sum()),
                 cp.goal.mode == "any", math.log(float(np.prod([len(x) for x in cp.init]))),
                 float(np.log(width + 1).sum()), int(cp.oob_crash.sum()), cp.has_cprox]
    tokmask = np.zeros(T_MAX, bool)
    tokmask[OFF_VAR:OFF_VAR + nv] = True
    tokmask[OFF_RULE:OFF_RULE + nr] = True
    tokmask[OFF_ITEM:OFF_ITEM + len(cp.items)] = True
    tokmask[OFF_CTRL:OFF_CTRL + nc] = True
    tokmask[OFF_GLOB] = True
    if rel.max() > 255:
        raise ValueError("relation count > 255")
    return {"var_s": r16(var_s), "rule_s": r16(rule_s), "item_s": r16(item_s), "ctrl_s": r16(ctrl_s),
            "glob_s": r16(glob_s), "tokmask": tokmask, "rel": rel.astype(np.uint8), "jmask": cp.jmask.copy()}


# ================================================================================ dynamic tokens + probes
def state_dynamic(program: dict, states, cp: Compiled | None = None, chunk: int = 256) -> dict:
    """Per-state arrays (float32, float16-rounded): var_d [N,10,F_VD], rule_d [N,24,F_RD], item_d [N,16,F_AD],
    ctrl_d [N,3,F_CD], glob_d [N,F_GD], jp [N,27,F_JP]."""
    cp = cp or Compiled(program)
    S = np.asarray(states, np.int64).reshape(-1, cp.nv)
    parts = [_dyn_chunk(cp, S[i:i + chunk]) for i in range(0, len(S), chunk)]
    if not parts:
        parts = [_dyn_chunk(cp, S)]
    return {k: np.concatenate([p[k] for p in parts], 0) for k in parts[0]}


def _dyn_chunk(cp: Compiled, S: np.ndarray) -> dict:
    N, nv, nr, nc = S.shape[0], cp.nv, cp.nr, cp.nc
    width = np.maximum(1, cp.hi - cp.lo).astype(np.float64)
    vj = cp.valid_joints
    nJ, nW = len(vj), len(cp.w_vals)
    viol0 = cp.viol(S)  # >= 1 on non-goal states
    v0 = np.maximum(1, viol0).astype(np.float64)
    cp0 = cp.cprox(S)
    # ---------------- exact one-step probes over (valid joint, w)
    X = np.repeat(S, nJ * nW, axis=0)
    Cm = np.tile(np.repeat(cp.cmd[vj, :nc], nW, axis=0), (N, 1))
    Wv = np.tile(cp.w_vals, N * nJ)
    Xn, crash, succ, tr = cp.exec_tick(X, Cm, Wv, trace=True)
    vn = cp.viol(Xn)
    cn = cp.cprox(Xn)
    shp = (N, nJ, nW)
    crash, succ, vn, cn = crash.reshape(shp), succ.reshape(shp), vn.reshape(shp), cn.reshape(shp)
    pw = cp.w_p[None, None, :]
    p_crash = (pw * crash).sum(-1)
    p_succ = (pw * succ).sum(-1)
    v_out = np.where(succ, 0, np.where(crash, viol0[:, None, None], vn)).astype(np.float64)
    e_viol = (pw * v_out).sum(-1)
    rel_viol = e_viol / v0[:, None]
    dviol = e_viol - viol0[:, None]
    c_out = np.where(crash, 0, cn).astype(np.float64)
    rel_cprox = ((pw * c_out).sum(-1) / np.maximum(1, cp0)[:, None]) if cp.has_cprox else np.ones((N, nJ))
    cost = np.where(succ, -1, np.where(crash, CRASH_COST, vn)).astype(np.int64)
    wsum = (cp.w_wts[None, None, :] * cost).sum(-1)  # exact integer W * E_j (SPEC §7)
    weak = wsum == wsum.min(1, keepdims=True)
    # ---------------- deterministic look-ahead: j then KEEP, modal w, ROLLOUT_H ticks
    Xr = np.repeat(S, nJ, axis=0)
    Cr = np.tile(cp.cmd[vj, :nc], (N, 1))
    Wm = np.full(N * nJ, cp.w_modal, np.int64)
    ro_crash = np.zeros(N * nJ, bool)
    ro_succ = np.zeros(N * nJ, bool)
    vref = np.repeat(v0, nJ)
    ro_min = np.ones(N * nJ)
    ro_fin = np.ones(N * nJ)
    live = np.ones(N * nJ, bool)
    keep_c = np.broadcast_to(cp.cmd[KEEP_JOINT, :nc], (N * nJ, nc))
    for h in range(ROLLOUT_H):
        idx = np.flatnonzero(live)
        if idx.size == 0:
            break
        Xh, ch, sh, _ = cp.exec_tick(Xr[idx], (Cr if h == 0 else keep_c)[idx], Wm[idx])
        Xr[idx] = Xh
        ro_crash[idx] |= ch
        ro_succ[idx] |= sh
        rv = np.where(sh, 0.0, cp.viol(Xh) / vref[idx])
        rv = np.where(ch, ro_fin[idx], rv)  # a crash keeps the last relative violation
        ro_min[idx] = np.minimum(ro_min[idx], rv)
        ro_fin[idx] = rv
        live[idx] = ~(ch | sh)
    # ---------------- joint probe table
    jp = np.zeros((N, N_JOINT, F_JP))
    nonkeep = np.array([sum(o != 1 for o in (j // 9, (j // 3) % 3, j % 3)) for j in range(N_JOINT)])
    jp[:, vj] = np.stack([p_crash, p_succ, rel_viol, slog(dviol), rel_cprox, weak,
                          ro_crash.reshape(N, nJ), ro_succ.reshape(N, nJ), ro_min.reshape(N, nJ),
                          ro_fin.reshape(N, nJ), np.broadcast_to(vj == KEEP_JOINT, (N, nJ)),
                          np.broadcast_to(nonkeep[vj], (N, nJ))], -1)
    # ---------------- controls: per option, others KEEP and max-marginal over the other slots
    ctrl_d = np.zeros((N, MAX_CTRL, F_CD))
    jpos = {int(j): k for k, j in enumerate(vj)}
    for s in range(nc):
        for o in range(3):
            if not cp.opt_mask[s, o]:
                continue
            ks = [k for k, j in enumerate(vj) if (int(j) // (9, 3, 1)[s]) % 3 == o]
            kk = jpos[KEEP_JOINT + (o - 1) * (9, 3, 1)[s]]
            ctrl_d[:, s, 6 * o:6 * o + 6] = np.stack(
                [p_crash[:, kk], p_succ[:, kk], rel_viol[:, kk], p_crash[:, ks].min(1), p_succ[:, ks].max(1),
                 rel_viol[:, ks].min(1)], -1)
    # ---------------- rules: trace under KEEP + modal w at the current state, plus spread over (j, w)
    _, _, _, trk = cp.exec_tick(S, np.broadcast_to(cp.cmd[KEEP_JOINT, :nc], (N, nc)),
                                np.full(N, cp.w_modal, np.int64), trace=True)
    tW = width[[t for (t, _e, _g) in cp.rules]]
    dl = tr["delta"].reshape(N, nJ * nW, nr)
    rule_d = np.zeros((N, MAX_RULES, F_RD))
    rule_d[:, :nr] = np.stack([trk["fired"], slog(trk["delta"]), trk["delta"] / tW, trk["oob"], trk["clamped"],
                               tr["fired"].reshape(N, nJ * nW, nr).any(1), (dl.max(1) - dl.min(1)) / tW], -1)
    # ---------------- vars
    var_d = np.zeros((N, MAX_VARS, F_VD))
    for i in range(nv):
        v = S[:, i]
        up, dn = v < cp.hi[i], v > cp.lo[i]
        Xu, Xd = S.copy(), S.copy()
        Xu[:, i] = np.minimum(v + 1, cp.hi[i])
        Xd[:, i] = np.maximum(v - 1, cp.lo[i])
        gu = np.where(up, cp.viol(Xu) - viol0, 0)
        gd = np.where(dn, cp.viol(Xd) - viol0, 0)
        cu = np.where(up, cp.cprox(Xu) - cp0, 0)
        cd = np.where(dn, cp.cprox(Xd) - cp0, 0)
        var_d[:, i] = np.stack([v, (v - cp.lo[i]) / width[i], v - cp.lo[i], cp.hi[i] - v, np.log1p(v - cp.lo[i]),
                                np.log1p(cp.hi[i] - v), ~dn, ~up, slog(gu), slog(gd), slog(cu), slog(cd)], -1)
    # ---------------- items
    item_d = np.zeros((N, MAX_ITEMS, F_AD))
    for a, (e, op, c, *_rest) in enumerate(cp.items):
        lo_e, hi_e = _expr_range(cp, e)
        S_e = max(1, hi_e - lo_e)
        ev = e.eval(S, None, None)
        vi = item_violation(ev, op, c)
        item_d[:, a] = np.stack([slog(ev), (ev - lo_e) / S_e, (c - ev) / S_e, vi == 0, slog(vi), vi / S_e], -1)
    # ---------------- global
    kk = jpos[KEEP_JOINT]
    glob_d = np.stack([slog(viol0), slog(cp0), p_crash[:, kk], p_succ[:, kk], rel_viol[:, kk], p_crash.min(1),
                       p_succ.max(1), rel_viol.min(1)], -1)
    return {"var_d": r16(var_d), "rule_d": r16(rule_d), "item_d": r16(item_d), "ctrl_d": r16(ctrl_d),
            "glob_d": r16(glob_d), "jp": r16(jp)}


# ================================================================================ batches and row arrays
STATIC_KEYS = ("var_s", "rule_s", "item_s", "ctrl_s", "glob_s")
DYN_KEYS = ("var_d", "rule_d", "item_d", "ctrl_d", "glob_d", "jp")


def assemble(st: dict, dy: dict, m_idx=None, with_rel: bool = True) -> dict:
    """Model batch (numpy float32) from static arrays (per machine, indexed by ``m_idx``; or a single machine's
    arrays broadcast when ``m_idx`` is None) and per-row dynamic arrays. ``with_rel=False`` omits the relation
    tensor (61 KB per row; not needed for feature statistics)."""
    N = dy["var_d"].shape[0]

    def g(k):
        a = st[k]
        if m_idx is None:
            return np.broadcast_to(a, (N,) + a.shape)
        return a[m_idx]
    f32 = np.float32
    out = {"x_var": np.concatenate([g("var_s"), dy["var_d"]], -1).astype(f32),
           "x_rule": np.concatenate([g("rule_s"), dy["rule_d"]], -1).astype(f32),
           "x_item": np.concatenate([g("item_s"), dy["item_d"]], -1).astype(f32),
           "x_ctrl": np.concatenate([g("ctrl_s"), dy["ctrl_d"]], -1).astype(f32),
           "x_glob": np.concatenate([g("glob_s"), dy["glob_d"]], -1).astype(f32),
           "jp": np.asarray(dy["jp"], f32), "tokmask": np.ascontiguousarray(g("tokmask")),
           "jmask": np.ascontiguousarray(g("jmask"))}
    if with_rel:
        out["rel"] = np.ascontiguousarray(g("rel"))
    return out


def tokenize(program: dict, states, cp: Compiled | None = None) -> dict:
    """Model batch for states of one program (inference path)."""
    cp = cp or Compiled(program)
    return assemble(machine_static(program, cp), state_dynamic(program, states, cp))


def build_row_arrays(programs: list, machine_idx, states, acceptable) -> dict:
    """Arrays for a training-rows .npz (docs/machine_zoo/ROWS.md, format ``mz-rows-v1``).

    programs: list of M mz-1 programs (row machine index m refers to programs[m]); machine_idx int[N];
    states: N state tuples (or int array [N, >= n_vars]; only the first n_vars entries of row i are read);
    acceptable: bool[N, 27] acceptable joints (training target = uniform over them).
    Returns per-machine ``m_*`` arrays and per-row ``r_*`` arrays (float16 features, uint8 relations)."""
    M = len(programs)
    mi = np.asarray(machine_idx, np.int64)
    N = len(mi)
    acc = np.asarray(acceptable, bool).reshape(N, N_JOINT)
    out = {"m_var_s": np.zeros((M, MAX_VARS, F_VS), np.float16),
           "m_rule_s": np.zeros((M, MAX_RULES, F_RS), np.float16),
           "m_item_s": np.zeros((M, MAX_ITEMS, F_AS), np.float16),
           "m_ctrl_s": np.zeros((M, MAX_CTRL, F_CS), np.float16), "m_glob_s": np.zeros((M, F_GS), np.float16),
           "m_tokmask": np.zeros((M, T_MAX), bool), "m_rel": np.zeros((M, N_REL, T_MAX, T_MAX), np.uint8),
           "m_jmask": np.zeros((M, N_JOINT), bool),
           "r_m": mi.astype(np.int32), "r_state": np.zeros((N, MAX_VARS), np.int16), "r_acc": acc,
           "r_var_d": np.zeros((N, MAX_VARS, F_VD), np.float16),
           "r_rule_d": np.zeros((N, MAX_RULES, F_RD), np.float16),
           "r_item_d": np.zeros((N, MAX_ITEMS, F_AD), np.float16),
           "r_ctrl_d": np.zeros((N, MAX_CTRL, F_CD), np.float16), "r_glob_d": np.zeros((N, F_GD), np.float16),
           "r_jp": np.zeros((N, N_JOINT, F_JP), np.float16)}
    for m, prog in enumerate(programs):
        cp = Compiled(prog)
        st = machine_static(prog, cp)
        for k in STATIC_KEYS:
            out["m_" + k][m] = st[k]
        out["m_tokmask"][m], out["m_rel"][m], out["m_jmask"][m] = st["tokmask"], st["rel"], st["jmask"]
        rows = np.flatnonzero(mi == m)
        if rows.size == 0:
            continue
        S = np.array([list(states[i])[:cp.nv] for i in rows], np.int64)
        if (acc[rows] & ~cp.jmask).any() or not acc[rows].any(1).all():
            raise ValueError(f"machine {m}: acceptable set empty or contains an invalid joint")
        out["r_state"][rows, :cp.nv] = S
        dy = state_dynamic(prog, S, cp)
        for k in DYN_KEYS:
            out["r_" + k][rows] = dy[k]
    return out


def feature_spec() -> dict:
    return {"format": ROWS_FORMAT, "t_max": T_MAX, "n_rel": N_REL, "caps": {**TYPE_CAP, "items": MAX_ITEMS},
            "rollout_h": ROLLOUT_H, "cprox_cap": CPROX_CAP,
            "features": {"var_s": VAR_STATIC, "var_d": VAR_DYN, "rule_s": RULE_STATIC, "rule_d": RULE_DYN,
                         "item_s": ITEM_STATIC, "item_d": ITEM_DYN, "ctrl_s": CTRL_STATIC, "ctrl_d": CTRL_DYN,
                         "glob_s": GLOB_STATIC, "glob_d": GLOB_DYN, "jp": JOINT_PROBE}}


def save_rows(path: str, arrays: dict, meta: dict) -> str:
    """Write a rows .npz (compressed): ``arrays`` from build_row_arrays (+ any extra ``r_*``/``m_*`` bookkeeping
    arrays, e.g. m_machine_id, r_behaviour), ``meta`` = builder metadata (JSON-serialisable). Adds the tokenizer
    feature spec and returns the sha256 of the acceptable-mask bytes (also stored as meta.acc_sha256)."""
    if not path.endswith(".npz"):
        raise ValueError("rows file must end in .npz")
    acc_sha = __import__("hashlib").sha256(np.ascontiguousarray(arrays["r_acc"]).tobytes()).hexdigest()
    full_meta = {**meta, **feature_spec(), "n_rows": len(arrays["r_m"]), "n_machines": len(arrays["m_rel"]),
                 "acc_sha256": acc_sha}
    np.savez_compressed(path, meta=np.array(__import__("json").dumps(full_meta, sort_keys=True)), **arrays)
    return acc_sha


def batch_from_rows(z: dict, rows, with_rel: bool = True) -> dict:
    """Model batch for rows of a loaded rows npz (dict of arrays) — the numpy twin of train_ps.RowStore.batch."""
    m = np.asarray(z["r_m"])[rows]
    st = {k: z["m_" + k] for k in STATIC_KEYS + ("tokmask", "jmask") + (("rel",) if with_rel else ())}
    dy = {k: z["r_" + k][rows] for k in DYN_KEYS}
    return assemble(st, dy, m, with_rel=with_rel)


# ================================================================================ probe4 baseline (descriptive)
_CP_CACHE: dict = {}


def compiled_cached(program: dict) -> Compiled:
    key = __import__("json").dumps(program, sort_keys=True)
    cp = _CP_CACHE.get(key)
    if cp is None:
        if len(_CP_CACHE) > 1024:
            _CP_CACHE.clear()
        cp = _CP_CACHE[key] = Compiled(program)
    return cp


def probe4_keys(cp: Compiled, S) -> tuple[np.ndarray, np.ndarray]:
    """Exact integer lexicographic keys (minimised in order) of the "probe4" baseline for states S [N, nv] over the
    valid joints: the same information the student's probe table carries (exact one-tick distribution over w, and
    the deterministic look-ahead "joint, then KEEP, modal w" over ROLLOUT_H ticks), without learning. W = total rand
    weight (1 when rand is null), P1 = exact one-tick probability:
        k1 = max(W·P1(crash), W·[the look-ahead path crashes])                     crash risk within the look-ahead
        k2 = -max(W·P1(success), W·[the look-ahead path succeeds])                 success within the look-ahead
        k3 = goal violation at the end of the look-ahead path (0 after a success; the last pre-crash value — the
             current state's violation if it crashes on the first tick — after a crash)
        k4 = W·E1[goal violation after one tick] (success -> 0, crash -> current violation: no progress)
    Returns (valid_joints int[nJ], keys int64[N, nJ, 4])."""
    S = np.asarray(S, np.int64).reshape(-1, cp.nv)
    N, nc = S.shape[0], cp.nc
    vj = cp.valid_joints
    nJ, nW = len(vj), len(cp.w_vals)
    Wt = int(cp.w_wts.sum())
    viol0 = cp.viol(S)
    # exact one tick
    X = np.repeat(S, nJ * nW, axis=0)
    Cm = np.tile(np.repeat(cp.cmd[vj, :nc], nW, axis=0), (N, 1))
    Wv = np.tile(cp.w_vals, N * nJ)
    Xn, crash, succ, _ = cp.exec_tick(X, Cm, Wv)
    vn = cp.viol(Xn).reshape(N, nJ, nW)
    crash, succ = crash.reshape(N, nJ, nW), succ.reshape(N, nJ, nW)
    wt = cp.w_wts[None, None, :]
    c1 = (wt * crash).sum(-1)
    s1 = (wt * succ).sum(-1)
    v1 = (wt * np.where(succ, 0, np.where(crash, viol0[:, None, None], vn))).sum(-1)
    # deterministic look-ahead (identical definition to the ro_* probe features)
    Xr = np.repeat(S, nJ, axis=0)
    Cr = np.tile(cp.cmd[vj, :nc], (N, 1))
    Wm = np.full(N * nJ, cp.w_modal, np.int64)
    keep_c = np.broadcast_to(cp.cmd[KEEP_JOINT, :nc], (N * nJ, nc))
    ro_c = np.zeros(N * nJ, bool)
    ro_s = np.zeros(N * nJ, bool)
    last = np.repeat(viol0, nJ).astype(np.int64)
    live = np.ones(N * nJ, bool)
    for h in range(ROLLOUT_H):
        idx = np.flatnonzero(live)
        if idx.size == 0:
            break
        Xh, ch, sh, _ = cp.exec_tick(Xr[idx], (Cr if h == 0 else keep_c)[idx], Wm[idx])
        Xr[idx] = Xh
        ro_c[idx] |= ch
        ro_s[idx] |= sh
        last[idx] = np.where(sh, 0, np.where(ch, last[idx], cp.viol(Xh)))
        live[idx] = ~(ch | sh)
    k1 = np.maximum(c1, Wt * ro_c.reshape(N, nJ))
    k2 = -np.maximum(s1, Wt * ro_s.reshape(N, nJ))
    return vj, np.stack([k1, k2, last.reshape(N, nJ), v1], -1).astype(np.int64)


def probe4_candidates(program: dict, state, cp: Compiled | None = None) -> list[int]:
    """Joints (increasing) whose probe4 key is lexicographically minimal."""
    cp = cp or compiled_cached(program)
    vj, K = probe4_keys(cp, np.asarray(state, np.int64)[None])
    k = K[0]
    best = k[np.lexsort(k.T[::-1])[0]]
    return [int(j) for j in vj[(k == best).all(1)]]


def probe4_action(program: dict, state, rng: np.random.Generator, cp: Compiled | None = None) -> int:
    """probe4 baseline: uniform over the lexicographic-minimal candidates with exactly ONE ``rng.integers`` call per
    decision on the policy stream (same CRN discipline as the SPEC §7 weak bot). Pure function of program + state."""
    c = probe4_candidates(program, state, cp)
    return c[int(rng.integers(len(c)))]
