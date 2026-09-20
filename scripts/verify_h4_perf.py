#!/usr/bin/env python3
"""Path A driver: confirm H4 (VF2PostLayout no-op, PR #14120) as a DETECTED forward-regression
performance event, in the regime where the no-op overhead is large.

The no-op overhead is significant for highly symmetric circuits mapped to LARGE coupling maps at
optimization level 3 (Qiskit issue #14867 / #14120) — a regime the <=8-qubit pilot corpus never
exercised. This script transpiles such regime units `--repeats` times in the baseline (good) and
candidate (buggy) per-event venvs, then applies the Stage-2 performance oracle.

Timing metric: defaults to WALL-CLOCK (`perf_counter`), because Windows `process_time()` has ~16 ms
resolution and a single transpile of these circuits sits near that boundary (CPU-time deltas collapse
to zeros). Wall-clock has sub-microsecond resolution; multi-run median + bootstrap CI + effect size
control the extra noise. Use `--metric cpu` to force CPU process time (keep the machine quiet).

Build the per-event venvs first (PowerShell; see FORWARD_REGRESSION_PLAN.md / SETUP_WINDOWS.md):
  environment/_builds/<env_id>-base/venv   (baseline, good)
  environment/_builds/<env_id>-cand/venv   (candidate, buggy)

Usage (repo root, anchor venv active):
  python scripts/verify_h4_perf.py
  python scripts/verify_h4_perf.py --widths 20,27,40 --repeats 9
  python scripts/verify_h4_perf.py --metric cpu
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

import yaml  # noqa: E402
from cart.events.table import load_events  # noqa: E402
from cart.labels.historical_runner import _venv_python  # noqa: E402
from cart.manifest.static_manifest import DEFAULT_BASIS  # noqa: E402
from cart.oracles.performance_stage2 import confirm_performance  # noqa: E402


def _stage2_cfg() -> dict:
    cfg = yaml.safe_load((_REPO_ROOT / "configs" / "thresholds.yaml").read_text()) or {}
    return (cfg.get("performance") or {}).get("stage2") or {}


def _fmt(x, spec="+.3f"):
    """None-safe number formatting for the per-unit line."""
    return format(x, spec) if isinstance(x, (int, float)) else "n/a"


def _run_worker(python_exe, *, family, n, backend, opt, basis, repeats, seed, out_dir) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(python_exe), "-m", "cart.labels.historical_worker",
           "--family", family, "--n", str(n), "--backend", backend, "--opt", str(opt),
           "--basis", ",".join(basis), "--seed", str(seed), "--repeats", str(repeats),
           "--out", str(out_dir)]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    subprocess.run(cmd, cwd=str(_REPO_ROOT), env=env, check=True, capture_output=True, timeout=7200)
    return json.loads((out_dir / "worker.json").read_text())


def _times(meta: dict, metric: str) -> list[float]:
    if metric == "cpu":
        return meta.get("cpu_times_s") or ([meta["cpu_time_s"]] if meta.get("cpu_time_s") is not None else [])
    return meta.get("wall_times_s") or ([meta["transpile_time_s"]] if meta.get("transpile_time_s") is not None else [])


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Stage-2 performance confirmation for H4 (VF2PostLayout no-op).")
    p.add_argument("--event", default="hist-vf2postlayout-noop")
    p.add_argument("--families", default="ghz", help="comma list; symmetric families surface the overhead")
    p.add_argument("--widths", default="16,20,27", help="comma list of widths (larger => larger coupling map)")
    p.add_argument("--backend", default="heavy_hex")
    p.add_argument("--opt", type=int, default=3)
    p.add_argument("--metric", choices=["wall", "cpu"], default="wall",
                   help="timing metric for detection (default wall; cpu is ~16ms-coarse on Windows)")
    p.add_argument("--repeats", type=int, default=None, help="override configs stage2.repeats")
    p.add_argument("--baseline-python", default=None)
    p.add_argument("--candidate-python", default=None)
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    cfg = _stage2_cfg()
    threshold = float(cfg.get("slowdown_threshold", 0.20))
    min_mag = str(cfg.get("min_effect_magnitude", "small"))
    repeats = int(args.repeats if args.repeats is not None else cfg.get("repeats", 7))
    n_boot, alpha = int(cfg.get("n_bootstrap", 2000)), float(cfg.get("alpha", 0.05))

    events = {e.event_id: e for e in load_events()}
    if args.event not in events:
        raise SystemExit(f"unknown event {args.event!r}")
    ev = events[args.event]
    bpy = args.baseline_python or _venv_python(f"{ev.event_environment_id}-base")
    cpy = args.candidate_python or _venv_python(f"{ev.event_environment_id}-cand")
    if not bpy or not cpy:
        raise SystemExit(
            f"per-event venvs missing for {ev.event_id}. Build them first (PowerShell):\n"
            f"  .\\environment\\setup\\build_qiskit_event.ps1 -Sha {ev.baseline_sha} -EventEnvId {ev.event_environment_id}-base -Force\n"
            f"  .\\environment\\setup\\build_qiskit_event.ps1 -Sha {ev.candidate_sha} -EventEnvId {ev.event_environment_id}-cand -Force\n"
            f"or pass --baseline-python/--candidate-python explicitly.")

    print(f"# Stage-2 performance confirmation: {ev.event_id}  (metric={args.metric})")
    print(f"# pre-declared (configs/thresholds.yaml): threshold={threshold}  min_effect={min_mag}  repeats={repeats}")
    print(f"# baseline(good)={ev.baseline_sha[:12]}  candidate(buggy)={ev.candidate_sha[:12]}\n")

    basis = list(DEFAULT_BASIS)
    families = [f.strip() for f in args.families.split(",") if f.strip()]
    widths = [int(w) for w in args.widths.split(",") if w.strip()]
    rows, any_detected, any_positive = [], False, False
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for fam in families:
            for n in widths:
                tag = f"{fam}-n{n}-{args.backend}-opt{args.opt}"
                try:
                    bm = _run_worker(bpy, family=fam, n=n, backend=args.backend, opt=args.opt,
                                     basis=basis, repeats=repeats, seed=args.seed, out_dir=tmp / f"{tag}-base")
                    cm = _run_worker(cpy, family=fam, n=n, backend=args.backend, opt=args.opt,
                                     basis=basis, repeats=repeats, seed=args.seed, out_dir=tmp / f"{tag}-cand")
                except subprocess.CalledProcessError as exc:
                    err = exc.stderr.decode()[-300:] if exc.stderr else str(exc)
                    print(f"[{tag}] worker failed: {err}")
                    continue
                if bm.get("status") != "ok" or cm.get("status") != "ok":
                    print(f"[{tag}] transpile error (baseline={bm.get('status')}, candidate={cm.get('status')})")
                    continue
                bt, ct = _times(bm, args.metric), _times(cm, args.metric)
                res = confirm_performance(bt, ct, slowdown_threshold=threshold, min_magnitude=min_mag,
                                          n_boot=n_boot, alpha=alpha, seed=args.seed)
                any_detected = any_detected or res.suspected_regression
                if isinstance(res.slowdown_ratio, (int, float)) and res.slowdown_ratio > 0:
                    any_positive = True
                rows.append({"unit": tag, "metric": args.metric, "result": res.__dict__,
                             "baseline_qiskit": bm.get("qiskit_version"), "candidate_qiskit": cm.get("qiskit_version"),
                             "baseline_times_s": bt, "candidate_times_s": ct})
                flag = "DETECTED" if res.suspected_regression else "—"
                print(f"[{tag:26}] n={res.n_baseline}/{res.n_candidate} "
                      f"base={_fmt(res.median_baseline_s, '.4f')}s cand={_fmt(res.median_candidate_s, '.4f')}s "
                      f"slowdown={_fmt(res.slowdown_ratio)} CI=[{_fmt(res.ratio_ci_lo)},{_fmt(res.ratio_ci_hi)}] "
                      f"d={_fmt(res.cliffs_delta, '+.2f')}({res.cliffs_magnitude}) -> {flag}")

    out = Path(args.out) if args.out else (_REPO_ROOT / "data" / "raw" / ev.event_id /
                                           f"perf_stage2-{args.metric}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"schema": "perf_stage2/v1", "event_id": ev.event_id, "metric": args.metric,
                               "pre_declared": {"slowdown_threshold": threshold, "min_effect_magnitude": min_mag,
                                                "repeats": repeats, "n_bootstrap": n_boot, "alpha": alpha},
                               "rows": rows}, indent=2))
    if any_detected:
        verdict = "H4 CONFIRMED as a detected forward-regression performance event"
    elif any_positive:
        verdict = "not confirmed: overhead is positive but below threshold — try larger --widths (e.g. 27,40,54) or --repeats 11"
    else:
        verdict = "not confirmed: no measurable overhead at this regime — try larger --widths, or report as below detection at commodity scale"
    print(f"\nverdict: {verdict}")
    print(f"raw: {out}")
    return 0 if any_detected else 2


if __name__ == "__main__":
    raise SystemExit(main())
