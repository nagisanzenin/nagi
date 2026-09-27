"""Burst: K simultaneous closed-set decisions (one per control) from ONE forward pass.

Burst was called "Chord" during research. ``mode="chord"``, ``encode_chord`` and ``render_chord_prompt`` still work
as deprecated aliases.

How the readout works (the same code finds the slots at training and at inference):

    prompt     = render_burst_prompt(state, questions in canonical control order)
    chat       = chat template(user = prompt), generation prompt, thinking off
    ids        = tok.encode(chat, add_special_tokens=False)
    positions  = burst_slot_positions(ids, blank_id, K)    p_k = index of the token BEFORE the k-th blank,
                                                            i.e. the last token of "[k]"
    slot k     = restricted softmax over the letter tokens A.. of slot k's options, read from the LM head at p_k

The blank is a fixed placeholder, so no slot sees another slot's answer: the K choices are simultaneous.

Control order matters: in research, rotating the slot order by one changed the joint action on 26% of states
(Chord P1, REJECT-ORDER). Two mitigations, both here:

1. Canonical control order (``canonical_control_order``), always applied: an explicit ``control_order``; else the
   order of the state's ``CONTROLS (set together each tick): a = ...; b = ...`` line (the trained layout); else the
   question ids sorted by code point. The prompt is therefore a function of the control SET: listing the same
   controls in another dict order renders the same prompt (the order resolution gated for the 0.6.0 release).
2. Permutation averaging (``permutations="cyclic"`` or ``"all"``): EXPERIMENTAL and off by default. It averages each
   control's probabilities over re-rendered slot orders and costs one forward per order. It is not the released
   configuration: the permutation-averaged variant failed its latency and order-residual release gates.
"""
from __future__ import annotations

import itertools
import re
import warnings
from typing import Callable, Sequence

from nagi.render import BURST_ANSWER, BURST_BLANK, render_burst_prompt

MAX_OPTIONS = 26
MIN_OPTIONS = 2
PERMUTATION_MODES = (None, "cyclic", "all")
MAX_ALL_PERMUTATION_SLOTS = 4          # "all" is K! forwards: 24 at K = 4
_CONTROLS_LINE = re.compile(r"^CONTROLS \(set together each tick\):[ \t]*(.+?)[ \t]*$", re.M)


# ----------------------------------------------------------------------------- control order

def controls_line_order(state) -> list[str] | None:
    """Control names in the order of the state's ``CONTROLS (set together each tick):`` line, or None.

    The line lists ``name = option | option; name = ...`` (a trailing period is allowed). Only string states are read;
    if the line occurs more than once the last one wins."""
    if not isinstance(state, str):
        return None
    found = _CONTROLS_LINE.findall(state)
    if not found:
        return None
    names = []
    for part in found[-1].rstrip(".").split(";"):
        name = part.split("=", 1)[0].strip()
        if name:
            names.append(name)
    return names or None


def canonical_control_order(state, questions: dict, control_order: Sequence[str] | None = None) -> tuple[list[str], str]:
    """(slot order, source). Source is "explicit", "controls_line" or "sorted".

    An explicit ``control_order`` must be a permutation of the question ids (ValueError otherwise). A CONTROLS line
    is used only when it names exactly the question ids; otherwise the ids are sorted by code point, never taken in
    the caller's dict order, so the rendered prompt does not depend on how the caller listed the controls."""
    qids = list(questions)
    if control_order is not None:
        order = list(control_order)
        if sorted(order) != sorted(qids) or len(set(order)) != len(order):
            raise ValueError("control_order must be a permutation of the question ids")
        return order, "explicit"
    line = controls_line_order(state)
    if line is not None and len(line) == len(set(line)) and sorted(line) == sorted(qids):
        return line, "controls_line"
    return sorted(qids), "sorted"


def permutation_orders(order: Sequence[str], mode: str | None) -> list[list[str]]:
    """Slot orders to average over. None: [order]. "cyclic": the K rotations (order first). "all": all K! orders
    (order first; K <= MAX_ALL_PERMUTATION_SLOTS)."""
    order = list(order)
    if mode not in PERMUTATION_MODES:
        raise ValueError(f"permutations must be one of {PERMUTATION_MODES}")
    if mode is None or len(order) == 1:
        return [order]
    if mode == "cyclic":
        return [order[i:] + order[:i] for i in range(len(order))]
    if len(order) > MAX_ALL_PERMUTATION_SLOTS:
        raise ValueError(f'permutations="all" supports at most {MAX_ALL_PERMUTATION_SLOTS} controls; use "cyclic"')
    return [list(p) for p in itertools.permutations(order)]


def average_probabilities(runs: Sequence[dict[str, dict[str, float]]]) -> dict[str, dict[str, float]]:
    """Arithmetic mean of each control's option probabilities over runs ({qid: {key: p}} each)."""
    if not runs:
        raise ValueError("no runs to average")
    out = {}
    for qid, probs in runs[0].items():
        keys = list(probs)
        for r in runs[1:]:
            if list(r[qid]) != keys:
                raise ValueError(f"{qid}: option keys differ across runs")
        out[qid] = {k: sum(r[qid][k] for r in runs) / len(runs) for k in keys}
    return out


def answer_from_probabilities(q: dict, probs: dict[str, float]) -> dict:
    """The same answer dict as the K-call path; ties go to the first option in the question's own order."""
    keys = list(probs)
    p = [probs[k] for k in keys]
    answer = {"probabilities": dict(probs), "confidence": max(p)}
    kind = q.get("type", "choice")
    if kind == "score":
        answer["score"] = sum(float(k) * v for k, v in probs.items())
    elif kind == "noul":
        answer["noul"] = probs["true"]
    else:
        answer["choice"] = keys[max(range(len(p)), key=p.__getitem__)]
    return answer


# ----------------------------------------------------------------------------- tokenization + slots

def sdk_chat_text(tok, prompt: str) -> str:
    """The SDK chat text: user turn, generation prompt, thinking off."""
    return tok.apply_chat_template([{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True,
                                   enable_thinking=False)


def burst_slot_positions(ids: Sequence[int], blank_id: int, n_slots: int | None = None) -> list[int]:
    """Readout positions of the answer slots: the index of the token before each occurrence of ``blank_id``."""
    ids = list(ids)
    pos = [i - 1 for i, t in enumerate(ids) if t == blank_id]
    if n_slots is not None and len(pos) != n_slots:
        raise ValueError(f"expected {n_slots} answer slots, found {len(pos)} blank tokens")
    if any(p < 0 for p in pos):
        raise ValueError("a blank token cannot be the first token")
    return pos


def _slot_char_ends(chat: str, n_slots: int) -> list[int]:
    start = chat.rfind(BURST_ANSWER)
    if start < 0:
        raise ValueError("Burst prompt has no ANSWER block")
    ends, cur = [], start
    for k in range(1, n_slots + 1):
        tag = f"[{k}]{BURST_BLANK}"
        i = chat.find(tag, cur)
        if i < 0:
            raise ValueError(f"answer slot [{k}] not found")
        ends.append(i + len(f"[{k}]"))
        cur = i + len(tag)
    if chat.count(BURST_BLANK) != n_slots:
        raise ValueError(f"the blank marker {BURST_BLANK!r} occurs {chat.count(BURST_BLANK)} times; expected {n_slots}")
    return ends


def encode_burst(tok, prompt: str, slot_keys: Sequence[Sequence[str]], max_tokens: int,
                 chat: Callable[[object, str], str] | None = None, check_letters: bool = True) -> dict:
    """Tokenize a Burst prompt and validate every slot; never truncates.

    Checks: 2..26 options per slot; the chat template closed any thinking block; len(ids) <= max_tokens; the text up
    to each "[k]" tokenizes to a prefix of ids; the blank is ONE token, the same id in every slot, and occurs exactly
    K times; each option letter appended at a slot boundary is exactly one extra token; letters distinct per slot.
    Returns {"chat", "ids", "positions", "letter_ids" (per slot), "blank_id"}."""
    n = len(slot_keys)
    if n < 1:
        raise ValueError("at least one slot is required")
    for keys in slot_keys:
        if not MIN_OPTIONS <= len(keys) <= MAX_OPTIONS:
            raise ValueError(f"Burst supports {MIN_OPTIONS}–{MAX_OPTIONS} options per slot")
    text = (chat or sdk_chat_text)(tok, prompt)
    if "<think>" in text and "</think>" not in text[text.rindex("<think>"):]:
        raise ValueError("Chat template left a thinking block open; enable_thinking=False was not honoured")
    ids = tok.encode(text, add_special_tokens=False)
    if len(ids) > max_tokens:
        raise ValueError(f"Input has {len(ids)} tokens; limit {max_tokens}. No truncation was applied.")
    ends = _slot_char_ends(text, n)
    blank_id, positions, letters = None, [], []
    for k, (end, keys) in enumerate(zip(ends, slot_keys), 1):
        pid = tok.encode(text[:end], add_special_tokens=False)
        if ids[:len(pid)] != pid or len(pid) >= len(ids):
            raise ValueError(f"Answer slot [{k}] boundary changes tokenization")
        b = ids[len(pid)]
        if tok.decode([b]) != BURST_BLANK:
            raise ValueError(f"Answer slot [{k}]: the blank marker is not a single token after the slot tag")
        if blank_id is None:
            blank_id = b
        elif b != blank_id:
            raise ValueError("The blank marker tokenizes differently across slots")
        positions.append(len(pid) - 1)
        if check_letters:
            row = []
            for j in range(len(keys)):
                comb = tok.encode(text[:end] + chr(65 + j), add_special_tokens=False)
                if len(comb) != len(pid) + 1 or comb[:-1] != pid:
                    raise ValueError(f"Answer slot [{k}]: letter {chr(65 + j)} changes tokenization")
                row.append(comb[-1])
            if len(set(row)) != len(row):
                raise ValueError(f"Answer slot [{k}]: letter slots collide")
            letters.append(row)
    if burst_slot_positions(ids, blank_id, n) != positions:
        raise ValueError("slot positions disagree with burst_slot_positions")
    return {"chat": text, "ids": ids, "positions": positions, "letter_ids": letters, "blank_id": blank_id}


def sdk_encode_burst(sdk, state, questions: dict, control_order: Sequence[str] | None = None) -> dict:
    """Validation + tokenization in canonical control order (usable outside the timed call for token counts)."""
    if not isinstance(questions, dict) or not questions:
        raise ValueError("questions must be a nonempty dict")
    for q in questions.values():
        if not isinstance(q, dict) or q.get("type", "choice") not in ("choice", "score", "noul"):
            raise ValueError("Supported question types: choice, score, noul")
    order, source = canonical_control_order(state, questions, control_order)
    prompt, slots = render_burst_prompt({"state": state, "questions": questions}, order)
    enc = encode_burst(sdk.tok, prompt, [k for _, k in slots], sdk.max_tokens)
    enc.update(prompt=prompt, slots=slots, order=order, order_source=source)
    return enc


# ----------------------------------------------------------------------------- SDK readout (torch)

def _forward_slots(sdk, enc) -> dict[str, dict[str, float]]:
    import torch

    core = sdk.model.get_base_model() if hasattr(sdk.model, "get_base_model") else sdk.model
    text = core.model.language_model if hasattr(core.model, "language_model") else core.model
    device = next(sdk.model.parameters()).device
    x = torch.tensor([enc["ids"]], device=device)
    hidden = text(input_ids=x, attention_mask=torch.ones_like(x), use_cache=False).last_hidden_state[0]
    weight = core.get_output_embeddings().weight
    cap = getattr(core.config.get_text_config(), "final_logit_softcapping", None)
    out = {}
    for (qid, keys), pos, letters in zip(enc["slots"], enc["positions"], enc["letter_ids"]):
        z = torch.nn.functional.linear(hidden[pos:pos + 1], weight[torch.tensor(letters, device=device)])
        if cap:
            z = cap * torch.tanh(z / cap)
        out[qid] = dict(zip(keys, (z.float() / sdk.temperature).softmax(-1)[0].cpu().tolist()))
    return out


def burst_system_one(sdk, state, questions: dict, control_order: Sequence[str] | None = None,
                     permutations: str | None = None) -> dict:
    """ONE forward (or one per slot order with ``permutations``) -> the K-call answer shape, keyed in the caller's
    question order, plus ``"burst": {"order", "order_source", "forwards", "permutations"}``.

    Softcap and temperature exactly as the K-call path: p = softmax(softcap(h_p · W[letters]) / T)."""
    import torch

    base = sdk_encode_burst(sdk, state, questions, control_order)
    orders = permutation_orders(base["order"], permutations)
    runs = []
    with torch.inference_mode():
        for i, order in enumerate(orders):
            enc = base if i == 0 else sdk_encode_burst(sdk, state, questions, order)
            runs.append(_forward_slots(sdk, enc))
    probs = runs[0] if len(runs) == 1 else average_probabilities(runs)
    answers = {qid: answer_from_probabilities(questions[qid], probs[qid]) for qid in questions}
    return {"answers": answers, "burst": {"order": base["order"], "order_source": base["order_source"],
                                          "forwards": len(runs), "permutations": permutations}}


def normalize_mode(mode: str) -> str:
    """"kcall" | "burst"; "chord" is a deprecated alias of "burst"."""
    if mode == "chord":
        warnings.warn('mode="chord" is deprecated; use mode="burst" (Chord was renamed Burst)', DeprecationWarning,
                      stacklevel=3)
        return "burst"
    if mode not in ("kcall", "burst"):
        raise ValueError("mode must be 'kcall' or 'burst'")
    return mode


# Deprecated research names.
def chord_slot_positions(ids, blank_id, n_slots=None):
    warnings.warn("chord_slot_positions is deprecated; use burst_slot_positions", DeprecationWarning, stacklevel=2)
    return burst_slot_positions(ids, blank_id, n_slots)


def encode_chord(tok, prompt, slot_keys, max_tokens, chat=None, check_letters=True):
    warnings.warn("encode_chord is deprecated; use encode_burst", DeprecationWarning, stacklevel=2)
    return encode_burst(tok, prompt, slot_keys, max_tokens, chat, check_letters)
