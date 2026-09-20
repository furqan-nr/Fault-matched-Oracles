#!/usr/bin/env python3
"""N1 retro-detection across Qiskit RELEASES — build-free (pip wheels, no Rust compile).

For each mined output-invisible fix that straddles a release boundary, install the PRE-fix and POST-fix
Qiskit releases into throwaway pip venvs, transpile the trigger in each, then check with the study's
oracles that the fix changed the INVISIBLE channel while the OUTPUT oracle stays blind:

  global_phase       check_global_phase(pre_out, post_out).equivalent is False  (phase changed)
                     AND check_semantic(pre_out, post_out).equivalent is True   (output-blind)
  contract_metadata  layout metadata (initial/final_index_layout, routing_permutation) differs pre->post
                     AND check_semantic blind
  determinism        the PRE release is non-deterministic on the trigger (metadata varies over repeats);
                     the POST release is deterministic

A retro_detected=True row = the differ/oracle catches, from released wheels alone, a real fix that an
output-equivalence oracle could not see. Caveat: cross-RELEASE (not adjacent-commit) diffs carry other
changes too; keep triggers specific to the fixed pass. For fixes whose parent is unreleased, use the
from-source build path (source_validate_mining.py) instead.

For pass-specific faults whose bug is masked by the full preset pipeline and only manifests when the
fixed pass runs in isolation (e.g. trig-gp14956-cc-2pi / CommutativeCancellation — the same reason
source_validate_mining.py threads an isolated-pass differential), set the target row's `isolated_pass`
column; worker() forwards it as historical_worker.py's --isolated-pass flag.

NOTE (2026-07-04, see data/mining_validation/RETRO_DETECT_NOTES.md): for every fix in the current mined
output-invisible sample, the buggy parent commit and its fix land inside the SAME Qiskit release (Qiskit
ships fixes fast, within one release cycle) — the buggy state itself was never shipped independently. Two
release wheels therefore cannot bracket the bug for any of these six PRs regardless of isolated-pass
wiring: this is a structural inapplicability of the build-free approach for this sample, not a mechanism
failure, and retro_detected=False here should be read that way. This path stays useful for any future
candidate whose buggy parent DID ship in an earlier release.

  PYTHONPATH=src python scripts/retro_detect_release.py --targets data/mining_validation/retro_detect_targets.csv
  ... --only 16201,14956    ... --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
IS_WIN = os.name == "nt"


def ensure_pip_venv(version: str) -> Path | None:
    d = _ROOT / "environment" / "_builds" / f"pip-qiskit-{version}" / "venv"
    py = d / ("Scripts/python.exe" if IS_WIN else "bin/python")
    if py.exists():
        return py
    print(f">> creating venv + pip install qiskit=={version} (build-free wheel) ...")
    subprocess.run([sys.executable, "-m", "venv", str(d)], check=True)
    r = subprocess.run([str(py), "-m", "pip", "install", "-q", f"qiskit=={version}", "numpy"])
    return py if (r.returncode == 0 and py.exists()) else None


def worker(py: Path, out: Path, row: dict, repeats: int = 1, *, isolated: str | None = None):
    out.mkdir(parents=True, exist_ok=True)
    cmd = [str(py), "-m", "cart.labels.historical_worker",
           "--backend", row["backend"], "--opt", row["opt"], "--seed", "1234",
           "--repeats", str(repeats), "--capture-layout", "--out", str(out)]
    if row.get("trigger"):
        cmd += ["--targeted", row["trigger"]]
    else:
        cmd += ["--family", row["family"], "--n", row["n"]]
    if isolated:
        cmd += ["--isolated-pass", isolated]
    env = dict(os.environ); env["PYTHONPATH"] = str(_ROOT / "src")
    subprocess.run(cmd, cwd=str(_ROOT), env=env, check=True, capture_output=True, timeout=900)
    return json.loads((out / "worker.json").read_text())


def load_qpy(p: Path):
    from qiskit import qpy
    with open(p, "rb") as fh:
        return qpy.load(fh)[0]


def retro_one(row: dict, out_root: Path) -> dict:
    from cart.oracles.global_phase import check_global_phase
    from cart.oracles.semantic import check_semantic
    from cart.oracles.property_layout import compare_layout_props
    from cart.labels.historical_runner import _circuit_fingerprint

    pr, ch = row["pr"], row["channel"]
    rec = {"pr": pr, "channel": ch, "pre": row["pre_version"], "post": row["post_version"]}
    pre_py = ensure_pip_venv(row["pre_version"])
    post_py = ensure_pip_venv(row["post_version"])
    if not pre_py or not post_py:
        rec["result"] = "venv_install_failed"; return rec
    wd = out_root / f"pr{pr}"
    isolated = row.get("isolated_pass") or None

    if ch == "determinism":
        w1 = worker(pre_py, wd / "pre1", row); w2 = worker(pre_py, wd / "pre2", row)
        po = worker(post_py, wd / "post1", row); po2 = worker(post_py, wd / "post2", row)
        try:
            pre_det = _circuit_fingerprint(load_qpy(wd/"pre1"/"circuit.qpy")) == _circuit_fingerprint(load_qpy(wd/"pre2"/"circuit.qpy"))
            post_det = _circuit_fingerprint(load_qpy(wd/"post1"/"circuit.qpy")) == _circuit_fingerprint(load_qpy(wd/"post2"/"circuit.qpy"))
            rec["pre_deterministic"], rec["post_deterministic"] = pre_det, post_det
            rec["retro_detected"] = (not pre_det) and post_det
        except Exception as e:
            rec["result"] = f"error:{type(e).__name__}"; return rec
        rec["result"] = "ok"; return rec

    pre = worker(pre_py, wd / "pre", row, isolated=isolated); post = worker(post_py, wd / "post", row, isolated=isolated)
    if "error" in (pre.get("status"), post.get("status")):
        rec["result"] = "transpile_error"; return rec
    pre_c, post_c = load_qpy(wd/"pre"/"circuit.qpy"), load_qpy(wd/"post"/"circuit.qpy")
    sem = check_semantic(pre_c, post_c)
    rec["output_oracle_blind"] = (sem.equivalent is True)
    if ch == "global_phase":
        gp = check_global_phase(pre_c, post_c)
        rec["global_phase_delta"] = gp.global_phase_delta
        rec["channel_diverges"] = (gp.equivalent is False)
    elif ch == "contract_metadata":
        res = compare_layout_props(pre.get("layout_props", {}), post.get("layout_props", {}))
        rec["property_divergent_fields"] = res.divergent_fields
        rec["channel_diverges"] = (res.equivalent is False)
    else:
        rec["result"] = f"unknown_channel:{ch}"; return rec
    rec["retro_detected"] = bool(rec.get("channel_diverges")) and bool(rec.get("output_oracle_blind"))
    rec["result"] = "ok"; return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default="data/mining_validation/retro_detect_targets.csv")
    ap.add_argument("--out", default="results/retro_detect")
    ap.add_argument("--only", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    rows = list(csv.DictReader(open(_ROOT / args.targets)))
    if args.only:
        keep = set(args.only.split(",")); rows = [r for r in rows if r["pr"] in keep]
    import time
    out_root = _ROOT / args.out / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    if args.dry_run:
        for r in rows:
            print(f"  PR {r['pr']:>6} [{r['channel']:<17}] {r['pre_version']} -> {r['post_version']}  "
                  f"trigger={r.get('trigger') or r['family']+'/'+r['n']}"
                  f"{'  isolated=' + r['isolated_pass'] if r.get('isolated_pass') else ''}")
        print(f"\n{len(rows)} retro-detection targets. Remove --dry-run to install wheels & run.")
        return 0
    out_root.mkdir(parents=True, exist_ok=True)
    results = [retro_one(r, out_root) for r in rows]
    (out_root / "retro_detect.json").write_text(json.dumps(results, indent=2, default=str))
    det = sum(1 for r in results if r.get("retro_detected"))
    print("\n================ RETRO-DETECTION ================")
    for r in results:
        print(f"  PR {r['pr']:>6} [{r['channel']:<17}] {r.get('result'):<12} retro_detected={r.get('retro_detected')}")
    print(f"\n{det}/{len(results)} mined fixes retro-detected from released wheels (output-invisible).")
    print(f"artifacts: {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
