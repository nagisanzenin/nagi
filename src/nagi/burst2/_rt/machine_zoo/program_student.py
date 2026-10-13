"""ProgramStudent (PS): typed-token transformer that reads an mz-1 program + state (pure numpy reference forward).

Training happens in torch (scripts/machine_zoo/train_ps.py); this module is the reference inference path used by the
evaluator and implements EXACTLY the same forward (validity gate, PREREG §7: max |Δlogit| < 1e-4, argmax >= 99.9%).

Input: ``machine_zoo.tokens`` batch (VAR/RULE/ITEM/CTRL/GLOB tokens at fixed positions of a 54-slot layout, token
mask, relation counts rel[N_REL, 54, 54], per-joint probe table jp[27, F_JP], joint mask). Architecture (config keys):
  per-type standardisation (mean/std fitted on valid training tokens; std 0 -> 1), padded tokens zeroed
  typed linear embeddings var/rule/item/ctrl/glob: F_type -> d                                      [d = 128]
  [layers = 3] pre-LN blocks over the 54 slots (NO positional encoding; rule order enters only through the rule
      index features and the prev/next-rule relations):
      h += MHA(LN(h)), [heads = 4], scores = q.k/sqrt(d_h) + Σ_t rel_t[q, k] * attn_bias[l, t, head] + key mask
      h += fc2(gelu_tanh(fc1(LN(h))))   fc1: d -> [mlp_ratio = 2]*d
  final LN. Output head (joint logits over the 27 joints, same family as GraphStudent):
      unary per used slot s:   u_s = head2(gelu_tanh(head1([h_ctrl_s, h_glob]))) in R^3
      pairwise per used s < t: P_st[a, b] = f(s,t)[a,b] + f(t,s)[b,a], f(s,t)[a,b] = <pair_a(h_s)[a], pair_b(h_t)[b]>/sqrt(r)
      probe term per joint j:  z_j = jp2(gelu_tanh(jp1(jp_hat_j) + jpg(h_glob)))     [jp_hidden = 32]
          (jp_hat = standardised one-step/look-ahead probe features of joint j, zero on invalid joints; the
          weights read the program through h_glob, so how much a probe matters is program-dependent)
      logit(o0, o1, o2) = Σ_s u_s(o_s) + Σ_{s<t} P_st(o_s, o_t) + z_j; unused slots contribute 0.
  Prediction = argmax of the masked joint logits (np.argmax: ties -> lowest index).
Equivariance: VAR tokens carry no position-dependent feature and relations are built by name, so permuting the var
order of a program (state permuted alike) permutes VAR tokens only and leaves the logits unchanged (tested).

Size/speed (measured 2026-10-10): d=128/L=3/H=4 = 480,032 params. Training (scripts/machine_zoo/train_ps.py
--synthetic-bench, batch 256): M2 CPU 2 threads 3.0 steps/s at 42 slots (1.6 at the 54-slot worst case; the machine
was shared), T4 GPU 6.84 steps/s per process with 6 concurrent processes (lane E). Inference: see below.
Scale arms (PREREG_SCALE §3, same forward): M = d256/L8/H8 = 4,447,716 params, L = d512/L24/H8 = 51,191,396.
Inference with numpy on Accelerate (the venv; 1 thread, 16 states per call, ~15-19 tokens): S 0.26, M 0.90, L 5.0 ms per
decision (tokenize ~1.6 ms + forward 2.7 / 12.8 / 79 ms per call). numpy on OpenBLAS (Homebrew python3) runs the GEMMs
~6x slower (192 vs 1150 GFLOP/s measured), so run L evaluations with an Accelerate/MKL numpy or fan out.
Token slots: the layout has the DSL caps (54) so no program is truncated; the 26 family modules of 2026-10-10 use
13-29 tokens (mean 19); training trims slots that are padding in every machine of its rows file, inference runs on
the program's own tokens only.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np

from nagi.burst2._rt.machine_zoo import tokens as TK

MASK_LOGIT = -1e9
LN_EPS = 1e-5
DEFAULT_CONFIG = {"d": 128, "heads": 4, "layers": 3, "mlp_ratio": 2, "pair_rank": 32, "jp_hidden": 32}
NORM_NAMES = tuple(f"{a}_{t}" for t in ("var", "rule", "item", "ctrl", "glob", "jp") for a in ("mu", "sd"))


def layout(n_var: int, n_rule: int, n_item: int) -> dict:
    """Slot slices of a (possibly trimmed) layout [VAR n_var | RULE n_rule | ITEM n_item | CTRL 3 | GLOB 1]. The
    full layout is (10, 24, 16); training may trim slots that are padding in EVERY row of its data (same math)."""
    oc = n_var + n_rule + n_item
    return {"var": slice(0, n_var), "rule": slice(n_var, n_var + n_rule), "item": slice(n_var + n_rule, oc),
            "ctrl": slice(oc, oc + TK.MAX_CTRL), "glob": oc + TK.MAX_CTRL, "T": oc + TK.MAX_CTRL + 1}


SLICES = layout(TK.MAX_VARS, TK.MAX_RULES, TK.MAX_ITEMS)


def model_config(**kw) -> dict:
    cfg = {**DEFAULT_CONFIG, **kw, "arch": "program_student_v1", "rows_format": TK.ROWS_FORMAT, "t_max": TK.T_MAX,
           "n_rel": TK.N_REL, **{f"f_{t}": TK.TYPE_WIDTH[t] for t in TK.TYPE_WIDTH}}
    if cfg["d"] % cfg["heads"]:
        raise ValueError("d must be divisible by heads")
    return cfg


def param_shapes(cfg: dict) -> dict:
    """name -> shape in torch layout (Linear weight = [out, in]); the torch module's state_dict matches exactly."""
    d, r, L, jh = cfg["d"], cfg["pair_rank"], cfg["layers"], cfg["jp_hidden"]
    hm = cfg["mlp_ratio"] * d
    s = {}
    for t in ("var", "rule", "item", "ctrl", "glob"):
        s[f"emb_{t}.weight"], s[f"emb_{t}.bias"] = (d, cfg[f"f_{t}"]), (d,)
    s["attn_bias"] = (L, cfg["n_rel"], cfg["heads"])
    for i in range(L):
        b = f"blocks.{i}."
        s.update({b + "ln1.weight": (d,), b + "ln1.bias": (d,), b + "qkv.weight": (3 * d, d), b + "qkv.bias": (3 * d,),
                  b + "proj.weight": (d, d), b + "proj.bias": (d,), b + "ln2.weight": (d,), b + "ln2.bias": (d,),
                  b + "fc1.weight": (hm, d), b + "fc1.bias": (hm,), b + "fc2.weight": (d, hm), b + "fc2.bias": (d,)})
    s.update({"ln_f.weight": (d,), "ln_f.bias": (d,), "head1.weight": (d, 2 * d), "head1.bias": (d,),
              "head2.weight": (3, d), "head2.bias": (3,), "pair_a.weight": (3 * r, d), "pair_a.bias": (3 * r,),
              "pair_b.weight": (3 * r, d), "pair_b.bias": (3 * r,), "jp1.weight": (jh, cfg["f_jp"]),
              "jp1.bias": (jh,), "jpg.weight": (jh, d), "jpg.bias": (jh,), "jp2.weight": (1, jh), "jp2.bias": (1,)})
    return s


def identity_norm(cfg: dict) -> dict:
    out = {}
    for t in ("var", "rule", "item", "ctrl", "glob", "jp"):
        out[f"mu_{t}"] = np.zeros(cfg[f"f_{t}"], np.float32)
        out[f"sd_{t}"] = np.ones(cfg[f"f_{t}"], np.float32)
    return out


def init_random(cfg: dict, seed: int) -> tuple[dict, dict]:
    """Random (untrained) params + identity normalisation, for tests (not the torch init)."""
    rng = np.random.default_rng(seed)
    p = {}
    for k, shp in param_shapes(cfg).items():
        if k.endswith("ln1.weight") or k.endswith("ln2.weight") or k == "ln_f.weight":
            p[k] = np.ones(shp, np.float32)
        elif len(shp) == 2:
            p[k] = (rng.standard_normal(shp) / np.sqrt(shp[1])).astype(np.float32)
        else:
            p[k] = (rng.standard_normal(shp) * 0.1).astype(np.float32)
    return p, identity_norm(cfg)


# ------------------------------------------------------------------ forward (numpy, float32) ----------------------
def _lin(x, p, name):
    """x[..., in] @ W.T + b as ONE 2-D GEMM (a 3-D @ 2-D matmul runs one small GEMM per leading index: ~5x slower)."""
    w = p[name + ".weight"]
    y = x.reshape(-1, x.shape[-1]) @ w.T + p[name + ".bias"]
    return y.reshape(x.shape[:-1] + (w.shape[0],))


def _ln(x, p, name):
    mu = x.mean(-1, keepdims=True)
    var = ((x - mu) ** 2).mean(-1, keepdims=True)
    return (x - mu) / np.sqrt(var + np.float32(LN_EPS)) * p[name + ".weight"] + p[name + ".bias"]


def gelu_tanh(x):
    c = np.float32(np.sqrt(2.0 / np.pi))
    return np.float32(0.5) * x * (np.float32(1.0) + np.tanh(c * (x + np.float32(0.044715) * x * x * x)))


def forward(p: dict, norm: dict, cfg: dict, batch: dict, compact: bool = True) -> np.ndarray:
    """Raw joint logits float32[B, 27] (unmasked). ``compact``: when every row shares one token mask (states of one
    program), run the blocks on the valid token slots only (identical math: padded slots are masked keys)."""
    f32 = np.float32
    tm = np.asarray(batch["tokmask"], bool)
    B, T = tm.shape
    lay = layout(batch["x_var"].shape[1], batch["x_rule"].shape[1], batch["x_item"].shape[1])
    if lay["T"] != T or batch["x_ctrl"].shape[1] != TK.MAX_CTRL:
        raise ValueError("token mask / type slot counts disagree")
    xs = {}
    for t in ("var", "rule", "item", "ctrl"):
        x = (np.asarray(batch["x_" + t], f32) - norm["mu_" + t]) / norm["sd_" + t]
        xs[t] = (x * tm[:, lay[t], None]).astype(f32)
    xg = ((np.asarray(batch["x_glob"], f32) - norm["mu_glob"]) / norm["sd_glob"]).astype(f32)
    h = np.concatenate([_lin(xs["var"], p, "emb_var"), _lin(xs["rule"], p, "emb_rule"), _lin(xs["item"], p, "emb_item"),
                        _lin(xs["ctrl"], p, "emb_ctrl"), _lin(xg, p, "emb_glob")[:, None]], 1).astype(f32)
    rel = np.asarray(batch["rel"])
    keep = None
    if compact and (tm == tm[:1]).all():
        keep = np.flatnonzero(tm[0])
        h = h[:, keep]
        rel = rel[:, :, keep][:, :, :, keep]
        tmk = tm[:, keep]
    else:
        tmk = tm
    Tk = h.shape[1]
    d, H = cfg["d"], cfg["heads"]
    dh = d // H
    key_bias = np.where(tmk, f32(0), f32(MASK_LOGIT))[:, None, None, :]
    R = rel.astype(f32).reshape(B, cfg["n_rel"], Tk * Tk).transpose(0, 2, 1)  # [B, q*k, rel]
    scale = f32(1.0 / np.sqrt(dh))
    for i in range(cfg["layers"]):
        b = f"blocks.{i}."
        bias = (R @ p["attn_bias"][i]).reshape(B, Tk, Tk, H).transpose(0, 3, 1, 2)
        y = _ln(h, p, b + "ln1")
        qkv = _lin(y, p, b + "qkv").reshape(B, Tk, 3, H, dh).transpose(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        s = (q @ k.transpose(0, 1, 3, 2)) * scale + bias + key_bias
        s = s - s.max(-1, keepdims=True)
        w = np.exp(s)
        w = w / w.sum(-1, keepdims=True)
        o = (w @ v).transpose(0, 2, 1, 3).reshape(B, Tk, d)
        h = h + _lin(o, p, b + "proj")
        y = _ln(h, p, b + "ln2")
        h = h + _lin(gelu_tanh(_lin(y, p, b + "fc1")), p, b + "fc2")
    h = _ln(h, p, "ln_f")
    if keep is not None:
        full = np.zeros((B, T, d), f32)
        full[:, keep] = h
        h = full
    hc, hg = h[:, lay["ctrl"]], h[:, lay["glob"]]
    cm = tm[:, lay["ctrl"]]
    nc = TK.MAX_CTRL
    u = _lin(gelu_tanh(_lin(np.concatenate([hc, np.broadcast_to(hg[:, None], hc.shape)], -1), p, "head1")), p,
             "head2")
    u = u * cm[..., None].astype(f32)
    r = cfg["pair_rank"]
    A = _lin(hc, p, "pair_a").reshape(B, nc, 3, r)
    Bm = _lin(hc, p, "pair_b").reshape(B, nc, 3, r)
    f = np.einsum("bsar,btcr->bstac", A, Bm) * f32(1.0 / np.sqrt(r))
    P = f + f.transpose(0, 2, 1, 4, 3)
    P = P * (cm[:, :, None] & cm[:, None, :]).astype(f32)[..., None, None]
    J = (u[:, 0][:, :, None, None] + u[:, 1][:, None, :, None] + u[:, 2][:, None, None, :]
         + P[:, 0, 1][:, :, :, None] + P[:, 0, 2][:, :, None, :] + P[:, 1, 2][:, None, :, :]).reshape(B, 27)
    jm = np.asarray(batch["jmask"], bool)
    jph = ((np.asarray(batch["jp"], f32) - norm["mu_jp"]) / norm["sd_jp"]) * jm[..., None].astype(f32)
    z = _lin(gelu_tanh(_lin(jph.astype(f32), p, "jp1") + _lin(hg, p, "jpg")[:, None, :]), p, "jp2")[..., 0]
    return (J + z).astype(f32)


# ------------------------------------------------------------------ persistence ----------------------------------
def weights_sha256(params: dict, norm: dict) -> str:
    """sha256 over (name, raw float32 bytes) of every param in sorted name order, then every norm in NORM_NAMES order."""
    h = hashlib.sha256()
    for k in sorted(params):
        h.update(k.encode())
        h.update(np.ascontiguousarray(params[k], dtype=np.float32).tobytes())
    for k in NORM_NAMES:
        h.update(k.encode())
        h.update(np.ascontiguousarray(norm[k], dtype=np.float32).tobytes())
    return h.hexdigest()


class ProgramStudent:
    """Trained ProgramStudent policy (weights + normalisation + config)."""

    def __init__(self, params: dict, norm: dict, config: dict):
        shapes = param_shapes(config)
        if set(shapes) != set(params) or any(tuple(params[k].shape) != shapes[k] for k in shapes):
            raise ValueError("param names/shapes do not match the config")
        for t in ("var", "rule", "item", "ctrl", "glob", "jp"):
            if config[f"f_{t}"] != TK.TYPE_WIDTH[t]:
                raise ValueError(f"feature width of {t} differs from machine_zoo.tokens (tokenizer changed?)")
        self.params = {k: np.asarray(v, np.float32) for k, v in params.items()}
        self.norm = {k: np.asarray(norm[k], np.float32) for k in NORM_NAMES}
        self.config = config
        self._static: dict = {}

    def weights_sha256(self) -> str:
        return weights_sha256(self.params, self.norm)

    def save(self, path: str) -> str:
        if not path.endswith(".npz"):
            raise ValueError("ProgramStudent files must end in .npz")
        sha = self.weights_sha256()
        arrays = {f"param/{k}": v for k, v in self.params.items()}
        arrays.update({f"norm/{k}": v for k, v in self.norm.items()})
        np.savez(path, config=np.array(json.dumps(self.config, sort_keys=True)), sha256=np.array(sha), **arrays)
        return sha

    @classmethod
    def load(cls, path: str) -> ProgramStudent:
        with np.load(path, allow_pickle=False) as z:
            params = {k[len("param/"):]: z[k] for k in z.files if k.startswith("param/")}
            norm = {k[len("norm/"):]: z[k] for k in z.files if k.startswith("norm/")}
            st = cls(params, norm, json.loads(str(z["config"])))
            stored = str(z["sha256"])
        if st.weights_sha256() != stored:
            raise ValueError(f"sha256 mismatch for {path}")
        return st

    # -------------------------------------------------------------- inference
    def logits_batch(self, batch: dict, compact: bool = True) -> np.ndarray:
        return forward(self.params, self.norm, self.config, batch, compact=compact)

    def predict_batch(self, batch: dict) -> np.ndarray:
        lg = np.where(np.asarray(batch["jmask"], bool), self.logits_batch(batch), np.float32(MASK_LOGIT))
        return np.argmax(lg, axis=1)

    def _cached(self, program: dict):
        key = json.dumps(program, sort_keys=True)
        hit = self._static.get(key)
        if hit is None:
            if len(self._static) > 4096:
                self._static.clear()
            cp = TK.Compiled(program)
            hit = self._static[key] = (cp, TK.machine_static(program, cp))
        return hit

    def tokenize(self, program: dict, states) -> dict:
        cp, st = self._cached(program)
        return TK.assemble(st, TK.state_dynamic(program, states, cp))

    def predict_raw(self, program: dict, states) -> list[int]:
        """Joint index per state (argmax of masked joint logits, ties -> lowest index). ``program`` is an mz-1
        program dict (or an object with a ``program`` attribute, e.g. lane A's Machine)."""
        if not isinstance(program, dict):
            program = program.program
        states = list(states)
        if not states:
            return []
        return [int(j) for j in self.predict_batch(self.tokenize(program, states))]
