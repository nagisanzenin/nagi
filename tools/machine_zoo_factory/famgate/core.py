# SPDX-License-Identifier: Apache-2.0
"""Machine family gate (famgate): the validator core of the Machine Zoo family factory.

A family is ONE Python file with FAMILY / PARAMS / build(p) -> mz-1x program / prose(p) -> natural-language
rulebook (format: GATES.md §1; language: docs/DSL_REFERENCE.md). The gate runs the frozen mz-1x gates unchanged
(xgates.run_gates = X0, X1, G2-G8, X3, X4d, X4h, X5; x6.blind_equivalence = X6) and adds the family checks
(thresholds frozen 2026-10-12 in the research gate v2g-famgate-v1 and kept identical here; rationale in GATES.md):

  V0  module contract: AST import allow-list, no I/O / dynamic code / hash() / id(), FAMILY schema, PARAMS grid
  V1  DSL parse + exact render/parse round trip of the served rulebook (xdsl.render_rulebook -> parse_rulebook_x)
  V2  determinism: build(p) twice (fresh dict copies) -> byte-identical canonical JSON; build does not mutate p
  V3  oracle (exact V-infinity label policy, uniform start, 100-tick cap) success >= oracle_min (0.95)
  V4  non-triviality: keep <= 0.20 (G5), greedy/weak <= 0.80 (G6), random <= 0.50, probe4 <= 0.80 (exact chains)
  V5  strata tags verified by execution (delay X4d, hidden X3+X4h, long median >= 20, interlock, axes3, budgets)
  V6  engine size limits: X1 (|S| <= 60k, |S_x| <= 100k, views <= 200k), rules <= 24, rulebook <= 3,200 chars,
      gate time per instance <= 120 s
  P1  prose rulebook: present, 400..6000 chars, deterministic, no DSL syntax (no := @ $w all( any( abs( sgn(
      < > = KEEP/DEC/INC), word 5-gram overlap with the DSL rulebook <= 0.10, and the exact parser REJECTS it
      (whole text as a rulebook, every line/sentence as a rule or predicate)
  P2  prose completeness checklist: every var/control identifier verbatim (>= 3 chars; identity name map), every
      range/start/option/rule/crash/goal number, tick order, crash beats goal, delay, hidden vars + window, chance
      -- a screen; the binding test is the blind sufficiency review (prose_check.py must print EXACT)
  V7  near-duplicates vs every INDEXED family: no shared mz-1x signature, WL structural similarity < 0.60, prose
      5-gram twin < 0.35, unique name. The index is built by the caller (validate.py): the job's own PASSED
      families, the bundled examples and any directory the user passes (e.g. the published Machine Zoo families).
      Nothing is indexed implicitly.

Every probability is an exact chain value (no Monte Carlo).
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import itertools
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, replace

import numpy as np

from . import _runtime  # noqa: F401  (puts the engine on the path and registers the family-file import names)
from . import xgates
from nagi.burst2._rt.bv2n.zoo_new import xdsl  # noqa: E402
from nagi.burst2._rt.bv2n.zoo_new import xteacher as _xt  # noqa: E402
from nagi.burst2._rt.machine_zoo import dsl, tokens  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
GATE_VERSION = "machine-zoo-factory-v1 (= v2g-famgate-v1 thresholds)"
STRATA = ("delay", "hidden", "long", "interlock", "axes3", "budget", "multibudget")
XFEATURES = ("delay", "hidden", "long")  # the mz-1x feature tags that xgates verifies
NAME_RE = re.compile(r"[a-z][a-z0-9_]{2,40}")
FAMILY_KEYS_REQ = ("name", "domain_id", "batch", "slot", "author", "title", "story", "strata")
FAMILY_KEYS_OPT = ("mode_var", "budget_vars")
ALLOWED_IMPORT = {"math", "itertools", "__future__", "machine_zoo.dsl", "bv2n.zoo_new.xdsl"}
ALLOWED_FROM = {"machine_zoo": {"dsl"}, "bv2n.zoo_new": {"xdsl"}, "math": None, "itertools": None,
                "__future__": None}
FORBIDDEN_CALLS = {"open", "exec", "eval", "compile", "__import__", "input", "globals", "locals", "vars",
                   "breakpoint", "hash", "id", "setattr", "getattr", "delattr", "print"}


@dataclass(frozen=True)
class Profile:
    """Frozen thresholds (2026-10-12, set before any family of the research job existed; identical here)."""

    name: str
    inst_salt: str
    oracle_min: float = 0.95  # V3 (the frozen mz-1x G2 floor is 0.90; families are stricter)
    keep_max: float = 0.20  # V4 = G5
    weak_max: float = 0.80  # V4 = G6 (greedy bot on the true state, delay-blind)
    random_max: float = 0.50  # V4 (uniform random joint)
    probe4_max: float = 0.80  # V4 (lexicographic 1-tick + 4-tick look-ahead probe on the true state, delay-blind)
    load_succ: float = 0.20  # V5 load-bearing margin (same as X4)
    load_ret: float = 10.0
    long_median: int = 20  # V5 long = X5
    mode_values_min: int = 3  # V5 interlock: >= 3 mode values each with oracle visit share >= 0.05
    mode_share_min: float = 0.05
    mode_range_max: int = 8
    mode_interlock_rules_min: int = 2
    axes_decisive_min: float = 0.10  # V5 axes3: every one of the 3 control slots decisive on >= 10% of visits
    min_pass: int = 6
    keep_max_inst: int = 10
    grid_min: int = 8
    grid_max: int = 64
    max_rules: int = 24  # V6
    max_rulebook_chars: int = 3200
    max_inst_seconds: float = 120.0
    require_prose: bool = True  # prose rulebook per instance (P1, P2) + optional glossary
    prose_min_chars: int = 400
    prose_max_chars: int = 6000
    prose_dsl_overlap_max: float = 0.10  # word 5-gram Jaccard prose vs served DSL rulebook
    prose_twin_max: float = 0.35  # word 5-gram Jaccard prose vs any other indexed family's prose (template reuse)
    dup_wl_max: float = 0.60  # V7: 201 hand-authored families max 0.50 (p99.9 0.27); one-edit re-skins 0.50-0.93
    x6: bool = True


PROFILES = {
    # Identical values (instance salt included) to the research profiles, so a published family re-validates to the
    # same kept instances: "train" = v2g-train (keep up to 10 instances), "benchmark" = the research evaluation-set
    # profile (keep up to 6 instances, different instance salt).
    "train": Profile("train", "v2g-fam-inst-v0"),
    "benchmark": Profile("benchmark", "v2g-zud-scan-v0", keep_max_inst=6),
}


# ============================================================================== mz-1x rulebook parse (V1)
_DELAY_RE = re.compile(r"reply delay: (\d+) ticks?(?: \(a command decided now is applied that many ticks later; "
                       r"KEEP is in flight at start\))?")
_HID_RE = re.compile(r"hidden vars \(never displayed\): ([a-z0-9_, ]+)")
_WIN_RE = re.compile(r"history shown: last (\d+) displayed observations")


def parse_rulebook_x(text: str) -> dict:
    """Exact inverse of xdsl.render_rulebook: rulebook text -> validated canonical mz-1x program."""
    marker = "extension mz-1x:\n"
    if marker not in text:
        return xdsl.make(dsl.parse(text))
    base_txt, ext = text.split(marker, 1)
    base = dsl.parse(base_txt)
    lines = [ln.strip() for ln in ext.splitlines() if ln.strip()]
    m = _DELAY_RE.fullmatch(lines[0]) if lines else None
    if not m:
        raise ValueError(f"bad delay line {lines[:1]}")
    d = int(m.group(1))
    if len(lines) == 2 and lines[1] == "hidden vars: none":
        return xdsl.make(base, delay=d)
    if len(lines) != 3:
        raise ValueError("extension block must have 2 or 3 lines")
    mh, mw = _HID_RE.fullmatch(lines[1]), _WIN_RE.fullmatch(lines[2])
    if not (mh and mw):
        raise ValueError(f"bad hidden/window lines {lines[1:]}")
    return xdsl.make(base, delay=d, hidden=[h.strip() for h in mh.group(1).split(",")], window=int(mw.group(1)))


def roundtrip_ok(px: dict) -> tuple[bool, str]:
    txt = xdsl.render_rulebook(px)
    try:
        back = parse_rulebook_x(txt)
    except Exception as ex:  # noqa: BLE001
        return False, f"parse failed: {type(ex).__name__}: {ex}"
    if xdsl.canonical_json(back) != xdsl.canonical_json(px):
        return False, "parse(render(px)) != px"
    if xdsl.render_rulebook(back) != txt:
        return False, "render(parse(text)) != text"
    return True, ""


# ============================================================================== module loading (V0)
def file_sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_module(path: str):
    """Import a family file under a unique module name (no package needed)."""
    sha = file_sha256(path)[:12]
    stem = os.path.splitext(os.path.basename(path))[0]
    modname = f"_mzfam_{stem}_{sha}"
    if modname in sys.modules:
        return sys.modules[modname]
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules[modname] = mod
    return mod


def static_errors(source: str) -> list[str]:
    errs = []
    try:
        tree = ast.parse(source)
    except SyntaxError as ex:
        return [f"syntax error: {ex}"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name not in ALLOWED_IMPORT:
                    errs.append(f"line {node.lineno}: import {a.name} not allowed")
        elif isinstance(node, ast.ImportFrom):
            mod = "." * node.level + (node.module or "")
            if mod not in ALLOWED_FROM:
                errs.append(f"line {node.lineno}: from {mod} import ... not allowed")
            elif ALLOWED_FROM[mod] is not None and any(a.name not in ALLOWED_FROM[mod] for a in node.names):
                errs.append(f"line {node.lineno}: from {mod} import {[a.name for a in node.names]} not allowed")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            errs.append(f"line {node.lineno}: call to {node.func.id}() not allowed in a family module")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr not in ("__name__",):
            errs.append(f"line {node.lineno}: dunder attribute {node.attr} not allowed")
    return errs


def schema_errors(F, P, prof: Profile, stem: str, strict: bool = True, mod=None) -> list[str]:
    errs = []
    if not isinstance(F, dict) or not isinstance(P, dict):
        return ["module needs FAMILY dict, PARAMS dict and build(p)"]
    if strict:
        miss = [k for k in FAMILY_KEYS_REQ if k not in F]
        extra = [k for k in F if k not in FAMILY_KEYS_REQ + FAMILY_KEYS_OPT]
        if miss or extra:
            errs.append(f"FAMILY keys: missing {miss}, unknown {extra}")
        for k in ("name", "domain_id", "batch", "author", "title", "story"):
            if not (isinstance(F.get(k), str) and F.get(k, "").strip()):
                errs.append(f"FAMILY[{k!r}] must be a non-empty string")
        if not (isinstance(F.get("slot"), int) and not isinstance(F.get("slot"), bool)):
            errs.append("FAMILY['slot'] must be an int")
    if F.get("name") != stem or not NAME_RE.fullmatch(str(F.get("name"))):
        errs.append(f"FAMILY['name'] must equal the file stem {stem!r} and match {NAME_RE.pattern}")
    st = F.get("strata")
    if not isinstance(st, list) or not st or not set(st) <= set(STRATA) or len(set(st)) != len(st):
        errs.append(f"FAMILY['strata'] must be a non-empty list of distinct tags from {STRATA}")
    st = set(st or [])
    if "interlock" in st and not isinstance(F.get("mode_var"), str):
        errs.append("strata 'interlock' needs FAMILY['mode_var'] (a base var name)")
    if ("budget" in st or "multibudget" in st):
        bv = F.get("budget_vars")
        need = 2 if "multibudget" in st else 1
        if not (isinstance(bv, list) and len(bv) >= need and all(isinstance(b, str) for b in bv)):
            errs.append(f"strata budget/multibudget needs FAMILY['budget_vars'] with >= {need} var names")
    if "mode_var" in F and "interlock" not in st:
        errs.append("FAMILY['mode_var'] given but 'interlock' not declared")
    if "budget_vars" in F and not ({"budget", "multibudget"} & st):
        errs.append("FAMILY['budget_vars'] given but no budget stratum declared")
    if prof.require_prose:
        mod_prose, gl = getattr(mod, "prose", None), getattr(mod, "GLOSSARY", None)
        if not callable(mod_prose):
            errs.append("module needs prose(p) -> str (the natural-language rulebook of the instance)")
        if gl is not None and not (isinstance(gl, dict) and all(isinstance(k, str) and isinstance(v, str)
                                                                for k, v in gl.items())):
            errs.append("GLOSSARY (optional) must map identifier -> plain-words description")
    if not 2 <= len(P) <= 5 or any(not isinstance(v, list) or not v or len(set(v)) != len(v) or
                                   any(type(x) is not int for x in v) for v in P.values()):
        errs.append("PARAMS: 2..5 params, each a non-empty list of distinct ints")
    else:
        n = 1
        for v in P.values():
            n *= len(v)
        if not prof.grid_min <= n <= prof.grid_max:
            errs.append(f"grid size {n} not in {prof.grid_min}..{prof.grid_max}")
    return errs


def instance_order(name: str, P: dict, salt: str) -> list[dict]:
    keys = sorted(P)
    pts = [dict(zip(keys, vals)) for vals in itertools.product(*[P[k] for k in keys])]
    return sorted(pts, key=lambda p: hashlib.sha256(
        (f"{salt}|{name}|" + json.dumps(p, sort_keys=True, separators=(",", ":"))).encode()).hexdigest())


def as_px(prog: dict) -> dict:
    """mz-1 programs (no delay, nothing hidden) are plain mz-1x programs."""
    if isinstance(prog, dict) and prog.get("dsl") == "mz-1":
        return xdsl.make(prog)
    return prog


def build_twice(mod, p: dict) -> tuple[dict | None, str]:
    """V2 determinism: two builds on fresh copies; returns (px, error)."""
    p1, p2 = dict(p), dict(p)
    a = as_px(mod.build(p1))
    b = as_px(mod.build(p2))
    if p1 != p or p2 != p:
        return None, "build mutated its params dict"
    xdsl.validate(a)
    if xdsl.canonical_json(a) != xdsl.canonical_json(b):
        return None, "build is not deterministic (two builds differ)"
    return xdsl.canonicalize(a), ""


# ============================================================================== extra exact probes (V4, V5)
def _onehot(idx, nv):
    P = np.zeros((len(idx), nv))
    P[np.arange(len(idx)), idx] = 1.0
    return P


def pol_probe4(T) -> np.ndarray:
    """probe4 (machine_zoo.tokens.probe4_keys, a descriptive look-ahead baseline), delay-blind, uniform over its
    lexicographic-minimal candidates. Fully observed programs: on the TRUE base state. Hidden programs: probe4_blind =
    memoryless on what the client sees (current displayed obs + in-flight queue): the joints that are probe4
    candidates for the largest share of consistent augmented states (uniform), so the probe never reads hidden
    values."""
    cp = tokens.Compiled(T.base_program)
    pos = {int(j): k for k, j in enumerate(T.valid)}
    X = np.asarray(T.base.X, np.int64)
    cand = np.zeros((len(X), T.nv), bool)
    for s in range(0, len(X), 512):
        vj, K = tokens.probe4_keys(cp, X[s:s + 512])
        cols = np.array([pos[int(j)] for j in vj])
        mask = np.ones(K.shape[:2], bool)
        for k in range(K.shape[2]):
            kk = np.where(mask, K[:, :, k], np.iinfo(np.int64).max)
            mask &= kk == kk.min(axis=1, keepdims=True)
        blk = np.zeros((len(K), T.nv), bool)
        blk[:, cols] = mask
        cand[s:s + 512] = blk
    c = cand[T.aug_base].astype(np.float64)
    if T.hidden:  # probe4_blind: the client sees only displayed vars -> candidate frequency over the observation group
        grp = T.oc.astype(np.int64) * T.M + (T.codes % T.M)
        _u, inv = np.unique(grp, return_inverse=True)
        inv = inv.reshape(-1)
        freq = np.zeros((len(_u), T.nv))
        np.add.at(freq, inv, c)
        best = freq >= freq.max(axis=1, keepdims=True) - 1e-12
        c = best[inv].astype(np.float64)
    return c / c.sum(axis=1, keepdims=True)


def pol_var_blind(T, cols: list[int]) -> np.ndarray:
    """Feature-ablation probe: acts on the TRUE augmented state with the given base var columns marginalised out
    (argmax of the uniform average Q over reachable augmented states that agree on every other var and the queue;
    lowest index on ties). Same construction as xteacher.pol_memoryless."""
    X = np.asarray(T.base.X)
    keep = [c for c in range(X.shape[1]) if c not in set(cols)]
    if keep:
        _u, ib = np.unique(X[:, keep], axis=0, return_inverse=True)
        ib = ib.reshape(-1)
    else:
        ib = np.zeros(len(X), np.int64)
    g = ib[T.aug_base].astype(np.int64) * T.M + (T.codes % T.M)
    _u, inv = np.unique(g, return_inverse=True)
    inv = inv.reshape(-1)
    meanQ = np.zeros((len(_u), T.nv))
    np.add.at(meanQ, inv, T.Qv)
    meanQ /= np.bincount(inv, minlength=len(_u))[:, None]
    best = meanQ >= meanQ.max(axis=1, keepdims=True) - _xt.TOL
    return _onehot(np.argmax(best, axis=1)[inv], T.nv)


def _load(T, orc: dict, P, name: str, prof: Profile) -> dict:
    c = T.chain(P)
    ds, dr = orc["success"] - c["success"], orc["mean_return"] - c["mean_return"]
    return {"pass": bool(ds >= prof.load_succ or dr >= prof.load_ret), "probe": name,
            "probe_success": c["success"], "probe_return": c["mean_return"], "d_success": ds, "d_return": dr}


def _reads(expr: dict) -> list[tuple[int, str]]:
    return [dsl.parse_atom(a) for _c, a in expr["t"]]


def _pred_atoms(p: dict) -> list[tuple[int, str]]:
    ((_k, items),) = p.items()
    out = []
    for it in items:
        out += _pred_atoms(it) if isinstance(it, dict) else _reads(it[0])
    return out


def interlock_static(base: dict, m: str) -> dict:
    """Rules whose guard reads the mode var m and that read a control (in the guard or the assignment)."""
    n_lock, n_write = 0, 0
    for r in base["rules"]:
        if r["set"] == m:
            n_write += 1
        if "if" in r:
            g = _pred_atoms(r["if"])
            atoms = g + _reads(r["to"])
            if any(name == m and k in (dsl.K_VAR, dsl.K_ABS, dsl.K_SGN) for k, name in g) and \
                    any(k in (dsl.K_CMD, dsl.K_ABSCMD) for k, _n in atoms):
                n_lock += 1
    return {"interlock_rules": n_lock, "mode_writes": n_write}


# ============================================================================== prose rulebook (P1, P2)
_NUMWORD = {0: ("zero", "no ", "none", "empty"), 1: ("one", "a single", "once", " a ", " an ", "first"),
            2: ("two", "twice", "second", "pair"), 3: ("three", "third"), 4: ("four", "fourth"),
            5: ("five", "fifth"), 6: ("six", "sixth"), 7: ("seven",), 8: ("eight",), 9: ("nine",), 10: ("ten",),
            11: ("eleven",), 12: ("twelve", "dozen")}
_FAIL_W = ("crash", "fail", "lost", "lose", "destroy", "wreck", "broken", "break", "damage", "disaster", "abort",
           "ends badly", "game over", "accident", "collide", "collision", "tips", "sink", "explode", "burst")
_SUCC_W = ("goal", "success", "succeed", "done", "complete", "win", "mission", "finished", "objective", "target")
_PREC_W = ("before", "wins", "beats", "precedence", "priority", "overrides", "override", "even if", "even when",
           "counts as", "rather than", "first", "outranks", "trumps", "regardless")
_ORDER_W = ("in this order", "in order", "order", "sequence", "then", "after that", "next", "top to bottom",
            "one after", "afterwards", "step by step", "first")
_DELAY_W = ("late", "delay", "lag", "later", "after", "takes effect", "in flight", "queued", "pending")
_HID_W = ("hidden", "not shown", "never shown", "cannot see", "can't see", "cannot be seen", "not displayed",
          "never displayed", "invisible", "unseen", "no display", "not visible", "no gauge", "not reported",
          "isn't shown", "is not shown", "unknown", "no readout", "no sensor", "unobserved")
_DSL_RE = [re.compile(x, re.M) for x in (r":=", r"@[a-z]", r"\$w", r"\b(?:all|any|abs|sgn)\(", r"[<>=]",
                                          r"\bmz-1", r"\b(?:KEEP|DEC|INC)\b", r"out of range:", r"crash if any holds",
                                          r"extension mz-1x", r"^\s*\d+\.\s*if\b", r"\bif [^.\n]*:\s*[a-z_]+\b")]


def _words(t: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", t.lower())


def _grams(t: str, n: int = 5) -> set:
    w = _words(t)
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0


def _has_num(v: int, low: str, nums: set) -> bool:
    v = abs(int(v))
    return str(v) in nums or any(w in low for w in _NUMWORD.get(v, ()))


def _expr_consts(e: dict) -> list[int]:
    return ([e["k"]] if e["k"] else []) + [c for c, _a in e["t"] if abs(c) >= 2]


def _pred_consts(q: dict) -> list[int]:
    ((_k, items),) = q.items()
    out = []
    for it in items:
        out += _pred_consts(it) if isinstance(it, dict) else (_expr_consts(it[0]) + [it[2]])
    return out


def _sentences(low: str) -> list[str]:
    return [x for x in re.split(r"(?<=[.!?;:])\s+|\n+", low) if x.strip()]


def parser_accepts(text: str) -> list[str]:
    """P1: the exact parser must REJECT the prose. Returns what it accepted: the whole text as an
    mz-1 / mz-1x rulebook, or any line / sentence as a DSL rule or predicate (empty list = rejected)."""
    hits = []
    for f in (parse_rulebook_x, dsl.parse):
        try:
            f(text)
            hits.append("whole text parses as a rulebook")
            break
        except Exception:  # noqa: BLE001
            pass
    pieces = {x.strip(" .;:-*\t") for x in re.split(r"\n|(?<=[.;!?])\s+", text) if x.strip()}
    for x in sorted(pieces):
        for f in (dsl.rule, dsl.pred):
            try:
                f(x)
                hits.append(x[:60])
                break
            except Exception:  # noqa: BLE001
                pass
    return hits[:5]


def _has_name(name: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text) is not None


def prose_checks(px: dict, text, glossary: dict, prof: Profile) -> dict:
    """P1 (present, not a DSL copy) and P2 (completeness checklist). Returns {'P1': {...}, 'P2': {...}}."""
    out = {"P1": {"pass": False}, "P2": {"pass": False}}
    if not isinstance(text, str):
        out["P1"]["error"] = "prose(p) must return a str"
        return out
    n = len(text)
    dsl_hits = sorted({m.group(0) for rx in _DSL_RE for m in rx.finditer(text)})[:12]
    ov = jaccard(_grams(text), _grams(xdsl.render_rulebook(px)))
    parsed = parser_accepts(text)
    out["P1"] = {"chars": n, "dsl_hits": dsl_hits, "dsl_5gram_jaccard": round(ov, 4), "parser_accepts": parsed,
                 "pass": bool(prof.prose_min_chars <= n <= prof.prose_max_chars and not dsl_hits
                              and ov <= prof.prose_dsl_overlap_max and not parsed)}
    low = " " + re.sub(r"\s+", " ", text.lower()) + " "
    nums = set(re.findall(r"\d+", low))
    sents = _sentences(low)
    base = px["base"]
    names = [v["name"] for v in base["vars"]] + [c["name"] for c in base["controls"]]
    term = {k: k.lower() for k in names}  # identity name map -> names appear verbatim
    miss: list[str] = []

    def need(cond, item):
        if not cond:
            miss.append(item)

    for k in names:
        need(len(k) >= 3, f"identifier {k!r} shorter than 3 chars (use a descriptive name; it must appear verbatim)")
        need(_has_name(k, text), f"identifier {k!r} does not appear verbatim in the prose")
    for v in base["vars"]:
        for c in sorted({v["lo"], v["hi"], *v["init"]}):
            need(_has_num(c, low, nums), f"var {v['name']}: number {c} (range/start) absent")
        if v["oob"] == "crash":
            need(any(_has_name(term[v["name"]], x) and any(w in x for w in _FAIL_W) for x in sents),
                 f"var {v['name']}: leaving its range is a failure, not stated next to its term")
    for c in base["controls"]:
        for o in c["opts"]:
            if o is not None:
                need(_has_num(o, low, nums), f"control {c['name']}: option value {o} absent")
    for i, r in enumerate(base["rules"], 1):
        consts = _expr_consts(r["to"]) + (_pred_consts(r["if"]) if "if" in r else [])
        for c in consts:
            need(_has_num(c, low, nums), f"rule {i} ({r['set']}): number {c} absent")
    for i, q in enumerate(base["crash"], 1):
        for c in _pred_consts(q):
            need(_has_num(c, low, nums), f"crash {i}: number {c} absent")
    for c in _pred_consts(base["goal"]):
        need(_has_num(c, low, nums), f"goal: number {c} absent")
    need(any(w in low for w in _FAIL_W) or not base["crash"], "no failure/crash wording")
    need(any(w in low for w in _SUCC_W), "no goal/success wording")
    need(any(w in low for w in _ORDER_W), "tick ordering (the updates happen in a stated order) not described")
    need(not base["crash"] or any(any(f in x for f in _FAIL_W) and any(g in x for g in _SUCC_W)
                                  and any(p in x for p in _PREC_W) for x in sents),
         "crash-beats-goal on the same tick not stated in one sentence")
    d = px["delay"]
    if d:
        need(any(any(w in x for w in _DELAY_W) and _has_num(d, x, set(re.findall(r"\d+", x))) for x in sents),
             f"reply delay of {d} tick(s) not stated")
    for h in px["hidden"]:
        need(any(_has_name(term[h], x) and any(w in x for w in _HID_W) for x in sents),
             f"hidden var {h!r} not stated as hidden next to its term")
    if px["hidden"]:
        need(_has_num(px["window"], low, nums), f"history window {px['window']} not stated")
    if base["rand"]:
        W = sum(w for _v, w in base["rand"])
        for v, w in base["rand"]:
            pct = 100.0 * w / W
            forms = {f"{w}/{W}", f"{w} in {W}", f"{w} out of {W}", f"{w} of {W}", f"{pct:g}%", f"{pct:.1f}%",
                     f"{pct:.2f}%", f"{round(pct)}%", f"{w}:{W - w}"}
            need(any(f in low for f in forms), f"chance of outcome {v} ({w}/{W}) not stated")
            need(_has_num(v, low, nums), f"chance outcome value {v} absent")
    out["P2"] = {"missing": miss[:20], "n_missing": len(miss), "pass": not miss}
    return out


def transition_diff(pa: dict, pb: dict, max_states: int = 60_000) -> str | None:
    """Transition-exact comparison of two mz-1x programs under the IDENTITY name map (the sufficiency criterion):
    same delay / window / hidden names, same var names with same ranges, same controls (names, options), same start set,
    and for every reachable state x every valid joint the same distribution over (next state, outcome).
    Returns None when exact, else a description of the first difference."""
    from nagi.burst2._rt.machine_zoo import interp  # noqa: PLC0415

    if (pa["delay"], pa["window"], sorted(pa["hidden"])) != (pb["delay"], pb["window"], sorted(pb["hidden"])):
        return "delay / window / hidden vars differ"
    A, B = pa["base"], pb["base"]
    va, vb = {v["name"]: v for v in A["vars"]}, {v["name"]: v for v in B["vars"]}
    if set(va) != set(vb):
        return f"var names differ: {sorted(set(va) ^ set(vb))}"
    for n in va:
        if (va[n]["lo"], va[n]["hi"], va[n]["oob"]) != (vb[n]["lo"], vb[n]["hi"], vb[n]["oob"]):
            return f"var {n}: range or out-of-range rule differs"
    ca, cb = {c["name"]: c["opts"] for c in A["controls"]}, {c["name"]: c["opts"] for c in B["controls"]}
    if ca != cb:
        return "controls (names or options) differ"
    order = sorted(va)
    ia = [[v["name"] for v in A["vars"]].index(n) for n in order]
    ib = [[v["name"] for v in B["vars"]].index(n) for n in order]
    cna, cnb = [c["name"] for c in A["controls"]], [c["name"] for c in B["controls"]]

    def key(state, idx):
        return tuple(state[i] for i in idx)

    jb = {}
    for j in interp.valid_joints(B):
        cmd = interp.commands(B, j)
        jb[tuple(sorted(zip(cnb, cmd)))] = j
    jmap = {}
    for j in interp.valid_joints(A):
        cmd = interp.commands(A, j)
        k = tuple(sorted(zip(cna, cmd)))
        if k not in jb:
            return f"joint {j} of the original has no counterpart"
        jmap[j] = jb[k]
    sa = {key(x, ia): x for x in interp.start_states(A)}
    sb = {key(x, ib): x for x in interp.start_states(B)}
    if set(sa) != set(sb):
        return "start sets differ"
    seen, frontier = set(sa), list(sa)
    while frontier:
        k = frontier.pop()
        xa, xb = sa[k], sb[k]
        for j, j2 in jmap.items():
            da, db = {}, {}
            for prob, nx, _r, outc in interp.step_dist(A, xa, j):
                kk = (key(nx, ia) if outc == "running" else outc)
                da[kk] = da.get(kk, 0.0) + prob
                if outc == "running" and key(nx, ia) not in sa:
                    sa[key(nx, ia)] = nx
            for prob, nx, _r, outc in interp.step_dist(B, xb, j2):
                kk = (key(nx, ib) if outc == "running" else outc)
                db[kk] = db.get(kk, 0.0) + prob
                if outc == "running" and key(nx, ib) not in sb:
                    sb[key(nx, ib)] = nx
            if set(da) != set(db) or any(abs(da[q] - db[q]) > 1e-12 for q in da):
                return f"state {dict(zip(order, k))}, joint {j}: transitions differ"
            for q in da:
                if isinstance(q, tuple) and q not in seen:
                    seen.add(q)
                    frontier.append(q)
                    if len(seen) > max_states:
                        return f"more than {max_states} reachable states"
    return None


# ============================================================================== one instance
def run_instance(px: dict, strata: list[str], F: dict, prof: Profile, prose_text=None, glossary=None) -> dict:
    """All per-instance checks (xgates + V3-V6). Returns a JSON-able report with 'pass' and 'failed'."""
    t0 = time.perf_counter()
    feats = [f for f in strata if f in XFEATURES]
    holder: dict = {}

    class _Rec(_xt.XTeacher):  # capture the teacher built inside the frozen run_gates (no second solve)
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            holder["T"] = self
            self._voc = None

        def view_oracle_chain(self, steps=_xt.MAX_STEPS):
            if steps != _xt.MAX_STEPS:
                return super().view_oracle_chain(steps)
            if self._voc is None:
                self._voc = super().view_oracle_chain(steps)
            return self._voc

    orig = xgates.XTeacher
    xgates.XTeacher = _Rec
    try:
        rep = xgates.run_gates(px, feats)
    finally:
        xgates.XTeacher = orig
    out = {"machine_id": rep.get("machine_id"), "signature": rep.get("signature"), "xgates_failed": rep["failed"]}
    for k in ("X1", "success", "crash", "mean_return", "len"):
        out[k] = rep.get(k)
    for g in ("G3", "G4", "X3", "X4d", "X4h", "X5"):
        if g in rep:
            out[g] = {k: v for k, v in rep[g].items() if k != "controls"}
    failed = [f"xgates:{g}" for g in rep["failed"]]
    T = holder.get("T")
    base = px["base"]
    # V1 round trip, V6 static size (independent of the teacher)
    ok, why = roundtrip_ok(px)
    if not ok:
        failed.append("V1:roundtrip")
        out["V1"] = why
    nrules, nchars = len(base["rules"]), len(xdsl.render_rulebook(px))
    out["V6"] = {"rules": nrules, "rulebook_chars": nchars}
    if nrules > prof.max_rules:
        failed.append("V6:rules")
    if nchars > prof.max_rulebook_chars:
        failed.append("V6:rulebook_chars")
    if prof.require_prose:
        out.update(prose_checks(px, prose_text, glossary or {}, prof))
        for k in ("P1", "P2"):
            if not out[k]["pass"]:
                failed.append(f"{k}:prose")
    if T is None or "success" not in rep:  # X0/X1 failed: nothing else to measure
        out["failed"], out["pass"] = failed or ["xgates"], False
        out["time_s"] = round(time.perf_counter() - t0, 3)
        return out
    orc = T.view_oracle_chain()
    succ = rep["success"]
    # V3 oracle floor
    if not (orc["success"] >= prof.oracle_min):
        failed.append("V3:oracle")
    # V4 non-triviality (keep/weak are G5/G6 inside xgates; re-asserted against the profile)
    p4 = T.chain(pol_probe4(T))
    out["success"]["probe4"] = p4["success"]
    out["V4"] = {"keep": succ["keep"], "weak": succ["weak"], "random": succ["random"], "probe4": p4["success"]}
    for k, lim in (("keep", prof.keep_max), ("weak", prof.weak_max), ("random", prof.random_max),
                   ("probe4", prof.probe4_max)):
        if out["V4"][k] > lim:
            failed.append(f"V4:{k}")
    # V5 strata (delay/hidden/long are X4d/X3+X4h/X5 inside xgates; declared tags must match the program by X0)
    names = [v["name"] for v in base["vars"]]
    st = set(strata)
    V5 = {}
    if "interlock" in st:
        m = F.get("mode_var")
        r = {"mode_var": m}
        if m not in names:
            r["pass"] = False
            r["error"] = "mode_var not a base var"
        else:
            col = names.index(m)
            v = base["vars"][col]
            r.update(interlock_static(base, m))
            Xm = np.asarray(T.base.X)[T.aug_base, col]
            w = orc["visits"]
            vals, inv = np.unique(Xm, return_inverse=True)
            share = np.bincount(inv.reshape(-1), weights=w, minlength=len(vals)) / max(w.sum(), 1e-300)
            r["mode_shares"] = {int(a): round(float(b), 4) for a, b in zip(vals, share)}
            r["n_modes_visited"] = int((share >= prof.mode_share_min).sum())
            r["load"] = _load(T, orc, pol_var_blind(T, [col]), "mode_blind", prof)
            r["pass"] = bool(v["hi"] - v["lo"] + 1 <= prof.mode_range_max
                             and r["interlock_rules"] >= prof.mode_interlock_rules_min and r["mode_writes"] >= 1
                             and r["n_modes_visited"] >= prof.mode_values_min and r["load"]["pass"])
        V5["interlock"] = r
    if "axes3" in st:
        ctrl = xgates._slot_minority(T, T.I if T.hidden else T.acc, orc["view_visits"] if T.hidden else orc["visits"])
        V5["axes3"] = {"n_controls": len(base["controls"]),
                       "decisive": [round(c["decisive_share"], 4) for c in ctrl],
                       "minority": [round(c["minority_share"], 4) for c in ctrl]}
        V5["axes3"]["pass"] = bool(len(base["controls"]) == 3 and all(
            c["decisive_share"] >= prof.axes_decisive_min and c["pass"] for c in ctrl))
    if "budget" in st or "multibudget" in st:
        need = 2 if "multibudget" in st else 1
        bv = F.get("budget_vars") or []
        rows = []
        Xb = np.asarray(T.base.X)
        nxt = T.base.nxt
        for b in bv:
            if b not in names:
                rows.append({"var": b, "pass": False, "error": "not a base var"})
                continue
            col = names.index(b)
            src = np.repeat(np.arange(len(Xb)), nxt.shape[1] * nxt.shape[2])
            dst = nxt.reshape(-1)
            ok_ = dst >= 0
            dec = bool((Xb[dst[ok_], col] < Xb[src[ok_], col]).any())
            ld = _load(T, orc, pol_var_blind(T, [col]), f"budget_blind:{b}", prof)
            rows.append({"var": b, "consumed": dec, "load": ld, "pass": bool(dec and ld["pass"])})
        V5["budgets"] = {"need": need, "vars": rows,
                         "pass": bool(sum(r_["pass"] for r_ in rows) >= need and all(r_["pass"] for r_ in rows))}
    for k, r in V5.items():
        if not r["pass"]:
            failed.append(f"V5:{k}")
    out["V5"] = V5
    out["time_s"] = round(time.perf_counter() - t0, 3)
    if out["time_s"] > prof.max_inst_seconds:
        failed.append("V6:time")
    out["failed"] = failed
    out["pass"] = not failed
    return out


# ============================================================================== structural fingerprint (V7)
_KIND = {dsl.K_VAR: "v", dsl.K_ABS: "av", dsl.K_SGN: "sv", dsl.K_CMD: "c", dsl.K_ABSCMD: "ac", dsl.K_W: "w"}


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def wl_features(px: dict, iters: int = 2) -> Counter:
    """Rename- and constant-invariant structural features: Weisfeiler-Lehman subtree hashes (iterations 0..iters)
    of the program graph (vars, controls, $w, rules, crash predicates, goal; edges labelled by role, atom kind,
    coefficient sign and comparison op). Identical structure -> identical multiset; one extra rule changes only the
    features near it."""
    p = px["base"]
    hid = set(px["hidden"])
    lab, adj = [], []

    def node(label):
        lab.append(label)
        adj.append([])
        return len(lab) - 1

    def edge(a, b, el):
        adj[a].append((el + ">", b))
        adj[b].append((el + "<", a))

    vn = {}
    for v in p["vars"]:
        span = v["hi"] - v["lo"]
        bucket = 0 if span <= 2 else 1 if span <= 8 else 2 if span <= 32 else 3
        vn[v["name"]] = node(f"V|{v['oob']}|{'h' if v['name'] in hid else 'd'}|"
                             f"{'m' if len(v['init']) > 1 else 's'}|{bucket}")
    cn = {c["name"]: node("C|" + "".join("n" if o is None else "i" for o in c["opts"])) for c in p["controls"]}
    wn = node(f"W|{len(p['rand'])}") if p["rand"] else None
    node(f"D|{px['delay']}|{px['window']}|{len(px['hidden'])}")

    def target(kind, name):
        if kind in (dsl.K_CMD, dsl.K_ABSCMD):
            return cn[name]
        if kind == dsl.K_W:
            return wn
        return vn[name]

    def link_expr(n, e, role):
        for c, a in e["t"]:
            k, name = dsl.parse_atom(a)
            edge(n, target(k, name), f"{role}|{_KIND[k]}|{'+' if c > 0 else '-'}{'1' if abs(c) == 1 else 'n'}")

    def link_pred(n, q, role, depth=0):
        ((kind, items),) = q.items()
        for it in items:
            if isinstance(it, dict):
                link_pred(n, it, role + kind[0], depth + 1)
            else:
                for c, a in it[0]["t"]:
                    k, name = dsl.parse_atom(a)
                    edge(n, target(k, name), f"{role}{kind[0]}|{_KIND[k]}|{'+' if c > 0 else '-'}|{it[1]}")

    for r in p["rules"]:
        n = node(f"R|{'g' if 'if' in r else 'u'}|{len(r['to']['t'])}|{'k' if r['to']['k'] else '0'}")
        edge(n, vn[r["set"]], "set")
        link_expr(n, r["to"], "to")
        if "if" in r:
            link_pred(n, r["if"], "if")
    for q in p["crash"]:
        link_pred(node("X"), q, "cr")
    link_pred(node("G"), p["goal"], "go")
    feats = Counter()
    cur = [_h(x) for x in lab]
    feats.update(f"0|{x}" for x in cur)
    for it in range(1, iters + 1):
        cur = [_h(cur[i] + "|" + ",".join(sorted(el + cur[j] for el, j in adj[i]))) for i in range(len(lab))]
        feats.update(f"{it}|{x}" for x in cur)
    return feats


def wl_sim(a: Counter, b: Counter) -> float:
    keys = set(a) | set(b)
    num = sum(min(a[k], b[k]) for k in keys)
    den = sum(max(a[k], b[k]) for k in keys)
    return num / den if den else 1.0


def text_shingles(px: dict, n: int = 8) -> set[str]:
    """Hashed word n-grams of the served rulebook (n = 8; a text leak guard compares them with Jaccard >= 0.5)."""
    w = xdsl.render_rulebook(px).split()
    return {_h(" ".join(w[i:i + n])) for i in range(max(0, len(w) - n + 1))}


# ============================================================================== index of existing families
_INDEX_CACHE: dict = {}


def fingerprint_module(mod, name: str, salt: str, n_inst: int = 4, kept_params=None) -> dict | None:
    F, P = getattr(mod, "FAMILY", None), getattr(mod, "PARAMS", None)
    if not isinstance(F, dict) or not isinstance(P, dict) or not callable(getattr(mod, "build", None)):
        return None
    pts = kept_params or instance_order(name, P, salt)[:n_inst]
    pxs = []
    for p in pts:
        try:
            pxs.append(as_px(mod.build(dict(p))))
        except Exception:  # noqa: BLE001 - an invalid grid point of an existing family is not an index entry
            continue
    if not pxs:
        return None
    pg = set()
    if callable(getattr(mod, "prose", None)):
        try:
            pg = _grams(mod.prose(dict(pts[0])))
        except Exception:  # noqa: BLE001
            pg = set()
    return {"name": name, "domain_id": F.get("domain_id"), "sigs": sorted({xdsl.signature(x) for x in pxs}),
            "base_sigs": sorted({dsl.signature(x["base"]) for x in pxs}), "wl": wl_features(pxs[0]),
            "title": F.get("title", ""), "prose_grams": pg}


def dir_index(fam_dir: str, source: str, salt: str, exclude_paths=()) -> list[dict]:
    """Fingerprints of every family file ``<fam_dir>/*.py`` (files starting with '_' skipped). A file that fails the
    V0 static contract is never imported (an index directory is data, not trusted code). Cached per process."""
    fam_dir = os.path.abspath(fam_dir)
    skip = {os.path.realpath(x) for x in exclude_paths}
    out = []
    for fn in sorted(os.listdir(fam_dir)) if os.path.isdir(fam_dir) else []:
        path = os.path.join(fam_dir, fn)
        if not fn.endswith(".py") or fn.startswith("_") or os.path.realpath(path) in skip:
            continue
        key = ("file", os.path.realpath(path), file_sha256(path), salt)
        if key not in _INDEX_CACHE:
            e = None
            try:
                with open(path) as f:
                    ok = not static_errors(f.read())
                e = fingerprint_module(load_module(path), fn[:-3], salt) if ok else None
            except Exception:  # noqa: BLE001 - a broken file is not an index entry
                e = None
            _INDEX_CACHE[key] = e
        if _INDEX_CACHE[key]:
            out.append(dict(_INDEX_CACHE[key], source=source, path=path))
    return out


def job_index(fam_dir: str, report_dir: str, source: str, salt: str, exclude: str | None = None) -> list[dict]:
    """Fingerprints of the PASSED families of a job (report pass = true, file unchanged since), from their kept
    params."""
    out = []
    if not os.path.isdir(report_dir):
        return out
    for fn in sorted(os.listdir(report_dir)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(report_dir, fn)) as f:
                rep = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        name = rep.get("family")
        if not rep.get("pass") or not name or name == exclude:
            continue
        path = os.path.join(fam_dir, f"{name}.py")
        if not os.path.exists(path) or file_sha256(path) != rep.get("module_sha256"):
            continue  # edited after its PASS: not indexed until re-validated
        try:
            mod = load_module(path)
        except Exception:  # noqa: BLE001
            continue
        e = fingerprint_module(mod, name, salt, kept_params=[k["params"] for k in rep.get("kept", [])][:4] or None)
        if e:
            e["source"] = source
            e["path"] = path
            out.append(e)
    return out


def dup_check(cand: dict, index: list[dict], prof: Profile, exclude_names=()) -> dict:
    """V7: exact mz-1x signature collisions and WL similarity against every index entry (self excluded)."""
    sig_hits, base_sig_hits, best, best_name, name_hit = [], [], 0.0, None, False
    twin, twin_name = 0.0, None
    for e in index:
        if e["name"] in exclude_names:
            continue
        if e["name"] == cand["name"]:
            name_hit = True
        if set(cand["sigs"]) & set(e["sigs"]):
            sig_hits.append(e["name"])
        if set(cand["base_sigs"]) & set(e["base_sigs"]):
            base_sig_hits.append(e["name"])
        s = wl_sim(cand["wl"], e["wl"])
        if s > best:
            best, best_name = s, e["name"]
        if cand.get("prose_grams") and e.get("prose_grams"):
            j = jaccard(cand["prose_grams"], e["prose_grams"])
            if j > twin:
                twin, twin_name = j, e["name"]
    ok = not sig_hits and not base_sig_hits and best < prof.dup_wl_max and not name_hit and twin < prof.prose_twin_max
    return {"pass": bool(ok), "sig_hits": sig_hits, "base_sig_hits": base_sig_hits, "name_hit": name_hit,
            "max_wl_sim": round(best, 4), "nearest": best_name, "max_prose_twin": round(twin, 4),
            "prose_twin_nearest": twin_name, "n_index": len(index)}


def token_hits(texts: list[str], tokens_: list[str]) -> list[str]:
    low = " | ".join(t.lower() for t in texts)
    return sorted({t for t in tokens_ if t.lower() in low})


# ============================================================================== family
def check_family(path: str, prof: Profile, *, strict_schema: bool = True, index: list[dict] | None = None,
                 family_rules=None, log=None, max_scan: int | None = None, kept_params: list[dict] | None = None,
                 x6: bool | None = None) -> dict:
    """Full family validation. ``index`` = the V7 near-duplicate index (list of fingerprints; None or [] = empty).
    ``family_rules(F) -> list[str]`` adds job-specific errors (domain, batch plan, tokens). ``kept_params``
    restricts the scan to the given grid points (re-checks of a known report only)."""
    t0 = time.perf_counter()
    stem = os.path.splitext(os.path.basename(path))[0]
    rec = {"family": stem, "gate_version": GATE_VERSION, "profile": asdict(prof), "module_sha256": file_sha256(path),
           "errors": []}
    with open(path) as f:
        src = f.read()
    errs = static_errors(src)
    mod = None
    if not errs:
        try:
            mod = load_module(path)
        except Exception as ex:  # noqa: BLE001
            errs.append(f"import failed: {type(ex).__name__}: {ex}")
    if mod is not None:
        F, P = getattr(mod, "FAMILY", None), getattr(mod, "PARAMS", None)
        errs += schema_errors(F, P, prof, stem, strict=strict_schema, mod=mod)
        if not callable(getattr(mod, "build", None)):
            errs.append("build(p) missing")
        if not errs and family_rules is not None:
            errs += family_rules(F)
    rec["errors"] = errs
    if errs:
        rec["pass"], rec["failed"] = False, ["V0:contract"]
        return rec
    rec["family_meta"] = {k: F[k] for k in F if k != "story"}
    strata = list(F["strata"])
    pts = kept_params if kept_params is not None else instance_order(stem, P, prof.inst_salt)
    if max_scan:
        pts = pts[:max_scan]
    kept, seen, insts = [], set(), []
    first_prose = None
    for p in pts:
        try:
            px, err = build_twice(mod, p)
        except Exception as ex:  # noqa: BLE001
            px, err = None, f"build raised {type(ex).__name__}: {ex}"
        ptxt = None
        if px is not None and prof.require_prose:
            try:
                ptxt = mod.prose(dict(p))
                if ptxt != mod.prose(dict(p)):
                    px, err = None, "prose(p) is not deterministic"
            except Exception as ex:  # noqa: BLE001
                px, err = None, f"prose(p) raised {type(ex).__name__}: {ex}"
        if px is None:
            r = {"pass": False, "failed": ["V2:build"], "error": err}
        else:
            try:
                r = run_instance(px, strata, F, prof, prose_text=ptxt, glossary=getattr(mod, "GLOSSARY", None))
                if ptxt is not None:
                    r["prose_sha256"] = hashlib.sha256(ptxt.encode()).hexdigest()
                    r["_prose"] = ptxt
            except Exception as ex:  # noqa: BLE001
                r = {"pass": False, "failed": ["error"], "error": f"{type(ex).__name__}: {ex}"}
        r["params"] = p
        ptext = r.pop("_prose", None)
        insts.append(r)
        if log:
            log(f"{stem} {p} {'PASS' if r['pass'] else 'FAIL ' + ','.join(r['failed'])} {r.get('time_s')}s"
                + (f" {r['error']}" if r.get("error") else ""))
        if r["pass"] and r["machine_id"] not in seen:
            seen.add(r["machine_id"])
            kept.append((px, r, p))
            if len(kept) == 1:
                first_prose = ptext
            if len(kept) >= prof.keep_max_inst:
                break
    rec["instances"] = insts
    rec["n_kept"] = len(kept)
    rec["kept"] = [{"params": p, "machine_id": r["machine_id"], "signature": r["signature"],
                    "prose_sha256": r.get("prose_sha256")} for _x, r, p in kept]
    failed = []
    if len(kept) < prof.min_pass:
        failed.append("admit:<min_pass")
    use_x6 = prof.x6 if x6 is None else x6
    if use_x6 and kept:
        from .x6 import blind_equivalence  # noqa: PLC0415

        rec["X6"] = blind_equivalence([x for x, _r, _p in sorted(kept, key=lambda k: k[1]["X1"]["n_aug"])[:2]])
        if not rec["X6"]["pass"]:
            failed.append("X6:blind")
    else:
        rec["X6"] = {"pass": None, "skipped": "no kept instance" if not kept else "disabled"}
    if kept:
        pxs = [x for x, _r, _p in kept]
        cand = {"name": stem, "sigs": sorted({xdsl.signature(x) for x in pxs}),
                "base_sigs": sorted({dsl.signature(x["base"]) for x in pxs}), "wl": wl_features(pxs[0]),
                "prose_grams": _grams(first_prose) if first_prose else set()}
        rec["V7"] = dup_check(cand, index or [], prof)
        if not rec["V7"]["pass"]:
            failed.append("V7:near_duplicate")
        rec["text_shingles_n"] = len(text_shingles(pxs[0]))
    rec["failed"] = failed
    rec["pass"] = not failed
    rec["wall_s"] = round(time.perf_counter() - t0, 1)
    return rec


def summary_line(rec: dict) -> str:
    if rec.get("errors"):
        return "CONTRACT ERRORS:\n  " + "\n  ".join(rec["errors"])
    fails = Counter(f for i in rec.get("instances", []) for f in i.get("failed", []))
    v7 = rec.get("V7", {})
    return (f"kept {rec.get('n_kept', 0)} (need {rec['profile']['min_pass']}); instance failures {dict(fails)}; "
            f"X6 {rec.get('X6', {}).get('pass')}; V7 sig_hits={len(v7.get('sig_hits', []))} "
            f"max_wl_sim={v7.get('max_wl_sim')} max_prose_twin={v7.get('max_prose_twin')}")


def dumps(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=True,
                      default=lambda o: o.tolist() if hasattr(o, "tolist") else (
                          dict(o) if isinstance(o, Counter) else sorted(o) if isinstance(o, set) else str(o)))


__all__ = ["GATE_VERSION", "PROFILES", "Profile", "STRATA", "check_family", "run_instance", "parse_rulebook_x",
           "roundtrip_ok", "wl_features", "wl_sim", "dir_index", "job_index", "fingerprint_module", "dup_check",
           "token_hits", "replace", "summary_line", "dumps", "file_sha256", "text_shingles", "load_module",
           "instance_order", "as_px", "transition_diff", "prose_checks", "static_errors"]
