"""rwL_planner: the privileged landing planner of the Rotorwash-Ramp v3.1 ladder (planner rung).

It reads the exact course, the lowered roof (v3.1 schedule) and the deck motion, and plays the K3 task: optionally
hook the leg's survivor (only early in the round, while the engine still has the power margin to carry the load),
fly the corridor to the next ship, stop over the deck, descend at a controlled sink relative to the heaving deck,
touch down, lift off again and repeat on the next leg. Every choice passes the v3 planner's one-tick safety filter
(rotorwash_ramp_bots.RampPlanner._safety: roll the engine's own physics forward 2 s and veto a collective choice that
crashes; a hard landing is a crash, so the filter also enforces the sink limit). Delay-aware like the v3 planner
(`lag`: it plans from the exactly predicted state where its reply lands). No RNG: a pure function of the state and
its memory.
"""
from __future__ import annotations

import math

from nagi.burst2._rt.arena.games import rotorwash as rw
from nagi.burst2._rt.arena.games.rotorwash_ramp_bots import COLL_STEPS, CYC_U, RampPlanner, _nearest


class LandingPlanner(RampPlanner):
    LOOK = (0.4, 0.8, 1.2, 1.6, 2.0, 2.6, 3.2)
    SAFETY_TICKS = 8
    SEARCH_CYCLIC = False
    RESCUE_UNTIL_S = 30.0       # start a rescue only before this time (the fading engine must still lift the load)
    V_MAX = 18.0                # m/s transit cap
    V_CARRY = 11.0              # m/s cap with the load hooked
    BRAKE = 1.2                 # m/s^2 planned deceleration toward a stop point
    DESCEND = True              # False: the stall-gate loiterer (st_loiter) that stops over the deck and never lands

    def _corridor(self, eng, s, x, vx, k):
        from nagi.burst2._rt.arena.games.rotorwash_ramp_v31 import ramp_course
        rc_now = ramp_course(s.seed, eng.sched, k)
        rc_fut = ramp_course(s.seed, eng.sched, min(eng.n_ticks, k + 12))
        lo, hi = -1e9, 1e9
        for tau in self.LOOK:
            xx = x + max(vx, 2.0) * tau
            fl = rc_now.floor_at(xx)
            ce = (rc_fut if tau > 1.5 else rc_now).ceil_at(xx)
            for sh in rc_now.ships:
                if abs(xx - sh[0]) <= 16.0:
                    fl = max(fl, sh[1] + 1.4 * sh[2] + 1.0)
            lo, hi = max(lo, fl), min(hi, ce)
        return lo, hi, rc_now

    KV = 5.0                    # deg of pitch per m/s of speed error

    @staticmethod
    def _cyclic_for(h, th_d):
        """The cyclic option whose 0.25 s hold brings the pitch closest to th_d with little residual rate (the pitch
        ODE of the engine, dw/dt = K_U (T/T_REF) u - D_W w - K_TH th, integrated at 20 ms with T = T_REF)."""
        best, best_c = None, None
        for n, u in CYC_U:
            th, w = h["th"], h["w"]
            for _ in range(25):
                w += (rw.K_U * u - rw.D_W * w - rw.K_TH * th) * 0.01
                th += w * 0.01
            for _ in range(10):                # then the pitch keeps evolving under the same u (next hold)
                w += (rw.K_U * u - rw.D_W * w - rw.K_TH * th) * 0.025
                th += w * 0.025
            c = (th - th_d) ** 2 + (0.15 * w) ** 2
            if best_c is None or c < best_c:
                best, best_c = n, c
        return best

    def _vertical(self, vy, vyd):
        ay = (vy - self.mem.get("vy", vy)) / 0.25
        self.mem["vy"] = vy
        return 1.1 * (vyd - vy) - 0.35 * ay

    def _decide(self):
        g, s, p = self.belief or self.game, self.state, self.seat
        eng = g.engine
        h = s.helis[p]
        co = rw.build_course(s.seed)
        k = s.t_ms // 250
        t = s.k * rw.DT
        x, y, vx, vy = h["x"], h["y"], h["vx"], h["vy"]
        lo, hi, rc = self._corridor(eng, s, x, vx, k)
        room = hi - lo
        o = eng.observe(s, p)
        winch = "hold"
        j = eng.next_ship(h)
        sx = co.ships[j][0]
        dky, dkv, _ = co.deck(j, t)
        deck_max = co.ships[j][1] + 1.4 * co.ships[j][2]
        leg = h["leg"]
        sxv, syv = co.surv[leg]
        rescue = (not h["att"] and h["surv_min"] <= leg and s.t_ms / 1000 < self.RESCUE_UNTIL_S
                  and sxv - x > -3.0 and h["landed"] < 0 and sxv < sx)
        if self.mem.get("rescue_leg") == leg and not h["att"] and h["surv_min"] <= leg and sxv - x > -6.0:
            rescue = True                     # committed: finish the hook attempt
        pitch_lim = 15.0 if room > 14 else 10.0
        if rescue:
            self.mem["rescue_leg"] = leg
            dx = sxv - x
            roof_here = rc.ceil_at(sxv)
            y_t = min(syv + 12.0, roof_here - 4.5)
            L_t = max(rw.L_MIN, min(rw.L_MAX, y_t - syv - 1.0))
            winch = "down" if h["L"] < L_t - 0.3 else ("up" if h["L"] > L_t + 0.6 else "hold")
            vmax = min(self.V_MAX, math.sqrt(2 * self.BRAKE * max(0.0, abs(dx) - 1.0)) + 0.3)
            vxd = max(-vmax, min(vmax, 0.35 * dx))
            if abs(dx) > 25:
                y_t = max(y_t, (lo + hi) / 2) if room < 30 else max(y_t, lo + 8.0)
            vyd = max(-2.0, min(2.5, 0.45 * (y_t - y)))
            pitch_lim = 10.0 if abs(dx) < 15 else pitch_lim
        else:
            dx = sx - x
            over = abs(dx) < 5.0 and abs(vx) < 2.0
            vmax = min(self.V_MAX, 4.0 + 0.6 * max(0.0, room - 12.0), math.sqrt(2 * self.BRAKE * max(0.0, abs(dx) - 0.5)) + 0.2)
            vxd = max(-vmax, min(vmax, 0.35 * dx))
            if h["att"]:                      # carry gently: reel in first, small pitch, damp the swing
                winch = "up" if h["L"] > 5.5 else "hold"
                cap = 0.0 if h["L"] > 7.0 else self.V_CARRY
                vxd = max(-cap, min(cap, vxd)) + 3.0 * math.sin(h["phi"]) + 0.3 * h["L"] * h["phid"]
                pitch_lim = 6.0
            if abs(dx) < 40:                  # final approach over the bay: hover 6 m above the highest deck point
                y_t = deck_max + rw.SKID_H + 6.0
                vyd = max(-2.0, min(2.5, 0.45 * (y_t - y)))
                if over and self.DESCEND:     # descend: sink ~0.9 m/s relative to the heaving deck
                    gap = y - rw.SKID_H - dky
                    vyd = dkv + max(-1.3, min(0.5, -0.35 * gap - 0.5))
                pitch_lim = min(pitch_lim, 6.0 if abs(dx) < 12 else 10.0)
            else:
                yc = (lo + hi) / 2 + 0.5
                lim = 3.0 + 0.1 * abs(vx)
                vyd = max(-lim, min(lim, 0.45 * (yc - y)))
        if h["landed"] >= 0 and j not in h["ships_landed"]:
            vyd = 0.0                          # sitting on a new deck cannot happen (it was credited); keep safe
        dc = self._vertical(vy, vyd)
        if o["rpm"] < 96.0 or o["power_margin"] < 3.0:
            dc = min(dc, 0.0)
        coll = _nearest(COLL_STEPS, dc)
        th_d = max(-pitch_lim, min(pitch_lim, self.KV * (vxd - vx)))
        cyc = self._cyclic_for(h, math.radians(th_d))
        coll, cyc = self._safety(eng, s, p, coll, cyc)
        return {"collective": coll, "cyclic": cyc, "winch": winch}


class Loiterer(LandingPlanner):
    """st_loiter (stall gate): the planner's flight and safety filter, no rescue, and over the deck it holds 6 m above
    the highest deck point for the rest of the round: the strongest 'loiter near a deck without landing' policy."""
    RESCUE_UNTIL_S = -1.0
    DESCEND = False


class DirectPlanner(LandingPlanner):
    """rwL_direct (reported; reviewer prototype): the ramp2.0 planner without the rescue: flies to the next ship and
    lands with the slow (hover 6 m, sink ~0.9 m/s) descent."""
    RESCUE_UNTIL_S = -1.0


class FastPlanner(LandingPlanner):
    """rwL_fast (ramp2.1 planner rung): the ramp2.0 planner re-tuned for the 60 s cap and the v3 ramp, so the first
    landing comes early (target 30-35 s; reviewer 2026-09-30: the ramp2.0 descent took ~13 s, first landing ~46 s).
    Privileged like every planner (exact course, lowered roof, deck heave), delay-aware (`lag`), no RNG. Changes:
      * transit: speed cap from the corridor room is looser (6 + 0.8 (room - 10) instead of 4 + 0.6 (room - 12)) and
        the planned braking is 2.0 m/s^2 (a 15 deg pitch gives ~2.6);
      * transit on a glide path (target height 3 m + 0.2 |dx| above the highest deck point, kept 8 m above the
        corridor floor and 6 m below its roof) instead of the corridor centre, so the ~50 m descent happens with
        forward airspeed during transit (the ramp2.0 planner flew mid-gap, ~58 m above the deck, then sank slowly);
      * approach: a gliding approach (target height 3 m + 0.08 |dx| above the highest deck point) instead of stopping
        6 m up; descent starts over the deck (|dx| < 3.5 m, |vx| < 1.5 m/s);
      * after a landing it sits 1.5 s, then lifts off and flies on toward the next ship (approach credit);
      * descent: sink SINK m/s relative to the heaving deck down to 2 m, then FLARE m/s;
      * the safety filter's continuation is a braking controller over the deck (sink -> FLARE rel. deck) instead of
        'hold', so a fast descent is kept whenever the next ticks can still arrest it; it still vetoes a collective
        whose best continuation crashes (a hard landing is a crash).
    No rescue by default (rwL_fastrescue hooks the survivor first when it is before the ship and time allows)."""
    RESCUE_UNTIL_S = -1.0
    BRAKE = 2.0                 # planned braking (a 15 deg pitch gives ~2.6 m/s^2 plus drag)
    V_MAX = 22.0
    STOP_DX, LEAD_S = 3.0, 1.0  # brake to stop 3 m short of the ship centre, with a 1 s reaction lead
    SINK, FLARE, FLARE_GAP = 2.5, 1.0, 3.0      # m/s relative to the deck; flare below FLARE_GAP m
    SINK_APP = 4.0              # approach sink cap (vortex ring needs > 0.6 v_h ~ 5 m/s of inflow)
    FINAL_DX, FINAL_VX = 8.0, 3.0   # descent starts within 8 m of the ship centre (deck half-length 13 m), |vx| < 3
    V_ROOM0, V_ROOM_K, ROOM0 = 6.0, 0.8, 10.0
    GLIDE = 0.25                # glide-path slope (m of height per m of distance to the ship) during transit
    GLIDE_APP = 0.3             # the slope on the final 45 m
    MARGIN_LO, MARGIN_HI = 8.0, 6.0
    DWELL_MS = 1500             # sit on a new deck this long before lifting off toward the next ship

    def _decide(self):
        g, s, p = self.belief or self.game, self.state, self.seat
        eng = g.engine
        h = s.helis[p]
        if self.RESCUE_UNTIL_S > 0 and (h["att"] or self._rescue_now(eng, s, h)):
            return super()._decide()
        co = rw.build_course(s.seed)
        k = s.t_ms // 250
        t = s.k * rw.DT
        x, y, vx, vy = h["x"], h["y"], h["vx"], h["vy"]
        lo, hi, rc = self._corridor(eng, s, x, vx, k)
        room = hi - lo
        o = eng.observe(s, p)
        j = eng.next_ship(h)
        sx = co.ships[j][0]
        dky, dkv, _ = co.deck(j, t)
        deck_max = co.ships[j][1] + 1.4 * co.ships[j][2]
        dx = sx - x
        pitch_lim = 15.0 if room > 14 else 10.0
        d_eff = abs(dx) - self.STOP_DX - self.LEAD_S * abs(vx)    # braking distance left, ~1 s reaction lead
        vmax = min(self.V_MAX, self.V_ROOM0 + self.V_ROOM_K * max(0.0, room - self.ROOM0),
                   math.sqrt(2 * self.BRAKE * max(0.0, d_eff)) + 1.0)
        vxd = max(-vmax, min(vmax, 0.35 * dx))
        final = False
        if abs(dx) < 45:                       # gliding approach toward a point just above the deck
            y_t = deck_max + rw.SKID_H + 2.0 + self.GLIDE_APP * abs(dx)
            y_t = min(y_t, rc.ceil_at(x) - 4.0)
            vyd = max(-self.SINK_APP, min(2.5, 0.5 * (y_t - y)))
            if abs(dx) < self.FINAL_DX and abs(vx) < self.FINAL_VX:
                final = True
                gap = y - rw.SKID_H - dky
                vyd = dkv - (self.SINK if gap > self.FLARE_GAP else self.FLARE)
            pitch_lim = min(pitch_lim, 8.0 if abs(dx) < 10 else 15.0)
        else:                                  # transit on a glide path toward the deck, inside the corridor
            glide = deck_max + rw.SKID_H + 3.0 + self.GLIDE * abs(dx)
            a_lo, a_hi = lo + self.MARGIN_LO, hi - self.MARGIN_HI
            yc = min(max(glide, a_lo), a_hi) if a_lo <= a_hi else (lo + hi) / 2 + 0.5
            lim = 3.0 + 0.1 * abs(vx)
            vyd = max(-lim, min(lim, 0.45 * (yc - y)))
        if h["landed"] >= 0:                   # on a credited deck: dwell, then lift off vertically
            t0 = self.mem.setdefault("land_t", s.t_ms)
            vyd, vxd = (0.0, 0.0) if s.t_ms - t0 < self.DWELL_MS else (2.0, 0.0)
            self.mem["climb_from"] = h["y"]
        else:
            self.mem.pop("land_t", None)
            if "climb_from" in self.mem:       # lift-off: climb 5 m clear of the deck before moving on
                if h["y"] - self.mem["climb_from"] < 5.0:
                    vyd, vxd = 2.0, 0.0
                else:
                    del self.mem["climb_from"]
        self.mem["final"] = final
        dc = self._vertical(vy, vyd)
        if o["rpm"] < 96.0 or o["power_margin"] < 3.0:
            dc = min(dc, 0.0)
        coll = _nearest(COLL_STEPS, dc)
        th_d = max(-pitch_lim, min(pitch_lim, self.KV * (vxd - vx)))
        cyc = self._cyclic_for(h, math.radians(th_d))
        coll, cyc = self._safety(eng, s, p, coll, cyc)
        return {"collective": coll, "cyclic": cyc, "winch": "up" if h["L"] > 5.5 else "hold"}

    def _rescue_now(self, eng, s, h):
        co = rw.build_course(s.seed)
        leg = h["leg"]
        sxv = co.surv[leg][0]
        sx = co.ships[eng.next_ship(h)][0]
        if self.mem.get("rescue_leg") == leg and h["surv_min"] <= leg and sxv - h["x"] > -6.0:
            return True
        return (h["surv_min"] <= leg and s.t_ms / 1000 < self.RESCUE_UNTIL_S and sxv - h["x"] > -3.0
                and h["landed"] < 0 and sxv < sx)

    def _rollout(self, eng, s, p, coll, cyc):
        """Over the deck: the candidate for one tick, then the braking continuation (sink FLARE m/s relative to the
        deck, the planner's vertical law) instead of 'hold'. Elsewhere: the v3 planner's rollout."""
        if not self.mem.get("final"):
            return super()._rollout(eng, s, p, coll, cyc)
        from nagi.burst2._rt.arena.games.rotorwash import RWState
        h = dict(s.helis[p])
        h["alive"] = True
        st = RWState(seed=s.seed, k=s.k, t_ms=s.t_ms, helis=[h], ended=False)
        co = rw.build_course(s.seed)
        j = eng.next_ship(h)
        acts = {"collective": coll, "cyclic": cyc, "winch": "hold"}
        step = getattr(self.belief or self.game, "step", eng.step)
        vy_prev = h["vy"]
        for i in range(self.SAFETY_TICKS):
            st, _ = step(st, {0: acts}, 250)
            hh = st.helis[0]
            if not hh["alive"]:
                return i
            if hh["landed"] >= 0:
                return self.SAFETY_TICKS
            _, dkv, _ = co.deck(j, st.k * rw.DT)
            vy = hh["vy"]
            dc = 1.1 * (dkv - self.FLARE - vy) - 0.35 * (vy - vy_prev) / 0.25
            vy_prev = vy
            acts = {"collective": _nearest(COLL_STEPS, dc), "cyclic": cyc, "winch": "hold"}
        return self.SAFETY_TICKS


class FastRescuePlanner(FastPlanner):
    """rwL_fastrescue (reported): rwL_fast that first hooks the survivor (ramp2.0 planner's rescue) when it is on the
    way and before RESCUE_UNTIL_S."""
    RESCUE_UNTIL_S = 12.0


PLANNER_BOTS = {"rwL_planner": LandingPlanner, "rwL_direct": DirectPlanner, "rwL_fast": FastPlanner,
                "rwL_fastrescue": FastRescuePlanner, "st_loiter": Loiterer}
