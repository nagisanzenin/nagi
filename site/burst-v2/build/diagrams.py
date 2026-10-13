"""Burst V2 page: the two architecture diagrams (inline SVG), stamped into index.html by make_page.py.

  svg_decision(v)  one decision: rules + state -> exact parser -> belief -> exact lookahead -> tie set A
                   -> (learned core, only on ties, gated by tau) -> seeded draw -> choice
  svg_core(v)      the learned core: the Zoo branch, the three game branches (own trunk copies) and where each
                   game is decided (Snake: SDK search pack, no core; Rotorwash-Ramp / Booster: core game head)

Each function returns a <figure class="arch"> with two <svg> variants, .wide (desktop) and .narrow (phones); the
<style> inside each SVG (scoped to .bv2-arch) picks one, so the block works without other CSS.
Every number in the visible text is a registered value read through v(key): the CANDIDATE.json values reuse
make_page's cfg_* keys and core_params; the architecture values are registered here as arch_* from the published
model card (bench/burst_v2/MODEL_CARD.md, byte-identical to the Hugging Face README at the pinned revision; its sha256
is pinned by fill_receipt.json outputs.MODEL_CARD) and from the SDK source. register() also cross-checks every claim
the drawings make in words (tie-break gate, Snake policy, separate trunks, one forward per tick) against those files.
No network.
"""
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
FILES_ADD = {
    "card": "bench/burst_v2/MODEL_CARD.md",
    "sdk_tokens": "src/nagi/burst2/_rt/machine_zoo/tokens.py",
    "sdk_game_data": "src/nagi/burst2/_rt/v2g/core/game_data.py",
    "sdk_multi_core": "src/nagi/burst2/_rt/v2g/core/multi_core.py",
    "sdk_search": "src/nagi/burst2/_rt/v2g/search.py",
}


def _read(b, rel):
    """Text of a file make_page hashed (b.receipts), checked against that hash."""
    raw = open(os.path.join(ROOT, rel), "rb").read()
    b.require(hashlib.sha256(raw).hexdigest() == b.receipts.get(rel), f"diagrams: {rel} not hashed or changed during the build")
    return raw.decode("utf-8")


def _flat(s):
    return " ".join(s.split())


def register(b):
    import re  # noqa: PLC0415

    req = b.require
    card = _read(b, FILES_ADD["card"])
    rec = "bench/burst_v2/receipts/"
    C = json.loads(_read(b, rec + "CANDIDATE.json"))
    FL = json.loads(_read(b, rec + "fill_receipt.json"))
    guide, api = _flat(_read(b, "docs/BURST_V2.md")), _read(b, "src/nagi/burst2/_api.py")
    toks, mc, srch = _flat(_read(b, FILES_ADD["sdk_tokens"])), _read(b, FILES_ADD["sdk_multi_core"]), _read(b, FILES_ADD["sdk_search"])

    # values shown in the drawings (CANDIDATE values: make_page's cfg_*; core_params: the M5 report)
    b.rx("arch_d", "card", r"relation-typed attention biases, d = (\d+), \d+ layers\.")
    b.rx("arch_layers", "card", r"relation-typed attention biases, d = \d+, (\d+) layers\.")
    b.rx("arch_joints", "card", r"Heads give a joint prior over the (\d+) joints")
    b.rx("arch_rel", "sdk_tokens", r"^N_REL = (\d+)$")
    b.rx("arch_window", "sdk_game_data", r"^SN_W, SN_C = (\d+), \d+$")

    # the published card is the released Hugging Face README, and it states the frozen candidate
    req(b.receipts[FILES_ADD["card"]] == FL["outputs"]["MODEL_CARD"], "MODEL_CARD.md sha != fill_receipt outputs.MODEL_CARD")
    cc, cs = C["config_resolved"]["candidate"], C["config_resolved"]["snake"]
    m = re.search(r"exact search on the parsed rules: ([\d,]+) simulations per decision, horizon up to (\d+),", card)
    req(bool(m) and (int(m.group(1).replace(",", "")), int(m.group(2))) == (cc["max_sims"], cc["k_max"]), "card lookahead != CANDIDATE max_sims / k_max")
    m = re.search(r"exact tie set only, when its confidence is ≥ τ = ([\d.]+) ", card)
    req(bool(m) and float(m.group(1)) == cc["tau"] == C["predeclared"]["search_config"]["tau"], "card tau != CANDIDATE tau")
    m = re.search(r"SDK Snake search pack \(([\d,]+) simulations, horizon (\d+), no learned core\)", card)
    req(bool(m) and (int(m.group(1).replace(",", "")), int(m.group(2))) == (cs["max_sims"], cs["k"]), "card Snake pack != CANDIDATE snake")
    req(re.search(r"\*\*(\d+\.\d+M) parameters\*\*", card).group(1) == b.values["core_params"], "card parameters != M5 report")
    req("Each Arena game has its own encoder and trunk copy in the same checkpoint." in card, "card: separate game trunks")
    req(re.search(r"the core's game head acts once per\s+tick, without lookahead", card) is not None, "card: RR / Booster once per tick")
    # what the drawings say in words, against the frozen candidate and the SDK source
    req(C["snake_policy"] == "sdk_pack" and 'SNAKE_POLICY = "sdk_pack"' in api, "Snake policy is not the SDK pack")
    req(cc["core_value"] is False and cc["tie"] == "sample", "candidate: the core gives leaf values or the tie is not a draw")
    req("one forward per tick" in C["predeclared"]["rr_booster_policy"], "CANDIDATE rr_booster_policy: one forward per tick")
    req("if core is not None and len(A) > 1:" in srch and "if conf >= tau:" in srch
        and "conf = float(np.nan_to_num(p_opt[A[int(np.argmax(pa))]], nan=0.0))" in srch,
        "search.py: core asked only on ties, gate = p_opt of its pick >= tau")
    req("uniform on A, or the core prior renormalised inside A when the confidence gate opens" in guide, "BURST_V2.md: the draw")
    req("The student never sees names" in toks, "tokens.py: no names")
    req('if a["enc"] == "cnn":' in mc and "G.SN_W" in mc and 'cfg["trunk"] == "separate"' in mc, "multi_core.py: Snake CNN / separate trunks")


# ---------------------------------------------------------------- drawing
CSS = (
    ".bv2-arch text{font-family:var(--nagi-body);fill:var(--nagi-muted)}"
    ".bv2-arch .t{fill:var(--nagi-bone);font-weight:700}"
    ".bv2-arch .g{font-family:var(--nagi-mono);font-weight:600;letter-spacing:.08em;fill:var(--nagi-dim)}"
    ".bv2-arch .gx{fill:var(--nagi-yellow)}.bv2-arch .gl{fill:var(--nagi-pink)}"
    ".bv2-arch .bx{fill:var(--nagi-panel2);stroke:var(--nagi-line);stroke-width:1.5}"
    ".bv2-arch .bx.ex{stroke:var(--nagi-yellow)}.bv2-arch .bx.ln{stroke:var(--nagi-pink)}"
    ".bv2-arch .bx.off{fill:none;stroke:var(--nagi-dim);stroke-dasharray:6 5}"
    ".bv2-arch .ar{fill:none;stroke:var(--nagi-muted);stroke-width:1.5}.bv2-arch .ar.off{stroke:var(--nagi-dim);stroke-dasharray:4 4}"
    ".bv2-arch .ah{fill:var(--nagi-muted)}.bv2-arch .ah.off{fill:var(--nagi-dim)}"
    ".arch svg.bv2-arch{display:block;width:100%;height:auto;margin:0 auto}@media (max-width:560px){.arch.bv2-fig{padding:10px 8px}}"
    ".arch svg.bv2-arch.wide{max-width:1040px}.arch svg.bv2-arch.narrow{display:none;max-width:400px}"
    "@media (max-width:1000px){.arch svg.bv2-arch.wide{display:none}.arch svg.bv2-arch.narrow{display:block}}"
)
TAG = {"ex": ("EXACT", "g gx"), "ln": ("LEARNED", "g gl"), "io": (None, "g"), "off": ("UNUSED", "g"), "sr": ("SEARCH", "g gx")}


def _t(x, y, s, cls="", size=12, anchor=None):
    a = f' text-anchor="{anchor}"' if anchor else ""
    c = f' class="{cls}"' if cls else ""
    return f'<text{c} x="{x:g}" y="{y:g}" font-size="{size:g}"{a}>{s}</text>'


def box(x, y, w, kind, title, lines, ts, ss, h=None, tag=None, stack=False, tg=9.5):
    """A labelled box; returns (svg, height). kind: ex exact, sr search, ln learned, io input/output, off unused.
    stack=True puts the tag on its own line above the title (narrow boxes)."""
    lh, pad = round(ss * 1.45), 12
    word, tcls = TAG[kind]
    word = tag if tag is not None else word
    rcls = {"ex": "bx ex", "sr": "bx ex", "ln": "bx ln", "io": "bx", "off": "bx off"}[kind]
    out = []
    if stack:
        ty = y + pad + ts
        if word:
            out.append(_t(x + pad, y + pad + tg - 1, word, tcls, tg))
            ty += tg + 5
    else:
        ty = y + pad + ts
        if word:
            out.append(_t(x + w - pad, ty, word, tcls, tg, "end"))
    out.append(_t(x + pad, ty, title, "t", ts))
    yl = ty + 4
    for s in lines:
        yl += lh
        out.append(_t(x + pad, yl, s, "", ss))
    hh = h if h is not None else round(yl - y + pad + 2)
    return f'<rect class="{rcls}" x="{x:g}" y="{y:g}" width="{w:g}" height="{hh:g}"/>' + "".join(out), hh


def arrow(pts, off=False):
    """Axis-aligned polyline with an arrowhead at the last point."""
    c = " off" if off else ""
    d = "M" + " L".join(f"{x:g} {y:g}" for x, y in pts)
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    dx, dy = (x1 > x0) - (x1 < x0), (y1 > y0) - (y1 < y0)
    px, py = -dy, dx
    hd = [(x1, y1), (x1 - 8 * dx + 4.5 * px, y1 - 8 * dy + 4.5 * py), (x1 - 8 * dx - 4.5 * px, y1 - 8 * dy - 4.5 * py)]
    tip = " ".join(f"{a:g},{b_:g}" for a, b_ in hd)
    end = (x1 - 7 * dx, y1 - 7 * dy)
    d = "M" + " L".join(f"{x:g} {y:g}" for x, y in pts[:-1] + [end])
    return f'<path class="ar{c}" d="{d}"/><polygon class="ah{c}" points="{tip}"/>'


def legend(items, x, y, size, dx=None, dy=0):
    """items: (kind, text); horizontal when dx is given, else vertical with step dy."""
    out = []
    for i, (kind, s) in enumerate(items):
        xi, yi = (x + sum(dx[:i]), y) if dx else (x, y + i * dy)
        rcls = {"ex": "bx ex", "ln": "bx ln", "io": "bx", "off": "bx off"}[kind]
        out.append(f'<rect class="{rcls}" x="{xi:g}" y="{yi - size + 1:g}" width="22" height="{size:g}"/>')
        out.append(_t(xi + 30, yi, s, "", size))
    return "".join(out)


def svg(variant, vid, w, h, title, desc, body):
    return (f'<svg class="{variant} bv2-arch" viewBox="0 0 {w} {h}" role="img" aria-labelledby="{vid}-t {vid}-d" '
            f'xmlns="http://www.w3.org/2000/svg"><title id="{vid}-t">{title}</title><desc id="{vid}-d">{desc}</desc>'
            f'<style>{CSS}</style>{body}</svg>')


# ---------------------------------------------------------------- (a) one decision
def svg_decision(v):
    sims, kmax, tau = v("cfg_sims"), v("cfg_kmax"), v("cfg_tau")
    title = "How Nagi Burst V2 makes one decision"
    desc = (f"Rules and state go to the exact parser, which builds the exact machine. A belief step keeps the states that "
            f"fit what was seen when variables are hidden or replies are delayed. The exact lookahead simulates the machine "
            f"(at most {sims} simulations, depth at most {kmax}) and returns the tie set A of moves it cannot tell apart. "
            f"Only when A holds more than one move is the learned core asked; if its probability that its pick is optimal is "
            f"at least {tau}, the seeded draw samples the core prior inside A, otherwise it samples uniformly on A. The core "
            f"never chooses outside A. The draw is replayable with session and step, and returns the choice: one option per "
            f"control, with probabilities. Exact parts: parser, belief, lookahead, draw. Learned part: the core.")
    leg = [("ex", "Exact: same input, same answer"), ("ln", "Learned: the core"), ("io", "Input and output")]

    # wide: one row, the core under the lookahead and the draw
    W, ts, ss, y0 = 1040, 14.5, 12, 46
    cols = [(0, 130, "io", "Rules + state", ["mz-1 / mz-1x text", "and the state now"], "INPUT"),
            (174, 130, "ex", "Exact parser", ["text → the exact", "machine; rejects", "rather than guesses"], None),
            (348, 130, "ex", "Belief", ["states that fit", "what was seen", "(hidden variables,", "reply delays)"], None),
            (522, 170, "ex", "Exact lookahead", ["simulates the machine", f"≤ {sims} simulations", f"depth ≤ {kmax}", "→ tie set A"], None),
            (736, 144, "ex", "Seeded draw", ["one move from A", "seeded by session", "+ step: replayable"], None),
            (924, 116, "io", "Choice", ["one option per", "control, and the", "probabilities"], "OUTPUT")]
    body = [legend(leg, 0, 14, 12.5, dx=[250, 180])]
    H0 = 128
    for x, w, kind, t, ls, tag in cols:
        body.append(box(x, y0, w, kind, t, ls, ts, ss, h=H0, tag=tag, stack=True)[0])
    ym = y0 + H0 / 2
    for (x, w, *_), (x2, *_) in zip(cols, cols[1:]):
        body.append(arrow([(x + w + 3, ym), (x2 - 3, ym)]))
    body.append(_t(714, ym - 8, "A", "g", 11, "middle"))
    cy = y0 + H0 + 36
    core, ch = box(522, cy, 358, "ln", "Learned core",
                   ["asked only when A holds more than one move", f"gate: P(its pick is optimal) ≥ τ = {tau}",
                    "open → the draw uses its prior inside A", "closed → uniform on A; it never leaves A"], ts, ss, stack=True)
    body.append(core)
    body.append(arrow([(560, y0 + H0 + 3), (560, cy - 3)]))
    body.append(_t(570, cy - 14, "A", "g", 11))
    body.append(arrow([(842, cy - 3), (842, y0 + H0 + 3)]))
    body.append(_t(832, cy - 14, "prior inside A", "g", 10.5, "end"))
    wide = svg("wide", "arch-dec-w", W, round(cy + ch + 4), title, desc, "".join(body))

    # narrow: one column; the tie set also goes straight to the draw (left rail)
    W, ts, ss, x0, gap = 320, 16, 14, 24, 22
    bw = W - x0
    nodes = [("io", "Rules + state", ["mz-1 / mz-1x text", "and the current state"], "INPUT"),
             ("ex", "Exact parser", ["text → the exact machine;", "rejects rather than guesses"], None),
             ("ex", "Belief", ["states that fit what was seen", "(hidden variables, reply delays)"], None),
             ("ex", "Exact lookahead", [f"≤ {sims} simulations, depth ≤ {kmax}", "→ tie set A of equally good moves"], None),
             ("ln", "Learned core", ["asked only when A has several moves", f"gate: P(pick optimal) ≥ τ = {tau}",
                                     "open → the draw uses its prior on A", "closed → uniform on A"], None),
             ("ex", "Seeded draw", ["one move from A, seeded by", "session + step: replayable"], None),
             ("io", "Choice", ["one option per control", "and the probabilities"], "OUTPUT")]
    body = [legend(leg, 0, 15, 13.5, dy=23)]
    y, pos = 82, []
    for kind, t, ls, tag in nodes:
        s, h = box(x0, y, bw, kind, t, ls, ts, ss, tag=tag, tg=10.5)
        body.append(s)
        pos.append((y, h))
        y += h + gap
    for (ya, ha), (yb, _) in zip(pos, pos[1:]):
        body.append(arrow([(x0 + bw / 2, ya + ha + 3), (x0 + bw / 2, yb - 3)]))
    (yl, hl), (yd, hd) = pos[3], pos[5]
    body.append(arrow([(x0 - 2, yl + hl / 2), (8, yl + hl / 2), (8, yd + hd / 2), (x0 - 3, yd + hd / 2)]))
    body.append(_t(12, yl + hl / 2 - 6, "A", "g", 11))
    narrow = svg("narrow", "arch-dec-n", W, round(y - gap + 4), title, desc, "".join(body))
    return f'<figure class="arch bv2-fig">{wide}{narrow}</figure>'


# ---------------------------------------------------------------- (b) the learned core
def svg_core(v):
    P, d, L, J, R, N = (v(k) for k in ("core_params", "arch_d", "arch_layers", "arch_joints", "arch_rel", "arch_window"))
    ss_, sk, tau = v("cfg_snake_sims"), v("cfg_snake_k"), v("cfg_tau")
    title = "Inside the Nagi Burst V2 learned core"
    desc = (f"One checkpoint, {P} parameters. Zoo branch, for machines: the program as typed tokens (var, rule, item, ctrl, "
            f"glob; exact features, no names, ids or positions), a trunk with relation-biased attention over {R} relation "
            f"types, d {d} × {L} layers, and heads for a prior over {J} joints, a success value and p_opt, the confidence "
            f"gate. On unseen machines the exact lookahead decides and the core only breaks its ties, when P(pick optimal) "
            f"≥ {tau}. Game branches: each Arena game has its own encoder and its own trunk copy, ending in per-slot logits: "
            f"a CNN over a {N}×{N} window for Snake Rush, MLP encoders for Rotorwash-Ramp and Booster Gauntlet. Where each "
            f"game is decided: Snake Rush by the SDK search pack ({ss_} simulations, horizon {sk}) with no learned core, so "
            f"the Snake branch is unused by the released policy; Rotorwash-Ramp and Booster Gauntlet by the core game head, "
            f"one forward per tick, no lookahead.")
    leg = [("ex", "Search: no learned weights"), ("ln", f"Learned: one checkpoint, {P} parameters"),
           ("off", "In the checkpoint, unused by the released policy")]

    # wide: four columns (input / encoder, trunk, output, where it decides)
    ts, ss = 14, 12
    X = [(0, 246), (290, 226), (560, 196), (800, 240)]
    body = [legend(leg, 0, 14, 12.5, dx=[236, 330])]
    for (x, _), s in zip(X, ("INPUT AND ENCODER", "TRUNK", "OUTPUT", "WHERE IT DECIDES")):
        body.append(_t(x, 54, s, "g", 10.5))
    y = 66
    row = [("io", "Your machine", ["typed tokens: var, rule, item,", "ctrl, glob · exact features", "no names, ids or positions"], "INPUT"),
           ("ln", "Zoo trunk", ["relation-biased attention", f"{R} relation types", f"d {d} × {L} layers"], None),
           ("ln", "Heads", [f"prior over {J} joints", "success value", "p_opt: the confidence gate"], None),
           ("sr", "Unseen machines", ["exact lookahead decides;", "the core only breaks its ties", f"if P(pick optimal) ≥ {tau}"], None)]
    hz = max(box(0, 0, w, k, t, ls, ts, ss, tag=g)[1] for (_, w), (k, t, ls, g) in zip(X, row))
    for (x, w), (k, t, ls, g) in zip(X, row):
        body.append(box(x, y, w, k, t, ls, ts, ss, h=hz, tag=g)[0])
    for (x, w), (x2, _) in zip(X, X[1:]):
        body.append(arrow([(x + w + 3, y + hz / 2), (x2 - 3, y + hz / 2)]))
    y += hz + 34
    body.append(_t(0, y, "GAME BRANCHES · EACH GAME HAS ITS OWN ENCODER AND TRUNK COPY", "g", 10.5))
    y += 12
    games = [("off", "Snake Rush", ["CNN encoder", f"over a {N}×{N} window"]), ("ln", "Rotorwash-Ramp", ["MLP encoder", "on the parsed view"]),
             ("ln", "Booster Gauntlet", ["MLP encoder", "on the parsed view"])]
    hg, rows = None, []
    for k, name, enc in games:
        cells = [(k, name, enc), (k, "Own trunk copy", ["same size as the Zoo trunk", "no relation bias"]),
                 (k, "Per-slot logits", ["one set of logits", "per control"])]
        hg = hg or max(box(0, 0, w, kk, t, ls, ts, ss)[1] for (_, w), (kk, t, ls) in zip(X, cells))
        for (x, w), (kk, t, ls) in zip(X, cells):
            body.append(box(x, y, w, kk, t, ls, ts, ss, h=hg, tag="" if kk == "off" else None)[0])
        for (x, w), (x2, _) in zip(X[:2], X[1:3]):
            body.append(arrow([(x + w + 3, y + hg / 2), (x2 - 3, y + hg / 2)], off=k == "off"))
        rows.append(y)
        y += hg + 14
    x4, w4 = X[3]
    body.append(box(x4, rows[0], w4, "sr", "SDK search pack", [f"{ss_} simulations, horizon {sk}", "no learned core"], ts, ss, h=hg)[0])
    body.append(_t(x4 - 22, rows[0] + hg / 2 + 4, "×", "g", 13, "middle"))
    hb = rows[2] + hg - rows[1]
    body.append(box(x4, rows[1], w4, "ln", "Core game head", ["plays Rotorwash-Ramp and", "Booster Gauntlet: per-slot", "argmax, one forward per tick,", "no lookahead"], ts, ss, h=hb)[0])
    for r in rows[1:]:
        body.append(arrow([(X[2][0] + X[2][1] + 3, r + hg / 2), (x4 - 3, r + hg / 2)]))
    wide = svg("wide", "arch-core-w", 1040, round(y - 14 + 4), title, desc, "".join(body))

    # narrow: the Zoo chain, then one row per game (branch -> where it decides)
    W, ts, ss, gap = 320, 16, 14, 20
    nleg = leg[:2] + [("off", "Unused by the released policy")]
    body = [legend(nleg, 0, 15, 13.5, dy=23)]
    y = 92
    body.append(_t(0, y, "ZOO BRANCH · MACHINES", "g", 11))
    y += 10
    chain = [("io", "Your machine", ["typed tokens: var, rule, item,", "ctrl, glob; exact features", "no names, ids or positions"], "INPUT"),
             ("ln", "Zoo trunk", ["relation-biased attention", f"{R} relation types · d {d} × {L} layers"], None),
             ("ln", "Heads", [f"prior over {J} joints · success value", "p_opt: the confidence gate"], None),
             ("sr", "Unseen machines", ["exact lookahead decides; the core", "only breaks its ties, when", f"P(pick optimal) ≥ {tau}"], None)]
    prev = None
    for k, t, ls, g in chain:
        s, h = box(0, y, W, k, t, ls, ts, ss, tag=g, tg=10.5)
        body.append(s)
        if prev:
            body.append(arrow([(W / 2, prev + 3), (W / 2, y - 3)]))
        prev = y + h
        y += h + gap
    y += 12
    body.append(_t(0, y, "GAME BRANCHES · OWN TRUNK COPY EACH", "g", 11))
    y += 22
    bw, ts2, ss2, ga = 150, 14.5, 13, 20
    grows = [("SNAKE RUSH", "off", "CNN encoder", [f"{N}×{N} window", "own trunk → logits"],
              "sr", "SDK search pack", [f"{ss_} simulations", f"horizon {sk}, no core"]),
             ("ROTORWASH-RAMP", "ln", "MLP encoder", ["on the parsed view", "own trunk → logits"],
              "ln", "Core game head", ["one forward per tick", "no lookahead"]),
             ("BOOSTER GAUNTLET", "ln", "MLP encoder", ["on the parsed view", "own trunk → logits"],
              "ln", "Core game head", ["one forward per tick", "no lookahead"])]
    for name, k1, t1, l1, k2, t2, l2 in grows:
        body.append(_t(0, y, name, "g", 11))
        y += 8
        h = max(box(0, 0, bw, k1, t1, l1, ts2, ss2, stack=True, tg=10)[1], box(0, 0, bw, k2, t2, l2, ts2, ss2, stack=True, tg=10)[1])
        body.append(box(0, y, bw, k1, t1, l1, ts2, ss2, h=h, stack=True, tg=10)[0])
        body.append(box(W - bw, y, bw, k2, t2, l2, ts2, ss2, h=h, stack=True, tg=10)[0])
        if k1 == "off":
            body.append(_t(W / 2, y + h / 2 + 5, "×", "g", 14, "middle"))
        else:
            body.append(arrow([(bw + 3, y + h / 2), (W - bw - 3, y + h / 2)]))
        y += h + 30
    y -= 16
    narrow = svg("narrow", "arch-core-n", W, round(y - 14 + 4), title, desc, "".join(body))
    return f'<figure class="arch bv2-fig">{wide}{narrow}</figure>'
