"""One request/render/timing contract for both pilot labels and actual serving.

The runner must call ``request`` after collecting fresh replies and computing
the controls applied at this boundary, before advancing the world. ``p_log``
is those applied controls, never the uncollected/in-flight reply. A new reply
applies at the next boundary under nominal1tick. Two ticks/mix are stress only.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from nagi.burst2._rt.burst_v2 import prompt as PR
from nagi.burst2._rt.burst_v2.rr import RRAdapter
from nagi.burst2._rt.nagi_r.render import render_chord_prompt

VERSION = "rrtp-request-v1"
NOMINAL_P_HAT = {1: 1.0}
CONTROLS = ("collective", "cyclic", "winch")
MAX_TOKENS = 1024
APPLIED_PREFIX = "APPLIED CONTROLS at this request boundary: "
_APPLIED = re.compile(r"^" + re.escape(APPLIED_PREFIX) +
                      r"collective=(\w+); cyclic=(\w+); winch=(\w+)\.$", re.M)


def normalize_controls(p_log: dict) -> dict:
    if set(p_log) != set(CONTROLS):
        raise ValueError("p_log must explicitly contain all three applied controls")
    out = {c: p_log[c] for c in CONTROLS}
    if any(out[c] not in RRAdapter.OPTIONS[c] for c in CONTROLS):
        raise ValueError("invalid applied control")
    return out


def applied_controls(text: str) -> dict:
    matches = list(_APPLIED.finditer(text))
    if len(matches) != 1:
        raise ValueError("exactly one explicit applied-controls line is required")
    return normalize_controls(dict(zip(CONTROLS, matches[0].groups())))


@dataclass(frozen=True)
class Request:
    state: str
    questions_json: str

    def __post_init__(self):
        applied_controls(self.state)
        q = self.questions
        if tuple(q) != CONTROLS:
            raise ValueError("canonical RR question order is required")
        if any(tuple(q[c].get("criteria", {})) != RRAdapter.OPTIONS[c] for c in CONTROLS):
            raise ValueError("canonical RR options are required")

    @property
    def questions(self) -> dict:
        return json.loads(self.questions_json)

    @property
    def p_log(self) -> dict:
        return applied_controls(self.state)

    @property
    def prompt(self) -> str:
        return render_chord_prompt({"state": self.state, "questions": self.questions})[0]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.prompt.encode()).hexdigest()

    def as_dict(self) -> dict:
        return {"contract": VERSION, "state": self.state, "questions_json": self.questions_json,
                "prompt_sha256": self.sha256}


def from_observation(observation: str, questions: dict, p_log: dict) -> Request:
    p = normalize_controls(p_log)
    if APPLIED_PREFIX in observation:
        raise ValueError("observation already contains applied-controls information")
    line = APPLIED_PREFIX + "; ".join(f"{c}={p[c]}" for c in CONTROLS) + "."
    state = observation + "\n" + line + "\nNominal reply delay: one 0.25 s tick."
    return Request(state, json.dumps(questions, separators=(",", ":")))


def request(binding, game, state, p_log: dict) -> Request:
    observation, questions = PR.served_request(binding, game, state, "rotorwash_ramp")
    return from_observation(observation, questions, p_log)


def encode(req: Request, tok) -> dict:
    from nagi.burst2._rt.nagi_r.chord import sdk_encode_chord
    sdk = type("ContractSDK", (), {"tok": tok, "max_tokens": MAX_TOKENS})()
    enc = sdk_encode_chord(sdk, req.state, req.questions)
    if enc["prompt"] != req.prompt:
        raise AssertionError("train/serve render mismatch")
    return enc


def hard_row(row_id: str, req: Request, answers: dict, meta: dict, tok=None) -> dict:
    """Deferred or encoded row; same IDs/render/weights across C/T, one row = one RR unit."""
    answers = normalize_controls(answers)
    targets = {c: {o: float(o == answers[c]) for o in req.questions[c]["criteria"]} for c in CONTROLS}
    out = dict(meta, id=row_id, contract=VERSION, a_star=[answers[c] for c in CONTROLS],
               prompt_sha256=req.sha256)
    if tok is None:
        out["deferred"] = {"state": req.state, "questions_json": req.questions_json,
                           "targets_json": json.dumps(targets, separators=(",", ":"))}
        return out
    enc = encode(req, tok)
    qids = [q for q, _ in enc["slots"]]
    keys = [list(k) for _, k in enc["slots"]]
    out.update(input_ids=enc["ids"], slot_positions=enc["positions"], slot_letter_ids=enc["letter_ids"],
               slot_targets=[[targets[q][o] for o in ks] for q, ks in zip(qids, keys)], qids=qids,
               keys=keys, n_tokens=len(enc["ids"]))
    return out
