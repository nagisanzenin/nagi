"""Shared pieces of the bv2n observation contract (G1): number formatting, the chord prompt wrapper, the tokenizer.

Every game module (snake, rr, booster) builds a frozen ClientView from what the client legitimately has at a request
boundary, renders it to the served state text (Burst V1's state sections verbatim + new V2 sections), wraps it in the
V1 chord prompt (nagi.render.render_chord_prompt with the canonical questions) and parses the prompt back exactly.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path

from nagi.burst2._rt.nagi_r.render import render_chord_prompt

CAP_TOKENS = 1024                      # serving / training chord cap (R1.26); zero truncation
TOKENIZER_DIRS = (
    Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen3.8-27B/snapshots/1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0",
    Path.home() / ".cache/nagi_tok/qwen3.8-27b",
)
APPLIED_PREFIX = "APPLIED now: "
_STATE_RE = re.compile(r"\nSTATE:\n(.*)\n\nCONTROLS \(choose all at the same time\):\n", re.S)


def fnum(v: int, nd: int, sign: bool = True) -> str:
    """Inverse of the engines' display rounding: v is the DISPLAYED value in units of 10^-nd (an int). Matches
    arena.games.booster._fmt_int on the rounded value: '+0' for zero, '-' only for a nonzero negative."""
    neg = v < 0
    a = -v if neg else v
    m = 10 ** nd
    s = str(a // m) + ("." + str(a % m).zfill(nd) if nd else "")
    return ("-" + s) if neg else (("+" + s) if sign else s)


def pnum(s: str, nd: int) -> int:
    """Parse a displayed decimal with exactly nd decimals into an int in units of 10^-nd."""
    neg = s.startswith("-")
    s = s.lstrip("+-")
    if nd:
        a, b = s.split(".")
        assert len(b) == nd, (s, nd)
        v = int(a) * 10 ** nd + int(b)
    else:
        assert "." not in s, s
        v = int(s)
    return -v if neg else v


def questions_json(qs: dict) -> str:
    return json.dumps(qs, separators=(",", ":"))


def chord_prompt(state: str, questions: dict) -> str:
    return render_chord_prompt({"state": state, "questions": questions})[0]


def split_prompt(prompt: str, questions: dict) -> str:
    """The state text of a chord prompt; fails closed unless the prompt is exactly chord_prompt(state, questions)."""
    m = _STATE_RE.search(prompt)
    if not m:
        raise ValueError("not a chord prompt")
    state = m.group(1)
    if chord_prompt(state, questions) != prompt:
        raise ValueError("prompt is not the canonical chord prompt of its state")
    return state


def applied_line(controls: tuple, values: tuple) -> str:
    return APPLIED_PREFIX + ", ".join(f"{c} {v}" for c, v in zip(controls, values))


def parse_applied(line: str, controls: tuple, options: dict) -> tuple:
    if not line.startswith(APPLIED_PREFIX):
        raise ValueError(f"bad applied-controls line: {line!r}")
    parts = line[len(APPLIED_PREFIX):].split(", ")
    out = []
    for c, p in zip(controls, parts, strict=True):
        k, v = p.split(" ")
        if k != c or v not in options[c]:
            raise ValueError(f"bad applied control {p!r}")
        out.append(v)
    return tuple(out)


def sha256_file(p: str | Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def tokenizer():
    """The Qwen3.8-27B tokenizer (pinned HF snapshot if cached, else the local nagi_tok copy). Offline only."""
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from transformers import AutoTokenizer
    for d in TOKENIZER_DIRS:
        if (d / "tokenizer.json").is_file():
            tok = AutoTokenizer.from_pretrained(str(d))
            tok.bv2n_source = str(d)
            tok.bv2n_sha256 = sha256_file(d / "tokenizer.json")
            return tok
    raise FileNotFoundError("no cached Qwen3.8-27B tokenizer")


def n_tokens(state: str, questions: dict, tok=None, cap: int = CAP_TOKENS) -> int:
    """Served token count (SDK chat template + chord validation, no truncation; raises above `cap`)."""
    from nagi.burst2._rt.nagi_r.chord import sdk_encode_chord
    sdk = type("ContractSDK", (), {"tok": tok or tokenizer(), "max_tokens": cap})()
    return len(sdk_encode_chord(sdk, state, questions)["ids"])
