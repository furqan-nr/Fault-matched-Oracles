#!/usr/bin/env python3
"""P3 — Source-validate mining classifications from a built-from-source fix boundary.

For each PR in a stratified sample, this builds the FIX commit (good) and its PARENT (buggy) from
source via the existing `build_qiskit_event` recipe, runs the trigger through BOTH:

  * the black-box OUTPUT oracle (semantic, layout+global-phase-aware) — should it stay BLIND
    (i.e. PASS the buggy build) for an output-invisible fix?  and
  * the channel-matched PROPERTY oracle (contract-metadata / determinism / global-phase) — does it
    CATCH the fault the output oracle misses?

A row is "invisible CONFIRMED from source" when output_oracle_blind AND property_oracle_detects.
This upgrades the label from "coded from PR text" to "verified by execution", exactly as done for H1.

Input CSV (data/mining_validation/source_validation_targets.csv), one row per PR:
  pr,channel,fix_sha,parent_sha,trigger,family,n,backend,opt,isolated_pass
    channel      contract_metadata | determinism | global_phase
    fix_sha      merge/fix commit (the GOOD build)
    parent_sha   fix_sha^ (the BUGGY build); leave blank to use "<fix_sha>^"
    trigger      targeted-unit id (optional); if blank, uses family/n
    isolated_pass  pass name, for contract-metadata via isolated-pass differential (optional)

Usage:
  python scripts/source_validate_mining.py \
      --targets data/mining_validation/source_validation_targets.csv \
      --out results/source_validation

Add --only 14603,16215 to validate a subset; --dry-run to print the build plan only.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))
IS_WIN = os.name == "nt"


def build_event(sha: str, eid: str) -> Path | None:
    venv = _REPO_ROOT / "environment" / "_builds" / eid / "venv"
    py = venv / ("Scripts/python.exe" if IS_WIN else "bin/python")
    if py.exists():
        return py
    if IS_WIN:
        cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File",
               str(_REPO_ROOT / "environment/setup/build_qiskit_event.ps1"),
               "-Sha", sha, "-EventEnvId", eid]
    else:
        cmd = ["bash", str(_REPO_ROOT / "environment/setup/build_qiskit_event.sh"), sha, eid]
    print(f">> building {eid} @ {sha[:12]} ...")
    subprocess.run(cmd, cwd=str(_REPO_ROOT))
    return py if py.exists() else None


def worker(py: Path, out_dir: Path, row: dict, *, isolated: str | None = None, repeats: int = 1) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(py), "-m", "cart.labels.historical_worker",
           "--backend", row["backend"], "--opt", row["opt"],
           "--seed", "1234", "--repeats", str(repeats),
           "--capture-layout", "--out", str(out_dir)]
    if row.get("trigger"):
        cmd += ["--targeted", row["trigger"]]
    else:
        cmd += ["--family", row["family"], "--n", row["n"]]
    if isolated:
        cmd += ["--isolated-pass", isolated]
    env = dict(os.environ); env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    subprocess.run(cmd, cwd=str(_REPO_ROOT), env=env, check=True,
                   capture_output=True, timeout=1200)
    return json.loads((out_dir / "worker.json").read_text())


def load_qpy(path: Path):
    from qiskit import qpy
    with open(path, "rb") as fh:
        return qpy.load(fh)[0]


def validate_pr(row: dict, out_root: Path) -> dict:
    from cart.oracles.property_layout import compare_layout_props
    from cart.oracles.semantic import check_semantic
    from cart.manifest.backends import coupling_map_for
    from cart.labels.historical_runner import _circuit_fingerprint
    from cart.manifest.static_manifest import DEFAULT_BASIS

    pr, ch = row["pr"], row["channel"]
    fix, parent = row["fix_sha"], (row.get("parent_sha") or f"{row['fix_sha']}^")
    rec: dict = {"pr": pr, "channel": ch, "fix_sha": fix, "parent_sha": parent}

    bpy = build_event(fix, f"sv-{pr}-fix")
    cpy = build_event(parent, f"sv-{pr}-bug")
    if not bpy or not cpy:
        rec["result"] = "build_failed"
        return rec

    wd = out_root / f"pr{pr}"
    isolated = row.get("isolated_pass") or None

    # Build the ORIGINAL trigger in the anchor env (what an output oracle checks the transpile against)
    if row.get("trigger"):
        from cart.manifest.targeted import build_targeted
        original = build_targeted(row["trigger"])
    else:
        from cart.manifest.circuits import build as build_circ
        original = build_circ(row["family"], int(row["n"]), seed=1234, measured=False)
    cmap = None if row["backend"] == "none" else coupling_map_for(row["backend"], original.num_qubits)

    # ---- OUTPUT ORACLE BLINDNESS: is the buggy transpile output-equivalent to the ORIGINAL? ----
    # (blind = an output-equivalence oracle sees nothing wrong on the buggy build)
    cfull = worker(cpy, wd / "bug_full", row, isolated=None)
    if cfull.get("status") == "error":
        rec["output_oracle_equivalent"] = "error"
        rec["output_oracle_blind"] = False              # a crash IS visible
    else:
        buggy = load_qpy(wd / "bug_full" / "circuit.qpy")
        sem = check_semantic(original, buggy, coupling_map=cmap, basis_gates=list(DEFAULT_BASIS))
        rec["output_oracle_equivalent"] = sem.equivalent
        rec["output_oracle_strength"] = sem.strength
        rec["output_oracle_blind"] = (sem.equivalent is True)   # None (can't assess) is NOT "blind"

    # ---- CHANNEL-MATCHED PROPERTY ORACLE: does it CATCH the fault? ----
    if ch == "determinism":
        c1 = worker(cpy, wd / "bug_r1", row); c2 = worker(cpy, wd / "bug_r2", row)
        if "error" in (c1.get("status"), c2.get("status")):
            rec["property_oracle_detects"] = None
        else:
            o1, o2 = load_qpy(wd / "bug_r1" / "circuit.qpy"), load_qpy(wd / "bug_r2" / "circuit.qpy")
            rec["property_oracle_detects"] = (_circuit_fingerprint(o1) != _circuit_fingerprint(o2))
    elif ch == "contract_metadata":
        bw = worker(bpy, wd / "fix", row, isolated=isolated)
        cw = worker(cpy, wd / "bug", row, isolated=isolated)
        b_ok, c_ok = bw.get("status") == "ok", cw.get("status") == "ok"
        if b_ok != c_ok:                                  # asymmetric error = the H1 signal
            rec["divergence"] = "asymmetric_error"
            rec["error_side"] = "bug" if not c_ok else "fix"
            rec["property_oracle_detects"] = True
        elif not b_ok and not c_ok:
            rec["property_oracle_detects"] = None
            rec["detail"] = f"both isolated runs errored ({bw.get('error_type')}/{cw.get('error_type')})"
        else:                                             # diff property_set over ALL keys + fingerprint
            ps_b, ps_c = bw.get("property_set", {}), cw.get("property_set", {})
            ps_diff = [k for k in sorted(set(ps_b) | set(ps_c)) if ps_b.get(k) != ps_c.get(k)]
            fp_div = _circuit_fingerprint(load_qpy(wd/"fix"/"circuit.qpy")) != _circuit_fingerprint(load_qpy(wd/"bug"/"circuit.qpy"))
            rec["property_divergent_fields"] = ps_diff
            rec["property_oracle_detects"] = bool(ps_diff) or fp_div
    elif ch == "global_phase":
        worker(bpy, wd / "fix", row, isolated=isolated); worker(cpy, wd / "bug", row, isolated=isolated)
        gb = float(load_qpy(wd / "fix" / "circuit.qpy").global_phase)
        gc = float(load_qpy(wd / "bug" / "circuit.qpy").global_phase)
        d = abs((gc - gb + math.pi) % (2 * math.pi) - math.pi)
        rec["global_phase_delta"] = d
        rec["property_oracle_detects"] = (d > 1e-9)
    else:
        rec.update(result=f"unknown_channel:{ch}")
        return rec

    rec["invisible_confirmed"] = (rec.get("output_oracle_blind") is True) and (rec.get("property_oracle_detects") is True)
    rec["result"] = "ok"
    return rec


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Source-validate mining classifications (P3).")
    p.add_argument("--targets", default="data/mining_validation/source_validation_targets.csv")
    p.add_argument("--out", default="results/source_validation")
    p.add_argument("--only", default=None, help="comma-separated PR numbers to run")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    rows = list(csv.DictReader(open(_REPO_ROOT / args.targets)))
    if args.only:
        keep = set(args.only.split(","))
        rows = [r for r in rows if r["pr"] in keep]
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_root = _REPO_ROOT / args.out / ts
    out_root.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        for r in rows:
            print(f"  PR {r['pr']:>6} [{r['channel']:<17}] fix={r['fix_sha'][:12]} "
                  f"parent={(r.get('parent_sha') or r['fix_sha']+'^')[:14]} "
                  f"trigger={r.get('trigger') or (r['family']+'/'+r['n'])}")
        print(f"\n{len(rows)} PRs planned. Remove --dry-run to build & validate.")
        return 0

    results = []
    for r in rows:
        print(f"\n=== PR {r['pr']} ({r['channel']}) ===")
        try:
            results.append(validate_pr(r, out_root))
        except Exception as exc:  # keep going; record the failure
            results.append({"pr": r["pr"], "channel": r["channel"],
                            "result": "exception", "error": f"{type(exc).__name__}: {exc}"[:300]})

    (out_root / "source_validation.json").write_text(json.dumps(results, indent=2, default=str))
    # tidy summary CSV
    cols = ["pr", "channel", "result", "output_oracle_blind", "property_oracle_detects",
            "invisible_confirmed", "property_divergent_fields", "global_phase_delta"]
    with open(out_root / "source_validation_summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader()
        for r in results:
            w.writerow(r)

    conf = sum(1 for r in results if r.get("invisible_confirmed"))
    print("\n================ SUMMARY ================")
    for r in results:
        print(f"  PR {r['pr']:>6} [{r['channel']:<17}] {r['result']:<14} "
              f"blind={r.get('output_oracle_blind')} detect={r.get('property_oracle_detects')} "
              f"=> invisible_confirmed={r.get('invisible_confirmed')}")
    print(f"\n{conf}/{len(results)} classifications CONFIRMED output-invisible from source.")
    print(f"artifacts: {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
