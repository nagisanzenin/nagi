"""Machine Zoo extension layer ``mz-1x``: reply delay + history-identifiable hidden state over an mz-1 base program.

Contract: docs/burst_v2_next/ZOO_NEW_SPEC.md §1-§2. An mz-1x program is

    {"dsl": "mz-1x", "base": <mz-1 program>, "delay": d, "hidden": [var, ...], "window": H}

- ``delay`` d in {0, 1, 2}: the joint decided at tick t is applied at tick t + d (KEEP = 13 is in flight at reset).
- ``hidden``: base var names (program order, distinct, at least one var stays displayed) that are never shown.
- ``window`` H in 1..6: number of displayed observations in the request (H = 1 when nothing is hidden).

PLAIN programs (d = 0, hidden = [], H = 1) ARE mz-1 programs: ``to_plain`` returns the canonical base and
``canonical_json`` / ``machine_id`` / ``signature`` equal ``machine_zoo.dsl``'s byte for byte. The base semantics are
never changed; the extension only wraps them (SPEC §2).
"""

from __future__ import annotations

import hashlib
import json

from nagi.burst2._rt.machine_zoo import dsl

DSL_X = "mz-1x"
X_KEYS = ("dsl", "base", "delay", "hidden", "window")
DELAYS = (0, 1, 2)
MAX_WINDOW = 6
KEEP_JOINT = 13


class XProgramError(ValueError):
    pass


def _dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def make(base: dict, delay: int = 0, hidden=(), window: int = 1) -> dict:
    """Validated canonical mz-1x program (a plain one if delay == 0 and nothing is hidden)."""
    names = [v["name"] for v in dsl.canonicalize(base)["vars"]]
    hid = [n for n in names if n in set(hidden)]
    px = {"dsl": DSL_X, "base": dsl.canonicalize(base), "delay": int(delay), "hidden": hid, "window": int(window)}
    if set(hidden) - set(names):
        raise XProgramError(f"hidden names not in base vars: {sorted(set(hidden) - set(names))}")
    validate(px)
    return px


def validate(px: dict) -> None:
    if not isinstance(px, dict) or set(px) != set(X_KEYS):
        raise XProgramError(f"mz-1x program must have exactly keys {X_KEYS}")
    if px["dsl"] != DSL_X:
        raise XProgramError(f"dsl must be {DSL_X!r}")
    dsl.validate(px["base"])  # base is a valid mz-1 program (SPEC rules 1-8)
    if px["delay"] not in DELAYS or isinstance(px["delay"], bool):
        raise XProgramError(f"delay must be one of {DELAYS}")
    names = [v["name"] for v in px["base"]["vars"]]
    hid = px["hidden"]
    if not isinstance(hid, list) or len(set(hid)) != len(hid) or any(h not in names for h in hid):
        raise XProgramError("hidden must be a list of distinct base var names")
    if hid != [n for n in names if n in set(hid)]:
        raise XProgramError("hidden must list vars in program order")
    if len(hid) >= len(names):
        raise XProgramError("at least one var must stay displayed")
    H = px["window"]
    if isinstance(H, bool) or not isinstance(H, int) or not 1 <= H <= MAX_WINDOW:
        raise XProgramError(f"window must be an int in 1..{MAX_WINDOW}")
    if not hid and H != 1:
        raise XProgramError("window must be 1 when nothing is hidden (history cannot change a label)")


def is_valid(px) -> bool:
    try:
        validate(px)
        return True
    except (XProgramError, dsl.ProgramError, KeyError, TypeError):
        return False


def is_plain(px: dict) -> bool:
    return px["delay"] == 0 and not px["hidden"]


def to_plain(px: dict) -> dict:
    """The canonical mz-1 base program (identical object for plain programs)."""
    if not is_plain(px):
        raise XProgramError("not a plain program (delay or hidden vars present)")
    return dsl.canonicalize(px["base"])


def canonicalize(px: dict) -> dict:
    return {"dsl": DSL_X, "base": dsl.canonicalize(px["base"]), "delay": px["delay"], "hidden": list(px["hidden"]),
            "window": px["window"]}


def canonical_json(px: dict) -> str:
    """Plain: mz-1 canonical JSON of the base (byte-identical). Else compact sorted-key JSON of the canonical mz-1x."""
    if is_plain(px):
        return dsl.canonical_json(px["base"])
    return _dumps(canonicalize(px))


def machine_id(px: dict) -> str:
    return hashlib.sha256(canonical_json(px).encode()).hexdigest()[:16]


def signature(px: dict) -> str:
    """Plain: mz-1 signature. Else sha256[:16] of (base signature, delay, hidden var positions, window)."""
    if is_plain(px):
        return dsl.signature(px["base"])
    names = [v["name"] for v in px["base"]["vars"]]
    ext = {"base_sig": dsl.signature(px["base"]), "delay": px["delay"],
           "hidden": [names.index(h) for h in px["hidden"]], "window": px["window"]}
    return hashlib.sha256(_dumps(ext).encode()).hexdigest()[:16]


def displayed(px: dict) -> list[str]:
    hid = set(px["hidden"])
    return [v["name"] for v in px["base"]["vars"] if v["name"] not in hid]


def history_len(px: dict) -> int:
    """K = number of past decided joints shown in a request: max(H - 1, d)."""
    return max(px["window"] - 1, px["delay"])


def render_rulebook(px: dict) -> str:
    """Rulebook text: the mz-1 rulebook of the base, then the extension lines (plain: the mz-1 rulebook only)."""
    txt = dsl.render(px["base"])
    if is_plain(px):
        return txt
    L = [txt.rstrip("\n"), "extension mz-1x:"]
    d = px["delay"]
    L.append(f"  reply delay: {d} tick{'s' if d != 1 else ''}" + (
        " (a command decided now is applied that many ticks later; KEEP is in flight at start)" if d else ""))
    if px["hidden"]:
        L.append(f"  hidden vars (never displayed): {', '.join(px['hidden'])}")
        L.append(f"  history shown: last {px['window']} displayed observations")
    else:
        L.append("  hidden vars: none")
    return "\n".join(L) + "\n"
