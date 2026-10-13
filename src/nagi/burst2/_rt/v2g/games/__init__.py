"""Game rule packs behind the LANES Machine API (``v2g.games.snake``: Snake Rush public rules, lane hybrid's forward
model). ``match_rules(text)`` returns the pack's Machine when ``text`` is exactly a pack's public rules text;
``match_request(text)`` when ``text`` is a served request of a pack. RR and Booster have no search pack
(lanes/runtime.md §6: the core plays them one-pass); their requests route to ``v2g.games.arena_core`` (the frozen
core-head policy, plumbing for gate I)."""

from __future__ import annotations


def _snake():
    try:
        from nagi.burst2._rt.v2g.games import snake  # noqa: PLC0415

        snake.rules_text()
    except ImportError:  # arena not in this checkout
        return None
    return snake


def match_rules(text: str):
    sn = _snake()
    return None if sn is None else sn.match_rules(text)


def match_request(text: str):
    """Snake pack, or the RR / Booster core-head route (v2g.games.arena_core), for an exact served request."""
    sn = _snake()
    g = None if sn is None else sn.match_request(text)
    if g is not None:
        return g
    try:
        from nagi.burst2._rt.v2g.games import arena_core  # noqa: PLC0415
    except ImportError:  # arena / bv2n not in this checkout
        return None
    return arena_core.match_request(text)
