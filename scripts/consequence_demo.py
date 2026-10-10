#!/usr/bin/env python3
"""Downstream-use simulations (added after review; Paper 1B, Sci Rep version).

(a) Phase estimation through a compiled, controlled gate, with a global-phase offset injected into the compiled circuit
    (0.3 rad = size of #16215 fix-vs-parent difference; pi/7 rad = size of #16201 difference).
(b) Readout through the recorded final layout, with two entries of the record transposed.
These are statevector simulations with INJECTED discrepancies of the observed size. They are not runs of the buggy builds
and not hardware runs: they show the consequence of a fault of that size under controlled conditions.

Reading the phase-estimation numbers: with t = 6 counting qubits the readout grid is k/64 (step 1/64 = 0.015625).
"modal_outcome" is the most likely discrete outcome k/64; "continuous_phase" = 0.25 + delta/(2*pi) is the phase the
register is estimating. The most likely outcome is the grid point nearest the continuous phase, so the two differ by at most half a step (0.0078).

Run:  python scripts/consequence_demo.py [--out results/consequence_demo.json]
"""
import argparse, json, math, os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("FMO_REPO", os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
import numpy as np
import qiskit
from qiskit import QuantumCircuit, transpile
from qiskit.circuit.library import QFTGate
from qiskit.quantum_info import Operator, Statevector
from qiskit.transpiler import CouplingMap
from cart.oracles.global_phase import check_global_phase


def qpe_dist(Ucirc, t=6):
    qc = QuantumCircuit(t + 1)
    qc.x(t)
    qc.h(range(t))
    cg = Ucirc.to_gate(label="U").control(1)
    for k in range(t):
        for _ in range(2 ** k):
            qc.append(cg, [k, t])
    qc.append(QFTGate(t).inverse(), range(t))
    return Statevector(qc).probabilities(list(range(t)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "results", "consequence_demo.json"))
    a = ap.parse_args()
    out = {"qiskit": qiskit.__version__}
    theta = 2 * math.pi * 0.25
    U = QuantumCircuit(1); U.p(theta, 0)
    Uc = transpile(U, basis_gates=["rz", "sx", "x", "cx"], optimization_level=3, seed_transpiler=1)
    out["compiled_U_stored_global_phase"] = float(Uc.global_phase)
    t = 6
    p_ok = qpe_dist(Uc, t)
    rows = []
    for name, delta in (("correct", 0.0), ("offset 0.3 rad (size of #16215)", 0.3), ("offset pi/7 rad (size of #16201)", math.pi / 7)):
        Uf = Uc.copy(); Uf.global_phase += delta
        r = check_global_phase(U, Uf)
        eq = Operator(U).equiv(Operator(Uf))
        p = qpe_dist(Uf, t)
        order = np.argsort(-p)
        cont = 0.25 + delta / (2 * math.pi)
        rows.append({"case": name, "delta": delta, "tracker_equivalent": r.equivalent, "tracker_delta": r.global_phase_delta,
                     "output_equivalent_modulo_phase": bool(eq), "peak_estimate": int(np.argmax(p)) / 2 ** t,
                     "grid_step": 1 / 2 ** t, "continuous_phase": cont, "continuous_shift": delta / (2 * math.pi),
                     "modal_outcome_index": int(order[0]), "modal_outcome": int(order[0]) / 2 ** t, "P_modal_outcome": float(p[order[0]]),
                     "second_outcome_index": int(order[1]), "second_outcome": int(order[1]) / 2 ** t, "P_second_outcome": float(p[order[1]]),
                     "nearest_grid_index": int(round(cont * 2 ** t)),
                     "P_true_outcome": float(p[int(0.25 * 2 ** t)]),
                     "total_variation_from_correct": float(0.5 * np.abs(p - p_ok).sum())})
    out["phase_estimation"] = rows
    rng = random.Random(11)
    trials = []
    n = 5
    for trial in range(60):
        qc = QuantumCircuit(n)
        bits = [rng.randrange(2) for _ in range(n)]
        if sum(bits) == 0: bits[rng.randrange(n)] = 1
        for i, b in enumerate(bits):
            if b: qc.x(i)
        for _ in range(6):
            x, y = rng.sample(range(n), 2); qc.swap(x, y)
        st = list(bits)
        for ins in qc.data:
            if ins.operation.name == "swap":
                x, y = [qc.find_bit(q).index for q in ins.qubits]; st[x], st[y] = st[y], st[x]
        tq = transpile(qc, coupling_map=CouplingMap.from_line(n), basis_gates=["x", "cx", "swap", "rz", "sx"],
                       optimization_level=3, seed_transpiler=trial)
        fin = tq.layout.final_index_layout() if tq.layout is not None else list(range(n))
        sv = Statevector(tq)
        idx = int(np.argmax(np.abs(sv.data)))
        phys = [(idx >> q) & 1 for q in range(tq.num_qubits)]
        decode = lambda lay: [phys[lay[i]] for i in range(n)]
        cor = list(fin); i, j = rng.sample(range(n), 2); cor[i], cor[j] = cor[j], cor[i]
        trials.append({"nontrivial_final_layout": fin != list(range(n)), "correct_record_ok": decode(fin) == st,
                       "corrupted_record_wrong": decode(cor) != st})
    out["readout"] = {"trials": len(trials),
                      "nontrivial_final_layout": sum(x["nontrivial_final_layout"] for x in trials),
                      "correct_record_ok": sum(x["correct_record_ok"] for x in trials),
                      "corrupted_record_wrong": sum(x["corrupted_record_wrong"] for x in trials)}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
