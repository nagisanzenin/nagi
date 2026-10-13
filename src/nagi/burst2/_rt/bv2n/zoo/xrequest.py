"""mz-1x (catalog C) request text: render through zoo-new's hook, exact parser, view <-> text round trip.

The served request for a catalog-C decision is ``bv2n.zoo_new.render_hook.request(px, view)`` (ZOO_NEW_SPEC.md §7):
the Burst chord layout of ``bv2n.zoo.render`` with RULES = mz-1 rulebook of the base + the ``extension mz-1x:``
block, and OBSERVATION = the window text (H displayed observations, oldest first, ``start`` for PAD; decided joints
with the in-flight ones marked). Hidden values never enter the text.

``parse_request_x(text) -> (px, view, order)`` inverts it exactly and raises unless ``render(parse(text)) == text``,
so any text policy (teacher through text, baselines, a model) sees only what the client legitimately knows.
"""
from __future__ import annotations

import re

from nagi.burst2._rt.bv2n.zoo import render as R
from nagi.burst2._rt.bv2n.zoo_new import render_hook as RH
from nagi.burst2._rt.bv2n.zoo_new import xdsl
from nagi.burst2._rt.bv2n.zoo_new.xteacher import XView

VERSION = "bv2n-zoo-xrequest-v0"
EXT_HEAD = "extension mz-1x:"
_OBS_RE = re.compile(r"^(now|t-(\d+)): (.*)$")
_DEC_RE = re.compile(r"^decided t-(\d+): (.*?)( \(in flight\))?$")


def render_x(px: dict, view: XView, order=None) -> str:
    return RH.request(px, view, order=order)


def _parse_rules(rules: str) -> dict:
    from nagi.burst2._rt.machine_zoo import dsl  # noqa: PLC0415

    if EXT_HEAD not in rules.split("\n"):
        base = dsl.parse(rules + "\n")
        return xdsl.make(base)
    head, ext = rules.split("\n" + EXT_HEAD + "\n", 1)
    base = dsl.parse(head + "\n")
    lines = ext.split("\n")
    m = re.fullmatch(r"  reply delay: (\d) ticks?.*", lines[0])
    if m is None:
        raise ValueError("bad extension block (delay)")
    d = int(m.group(1))
    hidden, window = [], 1
    if lines[1] != "  hidden vars: none":
        m = re.fullmatch(r"  hidden vars \(never displayed\): (.*)", lines[1])
        m2 = re.fullmatch(r"  history shown: last (\d) displayed observations", lines[2])
        if m is None or m2 is None:
            raise ValueError("bad extension block (hidden)")
        hidden, window = m.group(1).split(", "), int(m2.group(1))
    return xdsl.make(base, delay=d, hidden=hidden, window=window)


def _joint(base: dict, txt: str) -> int:
    ans = {}
    for part in txt.split(", "):
        k, v = part.split("=")
        ans[k] = v
    return R.answer_to_joint(base, ans)


def parse_request_x(text: str) -> tuple[dict, XView, list[str]]:
    """request text -> (canonical mz-1x program, XView, slot order). Raises unless the text round-trips exactly."""
    m = R._STATE_RE.search(text)
    if m is None:
        raise ValueError("not a bv2n Zoo request")
    px = _parse_rules(m.group(1))
    order = [g for _i, g in R._SLOT_RE.findall(m.group(3))]
    H, K = px["window"], xdsl.history_len(px)
    disp = xdsl.displayed(px)
    obs, dec = [None] * H, [None] * K
    for ln in m.group(2).split("\n"):
        md = _DEC_RE.match(ln)
        if md:
            dec[K - int(md.group(1))] = _joint(px["base"], md.group(2))
            continue
        mo = _OBS_RE.match(ln)
        if mo is None:
            raise ValueError(f"bad observation line {ln!r}")
        age = 0 if mo.group(1) == "now" else int(mo.group(2))
        if mo.group(3) == "start":
            obs[H - 1 - age] = None
        else:
            vals = dict(kv.split("=") for kv in mo.group(3).split(" "))
            if list(vals) != disp:
                raise ValueError("observation vars != displayed vars")
            obs[H - 1 - age] = tuple(int(vals[n]) for n in disp)
    view = XView(tuple(obs), tuple(dec))
    if render_x(px, view, order) != text:
        raise ValueError("mz-1x request does not round-trip")
    return px, view, order
