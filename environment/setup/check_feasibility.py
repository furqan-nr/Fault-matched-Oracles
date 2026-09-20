"""E4 — statevector feasibility check for the sampled-SV oracle tier (METHODOLOGY §2.2).

Confirms the laptop can hold/compare statevectors up to ~20-22 qubits without exhausting
16 GB. Reports memory and timing; does not assert pass/fail (you decide the safe ceiling).
"""
from __future__ import annotations

import time
import tracemalloc

import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector


def probe(n: int) -> dict:
    qc = QuantumCircuit(n)
    qc.h(range(n))
    for i in range(n - 1):
        qc.cx(i, i + 1)
    tracemalloc.start()
    t0 = time.perf_counter()
    sv = Statevector(qc)
    eq = sv.equiv(Statevector(qc))
    dt = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    theo_mb = (2 ** n) * 16 / (1024 * 1024)  # complex128 vector
    return {"n": n, "equiv": bool(eq), "seconds": round(dt, 3),
            "peak_mb": round(peak / 1024 / 1024, 1), "theoretical_vec_mb": round(theo_mb, 1)}


if __name__ == "__main__":
    print(f"qiskit statevector feasibility probe (numpy {np.__version__})")
    for n in (10, 16, 20, 22):
        r = probe(n)
        print(f"  n={r['n']:>2} | equiv={r['equiv']} | {r['seconds']}s | peak~{r['peak_mb']}MB | vec~{r['theoretical_vec_mb']}MB")
    print("Choose the sampled-SV ceiling so peak stays well under available RAM.")
