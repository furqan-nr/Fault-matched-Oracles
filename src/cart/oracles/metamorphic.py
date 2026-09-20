"""N2 — Metamorphic relations over transpiler METADATA (a new oracle class).

Program-level metamorphic testing is established; contract-level metamorphic relations are open
territory. These assert invariants the transpiler's recorded layout/permutation metadata must satisfy,
independent of the output map — so a violation is an output-invisible contract fault.

MR-1 (permutation consistency): appending the recorded `routing_permutation` to the routed output must
"undo" routing, recovering the (layout-normalized) input unitary. This is exactly the invariant PR
#14919 restored ("you're supposed to be able to append it as a permutation and it will undo the
effects"). Assumes a trivial initial layout (SetLayout(range(n)) + ApplyLayout), i.e. no input
relabeling — the standard setup for isolating routing composition.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator

from .semantic import UNITARY_MAX_QUBITS


@dataclass
class MetamorphicResult:
    relation: str                 # e.g. "MR-1"
    holds: bool | None            # True=invariant holds; False=violated (fault); None=not assessable
    detail: dict[str, Any]


def check_permutation_consistency(original: QuantumCircuit,
                                  transpiled: QuantumCircuit) -> MetamorphicResult:
    """MR-1: Operator(transpiled + PermutationGate(routing_permutation)) == Operator(original),
    modulo global phase. `original` is the pre-routing circuit under a trivial initial layout."""
    from qiskit.circuit.library import PermutationGate
    layout = getattr(transpiled, "layout", None)
    rp = None
    if layout is not None and callable(getattr(layout, "routing_permutation", None)):
        try:
            rp = list(layout.routing_permutation())
        except Exception as exc:
            return MetamorphicResult("MR-1", None, {"reason": f"routing_permutation raised {type(exc).__name__}"})
    if rp is None:
        return MetamorphicResult("MR-1", None, {"reason": "no routing_permutation recorded"})
    n = original.num_qubits
    if transpiled.num_qubits != n or n > UNITARY_MAX_QUBITS:
        return MetamorphicResult("MR-1", None, {"reason": "ancilla or too large for exact check",
                                                "routing_permutation": rp})
    test = transpiled.copy()
    test.append(PermutationGate(rp), test.qubits)
    holds = bool(Operator(test).equiv(Operator(original)))    # equiv = modulo global phase
    return MetamorphicResult("MR-1", holds, {"routing_permutation": rp,
                                             "note": "appended routing_permutation recovers input" if holds
                                             else "routing_permutation does NOT undo routing (contract fault)"})
