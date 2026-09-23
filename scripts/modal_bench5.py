"""5-way bench on Modal H100: Smol | Big | Laya | OpenJev | Jev.

Gold: data/gold_ltout.jsonl (full N=2700). Same scoring for every arm.
  Smol    = nagisanzeninz/nagi-smol-v0 (volume t4s_hail_s_c2)
  Big     = nagisanzeninz/nagi-big-v0  (volume hailg_g1/pissa + Qwen3.5-4B)
  Laya    = convaiinnovations/laya (PyPI laya)
  OpenJev = SemIf recipe — frozen Qwen3.5-4B letter-logit readout (no FT)
  Jev     = api.typesafe.ai jev-latest (if TYPESAFE_API_KEY set)

Run: modal run /abs/scripts/modal_bench5.py --tag b5
"""
from __future__ import annotations

import base64
import io
import json
import tarfile
from pathlib import Path

import modal

app = modal.App("nagi-bench5")
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("torch==2.5.1", index_url="https://download.pytorch.org/whl/cu124")
    .pip_install(
        "transformers>=4.48",
        "peft>=0.14",
        "accelerate",
        "safetensors",
        "numpy",
        "pyyaml",
        "tqdm",
        "laya==0.3.7",
    )
)
vol = modal.Volume.from_name("nagi-results", create_if_missing=True)


INNER = r'''
import json, math, os, sys, time, traceback
from pathlib import Path
sys.path.insert(0, "/root/nagi/src")
import torch
from nagi.render import option_keys, render_nagi_prompt, target_probs

ROOT = Path("/root/nagi")
OUT = Path("/results/bench5_TAG")
OUT.mkdir(parents=True, exist_ok=True)
rows = [json.loads(x) for x in open(ROOT / "data/gold_ltout.jsonl") if x.strip()]
print("rows", len(rows), flush=True)

def score(preds, lats):
    hard = soft = brier = 0.0
    confs, oks = [], []
    n = 0
    for r in rows:
        for qid, q in (r.get("questions") or {}).items():
            if r["id"] not in preds or qid not in preds[r["id"]]:
                continue
            keys = option_keys(q)
            gold = target_probs(r, qid, keys)
            pr = preds[r["id"]][qid]
            p = [float(pr.get(k, 0.0)) for k in keys] if isinstance(pr, dict) else [float(x) for x in pr][: len(keys)]
            s = sum(p) or 1.0
            p = [x / s for x in p]
            pred_i, gold_i = p.index(max(p)), gold.index(max(gold))
            ok = float(pred_i == gold_i)
            hard += ok
            soft += sum(a * b for a, b in zip(p, gold))
            brier += sum((a - b) ** 2 for a, b in zip(p, gold))
            confs.append(max(p)); oks.append(ok)
            n += 1
    ece = 0.0
    if confs:
        for i in range(10):
            lo, hi = i / 10, (i + 1) / 10
            m = [j for j, c in enumerate(confs) if (c > lo or (i == 0 and c >= 0)) and c <= hi]
            if m:
                mc = sum(confs[j] for j in m) / len(m)
                mo = sum(oks[j] for j in m) / len(m)
                ece += (len(m) / len(confs)) * abs(mc - mo)
    lats_s = sorted(x for x in lats if x is not None)
    return {
        "n": n,
        "hard_acc": hard / max(1, n),
        "soft_acc": soft / max(1, n),
        "brier": brier / max(1, n),
        "ece": ece,
        "latency_ms_p50": lats_s[len(lats_s)//2] if lats_s else None,
        "latency_ms_p95": lats_s[min(len(lats_s)-1, int(0.95*len(lats_s)))] if lats_s else None,
    }

def save(name, preds, lats, meta=None):
    m = score(preds, lats)
    if meta:
        m.update(meta)
    (OUT / f"{name}.json").write_text(json.dumps(m, indent=2))
    print(name, json.dumps(m), flush=True)
    return m

results = {}

# ---------- Smol ----------
try:
    from nagi.config import load_config
    from nagi.model import build_model
    from nagi.serve.predict import Nagi
    smol_dir = Path("/results/t4s_hail_s_c2")
    # model.pt may be a file; config.snapshot.yaml from same dir or nagi config
    cfg_path = smol_dir / "config.snapshot.yaml"
    if not cfg_path.exists():
        cfg_path = ROOT / "configs/hail_s_c2.yaml"
    cfg = load_config(cfg_path)
    model = build_model(cfg)
    st = torch.load(smol_dir / "model.pt", map_location="cpu", weights_only=True)
    if isinstance(st, dict) and "state_dict" in st: st = st["state_dict"]
    model.load_state_dict(st, strict=False)
    model = model.to("cuda").eval()
    nagi = Nagi(model)
    preds, lats = {}, []
    for i, r in enumerate(rows):
        qs = {qid: {"type": q.get("type","choice"), "instructions": q.get("instructions",""), "criteria": q.get("criteria")}
              for qid, q in (r.get("questions") or {}).items()}
        torch.cuda.synchronize(); t0 = time.perf_counter()
        out = nagi.system_one(state=r.get("state"), questions=qs)
        torch.cuda.synchronize(); lats.append((time.perf_counter()-t0)*1000)
        preds[r["id"]] = {qid: a.get("probabilities") or {} for qid, a in out["answers"].items()}
        if (i+1) % 500 == 0: print("smol", i+1, flush=True)
    results["Nagi-Smol"] = save("smol", preds, lats, {"model": "nagisanzeninz/nagi-smol-v0"})
    del model, nagi; torch.cuda.empty_cache()
except Exception as e:
    traceback.print_exc()
    results["Nagi-Smol"] = {"error": f"{type(e).__name__}: {e}"}

# ---------- Big (PiSSA) ----------
try:
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from nagi.render import label_for
    tok = AutoTokenizer.from_pretrained("Qwen/Qwen3.5-4B")
    base = AutoModelForCausalLM.from_pretrained("Qwen/Qwen3.5-4B", dtype=torch.bfloat16, attn_implementation="eager")
    model = PeftModel.from_pretrained(base, "/results/hailg_g1/pissa")
    model = model.merge_and_unload().to("cuda").eval()
    letter_ids = [tok.encode(label_for(i), add_special_tokens=False)[0] for i in range(26)]
    def qwen_letter_preds(m, tag):
        preds, lats = {}, []
        for i, r in enumerate(rows):
            qid = next(iter(r.get("questions") or {"label":1}))
            prompt, keys = render_nagi_prompt(r, qid)
            enc = tok(prompt, return_tensors="pt", truncation=True, max_length=768).to("cuda")
            torch.cuda.synchronize(); t0 = time.perf_counter()
            logits = m(**enc).logits[0, -1]
            torch.cuda.synchronize(); lats.append((time.perf_counter()-t0)*1000)
            K = min(len(keys), 26)
            raw = [float(logits[letter_ids[j]]) for j in range(K)]
            mx = max(raw); ex = [math.exp(z-mx) for z in raw]; s = sum(ex)
            preds[r["id"]] = {qid: {keys[j]: ex[j]/s for j in range(K)}}
            if (i+1) % 500 == 0: print(tag, i+1, flush=True)
        return preds, lats
    preds, lats = qwen_letter_preds(model, "big")
    results["Nagi-Big"] = save("big", preds, lats, {"model": "nagisanzeninz/nagi-big-v0"})
    del model; torch.cuda.empty_cache()

    # ---------- OpenJev = frozen Qwen3.5-4B letter-logit (SemIf) ----------
    base2 = AutoModelForCausalLM.from_pretrained("Qwen/Qwen3.5-4B", dtype=torch.bfloat16, attn_implementation="eager").to("cuda").eval()
    preds, lats = qwen_letter_preds(base2, "openjev")
    results["OpenJev"] = save("openjev", preds, lats, {"model": "Qwen/Qwen3.5-4B frozen (SemIf letter-logits)"})
    del base2; torch.cuda.empty_cache()
except Exception as e:
    traceback.print_exc()
    if "Nagi-Big" not in results:
        results["Nagi-Big"] = {"error": f"{type(e).__name__}: {e}"}
    if "OpenJev" not in results:
        results["OpenJev"] = {"error": f"{type(e).__name__}: {e}"}

# ---------- Laya ----------
try:
    import laya
    agent = laya.load("convaiinnovations/laya", device="cuda")
    preds, lats = {}, []
    for i, r in enumerate(rows):
        qs = {qid: {"type": q.get("type","choice"), "instructions": q.get("instructions",""), "criteria": q.get("criteria")}
              for qid, q in (r.get("questions") or {}).items()}
        torch.cuda.synchronize(); t0 = time.perf_counter()
        try:
            res = agent.predict(r.get("state"), qs)
        except Exception:
            # try alternate signature
            res = agent.predict(state=r.get("state"), questions=qs)
        torch.cuda.synchronize(); lats.append((time.perf_counter()-t0)*1000)
        ans = (res or {}).get("answers") or res or {}
        out = {}
        for qid, a in ans.items():
            if isinstance(a, dict) and a.get("probabilities"):
                out[qid] = a["probabilities"]
            elif isinstance(a, dict) and "noul" in a:
                p = float(a["noul"]); out[qid] = {"true": p, "false": 1-p}
        preds[r["id"]] = out
        if (i+1) % 500 == 0: print("laya", i+1, flush=True)
    results["Laya"] = save("laya", preds, lats, {"model": "convaiinnovations/laya"})
except Exception as e:
    traceback.print_exc()
    results["Laya"] = {"error": f"{type(e).__name__}: {e}"}

# ---------- Jev (API) ----------
try:
    key = os.environ.get("TYPESAFE_API_KEY", "")
    if not key:
        # try nagi env file if bundled
        results["Jev"] = {"error": "no TYPESAFE_API_KEY"}
    else:
        import urllib.request
        from urllib.request import Request, urlopen
        preds, lats = {}, []
        for i, r in enumerate(rows):
            questions = {}
            for qid, q in (r.get("questions") or {}).items():
                crit = q.get("criteria")
                if q.get("type") == "choice" and isinstance(crit, dict):
                    questions[qid] = {"type": "choice", "instructions": q.get("instructions",""), "criteria": crit}
                elif q.get("type") == "score":
                    questions[qid] = {"type": "score", "instructions": q.get("instructions",""), "criteria": crit if isinstance(crit, list) else list(range(4))}
                else:
                    questions[qid] = {"type": "noul", "instructions": q.get("instructions","")}
            body = json.dumps({"state": r.get("state"), "model": "jev-latest", "questions": questions}).encode()
            t0 = time.perf_counter()
            ok = False
            for attempt in range(5):
                try:
                    req = Request("https://api.typesafe.ai/v1/systemone", data=body,
                                  headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
                    with urlopen(req, timeout=90) as resp:
                        data = json.loads(resp.read().decode())
                    ok = True
                    break
                except Exception:
                    if attempt < 4: time.sleep(0.4 * 2**attempt)
            lats.append((time.perf_counter()-t0)*1000 if ok else None)
            if not ok: continue
            out = {}
            for qid, ans in (data.get("answers") or {}).items():
                probs = (ans.get("probabilities") or {}) if isinstance(ans, dict) else {}
                if probs:
                    out[qid] = {str(k): float(v) for k, v in probs.items()}
                elif isinstance(ans, dict) and "noul" in ans:
                    p = float(ans["noul"]); out[qid] = {"true": p, "false": 1-p}
            preds[r["id"]] = out
            if (i+1) % 200 == 0: print("jev", i+1, flush=True)
        results["Jev"] = save("jev", preds, lats, {"model": "jev-latest"})
except Exception as e:
    traceback.print_exc()
    results["Jev"] = {"error": f"{type(e).__name__}: {e}"}

(OUT / "summary.json").write_text(json.dumps(results, indent=2))
print("DONE", json.dumps(results, indent=2)[:4000], flush=True)
'''


@app.function(
    image=image,
    gpu="H100",
    timeout=60 * 60 * 3,
    volumes={"/results": vol},
    memory=64000,
)
def run_bench(bundle_b64: str, tag: str, typesafe_key: str = "") -> dict:
    import subprocess
    from pathlib import Path as P

    root = P("/root/nagi")
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    tarfile.open(fileobj=io.BytesIO(base64.b64decode(bundle_b64)), mode="r:gz").extractall(root.parent)
    env = {
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": f"{root}/src",
        "HF_HOME": "/root/hf",
        "TRANSFORMERS_CACHE": "/root/hf",
        "NAGI_BUDGET_USD": "300",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
    }
    if typesafe_key:
        env["TYPESAFE_API_KEY"] = typesafe_key
    inner = INNER.replace("bench5_TAG", f"bench5_{tag}")
    (root / "scripts" / "_bench5_inner.py").write_text(inner)
    cmd = f"cd {root} && python scripts/_bench5_inner.py"
    print("+", cmd, flush=True)
    r = subprocess.run(cmd, shell=True, env=env)
    vol.commit()
    out = {}
    sp = P(f"/results/bench5_{tag}/summary.json")
    if sp.exists():
        out = json.loads(sp.read_text())
    return {"status": "ok" if r.returncode == 0 else "failed", "code": r.returncode, "results": out}


@app.local_entrypoint()
def main(tag: str = "b5"):
    ROOT = Path(__file__).resolve().parents[1]
    names = ["data/gold_ltout.jsonl"]
    for p in (ROOT / "src").rglob("*.py"):
        names.append(str(p.relative_to(ROOT)))
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel in names:
            p = ROOT / rel
            if p.exists():
                tar.add(p, arcname=f"nagi/{rel}")
    payload = base64.b64encode(buf.getvalue()).decode()
    # TYPESAFE from local .env — never commit
    key = ""
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            if line.startswith("TYPESAFE_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not key:
        ja = Path("/Users/quanduong/.zcode/workspace/default/jev-ab/.env.local")
        if ja.exists():
            for line in ja.read_text().splitlines():
                if line.startswith("TYPESAFE_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    print(f"bundle {len(payload)/1e6:.2f}MB tag={tag} → nagi-bench5 / H100 jev_key={'yes' if key else 'NO'}", flush=True)
    res = run_bench.remote(payload, tag, key)
    out = ROOT / f"runs/bench5_{tag}_result.json"
    out.write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2)[:5000])
    print("WROTE", out)
