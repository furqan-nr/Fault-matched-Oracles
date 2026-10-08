#!/usr/bin/env python3
"""M2 probe (REVIEW3): which composition order does the installed Qiskit satisfy?

For each transpilation, compare recorded final_index_layout (f) with a∘r = [a[r[i]]] and r∘a = [r[a[i]]]
(a = initial_index_layout, r = routing_permutation). Count: only a∘r, only r∘a, both (the two orders
coincide), neither (would be a K2 violation). Reports qiskit.__version__ so the paper can name the
release.  From the repo root:  python scripts/composition_order_probe.py
Writes results/composition_order_probe.json.
"""
import json, sys, warnings
from collections import Counter
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
import qiskit
from qiskit import QuantumCircuit, transpile
from qiskit.circuit.library import QFT
from qiskit.circuit.random import random_circuit
from qiskit.transpiler import CouplingMap

BASIS = ["cx", "rz", "sx", "x"]
def circuits():
    for n in (4, 5, 6, 8):
        g = QuantumCircuit(n); g.h(0)
        for i in range(n - 1): g.cx(i, i + 1)
        yield f"ghz{n}", g
        q = QuantumCircuit(n); q.compose(QFT(n), inplace=True); yield f"qft{n}", q
        for s in range(5):
            yield f"rand{n}_{s}", random_circuit(n, 6, max_operands=2, seed=s)

def main():
    cnt = Counter(); nontrivial = Counter(); n_total = 0
    for name, c in circuits():
        n = c.num_qubits
        for topo in ("line", "ring"):
            cm = CouplingMap.from_line(n) if topo == "line" else CouplingMap.from_ring(n)
            for opt in (1, 2, 3):
                try:
                    t = transpile(c, coupling_map=cm, basis_gates=BASIS, optimization_level=opt, seed_transpiler=7)
                except Exception:
                    continue
                lay = t.layout
                if lay is None or t.num_qubits != n: continue
                try:
                    a = list(lay.initial_index_layout()); f = list(lay.final_index_layout()); r = list(lay.routing_permutation())
                except Exception:
                    continue
                ar = [a[r[i]] for i in range(n)]; ra = [r[a[i]] for i in range(n)]
                key = ("both" if (f == ar and f == ra) else "a_o_r_only" if f == ar else
                       "r_o_a_only" if f == ra else "neither")
                cnt[key] += 1; n_total += 1
                if ar != ra: nontrivial[key] += 1     # cases where the two orders actually differ
    out = {"qiskit_version": qiskit.__version__, "total": n_total, "counts": dict(cnt),
           "counts_where_orders_differ": dict(nontrivial)}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "composition_order_probe.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
if __name__ == "__main__":
    main()
