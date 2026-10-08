#!/usr/bin/env python3
"""Adversarial validation bundle (REVIEW2 B1): five cases that probe the limits of the oracle family.

Each case states what the family SHOULD do, runs the real oracles, and records expected vs observed.
Cases 1, 2, 4, 5 test that the oracles do not over-claim (no false alarm, honest 'not assessable').
Case 3 is an HONEST LIMITATION: a self-consistent but wrong metadata triple is not flagged by the
single-version contract checker (K0-K2); the script records that it is silent and what MR-1 and the
output oracle do on the same input, so the paper can state the limitation with evidence.

  1. legitimate NONZERO input global phase  -> phase tracker silent (no false positive)
  2. correct NONTRIVIAL layout/routing      -> contract checker silent; output oracle silent
  3. consistently corrupted metadata        -> contract checker silent (limitation); MR-1 / output recorded
  4. genuinely INEQUIVALENT output          -> phase tracker 'not assessable' (never a phase fault)
  5. reproducibility under an explicit fixed-seed contract (raw vs functional fingerprints)

Run from the repo root of 'Fault matched Oracles' with the Qiskit venv active:
    python scripts/adversarial_validation_bundle.py
Writes results/adversarial_validation_bundle.json and prints a summary.
"""
import hashlib, json, subprocess, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import QFT
from qiskit.quantum_info import Operator
from qiskit.transpiler import CouplingMap

from cart.events.mutations import baseline_transpiler
from cart.oracles.semantic import check_semantic
from cart.oracles.contract_differ import check_contracts
from cart.oracles.metamorphic import check_permutation_consistency
from cart.oracles.global_phase import check_global_phase

# reuse the proven layout-substitution helpers from the contract mutant script
sys.path.insert(0, str(ROOT / "scripts"))
from contract_mutant_eval import _CorruptedLayout, _patched_layout  # noqa: E402

BASIS = ["cx", "rz", "sx", "x"]
OUT = ROOT / "results" / "adversarial_validation_bundle.json"


def ghz(n, phase=0.0):
    c = QuantumCircuit(n, global_phase=phase)
    c.h(0)
    for i in range(n - 1):
        c.cx(i, i + 1)
    return c


def qft(n, phase=0.0):
    c = QuantumCircuit(n, global_phase=phase)
    c.compose(QFT(n), inplace=True)
    return c


def cfg(n, seed=1234, opt=3):
    return dict(coupling_map=CouplingMap.from_line(n), basis_gates=list(BASIS),
                optimization_level=opt, seed_transpiler=seed)


def longrange(n):
    """Line-coupled circuit with a long-range CX so routing inserts swaps (nontrivial permutation)."""
    c = QuantumCircuit(n)
    c.h(0)
    c.cx(0, n - 1)
    c.cx(1, n - 2)
    c.h(n - 1)
    return c


def checks(orig, t, cm, mr1_ok):
    r = {}
    r["contract_fired"] = len(check_contracts(orig, t, coupling_map=cm, basis_gates=BASIS)) > 0
    r["contract_violations"] = [v.kind if hasattr(v, "kind") else str(v)
                                for v in check_contracts(orig, t, coupling_map=cm, basis_gates=BASIS)]
    if mr1_ok:
        m = check_permutation_consistency(orig, t)
        r["mr1_holds"] = m.holds
    else:
        r["mr1_holds"] = "n/a"
    g = check_global_phase(orig, t)
    r["phase_equivalent"] = g.equivalent
    r["phase_delta"] = g.global_phase_delta
    r["phase_details"] = {k: (v if isinstance(v, (int, float, str, bool)) else str(v))
                          for k, v in g.details.items()}
    s = check_semantic(orig, t, coupling_map=cm, basis_gates=BASIS)
    r["semantic_equivalent"] = s.equivalent
    return r


def case1():
    rows = []
    for name, circ in (("ghz4_phase0.7", ghz(4, 0.7)), ("qft4_phase1.3", qft(4, 1.3)),
                       ("qft5_phase-2.1", qft(5, -2.1))):
        n = circ.num_qubits
        cm = CouplingMap.from_line(n)
        t = baseline_transpiler(cfg(n))(circ)
        r = checks(circ, t, cm, mr1_ok=name.startswith("ghz"))
        ok = (r["phase_equivalent"] is True) and (not r["contract_fired"])
        rows.append({"circuit": name, "input_global_phase": circ.global_phase,
                     "compiled_global_phase": float(t.global_phase), "result": r, "pass": ok})
    return {"claim": "A legitimate nonzero input global phase, preserved by the compiler, is not flagged.",
            "expected": "phase_equivalent True, contract silent", "rows": rows,
            "pass": all(x["pass"] for x in rows)}


def case2():
    rows = []
    for name, circ in (("longrange5", longrange(5)), ("longrange6", longrange(6)), ("qft5", qft(5))):
        n = circ.num_qubits
        cm = CouplingMap.from_line(n)
        t = baseline_transpiler(cfg(n, opt=1))(circ)
        lay = getattr(t, "layout", None)
        fin = list(lay.final_index_layout()) if lay is not None else None
        rp = list(lay.routing_permutation()) if lay is not None else None
        nontrivial = (fin is not None and fin != list(range(n))) or (rp is not None and rp != list(range(n)))
        r = checks(circ, t, cm, mr1_ok=False)
        ok = nontrivial and (not r["contract_fired"]) and (r["semantic_equivalent"] is True)
        rows.append({"circuit": name, "final_index_layout": fin, "routing_permutation": rp,
                     "nontrivial_layout": bool(nontrivial), "result": r, "pass": ok})
    return {"claim": "A correct, nontrivial layout/routing permutation is not flagged by the contract checker "
                     "and passes the output oracle.",
            "expected": "nontrivial layout, contract silent, semantic equivalent",
            "rows": rows, "pass": all(x["pass"] for x in rows)}


def case3():
    """Self-consistent but wrong triple: initial, routing, final all replaced so K1 and K2 hold."""
    rows = []
    for name, circ, mr1 in (("ghz5", ghz(5), True), ("qft5", qft(5), False)):
        n = circ.num_qubits
        cm = CouplingMap.from_line(n)
        t = baseline_transpiler(cfg(n))(circ)
        lay = t.layout
        a0 = list(lay.initial_index_layout())
        r0 = list(lay.routing_permutation())
        a1 = a0[:]; a1[0], a1[1] = a1[1], a1[0]
        r1 = r0[:]; r1[-1], r1[-2] = r1[-2], r1[-1]
        f1 = [a1[r1[i]] for i in range(n)]               # a ∘ r : satisfies K2 by construction
        changed = (a1 != a0) or (r1 != r0)
        fake = _CorruptedLayoutTriple(lay, a1, f1, r1)
        with _patched_layout(t, fake):
            res = checks(circ, t, cm, mr1_ok=mr1)
        rows.append({"circuit": name, "original": {"initial": a0, "routing": r0},
                     "corrupted": {"initial": a1, "routing": r1, "final": f1},
                     "triple_changed": bool(changed), "result": res,
                     "contract_silent": not res["contract_fired"]})
    return {"claim": "LIMITATION: a self-consistent but wrong metadata triple satisfies K1 and K2 and is not "
                     "flagged by the single-version contract checker; MR-1 and the output oracle behaviour "
                     "on the same input are recorded for comparison.",
            "expected": "contract silent (documented limitation)",
            "rows": rows, "pass": all(x["contract_silent"] for x in rows)}


class _CorruptedLayoutTriple:
    def __init__(self, orig, a, f, r):
        self._orig, self._a, self._f, self._r = orig, list(a), list(f), list(r)

    def initial_index_layout(self, *x, **k):
        return list(self._a)

    def final_index_layout(self, *x, **k):
        return list(self._f)

    def routing_permutation(self, *x, **k):
        return list(self._r)

    def __getattr__(self, name):
        return getattr(self._orig, name)


def case4():
    rows = []
    for name, circ in (("ghz4", ghz(4)), ("qft4", qft(4))):
        n = circ.num_qubits
        cm = CouplingMap.from_line(n)
        t = baseline_transpiler(cfg(n))(circ)
        t.x(0)                                            # genuinely inequivalent output
        r = checks(circ, t, cm, mr1_ok=False)
        ok = (r["phase_equivalent"] is None) and (r["semantic_equivalent"] is False)
        rows.append({"circuit": name, "result": r, "pass": ok})
    return {"claim": "A genuinely inequivalent output is left to the output oracle: the phase tracker reports "
                     "not assessable and never classifies it as a phase fault.",
            "expected": "phase_equivalent None; semantic_equivalent False",
            "rows": rows, "pass": all(x["pass"] for x in rows)}


WORKER = r'''
import json, sys, hashlib, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, sys.argv[1])
import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import QFT
from qiskit.quantum_info import Operator
from qiskit.transpiler import CouplingMap
from cart.events.mutations import baseline_transpiler
n = 5
c = QuantumCircuit(n); c.compose(QFT(n), inplace=True)
cfg = dict(coupling_map=CouplingMap.from_line(n), basis_gates=["cx","rz","sx","x"], optimization_level=3, seed_transpiler=1234)
reps = int(sys.argv[2]); raws=[]; funcs=[]
for _ in range(reps):
    t = baseline_transpiler(cfg)(c)
    ins = [(i.operation.name, tuple(t.find_bit(q).index for q in i.qubits), tuple(round(float(p),9) for p in i.operation.params if isinstance(p,(int,float)))) for i in t.data]
    fin = list(t.layout.final_index_layout()) if t.layout is not None else None
    raws.append(hashlib.sha256(repr((ins,fin)).encode()).hexdigest()[:12])
    U = Operator.from_circuit(t).data
    k = int(np.argmax(np.abs(U.ravel()) > 1e-6)); ph = np.angle(U.ravel()[k])
    V = np.round(U * np.exp(-1j*ph), 6)
    funcs.append(hashlib.sha256(np.round(V.real,6).tobytes()+np.round(V.imag,6).tobytes()).hexdigest()[:12])
print(json.dumps({"raw": raws, "func": funcs}))
'''


def case5():
    contract = ("Explicit reproducibility contract: same library version, same circuit, coupling map, basis, "
                "optimization level and seed_transpiler=1234; PYTHONHASHSEED is varied across subprocesses; "
                "thread count is not constrained. 'Reproducible' means raw fingerprint (instruction sequence + "
                "final_index_layout) is identical across runs; the functional fingerprint (layout-normalized "
                "unitary modulo global phase) separates harmless raw differences from functional ones.")
    raws, funcs, per_seed = [], [], {}
    for hs in (0, 1, 2, 3, 4):
        env = dict(__import__("os").environ, PYTHONHASHSEED=str(hs))
        p = subprocess.run([sys.executable, "-c", WORKER, str(ROOT / "src"), "3"], capture_output=True,
                           text=True, env=env)
        if p.returncode != 0:
            return {"claim": "reproducibility under explicit contract", "error": p.stderr[-800:], "pass": False}
        d = json.loads(p.stdout.strip().splitlines()[-1])
        per_seed[str(hs)] = d
        raws += d["raw"]; funcs += d["func"]
    raw_d, func_d = len(set(raws)), len(set(funcs))
    return {"claim": "The determinism runner reports against an explicitly stated contract, separating raw from "
                     "functional non-reproducibility.", "contract": contract,
            "runs": len(raws), "raw_distinct": raw_d, "func_distinct": func_d, "per_hashseed": per_seed,
            "verdict": ("reproducible under the stated contract" if raw_d == 1 else
                        "raw non-reproducible, functionally identical (output-invisible)" if func_d == 1 else
                        "raw AND functional non-reproducible"),
            "pass": True}


def main():
    OUT.parent.mkdir(exist_ok=True)
    cases = {}
    for key, fn in (("case1_nonzero_input_phase", case1), ("case2_nontrivial_layout", case2),
                    ("case3_self_consistent_corruption", case3), ("case4_inequivalent_output", case4),
                    ("case5_fixed_seed_contract", case5)):
        try:
            cases[key] = fn()
        except Exception as e:  # report, do not hide
            cases[key] = {"error": f"{type(e).__name__}: {e}", "pass": False}
    OUT.write_text(json.dumps(cases, indent=2, default=str))
    print("=" * 70)
    for k, v in cases.items():
        print(f"{k}: {'PASS' if v.get('pass') else 'CHECK'}", "|", v.get("error", ""))
        if "rows" in v:
            for r in v["rows"]:
                res = r.get("result", {})
                print("   ", r.get("circuit"), {kk: res.get(kk) for kk in
                      ("contract_fired", "mr1_holds", "phase_equivalent", "phase_delta", "semantic_equivalent")})
    c5 = cases.get("case5_fixed_seed_contract", {})
    print("case5: runs", c5.get("runs"), "raw_distinct", c5.get("raw_distinct"),
          "func_distinct", c5.get("func_distinct"), "->", c5.get("verdict"))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
