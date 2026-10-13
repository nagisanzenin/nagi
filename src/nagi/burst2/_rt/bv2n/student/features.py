"""Featurizers of the PARSED view (never the runner state) for the small CPU students (bv2n lane gamedata).

Snake (egocentric): frame direction d0 = the applied move p_log if it is legal w.r.t. the heading, else the heading
(the engine keeps the last direction for a straight-back reply). The 12x12 map is shifted so the head is the centre
of a 23x23 window and rotated so d0 points up; off-board cells are blocked. Channels: blocked (#, off-board),
wall-soon (+; 1 - due/13 when its due tick is listed, 0.5 otherwise), food, body, tail. Scalars: hunger, limit,
clock, cells this tick / next move, length, growth, heading relative to d0, food offset, and for each relative move
(straight, right, left): next cell blocked, flood-fill area from it, BFS steps to food (all computed from the map
text). Output = 4 relative classes (straight, right, back, left); absolute move = DNAME[(d0 + j) % 4].
RR: the parsed numeric fields (scaled by fixed rule-range constants) + one-hot p_log; outputs per control.
"""
from __future__ import annotations

from collections import deque

import numpy as np

DNAME = ("up", "right", "down", "left")
DIRS = ((0, -1), (1, 0), (0, 1), (-1, 0))
N, R = 12, 11
W = 2 * R + 1


def _rot_ccw(x: int, y: int, k: int) -> tuple[int, int]:
    for _ in range(k % 4):
        x, y = y, -x
    return x, y


def snake_frame(view: dict) -> int:
    hd = DNAME.index(view["heading"])
    p = view["p_log"].get("move", view["next"])
    d = DNAME.index(p)
    return hd if d == (hd + 2) % 4 else d


def _bfs(grid_blocked, start, goal_set, limit=200):
    if start in goal_set:
        return 0
    q, seen = deque([(start, 0)]), {start}
    while q:
        c, n = q.popleft()
        for dx, dy in DIRS:
            nx, ny = c[0] + dx, c[1] + dy
            if 0 <= nx < N and 0 <= ny < N and (nx, ny) not in seen and not grid_blocked[ny][nx]:
                if (nx, ny) in goal_set:
                    return n + 1
                seen.add((nx, ny))
                q.append(((nx, ny), n + 1))
    return -1


def _flood(grid_blocked, start) -> int:
    q, seen = deque([start]), {start}
    while q:
        c = q.popleft()
        for dx, dy in DIRS:
            nx, ny = c[0] + dx, c[1] + dy
            if 0 <= nx < N and 0 <= ny < N and (nx, ny) not in seen and not grid_blocked[ny][nx]:
                seen.add((nx, ny))
                q.append((nx, ny))
    return len(seen)


SNAKE_DIM = 5 * W * W + 15 + 9


def snake_x(view: dict) -> np.ndarray:
    d0 = snake_frame(view)
    g = view["grid"]
    hx, hy = view["head"]
    due = {(a, b): d for a, b, d in view["soon"]}
    img = np.zeros((5, W, W), np.float32)
    img[0] = 1.0
    blocked = [[False] * N for _ in range(N)]
    for y in range(N):
        for x in range(N):
            ch = g[y][x]
            ex, ey = _rot_ccw(x - hx, y - hy, d0)
            u, v = ex + R, ey + R
            img[0, v, u] = 1.0 if ch == "#" else 0.0
            if ch == "+":
                img[1, v, u] = 1.0 - due[(x, y)] / 13.0 if (x, y) in due else 0.5
            elif ch == "*":
                img[2, v, u] = 1.0
            elif ch == "o":
                img[3, v, u] = 1.0
            elif ch == "t":
                img[4, v, u] = 1.0
            blocked[y][x] = ch in "#o" or (ch == "+" and due.get((x, y), 99) <= 1)
    food = {tuple(f) for f in view["food"]}
    hd = DNAME.index(view["heading"])
    sc = [view["hunger"] / 40, view["limit"] / 40, view["hunger"] / max(1, view["limit"]), view["tick"] / 240,
          view["cells_now"] / 2, view["cells_next"] / 2, view["length"] / 40, view["growing"] / 4]
    sc += [1.0 if (hd - d0) % 4 == j else 0.0 for j in range(4)]
    if food:
        fx, fy = next(iter(sorted(food)))
        ex, ey = _rot_ccw(fx - hx, fy - hy, d0)
        sc += [ex / R, ey / R, (abs(ex) + abs(ey)) / (2 * R)]
    else:
        sc += [0.0, 0.0, 1.0]
    mv = []
    for j in (0, 1, 3):                                  # straight, right, left (relative to d0)
        dx, dy = DIRS[(d0 + j) % 4]
        nx, ny = hx + dx, hy + dy
        if not (0 <= nx < N and 0 <= ny < N) or blocked[ny][nx]:
            mv += [1.0, 0.0, 1.0]
            continue
        b2 = [row[:] for row in blocked]
        b2[hy][hx] = True
        dist = _bfs(b2, (nx, ny), food) if food else -1
        mv += [0.0, _flood(b2, (nx, ny)) / 144, (dist / 24) if dist >= 0 else 1.0]
    return np.concatenate([img.ravel(), np.asarray(sc + mv, np.float32)])


def snake_y(view: dict, joint: dict) -> list[int]:
    return [(DNAME.index(joint["move"]) - snake_frame(view)) % 4]


def snake_joint(view: dict, cls: list[int]) -> dict:
    return {"move": DNAME[(snake_frame(view) + cls[0]) % 4]}


# ------------------------------------------------------------------------------------------------ RR
RR_OPTIONS = {"collective": ("down2", "down1", "hold", "up1", "up2"), "cyclic": ("aft2", "aft1", "center", "fwd1", "fwd2"),
              "winch": ("up", "hold", "down")}
RR_CONTROLS = ("collective", "cyclic", "winch")


def _c(v, s=100.0):
    return max(-s, min(s, v))


def rr_x(o: dict) -> np.ndarray:
    f = [o["t"] / 60, o["points"] / 3, o["roof"] / 60, o["gust_gain"] - 1, o["power_pct"] / 100 - 1, o["fuel"] / 100,
         float(o["landed"]), o["agl"] / 50, o["vx"] / 10, o["vy"] / 5, o["pitch"] / 30, o["rate"] / 30,
         (o["rpm"] - 100) / 10, o["coll"] / 100, o["cyc"], o["margin"] / 50, o["wind"][0] / 5, o["wind"][1] / 5,
         *(r / 80 for r in o["rays"]), o["ship"] / 5, _c(o["ship_dx"]) / 100, o["ship_dy"] / 50, o["ship_vy"] / 3,
         float(o["hooked"]), o["rope"] / 25, o["load_angle"] / 50, o["load_rate"] / 50, o["hook_t"] / 1.5,
         _c(o.get("surv_dx", 100.0)) / 100, o.get("surv_dy", 0.0) / 50, o.get("rpm_low", 0) / 4]
    for c in RR_CONTROLS:
        f += [1.0 if o["p_log"].get(c) == x else 0.0 for x in RR_OPTIONS[c]]
    return np.asarray(f, np.float32)


RR_DIM = 37 + 13


def rr_y(view: dict, joint: dict) -> list[int]:
    return [RR_OPTIONS[c].index(joint[c]) for c in RR_CONTROLS]


def rr_joint(view: dict, cls: list[int]) -> dict:
    return {c: RR_OPTIONS[c][k] for c, k in zip(RR_CONTROLS, cls)}


SPEC = {"snake": {"x": snake_x, "y": snake_y, "joint": snake_joint, "heads": (4,), "dim": SNAKE_DIM},
        "rr": {"x": rr_x, "y": rr_y, "joint": rr_joint, "heads": (5, 5, 3), "dim": RR_DIM}}

# lane booster-student: the Booster featurizer lives in its own module (parsed BoosterView only)
from nagi.burst2._rt.bv2n.student import booster_features as _BF  # noqa: E402

SPEC["booster"] = _BF.SPEC

# ---------------------------------------------------------------- Snake, lag-projected (lane snake-student, arm S3)
# Under the nominal 1-tick reply the decision made at tick t is applied on the move t+1 -> t+2; the move t -> t+1 is
# the pending p_log move (cells_now cells in direction d0). snake_x computes its per-move features from the CURRENT
# head, i.e. for the wrong move. snake_lf_x appends the same kind of features (cell blocked / flood area / BFS steps
# to food), computed from the head PROJECTED along the pending move, for the cells_next cells of each candidate move.
# Body cells stay blocked (conservative: the tail's freed cells are ignored), the pending path's cells are added as
# body, '+' cells count as walls once due within the move's horizon. All from the parsed view only (no runner state).
LF_EXTRA = 2 + 2 + 3 * 5


def snake_lf_x(view: dict) -> np.ndarray:
    base = snake_x(view)
    d0 = snake_frame(view)
    g = view["grid"]
    hx, hy = view["head"]
    due = {(a, b): d for a, b, d in view["soon"]}

    def blocked_at(k):
        return [[g[y][x] in "#o" or (g[y][x] == "+" and due.get((x, y), 99) <= k) for x in range(N)] for y in range(N)]

    b1, b2 = blocked_at(1), blocked_at(2)
    dx, dy = DIRS[d0]
    px, py, dead_now, path = hx, hy, 0.0, [(hx, hy)]
    for _ in range(view["cells_now"]):
        nx, ny = px + dx, py + dy
        if not (0 <= nx < N and 0 <= ny < N) or b1[ny][nx] or (nx, ny) in path:
            dead_now = 1.0
            break
        px, py = nx, ny
        path.append((px, py))
    ex, ey = _rot_ccw(px - hx, py - hy, d0)
    food = {tuple(f) for f in view["food"]}
    out = [dead_now, view["cells_now"] / 2, ex / 2, ey / 2]
    cn = max(1, view["cells_next"])
    for j in (0, 1, 3):
        mx, my = DIRS[(d0 + j) % 4]
        qx, qy, crash, ate, cells = px, py, 0.0, 0.0, list(path)
        for _ in range(cn):
            nx, ny = qx + mx, qy + my
            if not (0 <= nx < N and 0 <= ny < N) or b2[ny][nx] or (nx, ny) in cells:
                crash = 1.0
                break
            qx, qy = nx, ny
            cells.append((qx, qy))
            ate = max(ate, float((qx, qy) in food))
        if crash:
            out += [1.0, 0.0, 0.0, 1.0, 0.0]
            continue
        bb = [row[:] for row in b2]
        for (cx, cy) in cells[:-1]:
            bb[cy][cx] = True
        dist = _bfs(bb, (qx, qy), food) if food else -1
        out += [0.0, ate, _flood(bb, (qx, qy)) / 144, (dist / 24) if dist >= 0 else 1.0,
                min((due[c] for c in due if abs(c[0] - qx) + abs(c[1] - qy) <= 1), default=13) / 13]
    return np.concatenate([base, np.asarray(out, np.float32)])


SPEC["snake_lf"] = {"x": snake_lf_x, "y": snake_y, "joint": snake_joint, "heads": (4,), "dim": SNAKE_DIM + LF_EXTRA}
