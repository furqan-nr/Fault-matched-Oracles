#!/usr/bin/env python3
"""verify_16215_router_phase.py -- #16215 Commuting2qGateRouter global-phase verifier.

PR #16215 ("Fix Commuting2qGateRouter global phase handling") fixes a global-phase regression: the pass's
internal phase accumulator was not reset to zero before being reused, so a circuit routed through it could
have its global phase corrupted even with NO commuting blocks at all, while the compiled circuit's
structure/behaviour is otherwise untouched -- output-invisible by construction.

NOTE: this project already has scripts/verify_16215_forward.py, but it runs a GENERIC qft/8 trigger through
the full preset pass manager, pointed at bisection venvs from the superseded bisection methodology (see
PLAN_1B.md's G5 / bisection-provenance correction). A generic QFT circuit never invokes
Commuting2qGateRouter at all (that pass only fires on PauliEvolutionGate / commuting-block circuits such as
QAOA), so that script is almost certainly blind to this fault for the same reason #14939 and #15024-v1 were
blind: a plausible-looking trigger that never reaches the buggy code path. This script instead mirrors the
fix's own regression test exactly
(test/python/transpiler/test_swap_strategy_router.py::test_global_phase_preserved_without_commuting_blocks):

    circ = QuantumCircuit(4, global_phase=0.3); circ.h(0); circ.cx(0, 1)
    swap_strat = SwapStrategy.from_line([0, 1, 2, 3])
    routed = PassManager([Commuting2qGateRouter(swap_strat)]).run(circ)
    # upstream expects: routed.global_phase == circ.global_phase == 0.3

Usage (from D:\CUSIT PhD\Post BASR -- both venvs already built, sv-16215-fix / sv-16215-bug):

  python scripts\verify_16215_router_phase.py `
    --baseline-python environment\_builds\sv-16215-fix\venv\Scripts\python.exe `
    --candidate-python environment\_builds\sv-16215-bug\venv\Scripts\python.exe `
    --out results\sv-16215-routerphase
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
import json, traceback
from pathlib import Path
import argparse


def build_trigger():
    from qiskit import QuantumCircuit
    circ = QuantumCircuit(4, global_phase=0.3)
    circ.h(0)
    circ.cx(0, 1)
    return circ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = {"status": "ok"}
    try:
        import qiskit
        from qiskit.transpiler import PassManager
        from qiskit.transpiler.passes.routing.commuting_2q_gate_routing import (
            SwapStrategy, Commuting2qGateRouter,
        )
        out["qiskit_version"] = qiskit.__version__
        original = build_trigger()
        swap_strat = SwapStrategy.from_line([0, 1, 2, 3])
        router = Commuting2qGateRouter(swap_strat)
        routed = PassManager([router]).run(original)
        out["global_phase"] = float(routed.global_phase)
        out["original_global_phase"] = float(original.global_phase)
        out["gate_counts"] = dict(routed.count_ops())
        try:
            from cart.oracles.semantic import check_semantic
            from cart.manifest.static_manifest import DEFAULT_BASIS
            sem = check_semantic(original, routed, coupling_map=None, basis_gates=list(DEFAULT_BASIS))
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
    probe_py = work / "probe_16215.py"
    probe_py.write_text(_PROBE)
    result = work / "result.json"
    cmd = [str(python_exe), str(probe_py), "--out", str(result)]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    subprocess.run(cmd, cwd=str(_REPO_ROOT), env=env, check=True, capture_output=True, timeout=600)
    return json.loads(result.read_text())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="#16215 Commuting2qGateRouter global-phase verifier.")
    p.add_argument("--event", default="sv-16215-routerphase")
    p.add_argument("--pr", default="16215")
    p.add_argument("--baseline-python", required=True, help="GOOD/fixed build (sv-16215-fix)")
    p.add_argument("--candidate-python", required=True, help="BUGGY build (sv-16215-bug)")
    p.add_argument("--out", default=str(_REPO_ROOT / "results" / "sv-16215-routerphase"))
    args = p.parse_args(argv)

    print("# #16215 Commuting2qGateRouter global-phase verification (upstream regression-test trigger)")
    print("# trigger: QuantumCircuit(4, global_phase=0.3); h(0); cx(0,1) -- no commuting blocks")
    print("# baseline(good/fixed) vs candidate(buggy)\n")

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bw = _run_probe(args.baseline_python, tmp / "base")
        cw = _run_probe(args.candidate_python, tmp / "cand")

        rec: dict = {"schema": "global_phase_routerphase_16215/v1", "event_id": args.event, "pr": args.pr,
                     "trigger": {"circuit": "QuantumCircuit(4, global_phase=0.3); h(0); cx(0,1)",
                                 "pass": "Commuting2qGateRouter(SwapStrategy.from_line([0,1,2,3]))"},
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

        rec["baseline"] = {"global_phase": bw.get("global_phase"), "output_equivalent": bw.get("output_equivalent")}
        rec["candidate"] = {"global_phase": cw.get("global_phase"), "output_equivalent": cw.get("output_equivalent")}

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
                           "the #16215 global-phase fault is reproduced")
        elif not output_oracle_blind:
            rec["verdict"] = "inconclusive"
            rec["note"] = "outputs not equivalent modulo phase -- not a pure global-phase fault; check the trigger"
        else:
            rec["verdict"] = "negative_here"
            rec["note"] = ("output blind but global_phase identical across builds on this exact upstream "
                           "trigger -- if this holds, #16215 may not be forward-verifiable with the current "
                           "oracle family; record as such rather than trying more generic triggers")
        _emit(out_root, rec)

        print(f"baseline : global_phase={gb}  output_equivalent={bw.get('output_equivalent')}")
        print(f"candidate: global_phase={gc}  output_equivalent={cw.get('output_equivalent')}")
        print(f"\nphase_differs={phase_differs}  output_oracle_blind={output_oracle_blind}  "
              f"=> fault_detected={fault_detected}")
        print(f"verdict: {rec['verdict']} -- {rec['note']}")
        return 0 if fault_detected else (2 if output_oracle_blind else 3)


def _emit(out_root: Path, rec: dict) -> None:
    out = out_root / f"routerphase_16215-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(rec, indent=2, default=str))
    print(f"raw: {out}")


if __name__ == "__main__":
    raise SystemExit(main())
