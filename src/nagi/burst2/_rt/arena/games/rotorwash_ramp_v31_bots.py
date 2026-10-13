"""Rotorwash-Ramp v3.1 bots: the ladder and the stall-proof gate's stall bots (CPU, deterministic, privileged).

Every bot reads the engine state (like every Arena ladder bot) and is a pure function of the state and its memory (no
RNG). Calibration plays each bot through the realtime runner's timing with a 1-tick reply delay
(arena.v3.delay.Delayed, FAIL_FIRST_BRIEF Amendment 3).

Ladder (docs/arena_v31/ROTORWASH_RAMP_V31.md §4):
  naive      rwN_slow     the heuristic's controller cruising at 6 m/s instead of 10: a cautious player that reaches the
                          first deck late (~75-90 s), when the roof, storm and engine fade make the landing harder, or
                          not at all before the cap.
  heuristic  rwH_lander   the frozen v2 rescue controller (arena.v2.bots.rw_mission) aimed at the next ship deck, no
                          rescue: flies the gap from the rays at <= 10 m/s, stops over the deck and descends onto it
                          with the v2 PD (no heave prediction, no RPM guard). (The v3 heuristic rw3_mission flies the
                          rescue with the same PD; under the v3.1 storm and engine fade its load swings out or its rotor
                          stalls on 32/32 calib seeds, so it is reported, not a rung.)
  planner    rwL_planner  privileged (arena.games.rotorwash_ramp_v31_planner): exact course, lowered roof and deck motion;
                          hooks the survivor early, carries it with swing damping, lands with a heave-matched descent,
                          lifts off and flies on; the v3 planner's one-tick safety filter vetoes crashing collectives.
                          Delay-aware (`lag`).
Stall bots (gate: max W(stall > rung) <= 0.5 over every stall bot and rung):
  st_idle      all defaults (rw0_hold).
  st_hover     holds its position: vx -> 0, altitude centred between the floor and the lowered roof (v2 PD gains).
  st_loiter    the planner's flight and safety filter with no rescue and no descent: it stops 6 m above the highest
               deck point and holds there for the rest of the round (the strongest loiterer).
  st_dive      a v2-PD loiterer 8 m above the deck (no RPM guard); late in the round its collective pumps and it can
               fall onto the deck: the adversarial case for partial credit (§5 of the doc).
  st_hookhover the heuristic mission until the survivor is hooked, then hovers in place with the load, never delivers.
Floor (reported, not a rung): rw1_creep, the v3 naive rung unchanged (frozen v2 bot: terrain-following hover at
  2 m/s, no hook). It cannot reach the first deck (~395 m) inside the 90 s cap, so its K3 is 0 on every seed, like
  Booster's bg0_idle. Any policy that ever touches a deck beats it on that seed, so the stall gate is taken over the
  three rungs and the floor is reported separately (§5).
Reported, not rungs: rwN_blind (rwH_lander without look-ahead rays), rw3_mission (v3 heuristic), rw2_naive (10 m/s
cruise ignoring terrain: distance, which K3 does not reward).
"""
from __future__ import annotations

from nagi.burst2._rt.arena.v2.bots import Bot, _nearest, make_bot as make_v2_bot, rw_mission
from nagi.burst2._rt.arena.games.rotorwash import COLL_OPTS, CYC_OPTS, SKID_H

# ramp2.0 (superseded rules, kept replayable; its receipt and hash chain use exactly these)
LADDER_IDS_20 = ("rwN_slow", "rwH_lander", "rwL_planner")        # naive, heuristic, planner (seats 1..3)
STALL_IDS_20 = ("st_idle", "st_hover", "st_loiter", "st_dive", "st_hookhover")
FLOOR_ID = "rw1_creep"
REPORTED_IDS_20 = ("rw1_creep", "rwN_blind", "rw3_mission", "rw2_naive")
# ramp2.1 (current): idle floor rung + naive / heuristic / planner (ghost seats 1..3 = the last three)
LADDER_IDS_21 = ("st_idle", "rwN_slow", "rwH_quick", "rwL_fast")
STALL_IDS_21 = ("st_idle", "st_hover", "st_hovercrash")                  # no progress: time only
REFUSAL_IDS_21 = ("st_loiter", "st_dive", "st_hookhover")   # progress, never attempt the deck (approach credit only)
REPORTED_IDS_21 = ("rw1_creep", "rwH_lander", "rwL_planner", "rwL_direct", "rwN_blind", "rw2_naive")
LADDERS = {"ramp2.0": LADDER_IDS_20, "ramp2.1": LADDER_IDS_21}
GHOSTS = {"ramp2.0": LADDER_IDS_20, "ramp2.1": LADDER_IDS_21[1:]}
# back-compat names (ramp2.0)
LADDER_IDS, STALL_IDS, REPORTED_IDS = LADDER_IDS_20, STALL_IDS_20, REPORTED_IDS_20


def _pd_alt_speed(o: dict, mem: dict, e_alt: float, vxd: float, lim_up: float = 2.5, lim_dn: float = 2.5) -> dict:
    """The rw_mission vertical / horizontal PD (same gains) for an altitude error and a desired vx."""
    vy, vx = o["vy"], o["vx"]
    vyd = max(-lim_dn, min(lim_up, 0.3 * e_alt))
    ay = (vy - mem.get("vy", vy)) / 0.25
    mem["vy"] = vy
    dc = 0.9 * (vyd - vy) - 0.35 * ay
    return {"collective": _nearest(COLL_OPTS, (-2, -1, 0, 1, 2), dc),
            "cyclic": _nearest(CYC_OPTS, (-20, -10, 0, 10, 20), max(-15, min(15, 7.0 * (vxd - vx)))),
            "winch": "hold"}


def _as_ship_target(o: dict) -> dict:
    """The observation with the next ship deck as the 'hooked' target (rw_mission then flies to it and lands)."""
    return dict(o, hooked=True, target_dx=o["ship_dx"], target_dy=o["ship_dy"], rope=5.0)


class V31Bot(Bot):
    """Numeric-observation bots (engine.observe of the v3.1 engine: lowered-roof rays, next ship, points)."""

    def policy(self, o: dict) -> dict:
        raise NotImplementedError

    def choose(self, q):
        if self._plan is None:
            o = self.game.engine.observe(self.state, self.seat)
            self._plan = self.policy(o)
        return self._plan.get(q.key, q.default)


class NaiveLander(V31Bot):
    """rwH_lander (heuristic rung): rw_mission aimed at the next ship deck, no rescue."""
    def policy(self, o):
        a = rw_mission(_as_ship_target(o), self.mem)
        a["winch"] = "hold"
        return a


class SlowLander(NaiveLander):
    """rwN_slow (naive rung): rwH_lander cruising at 6 m/s (rw_mission vx_cruise) instead of 10."""
    VX = 6.0

    def policy(self, o):
        a = rw_mission(_as_ship_target(o), self.mem, vx_cruise=self.VX)
        a["winch"] = "hold"
        return a


class BlindLander(V31Bot):
    """rwN_blind (reported): rwH_lander with no look-ahead. It sees only the up and down rays (the forward and
    diagonal rays read as clear), so it holds the gap's centre where it is and does not slow down or climb for the
    rock ahead, then lands like rwH_lander."""

    def policy(self, o):
        up, _, _, _, _, _, dn = o["rays"]
        a = rw_mission(_as_ship_target(dict(o, rays=(up, 80.0, 80.0, 80.0, 80.0, 80.0, dn))), self.mem)
        a["winch"] = "hold"
        return a


class QuickLander(V31Bot):
    """rwH_quick (ramp2.1 heuristic rung; reviewer prototype, kept): reads only what the prompt shows (rays, speeds,
    next-ship deck dx / dy / vy). Cruise: the rw_mission terrain rules (mid-gap from the up/down rays, climb / dive 8 m
    for close rock, slow to 1 m/s for a wall ahead) at VX m/s. Within NEAR m of the next ship: approach at <= V_APP m/s
    to hover HOVER m above the deck; over the deck (|dx| < 6 m, |vx| < 1.5 m/s) sink at SINK m/s relative to the
    deck's vertical speed. Same PD gains as rw_mission. No heave look-ahead, no delay compensation, no RPM guard, no
    rescue."""
    VX, NEAR, V_APP, HOVER, SINK = 12.0, 70.0, 6.0, 6.0, 1.2

    def policy(self, o):
        m = self.mem
        up, up45, fu, fw, fd, dn45, dn = o["rays"]
        dx, dy, vx, vy = o["ship_dx"], o["ship_dy"], o["vx"], o["vy"]
        if abs(dx) < self.NEAR:
            vxd = max(-self.V_APP, min(self.V_APP, 0.3 * dx))
            e_alt = dy + SKID_H + self.HOVER
            vyd = max(-2.0, min(2.5, 0.3 * e_alt))
            if abs(dx) < 6.0 and abs(vx) < 1.5:
                vyd = o["ship_vy"] - self.SINK
        else:
            vxd, e_alt = self.VX, (up - dn) / 2
            if fd < 30 or dn45 < 20:
                e_alt += 8
            if fu < 30 or up45 < 20:
                e_alt -= 8
            if min(fw, fu) < 25:
                vxd = min(vxd, 1.0)
            vyd = max(-2.5, min(2.5, 0.3 * e_alt))
        ay = (vy - m.get("vy", vy)) / 0.25
        m["vy"] = vy
        dc = 0.9 * (vyd - vy) - 0.35 * ay
        return {"collective": _nearest(COLL_OPTS, (-2, -1, 0, 1, 2), dc),
                "cyclic": _nearest(CYC_OPTS, (-20, -10, 0, 10, 20), max(-15, min(15, 7.0 * (vxd - vx)))),
                "winch": "hold"}


class StallBot(V31Bot):
    HOVER_S = 20.0

    def policy(self, o):
        m, bid = self.mem, self.bot_id
        up, up45, fu, fw, fd, dn45, dn = o["rays"]
        if bid == "st_idle":
            return {}
        if bid == "st_creep":
            return rw_mission(o, m, vx_cruise=2.0, hook=False)
        if bid == "st_hover":
            return _pd_alt_speed(o, m, (up - dn) / 2, 0.0)
        if bid == "st_hovercrash":               # hover in place for 20 s, then cut the collective until it crashes
            if o["t"] < self.HOVER_S:
                return _pd_alt_speed(o, m, (up - dn) / 2, 0.0)
            return {"collective": "down2", "cyclic": "center", "winch": "hold"}
        if bid == "st_dive":                     # the v2-PD loiterer: 8 m above the deck with the frozen v2 gains;
            a = rw_mission(_as_ship_target(o), m)   # late in the round (storm, engine fade, no RPM guard) its
            if abs(o["ship_dx"]) < 60:              # collective pumps and it may fall onto the deck (§5)
                a = _pd_alt_speed(o, m, o["ship_dy"] + 8.0, max(-4, min(4, 0.35 * o["ship_dx"])), lim_dn=2.0)
            a["winch"] = "hold"
            return a
        if bid == "st_hookhover":
            if o["hooked"] or m.get("hooked"):
                m["hooked"] = True
                return dict(_pd_alt_speed(o, m, (up - dn) / 2, 0.0), winch="up" if o["rope"] > 5.5 else "hold")
            return rw_mission(o, m)
        raise KeyError(bid)


BOTS = {"rwH_lander": NaiveLander, "rwN_slow": SlowLander, "rwN_blind": BlindLander, "rwH_quick": QuickLander,
        **{b: StallBot for b in ("st_idle", "st_hover", "st_hovercrash", "st_dive", "st_hookhover")}}
PLANNERS = ("rwL_planner", "rwL_direct", "rwL_fast", "rwL_fastrescue", "st_loiter")


def make_bot(bot_id: str):
    if bot_id in BOTS:
        return BOTS[bot_id](bot_id)
    if bot_id in PLANNERS:
        from nagi.burst2._rt.arena.games import rotorwash_ramp_v31_planner as PL
        return PL.PLANNER_BOTS[bot_id](bot_id)
    return make_v2_bot(bot_id)


__all__ = ["LADDERS", "GHOSTS", "LADDER_IDS_20", "LADDER_IDS_21", "STALL_IDS_20", "STALL_IDS_21", "REFUSAL_IDS_21",
           "REPORTED_IDS_20", "REPORTED_IDS_21", "LADDER_IDS", "STALL_IDS", "FLOOR_ID", "REPORTED_IDS", "make_bot"]
