#!/usr/bin/env python3
"""verify_16402_cc_phase.py -- #16402 CommutativeCancellation P/U1 global-phase verifier.

PR #16402 ("Fix incorrect global phase shift for P and U1 gates in CommutativeCancellation") fixes a
global-phase regression: CommutativeCancellation merges a run of T gates into a P/U1/RZ rotation and must
track the global phase that merge introduces. The buggy parent mistracks it for P and U1 gates specifically
(RZ was already correct), while the merged circuit stays functionally correct -- output-invisible.

Trigger and observable taken directly from the fix's own regression test
(test/python/transpiler/test_commutative_cancellation.py::test_p_u1_2pi_accumulation), not invented from
the PR title (the standing lesson from #14939 and #15024 v1's inert generic triggers):

    basis = ["p", "t", "rz", "cx"]
    cc = CommutativeCancellation(basis_gates=basis)
    qc = QuantumCircuit(1); qc.append(PhaseGate(pi/4), [0])
    for _ in range(15): qc.t(0)
    tqc = cc(qc)
    # upstream expects global_phase == 0.0 for a P-gate run (only RZ carries a nonzero expected phase)

Usage (from D:\CUSIT PhD\Post BASR -- both venvs already built, sv-16402-fix / sv-16402-bug):

  python scripts\verify_16402_cc_phase.py `
    --baseline-python environment\_builds\sv-16402-fix\venv\Scripts\python.exe `
    --candidate-python environment\_builds\sv-16402-bug\venv\Scripts\python.exe `
    --out results\sv-16402-ccphase
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

_PROBE = r'''
import json, math, traceback
from pathlib import Path
import argparse


def build_trigger():
    from qiskit import QuantumCircuit
    from qiskit.circuit.library import PhaseGate
    qc = QuantumCircuit(1)
    qc.append(PhaseGate(math.pi / 4), [0])
    for _ in range(15):
        qc.t(0)
    return qc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = {"status": "ok"}
    try:
        import qiskit
        from qiskit.transpiler import PassManager
        from qiskit.transpiler.passes import CommutativeCancellation
        out["qiskit_version"] = qiskit.__version__
        original = build_trigger()
        basis = ["p", "t", "rz", "cx"]
        cc = CommutativeCancellation(basis_gates=basis)
        tqc = PassManager([cc]).run(original)
        out["global_phase"] = float(tqc.global_phase)
        out["gate_counts"] = dict(tqc.count_ops())
        try:
            from cart.oracles.semantic import check_semantic
            from cart.manifest.static_manifest import DEFAULT_BASIS
            sem = check_semantic(original, tqc, coupling_map=None, basis_gates=list(DEFAULT_BASIS))
            out["output_equivalent"] = sem.equivalent
        except Exception as exc:
            out["output_equivalent"] = None
            out["semantic_error"] = (type(exc).__name__ + ": " + str(exc))[:200]
    except Exception as exc:
        out["status"] = "error"
        out["error_type"] = type(exc).__name__
        out["error"] = str(exc)[:400]
        out["traceback"] = traceback.format_exc()[-1200:]
    Path(a.out).write_text(json.dumps(out, indent=2, default=str))


main()
'''


def _run_probe(python_exe: str, work: Path) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    probe_py = work / "probe_16402.py"
    probe_py.write_text(_PROBE)
    result = work / "result.json"
    cmd = [str(python_exe), str(probe_py), "--out", str(result)]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    subprocess.run(cmd, cwd=str(_REPO_ROOT), env=env, check=True, capture_output=True, timeout=600)
    return json.loads(result.read_text())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="#16402 CommutativeCancellation P/U1 global-phase verifier.")
    p.add_argument("--event", default="sv-16402-ccphase")
    p.add_argument("--pr", default="16402")
    p.add_argument("--baseline-python", required=True, help="GOOD/fixed build (sv-16402-fix)")
    p.add_argument("--candidate-python", required=True, help="BUGGY build (sv-16402-bug)")
    p.add_argument("--out", default=str(_REPO_ROOT / "results" / "sv-16402-ccphase"))
    args = p.parse_args(argv)

    print("# #16402 CommutativeCancellation P/U1 global-phase verification (upstream regression-test trigger)")
    print("# trigger: PhaseGate(pi/4) + 15x t(0), CommutativeCancellation(basis_gates=[p,t,rz,cx])")
    print("# baseline(good/fixed) vs candidate(buggy)\n")

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bw = _run_probe(args.baseline_python, tmp / "base")
        cw = _run_probe(args.candidate_python, tmp / "cand")

        rec: dict = {"schema": "global_phase_ccphase_16402/v1", "event_id": args.event, "pr": args.pr,
                     "trigger": {"circuit": "PhaseGate(pi/4); 15x t(0)", "isolated_pass": "CommutativeCancellation",
                                 "basis_gates": ["p", "t", "rz", "cx"]},
                     "qiskit_version": {"baseline": bw.get("qiskit_version"), "candidate": cw.get("qiskit_version")},
                     "worker_status": {"baseline": bw.get("status"), "candidate": cw.get("status")}}

        if bw.get("status") != "ok" or cw.get("status") != "ok":
            rec["verdict"] = "inconclusive"
            rec["reason"] = "a build failed to run the trigger (not a refutation)"
            rec["errors"] = {"baseline": bw.get("error"), "candidate": cw.get("error")}
            _emit(out_root, rec)
            print("INCONCLUSIVE -- a build errored on the trigger (not a refutation):")
            print(f"  baseline : {bw.get('error_type')}: {bw.get('error')}")
            print(f"  candidate: {cw.get('error_type')}: {cw.get('error')}")
            return 3

        rec["baseline"] = {"global_phase": bw.get("global_phase"), "gate_counts": bw.get("gate_counts"),
                           "output_equivalent": bw.get("output_equivalent")}
        rec["candidate"] = {"global_phase": cw.get("global_phase"), "gate_counts": cw.get("gate_counts"),
                            "output_equivalent": cw.get("output_equivalent")}

        gb, gc = bw.get("global_phase"), cw.get("global_phase")
        phase_differs = (gb is not None and gc is not None and abs(gb - gc) > 1e-6)
        output_oracle_blind = (cw.get("output_equivalent") is True)
        fault_detected = bool(phase_differs and output_oracle_blind)

        rec["phase_differs"] = phase_differs
        rec["output_oracle_blind"] = output_oracle_blind
        rec["fault_detected"] = fault_detected
        if fault_detected:
            rec["verdict"] = "positive"
            rec["note"] = ("global_phase diverges between builds while the output oracle stays blind -- "
                           "the #16402 global-phase fault is reproduced")
        elif not output_oracle_blind:
            rec["verdict"] = "inconclusive"
            rec["note"] = "outputs not equivalent modulo phase -- not a pure global-phase fault; check the trigger"
        else:
            rec["verdict"] = "negative_here"
            rec["note"] = ("output blind but global_phase identical across builds -- the detector did not fire "
                           "with basis_gates=[p,t,rz,cx]; try the RZGate/U1Gate variants of the same upstream "
                           "test, or a different rep count from (7,15,23,31)")
        _emit(out_root, rec)

        print(f"baseline : global_phase={gb}  output_equivalent={bw.get('output_equivalent')}")
        print(f"candidate: global_phase={gc}  output_equivalent={cw.get('output_equivalent')}")
        print(f"\nphase_differs={phase_differs}  output_oracle_blind={output_oracle_blind}  "
              f"=> fault_detected={fault_detected}")
        print(f"verdict: {rec['verdict']} -- {rec['note']}")
        return 0 if fault_detected else (2 if output_oracle_blind else 3)


def _emit(out_root: Path, rec: dict) -> None:
    out = out_root / f"ccphase_16402-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(rec, indent=2, default=str))
    print(f"raw: {out}")


if __name__ == "__main__":
    raise SystemExit(main())
