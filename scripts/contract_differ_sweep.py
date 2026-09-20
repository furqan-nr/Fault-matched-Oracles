#!/usr/bin/env python3
"""N1 — sweep the transpiler contract differ over a circuit corpus on the INSTALLED Qiskit.

For each (circuit, width, opt level, coupling map): transpile twice (same seed) and assert the
layout/permutation contract (cart.oracles.contract_differ.check_contracts) on the first, plus MR-4
metadata idempotence between the two. Any violation is a candidate output-invisible contract bug.

A clean sweep on a released Qiskit is the expected, informative result (low false-positive rate =
the differ is trustworthy); real finds come from running it against buggy builds / current main / a
larger or adversarial corpus. --self-test proves the differ is not blind.

  PYTHONPATH=src python scripts/contract_differ_sweep.py --widths 4,6,8 --opts 1,2,3 --seeds 25
  PYTHONPATH=src python scripts/contract_differ_sweep.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from qiskit import transpile
from qiskit.circuit.random import random_circuit
from qiskit.transpiler import CouplingMap

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cart.oracles.contract_differ import check_contracts, metadata_signature   # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]


def _line(n): return [[i, i + 1] for i in range(n - 1)]
def _ring(n): return [[i, (i + 1) % n] for i in range(n)]


def self_test() -> int:
    print("== self-test: differ flags invalid / inconsistent layout metadata, passes a clean one ==")
    ok = True
    basis = ["cx", "rz", "sx", "x"]
    circ = random_circuit(4, 8, max_operands=2, measure=False, seed=1)
    t = transpile(circ, basis_gates=basis, coupling_map=CouplingMap(_line(4)),
                  optimization_level=3, seed_transpiler=1234)
    clean = check_contracts(circ, t, coupling_map=CouplingMap(_line(4)), basis_gates=basis)
    print(f"  clean transpile -> {len(clean)} violations (expect 0): {[v.kind for v in clean]}")
    ok = ok and not clean

    # C2: an invalid permutation (final_index_layout has a duplicate) must be flagged.
    class _BadLayout:
        def initial_index_layout(self): return [0, 1, 2, 3]
        def final_index_layout(self): return [0, 0, 2, 3]      # not a permutation
        def routing_permutation(self): return [0, 1, 2, 3]
    class _Stub:
        num_qubits = 4
        layout = _BadLayout()
    bad = check_contracts(circ, _Stub(), coupling_map=None, basis_gates=None)
    print(f"  invalid permutation -> {[v.kind for v in bad]} (expect invalid_permutation)")
    ok = ok and ("invalid_permutation" in [v.kind for v in bad])

    # C3: valid permutations that do NOT compose consistently must be flagged.
    class _IncLayout:
        def initial_index_layout(self): return [1, 0, 2, 3]
        def final_index_layout(self): return [0, 1, 2, 3]      # != initial∘routing
        def routing_permutation(self): return [2, 3, 0, 1]
    class _Stub2:
        num_qubits = 4
        layout = _IncLayout()
    inc = check_contracts(circ, _Stub2(), coupling_map=None, basis_gates=None)
    print(f"  inconsistent composition -> {[v.kind for v in inc]} (expect layout_composition)")
    ok = ok and ("layout_composition" in [v.kind for v in inc])

    s1 = metadata_signature(t)
    ok = ok and (s1 == metadata_signature(t))
    print(f"  metadata_signature stable on same circuit: {s1 == metadata_signature(t)}")
    print("SELF-TEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--widths", default="4,6,8")
    ap.add_argument("--depths", default="8")
    ap.add_argument("--opts", default="1,2,3")
    ap.add_argument("--seeds", type=int, default=25)
    ap.add_argument("--basis", default="cx,rz,sx,x")
    ap.add_argument("--out", default="results/contract_differ")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    widths = [int(x) for x in args.widths.split(",")]
    depths = [int(x) for x in args.depths.split(",")]
    opts = [int(x) for x in args.opts.split(",")]
    basis = args.basis.split(",")
    import qiskit
    viol: list[dict] = []
    n_cfg = 0
    t0 = time.time()
    for w in widths:
        cmaps = {"line": _line(w), "ring": _ring(w), "full": None}
        for depth in depths:
            for s in range(args.seeds):
                circ = random_circuit(w, depth, max_operands=2, measure=False, seed=s)
                for opt in opts:
                    for cname, cm in cmaps.items():
                        n_cfg += 1
                        cmap = CouplingMap(cm) if cm else None
                        base = {"width": w, "depth": depth, "opt": opt, "cmap": cname, "seed": s}
                        try:
                            t1 = transpile(circ, basis_gates=basis, coupling_map=cmap,
                                           optimization_level=opt, seed_transpiler=1234)
                            t2 = transpile(circ, basis_gates=basis, coupling_map=cmap,
                                           optimization_level=opt, seed_transpiler=1234)
                        except Exception as exc:
                            viol.append({**base, "kind": "transpile_error", "detail": f"{type(exc).__name__}: {exc}"[:200]})
                            continue
                        for x in check_contracts(circ, t1, coupling_map=cmap, basis_gates=basis):
                            viol.append({**base, "kind": x.kind, "detail": x.detail})
                        if metadata_signature(t1) != metadata_signature(t2):
                            viol.append({**base, "kind": "idempotence",
                                         "detail": "metadata differs across identical fixed-seed transpilations"})

    out_dir = _ROOT / args.out / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_dir.mkdir(parents=True, exist_ok=True)
    kinds: dict[str, int] = {}
    for x in viol:
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
    report = {"qiskit_version": qiskit.__version__, "configs": n_cfg, "violations": len(viol),
              "by_kind": kinds, "elapsed_s": round(time.time() - t0, 1), "items": viol}
    (out_dir / "contract_sweep.json").write_text(json.dumps(report, indent=2))
    print(f"qiskit {qiskit.__version__}: {n_cfg} configs, {len(viol)} violations {kinds or '{}'}")
    print(f"report: {out_dir / 'contract_sweep.json'}")
    if viol:
        print("\nfirst few violations (candidate contract bugs):")
        for x in viol[:8]:
            print(f"  {x['kind']:<22} w{x['width']} opt{x['opt']} {x['cmap']} seed{x['seed']}: {x['detail'][:90]}")
    else:
        print("no contract violations on this corpus (expected on a released Qiskit; run vs buggy "
              "builds / current main / a larger corpus to hunt real bugs).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
