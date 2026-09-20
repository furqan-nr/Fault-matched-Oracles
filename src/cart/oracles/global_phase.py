"""N4 — Global-phase-tracking oracle (METHODOLOGY §2.2, global_phase channel).

The semantic oracle (`check_semantic`) compares transpiled vs original **modulo global phase**
(`Operator.equiv`). By construction it cannot see a dropped/altered global phase — one of the study's
output-invisible channels. This oracle is its complement: it checks that transpilation preserved the
circuit's global phase, so a pass that drops or double-counts it is DETECTED end-to-end.

Tiers (respecting the "no full unitary beyond small circuits" rule):
  - exact      n <= 12: build the layout-normalized operator (small circuits only; a full 2^n x 2^n
               operator is allowed here) and extract the global phase relating the two.
  - sampled    12 < n <= 22: probe with k Haar-random product-state inputs and compare the two output
               STATEVECTORS (2^n vector, not a 2^n x 2^n operator) including phase. A true global-phase
               difference gives |<psi_o|psi_t>| ~ 1 with a phase offset consistent across all probes.
  - structural otherwise (non-unitary / ancilla / n > 22): cannot assess phase (equivalent=None).

`equivalent` semantics: True = global phase preserved (good build); False = phase dropped/altered
(the fault); None = not assessable, or the two circuits differ by MORE than a global phase (that is a
semantic difference, which is the semantic oracle's job, not this one).
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator, Statevector

from .semantic import is_unitary_pure, UNITARY_MAX_QUBITS, SAMPLED_SV_MAX_QUBITS

PHASE_TOL = 1e-7          # radians; below this the global phase is "preserved"
MAG_TOL = 1e-6           # |overlap| must be ~1 for a pure-global-phase relationship
CONSISTENCY_TOL = 1e-6   # sampled phases must agree across probes


@dataclass
class GlobalPhaseResult:
    strength: str                      # exact / sampled / structural
    equivalent: bool | None            # True=phase preserved; False=phase fault; None=not assessable
    global_phase_delta: float | None   # radians, wrapped to (-pi, pi]; None if not assessable
    cost_s: float
    details: dict[str, Any] = field(default_factory=dict)


def _wrap(phi: float) -> float:
    return (phi + math.pi) % (2 * math.pi) - math.pi


def _final_index_layout(transpiled: QuantumCircuit) -> list[int] | None:
    layout = getattr(transpiled, "layout", None)
    if layout is None:
        return None
    fn = getattr(layout, "final_index_layout", None)
    if not callable(fn):
        return None
    try:
        return list(fn())
    except Exception:
        return None


def _initial_index_layout(transpiled: QuantumCircuit) -> list[int] | None:
    layout = getattr(transpiled, "layout", None)
    if layout is None:
        return None
    fn = getattr(layout, "initial_index_layout", None)
    if not callable(fn):
        return None
    try:
        return list(fn())
    except Exception:
        return None


def _permute_sv(data: np.ndarray, perm: list[int]) -> np.ndarray:
    """Reorder statevector amplitudes so target qubit i holds old (physical) qubit perm[i].
    Little-endian bit order (qubit q -> bit q of the index)."""
    n = len(perm)
    out = np.empty_like(data)
    for old in range(data.shape[0]):
        new = 0
        for i in range(n):
            new |= ((old >> perm[i]) & 1) << i
        out[new] = data[old]
    return out


def _random_product_prep(n: int, rng: np.random.Generator) -> QuantumCircuit:
    """A random single-qubit-product state prep (Haar per qubit) — cheap, no entanglement."""
    qc = QuantumCircuit(n)
    for q in range(n):
        # Haar-random single-qubit rotation
        theta = 2 * math.acos(math.sqrt(rng.random()))
        phi = 2 * math.pi * rng.random()
        lam = 2 * math.pi * rng.random()
        qc.u(theta, phi, lam, q)
    return qc


def check_global_phase(
    original: QuantumCircuit,
    transpiled: QuantumCircuit,
    *,
    sampled_k: int = 5,
    seed: int = 0,
) -> GlobalPhaseResult:
    t0 = time.perf_counter()
    n = original.num_qubits
    ancilla = transpiled.num_qubits != n

    if (not is_unitary_pure(original)) or ancilla or n > SAMPLED_SV_MAX_QUBITS:
        reason = ("non_unitary" if not is_unitary_pure(original)
                  else "ancilla_added" if ancilla else "too_large")
        return GlobalPhaseResult("structural", None, None, time.perf_counter() - t0,
                                 {"reason": reason})

    # --- exact tier: small circuits only (full operator permitted here) ---
    if n <= UNITARY_MAX_QUBITS:
        Uo = Operator(original).data
        Ut = Operator.from_circuit(transpiled).data          # layout-normalized
        M = Uo.conj().T @ Ut
        phi = float(np.angle(np.trace(M)))
        pure_global = bool(np.allclose(M, np.exp(1j * phi) * np.eye(2 ** n), atol=1e-8))
        if not pure_global:
            return GlobalPhaseResult("exact", None, None, time.perf_counter() - t0,
                                     {"note": "circuits differ by more than a global phase "
                                              "(semantic difference — use the semantic oracle)"})
        delta = _wrap(phi)
        preserved = abs(delta) <= PHASE_TOL
        return GlobalPhaseResult("exact", preserved, delta, time.perf_counter() - t0,
                                 {"method": "operator_phase"})

    # --- sampled tier: 13..22 qubits, statevectors only (no 2^n x 2^n operator) ---
    init = _initial_index_layout(transpiled)
    fin = _final_index_layout(transpiled)
    rng = np.random.default_rng(seed)
    nq_t = transpiled.num_qubits
    # probe with |0..0> (layout-trivial) plus random computational-basis inputs, each routed to the
    # transpiled circuit's physical wires via the initial layout, output un-permuted via final layout.
    probes = [[0] * n] + [list(rng.integers(0, 2, n)) for _ in range(max(0, sampled_k - 1))]
    phis, mags = [], []
    for bits in probes:
        oc = QuantumCircuit(n)
        for i, b in enumerate(bits):
            if b:
                oc.x(i)
        so = Statevector(oc.compose(original)).data
        tc = QuantumCircuit(nq_t)
        for i, b in enumerate(bits):
            if b:
                tc.x(init[i] if init else i)
        st = Statevector(tc.compose(transpiled)).data
        if fin is not None and len(fin) == n:
            st = _permute_sv(st, fin)
        ov = np.vdot(so, st)
        mags.append(abs(ov)); phis.append(np.angle(ov))
    mags = np.asarray(mags); phis = np.asarray(phis)
    if np.any(np.abs(mags - 1.0) > MAG_TOL):
        return GlobalPhaseResult("sampled", None, None, time.perf_counter() - t0,
                                 {"note": "not a pure global-phase relationship (|overlap|<1); "
                                          "semantic difference or layout mismatch",
                                  "min_overlap": float(mags.min())})
    ref = phis[0]
    spread = float(np.max(np.abs(_np_wrap(phis - ref))))
    delta = _wrap(float(np.angle(np.mean(np.exp(1j * phis)))))
    if spread > CONSISTENCY_TOL:
        return GlobalPhaseResult("sampled", None, None, time.perf_counter() - t0,
                                 {"note": "phase inconsistent across probes; not a global phase",
                                  "phase_spread": spread})
    preserved = abs(delta) <= PHASE_TOL
    return GlobalPhaseResult("sampled", preserved, delta, time.perf_counter() - t0,
                             {"method": "sampled_statevector_phase", "k": len(probes)})


def _np_wrap(a: np.ndarray) -> np.ndarray:
    return (a + math.pi) % (2 * math.pi) - math.pi
