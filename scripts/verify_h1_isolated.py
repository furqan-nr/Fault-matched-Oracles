#!/usr/bin/env python3
"""H1 in isolation (PR #14603-style): detect the ElidePermutations fault the full pipeline masks.

The full preset pass manager applies a correct output even on the buggy build (so output oracles
pass — the paper's observability gap). But ElidePermutations *in isolation* behaves differently
between the fixed and buggy builds on a PermutationGate trigger. This script runs the pass alone in
each per-event venv and diffs (a) the pass's output circuit and (b) its property_set (the
virtual_permutation_layout it records) between builds. Any divergence is the H1 signal.

Secondary/retrospective deviation from the production output oracle (PROVENANCE_BACKLOG.md).

Usage (anchor venv active, repo root; H1 venvs already built):
  python scripts/verify_h1_isolated.py
  python scripts/verify_h1_isolated.py --pass ElidePermutations --trigger trig-h1-elide-permutations
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
from cart.labels.historical_runner import _venv_python, _circuit_fingerprint, _load_qpy  # noqa: E402


def _run_isolated(python_exe, *, pass_name, trigger, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(python_exe), "-m", "cart.labels.historical_worker",
           "--targeted", trigger, "--isolated-pass", pass_name,
           "--backend", "none", "--opt", "0", "--out", str(out_dir)]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    subprocess.run(cmd, cwd=str(_REPO_ROOT), env=env, check=True, capture_output=True, timeout=900)
    return json.loads((out_dir / "worker.json").read_text())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Isolated-pass differential for H1 (ElidePermutations).")
    p.add_argument("--event", default="hist-elide-permutations-mapping")
    p.add_argument("--pass", dest="pass_name", default="ElidePermutations")
    p.add_argument("--trigger", default="trig-h1-elide-permutations")
    p.add_argument("--baseline-python", default=None)
    p.add_argument("--candidate-python", default=None)
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    ev = {e.event_id: e for e in load_events()}.get(args.event)
    if ev is None:
        raise SystemExit(f"unknown event {args.event!r}")
    bpy = args.baseline_python or _venv_python(f"{ev.event_environment_id}-base")
    cpy = args.candidate_python or _venv_python(f"{ev.event_environment_id}-cand")
    if not bpy or not cpy:
        raise SystemExit(f"per-event venvs missing for {ev.event_id}; build base/cand first (see FORWARD_REGRESSION_PLAN.md).")

    print(f"# H1 isolated-pass differential: {ev.event_id}  (pass={args.pass_name}, trigger={args.trigger})")
    print(f"# baseline(good)={ev.baseline_sha[:12]}  candidate(buggy)={ev.candidate_sha[:12]}\n")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bm = _run_isolated(bpy, pass_name=args.pass_name, trigger=args.trigger, out_dir=tmp / "base")
        cm = _run_isolated(cpy, pass_name=args.pass_name, trigger=args.trigger, out_dir=tmp / "cand")
        b_ok, c_ok = bm.get("status") == "ok", cm.get("status") == "ok"
        if not b_ok and not c_ok:
            print("both builds errored running the pass in isolation — adjust the trigger/pass setup:")
            print(f"  baseline : {bm.get('error_type')}: {bm.get('error')}")
            print(f"  candidate: {cm.get('error_type')}: {cm.get('error')}")
            return 3
        if b_ok != c_ok:
            who = "candidate(buggy)" if not c_ok else "baseline(good)"
            em = cm if not c_ok else bm
            print(f"ASYMMETRIC: {who} raised {em.get('error_type')} where the other build ran clean.")
            print(f"  {who} error detail: {em.get('error_type')}: {em.get('error')}")
            print(f"\nverdict: H1 DETECTED in isolation — the buggy and fixed ElidePermutations diverge on "
                  f"the trigger ({who} errors, the other runs), a fault the full-pipeline output oracle masks.")
            out = Path(args.out) if args.out else (_REPO_ROOT / "data" / "raw" / ev.event_id /
                   f"isolated_run-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"schema": "isolated_run/v1", "event_id": ev.event_id,
                   "pass": args.pass_name, "trigger": args.trigger,
                   "asymmetric_error": {"side": who, "error_type": em.get("error_type"), "error": em.get("error")},
                   "baseline_status": bm.get("status"), "candidate_status": cm.get("status")}, indent=2))
            print(f"raw: {out}")
            return 0

        # (a) output-circuit diff
        fp_b = _circuit_fingerprint(_load_qpy(tmp / "base" / "circuit.qpy"))
        fp_c = _circuit_fingerprint(_load_qpy(tmp / "cand" / "circuit.qpy"))
        circuit_diverges = fp_b != fp_c

        # (b) property_set diff (focus on the recorded permutation/layout contract)
        ps_b, ps_c = bm.get("property_set", {}), cm.get("property_set", {})
        keys = sorted(set(ps_b) | set(ps_c))
        ps_diff = [k for k in keys if ps_b.get(k) != ps_c.get(k)]

        divergent = circuit_diverges or bool(ps_diff)
        print(f"output circuit differs between builds : {circuit_diverges}")
        print(f"property_set keys (candidate)        : {cm.get('property_set_keys')}")
        print(f"property_set fields that differ      : {ps_diff or 'none'}")
        verdict = ("H1 DETECTED in isolation (buggy ElidePermutations diverges from the fixed pass) — "
                   "invisible to the full-pipeline output oracle") if divergent else \
                  ("no divergence in isolation either — inspect property_set_keys above; the trigger may "
                   "need adjusting to the exact PR #14603 regression circuit")
        print(f"\nverdict: {verdict}")

        out = Path(args.out) if args.out else (_REPO_ROOT / "data" / "raw" / ev.event_id /
                                               f"isolated_run-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"schema": "isolated_run/v1", "event_id": ev.event_id,
                                   "pass": args.pass_name, "trigger": args.trigger,
                                   "circuit_diverges": circuit_diverges, "property_set_diff": ps_diff,
                                   "baseline_property_set": ps_b, "candidate_property_set": ps_c}, indent=2))
        print(f"raw: {out}")
        return 0 if divergent else 2


if __name__ == "__main__":
    raise SystemExit(main())
