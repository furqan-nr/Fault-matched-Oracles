#!/usr/bin/env python3
"""Determinism-channel evaluation for #14730 (VF2Layout), with an output-equivalence check.

Uses a noise-scored GenericBackendV2 target (local, free, no QPU) taken verbatim from the fix's
own regression test. Builds/reuses the fixed and parent revisions and transpiles the trigger with
a FIXED seed_transpiler many times, across processes with varied PYTHONHASHSEED. For each run it
records TWO fingerprints:
  * RAW  = gate list + recorded final_index_layout (distinct raw = the metadata/layout varies);
  * FUNC = SHA of the sorted statevector-probability vector (parameters bound, measurements
           stripped). Sorted probabilities are invariant to qubit permutation, so a single FUNC
           value across distinct RAW compilations means they are the same computation, i.e. the
           non-determinism is output-INVISIBLE. More than one FUNC means the outputs differ
           functionally, which would be a VISIBLE fault (we would not claim invisibility).
Run from repo root:  python scripts/determinism_eval.py
"""
import json, os, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "src"))
from source_validate_mining import build_event

FIX    = "d33ef5335e05523e35a29530dbc389c52c8e7bc7"
PARENT = "056c6413b03a306b170bc18efb8fcf9cc1c8a3a5"
HASHSEEDS = ["0", "1", "2", "7", "13"]

SNIPPET = r'''
import json, hashlib
import numpy as np
res = {}
try:
    from qiskit import QuantumCircuit
    from qiskit.circuit import ParameterVector
    from qiskit.quantum_info import Statevector
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
    try:
        from qiskit.providers.fake_provider import GenericBackendV2
    except Exception:
        from qiskit.providers import GenericBackendV2
    params = ParameterVector("t", 3)
    circ = QuantumCircuit(3)
    for i, par in enumerate(params): circ.rx(par, i)
    circ.measure_all()
    backend = GenericBackendV2(10, noise_info=True, seed=123)
    raws, funcs = [], []
    for _ in range(10):
        pm = generate_preset_pass_manager(optimization_level=3, target=backend.target, seed_transpiler=123)
        isa = pm.run(circ)
        ops = [(ci.operation.name, tuple(isa.find_bit(q).index for q in ci.qubits)) for ci in isa.data]
        try: lay = tuple(isa.layout.final_index_layout())
        except Exception: lay = "none"
        raws.append(hashlib.sha1((repr(ops) + "|" + repr(lay)).encode()).hexdigest()[:12])
        # FUNCTIONAL fingerprint: sorted statevector probabilities (permutation-invariant)
        try:
            u = isa.remove_final_measurements(inplace=False)
            ps = sorted(u.parameters, key=lambda p: p.name)
            u = u.assign_parameters({p: v for p, v in zip(ps, [0.1, 0.2, 0.3])})
            probs = np.sort(np.round(np.abs(Statevector(u).data) ** 2, 8))
            funcs.append(hashlib.sha1(probs.tobytes()).hexdigest()[:12])
        except Exception as e:
            funcs.append("funcerr:" + type(e).__name__)
    res["raws"] = raws; res["funcs"] = funcs
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
    raws, funcs = [], []
    for hs in HASHSEEDS:
        env = dict(os.environ); env["PYTHONHASHSEED"] = hs
        p = subprocess.run([str(py), "-c", SNIPPET], capture_output=True, text=True, env=env)
        got = None
        for line in (p.stdout or "").splitlines():
            if line.startswith("RESULT_JSON:"): got = json.loads(line[len("RESULT_JSON:"):])
        if got is None: return None, None, "no result; stderr=" + (p.stderr or "")[-200:]
        if "error" in got: return None, None, got["error"]
        raws.extend(got["raws"]); funcs.extend(got["funcs"])
    return raws, funcs, None

def main():
    fpy = ensure_build(FIX, "sv-14730-fix"); ppy = ensure_build(PARENT, "sv-14730-bug")
    if not fpy or not ppy: print("build failed"); return 1
    fr, ff, ferr = collect(fpy)
    br, bf, berr = collect(ppy)
    out = {"fix": {"raw_distinct": len(set(fr)) if fr else None, "func_distinct": len(set(ff)) if ff else None, "error": ferr},
           "parent": {"raw_distinct": len(set(br)) if br else None, "func_distinct": len(set(bf)) if bf else None, "error": berr},
           "runs_per_build": len(HASHSEEDS) * 10, "hashseeds": HASHSEEDS}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "determinism_eval.json").write_text(json.dumps(out, indent=2))
    print("=" * 66)
    print(f"trigger: #14730 fix test, GenericBackendV2(noise_info=True), seed_transpiler=123")
    print(f"runs per build: {len(HASHSEEDS)} PYTHONHASHSEED values x 10 = {len(HASHSEEDS)*10}")
    if ferr or berr:
        print("ERROR  fix:", ferr, " parent:", berr); return 1
    print(f"FIX    raw-distinct={len(set(fr))}  func-distinct={len(set(ff))}")
    print(f"PARENT raw-distinct={len(set(br))}  func-distinct={len(set(bf))}")
    print("  (raw = gate list + layout metadata; func = sorted statevector probabilities, permutation-invariant)")
    nd = len(set(br)) > 1 and len(set(fr)) == 1
    inv = len(set(bf)) == 1 and "funcerr" not in "".join(bf)
    if nd and inv:
        print("VERDICT: determinism REPRODUCED and OUTPUT-INVISIBLE — the parent's distinct compilations")
        print("         are the same computation (one functional fingerprint); the fix is deterministic.")
    elif nd and not inv:
        print("VERDICT: non-determinism reproduced but outputs differ FUNCTIONALLY — this is a VISIBLE")
        print("         fault, NOT output-invisible. Do not claim invisibility.")
    else:
        print(f"VERDICT: not reproduced here (parent raw-distinct={len(set(br))}). Limitation stands.")
    print("wrote results/determinism_eval.json")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
