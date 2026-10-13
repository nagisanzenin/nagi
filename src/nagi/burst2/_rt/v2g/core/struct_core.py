"""Arm S of the V2 core A/B: StructCore = typed-token transformer over the machine's rules + state (pure numpy serve path).

Lineage: GraphStudent (mc-0.1: typed entity tokens, 3 pre-LN layers d128, no positional encoding, relation-typed
attention biases, per-slot unary + pairwise joint head; 0.672 on unseen structures, REPORT_v3) -> ProgramStudent
(mz-1 programs: VAR/RULE/ITEM/CTRL/GLOB tokens, 21 relation types, per-joint exact probe table; machine_zoo) -> this
module, which keeps the ProgramStudent trunk and prior head unchanged (a PS checkpoint is a special case) and adds the
two heads the V2 search needs:

  trunk  h = PS blocks over the program's tokens (``machine_zoo.tokens``; features are exact functions of program +
         state, rounded through float16; no names, no ids, no positions).
  prior  z_j = Σ_s u_s(o_s) + Σ_{s<t} P_st(o_s, o_t) + jp-term_j       (PS head, factorized per control slot)
         trained on t = softmax(-(V* - Q*_j)/T), T = 0.25 reward units (R2.11; v2g-rec-v0 definitions).
  value  [v_logit, r_logit] = vh2(gelu(vh1([h_glob, mean_valid(h)])))
         value = sigmoid(v_logit) ≈ v_succ = P(success | follow π*) in [0, 1]  (BCE with the exact probability: a
         proper scoring rule, so the head is trained toward calibration);
         v_reward = 249 * sigmoid(r_logit) - 200 ≈ V* in reward units (search units; V* ∈ [-200, 49]).
  p_opt  o_j = oo2(gelu(Σ_s used E_s[o_s] + og(h_glob) + ojp(jp_hat_j)))   with E_s = oe(h_ctrl_s) ∈ R^{3 x oh}
         p_opt_j = sigmoid(o_j) ≈ P(j ∈ A*(s)) (per-joint BCE on the exact optimal set). Unlike the prior's
         softmax, p_opt is not split across tied optimal joints, so it is the calibrated statistic for the search
         confidence gate ("is this tie-break joint optimal?").

Interface (LANES.md Core; hook agreed with lane runtime 2026-10-12):
    core.predict({"machine": M, "items": [{"state": s, "history": h, "legal": [j, ...]}, ...]})
    core.predict([{"machine": M, "state": s, "legal": [...]}, ...])           (list form; grouped per machine)
  -> {"prior": float32[B, 27] logits (illegal = -1e9), "value": float32[B], "v_reward": float32[B],
      "p_opt": float32[B, 27] (0 illegal), "conf": float32[B] = max softmax(prior) over legal joints,
      "supported": bool[B]}
  M = a v2g Machine (.program = mz-1 base dict, .px = mz-1x dict or None, .kind), a machine_zoo Machine
  (.program) or an mz-1 program dict. Arm S v0 reads plain mz-1 programs (and mz-1x programs with delay 0 and nothing
  hidden, which ARE mz-1 programs). Other mz-1x programs return supported=False, conf=0, p_opt=0, value=nan: the
  search gate fails closed and search runs without the core (no silent guess).
"""

from __future__ import annotations

import hashlib
import json

import numpy as np

from nagi.burst2._rt.machine_zoo import program_student as PS
from nagi.burst2._rt.machine_zoo import tokens as TK

MASK_LOGIT = -1e9
N_JOINT = 27
V_LO, V_HI = -200.0, 49.0  # reward-unit range of V* (crash now .. success now)
ARCH = "v2g_struct_core_v0"
DEFAULT_CONFIG = {**PS.DEFAULT_CONFIG, "v_hidden": 128, "o_hidden": 32}
NORM_NAMES = PS.NORM_NAMES
# joint j = o0*9 + o1*3 + o2 -> option of slot s
JOINT_OPTS = np.array([[j // 9, (j // 3) % 3, j % 3] for j in range(N_JOINT)], np.int64)


def model_config(x_ext: bool = False, **kw) -> dict:
    """x_ext=True: arm S v1 (mz-1x views through v2g.core.xtokens); the key is absent for v0 configs (unchanged)."""
    cfg = PS.model_config(**{**DEFAULT_CONFIG, **kw})
    cfg["arch"] = ARCH
    if x_ext:
        from nagi.burst2._rt.v2g.core import xtokens as XT  # noqa: PLC0415
        cfg.update({"x_ext": True, "f_var_x": XT.F_VX, "f_ctrl_x": XT.F_CX, "f_glob_x": XT.F_GX})
    return cfg


def param_shapes(cfg: dict) -> dict:
    """PS shapes + value head + p_opt head (torch layout, Linear weight = [out, in])."""
    d, vh, oh = cfg["d"], cfg["v_hidden"], cfg["o_hidden"]
    s = dict(PS.param_shapes(cfg))
    s.update({"vh1.weight": (vh, 2 * d), "vh1.bias": (vh,), "vh2.weight": (2, vh), "vh2.bias": (2,),
              "oe.weight": (3 * oh, d), "oe.bias": (3 * oh,), "og.weight": (oh, d), "og.bias": (oh,),
              "ojp.weight": (oh, cfg["f_jp"]), "ojp.bias": (oh,), "oo2.weight": (1, oh), "oo2.bias": (1,)})
    if cfg.get("x_ext"):   # arm S v1 extension embeddings (no bias: zero extension features add exactly 0)
        s.update({"emb_var_x.weight": (d, cfg["f_var_x"]), "emb_ctrl_x.weight": (d, cfg["f_ctrl_x"]),
                  "emb_glob_x.weight": (d, cfg["f_glob_x"])})
    return s


def n_params(cfg: dict) -> int:
    return int(sum(np.prod(s) for s in param_shapes(cfg).values()))


def init_random(cfg: dict, seed: int) -> tuple[dict, dict]:
    """Random (untrained) params + identity normalisation (tests and latency only; not the torch init)."""
    rng = np.random.default_rng(seed)
    p = {}
    for k, shp in param_shapes(cfg).items():
        if k.endswith("ln1.weight") or k.endswith("ln2.weight") or k == "ln_f.weight":
            p[k] = np.ones(shp, np.float32)
        elif len(shp) == 2:
            p[k] = (rng.standard_normal(shp) / np.sqrt(shp[1])).astype(np.float32)
        else:
            p[k] = (rng.standard_normal(shp) * 0.1).astype(np.float32)
    return p, PS.identity_norm(cfg)


_lin, _ln, gelu_tanh = PS._lin, PS._ln, PS.gelu_tanh


def sigmoid(x):
    x = np.asarray(x, np.float32)
    return (np.float32(0.5) * (np.float32(1.0) + np.tanh(np.float32(0.5) * x))).astype(np.float32)


def forward_all(p: dict, norm: dict, cfg: dict, batch: dict, compact: bool = True) -> dict:
    """{"prior": raw joint logits [B,27] (unmasked), "v_logit": [B], "r_logit": [B], "o_logit": [B,27] (unmasked)}.

    Trunk and prior head are line for line ``machine_zoo.program_student.forward`` (tested equal)."""
    f32 = np.float32
    tm = np.asarray(batch["tokmask"], bool)
    B, T = tm.shape
    lay = PS.layout(batch["x_var"].shape[1], batch["x_rule"].shape[1], batch["x_item"].shape[1])
    if lay["T"] != T or batch["x_ctrl"].shape[1] != TK.MAX_CTRL:
        raise ValueError("token mask / type slot counts disagree")
    xs = {}
    for t in ("var", "rule", "item", "ctrl"):
        x = (np.asarray(batch["x_" + t], f32) - norm["mu_" + t]) / norm["sd_" + t]
        xs[t] = (x * tm[:, lay[t], None]).astype(f32)
    xg = ((np.asarray(batch["x_glob"], f32) - norm["mu_glob"]) / norm["sd_glob"]).astype(f32)
    h = np.concatenate([_lin(xs["var"], p, "emb_var"), _lin(xs["rule"], p, "emb_rule"), _lin(xs["item"], p, "emb_item"),
                        _lin(xs["ctrl"], p, "emb_ctrl"), _lin(xg, p, "emb_glob")[:, None]], 1).astype(f32)
    if cfg.get("x_ext") and "x_var_x" in batch:
        nv_ = batch["x_var"].shape[1]
        ext = np.zeros_like(h)
        ext[:, lay["var"]] = np.asarray(batch["x_var_x"], f32)[:, :nv_] @ p["emb_var_x.weight"].T
        ext[:, lay["ctrl"]] = np.asarray(batch["x_ctrl_x"], f32) @ p["emb_ctrl_x.weight"].T
        ext[:, lay["glob"]] = np.asarray(batch["x_glob_x"], f32) @ p["emb_glob_x.weight"].T
        h = (h + ext * tm[..., None].astype(f32)).astype(f32)
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
    R = rel.astype(f32).reshape(B, cfg["n_rel"], Tk * Tk).transpose(0, 2, 1)
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
    tmf = tmk.astype(f32)
    pooled = (h * tmf[..., None]).sum(1) / np.maximum(tmf.sum(1, keepdims=True), f32(1))
    if keep is not None:
        full = np.zeros((B, T, d), f32)
        full[:, keep] = h
        h = full
    hc, hg = h[:, lay["ctrl"]], h[:, lay["glob"]]
    cm = tm[:, lay["ctrl"]]
    nc = TK.MAX_CTRL
    # prior head (PS)
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
    jph = (((np.asarray(batch["jp"], f32) - norm["mu_jp"]) / norm["sd_jp"]) * jm[..., None].astype(f32)).astype(f32)
    z = _lin(gelu_tanh(_lin(jph, p, "jp1") + _lin(hg, p, "jpg")[:, None, :]), p, "jp2")[..., 0]
    prior = (J + z).astype(f32)
    # value head
    vr = _lin(gelu_tanh(_lin(np.concatenate([hg, pooled], -1), p, "vh1")), p, "vh2")
    # p_opt head
    oh = cfg["o_hidden"]
    E = _lin(hc, p, "oe").reshape(B, nc, 3, oh) * cm[..., None, None].astype(f32)
    ej = (E[:, 0][:, JOINT_OPTS[:, 0]] + E[:, 1][:, JOINT_OPTS[:, 1]] + E[:, 2][:, JOINT_OPTS[:, 2]])  # [B,27,oh]
    ej = ej + _lin(hg, p, "og")[:, None, :] + _lin(jph, p, "ojp")
    ol = _lin(gelu_tanh(ej), p, "oo2")[..., 0]
    return {"prior": prior, "v_logit": vr[:, 0].astype(f32), "r_logit": vr[:, 1].astype(f32),
            "o_logit": ol.astype(f32)}


def weights_sha256(params: dict, norm: dict) -> str:
    h = hashlib.sha256()
    for k in sorted(params):
        h.update(k.encode())
        h.update(np.ascontiguousarray(params[k], dtype=np.float32).tobytes())
    for k in NORM_NAMES:
        h.update(k.encode())
        h.update(np.ascontiguousarray(norm[k], dtype=np.float32).tobytes())
    return h.hexdigest()


def _program_of(machine):
    """(mz-1 program dict or None if unsupported, reason)."""
    if isinstance(machine, dict):
        if machine.get("dsl") == "mz-1x":
            px = machine
        else:
            return machine, None
    else:
        px = getattr(machine, "px", None)
        if px is None:
            return machine.program, None
    if int(px.get("delay", 0)) == 0 and not px.get("hidden"):
        return px["base"], None
    return None, "mz-1x with delay or hidden vars: arm S v0 reads plain mz-1 only"


def _px_of(machine):
    """The mz-1x program dict of a machine with delay or hidden vars (None otherwise)."""
    px = machine if isinstance(machine, dict) and machine.get("dsl") == "mz-1x" else getattr(machine, "px", None)
    if px is None or (int(px.get("delay", 0)) == 0 and not px.get("hidden")):
        return None
    return px


def _x_view(state, px):
    """(obs, dec) of an mz-1x view: a v2g.machine view dict {"kind": "mz-1x", "obs", "dec"}, an XView-like object, or
    (nothing hidden only) a full XState (base, queue) = the window-1 view. None = cannot read without hidden values."""
    if isinstance(state, dict):
        return (state["obs"], state["dec"]) if state.get("kind") == "mz-1x" else None
    if hasattr(state, "obs") and hasattr(state, "dec"):
        return state.obs, state.dec
    if px.get("hidden"):
        return None
    base, queue = state
    names = [v["name"] for v in px["base"]["vars"]]
    k = max(int(px.get("window", 1)) - 1, int(px["delay"]))
    dec = [None] * (k - len(queue)) + [int(j) for j in queue]
    return [tuple(int(base[i]) for i in range(len(names)))], dec


def _plain_state(state):
    """Full mz-1 state tuple from a tuple / list / v2g.machine mz-1 view dict {"kind": "mz-1", "state", ...};
    None for an mz-1x view (arm S v0 cannot read it)."""
    if isinstance(state, dict):
        if state.get("kind") == "mz-1":
            return tuple(int(v) for v in state["state"])
        return None
    return tuple(int(v) for v in state)


class StructCore:
    """Trained StructCore (weights + normalisation + config). Pure numpy; set OMP/VECLIB threads to 1 for serving."""

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

    # ------------------------------------------------------------------ persistence
    def weights_sha256(self) -> str:
        return weights_sha256(self.params, self.norm)

    def save(self, path: str) -> str:
        if not path.endswith(".npz"):
            raise ValueError("StructCore files must end in .npz")
        sha = self.weights_sha256()
        arrays = {f"param/{k}": v for k, v in self.params.items()}
        arrays.update({f"norm/{k}": v for k, v in self.norm.items()})
        np.savez(path, config=np.array(json.dumps(self.config, sort_keys=True)), sha256=np.array(sha), **arrays)
        return sha

    @classmethod
    def load(cls, path: str) -> "StructCore":
        with np.load(path, allow_pickle=False) as z:
            params = {k[len("param/"):]: z[k] for k in z.files if k.startswith("param/")}
            norm = {k[len("norm/"):]: z[k] for k in z.files if k.startswith("norm/")}
            st = cls(params, norm, json.loads(str(z["config"])))
            stored = str(z["sha256"])
        if st.weights_sha256() != stored:
            raise ValueError(f"sha256 mismatch for {path}")
        return st

    # ------------------------------------------------------------------ inference
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

    def outputs(self, batch: dict) -> dict:
        return forward_all(self.params, self.norm, self.config, batch)

    def predict_program(self, program: dict, states, legal=None, x: dict | None = None) -> dict:
        """Heads for states of ONE mz-1 program. legal: None (all valid joints) or a list per state.
        x: arm S v1 extension arrays (xtokens) for these rows; None = plain mz-1 (zeros)."""
        states = [tuple(int(v) for v in s) for s in states]
        B = len(states)
        nb = self.tokenize(program, states)
        if self.config.get("x_ext"):
            from nagi.burst2._rt.v2g.core import xtokens as XT  # noqa: PLC0415
            xz = x if x is not None else XT.zeros(B)
            nb.update({"x_var_x": xz["var_x"], "x_ctrl_x": xz["ctrl_x"], "x_glob_x": xz["glob_x"]})
        out = self.outputs(nb)
        jm = np.asarray(nb["jmask"], bool).copy()
        if legal is not None:
            lm = np.zeros((B, N_JOINT), bool)
            for i, lg in enumerate(legal):
                if lg is not None:
                    lm[i, np.asarray(list(lg), np.int64)] = True
                else:
                    lm[i] = jm[i]
            if (lm & ~jm).any():
                raise ValueError("legal joint outside the program's valid joints")
            jm = lm
        prior = np.where(jm, out["prior"], np.float32(MASK_LOGIT)).astype(np.float32)
        zz = prior - prior.max(1, keepdims=True)
        e = np.where(jm, np.exp(zz), 0.0)
        conf = (e.max(1) / e.sum(1)).astype(np.float32)
        return {"prior": prior, "value": sigmoid(out["v_logit"]),
                "v_reward": (np.float32(V_HI - V_LO) * sigmoid(out["r_logit"]) + np.float32(V_LO)).astype(np.float32),
                "p_opt": np.where(jm, sigmoid(out["o_logit"]), np.float32(0)).astype(np.float32),
                "conf": conf, "supported": np.ones(B, bool)}

    def _xprog(self, px: dict):
        from nagi.burst2._rt.v2g.core import xtokens as XT  # noqa: PLC0415
        key = "x|" + json.dumps(px, sort_keys=True)
        hit = self._static.get(key)
        if hit is None:
            if len(self._static) > 4096:
                self._static.clear()
            hit = self._static[key] = XT.XProgram(px)
        return hit

    @staticmethod
    def _closed(items, why) -> dict:
        B = len(items)
        lm = np.zeros((B, N_JOINT), bool)
        for i, it in enumerate(items):
            lm[i, np.asarray(list(it.get("legal") or []), np.int64)] = True
        return {"prior": np.where(lm, np.float32(0), np.float32(MASK_LOGIT)).astype(np.float32),
                "value": np.full(B, np.nan, np.float32), "v_reward": np.full(B, np.nan, np.float32),
                "p_opt": np.zeros((B, N_JOINT), np.float32), "conf": np.zeros(B, np.float32),
                "supported": np.zeros(B, bool), "reason": why}

    def _predict_x(self, px: dict, items) -> dict:
        """Arm S v1 rows of an mz-1x machine with delay / hidden vars (rows whose view needs hidden values fail closed)."""
        from nagi.burst2._rt.v2g.core import xtokens as XT  # noqa: PLC0415
        xp = self._xprog(px)
        views = [_x_view(it["state"], px) for it in items]
        ok = [i for i, v in enumerate(views) if v is not None]
        out = self._closed(items, "full state of a machine with hidden vars: the core reads views only")
        if ok:
            states, xa = XT.view_arrays(xp, [views[i] for i in ok])
            got = self.predict_program(px["base"], states, [items[i].get("legal") for i in ok], xa)
            for k in ("prior", "value", "v_reward", "p_opt", "conf", "supported"):
                out[k][ok] = got[k]
        return out

    def predict(self, batch) -> dict:
        """Core.predict (see module doc). Rows of an unsupported machine fail closed (supported=False, conf 0)."""
        if isinstance(batch, dict):
            groups = [(batch["machine"], list(batch["items"]))]
            order = None
        else:
            groups, order, by = [], [], {}
            for i, it in enumerate(batch):
                key = id(it["machine"])
                if key not in by:
                    by[key] = len(groups)
                    groups.append((it["machine"], []))
                groups[by[key]][1].append(it)
                order.append((by[key], len(groups[by[key]][1]) - 1))
        parts = []
        for machine, items in groups:
            program, why = _program_of(machine)
            if program is None:
                px = _px_of(machine)
                if self.config.get("x_ext") and px is not None:
                    parts.append(self._predict_x(px, items))
                else:
                    parts.append(self._closed(items, why))
                continue
            states = [_plain_state(it["state"]) for it in items]
            if any(s is None for s in states):
                raise ValueError("mz-1x view passed for a plain mz-1 machine")
            parts.append(self.predict_program(program, states, [it.get("legal") for it in items]))
        keys = ("prior", "value", "v_reward", "p_opt", "conf", "supported")
        if order is None:
            return {k: parts[0][k] for k in keys}
        return {k: np.stack([parts[g][k][i] for g, i in order]) if order else np.zeros(0) for k in keys}
