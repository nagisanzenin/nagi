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

    def __init__(self, model, tokenizer=None, kind: str = "m2p", temperature: float = 1.0):
        self.model = model.eval()
        self.kind = kind
        self.temperature = temperature
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
        from nagi.render import label_for, render_nagi_prompt

        device = self._device()
        if self._letter_ids is None:
            self.__dict__["_letter_ids"] = [
                self.tok.encode(label_for(i), add_special_tokens=False)[0] for i in range(26)
            ]
        row = {
            "state": state,
            "definition": None,
            "demos": [],
            "questions": questions,
        }
        answers = {}
        for qid, q in questions.items():
            prompt, keys = render_nagi_prompt(row, qid)
            enc = self.tok(prompt, return_tensors="pt", truncation=True, max_length=768)
            enc = {k: v.to(device) for k, v in enc.items()}
            logits = self.model(**enc).logits[0, -1] / self.temperature
            K = min(len(keys), 26)
            raw = [float(logits[self._letter_ids[j]]) for j in range(K)]
            mx = max(raw)
            ex = [torch.exp(torch.tensor(z - mx, dtype=torch.float64)) for z in raw]
            s = float(sum(ex))
            pdict = {keys[j]: float(ex[j]) / s for j in range(K)}
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
    model.load_state_dict(state, strict=False)
    model = model.to(dev)
    tok = model.tokenizer or AutoTokenizer.from_pretrained(cfg["model"]["state_encoder"])
    return Nagi(model, tokenizer=tok, kind="m2p", temperature=temperature)


def load_big(repo: str = BIG_REPO, revision: str | None = None, device: str | None = None, temperature: float = 1.0) -> Nagi:
    """Qwen3.5-4B + PiSSA adapter, letter-logit readout."""
    from huggingface_hub import hf_hub_download
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    dev = _pick_device(device)
    tok = AutoTokenizer.from_pretrained(QWEN, revision=revision)
    base = AutoModelForCausalLM.from_pretrained(QWEN, dtype=torch.bfloat16 if dev == "cuda" else torch.float32)
    from huggingface_hub import snapshot_download

    adapter_dir = snapshot_download(repo, revision=revision, allow_patterns=["pissa/*"])
    adapter_dir = os.path.join(adapter_dir, "pissa")
    model = PeftModel.from_pretrained(base, adapter_dir)
    model = model.merge_and_unload().to(dev)
    return Nagi(model, tokenizer=tok, kind="letter", temperature=temperature)
