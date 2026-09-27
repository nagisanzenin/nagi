from __future__ import annotations

"""Shared renderer: definition + 2 demos + state → model input.

Used by Track S (M2′) and Track G (Qwen PiSSA Choice-B) and T3b eval.
"""

import json
from typing import Any


LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
EXTENDED_SYMBOLS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$%&*+-/:;<=>?@")


def label_for(i: int) -> str:
    if i < 26:
        return LETTERS[i]
    return (LETTERS[i // 26 - 1] + LETTERS[i % 26]) if i < 702 else f"Q{i}"


def option_keys(q: dict) -> list[str]:
    t = q.get("type", "choice")
    crit = q.get("criteria")
    if t == "choice" and isinstance(crit, dict):
        return list(crit.keys())
    if t == "score":
        levels = crit if isinstance(crit, list) else list(range(4))
        return [str(i) for i in range(len(levels))]
    return ["false", "true"]


def state_text(state: Any) -> str:
    return state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)


def render_nagi_prompt(row: dict, qid: str | None = None, symbols: list[str] | None = None) -> tuple[str, list[str]]:
    """Build (prompt, option_keys) for one question. Uses definition+demos when present.

    Research: mixed definition+2 demos encoding is required for schema transfer.
    """
    qs = row.get("questions") or {}
    if qid is None:
        qid = next(iter(qs))
    q = qs[qid]
    keys = option_keys(q)
    crit = q.get("criteria")

    parts: list[str] = []
    defn = row.get("definition")
    if not defn:
        # fall back to schema card from family + instructions
        defn = f"Task: {q.get('type','choice')} decision. {q.get('instructions','')}"
    parts.append("TASK DEFINITION:")
    parts.append(str(defn))

    demos = row.get("demos") or []
    if demos:
        parts.append("\nEXAMPLES:")
        for i, d in enumerate(demos[:2], 1):
            parts.append(f"{i}) state: {state_text(d.get('state',''))}")
            parts.append(f"   answer: {d.get('gold')} ({d.get('note','')})")

    parts.append("\nSTATE:")
    parts.append(state_text(row.get("state")))

    parts.append(f"\nQUESTION ({q.get('type','choice')}): {q.get('instructions','')}")
    parts.append("OPTIONS:")
    for i, k in enumerate(keys):
        if isinstance(crit, dict):
            desc = crit.get(k, k)
        elif isinstance(crit, list):
            desc = crit[i] if i < len(crit) else k
        else:
            desc = "false" if k == "false" else "true"
        parts.append(f"{symbols[i] if symbols is not None else label_for(i)}) {k}: {desc}")
    parts.append("\nAnswer:")
    return "\n".join(parts), keys


def render_state_context(row: dict, qid: str | None = None) -> str:
    """M2′ state-tower input: definition + ≤2 demos + state + question.

    OPTIONS block is omitted — the option tower owns per-option text.
    Same fallback card as render_nagi_prompt so train/eval stay aligned.
    """
    qs = row.get("questions") or {}
    if qid is None:
        qid = next(iter(qs))
    q = qs[qid]
    parts: list[str] = []
    defn = row.get("definition")
    if not defn:
        fam = row.get("schema_id") or row.get("family") or ""
        prefix = f"Task family: {fam}. " if fam else ""
        defn = f"{prefix}Task: {q.get('type', 'choice')} decision. {q.get('instructions', '')}"
    parts.append("TASK DEFINITION:")
    parts.append(str(defn))

    demos = row.get("demos") or []
    if demos:
        parts.append("\nEXAMPLES:")
        for i, d in enumerate(demos[:2], 1):
            parts.append(f"{i}) state: {state_text(d.get('state', ''))}")
            parts.append(f"   answer: {d.get('gold')} ({d.get('note', '')})")

    parts.append("\nSTATE:")
    parts.append(state_text(row.get("state")))
    parts.append(f"\nQUESTION ({q.get('type', 'choice')}): {q.get('instructions', '')}")
    return "\n".join(parts)


def target_probs(row: dict, qid: str, keys: list[str]) -> list[float]:
    gold = (row.get("gold") or {}).get(qid) or {}
    probs = gold.get("probabilities") or {}
    t = [float(probs.get(k, 0.0)) for k in keys]
    s = sum(t)
    return [x / s for x in t] if s > 0 else [1.0 / len(t)] * len(t)


def render_bounded_prompt(tok,row,qid,max_len=768,symbols=None):
    """Preserve question/options/suffix; trim only serialized state to token budget."""
    r={'state':row['state'],'questions':row['questions']}; text=r['state'] if isinstance(r['state'],str) else json.dumps(r['state'],ensure_ascii=False)
    st=tok.encode(text,add_special_tokens=False)
    def render(n):
        rr=dict(r,state=tok.decode(st[:n],skip_special_tokens=True))
        return render_nagi_prompt(rr,qid,symbols=symbols)[0]
    full=render(len(st)); ids=tok.encode(full,add_special_tokens=True)
    if len(ids)<=max_len:return full,False
    if len(tok.encode(render(0),add_special_tokens=True))>max_len:raise ValueError('schema_exceeds_context')
    lo,hi=0,len(st)
    while lo<hi:
        mid=(lo+hi+1)//2
        if len(tok.encode(render(mid),add_special_tokens=True))<=max_len:lo=mid
        else:hi=mid-1
    return render(lo),True


# ----------------------------------------------------------------------------- Burst (one-forward multi-control)
# Burst was called "Chord" during research. The prompt strings below are byte-identical to the trained format;
# only the Python names changed. The CHORD_* / render_chord_prompt names remain as deprecated aliases.

BURST_BLANK = "\u25a1"  # WHITE SQUARE; one stable token in the Qwen3.8-27B tokenizer (id 169260)
BURST_HEADER = "CONTROLS (choose all at the same time):"
BURST_ANSWER = "ANSWER:"
BURST_DEFAULT_DEFINITION = "Task: choose every control at the same time; answer each [k] with one option letter."


def _option_desc(q: dict, keys: list[str], i: int, k: str) -> str:
    crit = q.get("criteria")
    if isinstance(crit, dict):
        return str(crit.get(k, k))
    if isinstance(crit, list):
        return str(crit[i]) if i < len(crit) else k
    return "false" if k == "false" else "true"


def render_burst_prompt(row: dict, qids: list[str] | None = None,
                        symbols: list[str] | None = None) -> tuple[str, list[tuple[str, list[str]]]]:
    """Burst prompt: every question of `row` in ONE prompt with one answer slot per question.

    Returns (prompt, [(qid, option_keys), ...]) in slot order (slot k = qids[k-1]; default: dict order).
    Layout:
        TASK DEFINITION:
        <definition, or BURST_DEFAULT_DEFINITION>
        [k] <qid> (<type>): <instructions>          one line per slot WITH nonempty instructions
        <blank>
        STATE:
        <state>
        <blank>
        CONTROLS (choose all at the same time):
        [k] <qid>: A) key: desc  B) key: desc ...   one line per slot
        <blank>
        ANSWER:
        [1]□
        ...
        [K]□                                         (no trailing newline)
    The model's answer for slot k is read at the last token of "[k]" (the token before the k-th BURST_BLANK);
    see nagi.burst.burst_slot_positions. BURST_BLANK must not occur anywhere else in the prompt.
    """
    qs = row.get("questions") or {}
    if not isinstance(qs, dict) or not qs:
        raise ValueError("questions must be a nonempty dict")
    qids = list(qs) if qids is None else list(qids)
    if not qids:
        raise ValueError("at least one slot is required")
    if len(set(qids)) != len(qids):
        raise ValueError("duplicate qids")
    slots: list[tuple[str, list[str]]] = []
    for qid in qids:
        if qid not in qs:
            raise KeyError(qid)
        if not isinstance(qid, str) or not qid or "\n" in qid:
            raise ValueError(f"qid must be a nonempty single-line string: {qid!r}")
        q = qs[qid]
        if not isinstance(q, dict):
            raise ValueError(f"question {qid!r} must be a dict")
        keys = option_keys(q)
        if symbols is not None and len(keys) > len(symbols):
            raise ValueError(f"{qid!r}: {len(keys)} options > {len(symbols)} symbols")
        slots.append((qid, keys))
    sym = (lambda i: symbols[i]) if symbols is not None else label_for
    parts = ["TASK DEFINITION:", str(row.get("definition") or BURST_DEFAULT_DEFINITION)]
    for k, (qid, _) in enumerate(slots, 1):
        q = qs[qid]
        ins = str(q.get("instructions") or "").strip()
        if ins:
            parts.append(f"[{k}] {qid} ({q.get('type', 'choice')}): {ins}")
    parts.append("\nSTATE:")
    parts.append(state_text(row.get("state")))
    parts.append("\n" + BURST_HEADER)
    for k, (qid, keys) in enumerate(slots, 1):
        opts = "  ".join(f"{sym(i)}) {key}: {_option_desc(qs[qid], keys, i, key)}" for i, key in enumerate(keys))
        parts.append(f"[{k}] {qid}: {opts}")
    parts.append("\n" + BURST_ANSWER)
    parts.append("\n".join(f"[{k}]{BURST_BLANK}" for k in range(1, len(slots) + 1)))
    prompt = "\n".join(parts)
    if prompt.count(BURST_BLANK) != len(slots):
        raise ValueError(f"the Burst blank marker {BURST_BLANK!r} must not occur in the state, definition, "
                         "instructions, qids or options")
    return prompt, slots


# Deprecated aliases (research name "Chord"); kept so existing callers keep working.
CHORD_BLANK = BURST_BLANK
CHORD_HEADER = BURST_HEADER
CHORD_ANSWER = BURST_ANSWER
CHORD_DEFAULT_DEFINITION = BURST_DEFAULT_DEFINITION


def render_chord_prompt(row: dict, qids: list[str] | None = None,
                        symbols: list[str] | None = None) -> tuple[str, list[tuple[str, list[str]]]]:
    """Deprecated alias of render_burst_prompt (Chord was renamed Burst)."""
    import warnings
    warnings.warn("render_chord_prompt is deprecated; use render_burst_prompt (Chord was renamed Burst)",
                  DeprecationWarning, stacklevel=2)
    return render_burst_prompt(row, qids, symbols)
