#!/usr/bin/env python3
"""N4 verification — the global-phase oracle measures the TRUE global-phase relationship between a
circuit and its transpilation (agreeing with an independent |0>-statevector ground truth), detects an
injected phase fault, and abstains on genuine semantic differences. The semantic (modulo-phase) oracle
is shown BLIND to the phase faults — the observability gap this oracle closes.

Run in any venv with Qiskit installed (no from-source build needed):
  PYTHONPATH=src python scripts/verify_n4_global_phase.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit.circuit.random import random_circuit
from qiskit.quantum_info import Statevector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cart.oracles.global_phase import check_global_phase, _permute_sv, _wrap   # noqa: E402
from cart.oracles.semantic import check_semantic                              # noqa: E402


def _clean(n, depth, seed):
    return random_circuit(n, depth, max_operands=2, measure=False, seed=seed)


def ground_truth(orig, tqc):
    """Independent phase measurement from the |0> statevector (different method than the operator
    tier). Returns (delta_rad, |overlap|)."""
    so = Statevector(orig).data
    st = Statevector(tqc).data
    fin = tqc.layout.final_index_layout() if tqc.layout is not None else None
    if fin is not None:
        st = _permute_sv(st, list(fin))
    ov = np.vdot(so, st)
    return float(np.angle(ov)), float(abs(ov))


def main() -> int:
    rng = np.random.default_rng(0)
    fails, n_checks, preserved_count = [], 0, 0

    def expect(cond, msg):
        nonlocal n_checks
        n_checks += 1
        if not cond:
            fails.append(msg)
        print(("  ok   " if cond else "  FAIL ") + msg)

    print("== 1. exact tier (n<=12): oracle matches independent ground-truth phase ==")
    for seed in range(10):
        orig = _clean(4, 6, seed)
        tqc = transpile(orig, basis_gates=["cx", "rz", "sx", "x"],
                        coupling_map=[[0, 1], [1, 2], [2, 3]], optimization_level=3, seed_transpiler=7)
        gt, mag = ground_truth(orig, tqc)
        r = check_global_phase(orig, tqc)
        if abs(gt) < 1e-6:
            preserved_count += 1
        expect(r.global_phase_delta is not None and abs(_wrap(r.global_phase_delta - gt)) < 1e-5,
               f"seed{seed}: delta matches truth (oracle={round(r.global_phase_delta,3) if r.global_phase_delta is not None else None}, truth={round(gt,3)})")
        expect(r.equivalent == (abs(_wrap(gt)) <= 1e-7),
               f"seed{seed}: equivalent flag correct ({r.equivalent})")
    print(f"  (info: {preserved_count}/10 transpilations preserved phase exactly; the rest carry a real transpiler phase shift)")

    print("\n== 2. injected global-phase fault: oracle DETECTS, semantic oracle is BLIND ==")
    for seed in range(8):
        orig = _clean(4, 6, seed)
        good = transpile(orig, basis_gates=["cx", "rz", "sx", "x"],
                         coupling_map=[[0, 1], [1, 2], [2, 3]], optimization_level=1, seed_transpiler=7)
        gt_good, _ = ground_truth(orig, good)
        buggy = good.copy()
        drop = float(rng.uniform(0.3, math.pi - 0.3))
        buggy.global_phase = buggy.global_phase + drop
        r = check_global_phase(orig, buggy)
        sem = check_semantic(orig, buggy)
        expect(r.equivalent is False and abs(_wrap(r.global_phase_delta - (gt_good + drop))) < 1e-5,
               f"seed{seed}: DETECTS injected {round(drop,2)} (oracle delta={round(r.global_phase_delta,2)})")
        expect(sem.equivalent is True, f"seed{seed}: semantic oracle BLIND  <- the gap")

    print("\n== 3. genuine semantic difference: gp-oracle abstains (None), semantic FAILS ==")
    for seed in range(6):
        orig = _clean(4, 6, seed)
        good = transpile(orig, basis_gates=["cx", "rz", "sx", "x"], optimization_level=1, seed_transpiler=7)
        broken = good.copy(); broken.x(0)
        expect(check_global_phase(orig, broken).equivalent is None, f"seed{seed}: gp-oracle abstains")
        expect(check_semantic(orig, broken).equivalent is False, f"seed{seed}: semantic oracle FAILS")

    print("\n== 4. sampled tier (n=14, statevectors only): matches truth + detects injected fault ==")
    orig = _clean(14, 4, 3)
    tqc = transpile(orig, basis_gates=["cx", "rz", "sx", "x"],
                    coupling_map=[[i, i + 1] for i in range(13)], optimization_level=1, seed_transpiler=7)
    gt, mag = ground_truth(orig, tqc)
    r = check_global_phase(orig, tqc)
    expect(r.strength == "sampled" and r.global_phase_delta is not None and abs(_wrap(r.global_phase_delta - gt)) < 1e-5,
           f"n14 matches truth (oracle={None if r.global_phase_delta is None else round(r.global_phase_delta,3)}, truth={round(gt,3)}, strength={r.strength})")
    buggy = tqc.copy(); buggy.global_phase += 0.9
    r2 = check_global_phase(orig, buggy)
    expect(r2.strength == "sampled" and r2.equivalent is False and abs(_wrap(r2.global_phase_delta - (gt + 0.9))) < 1e-5,
           f"n14 DETECTS injected 0.9 (oracle delta={None if r2.global_phase_delta is None else round(r2.global_phase_delta,3)})")

    print(f"\n================  {n_checks - len(fails)}/{n_checks} checks passed  ================")
    if fails:
        print("FAILURES:")
        for f in fails:
            print("  -", f)
        return 1
    print("N4 global-phase oracle: truthful, zero false positives, detects the invisible channel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
