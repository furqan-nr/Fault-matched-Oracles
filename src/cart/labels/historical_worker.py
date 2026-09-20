"""Per-event worker — runs INSIDE a per-event from-source venv (its own Qiskit revision).

Transpiles one test unit with that venv's Qiskit and writes the output circuit (QPY) + timing,
or the natural exception if transpilation fails. Invoked as a subprocess by historical_runner with
PYTHONPATH=src so `cart.manifest.*` is importable; it imports only Qiskit + numpy-backed helpers
(no yaml/pandas), so it runs in the lean per-event venv.

Usage:
  python -m cart.labels.historical_worker --family qft --n 8 --backend line \
      --opt 1 --basis cx,rz,sx,x --seed 1234 --out /path/out
  # multi-run timing (Stage-2 performance) + layout capture (property oracle):
  python -m cart.labels.historical_worker --targeted trig-h1-elide-permutations --backend none \
      --opt 3 --capture-layout --out /path/out
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from pathlib import Path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="cart.labels.historical_worker")
    p.add_argument("--family", default=None)            # generic circuit family
    p.add_argument("--targeted", default=None)          # targeted-trigger unit id (alternative)
    p.add_argument("--n", type=int, default=0)
    p.add_argument("--backend", required=True)          # "none" => no coupling map
    p.add_argument("--opt", type=int, required=True)
    p.add_argument("--basis", default="cx,rz,sx,x")
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument("--repeats", type=int, default=1,
                   help="transpile this many times; records cpu_times_s for Stage-2 performance")
    p.add_argument("--capture-layout", action="store_true",
                   help="record the transpiled circuit's layout/permutation contract (property oracle)")
    p.add_argument("--isolated-pass", default=None,
                   help="run ONLY this pass (e.g. ElidePermutations) and dump its output + property_set")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    basis = args.basis.split(",")

    import qiskit
    from qiskit.transpiler import generate_preset_pass_manager
    from cart.manifest.backends import coupling_map_for

    meta = {"qiskit_version": qiskit.__version__, "family": args.family,
            "targeted": args.targeted, "backend": args.backend, "opt": args.opt,
            "basis": basis, "seed": args.seed}

    if args.targeted:
        from cart.manifest.targeted import build_targeted
        circ = build_targeted(args.targeted)
    else:
        from cart.manifest.circuits import build
        circ = build(args.family, args.n, seed=args.seed, measured=False)

    if args.isolated_pass:
        # Run ONE pass in isolation (the PR-#14603-style canonical reproduction for H1): the
        # full preset pipeline masks the fault, but the pass alone behaves differently between the
        # fixed and buggy builds. Dump its output circuit + property_set for a build-vs-build diff.
        from qiskit.transpiler import PassManager
        from qiskit.transpiler import passes as _passes
        try:
            pm = PassManager([getattr(_passes, args.isolated_pass)()])
            tqc = pm.run(circ)
            from cart.oracles.property_layout import _to_jsonable
            meta["isolated_pass"] = args.isolated_pass
            meta["property_set_keys"] = sorted(pm.property_set.keys())
            meta["property_set"] = {k: _to_jsonable(pm.property_set[k]) for k in pm.property_set.keys()}
            from qiskit import qpy
            with open(out / "circuit.qpy", "wb") as fh:
                qpy.dump(tqc, fh)
            meta["status"] = "ok"
        except Exception as exc:
            meta["status"] = "error"; meta["error_type"] = type(exc).__name__; meta["error"] = str(exc)[:500]
        (out / "worker.json").write_text(json.dumps(meta, indent=2, default=str))
        return 0

    cmap = None if args.backend == "none" else coupling_map_for(args.backend, circ.num_qubits)
    repeats = max(1, args.repeats)
    try:
        cpu_times: list[float] = []
        wall_times: list[float] = []
        tqc = None
        for _ in range(repeats):
            # Fresh pass manager each run, mirroring a real CI invocation; only pm.run is timed.
            pm = generate_preset_pass_manager(optimization_level=args.opt, coupling_map=cmap,
                                              basis_gates=basis, seed_transpiler=args.seed)
            c0 = time.process_time()   # CPU process time — stable cost-calibration metric
            t0 = time.perf_counter()   # wall-clock — secondary reference
            tqc = pm.run(circ)
            cpu_times.append(time.process_time() - c0)
            wall_times.append(time.perf_counter() - t0)
        meta["transpile_time_s"] = wall_times[-1]
        meta["cpu_time_s"] = cpu_times[-1]
        if repeats > 1:
            meta["cpu_times_s"] = cpu_times    # multi-run timings for Stage-2 performance
            meta["wall_times_s"] = wall_times
        from qiskit import qpy
        with open(out / "circuit.qpy", "wb") as fh:
            qpy.dump(tqc, fh)
        if args.capture_layout:                # layout/permutation contract (property oracle)
            from cart.oracles.property_layout import extract_layout_props
            meta["layout_props"] = extract_layout_props(tqc)
        meta["status"] = "ok"
    except Exception as exc:  # natural transpilation failure (functional fault)
        meta["status"] = "error"
        meta["error_type"] = type(exc).__name__
        meta["error"] = str(exc)[:500]
        meta["traceback"] = traceback.format_exc()[-1500:]

    (out / "worker.json").write_text(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
