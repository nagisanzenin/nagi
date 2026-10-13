"""Machine Zoo DSL ``mz-1``: validation, canonical form, identities, text syntax, rulebook render/parse.

Contract: docs/machine_zoo/SPEC.md §1 (program and validity rules 1-8), §1.1 (text syntax), §6 (identity).
Readings of the SPEC that needed a decision are listed in docs/machine_zoo/AMBIGUITIES.md (A1-*).

Authoring helpers (family modules import only this module):

    from nagi.burst2._rt.machine_zoo import dsl
    dsl.program(
        vars=[dsl.var("pos", 0, 12, [0, 1]), dsl.var("vel", -3, 3, 0, oob="crash")],
        controls=[dsl.control("drive", [-1, 0, 1])],
        rand=[[-1, 1], [0, 2], [1, 1]],                # [value, weight] pairs, or None
        rules=["vel := vel + @drive + $w", "if all(vel != 0): pos := pos + vel"],
        crash=["any(pos <= 0, abs(vel) >= 3)"],
        goal="all(pos == 10, vel == 0)")             # -> validated canonical program (dict)

Text syntax: EXPR ``pos + 2*vel - @drive - 3``; atoms ``x``, ``@c``, ``$w``, ``abs(x)``, ``sgn(x)``, ``abs(@c)``.
PRED ``all(ITEM, ...)`` / ``any(ITEM, ...)``; ITEM = ``EXPR op INT`` or a nested all/any; a bare comparison means
``all(cmp)``. Extension: the right-hand side of a comparison may be an EXPR; its atoms move to the left
(``pos >= goal + 2`` == ``pos - goal >= 2``). Rule: ``var := EXPR`` or ``if PRED: var := EXPR``.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re

DSL = "mz-1"
KEYS = ("dsl", "vars", "controls", "rand", "rules", "crash", "goal")
NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,15}")  # always used with fullmatch (ruling O-1)
OPS = ("<=", ">=", "==", "!=", "<", ">")
_NAME = r"[a-z][a-z0-9_]*"
ATOM_RE = re.compile(  # used with fullmatch (a trailing newline is not part of an atom)
    rf"(?:(?P<var>{_NAME})|@(?P<cmd>{_NAME})|(?P<w>\$w)|abs\((?P<absv>{_NAME})\)|sgn\((?P<sgnv>{_NAME})\)"
    rf"|abs\(@(?P<absc>{_NAME})\))"
)
# atom kinds (shared with interp / teacher)
K_VAR, K_ABS, K_SGN, K_CMD, K_ABSCMD, K_W = range(6)
_VAR_KINDS = (K_VAR, K_ABS, K_SGN)


class ProgramError(ValueError):
    """A SPEC §1 violation. ``rule`` is the §1 validity rule number (1-8) or "schema" (keys, types, counts)."""

    def __init__(self, rule, msg: str):
        self.rule = rule
        where = f"rule {rule}" if isinstance(rule, int) else str(rule)
        super().__init__(f"mz-1 {where}: {msg}")


def _isint(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _islist(x) -> bool:
    return isinstance(x, (list, tuple))


def parse_atom(a) -> tuple[int, str | None]:
    """Atom string -> (kind, name); kind in K_VAR, K_ABS, K_SGN, K_CMD, K_ABSCMD, K_W (name None for $w)."""
    if not isinstance(a, str):
        raise ProgramError(5, f"atom must be a string, got {a!r}")
    m = ATOM_RE.fullmatch(a)
    if m is None:
        raise ProgramError(5, f"unknown atom {a!r} (allowed: x, @c, $w, abs(x), sgn(x), abs(@c))")
    for kind, grp in ((K_VAR, "var"), (K_CMD, "cmd"), (K_ABS, "absv"), (K_SGN, "sgnv"), (K_ABSCMD, "absc")):
        if m.group(grp) is not None:
            return kind, m.group(grp)
    return K_W, None


# ---------------------------------------------------------------------------------------------- canonical form


def canon_expr(e: dict) -> dict:
    """Merge equal atoms (sum coefficients), drop zero coefficients, sort terms by atom string."""
    acc: dict[str, int] = {}
    for c, a in e["t"]:
        acc[a] = acc.get(a, 0) + c
    return {"t": [[acc[a], a] for a in sorted(acc) if acc[a] != 0], "k": e["k"]}


def canon_pred(p: dict) -> dict:
    ((kind, items),) = p.items()
    out = []
    for it in items:
        out.append(canon_pred(it) if isinstance(it, dict) else [canon_expr(it[0]), it[1], it[2]])
    return {kind: out}


def canonicalize(program: dict) -> dict:
    """SPEC §1 canonical form (fresh lists/dicts; every EXPR merged/sorted; everything else in written order)."""
    p = program
    rules = []
    for r in p["rules"]:
        rr = {"set": r["set"], "to": canon_expr(r["to"])}
        if "if" in r:
            rr["if"] = canon_pred(r["if"])
        rules.append(rr)
    return {
        "dsl": p["dsl"],
        "vars": [
            {"name": v["name"], "lo": v["lo"], "hi": v["hi"], "oob": v["oob"], "init": list(v["init"])}
            for v in p["vars"]
        ],
        "controls": [{"name": c["name"], "opts": list(c["opts"])} for c in p["controls"]],
        "rand": None if p["rand"] is None else [[int(v), int(w)] for v, w in p["rand"]],
        "rules": rules,
        "crash": [canon_pred(q) for q in p["crash"]],
        "goal": canon_pred(p["goal"]),
    }


def _dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def canonical_json(program: dict) -> str:
    """SPEC §6: json.dumps(canonicalize(program), sort_keys=True, separators=(",", ":"))."""
    return _dumps(canonicalize(program))


def machine_id(program: dict) -> str:
    """SPEC §6: sha256(canonical JSON) hex[:16]."""
    return hashlib.sha256(canonical_json(program).encode()).hexdigest()[:16]


def _map_expr(e: dict, fa) -> dict:
    return {"t": [[c, fa(a)] for c, a in e["t"]], "k": e["k"]}


def _map_pred(p: dict, fe) -> dict:
    ((kind, items),) = p.items()
    return {kind: [_map_pred(it, fe) if isinstance(it, dict) else fe(it) for it in items]}


def signature(program: dict) -> str:
    """SPEC §6 structural signature: rename vars v0.. / controls c0.. (program order), re-canonicalize (terms
    re-sorted by the renamed atom; AMBIGUITIES A1-3), then zero every integer literal keeping list lengths and the
    null/int pattern of opts; sha256[:16] of the compact sorted-key JSON."""
    p = canonicalize(program)
    vmap = {v["name"]: f"v{i}" for i, v in enumerate(p["vars"])}
    cmap = {c["name"]: f"c{i}" for i, c in enumerate(p["controls"])}

    def ren(a: str) -> str:
        kind, name = parse_atom(a)
        return {
            K_VAR: lambda: vmap[name],
            K_ABS: lambda: f"abs({vmap[name]})",
            K_SGN: lambda: f"sgn({vmap[name]})",
            K_CMD: lambda: "@" + cmap[name],
            K_ABSCMD: lambda: f"abs(@{cmap[name]})",
            K_W: lambda: "$w",
        }[kind]()

    def ren_item(it):
        return [_map_expr(it[0], ren), it[1], it[2]]

    r = {
        "dsl": p["dsl"],
        "vars": [dict(v, name=vmap[v["name"]]) for v in p["vars"]],
        "controls": [dict(c, name=cmap[c["name"]]) for c in p["controls"]],
        "rand": p["rand"],
        "rules": [
            dict({"set": vmap[x["set"]], "to": _map_expr(x["to"], ren)},
                 **({"if": _map_pred(x["if"], ren_item)} if "if" in x else {}))
            for x in p["rules"]
        ],
        "crash": [_map_pred(q, ren_item) for q in p["crash"]],
        "goal": _map_pred(p["goal"], ren_item),
    }
    r = canonicalize(r)

    def zexpr(e):
        return {"t": [[0, a] for _c, a in e["t"]], "k": 0}

    def zitem(it):
        return [zexpr(it[0]), it[1], 0]

    z = {
        "dsl": r["dsl"],
        "vars": [dict(v, lo=0, hi=0, init=[0] * len(v["init"])) for v in r["vars"]],
        "controls": [dict(c, opts=[None if o is None else 0 for o in c["opts"]]) for c in r["controls"]],
        "rand": None if r["rand"] is None else [[0, 0] for _ in r["rand"]],
        "rules": [
            dict({"set": x["set"], "to": zexpr(x["to"])}, **({"if": _map_pred(x["if"], zitem)} if "if" in x else {}))
            for x in r["rules"]
        ],
        "crash": [_map_pred(q, zitem) for q in r["crash"]],
        "goal": _map_pred(r["goal"], zitem),
    }
    return hashlib.sha256(_dumps(z).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------------------------- validation


def _check_expr(e, where: str, var_names: set, ctl_names: set, has_rand: bool, vars_only: bool) -> None:
    if not isinstance(e, dict) or set(e) != {"t", "k"}:
        raise ProgramError(5, f"{where}: EXPR must be a dict with exactly keys 't' and 'k', got {e!r}")
    t, k = e["t"], e["k"]
    if not _islist(t):
        raise ProgramError(5, f"{where}: EXPR 't' must be a list of terms, got {t!r}")
    if not _isint(k) or abs(k) > 1000:
        raise ProgramError(5, f"{where}: EXPR 'k' must be an int with |k| <= 1000, got {k!r}")
    merged: dict[str, int] = {}
    for term in t:  # written terms: [int coef, allowed atom]; limits apply to the canonical form (ruling O-2)
        if not _islist(term) or len(term) != 2:
            raise ProgramError(5, f"{where}: term must be [coef, atom], got {term!r}")
        c, a = term
        if not _isint(c):
            raise ProgramError(5, f"{where}: coef must be an int, got {c!r} for atom {a!r}")
        kind, name = parse_atom(a)
        if kind in _VAR_KINDS and name not in var_names:
            raise ProgramError(5, f"{where}: atom {a!r} names no var" + (" (it is a control: use @)" if name in ctl_names else ""))
        if kind in (K_CMD, K_ABSCMD) and name not in ctl_names:
            raise ProgramError(5, f"{where}: atom {a!r} names no control")
        if kind == K_W and not has_rand:
            raise ProgramError(5, f"{where}: atom '$w' used but rand is null")
        if vars_only and kind not in _VAR_KINDS:
            raise ProgramError(7, f"{where}: goal/crash predicates may use var atoms only (x, abs(x), sgn(x)), got {a!r}")
        merged[a] = merged.get(a, 0) + c
    canon = {a: c for a, c in merged.items() if c != 0}
    if len(canon) > 6:
        raise ProgramError(5, f"{where}: EXPR has {len(canon)} terms after canonicalization (max 6)")
    for a, c in canon.items():
        if abs(c) > 10:
            raise ProgramError(5, f"{where}: canonical coefficient of {a!r} is {c} (|coef| <= 10)")


def _check_pred(p, where: str, depth: int, ctx: tuple) -> int:
    """Validate a PRED; returns its number of comparison items."""
    if not isinstance(p, dict) or len(p) != 1 or next(iter(p)) not in ("all", "any"):
        raise ProgramError(6, f"{where}: PRED must be {{'all': [...]}} or {{'any': [...]}}, got {p!r}")
    if depth > 2:
        raise ProgramError(6, f"{where}: PRED nesting depth > 2 (a PRED inside a nested PRED)")
    ((kind, items),) = p.items()
    if not _islist(items) or not 1 <= len(items) <= 6:
        raise ProgramError(6, f"{where}: {kind}(...) must have 1..6 items, got {items!r}")
    n = 0
    for i, it in enumerate(items):
        w = f"{where}.{kind}[{i}]"
        if isinstance(it, dict):
            n += _check_pred(it, w, depth + 1, ctx)
            continue
        if not _islist(it) or len(it) != 3:
            raise ProgramError(6, f"{w}: ITEM must be [EXPR, op, int] or a nested PRED, got {it!r}")
        e, op, c = it
        _check_expr(e, w, *ctx)
        if op not in OPS:
            raise ProgramError(6, f"{w}: op must be one of {OPS}, got {op!r}")
        if not _isint(c) or abs(c) > 1000:
            raise ProgramError(6, f"{w}: comparison constant must be an int with |c| <= 1000, got {c!r}")
        n += 1
    return n


def _check_name(name, what: str) -> None:
    if not isinstance(name, str) or NAME_RE.fullmatch(name) is None:
        raise ProgramError(1, f"{what} name {name!r} does not match ^[a-z][a-z0-9_]{{0,15}}$")


def validate(program: dict) -> None:
    """Raise ProgramError naming the violated SPEC §1 rule; return None when the program is valid."""
    p = program
    if not isinstance(p, dict):
        raise ProgramError("schema", "program must be a dict")
    if set(p) != set(KEYS):
        raise ProgramError("schema", f"program keys must be exactly {KEYS}; missing {sorted(set(KEYS) - set(p))}, "
                           f"extra {sorted(set(p) - set(KEYS))}")
    if p["dsl"] != DSL:
        raise ProgramError("schema", f"dsl must be {DSL!r}, got {p['dsl']!r}")
    vs, cs, rand = p["vars"], p["controls"], p["rand"]
    if not _islist(vs) or not 1 <= len(vs) <= 10:
        raise ProgramError("schema", f"vars must be a list of 1..10 vars, got {len(vs) if _islist(vs) else vs!r}")
    if not _islist(cs) or not 1 <= len(cs) <= 3:
        raise ProgramError("schema", f"controls must be a list of 1..3 controls, got {len(cs) if _islist(cs) else cs!r}")
    # rule 1 + 2: vars
    names: list[str] = []
    space, n_start = 1, 1
    for i, v in enumerate(vs):
        if not isinstance(v, dict) or set(v) != {"name", "lo", "hi", "oob", "init"}:
            raise ProgramError("schema", f"vars[{i}] must have exactly keys name, lo, hi, oob, init; got {v!r}")
        _check_name(v["name"], f"vars[{i}]")
        names.append(v["name"])
        lo, hi, init = v["lo"], v["hi"], v["init"]
        nm = v["name"]
        if not (_isint(lo) and _isint(hi)) or not (-1000 <= lo < hi <= 1000):
            raise ProgramError(2, f"var {nm!r}: need ints -1000 <= lo < hi <= 1000, got lo={lo!r} hi={hi!r}")
        if hi - lo > 400:
            raise ProgramError(2, f"var {nm!r}: hi - lo = {hi - lo} > 400")
        if v["oob"] not in ("clamp", "crash"):
            raise ProgramError(2, f"var {nm!r}: oob must be 'clamp' or 'crash', got {v['oob']!r}")
        if not _islist(init) or not init or not all(_isint(x) for x in init):
            raise ProgramError(2, f"var {nm!r}: init must be a non-empty list of ints, got {init!r}")
        if any(b <= a for a, b in zip(init, init[1:])):
            raise ProgramError(2, f"var {nm!r}: init must be strictly increasing, got {list(init)}")
        if init[0] < lo or init[-1] > hi:
            raise ProgramError(2, f"var {nm!r}: init {list(init)} outside [{lo}, {hi}]")
        space *= hi - lo + 1
        n_start *= len(init)
    if space > 2**62:
        raise ProgramError(2, f"product of var ranges {space} > 2^62")
    if n_start > 64:
        raise ProgramError(2, f"product of len(init) = {n_start} > 64 start states")
    # rule 1 + 3: controls
    for i, c in enumerate(cs):
        if not isinstance(c, dict) or set(c) != {"name", "opts"}:
            raise ProgramError("schema", f"controls[{i}] must have exactly keys name, opts; got {c!r}")
        _check_name(c["name"], f"controls[{i}]")
        names.append(c["name"])
        o = c["opts"]
        nm = c["name"]
        if not _islist(o) or len(o) != 3:
            raise ProgramError(3, f"control {nm!r}: opts must have exactly 3 entries, got {o!r}")
        if not _isint(o[1]):
            raise ProgramError(3, f"control {nm!r}: opts[1] (KEEP) must be an int, got {o[1]!r}")
        for x in (o[0], o[2]):
            if x is not None and not _isint(x):
                raise ProgramError(3, f"control {nm!r}: opts[0] and opts[2] must be int or null, got {o!r}")
        vals = [x for x in o if x is not None]
        if any(abs(x) > 10 for x in vals):
            raise ProgramError(3, f"control {nm!r}: option values must be in [-10, 10], got {o!r}")
        if len(set(vals)) != len(vals):
            raise ProgramError(3, f"control {nm!r}: non-null option values must be distinct, got {o!r}")
    if len(set(names)) != len(names):
        dup = sorted({n for n in names if names.count(n) > 1})
        raise ProgramError(1, f"var/control names must be distinct (one namespace); duplicated: {dup}")
    var_names, ctl_names = {v["name"] for v in vs}, {c["name"] for c in cs}
    # rule 4: rand
    if rand is not None:
        if not _islist(rand) or not 1 <= len(rand) <= 5:
            raise ProgramError(4, f"rand must be null or a list of 1..5 [value, weight] pairs, got {rand!r}")
        for pr in rand:
            if not _islist(pr) or len(pr) != 2 or not _isint(pr[0]) or not _isint(pr[1]):
                raise ProgramError(4, f"rand entries must be [int value, int weight], got {pr!r}")
        rv = [pr[0] for pr in rand]
        if any(b <= a for a, b in zip(rv, rv[1:])):
            raise ProgramError(4, f"rand values must be distinct and strictly increasing, got {rv}")
        if any(abs(x) > 10 for x in rv):
            raise ProgramError(4, f"rand values must be in [-10, 10], got {rv}")
        if any(pr[1] < 1 for pr in rand):
            raise ProgramError(4, f"rand weights must be ints >= 1, got {[pr[1] for pr in rand]}")
        if sum(pr[1] for pr in rand) > 1000:
            raise ProgramError(4, f"rand total weight {sum(pr[1] for pr in rand)} > 1000")
    has_rand = rand is not None
    # rules (rule 5/6 for content)
    rules = p["rules"]
    if not _islist(rules) or not 1 <= len(rules) <= 24:
        raise ProgramError("schema", f"rules must be a list of 1..24 rules, got {len(rules) if _islist(rules) else rules!r}")
    rctx = (var_names, ctl_names, has_rand, False)
    for i, r in enumerate(rules):
        if not isinstance(r, dict) or not ({"set", "to"} <= set(r) <= {"set", "to", "if"}):
            raise ProgramError("schema", f"rules[{i}] must have keys set, to and optionally if; got {r!r}")
        if "if" in r and not isinstance(r["if"], dict):
            raise ProgramError("schema", f"rules[{i}]: 'if' must be a PRED (omit the key for an unconditional rule)")
        if r["set"] not in var_names:
            raise ProgramError("schema", f"rules[{i}]: 'set' must name a var, got {r['set']!r}")
        _check_expr(r["to"], f"rules[{i}].to", *rctx)
        if "if" in r:
            _check_pred(r["if"], f"rules[{i}].if", 1, rctx)
    # crash / goal (rule 6/7)
    crash = p["crash"]
    if not _islist(crash) or len(crash) > 8:
        raise ProgramError("schema", f"crash must be a list of 0..8 PREDs, got {crash!r}")
    gctx = (var_names, ctl_names, has_rand, True)
    n_items = _check_pred(p["goal"], "goal", 1, gctx)
    for i, q in enumerate(crash):
        n_items += _check_pred(q, f"crash[{i}]", 1, gctx)
    if n_items > 16:
        raise ProgramError(7, f"goal + crash use {n_items} comparison items > 16")
    # rule 8: start states
    vidx = {v["name"]: i for i, v in enumerate(vs)}
    for s in itertools.product(*[v["init"] for v in vs]):
        if eval_pred_vars(p["goal"], s, vidx):
            raise ProgramError(8, f"start state {dict(zip(vidx, s))} satisfies the goal")
        for i, q in enumerate(crash):
            if eval_pred_vars(q, s, vidx):
                raise ProgramError(8, f"start state {dict(zip(vidx, s))} satisfies crash[{i}]")


def is_valid(program: dict) -> bool:
    try:
        validate(program)
    except ProgramError:
        return False
    return True


# small scalar evaluator for var-only predicates (rule 8); interp.py has the full compiled evaluator


def _atom_vars(a: str, x, vidx) -> int:
    kind, name = parse_atom(a)
    v = x[vidx[name]]
    return v if kind == K_VAR else abs(v) if kind == K_ABS else (v > 0) - (v < 0)


def _cmp(v: int, op: str, c: int) -> bool:
    return {"<=": v <= c, ">=": v >= c, "==": v == c, "!=": v != c, "<": v < c, ">": v > c}[op]


def eval_pred_vars(p: dict, x, vidx: dict) -> bool:
    ((kind, items),) = p.items()
    res = []
    for it in items:
        if isinstance(it, dict):
            res.append(eval_pred_vars(it, x, vidx))
        else:
            e, op, c = it
            res.append(_cmp(e["k"] + sum(cf * _atom_vars(a, x, vidx) for cf, a in e["t"]), op, c))
    return all(res) if kind == "all" else any(res)


# ---------------------------------------------------------------------------------------------- text syntax

_TOKEN_RE = re.compile(r"\s*(?:(?P<int>\d+)|(?P<sym><=|>=|==|!=|:=|<|>|:|\(|\)|,|\+|-|\*)|(?P<word>\$w|@?[a-z][a-z0-9_]*))")


def _tokenize(s: str) -> list[str]:
    toks, pos = [], 0
    s = s.rstrip()
    while pos < len(s):
        m = _TOKEN_RE.match(s, pos)
        if m is None or m.end() == pos:
            raise ProgramError("syntax", f"unexpected character {s[pos:].strip()[:1]!r} at {pos} in {s!r}")
        toks.append(m.group("int") or m.group("sym") or m.group("word"))
        pos = m.end()
    return toks


class _Parser:
    def __init__(self, s: str):
        self.s = s
        self.t = _tokenize(s)
        self.i = 0

    def peek(self, k: int = 0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else None

    def take(self, want: str | None = None) -> str:
        tok = self.peek()
        if tok is None or (want is not None and tok != want):
            raise ProgramError("syntax", f"expected {want or 'a token'!r} at token {self.i} ({tok!r}) in {self.s!r}")
        self.i += 1
        return tok

    def done(self) -> None:
        if self.peek() is not None:
            raise ProgramError("syntax", f"unexpected trailing {' '.join(self.t[self.i:])!r} in {self.s!r}")

    def atom(self) -> str:
        tok = self.take()
        if tok in ("abs", "sgn") and self.peek() == "(":
            self.take("(")
            inner = self.take()
            if not re.match(r"^@?[a-z]", inner) or (inner.startswith("@") and tok == "sgn"):
                raise ProgramError("syntax", f"bad argument {inner!r} of {tok}() in {self.s!r}")
            self.take(")")
            return f"{tok}({inner})"
        if not (tok == "$w" or re.match(r"^@?[a-z]", tok)):
            raise ProgramError("syntax", f"expected an atom, got {tok!r} in {self.s!r}")
        return tok

    def expr(self) -> dict:
        terms, k = [], 0
        sign = 1
        if self.peek() in ("+", "-"):
            sign = -1 if self.take() == "-" else 1
        while True:
            tok = self.peek()
            if tok is not None and tok.isdigit():
                n = int(self.take())
                if self.peek() == "*":
                    self.take("*")
                    terms.append([sign * n, self.atom()])
                else:
                    k += sign * n
            else:
                terms.append([sign, self.atom()])
            if self.peek() in ("+", "-"):
                sign = -1 if self.take() == "-" else 1
            else:
                break
        return canon_expr({"t": terms, "k": k})

    def cmp(self) -> list:
        lhs = self.expr()
        op = self.take()
        if op not in OPS:
            raise ProgramError("syntax", f"expected a comparison operator, got {op!r} in {self.s!r}")
        rhs = self.expr()
        e = canon_expr({"t": lhs["t"] + [[-c, a] for c, a in rhs["t"]], "k": lhs["k"]})
        return [e, op, rhs["k"]]

    def is_pred_start(self) -> bool:
        return self.peek() in ("all", "any") and self.peek(1) == "("

    def pred(self) -> dict:
        if not self.is_pred_start():
            return {"all": [self.cmp()]}
        kind = self.take()
        self.take("(")
        items = [self.item()]
        while self.peek() == ",":
            self.take(",")
            items.append(self.item())
        self.take(")")
        return {kind: items}

    def item(self):
        return self.pred() if self.is_pred_start() else self.cmp()

    def rule(self) -> dict:
        if self.peek() == "if" and self.peek(1) != ":=":
            self.take("if")
            guard = self.pred()
            self.take(":")
            target = self.take()
            self.take(":=")
            return {"set": target, "to": self.expr(), "if": guard}
        target = self.take()
        self.take(":=")
        return {"set": target, "to": self.expr()}


def expr(s: str) -> dict:
    """Text EXPR -> canonical §1 EXPR, e.g. expr("pos + 2*vel - @drive - 3")."""
    p = _Parser(s)
    e = p.expr()
    p.done()
    return e


def pred(s: str) -> dict:
    """Text PRED -> canonical §1 PRED, e.g. pred("all(pos >= 3, any(abs(vel) <= 1, fuel == 0))")."""
    p = _Parser(s)
    out = p.pred()
    p.done()
    return out


def rule(s: str) -> dict:
    """Text rule -> canonical §1 rule dict, e.g. rule("if fuel >= 1: vel := vel + @thrust")."""
    p = _Parser(s)
    r = p.rule()
    p.done()
    return r


def var(name: str, lo: int, hi: int, init, oob: str = "clamp") -> dict:
    """Var helper; ``init`` may be an int or an iterable of ints."""
    init = [init] if _isint(init) else list(init)
    return {"name": name, "lo": lo, "hi": hi, "oob": oob, "init": init}


def control(name: str, opts) -> dict:
    """Control helper; ``opts`` = [DEC value or None, KEEP value, INC value or None]."""
    return {"name": name, "opts": list(opts)}


def program(vars, controls, rules, goal, rand=None, crash=()) -> dict:
    """Assemble, validate and canonicalize a program. Rules/crash/goal may be text or §1 dicts; ``rand`` is None,
    a list of [value, weight] pairs, or a dict {value: weight}."""
    if isinstance(rand, dict):
        rand = [[v, w] for v, w in sorted(rand.items())]
    elif rand is not None:
        rand = [[v, w] for v, w in rand]
    p = {
        "dsl": DSL,
        "vars": [dict(v) for v in vars],
        "controls": [dict(c) for c in controls],
        "rand": rand,
        "rules": [rule(r) if isinstance(r, str) else r for r in rules],
        "crash": [pred(q) if isinstance(q, str) else q for q in crash],
        "goal": pred(goal) if isinstance(goal, str) else goal,
    }
    validate(p)
    return canonicalize(p)


# ---------------------------------------------------------------------------------------------- render / parse


def render_expr(e: dict, order: dict | None = None) -> str:
    """EXPR text; ``order`` (atom -> sort key) only changes the printed term order (vars, controls, $w)."""
    out = []
    terms = e["t"] if order is None else sorted(e["t"], key=lambda t: order.get(t[1], (9, 0, 0)))
    for c, a in terms:
        mag = abs(c)
        body = a if mag == 1 else f"{mag}*{a}"
        if not out:
            out.append(("-" if c < 0 else "") + body)
        else:
            out.append(("- " if c < 0 else "+ ") + body)
    k = e["k"]
    if not out:
        return str(k)
    if k:
        out.append(("- " if k < 0 else "+ ") + str(abs(k)))
    return " ".join(out)


def render_pred(p: dict, order: dict | None = None) -> str:
    ((kind, items),) = p.items()
    parts = [render_pred(it, order) if isinstance(it, dict) else f"{render_expr(it[0], order)} {it[1]} {it[2]}"
             for it in items]
    return f"{kind}({', '.join(parts)})"


def render_rule(r: dict, order: dict | None = None) -> str:
    body = f"{r['set']} := {render_expr(r['to'], order)}"
    return f"if {render_pred(r['if'], order)}: {body}" if "if" in r else body


def atom_order(program: dict) -> dict:
    """Readable term order for rendering: vars (program order; x, abs(x), sgn(x)), then controls, then $w."""
    o: dict = {"$w": (2, 0, 0)}
    for i, v in enumerate(program["vars"]):
        n = v["name"]
        o.update({n: (0, i, 0), f"abs({n})": (0, i, 1), f"sgn({n})": (0, i, 2)})
    for i, c in enumerate(program["controls"]):
        n = c["name"]
        o.update({"@" + n: (1, i, 0), f"abs(@{n})": (1, i, 1)})
    return o


def _opt(x) -> str:
    return "none" if x is None else str(x)


def render(program: dict) -> str:
    """Readable rulebook text of a program (canonical form). ``parse(render(p)) == canonicalize(p)``."""
    p = canonicalize(program)
    order = atom_order(p)
    L = [f"machine {p['dsl']}", "vars:"]
    for v in p["vars"]:
        L.append(f"  {v['name']} in [{v['lo']}, {v['hi']}], start {{{', '.join(map(str, v['init']))}}}, "
                 f"out of range: {v['oob']}")
    L.append("controls:")
    for c in p["controls"]:
        o = c["opts"]
        L.append(f"  @{c['name']}: DEC {_opt(o[0])}, KEEP {_opt(o[1])}, INC {_opt(o[2])}")
    if p["rand"] is None:
        L.append("random $w: none")
    else:
        W = sum(w for _v, w in p["rand"])
        L.append("random $w each tick:")
        for v, w in p["rand"]:
            L.append(f"  {v} with probability {w}/{W}")
    L.append("rules (in order, each tick):")
    for i, r in enumerate(p["rules"], 1):
        L.append(f"  {i}. {render_rule(r, order)}")
    if p["crash"]:
        L.append("crash if any holds:")
        for i, q in enumerate(p["crash"], 1):
            L.append(f"  {i}. {render_pred(q, order)}")
    else:
        L.append("crash if any holds: none")
    L.append(f"goal: {render_pred(p['goal'], order)}")
    return "\n".join(L) + "\n"


_VAR_LINE = re.compile(r"^(\S+) in \[(-?\d+), (-?\d+)\], start \{([-\d, ]+)\}, out of range: (clamp|crash)$")
_CTL_LINE = re.compile(r"^@(\S+): DEC (none|-?\d+), KEEP (-?\d+), INC (none|-?\d+)$")
_RAND_LINE = re.compile(r"^(-?\d+) with probability (\d+)/(\d+)$")
_NUM_LINE = re.compile(r"^(\d+)\. (.*)$")


def parse(text: str) -> dict:
    """Parse a rulebook produced by ``render`` back into a validated canonical program."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    head = lines[0].split()
    if len(head) != 2 or head[0] != "machine":
        raise ProgramError("syntax", f"rulebook must start with 'machine <dsl>', got {lines[0]!r}")
    p: dict = {"dsl": head[1], "vars": [], "controls": [], "rand": None, "rules": [], "crash": [], "goal": None}
    sec = None
    for ln in lines[1:]:
        s = ln.strip()
        if not ln.startswith("  "):
            if s == "vars:":
                sec = "vars"
            elif s == "controls:":
                sec = "controls"
            elif s == "random $w: none":
                sec, p["rand"] = None, None
            elif s == "random $w each tick:":
                sec, p["rand"] = "rand", []
            elif s.startswith("rules"):
                sec = "rules"
            elif s == "crash if any holds: none":
                sec = None
            elif s == "crash if any holds:":
                sec = "crash"
            elif s.startswith("goal: "):
                p["goal"], sec = pred(s[len("goal: "):]), None
            else:
                raise ProgramError("syntax", f"unknown rulebook line {ln!r}")
            continue
        if sec == "vars":
            m = _VAR_LINE.match(s)
            if not m:
                raise ProgramError("syntax", f"bad var line {s!r}")
            init = [int(x) for x in m.group(4).split(",")]
            p["vars"].append(var(m.group(1), int(m.group(2)), int(m.group(3)), init, m.group(5)))
        elif sec == "controls":
            m = _CTL_LINE.match(s)
            if not m:
                raise ProgramError("syntax", f"bad control line {s!r}")
            o = [None if x == "none" else int(x) for x in m.group(2, 3, 4)]
            p["controls"].append(control(m.group(1), o))
        elif sec == "rand":
            m = _RAND_LINE.match(s)
            if not m:
                raise ProgramError("syntax", f"bad random line {s!r}")
            p["rand"].append([int(m.group(1)), int(m.group(2))])
        elif sec in ("rules", "crash"):
            m = _NUM_LINE.match(s)
            if not m:
                raise ProgramError("syntax", f"bad numbered line {s!r}")
            p[sec].append(rule(m.group(2)) if sec == "rules" else pred(m.group(2)))
        else:
            raise ProgramError("syntax", f"indented line outside a section: {ln!r}")
    if p["goal"] is None:
        raise ProgramError("syntax", "rulebook has no goal line")
    validate(p)
    return canonicalize(p)
