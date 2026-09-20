"""Connectivity-pressure topology feature (METHODOLOGY §2.4).

A PRE-LAYOUT risk proxy, not a measurement of actual routing difficulty:

    connectivity_pressure = number of circuit two-qubit interaction edges that are NOT adjacent
                            in the backend coupling graph.

Placement rule (declared): the **trivial/identity layout** (virtual qubit i -> physical qubit i).
Direction: the coupling map is treated as **undirected** for adjacency. Actual routing difficulty
(SWAPs, final layout) is observed post-hoc in test_profile_baseline, never used at selection time.
"""
from __future__ import annotations

from qiskit import QuantumCircuit
from qiskit.transpiler import CouplingMap


def interaction_edges(circuit: QuantumCircuit) -> set[frozenset[int]]:
    """Undirected set of qubit-index pairs that interact via a two-qubit gate."""
    edges: set[frozenset[int]] = set()
    for instr in circuit.data:
        op = instr.operation
        if op.num_qubits == 2 and op.name != "barrier":
            i, j = (circuit.find_bit(b).index for b in instr.qubits)
            if i != j:
                edges.add(frozenset((i, j)))
    return edges


def connectivity_pressure(circuit: QuantumCircuit, coupling_map: CouplingMap) -> int:
    """Count interaction edges non-adjacent under the trivial layout (undirected)."""
    adj = {frozenset(e) for e in coupling_map.get_edges()}
    return sum(1 for e in interaction_edges(circuit) if e not in adj)


def two_qubit_density(circuit: QuantumCircuit) -> float:
    """Fraction of operations that are two-qubit gates (cheap circuit-shape proxy)."""
    total = sum(1 for i in circuit.data if i.operation.name != "barrier")
    if total == 0:
        return 0.0
    twoq = sum(1 for i in circuit.data
               if i.operation.num_qubits == 2 and i.operation.name != "barrier")
    return twoq / total
