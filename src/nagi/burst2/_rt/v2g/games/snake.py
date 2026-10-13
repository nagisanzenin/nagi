"""Snake Rush (rules rush-2) as a v2g game rule pack behind the LANES Machine API.

Wraps, without forking: the engine (``arena.games.snake_rush`` via ``bv2n.data.views`` contract source: reset / step /
served request bytes / parse), and lane hybrid's public-rules forward model + bounded own-move search
(``bv2n.hybrid.snake_search``: ``node_of`` / ``Sim.tick`` / ``SearchPolicy``; docs/burst_v2_next/lanes/hybrid.md).

    m = SnakeMachine()                              # or reader.read_rules(arena.games.snake_rush.rules_text())
    s = m.initial(seed)                             # engine state (TRAIN / dev seeds only; never Arena eval seeds)
    s2, terminal, success = m.step(s, joint)        # one engine tick with the APPLIED move (success = survived >= 30 s)
    text = m.request_text(s, applied_joint)         # served request bytes (contract v1; the episode's ViewBuilder)
    view = m.parse(text)                            # parsed view dict (the only search input)
    nxt, ate_or_cause = m.model_step(view, joint)   # forward model: one exact tick on known information
    joint, stats = m.search(view)                   # deterministic: sims budget, hash tie (= hybrid Srand12full)

Joints = move index 0..3 = (up, right, down, left). Timing: the 1-tick contract; the move decided on the request at
tick t is applied from t + 1, so the pending move (the request's APPLIED line) is the in-flight queue of length 1
(``delay = 1``), simulated exactly first. Unknown under the information set (forward model treats them as in
hybrid.md §2): the next food after an eat (none appears) and walls not yet announced (shown 12 ticks ahead).
Eval mode = deterministic: ``max_sims`` simulator calls (default 20,000, the hybrid's frozen budget), k = 12 own
moves, leaf 'full', hash tie (``tie='rand'`` in the hybrid). No wall-clock branching, nothing carried across calls.
"""

from __future__ import annotations

import time

KIND = "game"
DEFAULT_MAX_SIMS = 20_000
DEFAULT_K = 12


def _S():
    from nagi.burst2._rt.arena.games import snake_rush as S  # noqa: PLC0415

    return S


def rules_text() -> str:
    return _S().rules_text()


def match_rules(text: str):
    """SnakeMachine when ``text`` is exactly the public rules text (final newline tolerated), else None."""
    rt = rules_text()
    return SnakeMachine() if text.rstrip("\n") == rt.rstrip("\n") else None


def match_request(text: str):
    """SnakeMachine when ``text`` is a served Snake request (its STATE block starts with the exact rules text)."""
    rt = rules_text()
    return SnakeMachine() if ("\nSTATE:\n" + rt + "\n") in text else None


class SnakeMachine:
    kind = KIND
    game = "snake"
    delay = 1
    hidden: list = []
    window = 1

    def __init__(self):
        import hashlib  # noqa: PLC0415

        from nagi.burst2._rt.bv2n.data import views as VW  # noqa: PLC0415

        self.vs = VW.make("snake")
        self.S = _S()
        self.names = tuple(self.S.DNAME)
        self.machine_id = "game:snake:" + hashlib.sha256(rules_text().encode()).hexdigest()[:16]
        self.read_via = "exact"

    # ------------------------------------------------------------------ rules / engine
    def rules_text(self) -> str:
        return rules_text()

    def legal(self, state=None) -> list[int]:
        return [0, 1, 2, 3]

    def initial(self, seed):
        return self.vs.reset(seed)  # also starts the episode's ViewBuilder

    def step(self, state, joint: int, rng=None) -> tuple:
        s2 = self.vs.step(state, {"move": self.names[int(joint)]})
        done = bool(self.vs.done(s2))
        return s2, done, bool(done and self.vs.outcome(s2)["success"])

    def request_text(self, state, applied_joint: int) -> str:
        return self.vs.render(state, {"move": self.names[int(applied_joint)]})

    def parse(self, text: str) -> dict:
        return self.vs.parse(text)

    # ------------------------------------------------------------------ forward model + search
    def model_step(self, view_or_node, joint: int):
        from nagi.burst2._rt.bv2n.hybrid import snake_search as H  # noqa: PLC0415

        node = H.node_of(view_or_node) if isinstance(view_or_node, dict) else view_or_node
        return H.Sim(1).tick(node, int(joint))

    def search(self, view, history=None, core=None, deadline_ms=200.0, max_sims=None, k=None, tie="hash", rng=None,
               tau=0.9, deterministic=True, **_kw) -> tuple[int, dict]:
        from nagi.burst2._rt.bv2n.hybrid import snake_search as H  # noqa: PLC0415

        if not deterministic:
            raise ValueError("the Snake pack has no wall-clock mode (decisions are deterministic by construction)")
        if core is not None:
            raise ValueError("Snake core prior is not wired: lane hybrid D2 = -3.19 s (the prior hurt given search)")
        t0, c0 = time.perf_counter(), time.thread_time()
        budget = int(max_sims or DEFAULT_MAX_SIMS)
        pol = H.SearchPolicy(int(k or DEFAULT_K), budget=budget,
                             tie={"hash": "rand", "greedy": "greedy"}[tie], leaf="full")
        move = pol.act(view)["move"]
        st = pol.stats[-1]
        ms = (time.perf_counter() - t0) * 1e3
        # Sim counts the refused call that raises Budget: simulated ticks = min(calls, budget)
        stats = {"sims": min(int(st["sim_calls"]), budget), "stop": "sims" if st["sim_calls"] > budget else "k",
                 "depth": int(st["depth"]), "ms": ms,
                 "cpu_ms": (time.thread_time() - c0) * 1e3, "gated": False, "relevant": bool(st["relevant"]),
                 "deterministic": True, "max_sims": budget,
                 "over_deadline": bool(deadline_ms is not None and ms > deadline_ms), "acceptable": None}
        return self.names.index(move), stats

    def operate(self, state, options: dict, t0: float) -> dict:
        """SDK path for a parsed view dict (``state``); a served request goes through ``operate_request``."""
        opts = {k: v for k, v in (options or {}).items() if k not in ("seed", "session", "step", "rng", "tie")}
        j, st = self.search(state, **opts)  # deterministic hash tie: the request carries the tick (no state loops)
        st.update({"total_ms": (time.perf_counter() - t0) * 1e3, "machine_id": self.machine_id,
                   "read_via": self.read_via})
        return {"choice": {"move": self.names[j]}, "joint": j,
                "probabilities": {"move": {n: float(i == j) for i, n in enumerate(self.names)}},
                "joint_probabilities": {j: 1.0}, "stats": st}

    def operate_request(self, text: str, options: dict, t0: float) -> dict:
        tr = time.perf_counter()
        view = self.parse(text)
        read_ms = (time.perf_counter() - tr) * 1e3
        out = self.operate(view, options, t0)
        out["stats"]["read_ms"] = read_ms
        return out
