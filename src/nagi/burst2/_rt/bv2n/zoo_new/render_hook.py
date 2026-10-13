"""Adapter from mz-1x views to lane zoo-render's Burst chord renderer (``bv2n.zoo.render``, origin/bv2n-zoo-render).

ZOO_NEW_SPEC.md §7. The served request = render.render_request(base, state=None, rules_text=xdsl.render_rulebook(px),
observation=window_text(px, view)). Hidden var VALUES never enter the text (only their names, in the rulebook).
Targets: slot_targets(base, q27) when nothing is hidden, else targets_from_joint_set(base, I(x)) — never per-slot
sum-marginals (R2.13). When ``bv2n.zoo.render`` is not importable (lane not merged yet) ``available()`` is False and
only ``window_text`` / ``rules_text`` work.
"""

from __future__ import annotations

from . import xdsl
from .xteacher import XView

OPT = ("dec", "keep", "inc")


def _render():
    from nagi.burst2._rt.bv2n.zoo import render  # noqa: PLC0415

    return render


def available() -> bool:
    try:
        _render()
        return True
    except ImportError:
        return False


def rules_text(px: dict) -> str:
    return xdsl.render_rulebook(px).rstrip("\n")


def joint_text(base: dict, j: int) -> str:
    digits = (j // 9, (j // 3) % 3, j % 3)
    return ", ".join(f"{c['name']}={OPT[digits[s]]}" for s, c in enumerate(base["controls"]))


def window_text(px: dict, v: XView) -> str:
    """Observation block: H displayed observations (oldest first) and the decided joints (in flight marked)."""
    disp = xdsl.displayed(px)
    H, K, d = px["window"], xdsl.history_len(px), px["delay"]
    L = []
    for i, o in enumerate(v.obs):
        age = H - 1 - i
        tag = "now" if age == 0 else f"t-{age}"
        L.append(f"{tag}: " + ("start" if o is None else " ".join(f"{n}={x}" for n, x in zip(disp, o))))
    for i, j in enumerate(v.dec):
        age = K - i
        if j is None:
            continue
        flight = " (in flight)" if i >= K - d else ""
        L.append(f"decided t-{age}: {joint_text(px['base'], j)}{flight}")
    return "\n".join(L)


def request(px: dict, v: XView, order=None) -> str:
    return _render().render_request(px["base"], None, order=order, rules_text=rules_text(px),
                                    observation=window_text(px, v))


def targets(px: dict, label: dict) -> dict:
    r = _render()
    if label.get("q27") is not None:
        return r.slot_targets(px["base"], label["q27"])
    return r.targets_from_joint_set(px["base"], label["acceptable"])
