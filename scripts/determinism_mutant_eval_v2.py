#!/usr/bin/env python3
"""Determinism-channel synthetic mutant family — v2 fingerprint (review response B1).

Same mutant mechanism as determinism_mutant_eval.py (swap one adjacent pair of DISJOINT-qubit, hence
commuting, instructions via a PYTHONHASHSEED-dependent 2-element string-set tie-break), but the
FUNCTIONAL fingerprint is upgraded from a SORTED statevector-probability vector to a LAYOUT-NORMALIZED
UNITARY EQUIVALENCE MODULO GLOBAL PHASE test (see the header of determinism_eval_v2.py for why the old
fingerprint was too weak). Because the swapped instructions act on disjoint qubits, the mutation is
output-invisible BY CONSTRUCTION: the compiled circuit's unitary is provably unchanged, so the v2
func fingerprint MUST remain constant (func_distinct == 1) while only the RAW instruction sequence
varies (raw_distinct > 1). The control (no reorder) must show raw_distinct == 1.

Run from repo root (real Qiskit env active):  python scripts/determinism_mutant_eval_v2.py
Writes results/determinism_mutant_eval_v2.json (original determinism_mutant_eval.json untouched).

NOTE: smoke-test one circuit first and confirm `out.data[i] = instr` assignment works on your Qiskit
version (2.1-2.4 band, environment/ENV.md); report any error rather than trusting a partial run.
"""
import json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HASHSEEDS = ["0", "1", "2", "7", "13", "23"]
REPEATS_PER_SEED = 5

CIRCUITS = {
    "ghz4": ("ghz", 4), "ghz5": ("ghz", 5), "ghz6": ("ghz", 6),
    "qft4": ("qft", 4), "qft5": ("qft", 5), "qft6": ("qft", 6),
}

SNIPPET_TEMPLATE = r'''
import json, hashlib
import numpy as np
res = {}

def canon(arr):
    a = np.asarray(arr, dtype=complex).ravel()
    # Stable pivot: FIRST entry whose magnitude exceeds half the maximum.  (argmax is unstable for
    # unitaries with many equal-magnitude entries, e.g. QFT, where FP noise of ~1e-16 flips which
    # entry is "largest" and so changes the phase reference between two functionally equal circuits.)
    k = int(np.argmax(np.abs(a) > 0.5 * np.abs(a).max()))
    if abs(a[k]) > 1e-12:
        a = a * (abs(a[k]) / a[k])          # divide out global phase
    r  = np.round(a.real * 1e6).astype(np.int64)   # 6-decimal grid: tolerant to ~1e-16 FP noise
    im = np.round(a.imag * 1e6).astype(np.int64)   # (verdict is anyway confirmed by Operator.equiv)
    return hashlib.sha1(r.tobytes() + im.tobytes()).hexdigest()[:16]

try:
    from qiskit import QuantumCircuit
    from qiskit.circuit.library import QFT
    from qiskit.quantum_info import Operator
    from qiskit.transpiler import CouplingMap
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

    KIND = "%(kind)s"; N = %(n)d; MUTANT = %(mutant)s
    if KIND == "ghz":
        circ = QuantumCircuit(N); circ.h(0)
        for i in range(N - 1): circ.cx(i, i + 1)
    else:
        circ = QuantumCircuit(N); circ.compose(QFT(N), inplace=True)

    pm = generate_preset_pass_manager(optimization_level=3, coupling_map=CouplingMap.from_line(N),
                                       basis_gates=["cx", "rz", "sx", "x"], seed_transpiler=1234)
    out = pm.run(circ)
    try:
        U_REF = Operator.from_circuit(out).data     # unmutated reference, captured before any reordering
    except Exception:
        U_REF = Operator(out).data

    if MUTANT:
        data = list(out.data)
        for i in range(len(data) - 1):
            qa = set(out.find_bit(q).index for q in data[i].qubits)
            qb = set(out.find_bit(q).index for q in data[i + 1].qubits)
            if qa and qb and qa.isdisjoint(qb):
                pick = next(iter({"keep", "swap"}))   # PYTHONHASHSEED-dependent set-iteration tie-break
                if pick == "swap":
                    data[i], data[i + 1] = data[i + 1], data[i]
                break
        for i, instr in enumerate(data):
            out.data[i] = instr

    ops = [(ci.operation.name, tuple(out.find_bit(q).index for q in ci.qubits)) for ci in out.data]
    raw = hashlib.sha1(repr(ops).encode()).hexdigest()[:12]
    # FUNCTIONAL fingerprint v2: layout-normalized unitary modulo global phase.
    try:
        U = Operator.from_circuit(out).data
    except Exception:
        U = Operator(out).data
    # Functional fingerprint: "REF" when the circuit is equivalent modulo global phase (Qiskit's own
    # Operator.equiv) to the UNMUTATED compiled circuit of this same process; otherwise the canonical hash.
    # This removes any dependence of the verdict on rounding-grid boundaries.
    try:
        func = "REF" if Operator(U).equiv(Operator(U_REF)) else canon(U)
    except Exception:
        func = canon(U)
    res["raw"] = raw; res["func"] = func
except Exception as e:
    res["error"] = type(e).__name__ + ": " + str(e)[:300]
print("RESULT_JSON:" + json.dumps(res))
'''


def run_trial(kind, n, mutant, hashseed):
    snippet = SNIPPET_TEMPLATE % {"kind": kind, "n": n, "mutant": "True" if mutant else "False"}
    env = dict(os.environ); env["PYTHONHASHSEED"] = hashseed
    p = subprocess.run([sys.executable, "-c", snippet], capture_output=True, text=True, env=env)
    for line in (p.stdout or "").splitlines():
        if line.startswith("RESULT_JSON:"):
            return json.loads(line[len("RESULT_JSON:"):])
    return {"error": "no result; stderr=" + (p.stderr or "")[-300:]}


def collect(kind, n, mutant):
    raws, funcs, errs = [], [], []
    for hs in HASHSEEDS:
        for _ in range(REPEATS_PER_SEED):
            got = run_trial(kind, n, mutant, hs)
            if "error" in got:
                errs.append(got["error"]); continue
            raws.append(got["raw"]); funcs.append(got["func"])
    return raws, funcs, errs


def main():
    rows = []
    for cname, (kind, n) in CIRCUITS.items():
        m_raw, m_func, m_err = collect(kind, n, True)
        c_raw, c_func, c_err = collect(kind, n, False)
        row = {
            "circuit": cname,
            "mutant":  {"raw_distinct": len(set(m_raw)), "func_distinct": len(set(m_func)),
                        "runs": len(m_raw), "errors": m_err},
            "control": {"raw_distinct": len(set(c_raw)), "func_distinct": len(set(c_func)),
                        "runs": len(c_raw), "errors": c_err},
        }
        row["sensitivity_hit"] = (row["mutant"]["raw_distinct"] > 1 and row["mutant"]["func_distinct"] == 1)
        row["specificity_hit"] = (row["control"]["raw_distinct"] == 1)
        rows.append(row)

    n_circ = len(rows)
    n_sens = sum(1 for r in rows if r["sensitivity_hit"])
    n_spec = sum(1 for r in rows if r["specificity_hit"])
    summary = {"circuits": n_circ, "sensitivity_hits": n_sens, "specificity_hits": n_spec,
               "func_fingerprint": "layout-normalized unitary modulo global phase (Operator.from_circuit; v2, review response B1)",
               "hashseeds": HASHSEEDS, "repeats_per_seed": REPEATS_PER_SEED,
               "runs_per_condition_per_circuit": len(HASHSEEDS) * REPEATS_PER_SEED}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "determinism_mutant_eval_v2.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2))

    print("=" * 66)
    print("DETERMINISM-CHANNEL SYNTHETIC MUTANT FAMILY  (v2 func fingerprint)")
    print(f"func = {summary['func_fingerprint']}")
    print(f"{len(HASHSEEDS)} PYTHONHASHSEED values x {REPEATS_PER_SEED} repeats = "
          f"{len(HASHSEEDS) * REPEATS_PER_SEED} runs per condition per circuit, {n_circ} circuits")
    for r in rows:
        print(f"  {r['circuit']:6s} mutant raw_distinct={r['mutant']['raw_distinct']:2d} "
              f"func_distinct={r['mutant']['func_distinct']}  "
              f"control raw_distinct={r['control']['raw_distinct']}  "
              f"sensitivity={'HIT' if r['sensitivity_hit'] else 'miss'}  "
              f"specificity={'HIT' if r['specificity_hit'] else 'miss'}")
        for tag, sub in (("mutant", r["mutant"]), ("control", r["control"])):
            if sub["errors"]:
                print(f"      {tag} errors (x{len(sub['errors'])}): {sub['errors'][0][:120]}")
    print(f"sensitivity: {n_sens}/{n_circ} circuits show raw_distinct>1 with func_distinct==1 "
          f"(output-invisible non-determinism reproduced)")
    print(f"specificity: {n_spec}/{n_circ} circuits show the unmutated control as raw-stable")
    print("wrote results/determinism_mutant_eval_v2.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
