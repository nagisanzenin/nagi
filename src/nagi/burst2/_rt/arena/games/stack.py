"""G3 STACK ATTACK: 4-player Tetris battle for Arena Live (docs/arena_live/DESIGN.md §1 G3, §2, §4).

Rules (the complete, authoritative list; RULES_TEXT below is the compact version sent to models):

* Boards. Four boards, each 10 columns x 20 visible rows plus 2 hidden spawn rows (rows 20..21,
  0-indexed from the bottom). A block in a hidden row means that board has topped out.
* Pieces. The standard 7 tetrominoes I J L O S T Z with Guideline SRS orientations (0, R, 2, L =
  spawn, clockwise, 180, counter-clockwise; each state is a true rotation of the spawn cells inside
  the SRS bounding box: 4x4 for I, 3x3 for J L S T Z, O never changes). ONE 7-bag sequence is drawn
  from random.Random(seed) and every board plays that identical sequence.
* Decision. Every 250 ms of game time (decision_period_ms) every alive board places exactly one
  piece, chosen in two simultaneous stages of the same decision point:
    1. key 'rotation': options are the DISTINCT orientations of the current piece in the canonical
       order rot0, rotR, rot2, rotL (orientations whose normalised cell sets repeat an earlier one are
       dropped: I, S, Z -> rot0, rotR; J, L, T -> all four). Default rot0 (spawn orientation).
       The O piece has one orientation, so stage 1 is skipped and only 'column' is asked.
    2. key 'column': options 'c0'..'cK' in ascending order = every left-edge column at which the
       chosen orientation fits inside the 10 columns. Default = the spawn column of that orientation
       (SRS box spawned at column 3, i.e. the column the piece occupies when rotated in place at
       spawn), clamped into the valid range.
  The piece is then hard-dropped straight down from above the board at that rotation and column
  (no spins, no kicks, no hold). A missing, late or invalid reply applies the default, the same rule
  for everyone ("spawn-column drop").
* Line clears. Full rows are removed. Clearing n lines sends GARBAGE_TABLE[n] = {1:0, 2:1, 3:2, 4:4}
  garbage rows to EVERY other board that is still alive after this decision's placements (no
  targeting, no cancelling of own pending garbage). Garbage received is queued as "pending" and is
  applied right after that board's NEXT placement (next decision point), as one batch of rows that
  all share one hole column. The hole column is random.Random(f"{seed}:garbage:{k}") where k is the
  number of garbage batches this receiver has already taken: a function of (seed, receiver's count)
  only, never of the sender or of the slot.
* Pressure. From 30 s on, every 10 s all alive boards simultaneously receive pressure rows: the
  k-th pressure event (at 30 + 10k s) adds k+1 rows (1, 2, 3, 4, 5, 6 at 30..80 s), sharing one hole
  column random.Random(f"{seed}:pressure:{k}"), identical for all boards. Pressure is applied after
  that decision's placements and pending garbage.
* Top out. A board is eliminated when, after its placement and line clears, or after incoming
  garbage/pressure pushes the stack up, any block lies above row 20 (in the hidden rows). A piece
  whose drop would lock outside the 22-row field also tops out. Boards eliminated at the same
  decision point are tied.
* Level. level = 1 + t // 10 s, a pace display only; the real pressure is garbage + pressure rows.
* End and ranking. The round ends when <= 1 board is alive, or at the 90 s cap (max_round_ms).
  Ranking: alive boards first (grouped by lines sent, more is better, equal counts tie), then
  eliminated boards by elimination time (later is better), simultaneous eliminations tied.
  Pressure rows have holes, so the hard termination guarantee is the 90 s cap; random/stall play
  ends far earlier.

Observation (<= ~2000 chars): rules, own board (20 rows, '#' filled, '.' empty, top row first),
column heights, holes, current piece with every rotation option drawn as small ascii, next 3
pieces, own pending garbage, next pressure time, and per rival (listed in relative order
rival1..rival3 = the next slots clockwise) max height, pending garbage and alive. Stage 2 adds the
chosen rotation and the L1 shared sensors: for each column option, (lines cleared, max height,
holes) right after that drop (before pending garbage), identical code for every model.
"""

from __future__ import annotations

import copy
import random
from dataclasses import asdict, dataclass, field

from nagi.burst2._rt.arena.core import Event, Query, canonical_hash

W, H, HIDDEN = 10, 20, 2
H_TOTAL = H + HIDDEN
PIECES = "IJLOSTZ"
ROT_NAMES = ("rot0", "rotR", "rot2", "rotL")
GARBAGE_TABLE = {0: 0, 1: 0, 2: 1, 3: 2, 4: 4}
SPAWN_BOX_COL = 3
PRESSURE_START_MS, PRESSURE_EVERY_MS = 30000, 10000

# SRS spawn states in bounding-box coordinates (x right, y DOWN), box size per piece.
_SPAWN = {
    "I": (4, ((0, 1), (1, 1), (2, 1), (3, 1))),
    "J": (3, ((0, 0), (0, 1), (1, 1), (2, 1))),
    "L": (3, ((2, 0), (0, 1), (1, 1), (2, 1))),
    "O": (4, ((1, 0), (2, 0), (1, 1), (2, 1))),
    "S": (3, ((1, 0), (2, 0), (0, 1), (1, 1))),
    "T": (3, ((1, 0), (0, 1), (1, 1), (2, 1))),
    "Z": (3, ((0, 0), (1, 0), (1, 1), (2, 1))),
}


def _srs_states(piece: str) -> list[frozenset]:
    """The 4 SRS states (0, R, 2, L) as box-coordinate cell sets (y down). O is rotation-invariant."""
    n, cells = _SPAWN[piece]
    if piece == "O":
        return [frozenset(cells)] * 4
    out, cur = [], list(cells)
    for _ in range(4):
        out.append(frozenset(cur))
        cur = [(n - 1 - y, x) for x, y in cur]  # clockwise rotation inside the box
    return out


SRS_STATES = {p: _srs_states(p) for p in PIECES}


def _normalise(cells) -> tuple:
    mx, my = min(x for x, _ in cells), min(y for _, y in cells)
    return tuple(sorted((x - mx, y - my) for x, y in cells))


def _build_orientations():
    """piece -> list of (rot_name, cells bottom-up (dx, dy>=0 up), width, spawn_left_col)."""
    table = {}
    for p in PIECES:
        seen, lst = set(), []
        for name, st in zip(ROT_NAMES, SRS_STATES[p]):
            norm = _normalise(st)
            if norm in seen:
                continue
            seen.add(norm)
            hgt = max(y for _, y in norm) + 1
            cells = tuple(sorted((x, hgt - 1 - y) for x, y in norm))  # flip to y up
            width = max(x for x, _ in norm) + 1
            spawn = SPAWN_BOX_COL + min(x for x, _ in st)
            lst.append((name, cells, width, spawn))
        table[p] = lst
    return table


ORIENTATIONS = _build_orientations()


def rotation_options(piece: str) -> tuple[str, ...]:
    return tuple(o[0] for o in ORIENTATIONS[piece])


def _orient(piece: str, rot: str):
    for o in ORIENTATIONS[piece]:
        if o[0] == rot:
            return o
    return ORIENTATIONS[piece][0]


def column_options(piece: str, rot: str) -> tuple[str, ...]:
    return tuple(f"c{c}" for c in range(W - _orient(piece, rot)[2] + 1))


def default_column(piece: str, rot: str) -> str:
    _, _, width, spawn = _orient(piece, rot)
    return f"c{max(0, min(W - width, spawn))}"


def shape_ascii(piece: str, rot: str) -> str:
    _, cells, width, _ = _orient(piece, rot)
    hgt = max(y for _, y in cells) + 1
    rows = []
    for y in range(hgt - 1, -1, -1):
        rows.append("".join("x" if (x, y) in cells else "." for x in range(width)))
    return "/".join(rows)


# ---------------------------------------------------------------- board mechanics (pure helpers)


def drop(rows: list[int], piece: str, rot: str, col: int):
    """Hard drop. Returns (new_rows, lines_cleared, topped_out). rows: bottom-first bitmasks, len H_TOTAL."""
    _, cells, _, _ = _orient(piece, rot)

    def fits(y0):
        for dx, dy in cells:
            y = y0 + dy
            if y < 0:
                return False
            if y < H_TOTAL and rows[y] >> (col + dx) & 1:
                return False
        return True

    y0 = H_TOTAL  # start fully above the field
    while y0 > 0 and fits(y0 - 1):
        y0 -= 1
    new = list(rows)
    for dx, dy in cells:
        y = y0 + dy
        if y >= H_TOTAL:
            return new, 0, True  # locks outside the field
        new[y] |= 1 << (col + dx)
    full = (1 << W) - 1
    kept = [r for r in new if r != full]
    n = len(new) - len(kept)
    kept += [0] * n
    return kept, n, any(kept[y] for y in range(H, H_TOTAL))


def push_garbage(rows: list[int], n: int, hole: int):
    """Insert n rows (all cells but `hole`) at the bottom. Returns (new_rows, topped_out)."""
    if n <= 0:
        return list(rows), False
    g = ((1 << W) - 1) & ~(1 << hole)
    allrows = [g] * n + list(rows)
    over = any(allrows[H:])
    return allrows[:H_TOTAL], over


def heights(rows: list[int]) -> list[int]:
    hs = []
    for c in range(W):
        h = 0
        for y in range(H_TOTAL - 1, -1, -1):
            if rows[y] >> c & 1:
                h = y + 1
                break
        hs.append(h)
    return hs


def holes(rows: list[int]) -> int:
    hs, n = heights(rows), 0
    for c in range(W):
        n += sum(1 for y in range(hs[c]) if not rows[y] >> c & 1)
    return n


def board_lines(rows: list[int]) -> list[str]:
    return ["".join("#" if rows[y] >> c & 1 else "." for c in range(W)) for y in range(H - 1, -1, -1)]


def _garbage_hole(seed: int, k: int) -> int:
    return random.Random(f"{seed}:garbage:{k}").randrange(W)


def _pressure_hole(seed: int, k: int) -> int:
    return random.Random(f"{seed}:pressure:{k}").randrange(W)


def piece_sequence(seed: int, n: int) -> tuple[str, ...]:
    rng, out = random.Random(seed), []
    while len(out) < n:
        bag = list(PIECES)
        rng.shuffle(bag)
        out += bag
    return tuple(out[:n])


# ---------------------------------------------------------------- state


@dataclass
class Board:
    rows: list[int] = field(default_factory=lambda: [0] * H_TOTAL)
    idx: int = 0  # index of the current piece in the shared sequence
    pending: int = 0
    received: int = 0  # garbage batches applied so far (hole RNG key)
    lines: int = 0
    sent: int = 0
    alive: bool = True
    died_ms: int | None = None


@dataclass
class StackState:
    seed: int
    t_ms: int
    seq: tuple[str, ...]
    boards: list[Board]
    pressure_k: int = 0  # pressure events already applied


RULES_TEXT = (
    "STACK ATTACK: 4-player Tetris battle, everyone gets the same pieces. 10x20 board. Each turn pick "
    "a rotation, then a column (left edge of the piece); the piece hard-drops straight down. Clearing "
    "2/3/4 lines sends 1/2/4 garbage rows to EVERY rival (added under their stack after their next "
    "drop). From 30s, pressure rows rise on all boards every 10s (1,2,3.. rows). A block above row 20 "
    "= you are out. Last board standing wins."
)


class Stack:
    id = "stack"
    n_players = 4
    decision_period_ms = 250
    max_round_ms = 90000

    # ------------------------------------------------------------ protocol

    def reset(self, seed: int) -> StackState:
        n = self.max_round_ms // self.decision_period_ms + 8
        return StackState(seed, 0, piece_sequence(seed, n), [Board() for _ in range(self.n_players)])

    def _piece(self, s: StackState, p: int) -> str:
        return s.seq[s.boards[p].idx]

    def queries(self, s: StackState, player: int, answers: dict[str, str]) -> list[Query]:
        b = s.boards[player]
        if self.done(s) or not b.alive or "column" in answers:
            return []
        piece = self._piece(s, player)
        rots = rotation_options(piece)
        if len(rots) >= 2 and "rotation" not in answers:
            text = self._observation(s, player) + "\nChoose the ROTATION (shapes above, x = block)."
            return [Query(player, "rotation", text, rots, "rot0")]
        rot = answers.get("rotation", "rot0")
        if rot not in rots:
            rot = "rot0"
        opts = column_options(piece, rot)
        text = (self._observation(s, player) + f"\nRotation chosen: {rot} {shape_ascii(piece, rot)}\n"
                + self._sensors(b.rows, piece, rot) + "\nChoose the COLUMN (left edge of the piece).")
        return [Query(player, "column", text, opts, default_column(piece, rot))]

    def step(self, s: StackState, actions: dict[int, dict[str, str]], dt_ms: int):
        s = copy.deepcopy(s)
        t = s.t_ms + dt_ms
        ev: list[Event] = []
        was_done = self.done(s)
        # 1. simultaneous placements
        cleared = {}
        for p, b in enumerate(s.boards):
            if not b.alive:
                continue
            piece = s.seq[b.idx]
            a = actions.get(p, {}) or {}
            rot = a.get("rotation", "rot0")
            if rot not in rotation_options(piece):
                rot = "rot0"
            colid = a.get("column")
            if colid not in column_options(piece, rot):
                colid = default_column(piece, rot)
            rows, n, top = drop(b.rows, piece, rot, int(colid[1:]))
            b.rows, b.idx = rows, b.idx + 1
            b.lines += n
            cleared[p] = n
            if n:
                ev.append(Event(t, "lines_cleared", p, {"n": n}))
                if n == 4:
                    ev.append(Event(t, "tetris", p))
            if top:
                self._kill(b, t, ev, p, "placement")
        # 2. pending garbage (queued before this decision) lands after this placement
        for p, b in enumerate(s.boards):
            if b.alive and b.pending:
                n, hole = b.pending, _garbage_hole(s.seed, b.received)
                b.rows, top = push_garbage(b.rows, n, hole)
                b.pending, b.received = 0, b.received + 1
                ev.append(Event(t, "garbage_in", p, {"n": n, "hole": hole}))
                if top:
                    self._kill(b, t, ev, p, "garbage")
        # 3. sends from this decision's clears go to every other board still alive (queued)
        for p, n in cleared.items():
            g = GARBAGE_TABLE[n]
            if not g:
                continue
            to = [q for q, bq in enumerate(s.boards) if q != p and bq.alive]
            for q in to:
                s.boards[q].pending += g
            s.boards[p].sent += g * len(to)
            ev.append(Event(t, "lines_sent", p, {"n": g, "to": to}))
        # 4. pressure rows, identical for all alive boards
        while t >= PRESSURE_START_MS + PRESSURE_EVERY_MS * s.pressure_k:
            k = s.pressure_k
            n, hole = k + 1, _pressure_hole(s.seed, k)
            s.pressure_k += 1
            ev.append(Event(t, "pressure", None, {"n": n, "hole": hole}))
            for p, b in enumerate(s.boards):
                if b.alive:
                    b.rows, top = push_garbage(b.rows, n, hole)
                    if top:
                        self._kill(b, t, ev, p, "pressure")
        s.t_ms = t
        if not was_done and (self.done(s) or t >= self.max_round_ms):
            ev.append(Event(t, "round_end", None, {"ranking": self.ranking(s)}))
        return s, ev

    @staticmethod
    def _kill(b: Board, t: int, ev: list, p: int, cause: str):
        b.alive, b.died_ms, b.pending = False, t, 0
        ev.append(Event(t, "top_out", p, {"cause": cause}))

    def done(self, s: StackState) -> bool:
        return sum(b.alive for b in s.boards) <= 1

    def ranking(self, s: StackState) -> list[list[int]]:
        alive = [p for p, b in enumerate(s.boards) if b.alive]
        dead = [p for p, b in enumerate(s.boards) if not b.alive]
        out = []
        for v in sorted({s.boards[p].sent for p in alive}, reverse=True):
            out.append([p for p in alive if s.boards[p].sent == v])
        for tm in sorted({s.boards[p].died_ms for p in dead}, reverse=True):
            out.append([p for p in dead if s.boards[p].died_ms == tm])
        return out

    def render_state(self, s: StackState) -> dict:
        return {
            "t_ms": s.t_ms,
            "level": 1 + s.t_ms // 10000,
            "boards": ["".join(board_lines(b.rows)) for b in s.boards],  # 200 chars, top row first
            "current": [s.seq[b.idx] if b.alive else None for b in s.boards],
            "next": [list(s.seq[b.idx + 1:b.idx + 4]) for b in s.boards],
            "pending": [b.pending for b in s.boards],
            "lines": [b.lines for b in s.boards],
            "sent": [b.sent for b in s.boards],
            "alive": [b.alive for b in s.boards],
            "died_ms": [b.died_ms for b in s.boards],
            "pressure_events": s.pressure_k,
        }

    def state_hash(self, s: StackState) -> str:
        return canonical_hash({"seed": s.seed, "t": s.t_ms, "k": s.pressure_k,
                               "boards": [asdict(b) for b in s.boards]})

    # ------------------------------------------------------------ observation

    def _observation(self, s: StackState, player: int) -> str:
        b = s.boards[player]
        piece = self._piece(s, player)
        hs = heights(b.rows)
        nxt = PRESSURE_START_MS + PRESSURE_EVERY_MS * s.pressure_k
        lines = [
            RULES_TEXT,
            f"Time {s.t_ms / 1000:.2f}s level {1 + s.t_ms // 10000}. Next pressure at {nxt // 1000}s: "
            f"{s.pressure_k + 1} row(s).",
            f"You: lines {b.lines}, garbage sent {b.sent}, pending garbage {b.pending}.",
            "Your board (top row = row 20, # block, . empty; columns c0..c9 left to right):",
            *board_lines(b.rows),
            "Heights c0..c9: " + " ".join(map(str, hs)) + f" | holes {holes(b.rows)}",
            f"Piece {piece}, next {' '.join(s.seq[b.idx + 1:b.idx + 4])}.",
            "Rotations (rows top to bottom, / = new row): "
            + "  ".join(f"{r}={shape_ascii(piece, r)}" for r in rotation_options(piece)),
        ]
        for i in range(1, self.n_players):
            q = (player + i) % self.n_players
            bq = s.boards[q]
            lines.append(f"rival{i}: max height {max(heights(bq.rows))}, pending {bq.pending}, "
                         + ("alive" if bq.alive else "OUT"))
        return "\n".join(lines)

    @staticmethod
    def _sensors(rows: list[int], piece: str, rot: str) -> str:
        parts = []
        for cid in column_options(piece, rot):
            new, n, top = drop(rows, piece, rot, int(cid[1:]))
            parts.append(f"{cid}: TOP OUT" if top else f"{cid}: lines {n}, max h {max(heights(new))}, holes {holes(new)}")
        return "After drop (shared sensor) - " + "; ".join(parts)
