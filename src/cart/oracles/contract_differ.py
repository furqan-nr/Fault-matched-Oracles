"""N1 — Transpiler contract differ (bug-finder).

Asserts the transpiler's layout/permutation CONTRACT on transpiled circuits, independent of the
output map. These are hard invariants Qiskit's TranspileLayout is supposed to satisfy on every
transpilation, so a violation is a candidate bug in the output-invisible contract/metadata channel.

Checks (single-version; no trusted baseline needed) — all METADATA-INTERNAL invariants that do NOT
require reconciling the full output map (that is the semantic oracle's job; an earlier operator-level
reconciliation check was removed because Operator.from_circuit mis-reconciles under the default VF2
post-layout and produced false positives while the layout-applied output was in fact correct):
  C2 permutation      initial_index_layout / final_index_layout must be valid permutations of
                      range(n) (ancilla-free case); routing_permutation, if present, valid.
  C3 composition (MR-2)  final_index_layout must equal initial_index_layout composed with
                      routing_permutation, when all three are exposed.

MR-4 idempotence is checked at the sweep level (transpile twice, same seed -> identical metadata),
using `metadata_signature`.

`check_contracts` returns a list of Violation; an empty list means all contracts held.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qiskit import QuantumCircuit
from qiskit.transpiler import CouplingMap


@dataclass
class Violation:
    kind: str
    detail: str


def _layout_list(layout, name: str):
    fn = getattr(layout, name, None)
    if not callable(fn):
        return None
    try:
        return list(fn())
    except Exception as exc:  # a contract getter that raises IS itself a signal
        return f"__error__:{type(exc).__name__}"


def _is_perm(lst, n: int) -> bool:
    return isinstance(lst, list) and len(lst) == n and sorted(lst) == list(range(n))


def metadata_signature(transpiled: QuantumCircuit) -> dict[str, Any]:
    """Stable snapshot of the layout/permutation contract + global phase (for idempotence diffs)."""
    layout = getattr(transpiled, "layout", None)
    sig: dict[str, Any] = {"global_phase": round(float(transpiled.global_phase), 12)}
    if layout is not None:
        for name in ("initial_index_layout", "final_index_layout", "routing_permutation"):
            val = _layout_list(layout, name)
            if val is not None:
                sig[name] = val
    return sig


def check_contracts(
    original: QuantumCircuit,
    transpiled: QuantumCircuit,
    *,
    coupling_map: CouplingMap | None = None,
    basis_gates: list[str] | None = None,
) -> list[Violation]:
    v: list[Violation] = []
    n = original.num_qubits
    ancilla = transpiled.num_qubits != n
    layout = getattr(transpiled, "layout", None)

    # C2 permutation validity
    init = fin = rperm = None
    if layout is not None:
        init = _layout_list(layout, "initial_index_layout")
        fin = _layout_list(layout, "final_index_layout")
        rperm = _layout_list(layout, "routing_permutation")
        for name, lst in (("initial_index_layout", init), ("final_index_layout", fin)):
            if isinstance(lst, str) and lst.startswith("__error__"):
                v.append(Violation("layout_getter_raised", f"{name} -> {lst}"))
            elif lst is not None and not ancilla and not _is_perm(lst, n):
                v.append(Violation("invalid_permutation", f"{name}={lst} is not a permutation of range({n})"))

    # C3 composition (MR-2): final == initial permuted by routing_permutation, when all present
    if (isinstance(init, list) and isinstance(fin, list) and isinstance(rperm, list)
            and not ancilla and _is_perm(init, n) and _is_perm(fin, n) and _is_perm(rperm, n)):
        composed = [init[rperm[i]] for i in range(n)]
        composed_alt = [rperm[init[i]] for i in range(n)]
        if fin != composed and fin != composed_alt:
            v.append(Violation("layout_composition",
                               f"final_index_layout={fin} != initial∘routing "
                               f"({composed} / {composed_alt})"))

    return v
