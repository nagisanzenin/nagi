"""View-only RR teacher (LANES teacher API): the gated bv2n RR teacher as a function of an RRView only.

Gated teacher (lane teachers-rs, G3 PASS 24/24 Linux): rr_teacher_pilot.teacher.Teacher(request).controller(), i.e.
burst_v2.rr_teacher.RRTeacherPlanner (frozen sha256 c2e35a1f...) with DEFAULTS + filt_delays=(1,), lag_pred=True, fed
only the served request (InformationAdapter: canonical frame, ray terrain, generator priors, stall age 0). The rrtp
request is rebuilt from the view byte-identically (rr_teacher_pilot.contract.from_observation(view.obs, questions,
p_log)), so decisions are unchanged (tested). The view's rpm_low is NOT used by this teacher (it assumes stall age 0).
The teacher is deterministic: `rng` is accepted for the API and ignored.
"""
from __future__ import annotations

from nagi.burst2._rt.bv2n.contract import rr as CR

SOURCE = "rr_teacher_pilot.teacher.Teacher(kind='new', key='rrtp', worlds=4).controller"


def request_of(view: CR.RRView):
    from nagi.burst2._rt.rr_teacher_pilot.contract import from_observation
    return from_observation(view.obs, CR.QUESTIONS, view.p_log)


def act(view: CR.RRView, rng=None) -> dict:
    from nagi.burst2._rt.rr_teacher_pilot.teacher import Teacher
    a = Teacher(request_of(view)).controller()
    return {c: a[c] for c in CR.CONTROLS}


def label(view: CR.RRView) -> dict:
    """Hard one-hot targets of the teacher joint (the gated teacher has no tie set: its controller is anchored)."""
    j = act(view)
    return {"joint": j, "targets": {c: {o: float(o == j[c]) for o in CR.OPTIONS[c]} for c in CR.CONTROLS}}
