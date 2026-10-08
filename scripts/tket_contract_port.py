#!/usr/bin/env python3
"""tket port of the CONTRACT/permutation-metadata checker (review response B3).

WHY
---
tket_global_phase_port.py already showed ONE matched mechanism (the global-phase tracker) transfers to
pytket/tket. A reviewer asked for a SECOND mechanism — the contract/permutation checker — to transfer,
since contract/metadata is the dominant output-invisible channel 1A reports on tket (7 of 21 in-scope
tket bug-fixes; see data/mining_validation/tket_worksheet_R2.csv). This script re-implements the
contract checker's core invariant on tket and demonstrates it on a SYNTHETIC contract-corruption mutant,
exactly the status the global-phase port's own sensitivity number has (a synthetic-mutant demonstration,
not a from-source replay — replaying the seven real tket faults needs building tket's C++ at historical
commits, which is out of scope here; those seven are instead mapped to this checker's invariant in
docs TKET_CONTRACT_FAULT_MAP.md).

THE INVARIANT (tket analogue of src/cart/oracles/contract_differ.py's composition check)
----------------------------------------------------------------------------------------
After routing, a CompilationUnit records how the ORIGINAL qubits were placed and where they end up
(initial_map, final_map). The contract: those recorded maps must correctly describe the routed
circuit's own action, i.e. normalizing the routed unitary by the recorded maps must recover the
original circuit's unitary (up to a global phase). A contract/metadata fault records maps that do NOT
match what the circuit actually does, while the circuit itself (what a black-box output oracle runs and
measures) is unchanged — so the output oracle is BLIND and only a metadata-level check sees it.

  * output oracle (black-box): there EXISTS some qubit relabeling + global phase making the routed
    circuit equal to the original — true whenever the circuit is a correct routing of the original,
    independent of what the maps record. Corrupting only the recorded map leaves this true → blind.
  * contract checker: the SPECIFIC recorded maps must be the ones that reconcile the circuit with the
    original. Corrupt a recorded map and this fails → detected.

SYNTHETIC MUTANT: take a correctly routed circuit and its true (initial_map, final_map); the mutant
records a final_map with two entries transposed (a realistic "pass wrote the wrong permutation
metadata" bug) while leaving the circuit untouched. Control = the true maps.

Hand to a pytket environment (pip install pytket in a throwaway venv; same hand-off as
tket_global_phase_port.py). Run:  python scripts/tket_contract_port.py
Writes results/tket_contract_port.json. Report any traceback rather than trusting a partial run.
"""
from __future__ import annotations

import json, math, sys
from pathlib import Path
import numpy as np

try:
    from pytket.circuit import Circuit
    from pytket.architecture import Architecture
    from pytket.passes import DefaultMappingPass, RemoveImplicitQubitPermutation, SequencePass
    from pytket.predicates import CompilationUnit
except ImportError as exc:  # pragma: no cover
    sys.exit("tket_contract_port.py requires pytket (pip install pytket in a throwaway venv). "
             f"Import error: {exc}")

ROOT = Path(__file__).resolve().parents[1]
PHASE_TOL = 1e-7


def _wrap(phi: float) -> float:
    return (phi + math.pi) % (2 * math.pi) - math.pi


def circuits():
    """Same GHZ + QFT family and sizes as tket_global_phase_port.py / channel_matched_eval.py."""
    out = []
    for n in (4, 5, 6):
        g = Circuit(n); g.H(0)
        for i in range(n - 1): g.CX(i, i + 1)
        out.append((f"ghz{n}", g))
        q = Circuit(n)
        for i in range(n):
            q.H(i)
            for j in range(i + 1, n): q.CU1(1 / 2 ** (j - i), j, i)
        for k in range(n // 2): q.SWAP(k, n - k - 1)
        out.append((f"qft{n}", q))
    return out


def _line_architecture(n): return Architecture([(i, i + 1) for i in range(n - 1)])


def route(circ):
    n = circ.n_qubits
    cu = CompilationUnit(circ.copy())
    SequencePass([DefaultMappingPass(_line_architecture(n)),
                  RemoveImplicitQubitPermutation()]).apply(cu)
    return cu


def _permutation_matrix_be(perm, n):
    dim = 1 << n
    P = np.zeros((dim, dim))
    for logical_idx in range(dim):
        physical_idx = 0
        for i in range(n):
            bit = (logical_idx >> (n - 1 - i)) & 1
            physical_idx |= bit << (n - 1 - perm[i])
        P[physical_idx, logical_idx] = 1.0
    return P


def _logical_perm(original, routed, mapping):
    pos = {wire: idx for idx, wire in enumerate(routed.qubits)}
    return [pos[mapping[lq]] for lq in original.qubits]


def _to_logical_unitary(U_routed, original, routed, initial_perm_list, final_perm_list):
    n = original.n_qubits
    P_in = _permutation_matrix_be(initial_perm_list, n)
    P_out = _permutation_matrix_be(final_perm_list, n)
    return P_out.T @ U_routed @ P_in


def _equal_mod_phase(Uo, Ut, atol):
    M = Uo.conj().T @ Ut
    phi = float(np.angle(np.trace(M)))
    return bool(np.allclose(M, np.exp(1j * phi) * np.eye(M.shape[0]), atol=atol))


def check_contract_tket(original, routed, initial_perm_list, final_perm_list):
    """Fires (returns True) iff the RECORDED maps do NOT reconcile the routed circuit with the
    original up to a global phase — the tket analogue of contract_differ's composition violation."""
    Uo = original.get_unitary()
    Ut = _to_logical_unitary(routed.get_unitary(), original, routed, initial_perm_list, final_perm_list)
    return not _equal_mod_phase(Uo, Ut, atol=1e-8)


def output_oracle_blind(original, routed, true_initial, true_final):
    """Black-box view: the routed circuit, normalized by its TRUE maps, equals the original mod global
    phase. Unchanged by corrupting the RECORDED metadata, so it stays blind on the contract mutant."""
    Uo = original.get_unitary()
    Ut = _to_logical_unitary(routed.get_unitary(), original, routed, true_initial, true_final)
    return _equal_mod_phase(Uo, Ut, atol=1e-6)


def main():
    rows = []
    tp = n_mut = fp = tn = 0
    for cname, circ in circuits():
        cu = route(circ)
        routed, im, fm = cu.circuit, cu.initial_map, cu.final_map
        init_perm = _logical_perm(circ, routed, im)
        fin_perm = _logical_perm(circ, routed, fm)

        # --- specificity: contract checker on the clean, correctly-recorded maps ---
        fired_clean = check_contract_tket(circ, routed, init_perm, fin_perm)
        if fired_clean: fp += 1
        else: tn += 1
        rows.append({"circuit": cname, "kind": "clean", "contract_fired": fired_clean})

        # --- sensitivity: synthetic contract mutants (transpose two final-map entries) ---
        n = circ.n_qubits
        swaps = [(a, b) for a in range(n) for b in range(a + 1, n)]
        for (a, b) in swaps:
            bad_fin = list(fin_perm)
            bad_fin[a], bad_fin[b] = bad_fin[b], bad_fin[a]
            if bad_fin == fin_perm:   # identical (shouldn't happen for a<b) -> skip
                continue
            fired = check_contract_tket(circ, routed, init_perm, bad_fin)
            blind = output_oracle_blind(circ, routed, init_perm, fin_perm)
            n_mut += 1
            if fired and blind: tp += 1
            rows.append({"circuit": cname, "kind": "contract_mutant", "transposed": [a, b],
                         "contract_fired": fired, "output_blind": blind})

    sens = tp / n_mut if n_mut else 0.0
    spec = tn / (tn + fp) if (tn + fp) else 0.0
    summary = {"sdk": "pytket", "mechanism": "contract/permutation metadata checker",
               "mutants": n_mut, "detected_and_blind": tp, "sensitivity": round(sens, 3),
               "clean_runs": tn + fp, "false_positives": fp, "specificity": round(spec, 3)}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "tket_contract_port.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2))
    print("=" * 70)
    print("TKET PORT -- contract/permutation-metadata checker (B3)")
    print(f"sensitivity: {summary['sensitivity']}  ({tp}/{n_mut} contract mutants detected AND output-blind)")
    print(f"specificity: {summary['specificity']}  ({tn}/{tn + fp} clean runs silent, {fp} false positives)")
    print("wrote results/tket_contract_port.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
