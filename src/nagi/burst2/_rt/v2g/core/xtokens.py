"""Arm S v1: mz-1x view tokenizer = a wrapper around ``machine_zoo.tokens`` (no fork) + an extension feature block.

Input = exactly the client view of an mz-1x program px = {"base", "delay" d, "hidden", "window" H}
(bv2n.zoo_new.xdsl / v2g.machine): obs = H displayed observations (None-padded, oldest first, last = now; each lists
the DISPLAYED vars in program order) and dec = K = max(H - 1, d) past decided joints (None-padded, oldest first; the
last d are in flight, applied one per tick, oldest first). Hidden values are never read.

Decision state (what the base tokenizer sees), an exact deterministic function of (px, view):
  s_now   displayed vars = obs[-1]; each hidden var = the median of its start values (interp.start_states, a constant
          of the program) and flagged hidden.
  s_proj  s_now advanced through the d in-flight joints with the modal random value (interp.tick, ties -> first
          listed = tokens.Compiled.w_modal); stops early at a crash / success (flagged). The joint decided now lands
          on s_proj, so the base tokens + joint probes are computed there (the lag-projection that gave Snake +5 s).
Extension features (zeros for plain mz-1, so plain rows are unchanged; all in [0, 1] or {0, 1}, no normalisation):
  VAR  [F_VX = 14]  hidden flag; displayed flag; value_norm now (0 if hidden); for lag k = 1..5: value_norm of obs[-1-k]
                    and its availability (0 if hidden / None / beyond H); (proj - now) / width (0 if hidden).
  CTRL [F_CX = 11]  for in-flight position k = 1, 2 (k = 1 lands next tick): option one-hot (3) + present flag; for
                    the past decided joints that are no longer in flight: the share of each option (3).
  GLOB [F_GX = 10]  is_mz1x; delay one-hot (0, 1, 2); H / 6; n_hidden / n_vars; any hidden; projection ended in crash;
                    projection ended in success; share of available observations.
value_norm(v) = (v - lo) / (hi - lo) (0 when hi == lo); every extension feature is rounded through float16 (as the base
tokenizer's features), so served features equal the stored training features bit for bit. Static program features (VAR/RULE/ITEM/CTRL/GLOB static) are the
base program's, unchanged.
"""

from __future__ import annotations

import numpy as np

from nagi.burst2._rt.machine_zoo import interp
from nagi.burst2._rt.machine_zoo import tokens as TK

F_VX, F_CX, F_GX = 14, 11, 10
MAX_LAG = 5
KEEP = TK.KEEP_JOINT


def zeros(n: int) -> dict:
    return {"var_x": np.zeros((n, TK.MAX_VARS, F_VX), np.float32), "ctrl_x": np.zeros((n, TK.MAX_CTRL, F_CX), np.float32),
            "glob_x": np.zeros((n, F_GX), np.float32)}


def _modal_w(prog) -> int:
    return int(prog.w_vals[int(np.argmax(prog.w_probs))])


class XProgram:
    """Per-program constants (cache one per machine)."""

    def __init__(self, px: dict):
        self.px = px
        self.base = px["base"]
        self.prog = interp.compile_program(self.base)
        names = [v["name"] for v in self.base["vars"]]
        self.nv = len(names)
        hid = set(px.get("hidden") or [])
        self.hidden = np.array([n in hid for n in names], bool)
        self.disp_cols = [i for i, n in enumerate(names) if n not in hid]
        self.d = int(px.get("delay", 0))
        self.H = int(px.get("window", 1))
        self.lo = np.asarray(self.prog.lo, np.int64)
        self.hi = np.asarray(self.prog.hi, np.int64)
        starts = np.asarray(interp.start_states(self.base), np.int64)
        self.placeholder = np.floor(np.median(starts, axis=0)).astype(np.int64)
        self.w_modal = _modal_w(self.prog)
        n_ctrl = len(self.base["controls"])
        self.n_ctrl = n_ctrl

    def norm(self, v, cols):
        w = (self.hi - self.lo)[cols].astype(np.float64)
        return np.where(w > 0, (np.asarray(v, np.float64) - self.lo[cols]) / np.where(w > 0, w, 1), 0.0)

    def view_state(self, obs, dec) -> tuple[tuple, np.ndarray, np.ndarray, np.ndarray]:
        """(s_proj, var_x [MAX_VARS, F_VX], ctrl_x [MAX_CTRL, F_CX], glob_x [F_GX])."""
        obs = list(obs)
        dec = list(dec)
        if len(obs) != self.H or obs[-1] is None:
            raise ValueError("view obs window length != H or current observation missing")
        cur = np.asarray(obs[-1], np.int64)
        if len(cur) != len(self.disp_cols):
            raise ValueError("observation width != number of displayed vars")
        s_now = self.placeholder.copy()
        s_now[self.disp_cols] = cur
        s_now = np.clip(s_now, self.lo, self.hi)
        inflight = [int(j) if j is not None else KEEP for j in dec[len(dec) - self.d:]] if self.d else []
        s = tuple(int(x) for x in s_now)
        ended = None
        for j in inflight:
            s, oc = interp.tick(self.prog, s, j, self.w_modal)
            if oc != "running":
                ended = oc
                break
        s_proj = tuple(int(min(max(x, lo), hi)) for x, lo, hi in zip(s, self.lo, self.hi))
        vx = np.zeros((TK.MAX_VARS, F_VX), np.float32)
        nv = self.nv
        vx[:nv, 0] = self.hidden
        vx[:nv, 1] = ~self.hidden
        dc = np.asarray(self.disp_cols, np.int64)
        vx[dc, 2] = self.norm(cur, dc)
        for k in range(1, MAX_LAG + 1):
            i = len(obs) - 1 - k
            if i >= 0 and obs[i] is not None:
                vx[dc, 1 + 2 * k] = self.norm(obs[i], dc)
                vx[dc, 2 + 2 * k] = 1.0
        w = (self.hi - self.lo).astype(np.float64)
        dlt = np.where(w > 0, (np.asarray(s_proj, np.float64) - s_now) / np.where(w > 0, w, 1), 0.0)
        vx[:nv, 13] = np.where(self.hidden, 0.0, dlt)
        cx = np.zeros((TK.MAX_CTRL, F_CX), np.float32)
        for k, j in enumerate(inflight[:2]):
            o = interp.decode_joint(j)
            for s_ in range(self.n_ctrl):
                cx[s_, 4 * k + o[s_]] = 1.0
                cx[s_, 4 * k + 3] = 1.0
        past = [int(j) for j in dec[:len(dec) - self.d] if j is not None]
        if past:
            for s_ in range(self.n_ctrl):
                opts = [interp.decode_joint(j)[s_] for j in past]
                for o in range(3):
                    cx[s_, 8 + o] = opts.count(o) / len(past)
        gx = np.zeros(F_GX, np.float32)
        gx[0] = 1.0
        gx[1 + self.d] = 1.0
        gx[4] = self.H / 6.0
        gx[5] = self.hidden.sum() / nv
        gx[6] = float(self.hidden.any())
        gx[7] = float(ended == "crash")
        gx[8] = float(ended == "success")
        gx[9] = sum(o is not None for o in obs) / self.H
        r16 = (lambda a: a.astype(np.float16).astype(np.float32))   # rows store float16: serve == train bit for bit
        return s_proj, r16(vx), r16(cx), r16(gx)


def view_arrays(xp: XProgram, views) -> tuple[list, dict]:
    """[s_proj per view], {"var_x", "ctrl_x", "glob_x"} float32 arrays for a list of (obs, dec) views."""
    out = zeros(len(views))
    states = []
    for i, (obs, dec) in enumerate(views):
        s, vx, cx, gx = xp.view_state(obs, dec)
        states.append(s)
        out["var_x"][i], out["ctrl_x"][i], out["glob_x"][i] = vx, cx, gx
    return states, out
