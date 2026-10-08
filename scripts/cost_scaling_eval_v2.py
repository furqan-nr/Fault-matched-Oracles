#!/usr/bin/env python3
"""Cost / scaling measurement across THREE circuit families (review response B4).

cost_scaling_eval.py measured per-oracle cost on GHZ only. A reviewer noted the cost ORDERING
(contract << phase ~ semantic << MR-1 in the exact tier) could be GHZ-specific. This version runs the
identical thread-pinned, calibrated-batch protocol (see cost_scaling_eval.py's header for the full
timing discipline) on GHZ, QFT, and pseudo-random circuits, so the ordering can be read across
structurally different inputs rather than one family.

Families (all unitary-pure, no measurements, so every oracle tier applies the same way):
  * ghz    : the original family (line-native, shallow).
  * qft    : all-to-all controlled-phase structure, forces real SWAP insertion on a line.
  * random : qiskit.circuit.random.random_circuit(n, depth=n, max_operands=2, seed=1234+n), a
             fixed-seed pseudo-random circuit; deterministic across runs so the cost numbers are
             reproducible.

Widths span the exact tier (n<=12) and sampled tier (12<n<=22): [4, 8, 12, 16, 20].

Run from repo root (anchor Qiskit env active, otherwise-idle machine):  python scripts/cost_scaling_eval_v2.py
Writes results/cost_scaling_eval_v2.json. The original cost_scaling_eval.json (GHZ) is left intact.
"""
import os
os.environ.setdefault("RAYON_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("QISKIT_IN_PARALLEL", "TRUE")

import json, platform, statistics as st, sys, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qiskit import QuantumCircuit
from qiskit.circuit.library import QFT
from qiskit.circuit.random import random_circuit
from qiskit.transpiler import CouplingMap

from cart.events.mutations import baseline_transpiler
from cart.oracles.semantic import check_semantic, UNITARY_MAX_QUBITS
from cart.oracles.contract_differ import check_contracts
from cart.oracles.metamorphic import check_permutation_consistency
from cart.oracles.global_phase import check_global_phase, SAMPLED_SV_MAX_QUBITS

BASIS = ["cx", "rz", "sx", "x"]
WIDTHS = [4, 8, 12, 16, 20]
REPEATS = 5
TARGET_BATCH_S = 0.5


def make_circuit(family, n):
    if family == "ghz":
        qc = QuantumCircuit(n); qc.h(0)
        for i in range(n - 1): qc.cx(i, i + 1)
        return qc
    if family == "qft":
        qc = QuantumCircuit(n); qc.compose(QFT(n), inplace=True); return qc
    if family == "random":
        # fixed seed per width -> reproducible; no measurements -> unitary-pure
        return random_circuit(n, depth=n, max_operands=2, measure=False, seed=1234 + n)
    raise ValueError(family)


def cfg_for(n):
    return dict(coupling_map=CouplingMap.from_line(n), basis_gates=list(BASIS),
                optimization_level=3, seed_transpiler=1234)


def _calibrate_batch(fn, target_s=TARGET_BATCH_S, max_batch=20000):
    batch = 1
    while True:
        t0 = time.process_time()
        for _ in range(batch): fn()
        if time.process_time() - t0 >= target_s or batch >= max_batch:
            return max(batch, 1)
        batch *= 8


def timed_median(fn, repeats=REPEATS):
    result = fn()
    batch = _calibrate_batch(fn)
    samples = []
    for _ in range(repeats):
        t0 = time.process_time()
        for _ in range(batch): result = fn()
        samples.append((time.process_time() - t0) / batch)
    disp = {"min": min(samples), "max": max(samples),
            "stdev": st.stdev(samples) if len(samples) > 1 else 0.0, "n_repeats": len(samples)}
    return st.median(samples), disp, result


def hardware_info():
    return {"python_version": platform.python_version(), "platform": platform.platform(),
            "processor": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER"),
            "machine": platform.machine(), "cpu_count": os.cpu_count(),
            "RAYON_NUM_THREADS": os.environ.get("RAYON_NUM_THREADS"),
            "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS")}


def main():
    rows = []
    for family in ("ghz", "qft", "random"):
        for n in WIDTHS:
            cm = CouplingMap.from_line(n); cfg = cfg_for(n)
            circ = make_circuit(family, n)
            transpiled = baseline_transpiler(cfg)(circ)
            row = {"family": family, "n_qubits": n,
                   "exact_tier": n <= UNITARY_MAX_QUBITS,
                   "sampled_tier": UNITARY_MAX_QUBITS < n <= SAMPLED_SV_MAX_QUBITS}
            med, disp, r = timed_median(lambda: check_semantic(circ, transpiled, coupling_map=cm, basis_gates=BASIS))
            row["semantic_ms"] = round(med * 1000, 5); row["semantic_strength"] = r.strength
            med, disp, r = timed_median(lambda: check_contracts(circ, transpiled, coupling_map=cm, basis_gates=BASIS))
            row["contract_ms"] = round(med * 1000, 5); row["contract_violations"] = len(r)
            med, disp, r = timed_median(lambda: check_permutation_consistency(circ, transpiled))
            row["mr1_ms"] = round(med * 1000, 5); row["mr1_holds"] = r.holds
            med, disp, r = timed_median(lambda: check_global_phase(circ, transpiled))
            row["global_phase_ms"] = round(med * 1000, 5); row["global_phase_strength"] = r.strength
            row["contract_vs_semantic"] = (round(row["contract_ms"]/row["semantic_ms"], 4)
                                           if row["semantic_ms"] > 0 else None)
            row["phase_vs_semantic"] = (round(row["global_phase_ms"]/row["semantic_ms"], 4)
                                        if row["semantic_ms"] > 0 else None)
            row["mr1_vs_semantic"] = (round(row["mr1_ms"]/row["semantic_ms"], 4)
                                      if row["semantic_ms"] > 0 else None)
            rows.append(row)

    out = {"hardware": hardware_info(), "repeats_per_measurement": REPEATS, "widths": WIDTHS,
           "families": ["ghz", "qft", "random"], "unitary_max_qubits": UNITARY_MAX_QUBITS,
           "sampled_sv_max_qubits": SAMPLED_SV_MAX_QUBITS, "rows": rows}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "cost_scaling_eval_v2.json").write_text(json.dumps(out, indent=2, default=str))

    print("=" * 100)
    print("COST / SCALING across GHZ, QFT, random  (B4)")
    print(f"hardware: {out['hardware']['platform']}  py{out['hardware']['python_version']}")
    print(f"{'family':<8}{'n':>3}  {'tier':<8}{'semantic':>11}{'contract':>11}{'MR-1':>11}{'phase':>11}"
          f"{'con/sem':>9}{'phase/sem':>10}{'mr1/sem':>9}")
    for r in rows:
        tier = "exact" if r["exact_tier"] else ("sampled" if r["sampled_tier"] else "beyond")
        print(f"{r['family']:<8}{r['n_qubits']:>3}  {tier:<8}{r['semantic_ms']:>11.5f}{r['contract_ms']:>11.5f}"
              f"{r['mr1_ms']:>11.5f}{r['global_phase_ms']:>11.5f}{str(r['contract_vs_semantic']):>9}"
              f"{str(r['phase_vs_semantic']):>10}{str(r['mr1_vs_semantic']):>9}")
    print("wrote results/cost_scaling_eval_v2.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
