#!/usr/bin/env python3
"""Second real global-phase fault: PR #16201 (UnrollForLoops double-counts a loop body's global phase).

Builds/reuses the fix and parent, runs the fix's own trigger (a for-loop whose body carries a
global phase) through UnrollForLoops in isolation, and reports the tracked global_phase on each
build plus whether the two outputs are equal up to a global phase. Expected: the parent records a
different global_phase than the fix (the fault), while the applied unitaries are equal modulo global
phase (so an output-equivalence oracle is blind) -> an output-invisible global-phase regression.
Run from repo root:  python scripts/verify_16201.py
"""
import json, os, subprocess, sys, math
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "src"))
from source_validate_mining import build_event

FIX    = "2b4c81d4a8de182376eca71195474d86af7e7b33"
PARENT = FIX + "^"

SNIPPET = r'''
import json, math
import numpy as np
res = {}
try:
    from qiskit import QuantumCircuit
    from qiskit.transpiler import PassManager
    from qiskit.transpiler.passes import UnrollForLoops
    from qiskit.quantum_info import Operator
    body = QuantumCircuit(1, global_phase=math.pi / 7)
    body.x(0)
    qc = QuantumCircuit(1)
    qc.for_loop(range(3), None, body, [0], [])
    out = PassManager([UnrollForLoops()]).run(qc)
    res["global_phase"] = float(out.global_phase)
    op = Operator(out).data
    res["u_re"] = np.round(op.real, 6).tolist()
    res["u_im"] = np.round(op.imag, 6).tolist()
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

def run(py):
    p = subprocess.run([str(py), "-c", SNIPPET], capture_output=True, text=True)
    for line in (p.stdout or "").splitlines():
        if line.startswith("RESULT_JSON:"):
            return json.loads(line[len("RESULT_JSON:"):])
    return {"error": "no result; stderr=" + (p.stderr or "")[-200:]}

def equiv_mod_phase(a, b):
    A = np.array(a["u_re"]) + 1j * np.array(a["u_im"])
    B = np.array(b["u_re"]) + 1j * np.array(b["u_im"])
    M = A.conj().T @ B
    ph = M[0, 0]
    return abs(abs(ph) - 1) < 1e-6 and np.allclose(M, ph * np.eye(M.shape[0]), atol=1e-6)

def main():
    fpy = ensure_build(FIX, "sv-16201-fix"); ppy = ensure_build(PARENT, "sv-16201-bug")
    if not fpy or not ppy:
        print("build failed"); return 1
    fix = run(fpy); bug = run(ppy)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "verify_16201.json").write_text(json.dumps({"fix": fix, "parent": bug}, indent=2))
    print("=" * 62)
    if "error" in fix or "error" in bug:
        print("worker error:\n  fix:", fix.get("error"), "\n  parent:", bug.get("error")); return 1
    gf, gb = fix["global_phase"], bug["global_phase"]
    delta = abs((gf - gb + math.pi) % (2 * math.pi) - math.pi)
    blind = equiv_mod_phase(fix, bug)
    print(f"fix    global_phase = {gf:.4f}")
    print(f"parent global_phase = {gb:.4f}   (delta = {delta:.4f} rad)")
    print(f"applied outputs equal modulo global phase (output oracle blind): {blind}")
    if delta > 1e-3 and blind:
        print("VERDICT: #16201 output-INVISIBLE global-phase fault SOURCE-VERIFIED")
        print("         (parent records a different global phase; the phase oracle detects it,")
        print("          the output-equivalence oracle does not).")
    else:
        print(f"VERDICT: inconclusive (delta={delta:.4f}, blind={blind}).")
    print("wrote results/verify_16201.json")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
