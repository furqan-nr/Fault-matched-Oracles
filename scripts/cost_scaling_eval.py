#!/usr/bin/env python3
"""Cost and scaling measurement for the oracle family (B-2, PLAN_1B.md G3, RQ2.3's cost half).

Measures per-oracle CPU cost (process_time, thread-pinned) against a plain output-equivalence check
(check_semantic, the "null" baseline this study otherwise compares against) across a qubit-count
sweep spanning the family's own width tiers (METHODOLOGY / build_1b.js S4.1): an EXACT tier (n <= 12,
full 2^n x 2^n operator permitted), a SAMPLED tier (12 < n <= 22, statevector probes only, no full
operator -- global-phase tracker only; check_semantic and MR-1 fall back to structural/n-a here by
their own design, see src/cart/oracles/semantic.py and metamorphic.py), and beyond (structural only,
n/a for phase and semantic equivalence alike). The interesting comparison is NOT "does the matched
family avoid an exponential blowup the baseline suffers" -- check_semantic is already engineered with
the same width-tiering discipline and gracefully downgrades to a cheap structural check above 12
qubits rather than blowing up. The real contrast is WITHIN the shared exact tier (n<=12), and it splits
the family in two. The contract checker never touches amplitudes (pure metadata/list-level check, cost
essentially flat in n -- confirmed empirically at ~0.005-0.011ms across the whole n=4..20 sweep) and
keeps working at every width the sweep tests, including where semantic and phase have both fallen back
to n/a. MR-1, by contrast, DOES touch amplitudes and is NOT cheap: check_permutation_consistency
(metamorphic.py) builds Operator(original) plus Operator(transpiled-with-an-appended-n-qubit-
PermutationGate) and checks their equivalence -- the same two-operator-equivalence shape check_semantic
uses, plus one more gate. Empirically that one extra gate dominates (MR-1 measured ~2.9x check_semantic
at n=8, ~10.6x at n=12), consistent with the appended PermutationGate being composed as a full
2^n x 2^n dense matrix (an n-qubit gate has no small local factor to exploit) rather than folded in
analytically the way Operator.from_circuit's routing/layout normalization is for check_semantic's own
baseline path. Report this honestly in the paper: MR-1 is the single most expensive oracle in the
family within the exact tier, not a free metadata check -- the cost story is "contract is free, phase
is cheap in-tier, MR-1 carries real exact-tier overhead that grows with n," not "the whole family is
free."

Protocol (KAGGLE_CALIBRATION.md discipline, ../Paper 2 - Selection/): thread-pinned
(RAYON_NUM_THREADS=1, OMP_NUM_THREADS=1, set BEFORE importing qiskit), CPU process_time, one warmup
call discarded, median of >=5 timed repeats -- each repeat itself a CALIBRATED BATCH of N back-to-back
calls (N chosen so the batch's total time clears ~50ms) with the per-call cost recovered by dividing.
This is needed because time.process_time() on Windows is quantized to the OS scheduler's CPU-accounting
tick (commonly ~15.6 ms / 64 Hz) -- timing a single sub-millisecond call directly on Windows reads back
as a noisy multiple of that tick (0 ms, or 15.625 ms, or 46.875 ms = 3 ticks), not the true cost.
Batching many calls into one timed window averages the +-1-tick quantization error down to a
per-call fraction, the same trick `timeit` uses. Genuinely expensive calls (the exact/12-qubit tier)
already clear the threshold at batch=1, so they are never artificially repeated more than the
requested number of times. Hardware is recorded via `platform` (cross-platform; this study's earlier
calibration work recorded /proc/cpuinfo on Linux/Kaggle, this script runs on the user's own machine
so it records what `platform`/env vars can see there instead) -- run it on an otherwise IDLE machine
(close other applications first), per the same "quiet, stable, documented hardware" discipline
KAGGLE_CALIBRATION.md itself insists on; a run with other programs competing for CPU produces
numbers this study cannot stand behind.

The determinism runner is NOT included in this per-call comparison: its cost is a different shape
of measurement (a multi-process, multi-hashseed reproducibility PROTOCOL - see
determinism_mutant_eval.py - not a single oracle call), and is reported qualitatively in prose instead.

Run from repo root:  python scripts/cost_scaling_eval.py
Writes results/cost_scaling_eval.json.

NOTE: authored without a local Qiskit install available to the authoring session -- please skim the
printed summary for sanity (in particular that costs actually change shape around n=12 and n=22)
before trusting the numbers in the paper, and report back anything that errors.
"""
import os

# Must happen BEFORE the first `import qiskit` anywhere in this process.
os.environ.setdefault("RAYON_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("QISKIT_IN_PARALLEL", "TRUE")

import json, platform, statistics as st, sys, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qiskit import QuantumCircuit
from qiskit.transpiler import CouplingMap

from cart.events.mutations import baseline_transpiler
from cart.oracles.semantic import check_semantic, UNITARY_MAX_QUBITS
from cart.oracles.contract_differ import check_contracts
from cart.oracles.metamorphic import check_permutation_consistency
from cart.oracles.global_phase import check_global_phase, SAMPLED_SV_MAX_QUBITS

BASIS = ["cx", "rz", "sx", "x"]
WIDTHS = [4, 8, 12, 16, 20]     # spans the exact tier (<=12) and the sampled tier (12 < n <= 22)
REPEATS = 5


def ghz(n):
    qc = QuantumCircuit(n); qc.h(0)
    for i in range(n - 1): qc.cx(i, i + 1)
    return qc


def cfg_for(n):
    return dict(coupling_map=CouplingMap.from_line(n), basis_gates=list(BASIS),
                optimization_level=3, seed_transpiler=1234)


TARGET_BATCH_S = 0.5    # calibrate batch size so each timed window clears ~500ms (raised from 50ms:
                        # at 50ms, an n=8-ish call landing at batch=8 only divides the +-1-tick
                        # (~15.6ms) quantization error by 8, leaving ~5-15% residual noise per call --
                        # 500ms typically pushes batch to ~64 for the same call, cutting residual
                        # noise to ~1-2%. Calls that already clear 500ms on their own (n=12+) are
                        # unaffected -- they still stop at batch=1, per _calibrate_batch's design.


def _calibrate_batch(fn, target_s=TARGET_BATCH_S, max_batch=20000):
    """Find a batch size N such that timing N back-to-back calls clears `target_s` total --
    large enough that +-1 OS-tick quantization error becomes negligible per call once divided
    out. A single call that already clears target_s on its own (batch=1) is never re-multiplied."""
    batch = 1
    while True:
        t0 = time.process_time()
        for _ in range(batch):
            fn()
        dt = time.process_time() - t0
        if dt >= target_s or batch >= max_batch:
            return max(batch, 1)
        batch *= 8


def timed_median(fn, repeats=REPEATS):
    """process_time, warmup discarded, median of `repeats` CALIBRATED-BATCH timings (see
    _calibrate_batch) -- resolves per-call cost well below one OS CPU-accounting tick.

    Returns (median, dispersion, result) where dispersion is a dict with min/max/stdev
    across the `repeats` per-call samples, added so a reviewer can see how stable the
    reported point estimate is (a referee comment on the first draft asked for exactly
    this -- a bare median across only ~5 repeats hides how noisy any one number might be)."""
    result = fn()  # warmup (JIT-ish caches, first-call overhead) -- discarded, keep the result shape
    batch = _calibrate_batch(fn)
    samples = []
    for _ in range(repeats):
        t0 = time.process_time()
        for _ in range(batch):
            result = fn()
        samples.append((time.process_time() - t0) / batch)
    dispersion = {
        "min": min(samples),
        "max": max(samples),
        "stdev": st.stdev(samples) if len(samples) > 1 else 0.0,
        "n_repeats": len(samples),
    }
    return st.median(samples), dispersion, result


def hardware_info():
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER"),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "RAYON_NUM_THREADS": os.environ.get("RAYON_NUM_THREADS"),
        "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS"),
    }


def main():
    rows = []
    for n in WIDTHS:
        cm = CouplingMap.from_line(n)
        cfg = cfg_for(n)
        circ = ghz(n)
        transpiled = baseline_transpiler(cfg)(circ)

        row = {"n_qubits": n, "exact_tier": n <= UNITARY_MAX_QUBITS,
               "sampled_tier": UNITARY_MAX_QUBITS < n <= SAMPLED_SV_MAX_QUBITS}

        med_sem, disp_sem, sem_r = timed_median(lambda: check_semantic(circ, transpiled, coupling_map=cm, basis_gates=BASIS))
        row["semantic_ms"] = round(med_sem * 1000, 5)
        row["semantic_ms_range"] = [round(disp_sem["min"] * 1000, 5), round(disp_sem["max"] * 1000, 5)]
        row["semantic_ms_stdev"] = round(disp_sem["stdev"] * 1000, 5)
        row["semantic_strength"] = sem_r.strength
        row["semantic_equivalent"] = sem_r.equivalent

        med_con, disp_con, con_r = timed_median(lambda: check_contracts(circ, transpiled, coupling_map=cm, basis_gates=BASIS))
        row["contract_ms"] = round(med_con * 1000, 5)
        row["contract_ms_range"] = [round(disp_con["min"] * 1000, 5), round(disp_con["max"] * 1000, 5)]
        row["contract_ms_stdev"] = round(disp_con["stdev"] * 1000, 5)
        row["contract_violations"] = len(con_r)

        med_mr1, disp_mr1, mr1_r = timed_median(lambda: check_permutation_consistency(circ, transpiled))
        row["mr1_ms"] = round(med_mr1 * 1000, 5)
        row["mr1_ms_range"] = [round(disp_mr1["min"] * 1000, 5), round(disp_mr1["max"] * 1000, 5)]
        row["mr1_ms_stdev"] = round(disp_mr1["stdev"] * 1000, 5)
        row["mr1_holds"] = mr1_r.holds

        med_gp, disp_gp, gp_r = timed_median(lambda: check_global_phase(circ, transpiled))
        row["global_phase_ms"] = round(med_gp * 1000, 5)
        row["global_phase_ms_range"] = [round(disp_gp["min"] * 1000, 5), round(disp_gp["max"] * 1000, 5)]
        row["global_phase_ms_stdev"] = round(disp_gp["stdev"] * 1000, 5)
        row["global_phase_strength"] = gp_r.strength
        row["global_phase_equivalent"] = gp_r.equivalent

        row["overhead_contract_vs_semantic"] = (round(row["contract_ms"] / row["semantic_ms"], 4)
                                                 if row["semantic_ms"] > 0 else None)
        row["overhead_global_phase_vs_semantic"] = (round(row["global_phase_ms"] / row["semantic_ms"], 4)
                                                     if row["semantic_ms"] > 0 else None)
        rows.append(row)

    out = {"hardware": hardware_info(), "repeats_per_measurement": REPEATS,
           "widths": WIDTHS, "unitary_max_qubits": UNITARY_MAX_QUBITS,
           "sampled_sv_max_qubits": SAMPLED_SV_MAX_QUBITS, "rows": rows}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "cost_scaling_eval.json").write_text(json.dumps(out, indent=2, default=str))

    print("=" * 92)
    print("COST / SCALING MEASUREMENT")
    print(f"hardware: {out['hardware']}")
    print(f"{'n':>3}  {'tier':<10}  {'semantic(ms)':>14}  {'contract(ms)':>14}  {'MR-1(ms)':>14}  "
          f"{'phase(ms)':>14}  {'contract/sem':>12}  {'phase/sem':>10}")
    for r in rows:
        tier = "exact" if r["exact_tier"] else ("sampled" if r["sampled_tier"] else "beyond")
        print(f"{r['n_qubits']:>3}  {tier:<10}  {r['semantic_ms']:>14.5f}  {r['contract_ms']:>14.5f}  "
              f"{r['mr1_ms']:>14.5f}  {r['global_phase_ms']:>14.5f}  "
              f"{str(r['overhead_contract_vs_semantic']):>12}  {str(r['overhead_global_phase_vs_semantic']):>10}")
    print("wrote results/cost_scaling_eval.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
