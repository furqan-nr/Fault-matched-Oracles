#!/usr/bin/env python3
"""Determinism-channel synthetic mutant family (B-1, PLAN_1B.md G1a).

The two real, source-verified determinism faults in this study (#14730, #16237; see
determinism_eval.py, verify_16237.py) both come down to the same mechanism: some internal choice inside
the transpiler is decided by Python's hash-randomized set/dict iteration order rather than by
seed_transpiler, so the exact compiled representation varies across process launches (different
PYTHONHASHSEED) while the actual computation performed does not.

This mutant reproduces that mechanism directly rather than approximating it: after an otherwise fully
seeded transpile (seed_transpiler=1234, so nothing else varies), it looks for one adjacent pair of
instructions that act on DISJOINT qubits (which therefore commute trivially -- reordering them can never
change the circuit's unitary) and decides whether to swap them via `next(iter({"keep", "swap"}))`, a
2-element STRING set whose iteration order is exactly the PYTHONHASHSEED-dependent tie-break believed to
drive #16237's ConsolidateBlocks.basis_gate_name pick. Because the swapped pair provably commutes, this
mutation is output-invisible BY CONSTRUCTION (not just empirically): the FUNCTIONAL fingerprint (sorted
statevector probabilities) cannot change, only the RAW fingerprint (the literal instruction sequence)
can. A CONTROL condition (same transpile, no reorder step) on the same circuits gives the specificity
check: an honestly deterministic transpile must show raw_distinct == 1 across every PYTHONHASHSEED.

Because PYTHONHASHSEED is fixed for the lifetime of one interpreter, every trial is its own subprocess
(same harness pattern as determinism_eval.py / verify_16237.py) -- there is no way to vary it mid-process.

Run from repo root:  python scripts/determinism_mutant_eval.py
Writes results/determinism_mutant_eval.json.

NOTE: authored without a local Qiskit install available to the authoring session (no network egress to
PyPI from that sandbox). Please smoke-test on one circuit first -- in particular confirm item assignment
into `out.data[i]` works on the Qiskit version in the 2.1-2.4 band this study anchors on
(environment/ENV.md) -- before trusting a full run, and report back anything that errors so the harness
can be fixed rather than the result quietly misreported.
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
try:
    from qiskit import QuantumCircuit
    from qiskit.circuit.library import QFT
    from qiskit.quantum_info import Statevector
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
    probs = np.sort(np.round(np.abs(Statevector(out).data) ** 2, 8))
    func = hashlib.sha1(probs.tobytes()).hexdigest()[:12]
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
               "hashseeds": HASHSEEDS, "repeats_per_seed": REPEATS_PER_SEED,
               "runs_per_condition_per_circuit": len(HASHSEEDS) * REPEATS_PER_SEED}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "determinism_mutant_eval.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2))

    print("=" * 66)
    print("DETERMINISM-CHANNEL SYNTHETIC MUTANT FAMILY")
    print(f"{len(HASHSEEDS)} PYTHONHASHSEED values x {REPEATS_PER_SEED} repeats = "
          f"{len(HASHSEEDS) * REPEATS_PER_SEED} runs per condition per circuit, {n_circ} circuits")
    for r in rows:
        print(f"  {r['circuit']:6s} mutant raw_distinct={r['mutant']['raw_distinct']:2d} "
              f"func_distinct={r['mutant']['func_distinct']}  "
              f"control raw_distinct={r['control']['raw_distinct']}  "
              f"sensitivity={'HIT' if r['sensitivity_hit'] else 'miss'}  "
              f"specificity={'HIT' if r['specificity_hit'] else 'miss'}")
    print(f"sensitivity: {n_sens}/{n_circ} circuits show raw_distinct>1 with func_distinct==1 "
          f"(output-invisible non-determinism reproduced)")
    print(f"specificity: {n_spec}/{n_circ} circuits show the unmutated control as raw-stable "
          f"(no false alarm)")
    print("wrote results/determinism_mutant_eval.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
