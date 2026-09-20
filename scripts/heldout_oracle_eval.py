#!/usr/bin/env python3
"""Held-out evaluation of the fault-class-matched oracles (EMSE R2, point 1).

SPECIFICITY: run the 10 mutation families (all disjoint from the three source-verified design cases
#14603/#14919/#14956) through the matched oracles and measure false positives on clean baselines and
spurious firings on these out-of-channel faults.
SENSITIVITY: inject a synthetic, held-out global-phase corruption and confirm the global-phase oracle
catches it while the output-equivalence oracle stays blind.
MR-1 precondition: MR-1 assumes the circuit has NO inherent qubit permutation, so it is applied only to
permutation-free circuits (GHZ); QFT (bit-reversal) is out of scope and marked n/a.

Runs on the anchor Qiskit (no from-source builds).  From the repo root:
    python scripts/heldout_oracle_eval.py
Writes results/heldout_oracle_eval.json and prints a paper-ready summary.
"""
import json, math, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qiskit import QuantumCircuit
from qiskit.circuit.library import QFT
from qiskit.transpiler import CouplingMap
from qiskit.transpiler.exceptions import TranspilerError

from cart.events.mutations import MUTATION_OPERATORS, get_operator, baseline_transpiler
from cart.oracles.semantic import check_semantic
from cart.oracles.contract_differ import check_contracts
from cart.oracles.metamorphic import check_permutation_consistency
from cart.oracles.global_phase import check_global_phase

BASIS = ["cx", "rz", "sx", "x"]

def triggers():
    out = []
    for n in (4, 5, 6):
        ghz = QuantumCircuit(n, name=f"ghz{n}"); ghz.h(0)
        for i in range(n - 1): ghz.cx(i, i + 1)
        out.append((f"ghz{n}", ghz, True))                       # True => permutation-free (MR-1 applies)
        qft = QuantumCircuit(n, name=f"qft{n}"); qft.compose(QFT(n), inplace=True)
        out.append((f"qft{n}", qft, False))                      # QFT bit-reversal => MR-1 n/a
    return out

def cfg_for(n):
    return dict(coupling_map=CouplingMap.from_line(n), basis_gates=list(BASIS),
                optimization_level=3, seed_transpiler=1234)

def run_matched(orig, transpiled, cm, mr1_ok):
    r = {}
    try: r["contract"] = len(check_contracts(orig, transpiled, coupling_map=cm, basis_gates=BASIS)) > 0
    except Exception as e: r["contract"] = f"err:{type(e).__name__}"
    if mr1_ok:
        try: r["mr1"] = (check_permutation_consistency(orig, transpiled).holds is False)
        except Exception as e: r["mr1"] = f"err:{type(e).__name__}"
    else:
        r["mr1"] = None                                          # out of MR-1 precondition
    try: r["global_phase"] = (check_global_phase(orig, transpiled).equivalent is False)
    except Exception as e: r["global_phase"] = f"err:{type(e).__name__}"
    return r

def any_detect(d): return any(v is True for v in d.values())

def main():
    rows = []
    # ---- SPECIFICITY: the 10 real mutation families ----
    for fam in MUTATION_OPERATORS:
        op = get_operator(fam)
        for cname, circ, mr1_ok in triggers():
            n = circ.num_qubits; cm = CouplingMap.from_line(n); cfg = cfg_for(n)
            base_t = baseline_transpiler(cfg)(circ)
            try:
                mut_t = op.transpiler(cfg)(circ)
            except TranspilerError:
                rows.append({"kind": "real", "family": fam, "circuit": cname,
                             "mutant_crashes": True, "output_visible": "crash (compilation_failure)",
                             "matched_detected": None}); continue
            sem = check_semantic(circ, mut_t, coupling_map=cm, basis_gates=BASIS)
            det = run_matched(circ, mut_t, cm, mr1_ok)
            fp  = run_matched(circ, base_t, cm, mr1_ok)
            rows.append({"kind": "real", "family": fam, "circuit": cname,
                         "output_blind": (sem.equivalent is True),
                         "matched_detected": any_detect(det), "detail": det, "baseline_fp": fp})
    # ---- SENSITIVITY: synthetic held-out global-phase corruption ----
    for cname, circ, mr1_ok in triggers():
        n = circ.num_qubits; cm = CouplingMap.from_line(n); cfg = cfg_for(n)
        t = baseline_transpiler(cfg)(circ)
        t_bad = t.copy(); t_bad.global_phase = float(t.global_phase) + math.pi   # inject pi phase error
        sem = check_semantic(circ, t_bad, coupling_map=cm, basis_gates=BASIS)
        gp = check_global_phase(circ, t_bad)
        rows.append({"kind": "synthetic_phase", "circuit": cname,
                     "output_blind": (sem.equivalent is True),
                     "global_phase_detected": (gp.equivalent is False),
                     "delta": None if gp.global_phase_delta is None else round(float(gp.global_phase_delta), 4)})
    # ---- aggregate ----
    real = [r for r in rows if r["kind"] == "real" and "detail" in r]
    def fp_count(oracle, only_ghz=False):
        hit = tot = 0
        for r in real:
            v = r["baseline_fp"].get(oracle)
            if v is None: continue
            if only_ghz and not r["circuit"].startswith("ghz"): continue
            tot += 1; hit += (1 if v is True else 0)
        return hit, tot
    synth = [r for r in rows if r["kind"] == "synthetic_phase"]
    crashes = [r for r in rows if r.get("mutant_crashes")]
    summary = {
        "specificity_runs": len(real),
        "false_positives": {o: {"fired": fp_count(o, o == "mr1")[0], "of": fp_count(o, o == "mr1")[1]}
                            for o in ("contract", "mr1", "global_phase")},
        "spurious_channel_detections_on_out_of_channel_mutants":
            sum(1 for r in real if r["matched_detected"] is True),
        "crash_family_visible_compilation_failures": len(crashes),
        "sensitivity_synthetic_phase": {
            "runs": len(synth),
            "output_blind": sum(1 for r in synth if r["output_blind"]),
            "phase_oracle_detected": sum(1 for r in synth if r["global_phase_detected"])},
    }
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "heldout_oracle_eval.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2, default=str))
    print("=" * 66)
    print("HELD-OUT ORACLE EVALUATION")
    print(f"Specificity: {summary['specificity_runs']} runs (10 held-out mutation families x 6 circuits)")
    for o, d in summary["false_positives"].items():
        note = "  (MR-1 applied only to permutation-free GHZ)" if o == "mr1" else ""
        print(f"   false positives on clean baselines - {o:13s}: {d['fired']}/{d['of']}{note}")
    print(f"   spurious detections on out-of-channel mutants: "
          f"{summary['spurious_channel_detections_on_out_of_channel_mutants']}/{len(real)}")
    print(f"   incomplete-basis mutant -> visible compilation failure (crash): "
          f"{summary['crash_family_visible_compilation_failures']} runs")
    s = summary["sensitivity_synthetic_phase"]
    print(f"Sensitivity: synthetic global-phase corruption, {s['runs']} circuits")
    print(f"   output oracle blind: {s['output_blind']}/{s['runs']}   "
          f"global-phase oracle detected: {s['phase_oracle_detected']}/{s['runs']}")
    errs = [r for r in real if any(str(v).startswith("err:") for v in r.get("detail", {}).values())]
    if errs:
        print(f"\n{len(errs)} run(s) had oracle errors - paste to fix:")
        for r in errs[:6]: print("  ", r["family"], r["circuit"], r["detail"])
    print("wrote results/heldout_oracle_eval.json")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
