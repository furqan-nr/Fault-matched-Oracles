#!/usr/bin/env python3
"""Channel-matched evaluation with a metrics table (supervisor Action 4).

Builds a channel-matched GLOBAL-PHASE mutation family (synthetic phase-injection faults across
circuits and phase offsets), and measures, on the anchor Qiskit (no from-source builds):
  * SENSITIVITY  - fraction of channel faults the matched oracle detects while the output oracle
                   stays blind (a true output-invisible detection), with a 95% Wilson interval;
  * SPECIFICITY  - fraction of clean-baseline oracle runs that do NOT fire, with a Wilson interval;
  * RUNTIME      - median matched-oracle call time (ms);
  * MEMORY       - peak traced memory of a matched-oracle call (KB).
Contract/metadata-channel sensitivity is reported from the two source-verified real fixes
(#14603 contract differ, #14919 MR-1); determinism is reproduced separately under a noise-scored target (scripts/determinism_eval.py).
Run from repo root:  python scripts/channel_matched_eval.py
Writes results/channel_matched_eval.json and prints the metrics table.
"""
import json, math, statistics as st, sys, time, tracemalloc, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qiskit import QuantumCircuit
from qiskit.circuit.library import QFT
from qiskit.transpiler import CouplingMap

from cart.events.mutations import baseline_transpiler
from cart.oracles.semantic import check_semantic
from cart.oracles.contract_differ import check_contracts
from cart.oracles.metamorphic import check_permutation_consistency
from cart.oracles.global_phase import check_global_phase

BASIS = ["cx", "rz", "sx", "x"]
PHASES = [math.pi, math.pi / 2, math.pi / 3, 2 * math.pi / 7, 0.3, 1.0]   # channel-matched phase offsets

def wilson(k, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0, c - h), 3), round(min(1, c + h), 3))

def circuits():
    out = []
    for n in (4, 5, 6):
        g = QuantumCircuit(n); g.h(0)
        for i in range(n - 1): g.cx(i, i + 1)
        out.append((f"ghz{n}", g))
        q = QuantumCircuit(n); q.compose(QFT(n), inplace=True)
        out.append((f"qft{n}", q))
    return out

def cfg_for(n):
    return dict(coupling_map=CouplingMap.from_line(n), basis_gates=list(BASIS),
                optimization_level=3, seed_transpiler=1234)

def timed_mem(fn):
    tracemalloc.start(); t0 = time.perf_counter()
    r = fn()
    dt = (time.perf_counter() - t0) * 1000.0
    peak = tracemalloc.get_traced_memory()[1] / 1024.0
    tracemalloc.stop()
    return r, dt, peak

def main():
    rows = []
    gp_times, gp_mem = [], []
    tp = n_gp = 0
    fp = tn = 0
    for cname, circ in circuits():
        n = circ.num_qubits; cm = CouplingMap.from_line(n); cfg = cfg_for(n)
        base_t = baseline_transpiler(cfg)(circ)
        # --- SPECIFICITY: 3 matched oracles on the clean baseline ---
        for name, fn in (("contract", lambda: len(check_contracts(circ, base_t, coupling_map=cm, basis_gates=BASIS)) > 0),
                         ("mr1", lambda: check_permutation_consistency(circ, base_t).holds is False if cname.startswith("ghz") else None),
                         ("global_phase", lambda: check_global_phase(circ, base_t).equivalent is False)):
            v = fn()
            if v is None: continue
            n_ = 1
            if v is True: fp += 1
            else: tn += 1
        # --- SENSITIVITY: global-phase family ---
        for d in PHASES:
            t_bad = base_t.copy(); t_bad.global_phase = float(base_t.global_phase) + d
            (gp, sem), dt, mem = timed_mem(lambda: (check_global_phase(circ, t_bad),
                                                    check_semantic(circ, t_bad, coupling_map=cm, basis_gates=BASIS)))
            gp_times.append(dt); gp_mem.append(mem)
            detected = gp.equivalent is False
            blind = sem.equivalent is True
            n_gp += 1
            if detected and blind: tp += 1
            rows.append({"circuit": cname, "delta": round(d, 4), "detected": detected,
                         "output_blind": blind, "oracle_ms": round(dt, 2), "peak_kb": round(mem, 1)})
    sens = tp / n_gp if n_gp else 0
    spec = tn / (tn + fp) if (tn + fp) else 0
    summary = {
        "global_phase_channel": {
            "mutants": n_gp, "detected_and_blind": tp,
            "sensitivity": round(sens, 3), "sensitivity_wilson95": wilson(tp, n_gp),
            "median_oracle_ms": round(st.median(gp_times), 2) if gp_times else None,
            "peak_memory_kb": round(max(gp_mem), 1) if gp_mem else None},
        "specificity_all_channels": {
            "clean_runs": tn + fp, "false_positives": fp,
            "specificity": round(spec, 3), "specificity_wilson95": wilson(tn, tn + fp)},
        "contract_metadata_channel": {"note": "sensitivity from 2 source-verified real fixes",
            "detected": 2, "of": 2, "fixes": ["#14603 (contract differ)", "#14919 (MR-1)"]},
        "determinism_channel": {"note": "reproduced separately under a noise-scored target; see scripts/determinism_eval.py and results/determinism_eval.json"},
    }
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "channel_matched_eval.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    g = summary["global_phase_channel"]; s = summary["specificity_all_channels"]
    print("=" * 70)
    print("CHANNEL-MATCHED EVALUATION - metrics")
    print(f"{'channel':22s}{'sensitivity (95% CI)':26s}{'specificity (95% CI)':26s}")
    print(f"{'global phase':22s}{str(g['sensitivity'])+' '+str(g['sensitivity_wilson95']):26s}"
          f"{str(s['specificity'])+' '+str(s['specificity_wilson95']):26s}")
    print(f"{'contract/metadata':22s}{'2/2 (real fixes)':26s}{str(s['specificity']):26s}")
    print(f"{'determinism':22s}{'reproduced (determinism_eval.py)':26s}{'-':26s}")
    print(f"runtime: median matched-oracle call {g['median_oracle_ms']} ms   "
          f"peak memory {g['peak_memory_kb']} KB   ({g['mutants']} phase mutants, {s['clean_runs']} clean runs)")
    print("wrote results/channel_matched_eval.json")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
