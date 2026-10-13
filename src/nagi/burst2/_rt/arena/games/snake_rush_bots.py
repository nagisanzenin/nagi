"""Arena v3 SNAKE RUSH bot ladder (CPU, deterministic, no RNG). docs/arena_v3/SNAKE.md §Ladder.

Each policy is a pure function policy(state, game, R) -> option, where R is the rule set the bot BELIEVES (the ladder
bots believe the true rules, game.rules; the flip-share analysis also calls the planner with R = BASE). Bots see only
what the text shows: the board, the '+' cells with their due ticks, the hunger counter and the clock-indexed ramp
(the ramp formulas are in the rules text); never the unshown part of the wall schedule.

  sr1_naive    : head for the nearest food (Manhattan; torus when the edges wrap); never steer into a wall or off
                 the board (every cell of the move), but blind to its own body; ties: turns before going straight,
                 then canonical order. It dies by biting itself once it is long: a player that reads the food and
                 the walls but not its own shape.
  sr2_heuristic: among moves that do not crash this tick (every cell of a double step), keep those after which the
                 free area reachable from the new head is >= the snake's length (walls, '+' cells due within 2
                 ticks and poison closed); take the one nearest the food; else the largest area. Ignores hunger.
  sr3_planner  : tick-exact search over the macro moves (1 or 2 cells per tick from the clock, turns only at tick
                 boundaries, body cells free once the tail has passed, '+' cells closed from their due tick) to the
                 earliest food reachable before the hunger runs out; simulate the snake along that route and take it
                 if the virtual head can then still reach its virtual tail. Otherwise stall by following the tail
                 while the hunger leaves slack; when it does not, take the food route anyway. Last resort: sr2.
"""
from __future__ import annotations

from nagi.burst2._rt.arena.games.snake_rush import (BASE, DNAME, NB, N, T_CAP, Rules, RushState, flood, legal, xy)
from nagi.burst2._rt.arena.v2.bots import Bot

INF = 1 << 30
SLACK = 3          # planner: stall (follow the tail) only while hunger - route ticks >= SLACK


def _order(s: RushState) -> list[int]:
    """Legal directions, current heading first (deterministic tie-break), then canonical order."""
    return [s.heading] + [DNAME.index(o) for o in legal(s.heading) if DNAME.index(o) != s.heading]


def _targets(s: RushState, game, R: Rules) -> list[int]:
    return game.items(s, R)


def _manhattan(a: int, b: int, wrap: bool) -> int:
    (ax, ay), (bx, by) = xy(a), xy(b)
    dx, dy = abs(ax - bx), abs(ay - by)
    return (min(dx, N - dx) + min(dy, N - dy)) if wrap else dx + dy


def _near(c: int, targets, wrap: bool) -> int:
    return min((_manhattan(c, t, wrap) for t in targets), default=0)


def vmove(s: RushState, body: tuple, grow: int, d: int, cells: int, walls, targets, R: Rules,
          poison: int = -1) -> tuple[str, tuple, int, int]:
    """Move a virtual snake `cells` cells in direction d. Returns (crash cause or '', body, grow, food eaten)."""
    ate = 0
    for _ in range(cells):
        nxt = NB[R.wrap][body[0]][d]
        solid = () if R.ghost else (body if grow > 0 else body[:-1])
        if nxt < 0:
            return "edge", body, grow, ate
        if walls[nxt]:
            return "wall", body, grow, ate
        if nxt in solid:
            return "self", body, grow, ate
        if R.poison and nxt == poison:
            return "poison", body, grow, ate
        body = (nxt,) + body
        if grow > 0:
            grow -= 1
        else:
            body = body[:-1]
        if nxt in targets:
            grow += R.growth
            ate += 1
            targets = ()           # the next food is unknown: stop treating any cell as food
    return "", body, grow, ate


# ---------------------------------------------------------------- L1 naive

def naive(s: RushState, game, R: Rules = BASE) -> str:
    """Head for the nearest food; never steer into a wall or off the board (every cell of this move), but ignore
    the snake's own body. Ties: turns before straight, then canonical order."""
    from dataclasses import replace
    targets = _targets(s, game, R)
    Rg = replace(R, ghost=True)            # blind to its own body
    W = eff_walls(s, R)
    best, key = s.heading, None
    for d in _order(s)[1:] + [s.heading]:
        why, body, _, _ = vmove(s, s.body, s.grow, d, R.next_move(s.tick)[1], W, targets, Rg, s.poison)
        k = (bool(why), _near(body[0], targets, R.wrap), d == s.heading)
        if key is None or k < key:
            best, key = d, k
    return DNAME[best]


# ---------------------------------------------------------------- L2 heuristic

def eff_walls(s: RushState, R: Rules) -> bytes:
    """Cells that kill the head now: walls, plus the shown '+' cells when R says they are already deadly."""
    if not R.hot_warn:
        return s.walls
    w = bytearray(s.walls)
    for c, _ in s.warned():
        w[c] = 1
    return bytes(w)


def _closed(s: RushState, R: Rules, within: int) -> bytearray:
    w = bytearray(s.walls)
    for c, dd in s.warned():
        if dd <= within:
            w[c] = 1
    if R.poison and s.poison >= 0:
        w[s.poison] = 1
    return w


def heuristic(s: RushState, game, R: Rules = BASE) -> str:
    targets = _targets(s, game, R)
    w = _closed(s, R, 2)
    cands = []
    for d in _order(s):
        why, body, grow, _ = vmove(s, s.body, s.grow, d, R.next_move(s.tick)[1], eff_walls(s, R), targets, R,
                                   s.poison)
        if why:
            continue
        blocked = (set() if R.ghost else set(body[1:])) | {c for c in range(N * N) if w[c]}
        area = flood(body[0], blocked, R.wrap)
        cands.append((d, body, _near(body[0], targets, R.wrap), area))
    if not cands:
        return DNAME[s.heading]
    ok = [c for c in cands if c[3] >= len(c[1])]
    if ok:
        return DNAME[min(ok, key=lambda c: c[2])[0]]
    return DNAME[max(cands, key=lambda c: c[3])[0]]


# ---------------------------------------------------------------- L3 planner

def _due_map(s: RushState) -> dict[int, int]:
    """Visible '+' cells -> absolute due tick (closed for any move that starts at or after it)."""
    return {c: s.tick + dd for c, dd in s.warned()}


def route(s: RushState, game, R: Rules, hunger: int | None = None, targets=None):
    """Earliest food reachable by macro moves before the hunger runs out: (list of directions per tick, ticks) or
    None. Tick-exact: move j starts at tick s.tick + j and covers R.cells(s.tick + j) cells; turns only between
    moves; a body cell is enterable once the tail has passed it (cell steps); a '+' cell is closed for moves
    starting at or after its due tick; poison is closed."""
    targets = set(_targets(s, game, R) if targets is None else targets)
    if not targets:
        return None
    hunger = s.hunger if hunger is None else hunger
    L, g = len(s.body), s.grow
    free_at = {} if R.ghost else {c: (L - i) + g for i, c in enumerate(s.body) if i > 0}
    due = _due_map(s)
    W = eff_walls(s, R)
    nb = NB[R.wrap]
    start = (s.head, s.heading)
    parent = {start: None}
    frontier, steps = [start], 0
    for j in range(hunger):
        tick = s.tick + j
        cells = R.cells(tick)
        if cells == 0:             # the snake waits this tick: same frontier, one tick of hunger spent
            continue
        nxt_front = []
        for node in frontier:
            c0, hd = node
            for d in range(4):
                if d == (hd + 2) % 4:
                    continue
                c, ok, hit = c0, True, False
                for k in range(cells):
                    n = nb[c][d]
                    if (n < 0 or W[n] or (R.poison and n == s.poison) or steps + k + 1 < free_at.get(n, 0)
                            or due.get(n, INF) <= tick):
                        ok = False
                        break
                    c = n
                    if c in targets:
                        hit = True
                        break
                if not ok:
                    continue
                key = (c, d)
                if hit:
                    path, cur = [d], node
                    while parent[cur] is not None:
                        prev, dd = parent[cur]
                        path.append(dd)
                        cur = prev
                    path.reverse()
                    return path, j + 1
                if key not in parent:
                    parent[key] = (node, d)
                    nxt_front.append(key)
        frontier = nxt_front
        steps += cells
        if not frontier:
            break
    return None


def _tail_reach(body: tuple, grow: int, walls, R: Rules) -> int:
    """Earliest cell step at which the head can enter the current tail cell (time-aware), -1 if it cannot."""
    if len(body) < 2 or R.ghost:
        return 1
    L = len(body)
    free_at = {c: (L - i) + grow for i, c in enumerate(body) if i > 0}
    tail = body[-1]
    nb, dist, q = NB[R.wrap], {body[0]: 0}, [body[0]]
    for c in q:
        t = dist[c] + 1
        for n in nb[c]:
            if n >= 0 and n not in dist and not walls[n] and t >= free_at.get(n, 0):
                if n == tail:
                    return t
                dist[n] = t
                q.append(n)
    return -1


class V:
    """Virtual snake for look-ahead: what the text shows (board, '+' cells with due ticks, hunger); food eaten in
    a simulated move is not replaced (the next food is unknown before the move)."""
    __slots__ = ("tick", "body", "grow", "hunger", "walls", "due", "food", "heading", "poison")

    def __init__(self, tick, body, grow, hunger, walls, due, food, heading, poison):
        self.tick, self.body, self.grow, self.hunger = tick, body, grow, hunger
        self.walls, self.due, self.food, self.heading, self.poison = walls, due, food, heading, poison


def root(s: RushState, game, R: Rules) -> V:
    return V(s.tick, s.body, s.grow, s.hunger, eff_walls(s, R), _due_map(s), frozenset(_targets(s, game, R)), s.heading,
             s.poison)


def _build(walls, due, tick, body):
    built = [c for c, t in due.items() if t <= tick and c not in body]
    if built:
        w = bytearray(walls)
        for c in built:
            w[c] = 1
        walls = bytes(w)
        due = {c: t for c, t in due.items() if c not in built}
    return walls, due


def vstep(v: V, d: int, R: Rules, hunger_kills: bool = True):
    """The NEXT MOVE in direction d: first the waiting ticks (0 cells) before it, then one move of >= 1 cell.
    (child V, food eaten) or None if the move crashes (or starves when hunger_kills)."""
    tick, hunger, walls, due = v.tick, v.hunger, v.walls, v.due
    while R.cells(tick) == 0 and tick < T_CAP:
        tick += 1
        hunger = min(hunger - 1, R.hunger_limit(tick))
        if hunger <= 0 and hunger_kills:
            return None
        walls, due = _build(walls, due, tick, v.body)
    why, body, grow, ate = vmove(None, v.body, v.grow, d, R.cells(tick), walls, v.food, R, v.poison)
    if why:
        return None
    tick += 1
    hunger = R.hunger_limit(tick) if ate else min(hunger - 1, R.hunger_limit(tick))
    if hunger <= 0 and hunger_kills:
        return None
    walls, due = _build(walls, due, tick, body)
    return V(tick, body, grow, hunger, walls, due, frozenset() if ate else v.food, d, v.poison), ate


def vtick(v: V, d: int, R: Rules):
    """Exactly one tick with direction d (a waiting tick moves nothing and keeps the heading). None if it dies."""
    if R.cells(v.tick) > 0:
        r = vstep(v, d, R)
        return None if r is None else r[0]
    tick = v.tick + 1
    hunger = min(v.hunger - 1, R.hunger_limit(tick))
    if hunger <= 0:
        return None
    walls, due = _build(v.walls, v.due, tick, v.body)
    return V(tick, v.body, v.grow, hunger, walls, due, v.food, v.heading, v.poison)


def survive(v: V, depth: int, R: Rules) -> bool:
    """Some move sequence avoids every crash for `depth` more ticks (hunger ignored: the food route handles it)."""
    if depth == 0:
        return True
    for d in (v.heading, (v.heading + 1) % 4, (v.heading + 3) % 4):
        r = vstep(v, d, R, hunger_kills=False)
        if r is not None and survive(r[0], depth - 1, R):
            return True
    return False


def _as_state(v: V, s: RushState) -> RushState:
    from dataclasses import replace
    return replace(s, tick=v.tick, body=v.body, grow=v.grow, hunger=v.hunger, walls=v.walls, heading=v.heading,
                   sched=tuple(sorted((t, c) for c, t in v.due.items())))


def _route_v(v: V, s: RushState, game, R: Rules):
    if not v.food:
        return None
    return route(_as_state(v, s), game, R, v.hunger, targets=v.food)


def _free(walls, v: V) -> bytearray:
    w = bytearray(walls)
    for c, t in v.due.items():
        if t <= v.tick + 3:
            w[c] = 1
    return w


def planner(s: RushState, game, R: Rules = BASE, depth: int = 8, lag: tuple[int, int] | None = None) -> str:
    """One-move look-ahead: every legal first move is scored (lexicographic, higher is better):
    (3) it eats now and the head can still reach its tail; (2) from the child a food route before the hunger runs
    out exists and, simulated, leaves the head able to reach its tail and survive `depth` more ticks, shorter is
    better; (1) otherwise a stall: when the hunger no longer leaves SLACK ticks over the route, the (unsafe) route;
    else the move that keeps the tail reachable with the most room; (0) moves that cannot survive `depth` ticks,
    by flood area. Crashing moves are never taken if any other exists.
    lag = (direction, n): the reply lands n ticks after s and the runner applies `direction` until then (the planner's
    own previous reply; arena.v3.delay). The look-ahead then starts from the predicted state after those n ticks
    (food eaten on the way is unknown and treated as gone)."""
    r0 = root(s, game, R)
    if lag:
        for _ in range(lag[1]):
            nv = vtick(r0, lag[0], R)
            if nv is None:
                break
            r0 = nv
    best, key = None, None
    for d in [r0.heading] + [x for x in range(4) if x != r0.heading and x != (r0.heading + 2) % 4]:
        res = vstep(r0, d, R)
        if res is None:
            continue
        v, ate = res
        w = _free(v.walls, v)
        area = flood(v.body[0], (set() if R.ghost else set(v.body[1:])) | {c for c in range(N * N) if w[c]}, R.wrap)
        if not survive(v, depth, R):
            k = (0, area)
        elif ate:
            k = (3, 1 if _tail_reach(v.body, v.grow, w, R) >= 0 else 0, area)
        else:
            rt = _route_v(v, s, game, R)
            k = None
            if rt is not None:
                path, ticks = rt
                u, ok = v, True
                for dd in path:
                    nx = vstep(u, dd, R)
                    if nx is None:
                        ok = False
                        break
                    u = nx[0]
                if ok and _tail_reach(u.body, u.grow, _free(u.walls, u), R) >= 0 and survive(u, depth, R):
                    k = (2, -ticks, area)
                elif v.hunger - ticks < SLACK:
                    k = (1, 1, -ticks, area)
            if k is None:
                tr = _tail_reach(v.body, v.grow, w, R)
                k = (1, 0, tr >= 0, tr if tr >= 0 else 0, area)
        if key is None or k > key:
            best, key = d, k
    if best is None:
        return heuristic(s, game, R) if lag is None else DNAME[s.dir]
    return DNAME[best]


POLICIES = {"sr1_naive": naive, "sr2_heuristic": heuristic, "sr3_planner": planner}
LADDER = tuple(POLICIES)


class RushBot(Bot):
    """Ladder bot for the v2 runner: sees the engine state, believes the true rules of the game it plays. `lag` is set
    by arena.v3.delay.Delayed (realtime timing); only the planner uses it (it plans from where its reply lands)."""

    lag = None
    belief: Rules | None = None     # the rules the bot believes (None = the true rules; flip / value-of-knowing)

    def choose(self, q) -> str:
        R = self.belief or self.game.rules
        if self.bot_id == "sr3_planner" and self.lag:
            acts, n = self.lag
            mv = planner(self.state, self.game, R, lag=(DNAME.index(acts["move"]), n))
        else:
            mv = POLICIES[self.bot_id](self.state, self.game, R)
        return mv if mv in q.options else q.default


def make_rush_bot(bot_id: str) -> RushBot:
    assert bot_id in POLICIES, bot_id
    return RushBot(bot_id)
