#!/usr/bin/env python3
"""verify_15040_dag_order.py -- #15040 DAG edge-order determinism verifier (EXPLORATORY).

PR #15040 ("Fix edge-order non-determinism when adding DAG nodes") fixes a Rust-level non-determinism in
DAGCircuit::apply_operation_back/front: adding a high-degree node (e.g. a Barrier spanning many qubits) can
wire its edges in a different order across otherwise-identical calls. This is lower-level than the paper's
other two determinism faults (#14730 VF2Layout, #16237 ConsolidateBlocks), which are both visible through a
normal transpile() call; this one lives inside the DAG data structure itself and is verified here by
mirroring the fix's own regression test directly
(test/python/dagcircuit/test_dagcircuit.py::TestDagApplyOperation::test_apply_operation_determinism):

    qc = QuantumCircuit(100)
    left = circuit_to_dag(qc);  DAGCircuit.apply_operation_back(left,  Barrier(100), qc.qubits, [])
    right = circuit_to_dag(qc); DAGCircuit.apply_operation_back(right, Barrier(100), qc.qubits, [])
    # upstream fix asserts: left.structurally_equal(right) is True

EXPLORATORY, unlike the other two scripts in this batch: it is not yet established that this shows the
paper's usual "raw fingerprint diverges while functional fingerprint agrees" signature, since a Barrier
changes no circuit semantics either way -- there is no separate "functional" observable to contrast against
here, only the structural (raw) one. Treat a positive as evidence of the SAME determinism_runner failure
mode (an internal representation that should be reproducible is not), but write it up as its own case, not
silently folded into #14730/#16237's exact framing.

Runs the probe in N separate fresh processes per build (like the project's own PYTHONHASHSEED-sweep
protocol for #14730/#16237), since this non-determinism is a hash-map iteration order that -- like
PYTHONHASHSEED-driven dict ordering -- may only vary ACROSS process restarts, not within one.

Usage (from the repository root -- both venvs already built, sv-15040-fix / sv-15040-bug):

  python scripts\verify_15040_dag_order.py `
    --baseline-python environment\_builds\sv-15040-fix\venv\Scripts\python.exe `
    --candidate-python environment\_builds\sv-15040-bug\venv\Scripts\python.exe `
    --repeats 10 `
    --out results\sv-15040-dagorder

If this comes back negative_here, re-run with --repeats 50 before concluding (see the note it prints).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

_PROBE = r'''
import json, traceback
from pathlib import Path
import argparse


def one_run():
    from qiskit import QuantumCircuit
    from qiskit.circuit import Barrier
    from qiskit.converters import circuit_to_dag
    from qiskit.dagcircuit import DAGCircuit

    qc = QuantumCircuit(100)
    qubits = qc.qubits
    left = circuit_to_dag(qc)
    DAGCircuit.apply_operation_back(left, Barrier(len(qubits)), qubits, [])
    right = circuit_to_dag(qc)
    DAGCircuit.apply_operation_back(right, Barrier(len(qubits)), qubits, [])
    return bool(left.structurally_equal(right))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = {"status": "ok"}
    try:
        import qiskit
        out["qiskit_version"] = qiskit.__version__
        out["structurally_equal"] = [one_run() for _ in range(a.repeats)]
    except Exception as exc:
        out["status"] = "error"
        out["error_type"] = type(exc).__name__
        out["error"] = str(exc)[:400]
        out["traceback"] = traceback.format_exc()[-1200:]
    Path(a.out).write_text(json.dumps(out, indent=2, default=str))


main()
'''


def _run_probe_once(python_exe: str, work: Path, repeats: int) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    probe_py = work / "probe_15040.py"
    probe_py.write_text(_PROBE)
    result = work / "result.json"
    cmd = [str(python_exe), str(probe_py), "--repeats", str(repeats), "--out", str(result)]
    subprocess.run(cmd, cwd=str(_REPO_ROOT), check=True, capture_output=True, timeout=600)
    return json.loads(result.read_text())


def _run_across_processes(python_exe: str, work: Path, n_processes: int) -> list[dict]:
    return [_run_probe_once(python_exe, work / f"proc{i}", repeats=1) for i in range(n_processes)]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="#15040 DAG edge-order determinism verifier (exploratory).")
    p.add_argument("--event", default="sv-15040-dagorder")
    p.add_argument("--pr", default="15040")
    p.add_argument("--baseline-python", required=True, help="GOOD/fixed build (sv-15040-fix)")
    p.add_argument("--candidate-python", required=True, help="BUGGY build (sv-15040-bug)")
    p.add_argument("--repeats", type=int, default=10, help="fresh processes per build")
    p.add_argument("--out", default=str(_REPO_ROOT / "results" / "sv-15040-dagorder"))
    args = p.parse_args(argv)

    print("# #15040 DAG edge-order determinism verification (EXPLORATORY, upstream regression-test trigger)")
    print("# trigger: QuantumCircuit(100); two independent circuit_to_dag() + apply_operation_back(Barrier(100))")
    print(f"# {args.repeats} fresh processes per build (each does one within-process left/right compare)\n")

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        base_runs = _run_across_processes(args.baseline_python, tmp / "base", args.repeats)
        cand_runs = _run_across_processes(args.candidate_python, tmp / "cand", args.repeats)

        base_errored = [r for r in base_runs if r.get("status") != "ok"]
        cand_errored = [r for r in cand_runs if r.get("status") != "ok"]

        rec: dict = {"schema": "dag_order_15040/v1", "event_id": args.event, "pr": args.pr,
                     "trigger": {"circuit": "QuantumCircuit(100)", "op": "apply_operation_back(Barrier(100))",
                                 "compared_via": "DAGCircuit.structurally_equal"},
                     "n_processes": args.repeats}

        if base_errored or cand_errored:
            rec["verdict"] = "inconclusive"
            rec["reason"] = "a process errored running the trigger (not a refutation)"
            rec["errors"] = {"baseline": [r.get("error") for r in base_errored],
                             "candidate": [r.get("error") for r in cand_errored]}
            _emit(out_root, rec)
            print("INCONCLUSIVE -- at least one process errored (not a refutation); see JSON for details.")
            return 3

        base_flat = [v for r in base_runs for v in r.get("structurally_equal", [])]
        cand_flat = [v for r in cand_runs for v in r.get("structurally_equal", [])]
        base_mismatches = base_flat.count(False)
        cand_mismatches = cand_flat.count(False)

        rec["baseline"] = {"structurally_equal_runs": base_flat, "mismatches": base_mismatches, "n": len(base_flat)}
        rec["candidate"] = {"structurally_equal_runs": cand_flat, "mismatches": cand_mismatches, "n": len(cand_flat)}

        fault_detected = bool(base_mismatches == 0 and cand_mismatches > 0)
        rec["fault_detected"] = fault_detected
        if fault_detected:
            rec["verdict"] = "positive"
            rec["note"] = (f"fixed build: {base_mismatches}/{len(base_flat)} mismatches; buggy parent: "
                           f"{cand_mismatches}/{len(cand_flat)} mismatches -- the edge-order non-determinism "
                           "reproduces on the buggy build and not on the fix. Report as its own case: the "
                           "observable here is DAG-internal structure, not a downstream transpile() artifact "
                           "like #14730/#16237")
        elif base_mismatches == 0 and cand_mismatches == 0:
            rec["verdict"] = "negative_here"
            rec["note"] = (f"no mismatches on either build across {args.repeats} process restarts each -- "
                           "either more processes/repeats are needed to surface it, it needs a PYTHONHASHSEED "
                           "sweep rather than default-seed restarts, or it does not reproduce with a pure-"
                           "Barrier trigger; try --repeats 50 before concluding negative")
        else:
            rec["verdict"] = "inconclusive"
            rec["note"] = "the fixed build ALSO shows mismatches -- this trigger does not cleanly separate the two builds"
        _emit(out_root, rec)

        print(f"baseline  mismatches: {base_mismatches}/{len(base_flat)}")
        print(f"candidate mismatches: {cand_mismatches}/{len(cand_flat)}")
        print(f"\n=> fault_detected={fault_detected}")
        print(f"verdict: {rec['verdict']} -- {rec['note']}")
        return 0 if fault_detected else 2


def _emit(out_root: Path, rec: dict) -> None:
    out = out_root / f"dagorder_15040-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(rec, indent=2, default=str))
    print(f"raw: {out}")


if __name__ == "__main__":
    raise SystemExit(main())
