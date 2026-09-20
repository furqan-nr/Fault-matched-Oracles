#!/usr/bin/env python3
"""Path B driver: detect H1 (ElidePermutations, PR #14603) via the property/layout oracle.

The H1 fault corrupts the `virtual_permutation_layout` contract while leaving the output unitary
correct, so the production output oracle reports EQUIVALENT (the paper's observability gap). This
script runs the H1 targeted trigger through the full preset pass manager in the baseline (good) and
candidate (buggy) per-event venvs with `--capture-layout`, then compares the recorded layout
contract. A DIVERGENCE is the H1 signal an output-only oracle cannot see.

Secondary/retrospective deviation from the production output oracle (PROVENANCE_BACKLOG.md); never
fold it into the Primary CI claim.

Usage (repo root, anchor venv active):
  python scripts/verify_h1_property.py
  python scripts/verify_h1_property.py --backends none,line --opt 3
  python scripts/verify_h1_property.py --baseline-python <path> --candidate-python <path>
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

from cart.events.table import load_events  # noqa: E402
from cart.labels.historical_runner import _venv_python  # noqa: E402
from cart.manifest.static_manifest import DEFAULT_BASIS  # noqa: E402
from cart.manifest.targeted import units_for_fault  # noqa: E402
from cart.oracles.property_layout import compare_layout_props  # noqa: E402


def _worker_layout(python_exe, *, targeted_id, backend, opt, basis, seed, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(python_exe), "-m", "cart.labels.historical_worker",
           "--targeted", targeted_id, "--backend", backend, "--opt", str(opt),
           "--basis", ",".join(basis), "--seed", str(seed), "--capture-layout", "--out", str(out_dir)]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    subprocess.run(cmd, cwd=str(_REPO_ROOT), env=env, check=True, capture_output=True, timeout=1200)
    return json.loads((out_dir / "worker.json").read_text())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Property/layout oracle for H1 (ElidePermutations).")
    p.add_argument("--event", default="hist-elide-permutations-mapping")
    p.add_argument("--backends", default="none,line")
    p.add_argument("--opt", type=int, default=3)
    p.add_argument("--baseline-python", default=None)
    p.add_argument("--candidate-python", default=None)
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    events = {e.event_id: e for e in load_events()}
    if args.event not in events:
        raise SystemExit(f"unknown event {args.event!r}")
    ev = events[args.event]
    bpy = args.baseline_python or _venv_python(f"{ev.event_environment_id}-base")
    cpy = args.candidate_python or _venv_python(f"{ev.event_environment_id}-cand")
    if not bpy or not cpy:
        raise SystemExit(
            f"per-event venvs missing for {ev.event_id}. Build them first (PowerShell):\n"
            f"  .\\environment\\setup\\build_qiskit_event.ps1 -Sha {ev.baseline_sha} -EventEnvId {ev.event_environment_id}-base\n"
            f"  .\\environment\\setup\\build_qiskit_event.ps1 -Sha {ev.candidate_sha} -EventEnvId {ev.event_environment_id}-cand\n"
            f"or pass --baseline-python/--candidate-python.")

    tunits = units_for_fault(ev.fault_id)
    if not tunits:
        raise SystemExit(f"no targeted trigger units registered for fault {ev.fault_id!r}")
    basis = list(DEFAULT_BASIS)
    backends = [b.strip() for b in args.backends.split(",") if b.strip()]

    print(f"# Property/layout oracle (Secondary retrospective): {ev.event_id}")
    print(f"# baseline(good)={ev.baseline_sha[:12]}  candidate(buggy)={ev.candidate_sha[:12]}\n")

    rows, any_divergent = [], False
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for u in tunits:
            for backend in backends:
                tag = f"{u.test_id}-{backend}-opt{args.opt}"
                bm = _worker_layout(bpy, targeted_id=u.test_id, backend=backend, opt=args.opt,
                                    basis=basis, seed=args.seed, out_dir=tmp / f"{tag}-base")
                cm = _worker_layout(cpy, targeted_id=u.test_id, backend=backend, opt=args.opt,
                                    basis=basis, seed=args.seed, out_dir=tmp / f"{tag}-cand")
                if bm.get("status") != "ok" or cm.get("status") != "ok":
                    print(f"[{tag}] transpile error (baseline={bm.get('status')}, candidate={cm.get('status')})")
                    continue
                res = compare_layout_props(bm.get("layout_props", {}), cm.get("layout_props", {}))
                any_divergent = any_divergent or (res.equivalent is False)
                rows.append({"unit": tag, "equivalent": res.equivalent,
                             "divergent_fields": res.divergent_fields, "details": res.details})
                if res.equivalent is False:
                    verdict = f"DIVERGENT on {res.divergent_fields}  <- H1 detected by property oracle"
                elif res.equivalent is True:
                    verdict = "identical contract (no divergence)"
                else:
                    verdict = f"no contract captured ({res.details.get('reason')})"
                print(f"[{tag:32}] {verdict}")

    out = Path(args.out) if args.out else (_REPO_ROOT / "data" / "raw" / ev.event_id /
                                           f"property_run-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"schema": "property_run/v1", "event_id": ev.event_id,
                               "oracle": "property_layout", "track": "secondary_retrospective", "rows": rows}, indent=2))
    print(f"\nverdict: {'H1 property-channel divergence DETECTED (output oracle cannot see it)' if any_divergent else 'no divergence captured — confirm virtual_permutation_layout/routing_permutation is exposed on this build'}")
    print(f"raw: {out}")
    return 0 if any_divergent else 2


if __name__ == "__main__":
    raise SystemExit(main())
