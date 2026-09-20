"""Tiered semantic oracle (METHODOLOGY §2.2).

Applicability + width decide the tier:
  - unitary / sampled-statevector equivalence only for unitary-pure circuits (no measurement,
    reset, or classical control) AND when transpilation added no ancilla (transpiled width ==
    original width). Layout permutation is normalized via Operator.from_circuit (uses the
    circuit's TranspileLayout).
  - otherwise -> structural validity (valid circuit, gates in basis, 2q gates respect the
    coupling map). Structural cannot assert semantic equivalence (equivalent = None).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from qiskit import QuantumCircuit
from qiskit.transpiler import CouplingMap
from qiskit.quantum_info import Operator, Statevector

UNITARY_MAX_QUBITS = 12
SAMPLED_SV_MAX_QUBITS = 22
NONUNITARY_OPS = {"measure", "reset"}


@dataclass
class OracleResult:
    strength: str                       # exact / sampled / property / structural
    equivalent: bool | None             # None when strength cannot assert equivalence
    layout_normalization_applied: bool
    cost_s: float
    details: dict[str, Any] = field(default_factory=dict)


def is_unitary_pure(circuit: QuantumCircuit) -> bool:
    for instr in circuit.data:
        op = instr.operation
        if op.name in NONUNITARY_OPS:
            return False
        if getattr(op, "condition", None) is not None:
            return False
        if op.name in ("if_else", "while_loop", "switch_case", "for_loop"):
            return False
    return True


def _structural_valid(transpiled: QuantumCircuit, coupling_map: CouplingMap | None,
                      basis_gates: list[str] | None) -> tuple[bool, dict]:
    details: dict[str, Any] = {}
    ok = True
    if basis_gates is not None:
        allowed = set(basis_gates) | {"barrier", "measure", "reset"}
        bad = sorted({i.operation.name for i in transpiled.data} - allowed)
        details["out_of_basis"] = bad
        ok = ok and not bad
    if coupling_map is not None:
        edges = {tuple(e) for e in coupling_map.get_edges()}
        undirected = edges | {(b, a) for a, b in edges}
        violations = 0
        for instr in transpiled.data:
            if instr.operation.num_qubits == 2 and instr.operation.name != "barrier":
                q = [transpiled.find_bit(b).index for b in instr.qubits]
                if (q[0], q[1]) not in undirected:
                    violations += 1
        details["coupling_violations"] = violations
        ok = ok and violations == 0
    return ok, details


def check_semantic(
    original: QuantumCircuit,
    transpiled: QuantumCircuit,
    *,
    coupling_map: CouplingMap | None = None,
    basis_gates: list[str] | None = None,
    sampled_k: int = 6,
    seed: int = 0,
) -> OracleResult:
    t0 = time.perf_counter()
    n = original.num_qubits
    ancilla = transpiled.num_qubits != n

    # Structural unless the circuit is unitary-pure, ancilla-free, AND small enough for an exact
    # operator. We do NOT build a full 2^n x 2^n operator above UNITARY_MAX_QUBITS (memory-safe:
    # a 13q operator is ~1 GiB, an 18q operator is ~512 GiB). The 13-22q sampled-SV tier with
    # layout-normalised statevectors is a documented deferred limitation; such circuits fall to
    # structural here.
    if (not is_unitary_pure(original)) or ancilla or n > UNITARY_MAX_QUBITS:
        ok, details = _structural_valid(transpiled, coupling_map, basis_gates)
        details["reason"] = ("non_unitary" if not is_unitary_pure(original)
                             else "ancilla_added" if ancilla
                             else "too_large_for_exact_operator")
        return OracleResult("structural", None, False, time.perf_counter() - t0,
                            {"structural_ok": ok, **details})

    # exact unitary equivalence, modulo global phase (n <= UNITARY_MAX_QUBITS)
    Uo = Operator(original)
    Ut = Operator.from_circuit(transpiled)   # normalizes routing/layout permutation
    eq = bool(Uo.equiv(Ut))
    return OracleResult("exact", eq, True, time.perf_counter() - t0,
                        {"method": "operator_equiv_modulo_phase"})
