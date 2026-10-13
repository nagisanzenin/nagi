"""Fill nagi.burst2's frozen constants from the FROZEN research CANDIDATE.json (and, later, the HF weights commit).

    python scripts/burst2_fill_frozen.py --candidate <research>/docs/burst_v2_general/CANDIDATE.json [--revision H]

Sets in src/nagi/burst2/_api.py: S_STAR (budget of candidate_policy G<S*>b1b), SNAKE_POLICY (snake_policy),
CORE_SHA256 (core_weights_sha256) and, with --revision, BURST_V2_REVISION (the Hugging Face commit of the released
weights, 40 hex). Rewrites src/nagi/burst2/frozen/candidate_search.json from the candidate. Refuses unless the
candidate status is FROZEN and its search config sha is the shipped runtime_search_config_v1b.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "src/nagi/burst2/_api.py"
FROZEN = ROOT / "src/nagi/burst2/frozen"


def setconst(src: str, name: str, value: str) -> str:
    new, n = re.subn(rf"^{name} = .*?(\s+#.*)?$", lambda m: f"{name} = {value}{m.group(1) or ''}", src, count=1,
                     flags=re.M)
    if n != 1:
        raise SystemExit(f"constant {name} not found")
    return new


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--revision", default=None)
    a = ap.parse_args()
    c = json.loads(Path(a.candidate).read_text())
    if c.get("status") != "FROZEN":
        raise SystemExit(f"CANDIDATE status {c.get('status')!r} != FROZEN")
    sc = c["predeclared"]["search_config"]
    shipped = hashlib.sha256((FROZEN / "runtime_search_config_v1b.json").read_bytes()).hexdigest()
    if sc["sha256"] != shipped:
        raise SystemExit("candidate search config sha != shipped runtime_search_config_v1b.json")
    m = re.fullmatch(r"G(\d+)b1b", c["candidate_policy"])
    if not m or c["candidate_policy"] != sc["candidate_policy"]:
        raise SystemExit(f"unexpected candidate_policy {c['candidate_policy']!r}")
    if c["snake_policy"] not in ("sdk_pack", "core_head"):
        raise SystemExit(f"unexpected snake_policy {c['snake_policy']!r}")
    if not re.fullmatch(r"[0-9a-f]{64}", c["core_weights_sha256"]):
        raise SystemExit("bad core_weights_sha256")
    src = API.read_text()
    src = setconst(src, "S_STAR", f"{int(m.group(1)):_}")
    src = setconst(src, "SNAKE_POLICY", json.dumps(c["snake_policy"]))
    src = setconst(src, "CORE_SHA256", json.dumps(c["core_weights_sha256"]))
    if a.revision:
        if not re.fullmatch(r"[0-9a-f]{40}", a.revision):
            raise SystemExit("revision must be the full 40-hex HF commit")
        src = setconst(src, "BURST_V2_REVISION", json.dumps(a.revision))
    API.write_text(src)
    out = {"candidate_policy": c["candidate_policy"], "core_weights_sha256": c["core_weights_sha256"],
           "file": sc["file"], "frozen_at": c.get("frozen_at"), "harness_commit": c.get("harness_commit"),
           "search_only_s0_star": c.get("search_only_s0_star"), "sha256": sc["sha256"],
           "snake_policy": c["snake_policy"], "source": "research docs/burst_v2_general/CANDIDATE.json (FROZEN)",
           "status": "FROZEN", "tau": sc["tau"]}
    (FROZEN / "candidate_search.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: out[k] for k in ("candidate_policy", "snake_policy", "core_weights_sha256", "tau")}))


if __name__ == "__main__":
    main()
