#!/usr/bin/env python3
"""Diagnostic for the determinism mutant on qft4 (review response B1).

determinism_mutant_eval_v2.py reported qft4 mutant func_distinct=2 under the stronger fingerprint
(layout-normalized unitary modulo global phase). The mutation is only supposed to swap an adjacent
pair of DISJOINT-qubit (hence commuting) instructions, which can never change the unitary. This script
builds the compiled qft4 circuit once, finds exactly the pair the mutant would swap, constructs the
'keep' and 'swap' orderings deterministically (no PYTHONHASHSEED needed), and reports:
  * which two instructions get swapped (names + qubit indices),
  * whether they are truly disjoint,
  * Operator.equiv between keep and swap (Qiskit's own modulo-global-phase equality), and
  * the max entry-wise difference after global-phase alignment.

If equiv == True  -> the func_distinct=2 was a fingerprint/rounding artifact; the mutation IS invisible.
If equiv == False -> the swapped pair does NOT commute to the same unitary; the qft4 mutant is output-
                     VISIBLE and should not be counted as an output-invisible determinism mutant.

Also re-runs the same check for qft5 and qft6 (which reported func_distinct=1) as a cross-check.

Run from repo root (anchor Qiskit env active):  python scripts/diag_determinism_qft4.py
"""
import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import QFT
from qiskit.quantum_info import Operator
from qiskit.transpiler import CouplingMap
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager


def build_compiled(n):
    circ = QuantumCircuit(n)
    circ.compose(QFT(n), inplace=True)
    pm = generate_preset_pass_manager(optimization_level=3, coupling_map=CouplingMap.from_line(n),
                                       basis_gates=["cx", "rz", "sx", "x"], seed_transpiler=1234)
    return pm.run(circ)


def reordered(out, do_swap):
    """Return a copy of `out` with the first disjoint-qubit adjacent pair optionally swapped.
    Returns (circuit, info) where info describes the pair."""
    data = list(out.data)
    info = {"found": False}
    for i in range(len(data) - 1):
        qa = set(out.find_bit(q).index for q in data[i].qubits)
        qb = set(out.find_bit(q).index for q in data[i + 1].qubits)
        if qa and qb and qa.isdisjoint(qb):
            info = {"found": True, "i": i,
                    "instr_i": (data[i].operation.name, sorted(qa)),
                    "instr_j": (data[i + 1].operation.name, sorted(qb)),
                    "disjoint": True}
            if do_swap:
                data[i], data[i + 1] = data[i + 1], data[i]
            break
    new = out.copy()
    for k, instr in enumerate(data):
        new.data[k] = instr
    return new, info


def phase_aligned_maxdiff(A, B):
    a = A.ravel(); b = B.ravel()
    k = int(np.argmax(np.abs(a)))
    if abs(a[k]) > 1e-12 and abs(b[k]) > 1e-12:
        a = a * (abs(a[k]) / a[k]); b = b * (abs(b[k]) / b[k])
    return float(np.max(np.abs(a - b)))


def check(n):
    out = build_compiled(n)
    keep, info = reordered(out, do_swap=False)
    swap, _ = reordered(out, do_swap=True)
    if not info["found"]:
        print(f"qft{n}: no disjoint-qubit adjacent pair (structural no-op) — nothing to swap")
        return
    Uk = Operator.from_circuit(keep)
    Us = Operator.from_circuit(swap)
    equiv = bool(Uk.equiv(Us))                 # Qiskit's modulo-global-phase equality
    maxd = phase_aligned_maxdiff(Uk.data, Us.data)
    print(f"qft{n}: swap pair @ index {info['i']}: {info['instr_i']}  <->  {info['instr_j']}  "
          f"disjoint={info['disjoint']}")
    print(f"       Operator.equiv(keep, swap) = {equiv}   max|U_keep - U_swap| (phase-aligned) = {maxd:.3e}")
    if equiv:
        print(f"       -> SAME computation modulo global phase (output-invisible). func_distinct>1 was a")
        print(f"          rounding artifact of the hash, not a real functional difference.")
    else:
        print(f"       -> DIFFERENT computation: the swapped pair does NOT commute to the same unitary,")
        print(f"          so the qft{n} determinism mutant is output-VISIBLE and must not be counted.")


if __name__ == "__main__":
    for n in (4, 5, 6):
        check(n)
        print()
