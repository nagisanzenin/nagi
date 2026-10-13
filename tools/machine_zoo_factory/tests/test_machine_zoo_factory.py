# SPDX-License-Identifier: Apache-2.0
"""Offline CPU tests of the Machine Zoo family factory (tools/machine_zoo_factory). Run:

    OMP_NUM_THREADS=2 python -m pytest -q tools/machine_zoo_factory/tests
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from os import environ

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")  # the exact teacher's policy evaluation uses scipy.sparse

TOOL = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if TOOL not in sys.path:
    sys.path.insert(0, TOOL)

import famgate as fg  # noqa: E402
import prose_check  # noqa: E402
import validate  # noqa: E402

EXAMPLE = os.path.join(TOOL, "examples", "example_dock_cart.py")
TEMPLATE = os.path.join(TOOL, "examples", "family_template.py")
READING = os.path.join(TOOL, "examples", "example_dock_cart.reading.txt")
DOMAINS = os.path.join(TOOL, "examples", "domains_example.txt")
PROF = fg.PROFILES["train"]


def _copy_family(src: str, dst_dir: str, name: str, edits=()) -> str:
    """Copy a family file under a new name (FAMILY['name'] = file stem), applying (old, new) text edits."""
    with open(src) as f:
        s = f.read()
    stem = os.path.splitext(os.path.basename(src))[0]
    s = s.replace(f'"name": "{stem}"', f'"name": "{name}"')
    for a, b in edits:
        assert a in s, a
        s = s.replace(a, b)
    os.makedirs(dst_dir, exist_ok=True)
    path = os.path.join(dst_dir, f"{name}.py")
    with open(path, "w") as f:
        f.write(s)
    return path


def _run(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    env = dict(environ, OMP_NUM_THREADS="2")
    return subprocess.run([sys.executable, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=300)


# ------------------------------------------------------------------------------------------------ the example passes
def test_example_passes_full_gate_with_x6(tmp_path, capsys):
    rec = validate.run(EXAMPLE, x6=True, quiet=True, job=str(tmp_path))
    out = capsys.readouterr().out
    assert rec["pass"], rec["failed"]
    assert rec["n_kept"] == 10 and rec["X6"]["pass"] is True and rec["V7"]["pass"]
    assert rec["gate_version"] == fg.GATE_VERSION
    assert "kept 10 (need 6); instance failures {}; X6 True" in out
    assert "FAMILY PASS example_dock_cart" in out
    rep = json.loads((tmp_path / "REPORTS" / "example_dock_cart.json").read_text())
    assert rep["pass"] and rep["module_sha256"] == fg.file_sha256(EXAMPLE)


def test_template_passes_draft_gate(tmp_path):
    rec = validate.run(TEMPLATE, x6=False, quiet=True, job=str(tmp_path), write_report=False)
    assert rec["n_kept"] >= PROF.min_pass
    assert rec["failed"] == ["X6:skipped(draft --no-x6)"]  # a draft run never counts as PASS


def test_thresholds_identical_to_research_gate():
    p = PROF
    assert (p.oracle_min, p.keep_max, p.weak_max, p.random_max, p.probe4_max) == (0.95, 0.20, 0.80, 0.50, 0.80)
    assert (p.load_succ, p.load_ret, p.long_median, p.min_pass, p.keep_max_inst) == (0.20, 10.0, 20, 6, 10)
    assert (p.max_rules, p.max_rulebook_chars, p.max_inst_seconds) == (24, 3200, 120.0)
    assert (p.prose_min_chars, p.prose_max_chars, p.prose_dsl_overlap_max, p.prose_twin_max, p.dup_wl_max) == \
        (400, 6000, 0.10, 0.35, 0.60)
    assert p.inst_salt == "v2g-fam-inst-v0"


# ------------------------------------------------------------------------------------------------ broken families fail
def test_dsl_leaked_into_prose_fails_P1(tmp_path):
    leak = 'nothing here is random.\n"""'
    path = _copy_family(EXAMPLE, str(tmp_path / "FAMILIES"), "leaky_dock_cart", edits=[(
        leak, 'nothing here is random.\nRule 2 in short:\nif all(mode == 2, @lever == -1): pos := pos + 1\n"""')])
    rec = fg.check_family(path, PROF, index=[], x6=False, max_scan=3)
    assert not rec["pass"] and "admit:<min_pass" in rec["failed"]
    for inst in rec["instances"]:
        assert "P1:prose" in inst["failed"]
        assert inst["P1"]["dsl_hits"] and inst["P1"]["parser_accepts"]


def test_trivial_machine_fails_V4(tmp_path):
    src = '''from machine_zoo import dsl
from bv2n.zoo_new import xdsl

FAMILY = {"name": "drift_belt", "domain_id": "drift_belt", "batch": "x", "slot": 1, "author": "test",
          "title": "Belt that drifts to the goal", "story": "The belt reaches the end on its own.", "strata": ["long"]}
PARAMS = {"goal_cell": [8, 9, 10, 11], "start_hi": [1, 2]}


def build(p):
    return xdsl.make(dsl.program(
        vars=[dsl.var("belt_pos", 0, 12, list(range(0, p["start_hi"] + 1)))],
        controls=[dsl.control("nudge", [-1, 0, 1])],
        rules=["belt_pos := belt_pos + 1 + @nudge"],
        goal=f"belt_pos >= {p['goal_cell']}"))


def prose(p):
    return "The belt moves on its own. " * 20
'''
    d = tmp_path / "FAMILIES"
    d.mkdir()
    path = d / "drift_belt.py"
    path.write_text(src)
    rec = fg.check_family(str(path), PROF, index=[], x6=False, max_scan=3)
    assert not rec["pass"]
    for inst in rec["instances"]:
        assert "V4:keep" in inst["failed"] and inst["V4"]["keep"] > PROF.keep_max


def test_forbidden_import_fails_V0(tmp_path):
    path = _copy_family(EXAMPLE, str(tmp_path / "FAMILIES"), "io_dock_cart",
                        edits=[("from machine_zoo import dsl\n", "import os\nfrom machine_zoo import dsl\n")])
    rec = fg.check_family(path, PROF, index=[], x6=False)
    assert rec["failed"] == ["V0:contract"] and any("import os" in e for e in rec["errors"])


def test_forbidden_tokens_file(tmp_path):
    tok = tmp_path / "tokens.txt"
    tok.write_text("# one token per line\nDock\n")
    rec = validate.run(EXAMPLE, x6=False, quiet=True, job=str(tmp_path), tokens_file=str(tok), write_report=False)
    assert rec["failed"] == ["V0:contract"] and any("forbidden tokens" in e for e in rec["errors"])


# ------------------------------------------------------------------------------------------------ V7 index is explicit
def test_v7_index_is_only_what_the_user_supplies(tmp_path):
    fam = _copy_family(EXAMPLE, str(tmp_path / "job" / "FAMILIES"), "harbour_cart",
                       edits=[('"domain_id": "example_dock_cart"', '"domain_id": "harbour_cart"')])
    job = str(tmp_path / "job")
    # default: the bundled examples are indexed -> a renamed copy of the example is a near-duplicate
    rec = validate.run(fam, x6=False, quiet=True, job=job, write_report=False)
    assert rec["V7"]["sig_hits"] == ["example_dock_cart"] and not rec["V7"]["pass"]
    # nothing indexed: the same file has no V7 finding (no built-in catalog exists)
    rec = validate.run(fam, x6=False, quiet=True, job=job, examples=False, write_report=False)
    assert rec["V7"]["n_index"] == 0 and rec["V7"]["pass"]
    # a user-supplied index directory (e.g. the published Machine Zoo families) is used when given
    ext = tmp_path / "published"
    ext.mkdir()
    shutil.copy(EXAMPLE, ext / "example_dock_cart.py")
    rec = validate.run(fam, x6=False, quiet=True, job=job, examples=False, index_dirs=[str(ext)],
                       write_report=False)
    assert rec["V7"]["sig_hits"] == ["example_dock_cart"] and not rec["V7"]["pass"]


# ------------------------------------------------------------------------------------------------ blind sufficiency
def test_prose_check_exact_and_diff(tmp_path):
    with open(READING) as f:
        text = f.read()
    ok, msg = prose_check.check(EXAMPLE, text)
    assert ok and msg.startswith("EXACT"), msg
    wrong = text.replace("pos := pos + 3", "pos := pos + 2")
    assert wrong != text
    ok, msg = prose_check.check(EXAMPLE, wrong)
    assert not ok and msg.startswith("DIFF"), msg
    r = _run(["prose_check.py", EXAMPLE, READING], cwd=TOOL)
    assert r.returncode == 0 and r.stdout.startswith("EXACT"), r.stdout + r.stderr


# ------------------------------------------------------------------------------------------------ job workflow smoke
def test_make_batches_validate_review_status_manifest(tmp_path):
    job = tmp_path / "myjob"
    (job / "BATCHES").mkdir(parents=True)
    # one-slot plans so the template (stratum `long`) can fill a slot
    (job / "BATCHES" / "plans.json").write_text(json.dumps(
        {"plans": {"L": [["long"]], "DL": [["long"]]}, "rotation": {"train": ["L"], "dev": "DL"}}))
    r = _run(["make_batches.py", "--job", str(job), "--domains", DOMAINS, "--salt", "test-salt", "--dev-every", "4"],
             cwd=TOOL)
    assert r.returncode == 0, r.stderr
    assert "8 batches: 2 dev, 6 train" in r.stdout
    lines = [ln for ln in (job / "BATCHES" / "batches.txt").read_text().splitlines() if not ln.startswith("#")]
    assert len(lines) == 8 and lines[0].split(" | ")[2] == "dev" and lines[4].split(" | ")[2] == "dev"
    bid, dom = lines[1].split(" | ")[:2]
    # an author claims the batch and writes one family into the slot
    (job / "CLAIMS" / bid).mkdir(parents=True)
    name = f"{dom}_tram"[:40]
    fam = _copy_family(TEMPLATE, str(job / "FAMILIES"), name, edits=[
        ('"domain_id": "template_tram_stop"', f'"domain_id": "{dom}"'),
        ('"batch": "example"', f'"batch": "{bid}"'), ('"slot": 0', '"slot": 1')])
    rec = validate.run(fam, x6=True, quiet=True, examples=False)
    assert rec["pass"], rec["failed"]
    assert rec["split"] == "train"
    # a blind reviewer accepts it (verdict bound to the module sha256)
    (job / "REVIEWS").mkdir()
    (job / "REVIEWS" / f"{name}.json").write_text(json.dumps(
        {"family": name, "module_sha256": fg.file_sha256(fam), "verdict": "OK", "reviewer": "test"}))
    r = _run(["status.py", "--job", str(job), "--manifest"], cwd=TOOL)
    assert r.returncode == 0, r.stderr
    assert re.search(rf"{bid} train L .*CLAIMED \d+m s1:PASS\({name}\)", r.stdout), r.stdout
    assert "reviews of PASS families: {'OK': 1}" in r.stdout
    man = json.loads((job / "MANIFEST.json").read_text())
    assert man["n"] == 1 and man["families"][0]["accepted"] is True
    assert len(man["families"][0]["kept"]) == rec["n_kept"] and man["families"][0]["kept"][0]["prose_text"]
    # editing a family after its PASS un-counts it until re-validated
    with open(fam, "a") as f:
        f.write("\n# edited\n")
    r = _run(["status.py", "--job", str(job), "--brief"], cwd=TOOL)
    assert f"{bid} train L" in r.stdout and "s1:FAIL" in r.stdout, r.stdout


# ------------------------------------------------------------------------------------------------ episode runner
def _example_tasks(tmp_path, n: int = 2, salt: str = "test-salt-v0") -> str:
    """A tiny task file built from the bundled example family (no benchmark data in this repository)."""
    from nagi.burst2._rt.bv2n.zoo_new import xdsl

    mod = fg.load_module(EXAMPLE)
    path = tmp_path / "tasks.jsonl"
    with open(path, "w") as f:
        for p in fg.instance_order("example_dock_cart", mod.PARAMS, PROF.inst_salt)[:n]:
            px = fg.as_px(mod.build(dict(p)))
            f.write(json.dumps({"family": "example", "cluster": "example_dock_cart", "machine_id": xdsl.machine_id(px),
                                "spec": px, "salt": salt}) + "\n")
    return str(path)


def test_run_episodes_oracle_keep_and_crn(tmp_path):
    sys.path.insert(0, os.path.join(TOOL, "benchmark"))
    import run_episodes as RE

    tasks = _example_tasks(tmp_path)
    r = _run([os.path.join("benchmark", "run_episodes.py"), "--tasks", tasks, "--policy", "oracle",
              "--out", str(tmp_path / "rows.csv")], cwd=TOOL)
    assert r.returncode == 0, r.stderr
    with open(tmp_path / "rows.csv") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2 * 16 and list(rows[0]) == RE.ROW_FIELDS
    for row in rows:
        assert row["crn_key"] == hashlib.sha256(f"test-salt-v0|{row['machine']}|{row['episode']}".encode()).hexdigest()
        assert row["valid"] == "True" and row["arm"] == "oracle"
    # the exact oracle succeeds with probability 1 on these instances (exact chain), so every episode succeeds
    for t in RE.load_tasks(tasks):
        T = RE._teacher(RE.Machine(t["spec"]))
        assert T.view_oracle_chain()["success"] == pytest.approx(1.0)
    assert all(row["success"] == "1" for row in rows)
    # keep never reaches the dock; a policy returning an illegal joint makes the episode INVALID
    t = RE.load_tasks(tasks)[0]
    assert sum(x["success"] for x in RE.run_task(t, RE.keep, "keep", "keep")) == 0
    bad = RE.run_task(t, lambda d: 99, "bad", "bad", E=2)
    assert [x["valid"] for x in bad] == [False, False] and bad[0]["outcome"] == "invalid"
    # common random numbers: the same streams give the same episodes
    a = RE.run_task(t, RE.random_policy, "r", "random")
    b = RE.run_task(t, RE.random_policy, "r", "random")
    assert a == b
