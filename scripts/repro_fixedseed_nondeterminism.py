#!/usr/bin/env python3
"""Minimal reproducer (found by N1's contract differ): fixed-seed transpilation in Qiskit 2.5.0 is
non-deterministic in its recorded layout metadata — even single-threaded. The compiled circuit stays
correct modulo layout, so an output-equivalence oracle is BLIND; only a metadata/contract oracle sees
it. Output-invisible determinism-channel behavior.

  PYTHONPATH=src python scripts/repro_fixedseed_nondeterminism.py
  RAYON_NUM_THREADS=1 PYTHONPATH=src python scripts/repro_fixedseed_nondeterminism.py   # still varies
"""
import qiskit
from qiskit import transpile
from qiskit.circuit.random import random_circuit
from qiskit.transpiler import CouplingMap

circ = random_circuit(4, 8, max_operands=2, measure=False, seed=6)
cmap = CouplingMap([[i, (i + 1) % 4] for i in range(4)])   # 4-qubit ring
seen = {}
for _ in range(20):
    t = transpile(circ, basis_gates=["cx", "rz", "sx", "x"], coupling_map=cmap,
                   optimization_level=3, seed_transpiler=1234)
    key = tuple(t.layout.final_index_layout())
    seen[key] = seen.get(key, 0) + 1

print(f"qiskit {qiskit.__version__}: fixed seed_transpiler=1234, 20 identical transpile() calls")
print(f"distinct final_index_layout values: {len(seen)}  (1 = deterministic, >1 = BUG)")
for k, c in seen.items():
    print(f"  {list(k)}  x{c}")
