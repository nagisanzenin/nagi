"""Multi-domain arm S core: ONE checkpoint (.npz) serving Zoo machines and the 3 Arena games (pure numpy serve path).

Architecture and training: ``v2g.core.train_multi`` (module doc). Serve path, per domain:
  zoo      ``zoo_core()`` = a StructCore over the checkpoint's zoo parameters (same names) -> Core.predict contract
           (prior over the 27 joints factorized per slot, value in [0,1], v_reward, p_opt, conf, supported).
  games    ``predict_game(game, X)`` on the reference students' features (bv2n.student.features: snake_lf_x,
           rr_x, booster_x) -> per-slot logits, joint logits over the full mixed-radix joint space (first slot most
           significant = data lane encoding, the same convention as mz-1 joints), value (sigmoid; untrained in
           bring-up v0 -> reported as nan unless cfg["game_value"][game] is true), conf = max softmax over joints.
           ``GamePolicy(core, game)`` adapts it to the bv2n closed-loop evaluator (``.act(view)``: per-slot argmax).
Numerics: float32 numpy; the torch twin is tested equal (tests/test_v2g_core_multi.py).
"""

from __future__ import annotations

import hashlib
import json

import numpy as np

from nagi.burst2._rt.v2g.core import game_data as G
from nagi.burst2._rt.v2g.core import struct_core as SC

_lin, _ln, gelu = SC._lin, SC._ln, SC.gelu_tanh


def relu(x):
    return np.maximum(x, np.float32(0))


def conv2d(x, w, b, stride=1, pad=0):
    """x [B, C, H, W], w [O, C, k, k] -> [B, O, H', W'] (cross-correlation = torch.nn.Conv2d)."""
    if pad:
        x = np.pad(x, ((0, 0), (0, 0), (pad, pad), (pad, pad)))
    k = w.shape[-1]
    win = np.lib.stride_tricks.sliding_window_view(x, (k, k), axis=(2, 3))[:, :, ::stride, ::stride]  # B,C,H',W',k,k
    B, C, Ho, Wo = win.shape[:4]
    cols = win.transpose(0, 2, 3, 1, 4, 5).reshape(B * Ho * Wo, C * k * k)
    y = cols @ w.reshape(w.shape[0], -1).T + b
    return y.reshape(B, Ho, Wo, -1).transpose(0, 3, 1, 2).astype(np.float32)


def blocks_np(p, prefix, h, cfg):
    B, T, d = h.shape
    H = cfg["heads"]
    dh = d // H
    scale = np.float32(1.0 / np.sqrt(dh))
    for i in range(cfg["layers"]):
        b = f"{prefix}blocks.{i}."
        y = _ln(h, p, b + "ln1")
        qkv = _lin(y, p, b + "qkv").reshape(B, T, 3, H, dh).transpose(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        s = (q @ k.transpose(0, 1, 3, 2)) * scale
        s = s - s.max(-1, keepdims=True)
        w = np.exp(s)
        w = w / w.sum(-1, keepdims=True)
        h = h + _lin((w @ v).transpose(0, 2, 1, 3).reshape(B, T, d), p, b + "proj")
        h = h + _lin(gelu(_lin(_ln(h, p, b + "ln2"), p, b + "fc1")), p, b + "fc2")
    return _ln(h, p, prefix + "ln_f")


def game_forward(p: dict, cfg: dict, game: str, X: np.ndarray) -> tuple[list, np.ndarray]:
    """(per-slot logits [B, n_s], value logit [B]) for raw features X [B, dim]."""
    g = f"g.{game}."
    a = cfg["game_arch"][game]
    x = ((np.asarray(X, np.float32) - p[g + "mu"]) / p[g + "sd"]).astype(np.float32)
    if a["enc"] == "cnn":
        img = x[:, :G.SN_IMG].reshape(-1, G.SN_C, G.SN_W, G.SN_W)
        c = relu(conv2d(img, p[g + "conv.0.weight"], p[g + "conv.0.bias"], 1, 1))
        c = relu(conv2d(c, p[g + "conv.2.weight"], p[g + "conv.2.bias"], 2))
        c = relu(conv2d(c, p[g + "conv.4.weight"], p[g + "conv.4.bias"], 2))
        x = np.concatenate([c.reshape(len(x), -1), x[:, G.SN_IMG:]], 1)
    for i in range(a["depth"]):
        x = relu(_lin(x, p, f"{g}body.{2 * i}"))
    z = x
    B, d, k = len(z), cfg["d"], cfg["g_tokens"]
    h = np.concatenate([_lin(z, p, g + "tok").reshape(B, k, d),
                        np.broadcast_to(p[g + "emb"][None], (B,) + p[g + "emb"].shape)], 1).astype(np.float32)
    h = blocks_np(p, g if cfg["trunk"] == "separate" else "", h, cfg)
    S = len(cfg["game_heads"][game])
    logits = [(_lin(h[:, k + s], p, f"{g}heads.{s}") + _lin(z, p, f"{g}direct.{s}")).astype(np.float32)
              for s in range(S)]
    v = _lin(gelu(_lin(np.concatenate([h[:, -1], h.mean(1)], -1), p, g + "vh1")), p, g + "vh2")[:, 0]
    return logits, v.astype(np.float32)


def joint_logits(slot_logits: list) -> np.ndarray:
    """[B, Π n_s] factorized joint logits, joint id mixed radix with the FIRST slot most significant."""
    J = slot_logits[0]
    for lg in slot_logits[1:]:
        J = (J[:, :, None] + lg[:, None, :]).reshape(len(J), -1)
    return J.astype(np.float32)


class MultiCore:
    def __init__(self, params: dict, zoo_norm: dict, config: dict):
        self.params = {k: np.asarray(v, np.float32) for k, v in params.items()}
        self.zoo_norm = {k: np.asarray(zoo_norm[k], np.float32) for k in SC.NORM_NAMES}
        self.config = config
        self._zoo = None
        zshapes = SC.param_shapes(config)
        missing = set(zshapes) - set(self.params)
        if missing:
            raise ValueError(f"zoo params missing: {sorted(missing)[:5]}")

    def weights_sha256(self) -> str:
        h = hashlib.sha256()
        for k in sorted(self.params):
            h.update(k.encode())
            h.update(np.ascontiguousarray(self.params[k], dtype=np.float32).tobytes())
        for k in SC.NORM_NAMES:
            h.update(k.encode())
            h.update(np.ascontiguousarray(self.zoo_norm[k], dtype=np.float32).tobytes())
        h.update(json.dumps(self.config, sort_keys=True).encode())
        return h.hexdigest()

    def save(self, path: str) -> str:
        sha = self.weights_sha256()
        arrays = {f"param/{k}": v for k, v in self.params.items()}
        arrays.update({f"norm/{k}": v for k, v in self.zoo_norm.items()})
        np.savez(path, config=np.array(json.dumps(self.config, sort_keys=True)), sha256=np.array(sha), **arrays)
        return sha

    @classmethod
    def load(cls, path: str) -> "MultiCore":
        with np.load(path, allow_pickle=False) as z:
            params = {k[len("param/"):]: z[k] for k in z.files if k.startswith("param/")}
            norm = {k[len("norm/"):]: z[k] for k in z.files if k.startswith("norm/")}
            core = cls(params, norm, json.loads(str(z["config"])))
            stored = str(z["sha256"])
        if core.weights_sha256() != stored:
            raise ValueError(f"sha256 mismatch for {path}")
        return core

    def zoo_core(self) -> SC.StructCore:
        if self._zoo is None:
            zc = {k: v for k, v in self.config.items()}
            zc["arch"] = SC.ARCH
            shapes = SC.param_shapes(zc)
            self._zoo = SC.StructCore({k: self.params[k] for k in shapes}, self.zoo_norm, zc)
        return self._zoo

    def predict(self, batch) -> dict:
        """Zoo Core.predict (struct_core contract)."""
        return self.zoo_core().predict(batch)

    def predict_game(self, game: str, X: np.ndarray, legal=None) -> dict:
        slot, vlog = game_forward(self.params, self.config, game, X)
        J = joint_logits(slot)
        if legal is not None:
            m = np.zeros_like(J, bool)
            for i, lg in enumerate(legal):
                m[i, np.asarray(list(lg), np.int64)] = True
            J = np.where(m, J, np.float32(SC.MASK_LOGIT))
        zz = J - J.max(1, keepdims=True)
        e = np.exp(zz)
        trained_v = bool(self.config.get("game_value", {}).get(game, False))
        return {"slot_logits": slot, "prior": J, "conf": (e.max(1) / e.sum(1)).astype(np.float32),
                "value": SC.sigmoid(vlog) if trained_v else np.full(len(J), np.nan, np.float32)}


class GamePolicy:
    """bv2n closed-loop adapter: features of the parsed view -> per-slot argmax -> joint dict."""

    def __init__(self, core: MultiCore, game: str):
        from nagi.burst2._rt.bv2n.student import features as F  # noqa: PLC0415
        self.core, self.game = core, game
        self.sp = F.SPEC["snake_lf" if game == "snake" else game]
        self.tag = f"v2g-multi:{game}"

    def act(self, view: dict) -> dict:
        x = np.asarray(self.sp["x"](view), np.float32).astype(np.float16).astype(np.float32)[None]  # = training rows
        slot, _ = game_forward(self.core.params, self.core.config, self.game, x)
        return self.sp["joint"](view, [int(lg[0].argmax()) for lg in slot])
