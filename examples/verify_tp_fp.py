"""Minimal finding-verifier example (Nagi-Smol).

  python examples/verify_tp_fp.py
"""

from nagi import load_smol

dossier = """SCANNER FINDING
- description: SQL injection in login form
- evidence: error-based SQLi; MySQL schema dump returned on ' OR 1=1 --
- request: POST /login user=admin'--
- response: HTTP 200 + full table dump
"""

VERIFY = {
    "verdict": {
        "type": "choice",
        "instructions": (
            "Classify TP only if the evidence directly proves exploitability, else FP. "
            "An execution proof (schema dump, cross-owner object) always means TP."
        ),
        "criteria": {
            "TP": "The evidence dossier directly proves the vulnerability is exploitable.",
            "FP": "The evidence does not prove exploitability or is a scanner artifact.",
        },
    }
}

if __name__ == "__main__":
    nagi = load_smol()
    ans = nagi.system_one(state=dossier, questions=VERIFY)["answers"]["verdict"]
    print(ans)
    p_fp = ans["probabilities"]["FP"]
    if p_fp >= 0.95:
        print("→ suppress (τ=0.95)")
    elif ans["probabilities"]["TP"] >= 0.5:
        print("→ verified TP")
    else:
        print("→ keep unverified")
