from __future__ import annotations

import json
import os
from typing import Any

import torch

SMOL_REPO = "nagisanzeninz/nagi-smol-v0"
BIG_REPO = "nagisanzeninz/nagi-big-v0"
QWEN = "Qwen/Qwen3.5-4B"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class Nagi:
    """Jev/Laya-compatible system_one over an M2′ or letter-logit backend."""

    def __init__(self, model, tokenizer=None, kind: str = "m2p", temperature: float = 1.0, schema_context: bool = False, max_options: int = 26, chat_template: bool = False):
        self.model = model.eval()
        self.kind = kind
        self.temperature = temperature
        self.schema_context = schema_context
        self.chat_template = chat_template
        if not 2 <= max_options <= 78:
            raise ValueError("max_options must be between 2 and 78")
        self.max_options = max_options
        self.tok = tokenizer or getattr(model, "tokenizer", None)
        self._letter_ids = None

    def _device(self):
        return next(self.model.parameters()).device

    @staticmethod
    def _questions_as_dict(questions: dict) -> dict:
        out = {}
        for qid, q in questions.items():
            if isinstance(q, dict):
                out[qid] = q
            else:
                # typesafe-style object
                out[qid] = {
                    "type": getattr(q, "type", "choice"),
                    "instructions": getattr(q, "instructions", ""),
                    "criteria": getattr(q, "criteria", None),
                }
        return out

    @torch.no_grad()
    def system_one(self, state: Any, questions: dict) -> dict:
        qs = self._questions_as_dict(questions)
        if self.kind == "letter":
            return self._letter_system_one(state, qs)
        return self._m2p_system_one(state, qs)

    def _m2p_system_one(self, state: Any, questions: dict) -> dict:
        device = self._device()
        stxt = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)
        smax = getattr(self.model, "state_max_len", 512)
        omax = getattr(self.model, "option_max_len", 64)
        answers = {}
        for qid, q in questions.items():
            qtype = q.get("type", "choice")
            crit = q.get("criteria")
            if qtype == "choice" and isinstance(crit, dict):
                keys = list(crit)
                otexts = [f"{k}: {crit[k]}" for k in keys]
            elif qtype == "score":
                levels = crit if isinstance(crit, list) else list(range(4))
                keys = [str(i) for i in range(len(levels))]
                otexts = [f"{i}: {x}" for i, x in enumerate(levels)]
            else:
                keys = ["false", "true"]
                otexts = ["false", "true"]
            if self.schema_context:
                from nagi.render import render_state_context
                prompt = render_state_context({"state": state, "questions": {qid: q}}, qid)
            else:
                prompt = stxt + "\nQ: " + (q.get("instructions") or "")
            st = self.tok(prompt, truncation=True, max_length=smax, return_tensors="pt", padding="max_length")
            st = {k: v.to(device) for k, v in st.items()}
            K = len(otexts)
            opt_ids = torch.zeros(1, K, omax, dtype=torch.long, device=device)
            opt_mask = torch.zeros(1, K, omax, dtype=torch.long, device=device)
            for j, ot in enumerate(otexts):
                enc = self.tok(ot, truncation=True, max_length=omax, padding="max_length", return_tensors="pt")
                opt_ids[0, j] = enc["input_ids"][0].to(device)
                opt_mask[0, j] = enc["attention_mask"][0].to(device)
            qtid = torch.tensor([{"choice": 0, "score": 1, "noul": 2}[qtype]], device=device)
            logits = self.model(st["input_ids"], st["attention_mask"], opt_ids, opt_mask, qtid)[0] / self.temperature
            probs = torch.softmax(logits, -1)
            pdict = {k: float(probs[i]) for i, k in enumerate(keys)}
            conf = float(probs.max())
            if qtype == "noul":
                answers[qid] = {"noul": pdict.get("true", 0.5), "probabilities": pdict, "confidence": conf}
            elif qtype == "score":
                exp = sum(i * pdict[str(i)] for i in range(len(keys)))
                answers[qid] = {"score": exp, "probabilities": pdict, "confidence": conf}
            else:
                answers[qid] = {"choice": max(pdict, key=pdict.get), "probabilities": pdict, "confidence": conf}
        return {"answers": answers}

    def _letter_ids(self_tok):
        raise RuntimeError("unused")

    def _letter_system_one(self, state: Any, questions: dict) -> dict:
        from nagi.render import label_for, render_nagi_prompt, render_bounded_prompt, EXTENDED_SYMBOLS

        device = self._device()
        if self._letter_ids is None:
            encoded = [self.tok.encode(x, add_special_tokens=False) for x in EXTENDED_SYMBOLS[:self.max_options]]
            if any(len(x) != 1 for x in encoded) or len({x[0] for x in encoded}) != self.max_options:
                raise ValueError("Decision symbols must map to unique single tokens")
            self.__dict__["_letter_ids"] = [x[0] for x in encoded]
        row = {
            "state": state,
            "definition": None,
            "demos": [],
            "questions": questions,
        }
        answers = {}
        for qid, q in questions.items():
            prompt, keys = render_nagi_prompt(row, qid)
            if len(keys) > self.max_options:
                raise ValueError(f"Nagi-Big supports at most {self.max_options} options in this configuration")
            symbols = EXTENDED_SYMBOLS[:self.max_options]
            budget = 2048 if len(keys) > 26 else 768
            prompt, _ = render_bounded_prompt(self.tok, row, qid, budget - 64 if self.chat_template else budget, symbols=symbols)
            if self.chat_template:
                prompt = self.tok.apply_chat_template([{'role': 'user', 'content': prompt + '\nReturn exactly one option symbol; no explanation.'}], tokenize=False, add_generation_prompt=True, enable_thinking=False)
            enc = self.tok(prompt, return_tensors="pt", truncation=False)
            enc = {k: v.to(device) for k, v in enc.items()}
            logits = self.model(**enc).logits[0, -1]
            K = len(keys)
            selected = logits[self._letter_ids[:K]].float().cpu().double() / self.temperature
            probabilities = torch.softmax(selected, -1).tolist()
            pdict = dict(zip(keys, probabilities))
            conf = max(pdict.values())
            qtype = q.get("type", "choice")
            if qtype == "score":
                exp = sum(float(k) * pdict[k] for k in pdict if str(k).isdigit())
                answers[qid] = {"score": exp, "probabilities": pdict, "confidence": conf}
            elif qtype == "noul":
                answers[qid] = {"noul": pdict.get("true", 0.5), "probabilities": pdict, "confidence": conf}
            else:
                answers[qid] = {"choice": max(pdict, key=pdict.get), "probabilities": pdict, "confidence": conf}
        return {"answers": answers}


def _pick_device(device: str | None) -> str:
    if device:
        return device
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_smol(repo: str = SMOL_REPO, revision: str | None = None, device: str | None = None, temperature: float = 1.0) -> Nagi:
    """421M M2′ dual encoder + option tower."""
    from huggingface_hub import hf_hub_download
    from transformers import AutoTokenizer

    from nagi.model import build_model

    dev = _pick_device(device)
    cfg_path = hf_hub_download(repo, "config.snapshot.yaml", revision=revision)
    pt_path = hf_hub_download(repo, "model.pt", revision=revision)
    import yaml

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    model = build_model(cfg)
    state = torch.load(pt_path, map_location="cpu", weights_only=True)
    if isinstance(state, dict) and "state_dict" in state:
        state = state["state_dict"]
    model.load_state_dict(state, strict=True)
    model = model.to(dev)
    tok = model.tokenizer or AutoTokenizer.from_pretrained(cfg["model"]["state_encoder"])
    return Nagi(model, tokenizer=tok, kind="m2p", temperature=temperature,
                schema_context=cfg.get("model", {}).get("use_schema_options", False))


def load_big(repo: str = BIG_REPO, revision: str | None = None, device: str | None = None, temperature: float = 1.0, base_revision: str | None = None, max_options: int = 26, chat_template: bool = False) -> Nagi:
    """Qwen3.5-4B + PiSSA adapter, letter-logit readout."""
    from huggingface_hub import hf_hub_download
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    dev = _pick_device(device)
    tok = AutoTokenizer.from_pretrained(QWEN, revision=base_revision)
    base = AutoModelForCausalLM.from_pretrained(QWEN, revision=base_revision, dtype=torch.bfloat16 if dev == "cuda" else torch.float32, attn_implementation="eager")
    from huggingface_hub import snapshot_download

    adapter_dir = snapshot_download(repo, revision=revision, allow_patterns=["pissa/*"])
    adapter_dir = os.path.join(adapter_dir, "pissa")
    model = PeftModel.from_pretrained(base, adapter_dir)
    model = model.merge_and_unload().to(dev)
    return Nagi(model, tokenizer=tok, kind="letter", temperature=temperature, max_options=max_options, chat_template=chat_template)
