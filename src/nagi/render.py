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
