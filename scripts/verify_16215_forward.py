#!/usr/bin/env python3
"""fwd-pr16215 forward-pair verification — the global-phase output-invisible channel.

PR #16215 fixes a transpiler global-phase regression: the buggy build (introducing commit `f2f85a94`)
mis-tracks the circuit's global phase, while the compiled *map* stays correct modulo global phase, so a
black-box output-equivalence oracle is BLIND. This script runs the QFT global-phase trigger through the
transpiler in the baseline (last-good) and candidate (introducing) venvs and asserts the acceptance
criterion for promotion:

    output-equivalence oracle stays BLIND (compiled map ≡ original modulo global phase in BOTH builds)
    AND the tracked global phase DIFFERS between baseline and candidate.

Both #16215 revisions are already built at the parent (Paper 1 bisection, both 2.5.0.dev0 — the same era
as the oracle family), so no new build is needed. Same CLI shape as `verify_h1_isolated.py` so it runs on
the parent by pointing at those venvs' pythons:

  python scripts/verify_16215_forward.py \
      --baseline-python  environment/_builds/_bisect-a241dd19a81e/venv/Scripts/python.exe \
      --candidate-python environment/_builds/_bisect-f2f85a9476e3/venv/Scripts/python.exe

Trigger defaults to the QFT family (the source_validation_targets.csv row for 16215); pass --targets to
read family/n/backend/opt from that CSV, or override with --n/--backend/--opt. Only on a POSITIVE result
(exit 0) is the event promoted into the ledger (PROVENANCE_BACKLOG.md step 4).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from cart.labels.historical_runner import _venv_python, _load_qpy  # noqa: E402


def _row_from_csv(targets: Path, pr: str) -> dict | None:
    if not targets or not Path(targets).exists():
        return None
    with open(targets, newline="") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("pr", "")).strip() == str(pr):
                return row
    return None


def _run_worker(python_exe: str, *, family: str, n: int, backend: str, opt: int,
                basis: str, seed: int, out_dir: Path) -> dict:
    """Transpile the trigger inside one from-source venv; returns worker.json (writes circuit.qpy)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(python_exe), "-m", "cart.labels.historical_worker",
           "--family", family, "--n", str(n), "--backend", backend, "--opt", str(opt),
           "--basis", basis, "--seed", str(seed), "--out", str(out_dir)]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    subprocess.run(cmd, cwd=str(_REPO_ROOT), env=env, check=True, capture_output=True, timeout=1200)
    return json.loads((out_dir / "worker.json").read_text())


def _measure(original, transpiled) -> dict:
    """Global-phase + output-equivalence measurement of one transpilation (anchor venv)."""
    from cart.oracles.global_phase import check_global_phase, _wrap  # noqa
    from cart.oracles.semantic import check_semantic
    gp = check_global_phase(original, transpiled)
    sem = check_semantic(original, transpiled)
    return {
        "tracked_global_phase": float(getattr(transpiled, "global_phase", 0.0)),
        "gp_strength": gp.strength,
        "gp_equivalent": gp.equivalent,                      # True=phase preserved, False=phase fault, None=n/a
        "gp_delta_rad": None if gp.global_phase_delta is None else round(float(gp.global_phase_delta), 9),
        "output_oracle_equivalent": sem.equivalent,          # True => output oracle BLIND to any phase issue
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="fwd-pr16215 global-phase forward-pair verifier.")
    p.add_argument("--event", default="fwd-pr16215")
    p.add_argument("--pr", default="16215")
    p.add_argument("--baseline-python", default=None, help="last-good (a241dd19) venv python")
    p.add_argument("--candidate-python", default=None, help="introducing (f2f85a94) venv python")
    p.add_argument("--targets", default=str(_REPO_ROOT / "data" / "mining_validation" / "source_validation_targets.csv"),
                   help="optional CSV; the 16215 row overrides family/n/backend/opt")
    p.add_argument("--family", default="qft")
    p.add_argument("--n", type=int, default=5)               # exact tier (<=12): true operator phase
    p.add_argument("--backend", default="line")
    p.add_argument("--opt", type=int, default=1)
    p.add_argument("--basis", default="cx,rz,sx,x")
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument("--out", default=str(_REPO_ROOT / "results" / "fwd-pr16215"))
    args = p.parse_args(argv)

    # 16215 trigger spec: CLI defaults, overridable by the CSV row if present.
    row = _row_from_csv(Path(args.targets), args.pr)
    family = (row or {}).get("family") or args.family
    n = int((row or {}).get("n") or args.n)
    backend = (row or {}).get("backend") or args.backend
    opt = int((row or {}).get("opt") or args.opt)

    bpy = args.baseline_python or _venv_python("_bisect-a241dd19a81e") or _venv_python(f"{args.event}-base")
    cpy = args.candidate_python or _venv_python("_bisect-f2f85a9476e3") or _venv_python(f"{args.event}-cand")
    if not bpy or not cpy:
        raise SystemExit("baseline/candidate venvs not found; pass --baseline-python / --candidate-python "
                         "(both #16215 revisions are prebuilt at the parent, see FORWARD_PAIR_RESULTS.md).")

    print(f"# fwd-pr16215 global-phase forward-pair verification")
    print(f"# trigger: {family} n={n} backend={backend} opt={opt} basis={args.basis}")
    print(f"# baseline(last-good a241dd19) vs candidate(introducing f2f85a94)\n")

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bw = _run_worker(bpy, family=family, n=n, backend=backend, opt=opt, basis=args.basis,
                         seed=args.seed, out_dir=tmp / "base")
        cw = _run_worker(cpy, family=family, n=n, backend=backend, opt=opt, basis=args.basis,
                         seed=args.seed, out_dir=tmp / "cand")

        rec: dict = {"schema": "global_phase_forward/v1", "event_id": args.event, "pr": args.pr,
                     "trigger": {"family": family, "n": n, "backend": backend, "opt": opt,
                                 "basis": args.basis, "seed": args.seed},
                     "qiskit_version": {"baseline": bw.get("qiskit_version"), "candidate": cw.get("qiskit_version")},
                     "worker_status": {"baseline": bw.get("status"), "candidate": cw.get("status")}}

        # Either build failing to transpile the trigger is INCONCLUSIVE (e.g. era mismatch), never refuted.
        if bw.get("status") != "ok" or cw.get("status") != "ok":
            rec["verdict"] = "inconclusive"
            rec["reason"] = "a build failed to transpile the trigger (see worker error); not a refutation"
            rec["errors"] = {"baseline": bw.get("error"), "candidate": cw.get("error")}
            _emit(out_root, rec)
            print("INCONCLUSIVE — a build errored on the trigger (not a refutation):")
            print(f"  baseline : {bw.get('error_type')}: {bw.get('error')}")
            print(f"  candidate: {cw.get('error_type')}: {cw.get('error')}")
            return 3

        from cart.manifest.circuits import build
        from cart.oracles.global_phase import _wrap
        original = build(family, n, seed=args.seed, measured=False)
        t_base = _load_qpy(tmp / "base" / "circuit.qpy")
        t_cand = _load_qpy(tmp / "cand" / "circuit.qpy")
        m_base, m_cand = _measure(original, t_base), _measure(original, t_cand)
        rec["baseline"], rec["candidate"] = m_base, m_cand

        # Acceptance: output oracle blind on the candidate (buggy) build, and the tracked phase differs.
        output_oracle_blind = (m_cand["output_oracle_equivalent"] is True)
        db, dc = m_base["gp_delta_rad"], m_cand["gp_delta_rad"]
        phase_differs = False
        if db is not None and dc is not None:
            phase_differs = abs(_wrap(db - dc)) > 1e-6
        phase_differs = phase_differs or (m_base["gp_equivalent"] != m_cand["gp_equivalent"]) \
            or (abs(_wrap(m_base["tracked_global_phase"] - m_cand["tracked_global_phase"])) > 1e-6)

        fault_detected = bool(output_oracle_blind and phase_differs)
        rec["output_oracle_blind"] = output_oracle_blind
        rec["phase_differs"] = bool(phase_differs)
        rec["fault_detected"] = fault_detected
        if fault_detected:
            rec["verdict"] = "positive"
            rec["note"] = ("forward global-phase regression reproduced: output oracle blind while the "
                           "tracked global phase diverges between last-good and introducing builds — promotable")
        elif not output_oracle_blind:
            rec["verdict"] = "inconclusive"
            rec["note"] = ("outputs differ by more than a global phase (output oracle not blind) — this is a "
                           "semantic difference, not the global-phase channel; check trigger/n/opt")
        else:
            rec["verdict"] = "negative_here"
            rec["note"] = ("output blind but no phase divergence on this trigger; try the CSV's exact "
                           "n/opt/backend before concluding")
        _emit(out_root, rec)

        print(f"baseline : tracked_gp={m_base['tracked_global_phase']:.6f}  gp_delta={db}  "
              f"gp_equiv={m_base['gp_equivalent']}  output_equiv={m_base['output_oracle_equivalent']}")
        print(f"candidate: tracked_gp={m_cand['tracked_global_phase']:.6f}  gp_delta={dc}  "
              f"gp_equiv={m_cand['gp_equivalent']}  output_equiv={m_cand['output_oracle_equivalent']}")
        print(f"\noutput_oracle_blind={output_oracle_blind}  phase_differs={phase_differs}  "
              f"=> fault_detected={fault_detected}")
        print(f"verdict: {rec['verdict']} — {rec['note']}")
        return 0 if fault_detected else (2 if output_oracle_blind else 3)


def _emit(out_root: Path, rec: dict) -> None:
    out = out_root / f"global_phase_forward-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(rec, indent=2, default=str))
    print(f"raw: {out}")


if __name__ == "__main__":
    raise SystemExit(main())
