"""Hybrid Snake policy (lane bv2n hybrid): a frozen one-pass student prior + a bounded look-ahead search over the
agent's OWN moves, written from the public rules (arena.games.snake_rush.rules_text: board, speed / hunger schedule,
'+' -> '#' after WARN ticks, never under the snake) and the PARSED contract view only (the dict that
bv2n.data.views.view_dict(parse(render(view))) returns). It never reads runner state, the teacher, the seed or the
food RNG. It does not call or copy arena.games.snake_rush_bots (the teacher sr3_planner).

Forward model (exact under the information set, except where marked unknown):
  * the pending move: the reply to THIS request lands at t + 1 (nominal 1-tick contract), so the move t -> t + 1 is
    the applied p_log move (engine rule: straight-back keeps the last direction);
  * per tick: cells(t) cells in the chosen direction, death on edge / wall / own body (the tail cell only while
    growing), growth 2 per food, hunger = H(t + 1) on eating else hunger - 1 (0 = starved), then every due '+' cell
    not under the body becomes a wall;
  * UNKNOWN, treated pessimistically for hunger: the next food after a simulated eat (no new food appears in the
    search), and walls not yet announced (a wall is shown exactly WARN = 12 ticks before it is due, so every wall due
    within 12 ticks of the view is known; the search horizon is reported in ticks).

Search value of a root move m (k = depth in MOVING steps after the pending one; waiting ticks with 0 cells are
advanced automatically): V(m) = max over own continuations of (moving steps survived, capped at k; leaf_ok), with
leaf_ok (evaluated only at full depth) = the leaf head can still reach a freed body cell or at least len + growth
cells under a time-aware BFS (the trap test) AND (food already eaten in the search, or the visible food is within the
cell budget of the remaining hunger). Policies:
  H  (hybrid)   the student's highest-prior move among argmax_m V(m)
  S  (no learning, mc-2 S4 analogue)  a deterministic pseudo-random move among argmax V (hash of the request)
  G  (no learning, hand heuristic)    the move with the shortest time-aware BFS distance to food among argmax V
Compute bound: iterative deepening d = 1..k with a deterministic budget of simulator calls; if the budget runs out
inside depth d, the decision uses depth d - 1 (always complete). Deterministic given the view.
"""
from __future__ import annotations

import hashlib
import time

from nagi.burst2._rt.arena.games import snake_rush as S

R = S.BASE
N = S.N
NB = S.NB[False]
DNAME = S.DNAME
_DIDX = {d: i for i, d in enumerate(DNAME)}


class Budget(Exception):
    pass


class Node:
    """A simulated position at a tick boundary (what the view shows, advanced by known rules)."""
    __slots__ = ("tick", "body", "grow", "hunger", "walls", "due", "food", "heading", "dir")

    def __init__(self, tick, body, grow, hunger, walls, due, food, heading, dir_):
        self.tick, self.body, self.grow, self.hunger = tick, body, grow, hunger
        self.walls, self.due, self.food, self.heading, self.dir = walls, due, food, heading, dir_


def _cell(xy) -> int:
    return int(xy[1]) * N + int(xy[0])


def node_of(view: dict) -> Node:
    """Root node from the parsed view dict only (grid text, ordered body, the complete '+' list, status lines)."""
    g = "".join(view["grid"])
    walls = frozenset(c for c, ch in enumerate(g) if ch == "#")
    t = int(view["tick"])
    due = tuple(sorted((t + int(d), _cell((x, y))) for x, y, d in view["warned"]))
    food = frozenset(c for c, ch in enumerate(g) if ch == "*")
    body = tuple(_cell(b) for b in view["body"])
    return Node(t, body, int(view["growing"]), int(view["hunger"]), walls, due, food, _DIDX[view["heading"]],
                _DIDX[view["next"]])


class Sim:
    """Counts simulator calls (one call = one simulated tick) against a budget."""

    def __init__(self, budget: int, leaf: str = "full"):
        assert leaf in ("none", "trap", "full")
        self.calls, self.budget, self.leaf = 0, budget, leaf

    def tick(self, v: Node, d: int):
        """One tick with reply direction d (engine rule: straight back keeps the last direction).
        Returns (child, ate) or (None, cause)."""
        self.calls += 1
        if self.calls > self.budget:
            raise Budget
        if d == (v.heading + 2) % 4:
            d = v.dir
        n = R.cells(v.tick)
        body, grow, food, walls, ate = v.body, v.grow, v.food, v.walls, False
        for _ in range(n):
            nxt = NB[body[0]][d]
            if nxt < 0:
                return None, "edge"
            if nxt in walls:
                return None, "wall"
            if nxt in (body if grow > 0 else body[:-1]):
                return None, "self"
            body = (nxt,) + (body if grow > 0 else body[:-1])
            if grow > 0:
                grow -= 1
            if nxt in food:
                ate, grow, food = True, grow + R.growth, frozenset()   # the next food is unknown: none appears
        tick = v.tick + 1
        lim = R.hunger_limit(tick)
        hunger = lim if ate else min(v.hunger - 1, lim)
        if hunger <= 0:
            return None, "starved"
        due = v.due
        if due and due[0][0] <= tick:
            occ = set(body)
            built = [c for t_, c in due if t_ <= tick and c not in occ]
            if built:
                walls = walls | frozenset(built)
                due = tuple(x for x in due if x[1] not in built)
                if food & walls:
                    food = frozenset()                      # food on a new wall moves (to an unknown cell)
        return Node(tick, body, grow, hunger, walls, due, food, d if n else v.heading, d), ate

    def advance_wait(self, v: Node):
        """Advance through waiting ticks (0 cells) until a tick whose move covers >= 1 cell (or T_CAP)."""
        while v.tick < S.T_CAP and R.cells(v.tick) == 0:
            v, why = self.tick(v, v.dir)
            if v is None:
                return None
        return v


def time_bfs(v: Node):
    """Time-aware BFS in cell steps from the head: body[i] (i >= 1) is enterable from step len - i + grow on (no
    further eating assumed); walls and every shown '+' cell are blocked. Returns (reached count, freed body cell
    reached, distance to the nearest visible food or -1)."""
    body, L, g = v.body, len(v.body), v.grow
    free_at = {c: L - i + g for i, c in enumerate(body) if i > 0}
    blocked = v.walls | frozenset(c for _, c in v.due)
    dist = {body[0]: 0}
    q = [body[0]]
    tail_hit, fd = False, -1
    food = v.food
    for c in q:
        t = dist[c] + 1
        for n in NB[c]:
            if n < 0 or n in dist or n in blocked:
                continue
            fa = free_at.get(n)
            if fa is not None:
                if t < fa:
                    continue
                tail_hit = True
            dist[n] = t
            q.append(n)
            if fd < 0 and n in food:
                fd = t
    return len(dist) - 1, tail_hit, fd


# leaf tests: 'none' (pure k-step survival), 'trap' (+ trap test), 'full' (+ trap and hunger tests)


def leaf_ok(v: Node, ate_any: bool, leaf: str = "full") -> bool:
    if v.tick >= S.T_CAP or leaf == "none":
        return True
    reach, tail_hit, fd = time_bfs(v)
    if not (tail_hit or reach >= len(v.body) + v.grow):
        return False
    if leaf == "trap" or ate_any or not v.food:
        return True
    budget = R.pos(v.tick + v.hunger) - R.pos(v.tick)
    return 0 <= fd <= budget


def expand(sim: Sim, v: Node, d: int, k: int, ate_any: bool) -> tuple:
    """Value of playing d now from `v` (a node whose tick moves >= 1 cell), then the best own continuation."""
    c, ate = sim.tick(v, d)
    if c is None:
        return (0, False)
    c = sim.advance_wait(c)
    if c is None:                                       # starved while waiting before the next move: a death
        return (0, False)
    s2, ok = value(sim, c, k - 1, ate_any or ate)
    return (1 + s2, ok)


def value(sim: Sim, v: Node, k: int, ate_any: bool) -> tuple:
    """(moving steps survived capped at k, leaf_ok) maximised over own continuations; early exit at the maximum.
    `v` is a node at a tick whose move covers >= 1 cell (or at T_CAP)."""
    if v.tick >= S.T_CAP:
        return (k, True)
    if k == 0:
        return (0, leaf_ok(v, ate_any, sim.leaf))
    best = (0, False)
    h = v.heading
    for d in (h, (h + 1) % 4, (h + 3) % 4):            # deeper ordering: straight, right, left (fixed)
        val = expand(sim, v, d, k, ate_any)
        if val > best:
            best = val
            if best == (k, True):
                break
    return best


def legal_moves(heading: int) -> list[int]:
    return [d for d in range(4) if d != (heading + 2) % 4]


class SearchPolicy:
    """tie in {'prior', 'rand', 'greedy'}; student = a bv2n.student.model.Student (needed for 'prior')."""

    def __init__(self, k: int, budget: int = 20_000, tie: str = "prior", student=None, leaf: str = "full"):
        assert tie in ("prior", "rand", "greedy") and (tie != "prior" or student is not None)
        self.k, self.budget, self.tie, self.student, self.leaf = k, budget, tie, student, leaf
        self.stats: list[dict] = []

    # ---------------------------------------------------------------- tie-break orders
    def _prior_order(self, view: dict, moves: list[int]) -> tuple[list[int], int]:
        import torch
        from nagi.burst2._rt.bv2n.student import features as F
        st = self.student
        x = (st.sp["x"](view) - st.mu) / st.sd
        with torch.no_grad():
            logits = st.net(torch.from_numpy(x[None]))[0][0].numpy()
        d0 = F.snake_frame(view)
        score = {d: float(logits[(d - d0) % 4]) for d in range(4)}
        argmax = (d0 + int(logits.argmax())) % 4
        return sorted(moves, key=lambda d: (-score[d], d)), argmax

    def _rand_order(self, view: dict, moves: list[int]) -> list[int]:
        key = hashlib.sha256(("bv2n-hybrid-S|" + "".join(view["grid"]) + f"|{view['tick']}|{view['p_log']}").encode()).digest()
        return sorted(moves, key=lambda d: (key[d], d))

    def _greedy_order(self, v1: Node | None, moves: list[int], sim: Sim) -> list[int]:
        if v1 is None:
            return moves
        out = []
        for d in moves:
            c, ate = sim.tick(v1, d)
            if c is None:
                out.append((2, 0, d))
            elif ate:
                out.append((0, 0, d))
            else:
                fd = time_bfs(c)[2]
                out.append((1, fd if fd >= 0 else 999, d))
        return [d for *_, d in sorted(out)]

    # ---------------------------------------------------------------- decision
    def act(self, view: dict) -> dict:
        t0, c0 = time.perf_counter(), time.thread_time()
        sim = Sim(self.budget, self.leaf)
        root = node_of(view)
        pend = _DIDX[view["p_log"]["move"]]
        v1, _ = sim.tick(root, pend)                      # the pending move t -> t + 1 (deterministic)
        heading = v1.heading if v1 is not None else root.heading
        moves = legal_moves(heading)
        prior_arg = None
        if self.tie == "prior":
            order, prior_arg = self._prior_order(view, moves)
        elif self.tie == "rand":
            order = self._rand_order(view, moves)
        else:
            order = self._greedy_order(v1, moves, sim)
        relevant = v1 is not None and v1.tick < S.T_CAP and R.cells(v1.tick) > 0
        depth_done, choice, vals = 0, order[0], {}
        if relevant:
            for k in range(1, self.k + 1):
                try:
                    vk = {}
                    for d in order:
                        vk[d] = expand(sim, v1, d, k, False)
                        if vk[d] == (k, True):
                            break                        # the best possible value: earlier moves in `order` are worse
                except Budget:
                    break
                vals, depth_done = vk, k
                best = max(vals.values())
                choice = next(d for d in order if vals.get(d) == best)
        self.stats.append({"wall_ms": (time.perf_counter() - t0) * 1e3, "cpu_ms": (time.thread_time() - c0) * 1e3,
                           "sim_calls": sim.calls, "depth": depth_done, "relevant": relevant,
                           "override": prior_arg is not None and relevant and choice != prior_arg})
        return {"move": DNAME[choice]}
