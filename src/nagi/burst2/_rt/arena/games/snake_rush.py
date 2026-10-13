"""Arena v3 SNAKE RUSH: endless single-player Snake under a continuous, clock-indexed ramp (docs/arena_v3/SNAKE.md).

Replaces the v1 Snake (arena.games.snake, capped at 300 ticks, no time pressure) under the fail-first brief
(docs/arena_v3/FAIL_FIRST_BRIEF.md + Amendment 1): there is no success terminal state; a round ends at the player's
failure or at the cap T_CAP = 240 ticks (60 s at 4 Hz, right-censored; Amendment 2). Pure-Python integers only in the state
update (no floats, no numpy, no `random`), so a round is bit-exact on every platform.

Exact rules (the text sent to the model is `rules_text()` + the announced variant sentence):

* Board. N x N cells (N = 12), cell id c = y * N + x, x to the right, y downward; outside is the edge. Start walls:
  3-5 short straight segments from the seed (splitmix64 `draw`), added cell by cell only while every open cell stays
  4-connected; a lane around the spawn stays clear. Spawn: length 3, head (6, 8), heading up.
* Clock and ramp. Tick t = 0, 1, ... (250 ms each, FIXED; the protocol clock). Every difficulty parameter is an
  integer function of t ONLY (never of food eaten, length or position), identical for every player of a seed:
    hunger limit  H(t) = H0 - (H0 - H1) * t // T_CAP                  (ticks; 40 -> 16)
    extra cells   E(t) = (t - S0)^2 // (2 (S1 - S0)) on [S0, S1], 0 before, (S1 - S0) // 2 + t - S1 after
                  (cumulative; the move from t to t+1 covers 1 + E(t+1) - E(t) cells in the chosen direction, so
                  the speed ramps linearly from 1 cell/tick at S0 = 12 (3 s) to 2 cells/tick at S1 = 240)
    walls due     C(t) = max(0, t - W0)^2 // WQ + max(0, t - W0) // WL (cumulative count of scheduled wall cells)
  Levels are display labels only: level(t) = 1 + t // 40 (10 s each, L1 ... L6). No parameter steps at a level
  boundary (Amendment 1: no step walls).
  with W0 = 8, WQ = 4000, WL = 12 (32 scheduled walls by 60 s).
* Scheduled walls. Wall j (j = 0, 1, ...) is due at tick tau_j = min{t : C(t) > j}. Its cell is fixed at reset from
  the seed alone (never from the snake): drawn uniformly among open cells not in the spawn lane, accepted only if
  every open cell stays 4-connected with all earlier walls in place. It is shown as '+' for WARN = 12 ticks (3 s)
  before tau_j; at tau_j it becomes wall '#', or, if the snake lies on it then, on the first later tick the snake no
  longer covers it (a wall never appears on the snake). Food or poison on a new wall moves.
* Decision. One Query per tick, key 'move', options = the 3 absolute directions that are not straight back
  (canonical order up, right, down, left), default = current heading (late or invalid replies keep the heading).
* Move (tick t -> t+1). The head steps 1 + E(t+1) - E(t) cells, one at a time, in the chosen direction. Per cell:
  death 'edge' off the board (unless edges wrap), 'wall' on a wall (or on a '+' cell under sr_hotwarn), 'self' on a
  body cell (the tail cell counts only while growth is pending; never under sr_ghost), 'poison' on poison (variant). Then with pending growth g > 0: g -= 1 (tail stays), else
  the tail leaves. On food: eaten += 1, g += growth, new food at once (it can be eaten on the second cell of a double
  step).
* Hunger. hunger = ticks left to eat. After the move: if food was eaten this tick, hunger = H(t+1); else hunger -= 1
  and at 0 the snake dies 'starved'. Always hunger <= H(t+1) (the limit shrinks with the clock).
* End. Death, or t = T_CAP (censored), or no free cell for food (board full; never observed).
* Fair food. Food spawns uniformly (sorted candidates, `draw`) on free cells of the 2-core of the open-cell graph
  (no 1-wide dead ends; walls and '+' cells count as closed) at static shortest-path distance 2 .. max(3, H - 4) from
  the head (walls, '+' cells and the body as obstacles); if none, any such core cell. So the food is always
  reachable in time by at least the static route (the body only frees cells as it moves).
* Randomness. Every draw is splitmix64(seed-derived stream, counter) mod n over a sorted candidate list; the counter
  lives in the state, so a round is a pure function of (seed, variant, applied actions).
* Scores (docs/arena_v3/SNAKE.md, FAIL_FIRST_BRIEF Amendment 1). survival_s = death tick * 0.25 s (the moment of
  the fatal move), 60 if censored; level_at_fail = level of the tick the fatal move started from; game_score = food
  eaten. Ladder position and score01: `snake_rush_arena`.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
from dataclasses import dataclass, replace

from nagi.burst2._rt.arena.core import Event, Query

N = 12
TICK_MS = 250                     # FIXED protocol clock (runner assumes it; NEW_GAME_CONTRACT)
T_CAP = 240                       # 60 s cap (right-censored; FAIL_FIRST_BRIEF Amendment 2)
LEVEL_TICKS = 40                  # display label only
N_LEVELS = 6
START_LEN = 3
SPAWN = (6, 8)
WARN = 12                         # ticks a scheduled wall is shown as '+' before it is due
DIRS = ((0, -1), (1, 0), (0, 1), (-1, 0))  # up, right, down, left (y grows downward)
DNAME = ("up", "right", "down", "left")
RULES_VERSION = "rush-2"
M64 = (1 << 64) - 1
SPEED = (500, 500, 500, 800, 1150, 1550, 2000)  # base speed anchors, cells per tick x 1000 at 0, 10, ..., 60 s
SALT_WALLS, SALT_FOOD, SALT_POISON, SALT_SCHED, SALT_POLICY = 0x57A11, 0xF00D, 0x7015, 0x5C4ED, 0x9011C7


# ---------------------------------------------------------------- integer PRNG (portable by construction)

def splitmix64(x: int) -> int:
    x = (x + 0x9E3779B97F4A7C15) & M64
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & M64
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & M64
    return x ^ (x >> 31)


def draw(seed: int, salt: int, k: int, n: int) -> int:
    """k-th draw in [0, n) of stream (seed, salt). Modulo bias < n / 2^64 (negligible, and deterministic)."""
    return splitmix64(splitmix64((seed & M64) ^ (salt << 32)) ^ k) % n


# ---------------------------------------------------------------- rules, ramp and variants

@dataclass(frozen=True)
class Rules:
    wrap: bool = False       # edges wrap (torus); walls still kill
    poison: bool = False     # a poison item x next to the food kills the snake that eats it
    growth: int = 2          # segments added per food
    ghost: bool = False      # the head may cross the snake's own body (only walls and edges kill)
    hot_warn: bool = False   # a '+' cell already kills the head that enters it
    h0: int = 40             # hunger limit at t = 0 (ticks)
    h1: int = 16             # hunger limit at t = T_CAP
    speed: tuple[int, ...] = SPEED  # cells per tick x 1000 at t = 0, 10, ..., 60 s (piecewise linear per tick)
    w0: int = 8              # first tick of the wall ramp
    wq: int = 4000           # wall ramp quadratic divisor
    wl: int = 12             # wall ramp linear divisor (one wall per wl ticks from w0)

    def hunger_limit(self, t: int) -> int:
        t = min(max(t, 0), T_CAP)
        return self.h0 - (self.h0 - self.h1) * t // T_CAP

    def vel(self, t: int) -> int:
        """Speed V(t) in cells per tick x 1000: integer linear interpolation between the 10 s anchors."""
        return _vel(self.speed, t)

    def pos(self, t: int) -> int:
        """Cumulative cells P(t) = floor(sum_{j < t} V(j) / 1000): the moves up to tick t cover P(t) cells."""
        return _pos_table(self.speed)[min(max(t, 0), T_CAP + 64)]

    def cells(self, t: int) -> int:
        """Cells covered by the move from tick t to t + 1: 0 (the snake waits), 1 or 2."""
        return self.pos(t + 1) - self.pos(t)

    def next_move(self, t: int) -> tuple[int, int]:
        """(tick, cells) of the first move at or after tick t that covers >= 1 cell (the move a reply steers)."""
        u = max(t, 0)
        while self.cells(u) == 0:
            u += 1
        return u, self.cells(u)

    def walls_due(self, t: int) -> int:
        d = max(0, min(t, T_CAP) - self.w0)
        return d * d // self.wq + d // self.wl


BASE = Rules()


def _vel(speed: tuple[int, ...], t: int) -> int:
    t = min(max(t, 0), T_CAP)
    i = min(t // LEVEL_TICKS, len(speed) - 2)
    a, b = speed[i], speed[i + 1]
    return a + (b - a) * (t - i * LEVEL_TICKS) // LEVEL_TICKS


_POS: dict = {}


def _pos_table(speed: tuple[int, ...]) -> tuple[int, ...]:
    tab = _POS.get(speed)
    if tab is None:
        acc, out = 0, [0]
        for j in range(T_CAP + 64):
            acc += _vel(speed, j)
            out.append(acc // 1000)
        assert all(0 <= b - a <= 2 for a, b in zip(out, out[1:])), speed
        tab = _POS[speed] = tuple(out)
    return tab


def level(t: int) -> int:
    """Display label: L1 = 0-9.75 s, L2 = 10-19.75 s, ... (never a parameter step)."""
    return min(N_LEVELS, 1 + max(0, t) // LEVEL_TICKS)


@dataclass(frozen=True)
class Variant:
    id: str
    split: str  # 'variant_dev' (open for development) | 'variant_sealed' (no model looks before the gate)
    announce_text: str
    rules: Rules


VARIANTS = {v.id: v for v in (
    Variant("sr_wrap", "variant_dev",
            "RULE CHANGE: the board edge wraps around: stepping off one side enters the opposite side of the same "
            "row or column. Walls # still kill.", Rules(wrap=True)),
    Variant("sr_poison", "variant_dev",
            "RULE CHANGE: a poison item x lies next to the food. Eating x kills the snake; x moves when the food "
            "moves.", Rules(poison=True)),
    Variant("sr_ghost", "variant_dev",
            "RULE CHANGE: ghost body: the head may cross the snake's own body; only walls # and the edge kill.",
            Rules(ghost=True)),
    Variant("sr_hotwarn", "variant_sealed",
            "RULE CHANGE: live warnings: a + cell already kills the head that enters it (it still becomes wall # "
            "later).", Rules(hot_warn=True)),
    Variant("sr_rush", "variant_sealed",
            "RULE CHANGE: rush: the speed rises faster: 2 cells per tick from 40 s.",
            Rules(speed=(500, 700, 1000, 1400, 2000, 2000, 2000))),
)}


def _speed_phrase(R: Rules) -> str:
    vals = ", ".join(f"{v / 1000:g}" for v in R.speed)
    return f"cells per tick at 0, 10, ..., 60 s: {vals}, smoothly between (below 1 some ticks wait)"


def rules_text(R: Rules = BASE) -> str:
    """The base-rules paragraph (the variant sentence is appended when announced). Numbers follow R."""
    return (f"SNAKE RUSH (rules {RULES_VERSION}): endless Snake, one player, {N}x{N} board; x = column 0-{N - 1} left "
            f"to right, y = row 0-{N - 1} top to bottom. Every 250 ms pick the direction of the next move: up, right, "
            "down or left; straight back, a late or an invalid reply keeps the last one. The head dies entering the "
            f"edge, a wall # or the body (the tail cell is safe unless growing). Food * adds {R.growth} segments; new food "
            f"appears at once. Hunger: eat before the counter runs out or starve; its limit falls from {R.h0} ticks "
            f"to {R.h1} at {T_CAP // 4} s. Speed: {_speed_phrase(R)}. Walls: a + cell becomes wall # after "
            f"{WARN} ticks ({WARN // 4} s), never under the snake; they come faster over time. Everything follows "
            f"the clock; a level is 10 s. Survive until death or {T_CAP // 4} s.")


# ---------------------------------------------------------------- grid helpers

def _nb_table(wrap: bool) -> tuple[tuple[int, ...], ...]:
    out = []
    for c in range(N * N):
        x, y = c % N, c // N
        row = []
        for dx, dy in DIRS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < N and 0 <= ny < N:
                row.append(ny * N + nx)
            else:
                row.append((ny % N) * N + nx % N if wrap else -1)
        out.append(tuple(row))
    return tuple(out)


NB = {False: _nb_table(False), True: _nb_table(True)}  # NB[wrap][cell][dir] -> cell or -1 (edge)


def xy(c: int) -> tuple[int, int]:
    return c % N, c // N


def _blk(blocked, c: int) -> bool:
    return c in blocked if isinstance(blocked, (set, frozenset)) else bool(blocked[c])


def flood(start: int, blocked, wrap: bool) -> int:
    """Number of cells 4-reachable from `start` (start excluded) avoiding `blocked` (a set or bytes-like)."""
    nb, seen, stack = NB[wrap], {start}, [start]
    while stack:
        c = stack.pop()
        for n in nb[c]:
            if n >= 0 and n not in seen and not _blk(blocked, n):
                seen.add(n)
                stack.append(n)
    return len(seen) - 1


def bfs_dist(start: int, blocked, wrap: bool) -> list[int]:
    """Shortest step counts from `start` to every cell avoiding `blocked` (-1 = unreachable)."""
    nb, dist, q = NB[wrap], [-1] * (N * N), [start]
    dist[start] = 0
    for c in q:
        for n in nb[c]:
            if n >= 0 and dist[n] < 0 and not _blk(blocked, n):
                dist[n] = dist[c] + 1
                q.append(n)
    return dist


def _connected(w) -> bool:
    free = [c for c in range(N * N) if not w[c]]
    return not free or flood(free[0], w, False) == len(free) - 1


def core(w, wrap: bool) -> set[int]:
    """2-core of the open-cell graph (open = w[c] == 0): repeatedly drop open cells with <= 1 open neighbour."""
    nb = NB[wrap]
    live = {c for c in range(N * N) if not w[c]}
    deg = {c: sum(1 for n in nb[c] if n in live) for c in live}
    stack = sorted(c for c in live if deg[c] <= 1)
    while stack:
        c = stack.pop()
        if c not in live:
            continue
        live.discard(c)
        for n in nb[c]:
            if n in live:
                deg[n] -= 1
                if deg[n] <= 1:
                    stack.append(n)
    return live


def _lane() -> set[int]:
    sx, sy = SPAWN
    return {c for c in range(N * N) if abs(xy(c)[0] - sx) <= 1 and xy(c)[1] >= sy - 5}


LANE = frozenset(_lane())


def _safe() -> set[int]:
    """Opening zone (rush-2): every cell within 3 (Chebyshev) of the spawn head plus the 3-wide column band the snake
    heads into. No start wall lies here, and no scheduled wall due in the first 10 s (a sane opening under latency)."""
    sx, sy = SPAWN
    return {c for c in range(N * N) if (abs(xy(c)[0] - sx) <= 3 and abs(xy(c)[1] - sy) <= 3) or abs(xy(c)[0] - sx) <= 1}


SAFE = frozenset(_safe())
SAFE_DUE = LEVEL_TICKS    # scheduled walls due before this tick also avoid SAFE


def make_walls(seed: int) -> bytes:
    """Start walls: 3-5 straight segments of 2-4 cells, cell by cell while the open cells stay connected."""
    walls, k = bytearray(N * N), 0

    def nxt(n):
        nonlocal k
        k += 1
        return draw(seed, SALT_WALLS, k, n)

    for _ in range(3 + nxt(3)):
        x, y, d, ln = 1 + nxt(N - 2), 1 + nxt(N - 2), nxt(4), 2 + nxt(3)
        for _ in range(ln):
            c = y * N + x
            if 0 <= x < N and 0 <= y < N and c not in SAFE and not walls[c]:
                walls[c] = 1
                if not _connected(walls):
                    walls[c] = 0
            x, y = x + DIRS[d][0], y + DIRS[d][1]
    return bytes(walls)


def wall_schedule(seed: int, start: bytes, R: Rules = BASE) -> tuple[tuple[int, int], ...]:
    """((due tick, cell), ...) of every scheduled wall up to T_CAP; cells from the seed only (never the snake).
    Each cell is drawn among open cells outside the spawn lane, accepted if all open cells stay 4-connected with
    the start walls and every earlier scheduled wall in place (so deferral can only keep the board more open)."""
    w = bytearray(start)
    out, k = [], 0
    n_due = R.walls_due(T_CAP)
    due = [min(t for t in range(T_CAP + 1) if R.walls_due(t) > j) for j in range(n_due)]
    for j in range(n_due):
        cand = [c for c in range(N * N) if not w[c] and c not in LANE and (due[j] >= SAFE_DUE or c not in SAFE)]
        cell = -1
        while cand:
            k += 1
            c = cand[draw(seed, SALT_SCHED, k, len(cand))]
            w[c] = 1
            if _connected(w):
                cell = c
                break
            w[c] = 0
            cand.remove(c)
        if cell < 0:
            break
        out.append((due[j], cell))
    return tuple(out)


# ---------------------------------------------------------------- state

@dataclass(frozen=True)
class RushState:
    seed: int
    tick: int
    body: tuple[int, ...]   # cell ids, head first
    heading: int            # index into DIRS
    grow: int               # pending growth
    food: int               # -1 = none (board full)
    poison: int             # -1 = none
    walls: bytes            # N*N, 1 = wall
    sched: tuple[tuple[int, int], ...]  # scheduled walls not yet built: (due tick, cell), due order
    hunger: int             # ticks left to eat
    alive: bool
    eaten: int
    streak: int             # food eaten since the last tick without food within 12 ticks (display/SFX only)
    last_eat: int           # tick of the last food, -1 = none
    k: int                  # draw counter (food, poison)
    died_tick: int          # -1 = alive
    cause: str
    dir: int = 0            # direction of the next move (the last reply; the query default); heading = last moved

    @property
    def head(self) -> int:
        return self.body[0]

    def solid(self) -> set[int]:
        """Body cells the head cannot enter this tick (the tail is free when not growing)."""
        return set(self.body if self.grow > 0 else self.body[:-1])

    def warned(self) -> list[tuple[int, int]]:
        """(cell, ticks until due; <= 0 = overdue, waiting for the snake to leave) of every '+' cell shown now."""
        return [(c, d - self.tick) for d, c in self.sched if d - self.tick <= WARN]


def legal(heading: int) -> tuple[str, ...]:
    return tuple(DNAME[d] for d in range(4) if d != (heading + 2) % 4)


def survival_ticks(s: RushState) -> int:
    return s.died_tick if not s.alive else s.tick


def survival_s(s: RushState) -> float:
    return survival_ticks(s) * TICK_MS / 1000


def level_at_fail(s: RushState) -> int:
    """Level of the tick the fatal move started from (the level reached); level(T_CAP - 1) = 6 if censored."""
    return level(s.died_tick - 1) if not s.alive else level(min(s.tick, T_CAP) - 1)


def censored(s: RushState) -> bool:
    return s.alive and s.tick >= T_CAP


# ---------------------------------------------------------------- engine

class SnakeRush:
    """Game protocol (arena.core.Game) plus the v2-runner extras (ctx, rules_id, sensor_top)."""

    id, n_players = "snake", 1
    title = "SNAKE RUSH"

    def __init__(self, variant: str | None = None, announce: bool = True, sensors: bool = True,
                 rules: Rules | None = None):
        self.variant = VARIANTS[variant] if variant else None
        self.rules = rules or (self.variant.rules if self.variant else BASE)
        self.announce, self.sensors = announce, sensors
        self.belief = self.rules if (announce or self.variant is None) else BASE  # the rules the TEXT describes
        self.decision_period_ms = TICK_MS
        self.max_round_ms = T_CAP * TICK_MS
        self.rules_text = rules_text(self.belief if self.variant else self.rules) + (
            " " + self.variant.announce_text if self.variant and announce else "")

    @property
    def rules_id(self) -> str:
        v = self.variant.id if self.variant else "base"
        ann = "announced" if self.announce or not self.variant else "unannounced"
        return f"snake_rush:{RULES_VERSION}:{v}:{ann}:{'L1' if self.sensors else 'L0'}"

    def ctx(self):
        return contextlib.nullcontext()

    # ------------------------------------------------------------ reset / spawns

    def reset(self, seed: int) -> RushState:
        sx, sy = SPAWN
        body = tuple((sy + i) * N + sx for i in range(START_LEN))
        walls = make_walls(seed)
        s = RushState(seed, 0, body, 0, 0, -1, -1, walls, wall_schedule(seed, walls, self.rules),
                      self.rules.hunger_limit(0), True, 0, 0, -1, 0, -1, "")
        return self._spawn_food(s)

    def _closed(self, s: RushState, warned: bool = True) -> bytearray:
        """Walls, plus the '+' cells shown now (food never spawns on a cell about to become wall)."""
        w = bytearray(s.walls)
        if warned:
            for c, _ in s.warned():
                w[c] = 1
        return w

    def _spawn_food(self, s: RushState) -> RushState:
        R = self.rules
        w = self._closed(s)
        occ = set(s.body)
        free = [c for c in range(N * N) if not w[c] and c not in occ]
        if not free:
            return replace(s, food=-1, poison=-1)
        cc = core(w, R.wrap)
        free = [c for c in free if c in cc] or free
        blocked = set(s.body[1:]) | {c for c in range(N * N) if w[c]}
        dist = bfs_dist(s.head, blocked, R.wrap)
        hi = max(3, R.pos(s.tick + R.hunger_limit(s.tick) - 4) - R.pos(s.tick))
        fair = [c for c in free if 2 <= dist[c] <= hi]
        cand = fair or [c for c in free if dist[c] >= 1] or free
        k = s.k + 1
        s = replace(s, food=cand[draw(s.seed, SALT_FOOD, k, len(cand))], k=k)
        return self._spawn_poison(s) if R.poison else s

    def _spawn_poison(self, s: RushState) -> RushState:
        """Poison: a free cell next to the food (4-neighbour), not next to the head, keeping the open cells
        connected and the food in the 2-core; else none."""
        R = self.rules
        w = self._closed(s)
        occ = set(s.body) | {s.food}
        near = [n for n in NB[R.wrap][s.food] if n >= 0 and not w[n] and n not in occ
                and n not in NB[R.wrap][s.head]]
        cand = []
        for c in near:
            w[c] = 1
            if _connected(w) and s.food in core(w, R.wrap):
                cand.append(c)
            w[c] = 0
        if not cand:
            return replace(s, poison=-1)
        k = s.k + 1
        return replace(s, poison=cand[draw(s.seed, SALT_POISON, k, len(cand))], k=k)

    # ------------------------------------------------------------ protocol

    def queries(self, s: RushState, player: int, answers: dict[str, str]) -> list[Query]:
        if "move" in answers or self.done(s):
            return []
        return [Query(0, "move", self.observation(s), DNAME, DNAME[s.dir])]

    def multi_query(self, s: RushState, player: int = 0):
        """Chord form of the same state: the observation without the final 'Choose your move.' line, one slot."""
        from nagi.burst2._rt.arena.chord import MultiQuery
        if self.done(s):
            return None
        text = self.observation(s).rsplit("\n", 1)[0]
        return MultiQuery(0, text, (("move", DNAME, DNAME[s.dir]),))

    def step(self, s: RushState, actions: dict[int, dict[str, str]], dt_ms: int) -> tuple[RushState, list[Event]]:
        if self.done(s):
            return s, []
        R, t0 = self.rules, s.tick
        tick = t0 + 1
        t_ms = tick * TICK_MS
        a = actions.get(0, {}).get("move")
        d = DNAME.index(a) if a in legal(s.heading) else s.dir     # straight back (or invalid) keeps the last one
        ev, ate = [], 0
        n_cells = R.cells(t0)
        ns = replace(s, dir=d, heading=d if n_cells else s.heading)
        hot = {c for c, _ in s.warned()} if R.hot_warn else set()
        for step_i in range(n_cells):
            nxt = NB[R.wrap][ns.head][d]
            cause = ("edge" if nxt < 0 else "wall" if (ns.walls[nxt] or nxt in hot)
                     else "self" if (nxt in ns.solid() and not R.ghost)
                     else "poison" if (R.poison and nxt == ns.poison) else "")
            if cause:
                hx, hy = xy(ns.head)
                cell = list(xy(nxt)) if nxt >= 0 else [hx + DIRS[d][0], hy + DIRS[d][1]]
                ns = replace(ns, tick=tick, alive=False, died_tick=tick, cause=cause)
                ev.append(Event(t_ms, "eliminated", 0, {"cause": cause, "cell": cell, "level": level(t0),
                                                        "t_fail_ms": tick * TICK_MS}))
                return ns, ev + [self._end_event(ns, t_ms)]
            body, grow = (nxt,) + ns.body, ns.grow
            if grow > 0:
                grow -= 1
            else:
                body = body[:-1]
            ns = replace(ns, body=body, grow=grow)
            if nxt == ns.food:
                ate += 1
                streak = ns.streak + 1 if ns.last_eat >= 0 and t0 - ns.last_eat <= 12 else 1
                ns = replace(ns, eaten=ns.eaten + 1, grow=grow + R.growth, streak=streak, last_eat=t0)
                ns = self._spawn_food(ns)
                ev.append(Event(t_ms, "eat", 0, {"cell": list(xy(nxt)), "length": len(body) + ns.grow,
                                                 "streak": streak, "eaten": ns.eaten, "sub": step_i}))
        ns = replace(ns, tick=tick)
        limit = R.hunger_limit(tick)
        if ate:
            ns = replace(ns, hunger=limit)
        else:
            ns = replace(ns, hunger=min(ns.hunger - 1, limit))
            if ns.hunger <= 0:
                ns = replace(ns, hunger=0, alive=False, died_tick=tick, cause="starved")
                ev.append(Event(t_ms, "eliminated", 0, {"cause": "starved", "cell": list(xy(ns.head)),
                                                        "level": level(t0), "t_fail_ms": tick * TICK_MS}))
                return ns, ev + [self._end_event(ns, t_ms)]
        if ns.hunger in (8, 4) and not ate:
            ev.append(Event(t_ms, "hunger_warn", 0, {"left": ns.hunger}))
        # scheduled walls: every due cell not under the snake becomes wall now (deferred cells wait)
        built, keep, occ = [], [], set(ns.body)
        for due, c in ns.sched:
            if due <= tick and c not in occ:
                built.append(c)
            else:
                keep.append((due, c))
        if built:
            w = bytearray(ns.walls)
            for c in built:
                w[c] = 1
            ns = replace(ns, walls=bytes(w), sched=tuple(keep))
            ev.append(Event(t_ms, "wall", 0, {"cells": [list(xy(c)) for c in built]}))
            if ns.food in built or ns.poison in built:
                ns = self._spawn_food(ns)
        new_warn = [c for due, c in ns.sched if due - tick == WARN]
        if new_warn:
            ev.append(Event(t_ms, "wall_warn", 0, {"cells": [list(xy(c)) for c in new_warn]}))
        if tick % LEVEL_TICKS == 0 and tick < T_CAP:
            ev.append(Event(t_ms, "level", None, {"level": level(tick)}))
        if self.done(ns):
            ev.append(self._end_event(ns, t_ms))
        return ns, ev

    def _end_event(self, s: RushState, t: int) -> Event:
        reason = s.cause if not s.alive else "board_full" if s.food < 0 else "cap"
        return Event(t, "round_end", None, {"ranking": [[0]], "reason": reason, "eaten": s.eaten,
                                           "survival_s": survival_s(s), "level_at_fail": level_at_fail(s),
                                           "censored": censored(s)})

    def done(self, s: RushState) -> bool:
        return not s.alive or s.tick >= T_CAP or s.food < 0

    def ranking(self, s: RushState) -> list[list[int]]:
        return [[0]]

    # ------------------------------------------------------------ observation

    def items(self, s: RushState, B: Rules | None = None) -> list[int]:
        """Cells the rules `B` call plain food. A reader of the base rules sees the poison as food '*'."""
        B = self.belief if B is None else B
        return sorted(c for c in (s.food, -1 if B.poison else s.poison) if c >= 0)

    def sensor(self, s: RushState, opt: str, B: Rules | None = None) -> tuple[str, tuple]:
        """(text, sort key) of one option judged on the current board under rules `B` (default: the text's): the
        cells the move covers this tick (B's speed), then 'crash (edge|wall|body)' or 'area A, food D'."""
        B = self.belief if B is None else B
        d = DNAME.index(opt)
        body, grow, head = s.body, s.grow, s.head
        hot = {c for c, _ in s.warned()} if B.hot_warn else set()
        for _ in range(B.next_move(s.tick)[1]):
            nxt = NB[B.wrap][head][d]
            solid = set() if B.ghost else set(body if grow > 0 else body[:-1])
            if nxt < 0 or s.walls[nxt] or nxt in hot or nxt in solid:
                why = "edge" if nxt < 0 else "wall" if (s.walls[nxt] or nxt in hot) else "body"
                return f"crash ({why})", (0,)
            body = (nxt,) + body
            if grow > 0:
                grow -= 1
            else:
                body = body[:-1]
            head = nxt
            if nxt in self.items(s, B):
                break
        blocked = (set() if B.ghost else set(body[1:])) | {c for c in range(N * N) if s.walls[c]} | hot
        area = flood(head, blocked, B.wrap)
        dist = bfs_dist(head, blocked, B.wrap)
        items = self.items(s, B)
        if head in items:
            fd = 0
        else:
            ds = [dist[c] for c in items if dist[c] >= 0]
            fd = min(ds) if ds else None
        txt = f"area {area}, food {'-' if fd is None else fd}"
        bad = B.poison and head == s.poison
        if bad:
            txt += ", eats poison"
        return txt, (1, not bad, area, -(fd if fd is not None else 10 ** 6))

    def sensor_top(self, s, q, answers: dict) -> str | None:
        best, key = None, None
        for o in q.options:
            k = self.sensor(s, o)[1]
            if key is None or k > key:
                best, key = o, k
        return best

    def observation(self, s: RushState) -> str:
        B = self.belief
        grid = ["#" if s.walls[c] else "." for c in range(N * N)]
        for c, _ in s.warned():
            grid[c] = "+"
        for c in self.items(s, B):
            grid[c] = "*"
        if B.poison and s.poison >= 0:
            grid[s.poison] = "x"
        for i, c in enumerate(s.body):
            grid[c] = "H" if i == 0 else "t" if i == len(s.body) - 1 else "o"
        legend = "H head, o body, t tail, * food, # wall, + wall soon, . free" + (", x poison" if B.poison else "")
        hx, hy = xy(s.head)

        def where(c):
            fx, fy = xy(c)
            off = [f"{abs(fx - hx)} {'right' if fx > hx else 'left'}" if fx != hx else "same column",
                   f"{abs(fy - hy)} {'down' if fy > hy else 'up'}" if fy != hy else "same row"]
            return f"({fx},{fy}): {', '.join(off)}"

        t = s.tick
        nxt_cells = B.cells(t)
        mv_t, mv_cells = B.next_move(t)
        move_txt = (f"This move: {nxt_cells} cell{'s' if nxt_cells > 1 else ''}" if nxt_cells else
                    f"This tick waits; next move: {mv_cells} cell" + ("s" if mv_cells > 1 else ""))
        nxt_dir = f" (next {DNAME[s.dir]})" if s.dir != s.heading else ""
        soon = sorted(s.warned(), key=lambda cw: (cw[1], cw[0]))
        lines = [self.rules_text, f"Map ({legend}):", *("".join(grid[y * N:(y + 1) * N]) for y in range(N)),
                 f"Time {t * TICK_MS / 1000:g} s (tick {t}), level {level(t)}. Hunger {s.hunger} ticks left "
                 f"(limit {B.hunger_limit(t)}). {move_txt}.",
                 f"Length {len(s.body)}, growing {s.grow}, heading {DNAME[s.heading]}{nxt_dir}. Food eaten {s.eaten}.",
                 f"Head ({hx},{hy}). Food " + " and ".join(where(c) for c in self.items(s, B)) + "."]
        if B.poison and s.poison >= 0:
            lines.append(f"Poison {where(s.poison)}.")
        if soon:
            lines.append("Walls soon: " + ", ".join(f"({xy(c)[0]},{xy(c)[1]}) in {max(dd, 0)}" for c, dd in soon[:6])
                         + (f" (+{len(soon) - 6} more)" if len(soon) > 6 else "") + " ticks.")
        if self.sensors:
            lines.append("Sensors (area = free cells reachable after the move; food = steps, - = no path):")
            lines += [f"{o}: {self.sensor(s, o)[0]}" for o in legal(s.heading)]
        lines.append("Choose your move.")
        return "\n".join(lines)

    # ------------------------------------------------------------ renderer / hashing

    def render_state(self, s: RushState) -> dict:
        R = self.rules
        return {"grid": N, "tick": s.tick, "t_ms": s.tick * TICK_MS, "level": level(s.tick),
                "walls": [c for c in range(N * N) if s.walls[c]], "body": [list(xy(c)) for c in s.body],
                "heading": s.heading, "food": list(xy(s.food)) if s.food >= 0 else None,
                "poison": list(xy(s.poison)) if s.poison >= 0 else None,
                "warn": [[*xy(c), dd] for c, dd in s.warned()], "hunger": s.hunger,
                "hunger_limit": R.hunger_limit(s.tick), "cells_next": R.cells(s.tick), "dir": s.dir,
                "speed": R.vel(s.tick) / 1000,
                "alive": s.alive, "cause": s.cause, "eaten": s.eaten, "streak": s.streak, "grow": s.grow,
                "died_tick": s.died_tick, "survival_s": survival_s(s), "level_at_fail": level_at_fail(s),
                "censored": censored(s), "points": s.eaten}

    def state_hash(self, s: RushState) -> str:
        blob = [s.seed, s.tick, list(s.body), s.heading, s.grow, s.food, s.poison, s.walls.hex(),
                [list(x) for x in s.sched], s.hunger, s.alive, s.eaten, s.streak, s.last_eat, s.k, s.died_tick,
                s.cause, s.dir]
        return hashlib.sha256(json.dumps(blob, separators=(",", ":")).encode()).hexdigest()


# ---------------------------------------------------------------- seeds and cross-platform hash

SEED_PREFIX = "arena-v3|snake_rush"
SPLITS = ("calib", "eval", "dev", "variant_dev", "variant_sealed")


def seeds(split: str, n: int = 24) -> list[int]:
    assert split in SPLITS, split
    return [int(hashlib.sha256(f"{SEED_PREFIX}|{split}|{i}".encode()).hexdigest(), 16) % (2 ** 31) for i in range(n)]


def hash_steps(n_steps: int = 1000) -> str:
    """sha256 over the state hashes of n_steps ticks: rounds on seeds 0, 1, ... cycling base + every variant, played
    by the L1 sensor argmax with a splitmix64 deviation every 7th tick. Compare this value across platforms."""
    h, steps, i, order = hashlib.sha256(), 0, 0, [None, *VARIANTS]
    while steps < n_steps:
        g = SnakeRush(order[i % len(order)])
        s = g.reset(i)
        h.update(g.state_hash(s).encode())
        while not g.done(s) and steps < n_steps:
            q = g.queries(s, 0, {})[0]
            mv = q.options[draw(i, SALT_POLICY, s.tick, 4)] if s.tick % 7 == 6 else g.sensor_top(s, q, {})
            s, _ = g.step(s, {0: {"move": mv}}, TICK_MS)
            h.update(g.state_hash(s).encode())
            steps += 1
        i += 1
    return h.hexdigest()
