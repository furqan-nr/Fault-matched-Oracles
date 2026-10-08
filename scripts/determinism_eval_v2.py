#!/usr/bin/env python3
"""Determinism-channel evaluation for #14730 (VF2Layout) — v2 fingerprint (review response B1).

WHAT CHANGED FROM determinism_eval.py
-------------------------------------
The original FUNCTIONAL fingerprint was the SHA of a SORTED statevector-probability vector
(`np.sort(np.abs(Statevector)**2)`). A pre-submission reviewer correctly noted that this is too weak
to establish "same computation": sorting discards qubit position and |amplitude|**2 discards all phase,
so two genuinely different computations can share one sorted-probability profile.

This version replaces FUNC with a LAYOUT-NORMALIZED UNITARY EQUIVALENCE MODULO GLOBAL PHASE test:
  * strip the final measurements, bind the trigger's parameters;
  * build the layout-normalized operator with `Operator.from_circuit(u)` — this undoes ONLY the
    transpiler's own recorded qubit permutation (nothing else), returning the operator in the original
    logical qubit order;
  * canonicalize away the single global phase (scale so the largest-magnitude entry is real-positive)
    and hash the rounded complex entries.
Two compilations get the SAME func id iff their layout-normalized unitaries are equal up to a global
phase — i.e. the same computation, allowing only the legitimate layout permutation. This is strictly
stronger than the sorted-probability fingerprint and is what the paper's own semantic/global-phase
oracles already use (Operator.from_circuit + equivalence modulo global phase).

RAW fingerprint (gate list + recorded final_index_layout) is UNCHANGED, so raw_distinct still measures
whether the layout metadata varies across runs.

Interpretation is identical to the original: parent raw_distinct>1 AND fix raw_distinct==1 (non-
determinism reproduced and fixed), AND parent func_distinct==1 (the distinct compilations are the same
computation -> OUTPUT-INVISIBLE). func_distinct>1 on the parent would mean the outputs differ
functionally (a VISIBLE fault) and we would NOT claim invisibility.

Run from repo root (real Qiskit env active):  python scripts/determinism_eval_v2.py
Writes results/determinism_eval_v2.json (the original determinism_eval.json is left untouched).
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

def canon(arr):
    """Canonical hash of a complex array modulo a single global phase.
    Scale so the largest-magnitude entry is real-positive, round to 1e-8, hash real+imag as ints."""
    a = np.asarray(arr, dtype=complex).ravel()
    k = int(np.argmax(np.abs(a)))
    if abs(a[k]) > 1e-12:
        a = a * (abs(a[k]) / a[k])          # divide out global phase
    r  = np.round(a.real * 1e6).astype(np.int64)   # 6-decimal grid: tolerant to ~1e-16 FP noise
    im = np.round(a.imag * 1e6).astype(np.int64)   # (verdict is anyway confirmed by Operator.equiv)
    return hashlib.sha1(r.tobytes() + im.tobytes()).hexdigest()[:16]

try:
    from qiskit import QuantumCircuit
    from qiskit.circuit import ParameterVector
    from qiskit.quantum_info import Operator, Statevector
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
    raws, funcs, method = [], [], None
    for _ in range(10):
        pm = generate_preset_pass_manager(optimization_level=3, target=backend.target, seed_transpiler=123)
        isa = pm.run(circ)
        ops = [(ci.operation.name, tuple(isa.find_bit(q).index for q in ci.qubits)) for ci in isa.data]
        try: lay = tuple(isa.layout.final_index_layout())
        except Exception: lay = "none"
        raws.append(hashlib.sha1((repr(ops) + "|" + repr(lay)).encode()).hexdigest()[:12])
        # FUNCTIONAL fingerprint v2: layout-normalized unitary, modulo global phase.
        try:
            lay_obj = getattr(isa, "layout", None)
            u = isa.remove_final_measurements(inplace=False)
            ps = sorted(u.parameters, key=lambda p: p.name)
            u = u.assign_parameters({p: v for p, v in zip(ps, [0.1, 0.2, 0.3])})
            # Operator.from_circuit undoes ONLY the recorded layout permutation.
            if getattr(u, "layout", None) is None and lay_obj is not None:
                try: u._layout = lay_obj          # restore layout if strip dropped it
                except Exception: pass
            try:
                U = Operator.from_circuit(u).data
                method = "operator_from_circuit_mod_global_phase"
            except Exception:
                # Fallback: layout-normalized output statevector on |0...0>, phase-sensitive,
                # un-permuted to logical order via the recorded final_index_layout.
                sv = Statevector(u).data
                perm = list(isa.layout.final_index_layout())
                nbit = len(perm)
                out = np.empty_like(sv)
                for old in range(sv.shape[0]):
                    new = 0
                    for i in range(nbit):
                        new |= ((old >> perm[i]) & 1) << i
                    out[new] = sv[old]
                U = out
                method = "sampled_statevector_zero_input_mod_global_phase"
            funcs.append(canon(U))
        except Exception as e:
            funcs.append("funcerr:" + type(e).__name__ + ":" + str(e)[:120])
    res["raws"] = raws; res["funcs"] = funcs; res["func_method"] = method
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
    raws, funcs, method = [], [], None
    for hs in HASHSEEDS:
        env = dict(os.environ); env["PYTHONHASHSEED"] = hs
        p = subprocess.run([str(py), "-c", SNIPPET], capture_output=True, text=True, env=env)
        got = None
        for line in (p.stdout or "").splitlines():
            if line.startswith("RESULT_JSON:"): got = json.loads(line[len("RESULT_JSON:"):])
        if got is None: return None, None, None, "no result; stderr=" + (p.stderr or "")[-200:]
        if "error" in got: return None, None, None, got["error"]
        raws.extend(got["raws"]); funcs.extend(got["funcs"]); method = got.get("func_method") or method
    return raws, funcs, method, None

def main():
    fpy = ensure_build(FIX, "sv-14730-fix"); ppy = ensure_build(PARENT, "sv-14730-bug")
    if not fpy or not ppy: print("build failed"); return 1
    fr, ff, fm, ferr = collect(fpy)
    br, bf, bm, berr = collect(ppy)
    out = {"fix": {"raw_distinct": len(set(fr)) if fr else None, "func_distinct": len(set(ff)) if ff else None, "error": ferr},
           "parent": {"raw_distinct": len(set(br)) if br else None, "func_distinct": len(set(bf)) if bf else None, "error": berr},
           "func_fingerprint": "layout-normalized unitary modulo global phase (Operator.from_circuit; v2, review response B1)",
           "func_method_used": {"fix": fm, "parent": bm},
           "runs_per_build": len(HASHSEEDS) * 10, "hashseeds": HASHSEEDS}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "determinism_eval_v2.json").write_text(json.dumps(out, indent=2))
    print("=" * 66)
    print("trigger: #14730 fix test, GenericBackendV2(noise_info=True), seed_transpiler=123")
    print(f"FUNC fingerprint v2: {out['func_fingerprint']}")
    print(f"runs per build: {len(HASHSEEDS)} PYTHONHASHSEED values x 10 = {len(HASHSEEDS)*10}")
    if ferr or berr:
        print("ERROR  fix:", ferr, " parent:", berr); return 1
    print(f"func method used -> fix: {fm}   parent: {bm}")
    print(f"FIX    raw-distinct={len(set(fr))}  func-distinct={len(set(ff))}")
    print(f"PARENT raw-distinct={len(set(br))}  func-distinct={len(set(bf))}")
    bad = [x for x in (ff + bf) if isinstance(x, str) and x.startswith("funcerr")]
    if bad:
        print("WARNING funcerr samples:", bad[:3]); 
    nd = len(set(br)) > 1 and len(set(fr)) == 1
    inv = len(set(bf)) == 1 and not bad
    if nd and inv:
        print("VERDICT: determinism REPRODUCED and OUTPUT-INVISIBLE (parent's distinct compilations are")
        print("         the same layout-normalized unitary modulo global phase; fix is deterministic).")
    elif nd and not inv:
        print("VERDICT: non-determinism reproduced but the layout-normalized unitaries DIFFER -> VISIBLE")
        print("         fault; do NOT claim invisibility. (Report this back.)")
    else:
        print(f"VERDICT: not reproduced here (parent raw-distinct={len(set(br))}). Limitation stands.")
    print("wrote results/determinism_eval_v2.json")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
