"""G1 LIGHTCYCLE ROYALE: 4-player Tron light cycles on a shrinking, 4-fold symmetric arena (DESIGN.md §1 G1).

Exact rules (the rules text sent to every model is RULES below; it states the same thing in short form):

* Board. 48x48 cells, x to the right, y downward; outside the board is wall. Obstacles: one quadrant
  (x, y < 24) is drawn from random.Random(seed) as short straight segments, then copied by the 90-degree
  rotation R(x, y) = (47 - y, x) three times, so the layout is exactly R-invariant. Player p spawns at
  R^p(23, 44) with heading R^p(up): p0 bottom facing up, p1 left facing right, p2 top facing down,
  p3 right facing left. A 6-wide corridor from each spawn to 14 cells ahead (and its rotations) is
  cleared of obstacles. Every cycle's own spawn cell is its first trail cell.
* Decision. Every 125 ms of game time each living player gets one Query, key 'move', options
  ('straight', 'left', 'right', 'boost_straight', 'boost_left', 'boost_right'), default 'straight'
  (late or invalid replies apply it). Turns are relative to the cycle's own heading; the new heading
  applies to all cells moved this tick.
* Boost. A boost_* move with >= 1 charge costs 1 charge and moves 2 cells this tick; with 0 charges it
  is the normal move in that direction (no charge, no 'boost' event). The meter starts full at 3,
  holds at most 3, and every living player gains +1 charge whenever game time reaches a multiple of
  2000 ms (after that tick's moves).
* Movement and collisions, simultaneous. A tick has two sub-steps: in sub-step 1 every living player
  moves 1 cell; in sub-step 2 only the players that spent a boost charge move their 2nd cell, the
  others stand still. Inside a sub-step all movers' target cells are judged against the board as it
  was at the start of that sub-step (every trail cell including every head, dead players' trails,
  obstacles, rings closed before this tick, outside). A mover dies, cause in this priority:
  'head_on' if it and another mover swap cells; 'wall' if the target is outside, an obstacle or a
  closed ring; 'trail_of_<q>' if the target is on player q's trail or head (q may be itself);
  'head_on' if two or more movers target the same free cell (all of them die). Surviving movers then
  occupy their target. A dead player stops, its trail stays as an obstacle, and it is not queried.
* Shrink. rings_closed(t) = 0 for t < 15000 ms, 1 + (t - 15000) // 1000 for 15000 <= t < 35000, and 24
  (the whole board) from 35000. Ring k is closed when every cell with min(x, y, 47-x, 47-y) < k is
  wall (same as Chebyshev distance from the centre >= 24 - k). After a tick's moves, any living cycle
  whose head is in a newly closed cell dies with cause 'shrink'; moving into an already closed cell
  is 'wall'. At 35000 ms the remaining 8x8 core closes, so every round ends by max_round_ms.
* End and ranking. The round is done when <= 1 player is alive. Ranking is elimination order, later
  is better; players eliminated in the same tick are tied; players still alive (if the Referee cap
  hits first) are tied first.
* Events (t_ms = time after the tick): 'boost' {charges_left}; 'eliminated' {cause, cell};
  'near_miss' {blocked_by} when a player turned (left/right, boosted or not), survived the tick, and
  the cell straight ahead of its old heading was blocked at the start of the tick (it dodged by one
  cell); 'shrink' {ring} when rings_closed increases; 'round_end' {ranking}.
* Observation (egocentric, rotated so the own heading is up, no absolute coordinates): a 15x15 window
  centred on the own head ('^'), rows from 7 ahead down to 7 behind, '.' free, '#' blocked (wall,
  obstacle, closed ring, any trail, dead head), '1'-'3' living opponent heads; opponent n is seat
  (p + n) % 4. Then own charges, ms until the next ring closes, each opponent's head vector
  (R = cells to the right, F = cells ahead) with heading relative to yours, and L1 sensors per
  option judged against the current board (ignoring other players' simultaneous moves): 'crash' if
  the move itself enters a blocked cell, else 'run' = free cells straight ahead of the resulting head
  and 'area' = cells reachable from it by 4-neighbour flood fill (capped at 400).
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from functools import lru_cache

from nagi.burst2._rt.arena.core import Event, Query

N, W = 48, 50  # board side; padded side (1-cell wall border) used for flat indices
DIRS = ((0, -1), (1, 0), (0, 1), (-1, 0))  # up, right, down, left: clockwise, y grows downward
DNAME = ("up", "right", "down", "left")
REL = ("same as you", "to your right", "toward your back", "to your left")
STEP = tuple(dx + dy * W for dx, dy in DIRS)
OPTIONS = ("straight", "left", "right", "boost_straight", "boost_left", "boost_right")
TURN = {"straight": 0, "left": 3, "right": 1}
SHRINK_START, SHRINK_EVERY, CLOSE_MS = 15000, 1000, 35000
BOOST_MAX, RECHARGE_MS = 3, 2000
VIEW, AREA_CAP = 7, 400
SPAWN = (23, 44)

RULES = ("LIGHTCYCLE ROYALE: 4 cycles, 48x48 arena. Every 125 ms all players choose at once. Moves are "
         "relative to your heading. boost_* moves 2 cells and costs 1 charge (max 3, +1 every 2 s); with "
         "0 charges it is a normal move. Cycles leave solid trails. You die entering a wall, obstacle, "
         "any trail or the edge; heads entering one cell or swapping all die. From 15 s the outer ring "
         "becomes wall every 1 s (cycles on it die); at 35 s all is wall. Last alive wins; ties if out "
         "together. Late/invalid reply = straight.")


def idx(x: int, y: int) -> int:
    return (y + 1) * W + x + 1


def xy(i: int) -> tuple[int, int]:
    return i % W - 1, i // W - 1


def rot(x: int, y: int) -> tuple[int, int]:
    return N - 1 - y, x


RING = tuple(min(x, y, N - 1 - x, N - 1 - y) if 0 <= x < N and 0 <= y < N else -1
             for x, y in map(xy, range(W * W)))


def rings_closed(t: int) -> int:
    if t < SHRINK_START:
        return 0
    return N // 2 if t >= CLOSE_MS else 1 + (t - SHRINK_START) // SHRINK_EVERY


def next_ring_ms(t: int) -> int:
    return SHRINK_START - t if t < SHRINK_START else SHRINK_EVERY - (t - SHRINK_START) % SHRINK_EVERY


@lru_cache(maxsize=None)
def _ring_mask(k: int) -> int:
    return int.from_bytes(bytes(1 if r < k else 0 for r in RING), "big")


@dataclass
class LCState:
    t: int
    obst: bytes  # padded grid, 1 = obstacle (static for the round)
    own: bytearray  # padded grid, p + 1 = trail or head of player p, 0 = none
    head: list[int]  # padded indices
    dir: list[int]  # index into DIRS
    alive: list[bool]
    charges: list[int]
    out: list[list[int]]  # elimination tiers, first out first
    new: list[list[int]]  # cells each player entered during the last tick

    def blocked(self) -> bytes:
        v = int.from_bytes(self.obst, "big") | int.from_bytes(self.own, "big") | _ring_mask(rings_closed(self.t))
        return v.to_bytes(W * W, "big")


def make_obstacles(seed: int) -> bytes:
    rng, quad = random.Random(seed), set()
    for _ in range(rng.randint(6, 10)):
        x, y = rng.randrange(2, 22), rng.randrange(2, 22)
        dx, dy = rng.choice(DIRS)
        for _ in range(rng.randint(2, 7)):
            if 0 <= x < N // 2 and 0 <= y < N // 2:
                quad.add((x, y))
            x, y = x + dx, y + dy
    clear = {(x, y) for x in range(21, 27) for y in range(SPAWN[1] - 14, N)}
    grid = bytearray(W * W)
    for cells, value in ((quad, 1), (clear, 0)):
        for c in cells:
            for _ in range(4):
                grid[idx(*c)] = value
                c = rot(*c)
    return bytes(grid)


class Lightcycle:
    id, n_players, decision_period_ms, max_round_ms = "lightcycle", 4, 125, CLOSE_MS

    def reset(self, seed: int) -> LCState:
        own, heads, c = bytearray(W * W), [], SPAWN
        for p in range(4):
            heads.append(idx(*c))
            own[heads[-1]] = p + 1
            c = rot(*c)
        return LCState(0, make_obstacles(seed), own, heads, [0, 1, 2, 3], [True] * 4, [BOOST_MAX] * 4,
                       [], [[h] for h in heads])

    # ------------------------------------------------------------ observation

    def queries(self, s: LCState, player: int, answers: dict[str, str]) -> list[Query]:
        if "move" in answers or not s.alive[player]:
            return []
        return [Query(player, "move", self.observation(s, player), OPTIONS, "straight")]

    def observation(self, s: LCState, p: int) -> str:
        blk, d = s.blocked(), s.dir[p]
        hx, hy = xy(s.head[p])
        (fx, fy), (rx, ry) = DIRS[d], DIRS[(d + 1) % 4]
        heads = {s.head[q]: str((q - p) % 4) for q in range(4) if q != p and s.alive[q]}
        rows = []
        for f in range(VIEW, -VIEW - 1, -1):
            row = ""
            for r in range(-VIEW, VIEW + 1):
                x, y = hx + f * fx + r * rx, hy + f * fy + r * ry
                i = idx(x, y)
                row += ("#" if not (0 <= x < N and 0 <= y < N) else "^" if (f, r) == (0, 0)
                        else heads.get(i) or ("#" if blk[i] else "."))
            rows.append(row)
        opp = []
        for n in (1, 2, 3):
            q = (p + n) % 4
            if not s.alive[q]:
                opp.append(f"{n}: out")
                continue
            dx, dy = xy(s.head[q])[0] - hx, xy(s.head[q])[1] - hy
            opp.append(f"{n}: R{dx * rx + dy * ry:+d} F{dx * fx + dy * fy:+d}, heading {REL[(s.dir[q] - d) % 4]}")
        sens = [f"{o}: {self._sensor(blk, s.head[p], d, o, s.charges[p])}" for o in OPTIONS]
        k = rings_closed(s.t)
        return "\n".join([RULES, "Map (you ^ facing up; top row = 7 ahead; . free # blocked 1-3 opponents):",
                          *rows, f"Boost charges: {s.charges[p]}/{BOOST_MAX}. Rings closed: {k}. "
                          f"Next ring closes in {next_ring_ms(s.t)} ms.",
                          "Opponents (R right, F ahead):", *opp,
                          "Sensors per move (run = free cells straight on, area = reachable cells, cap 400):",
                          *sens, "Choose your move."])

    @staticmethod
    def _sensor(blk: bytes, h: int, d: int, opt: str, charges: int) -> str:
        nd = (d + TURN[opt.removeprefix("boost_")]) % 4
        path = [h + STEP[nd]]
        if opt.startswith("boost_") and charges > 0 and not blk[path[0]]:
            path.append(path[0] + STEP[nd])
        if any(blk[c] for c in path):
            return "crash"
        end, run = path[-1], 0
        while not blk[end + (run + 1) * STEP[nd]]:
            run += 1
        seen, stack = {h, *path}, [end]
        base = len(seen)
        while stack and len(seen) - base < AREA_CAP:
            c = stack.pop()
            for st in STEP:
                n = c + st
                if n not in seen and not blk[n]:
                    seen.add(n)
                    stack.append(n)
        return f"run {run}, area {min(AREA_CAP, len(seen) - base)}"

    # ------------------------------------------------------------ physics

    def step(self, s: LCState, actions: dict[int, dict[str, str]], dt_ms: int) -> tuple[LCState, list[Event]]:
        t, k0 = s.t + dt_ms, rings_closed(s.t)
        own, head, dirs = bytearray(s.own), list(s.head), list(s.dir)
        alive, charges, new = list(s.alive), list(s.charges), [[] for _ in range(4)]
        blk0, events, dead, boost, dodged = s.blocked(), [], {}, set(), {}
        for p in range(4):
            if not alive[p]:
                continue
            opt = actions.get(p, {}).get("move", "straight")
            opt = opt if opt in OPTIONS else "straight"
            base = opt.removeprefix("boost_")
            if base != "straight" and blk0[head[p] + STEP[dirs[p]]]:
                dodged[p] = head[p] + STEP[dirs[p]]
            dirs[p] = (dirs[p] + TURN[base]) % 4
            if opt != base and charges[p] > 0:
                charges[p] -= 1
                boost.add(p)
                events.append(Event(t, "boost", p, {"charges_left": charges[p]}))
        for sub in (1, 2):
            movers = [p for p in range(4) if alive[p] and p not in dead and (sub == 1 or p in boost)]
            tgt = {p: head[p] + STEP[dirs[p]] for p in movers}
            for p in movers:
                c = tgt[p]
                if any(tgt[q] == head[p] and c == head[q] for q in movers if q != p):
                    dead[p] = "head_on"
                elif RING[c] < k0 or s.obst[c]:
                    dead[p] = "wall"
                elif own[c]:
                    dead[p] = f"trail_of_{own[c] - 1}"
                elif any(tgt[q] == c for q in movers if q != p):
                    dead[p] = "head_on"
            for p in movers:
                if p not in dead:
                    head[p] = tgt[p]
                    own[tgt[p]] = p + 1
                    new[p].append(tgt[p])
        k1 = rings_closed(t)
        for p in range(4):
            if alive[p] and p not in dead and RING[head[p]] < k1:
                dead[p] = "shrink"
        if k1 > k0:
            events.append(Event(t, "shrink", None, {"ring": k1}))
        for p in sorted(dead):
            alive[p] = False
            cell = head[p] + STEP[dirs[p]] if dead[p] != "shrink" else head[p]
            events.append(Event(t, "eliminated", p, {"cause": dead[p], "cell": list(xy(cell))}))
        if t % RECHARGE_MS == 0:
            charges = [min(BOOST_MAX, c + 1) if a else c for c, a in zip(charges, alive)]
        for p, c in sorted(dodged.items()):
            if alive[p]:
                o = s.own[c]
                events.append(Event(t, "near_miss", p, {"blocked_by": f"trail_of_{o - 1}" if o else "wall"}))
        ns = LCState(t, s.obst, own, head, dirs, alive, charges, s.out + ([sorted(dead)] if dead else []), new)
        if self.done(ns):
            events.append(Event(t, "round_end", None, {"ranking": self.ranking(ns)}))
        return ns, events

    def done(self, s: LCState) -> bool:
        return sum(s.alive) <= 1

    def ranking(self, s: LCState) -> list[list[int]]:
        alive = [p for p in range(4) if s.alive[p]]
        return ([alive] if alive else []) + [list(tier) for tier in reversed(s.out)]

    # ------------------------------------------------------------ renderer / hashing

    def render_state(self, s: LCState) -> dict:
        return {"grid": N, "t_ms": s.t, "ring": rings_closed(s.t),
                "obstacles": [xy(i)[1] * N + xy(i)[0] for i in range(W * W) if s.obst[i]],
                "players": [{"head": list(xy(s.head[p])), "heading": DNAME[s.dir[p]], "alive": s.alive[p],
                             "boost": s.charges[p], "new": [list(xy(c)) for c in s.new[p]]} for p in range(4)]}

    def state_hash(self, s: LCState) -> str:
        blob = {"t": s.t, "obst": s.obst.hex(), "own": s.own.hex(), "head": s.head, "dir": s.dir,
                "alive": s.alive, "charges": s.charges, "out": s.out, "new": s.new}
        return hashlib.sha256(json.dumps(blob, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
