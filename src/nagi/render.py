from __future__ import annotations

import json
from typing import Any

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def label_for(i: int) -> str:
    return LETTERS[i] if i < 26 else (LETTERS[i // 26 - 1] + LETTERS[i % 26] if i < 702 else f"Q{i}")


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


def render_nagi_prompt(row: dict, qid: str | None = None) -> tuple[str, list[str]]:
    """definition + ≤2 demos + state + question + options (letter labels)."""
    qs = row.get("questions") or {}
    if qid is None:
        qid = next(iter(qs))
    q = qs[qid]
    keys = option_keys(q)
    crit = q.get("criteria")

    parts: list[str] = []
    defn = row.get("definition")
    if not defn:
        fam = row.get("schema_id") or row.get("family") or ""
        prefix = f"Task family: {fam}. " if fam else ""
        defn = f"{prefix}Task: {q.get('type', 'choice')} decision. {q.get('instructions', '')}"
    parts += ["TASK DEFINITION:", str(defn)]

    demos = row.get("demos") or []
    if demos:
        parts.append("\nEXAMPLES:")
        for i, d in enumerate(demos[:2], 1):
            parts.append(f"{i}) state: {state_text(d.get('state', ''))}")
            parts.append(f"   answer: {d.get('gold')} ({d.get('note', '')})")

    parts += ["\nSTATE:", state_text(row.get("state"))]
    parts.append(f"\nQUESTION ({q.get('type', 'choice')}): {q.get('instructions', '')}")
    parts.append("OPTIONS:")
    for i, k in enumerate(keys):
        if isinstance(crit, dict):
            desc = crit.get(k, k)
        elif isinstance(crit, list):
            desc = crit[i] if i < len(crit) else k
        else:
            desc = "false" if k == "false" else "true"
        parts.append(f"{label_for(i)}) {k}: {desc}")
    parts.append("\nAnswer:")
    return "\n".join(parts), keys


def target_probs(row: dict, qid: str, keys: list[str]) -> list[float]:
    gold = (row.get("gold") or {}).get(qid) or {}
    probs = gold.get("probabilities") or {}
    t = [float(probs.get(k, 0.0)) for k in keys]
    s = sum(t)
    return [x / s for x in t] if s > 0 else [1.0 / len(t)] * len(t)
