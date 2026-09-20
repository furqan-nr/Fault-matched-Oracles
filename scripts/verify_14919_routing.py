#!/usr/bin/env python3
"""N2 / MR-1 verification of PR #14919 (final_layout / routing_permutation composition).

Runs the PR's own regression scenario (an identity circuit routed through 5 coupling maps in a row) in
the fix and parent from-source venvs, then applies MR-1 (append routing_permutation -> must recover the
identity). On the FIXED build the invariant holds; on the BUGGY build the recorded routing_permutation
is composed backwards, so it does NOT undo routing — yet the routed output is still identity modulo
layout permutation, so an output-equivalence oracle is BLIND. That is the output-invisible contract
fault, caught by the metamorphic oracle.

Reuses environment/_builds/sv-14919-fix/venv and sv-14919-bug/venv (already built). No new builds.
  PYTHONPATH=src python scripts/verify_14919_routing.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
IS_WIN = os.name == "nt"

# Embedded worker: builds the #14919 scenario, routes it, dumps routing_permutation + whether MR-1 holds.
WORKER = r'''
import json, sys, random
import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import PermutationGate
from qiskit.transpiler import CouplingMap, PassManager, passes
from qiskit.quantum_info import Operator
out, routing = sys.argv[1], sys.argv[2]
def random_line(n, rng):
    line = list(range(n)); rng.shuffle(line)
    cm = CouplingMap([[a, b] for a, b in zip(line[:-1], line[1:])]); cm.make_symmetric(); return cm
rng = random.Random(0); n = 5
qc = QuantumCircuit(n)
for i in range(n):
    for j in range(n):
        if i != j: qc.cx(i, j)
qc.barrier(); qc.compose(qc.inverse(), qc.qubits, inplace=True)
gens = {"sabre": lambda cmap, seed: passes.SabreSwap(cmap, seed=seed, trials=1),
        "lookahead": lambda cmap, _s: passes.LookaheadSwap(cmap),
        "basic": lambda cmap, seed: passes.BasicSwap(cmap)}
pm = PassManager([passes.SetLayout(list(range(n))), passes.ApplyLayout()])
pm += PassManager([gens[routing](random_line(n, rng), i) for i in range(5)])
res = pm.run(qc)
rp = [int(x) for x in res.layout.routing_permutation()]
# MR-1: append routing_permutation, must recover identity (qc is identity)
test = res.copy(); test.append(PermutationGate(rp), test.qubits)
mr1 = bool(np.allclose(Operator(test).data, np.eye(2**n), atol=1e-8))
json.dump({"routing_permutation": rp, "mr1_recovers_identity": mr1,
           "qiskit_version": __import__("qiskit").__version__}, open(out, "w"))
'''


def venv_python(env_id: str) -> Path | None:
    base = _ROOT / "environment" / "_builds" / env_id / "venv"
    for c in (base / "Scripts" / "python.exe", base / "bin" / "python"):
        if c.exists():
            return c
    return None


def run_in(py: Path, routing: str, tmp: Path) -> dict:
    script = tmp / "w.py"; script.write_text(WORKER)
    out = tmp / f"{routing}.json"
    subprocess.run([str(py), str(script), str(out), routing], check=True, capture_output=True, timeout=600)
    return json.loads(out.read_text())


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="MR-1 verification of PR #14919 (fix-boundary by default).")
    ap.add_argument("--fix-env", default="sv-14919-fix", help="env-id of the GOOD build (baseline)")
    ap.add_argument("--bug-env", default="sv-14919-bug", help="env-id of the BUGGY build (candidate)")
    a = ap.parse_args(argv)
    fix = venv_python(a.fix_env); bug = venv_python(a.bug_env)
    if not fix or not bug:
        print(f"missing {a.fix_env} / {a.bug_env} venvs; build them with "
              f"environment/setup/build_qiskit_event.ps1, or run source_validate_mining.py --only 14919.")
        return 2
    print("# MR-1 (permutation consistency) — PR #14919, fix vs parent from source\n")
    rows = []
    with tempfile.TemporaryDirectory() as _t:
        tmp = Path(_t)
        for routing in ("sabre", "lookahead", "basic"):
            f = run_in(fix, routing, tmp); b = run_in(bug, routing, tmp)
            detected = (f["mr1_recovers_identity"] is True) and (b["mr1_recovers_identity"] is False)
            rows.append((routing, f, b, detected))
            print(f"  routing={routing:9}  fix MR-1={f['mr1_recovers_identity']}  "
                  f"bug MR-1={b['mr1_recovers_identity']}  -> fault detected: {detected}")
    any_detect = any(r[3] for r in rows)
    out = _ROOT / "data" / "raw" / "hist-final-layout-composition"
    out.mkdir(parents=True, exist_ok=True)
    import time
    (out / f"mr1_run-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json").write_text(
        json.dumps({"schema": "mr1_run/v1", "pr": 14919,
                    "rows": [{"routing": r[0], "fix": r[1], "bug": r[2], "detected": r[3]} for r in rows]}, indent=2))
    print(f"\nverdict: {'MR-1 DETECTS #14919 from source' if any_detect else 'no divergence — check builds'} "
          f"(output-equivalence oracle is blind: routed circuit is identity modulo layout permutation).")
    return 0 if any_detect else 1


if __name__ == "__main__":
    raise SystemExit(main())
