#!/usr/bin/env python3
"""tket port of the global-phase-tracking oracle (PLAN_1B B-3; feeds Paper 1B RQ2.4 -- "transfer
to a second SDK").

WHAT THIS IS
------------
`src/cart/oracles/global_phase.py` (the Qiskit-side oracle evaluated in channel_matched_eval.py)
detects a synthetic global-phase-drop fault that `check_semantic` (Operator.equiv, i.e. equality
MODULO GLOBAL PHASE) is blind to by construction. That blindness is not a property of Qiskit's
`Operator.equiv` specifically -- it is a property of any oracle whose equivalence notion discards
global phase, which is how essentially every practical "did the transpiler preserve semantics"
check is defined (global phase has no observable consequence for a standalone circuit, so nearly
every equivalence check discards it on purpose). This script re-implements the same mechanism,
end to end, on an independently engineered compiler stack (pytket / tket) rather than arguing by
analogy from the Qiskit result:

  1. build a small circuit family (GHZ + QFT, n in {4,5,6} -- the same family and sizes used in
     scripts/channel_matched_eval.py),
  2. route each circuit through a REAL tket compilation pipeline against a line architecture
     (pytket.passes.DefaultMappingPass), which is free to reorder qubits (a "layout"), then strip
     any implicit boundary permutation so the routed circuit's unitary is unambiguous,
  3. build a matched oracle that normalizes the routed circuit's unitary back into the ORIGINAL
     qubit ordering (undoing exactly that layout, via CompilationUnit.initial_map/final_map) and
     extracts the residual global phase,
  4. inject the same synthetic phase offsets used on the Qiskit side (channel_matched_eval.py's
     PHASES list, identical radian magnitudes) via Circuit.add_phase(), and
  5. report sensitivity (does the matched oracle fire on the injected fault?) and "output-oracle
     blindness" (does an equivalence-modulo-global-phase check stay silent on it?), exactly as
     channel_matched_eval.py reports them for the Qiskit side.

This is a synthetic-mutant demonstration, not a replay of a historical tket bug fix -- the same
status the Qiskit-side global-phase channel's own sensitivity number has in channel_matched_eval.py
(t_bad.global_phase = ... + d there is exactly this script's t_bad.add_phase(...) here). The
project's separate cross-SDK commit-mining study (companion paper, 1A) is the source for whether
this fault *class* actually recurs on tket; what this script adds is a demonstration that the
*detection mechanism* (layout-normalized phase/permutation tracking) transfers to tket's own API,
not just to Qiskit's.

WHY THIS SCRIPT WAS WRITTEN BUT NOT RUN BY ITS AUTHOR
-------------------------------------------------------
The authoring sandbox for this repository is Qiskit-only by design (environment/ENV.md and
environment/requirements.anchor.in pin Qiskit 2.4.2; grep of src/cart and environment/ turned up no
pytket reference anywhere) AND its outbound network is blocked at an organisation policy layer
(`pip install pytket` fails with HTTP 403 from an "Egress Gateway", confirmed via
`curl -sSv https://pypi.org/pypi/pytket/json`; this is a policy boundary, not a transient error, so
it was not routed around). Every pytket API used below was therefore verified against the official
docs (docs.quantinuum.com/tket, pytket 2.18.1, fetched 2026-09-12) by direct quotation rather than
by executing it -- see the API NOTES block below for exactly what was confirmed and how. Hand this
script to an environment where `pip install pytket` works (a separate/throwaway virtualenv is
enough -- do NOT add pytket to environment/requirements.anchor.in; that lockfile is intentionally
Qiskit-only, see ENV.md) and run it there; then its results/tket_global_phase_port.json output is
what belongs in the paper, not any number invented here.

API NOTES (confirmed by quotation from docs.quantinuum.com/tket, not by execution)
------------------------------------------------------------------------------------
  * Circuit(n): gate methods .H(q), .X(q), .CX(c,t), .CU1(angle_half_turns, c, t), .SWAP(a,b); all
    angles in HALF-TURNS (1.0 == pi radians). The .CU1/.SWAP construction below mirrors the
    generalised-QFT example given verbatim in the pytket phase-estimation user-guide page.
  * Circuit.phase / Circuit.add_phase(a): global phase, in half-turns.
  * Circuit.get_unitary(): "ILO-BE convention" -- Increasing Lexicographic Order + Big Endian,
    i.e. qubit index 0 is the MOST significant bit of the matrix index. This is the OPPOSITE of
    the bit convention src/cart/oracles/global_phase.py's _permute_sv relies on (Qiskit: qubit 0 =
    least significant bit) -- the permutation helper below is re-derived for BE bit order, not
    copied from that file.
  * pytket.architecture.Architecture(list_of_int_pairs): coupling-map constructor.
  * pytket.predicates.CompilationUnit(circ): .circuit (current circuit); .initial_map and
    .final_map, "the map from the original qubits to the corresponding qubits at the start/end of
    the current circuit" -- i.e. the tket analogue of Qiskit's initial_index_layout() /
    final_index_layout(), which is exactly what global_phase.py's Qiskit-side layout normalization
    already relies on.
  * pytket.passes.DefaultMappingPass(architecture).apply(cu): places + routes; can introduce a
    qubit permutation (a "layout"), the same idea as Qiskit's transpile() with a coupling_map.
  * pytket.passes.RemoveImplicitQubitPermutation(): "Remove any implicit qubit permutation by
    appending SWAP gates." Included in the pipeline below SPECIFICALLY so get_unitary() is
    guaranteed to reflect an explicit gate sequence with no leftover implicit boundary
    relabelling -- the fetched docs do not state whether get_unitary() itself accounts for an
    implicit permutation, and that could not be checked by execution, so the ambiguity is designed
    out rather than assumed away.
  * pytket.passes.SequencePass([...]).apply(cu): applies passes in order, updating cu's maps
    cumulatively.

If any of the above turns out not to match the installed pytket version when this is finally run,
that mismatch -- not the general approach -- is what needs fixing first.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

try:
    from pytket.circuit import Circuit
    from pytket.architecture import Architecture
    from pytket.passes import DefaultMappingPass, RemoveImplicitQubitPermutation, SequencePass
    from pytket.predicates import CompilationUnit
except ImportError as exc:  # pragma: no cover - exercised only in the hand-off environment
    sys.exit(
        "tket_global_phase_port.py requires pytket, which is intentionally NOT part of this "
        "project's Qiskit-only anchor environment (see environment/ENV.md). Install it in a "
        "separate/throwaway virtualenv (`pip install pytket`) and re-run there.\n"
        f"Import error: {exc}"
    )

ROOT = Path(__file__).resolve().parents[1]

# Same radian magnitudes as scripts/channel_matched_eval.py's PHASES list, so the injected fault is
# the same size on both SDKs; converted to half-turns (pytket's angle unit) at the call site.
PHASES_RAD = [math.pi, math.pi / 2, math.pi / 3, 2 * math.pi / 7, 0.3, 1.0]
PHASE_TOL = 1e-7


def _wrap(phi: float) -> float:
    return (phi + math.pi) % (2 * math.pi) - math.pi


def circuits():
    """Same two families and sizes as channel_matched_eval.py's circuits(): GHZ (line-native,
    entangling -- routes almost trivially on a line architecture) and QFT (all-to-all controlled-
    phase structure -- forces real SWAP insertion on a line, exercising the permutation-
    normalization machinery non-trivially)."""
    out = []
    for n in (4, 5, 6):
        g = Circuit(n)
        g.H(0)
        for i in range(n - 1):
            g.CX(i, i + 1)
        out.append((f"ghz{n}", g))

        # Built the same way as pytket's own generalised-QFT user-guide example: H then
        # descending CU1 controlled-phase rungs, final SWAPs to restore bit order.
        q = Circuit(n)
        for i in range(n):
            q.H(i)
            for j in range(i + 1, n):
                q.CU1(1 / 2 ** (j - i), j, i)
        for k in range(n // 2):
            q.SWAP(k, n - k - 1)
        out.append((f"qft{n}", q))
    return out


def _line_architecture(n: int) -> "Architecture":
    return Architecture([(i, i + 1) for i in range(n - 1)])


def route(circ: "Circuit") -> "CompilationUnit":
    """Route `circ` against a line architecture of matching width and strip any implicit boundary
    permutation, so get_unitary() below is guaranteed to reflect an explicit gate sequence only."""
    n = circ.n_qubits
    cu = CompilationUnit(circ.copy())
    SequencePass([
        DefaultMappingPass(_line_architecture(n)),
        RemoveImplicitQubitPermutation(),
    ]).apply(cu)
    return cu


def _permutation_matrix_be(perm: list[int], n: int) -> np.ndarray:
    """dim x dim permutation matrix (ILO-BE bit order: qubit 0 = most significant bit) mapping a
    LOGICAL basis index to the PHYSICAL basis index, given perm[i] = physical wire holding logical
    qubit i."""
    dim = 1 << n
    P = np.zeros((dim, dim))
    for logical_idx in range(dim):
        physical_idx = 0
        for i in range(n):
            bit = (logical_idx >> (n - 1 - i)) & 1
            physical_idx |= bit << (n - 1 - perm[i])
        P[physical_idx, logical_idx] = 1.0
    return P


def _logical_perm(original: "Circuit", routed: "Circuit", mapping: dict) -> list[int]:
    """perm[i] = index, within routed.qubits, of the physical wire that `mapping` (initial_map or
    final_map, keyed by the ORIGINAL circuit's qubits) associates with original.qubits[i]."""
    pos = {wire: idx for idx, wire in enumerate(routed.qubits)}
    return [pos[mapping[lq]] for lq in original.qubits]


def _to_logical_unitary(U_routed: np.ndarray, original: "Circuit", routed: "Circuit",
                         initial_map: dict, final_map: dict) -> np.ndarray:
    """Re-express a routed circuit's ILO-BE unitary in the ORIGINAL logical qubit ordering, undoing
    both the initial placement and the final position implied by CompilationUnit's maps:

        U_logical = P_out^T @ U_routed @ P_in

    (P_in/P_out place/read logical qubit i at the physical wire initial_map/final_map send it to.)
    This is the tket analogue of global_phase.py's Qiskit-side _permute_sv + initial/final index
    layout combination, generalized to a full unitary and re-derived for tket's BE bit order and
    for the (in general nontrivial) initial placement as well as the final one."""
    n = original.n_qubits
    P_in = _permutation_matrix_be(_logical_perm(original, routed, initial_map), n)
    P_out = _permutation_matrix_be(_logical_perm(original, routed, final_map), n)
    return P_out.T @ U_routed @ P_in


def check_global_phase_tket(original: "Circuit", routed: "Circuit",
                             initial_map: dict, final_map: dict) -> dict:
    """Matched oracle: layout-normalize `routed`'s unitary back to `original`'s qubit ordering,
    then check whether the two differ by nothing more than a global phase, and whether that phase
    is ~0 (preserved) or not (the fault). Mirrors check_global_phase's exact tier
    (src/cart/oracles/global_phase.py); only the exact tier is ported here -- n <= 6 throughout
    this family, well inside its range -- the sampled tier (>12 qubits, statevector probes) is
    future work, not attempted in this port."""
    n = original.n_qubits
    Uo = original.get_unitary()
    Ut = _to_logical_unitary(routed.get_unitary(), original, routed, initial_map, final_map)
    M = Uo.conj().T @ Ut
    phi = float(np.angle(np.trace(M)))
    pure_global = bool(np.allclose(M, np.exp(1j * phi) * np.eye(2 ** n), atol=1e-8))
    if not pure_global:
        return {"equivalent": None, "delta": None,
                "note": "differs by more than a global phase (not this oracle's job)"}
    delta = _wrap(phi)
    return {"equivalent": abs(delta) <= PHASE_TOL, "delta": delta}


def output_oracle_blind(original: "Circuit", routed: "Circuit",
                         initial_map: dict, final_map: dict) -> bool:
    """Stand-in for the Qiskit side's check_semantic / Operator.equiv: 'equivalent up to an
    arbitrary global phase'. True iff the routed circuit is equivalent to the original modulo SOME
    global phase -- which, for any purely-additive global-phase mutant layered on top of an
    already single-global-phase-equivalent pair, is true by construction (that construction IS the
    output-invisible-channel argument). It is measured here, not just asserted, so the
    sensitivity/blindness pairing below is reported the same way channel_matched_eval.py reports
    it for Qiskit."""
    n = original.n_qubits
    Uo = original.get_unitary()
    Ut = _to_logical_unitary(routed.get_unitary(), original, routed, initial_map, final_map)
    M = Uo.conj().T @ Ut
    phi = float(np.angle(np.trace(M)))
    return bool(np.allclose(M, np.exp(1j * phi) * np.eye(2 ** n), atol=1e-6))


def main() -> int:
    rows = []
    tp = n_gp = 0
    fp = tn = 0

    for cname, circ in circuits():
        cu = route(circ)
        routed, im, fm = cu.circuit, cu.initial_map, cu.final_map

        # --- specificity: matched oracle on the clean, unmutated routed circuit ---
        clean = check_global_phase_tket(circ, routed, im, fm)
        if clean["equivalent"] is True:
            tn += 1
        elif clean["equivalent"] is False:
            fp += 1
        rows.append({"circuit": cname, "delta": 0.0, "clean_baseline": True,
                     "detected": clean["equivalent"] is False, "note": clean.get("note")})

        # --- sensitivity: inject the same phase offsets as channel_matched_eval.py ---
        for d in PHASES_RAD:
            t_bad = routed.copy()
            t_bad.add_phase(d / math.pi)  # tket angles are in half-turns
            res = check_global_phase_tket(circ, t_bad, im, fm)
            blind = output_oracle_blind(circ, t_bad, im, fm)
            n_gp += 1
            detected = res["equivalent"] is False
            if detected and blind:
                tp += 1
            rows.append({"circuit": cname, "delta": round(d, 4), "clean_baseline": False,
                         "detected": detected, "output_blind": blind,
                         "recovered_delta": res.get("delta")})

    sens = tp / n_gp if n_gp else 0.0
    spec = tn / (tn + fp) if (tn + fp) else 0.0
    summary = {
        "sdk": "pytket",
        "mutants": n_gp, "detected_and_blind": tp, "sensitivity": round(sens, 3),
        "clean_runs": tn + fp, "false_positives": fp, "specificity": round(spec, 3),
    }
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "tket_global_phase_port.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2))

    print("=" * 70)
    print("TKET PORT -- global-phase matched oracle (RQ2.4 / PLAN_1B B-3)")
    print(f"sensitivity: {summary['sensitivity']}  ({tp}/{n_gp} phase mutants detected AND "
          f"output-blind)")
    print(f"specificity: {summary['specificity']}  ({tn}/{tn + fp} clean runs silent, "
          f"{fp} false positives)")
    print("wrote results/tket_global_phase_port.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
