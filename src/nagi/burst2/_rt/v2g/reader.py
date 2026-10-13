"""Exact reader: rules text (or a full served request) -> runnable ``v2g.machine.Machine`` (+ the client view).

Accepted inputs (exact schema renderings; anything else raises ``ReaderError``):
  1. mz-1 rulebook = ``machine_zoo.dsl.render(program)`` (docs/machine_zoo/SPEC.md §1.1 text form);
  2. mz-1x rulebook = mz-1 rulebook of the base + the ``extension mz-1x:`` block (``bv2n.zoo_new.xdsl.render_rulebook``,
     ZOO_NEW_SPEC §7): reply delay, hidden var NAMES, window length;
  3. a served Zoo request (``bv2n.zoo.render.render_request`` for mz-1, ``bv2n.zoo_new.render_hook.request`` for mz-1x),
     which also yields the client view (mz-1: the state; mz-1x: the observation window + decided joints);
  4. a game rule pack (``v2g.games``): the Snake Rush public rules text (``arena.games.snake_rush.rules_text()``).

Exactness rule (fail closed, handbook R3.17): a text is accepted only if re-rendering the parsed machine gives the
same bytes (``strict=True``; a missing final newline is tolerated). So text path == structured path by construction,
and the gate-I parity test (tests/test_v2g_operate.py) checks the decisions as well.

Free-form rules (PLAN §0.3 "LLM reads once per machine") are out of Phase 0: ``read_rules(text, fallback=f)`` calls
``f(text) -> program dict`` only when the exact parser fails, and the result must pass ``dsl.validate`` /
``xdsl.validate``; no fallback is wired by default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from nagi.burst2._rt.machine_zoo import dsl

from .machine import Machine

EXT_HEAD = "extension mz-1x:"
_DELAY_RE = re.compile(r"  reply delay: (\d) ticks?(?: \(.*\))?")
_HID_RE = re.compile(r"  hidden vars \(never displayed\): (.*)")
_WIN_RE = re.compile(r"  history shown: last (\d) displayed observations")


class ReaderError(ValueError):
    pass


@dataclass
class Read:
    machine: object
    view: dict | None = None  # client view when the input was a full request
    order: list | None = None  # slot order of the request (Burst chord)
    source: str = "rules"  # rules | request | game


def _norm(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def _parse_mz1x(text: str) -> dict:
    from nagi.burst2._rt.bv2n.zoo_new import xdsl  # noqa: PLC0415

    head, ext = text.split("\n" + EXT_HEAD + "\n", 1)
    base = dsl.parse(head + "\n")
    lines = ext.rstrip("\n").split("\n")
    m = _DELAY_RE.fullmatch(lines[0])
    if m is None:
        raise ReaderError("bad mz-1x extension block (delay line)")
    d = int(m.group(1))
    hidden, window = [], 1
    if len(lines) == 2 and lines[1] == "  hidden vars: none":
        pass
    elif len(lines) == 3:
        mh, mw = _HID_RE.fullmatch(lines[1]), _WIN_RE.fullmatch(lines[2])
        if mh is None or mw is None:
            raise ReaderError("bad mz-1x extension block (hidden / window lines)")
        hidden, window = mh.group(1).split(", "), int(mw.group(1))
    else:
        raise ReaderError("bad mz-1x extension block (line count)")
    return xdsl.make(base, delay=d, hidden=hidden, window=window)


def read_rules(text: str, strict: bool = True, fallback=None) -> Machine:
    """Rulebook text -> Machine (mz-1, mz-1x or a game rule pack). Raises ReaderError unless exact."""
    from nagi.burst2._rt.v2g import games  # noqa: PLC0415

    g = games.match_rules(text)
    if g is not None:
        return g
    t = _norm(text)
    try:
        lines = t.split("\n")
        if EXT_HEAD in lines:
            m = Machine(_parse_mz1x(t))
        else:
            m = Machine(dsl.parse(t))
    except (ReaderError, ValueError, KeyError, IndexError) as ex:
        if fallback is None:
            raise ReaderError(f"not an exact mz-1 / mz-1x rulebook: {ex}") from None
        m = Machine(fallback(text))
        m.read_via = "fallback"
        return m
    if strict and m.rules_text() != t:
        raise ReaderError("rulebook does not round-trip (non-canonical text); use strict=False to canonicalize")
    m.read_via = "exact"
    return m


def read_request(text: str) -> Read:
    """Served Zoo request text -> (Machine, client view, slot order). Raises unless the request round-trips."""
    from nagi.burst2._rt.bv2n.zoo import render as R  # noqa: PLC0415

    mt = R._STATE_RE.search(text)
    if mt is None:
        raise ReaderError("not a Zoo request")
    rules = mt.group(1)
    try:
        if EXT_HEAD in rules.split("\n"):
            from nagi.burst2._rt.bv2n.zoo import xrequest as XR  # noqa: PLC0415

            px, xv, order = XR.parse_request_x(text)
            m = Machine(px)
            view = {"kind": "mz-1x", "obs": tuple(xv.obs), "dec": tuple(xv.dec)}
        else:
            prog, state, order = R.parse_request(text)
            m = Machine(prog)
            view = m.view(state)
    except ReaderError:
        raise
    except (ValueError, KeyError, IndexError) as ex:
        raise ReaderError(f"request does not parse exactly: {ex}") from None
    if m.request_text(view, order) != text:
        raise ReaderError("request does not round-trip")
    m.read_via = "exact"
    return Read(m, view, order, "request")


def read(text: str) -> Read:
    """Any accepted input (module doc) -> Read."""
    from nagi.burst2._rt.v2g import games  # noqa: PLC0415

    g = games.match_request(text)
    if g is not None:
        return Read(g, g.parse(text), None, "game")
    if "\nSTATE:\nRULES:\n" in text:
        return read_request(text)
    m = read_rules(text)
    return Read(m, None, None, "game" if getattr(m, "kind", "zoo") != "zoo" else "rules")
