#!/usr/bin/env python3
"""Second real determinism fault: PR #16237 (ConsolidateBlocks picks the basis gate non-deterministically).

Builds/reuses the fix and parent and, across processes with varied PYTHONHASHSEED, records the
basis_gate_name ConsolidateBlocks selects for two basis sets (the fix's own test cases). A fix build
selects the same gate every time; the parent selects different gates across hash seeds. Both choices
consolidate a block into equivalent circuits, so the non-determinism is output-invisible.
Run from repo root:  python scripts/verify_16237.py
"""
import json, os, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "src"))
from source_validate_mining import build_event

FIX    = "3b9a64fdd4353834d83a6e393a76a2ee657800f2"
PARENT = FIX + "^"
HASHSEEDS = ["0", "1", "2", "7", "13", "23"]

SNIPPET = r'''
import json
res = {}
try:
    from qiskit.transpiler.passes import ConsolidateBlocks
    names = {}
    for basis in [["ryy", "rzz"], ["ecr", "cx", "cz"]]:
        names[",".join(basis)] = ConsolidateBlocks(basis_gates=basis).basis_gate_name
    res["names"] = names
except Exception as e:
    res["error"] = type(e).__name__ + ": " + str(e)[:200]
print("RESULT_JSON:" + json.dumps(res))
'''

def ensure_build(sha, eid):
    venv = ROOT / "environment" / "_builds" / eid / "venv"
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if py.exists():
        print(f"reusing existing build {eid}"); return py
    return build_event(sha, eid)

def collect(py):
    per_basis = {}
    for hs in HASHSEEDS:
        env = dict(os.environ); env["PYTHONHASHSEED"] = hs
        p = subprocess.run([str(py), "-c", SNIPPET], capture_output=True, text=True, env=env)
        got = None
        for line in (p.stdout or "").splitlines():
            if line.startswith("RESULT_JSON:"): got = json.loads(line[len("RESULT_JSON:"):])
        if got is None: return None, "no result; stderr=" + (p.stderr or "")[-200:]
        if "error" in got: return None, got["error"]
        for b, name in got["names"].items():
            per_basis.setdefault(b, []).append(name)
    return per_basis, None

def main():
    fpy = ensure_build(FIX, "sv-16237-fix"); ppy = ensure_build(PARENT, "sv-16237-bug")
    if not fpy or not ppy:
        print("build failed"); return 1
    fx, ferr = collect(fpy); bg, berr = collect(ppy)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "verify_16237.json").write_text(json.dumps({"fix": fx, "parent": bg}, indent=2))
    print("=" * 62)
    print(f"runs per build: {len(HASHSEEDS)} PYTHONHASHSEED values")
    if ferr or berr:
        print("ERROR fix:", ferr, " parent:", berr); return 1
    reproduced = False
    for b in fx:
        fset, bset = set(fx[b]), set(bg[b])
        print(f"basis [{b}]  fix -> {sorted(fset)} (distinct {len(fset)})   parent -> {sorted(bset)} (distinct {len(bset)})")
        if len(bset) > 1 and len(fset) == 1:
            reproduced = True
    if reproduced:
        print("VERDICT: #16237 determinism fault SOURCE-VERIFIED (parent's basis-gate choice varies")
        print("         across hash seeds, the fix is constant; both choices are equivalent consolidations,")
        print("         so the non-determinism is output-invisible).")
    else:
        print("VERDICT: not reproduced here (basis choice stable on both).")
    print("wrote results/verify_16237.json")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
