"""The served Burst chord prompt of a state, and its training encoding.

Served path (Burst release, scripts/arena_v3_worker.py interface 'chord' + canonical_order, player
enormous_burst/chord): mq = binding.multi_query(game, s) -> arena.agents_chord.sdk_chord_request(mq) ->
nagi.burst.canonical_questions(qs, the frozen per-game canonical order) -> sdk.encode_chord(state, qs) =
nagi.chord.sdk_encode_chord (render_chord_prompt + SDK chat template + encode_chord, no truncation). This module calls
exactly those functions; `encode` uses a shim with the Qwen3.8-27B tokenizer (HF cache, pinned revision).
Training row = the P1 chord format of scripts/chord_train_worker.encode_chord_rows (input_ids, slot_positions,
slot_letter_ids, slot_targets, qids, keys).
"""
from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

BASE_REVISION = "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"
CHORD_BUDGET = 900           # Arena chord prompt budget (GAME_BRIEF req. 7); every row asserts <= this
CHORD_CAP = 1024             # serving / training chord cap (R1.26)
# Burst release config br_A_s*: groups[0].players[0].canonical_orders (frozen prereg constants)
CANONICAL_ORDERS = {"booster_gauntlet": ("throttle", "gimbal", "fins", "legs"),
                    "rotorwash_ramp": ("collective", "cyclic", "winch"), "snake": ("move",)}


def served_request(binding, game, state, seed_game: str) -> tuple[str, dict]:
    """(state text, questions) exactly as the Burst worker builds them for this state (seat 0)."""
    from nagi.burst2._rt.arena.agents_chord import sdk_chord_request
    from nagi.burst2._rt.nagi_r.burst import canonical_questions
    mq = binding.multi_query(game, state)
    if mq is None:
        raise ValueError("no request: seat 0 is not playing")
    st, qs = sdk_chord_request(mq)
    return st, canonical_questions(qs, list(CANONICAL_ORDERS[seed_game]))


def kcall_text_sha(game, state) -> str:
    """sha256 of the runner's request text ('\\n\\n'.join of the K-call query texts) = the records' text_sha256."""
    qs = game.queries(state, 0, {})
    return hashlib.sha256("\n\n".join(q.text for q in qs).encode()).hexdigest()


@lru_cache(maxsize=1)
def tokenizer():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from transformers import AutoTokenizer
    snap = Path.home() / f".cache/huggingface/hub/models--Qwen--Qwen3.8-27B/snapshots/{BASE_REVISION}"
    if not (snap / "tokenizer.json").is_file():
        raise FileNotFoundError(f"Qwen3.8-27B tokenizer not cached at {snap}")
    return AutoTokenizer.from_pretrained(str(snap))


class _SDK:
    """The attributes nagi.chord.sdk_encode_chord reads from NagiEnormous (tok, max_tokens)."""

    def __init__(self, tok, max_tokens: int = CHORD_CAP):
        self.tok, self.max_tokens = tok, max_tokens


def encode(state_text: str, questions: dict, tok=None) -> dict:
    from nagi.burst2._rt.nagi_r.chord import sdk_encode_chord
    enc = sdk_encode_chord(_SDK(tok or tokenizer()), state_text, questions)
    if len(enc["ids"]) > CHORD_BUDGET:
        raise ValueError(f"chord prompt {len(enc['ids'])} tokens > budget {CHORD_BUDGET}")
    return enc


def train_row(row_id: str, state_text: str, questions: dict, targets: dict, meta: dict, tok=None) -> dict:
    """P1 chord row. targets = {qid: {option: prob}} (sum 1 per control).
    BV2_DEFER_ENCODE=1 (Linux CPU relabel jobs without the tokenizer): the served request is stored instead of token
    ids ('deferred'); scripts/ev2_encode_deferred.py encodes it on a machine with the pinned tokenizer and checks the
    rendered prompt sha256."""
    if os.environ.get("BV2_DEFER_ENCODE") == "1":
        from nagi.burst2._rt.nagi_r.render import render_chord_prompt
        prompt, _ = render_chord_prompt({"state": state_text, "questions": questions})
        # questions as a JSON string: the rows file is written with sort_keys, which would reorder slots and options
        return dict(meta, id=row_id, deferred={"state": state_text, "questions_json": json.dumps(questions),
                                               "targets_json": json.dumps(targets)},
                    prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
    enc = encode(state_text, questions, tok)
    keys = [list(k) for _, k in enc["slots"]]
    qids = [q for q, _ in enc["slots"]]
    slot_targets = []
    for q, ks in zip(qids, keys):
        t = [float(targets[q][o]) for o in ks]
        assert abs(sum(t) - 1) < 1e-6 and all(v >= 0 for v in t), (row_id, q)
        slot_targets.append(t)
    return dict(meta, id=row_id, input_ids=enc["ids"], slot_positions=enc["positions"],
                slot_letter_ids=enc["letter_ids"], slot_targets=slot_targets, qids=qids, keys=keys,
                n_tokens=len(enc["ids"]), prompt_sha256=hashlib.sha256(enc["prompt"].encode()).hexdigest())
